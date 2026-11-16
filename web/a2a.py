"""Cliente A2A del chat web: descubre agentes por su tarjeta y les envía tareas.

Sirve para cualquier agente que publique `/.well-known/agent-card.json`. Cuando el servidor es
`langgraph dev` la tarjeta exige `assistant_id`, así que primero se busca el asistente en
`/assistants/search`. La URL de la tarjeta se reescribe al host que el usuario escribió: un agente
publicado por túnel anuncia su `127.0.0.1` y ese host solo existe en su propia máquina.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit

import httpx

from canales.a2a import texto_de

RUTA_TARJETA = "/.well-known/agent-card.json"

CABECERA_CLAVE = "X-Agente-Clave"
"""Cabecera con la que este proyecto pide la clave cuando la ficha no dice otra cosa."""


class ErrorAgenteRemoto(RuntimeError):
    """No se pudo descubrir o consultar el agente indicado."""


@dataclass(frozen=True)
class Agente:
    """Un agente listo para recibir `message/send`."""

    base: str
    nombre: str
    url_a2a: str
    assistant_id: str | None
    descripcion: str = ""
    clave: str = ""
    habilidades: tuple[str, ...] = ()
    requiere_clave: bool = False
    """La ficha declara que `message/send` exige credencial."""
    cabecera_clave: str = CABECERA_CLAVE
    """Cabecera donde la ficha pide la clave (``Authorization`` si es Bearer)."""
    prefijo_clave: str = ""
    """Texto que precede a la clave, por ejemplo ``Bearer ``."""
    version_protocolo: str = ""
    """`protocolVersion` de la interfaz declarada; se envía como ``A2A-Version``."""


def normalizar_url(url: str) -> str:
    """Valida la URL de un agente y la deja sin barra final."""
    limpio = (url or "").strip()
    partes = urlsplit(limpio)
    if partes.scheme not in {"http", "https"}:
        raise ErrorAgenteRemoto("La URL debe empezar con http:// o https://.")
    if not partes.hostname:
        raise ErrorAgenteRemoto("La URL debe incluir el host del agente.")
    if partes.username or partes.password:
        raise ErrorAgenteRemoto("La URL no debe llevar usuario ni clave.")
    if partes.fragment or partes.query:
        raise ErrorAgenteRemoto("La URL no debe llevar parámetros ni fragmentos.")
    return urlunsplit((partes.scheme, partes.netloc, partes.path.rstrip("/"), "", ""))


def ruta_de_usuario(url: str) -> str:
    """Ruta que escribió el usuario, o vacía si pegó la raíz o la propia ficha.

    Sirve para respetar `https://host/a2a/<uuid>` sin convertir `…/.well-known/agent-card.json`
    (la ficha, que también se comparte) en el endpoint de mensajes.
    """
    ruta = urlsplit(url).path.rstrip("/")
    return "" if ruta.endswith(RUTA_TARJETA) else ruta


def _url_reenviada(base: str, url_tarjeta: str) -> str:
    """Usa el host con que entró el usuario y la ruta que anuncia la tarjeta.

    Hay dos casos reales: un agente publicado por túnel anuncia su `127.0.0.1` (host equivocado) y un
    agente en Cloud Run anuncia `http://` aunque se le hable por HTTPS (esquema equivocado). En ambos
    manda la URL que escribió el usuario. El esquema nunca baja a `http` si alguna de las dos dice
    `https`: la clave viajaría sin cifrar.
    """
    anfitrion = urlsplit(base)
    anunciada = urlsplit(url_tarjeta)
    esquema = "https" if "https" in {anfitrion.scheme, anunciada.scheme} else anfitrion.scheme
    return urlunsplit((esquema, anfitrion.netloc, anunciada.path or "/", anunciada.query, ""))


def _detalle_esquema(esquema: object) -> dict:
    """Aplana las dos formas en que una ficha A2A anida un esquema de seguridad."""
    if not isinstance(esquema, dict):
        return {}
    for anidado in ("apiKeySecurityScheme", "httpSecurityScheme", "bearerSecurityScheme"):
        if isinstance(esquema.get(anidado), dict):
            return esquema[anidado]
    return esquema


def _nombres_requeridos(datos: dict) -> list[str]:
    """Nombres de los esquemas que la ficha exige (`securityRequirements`/`security`)."""
    nombres: list[str] = []
    requisitos: list = []
    for fuente in ("securityRequirements", "security_requirements", "security"):
        valor = datos.get(fuente)
        if isinstance(valor, list):
            requisitos.extend(valor)
    for requisito in requisitos:
        if not isinstance(requisito, dict):
            continue
        esquemas = requisito.get("schemes") or requisito
        if isinstance(esquemas, dict):
            nombres.extend(str(nombre) for nombre in esquemas)
        elif isinstance(esquemas, list):
            nombres.extend(str(nombre) for nombre in esquemas if isinstance(nombre, str))
    return nombres


def _cabecera_de(detalle: dict) -> tuple[str, str]:
    """(cabecera, prefijo) del esquema, o `("", "")` si no se autentica por cabecera."""
    tipo = str(detalle.get("type") or "").lower()
    mecanismo = str(detalle.get("scheme") or "").lower()
    if tipo == "http" or mecanismo in {"bearer", "basic"}:
        return ("Authorization", "Bearer ") if mecanismo == "bearer" else ("", "")
    if tipo == "apikey" or detalle.get("name"):
        if str(detalle.get("location") or "header").lower() != "header":
            return "", ""
        return str(detalle.get("name") or CABECERA_CLAVE), ""
    return "", ""


def _esquema_de_clave(datos: dict) -> tuple[bool, str, str]:
    """(¿exige clave?, cabecera, prefijo) según cómo la declare la ficha.

    Cubre el A2A actual (`securitySchemes` con `securityRequirements`, como el agente de
    auditoría que usa `X-API-Key`), el formato propio anterior (`authentication.header`, como
    `agente_cz_A2A`) y las fichas que no declaran nada.
    """
    declarados = datos.get("securitySchemes") or datos.get("security_schemes") or {}
    if not isinstance(declarados, dict):
        declarados = {}
    requeridos = [nombre for nombre in _nombres_requeridos(datos) if nombre in declarados]
    for nombre in requeridos or list(declarados):
        detalle = _detalle_esquema(declarados.get(nombre))
        cabecera, prefijo = _cabecera_de(detalle)
        if cabecera:
            return True, cabecera, prefijo
        if detalle:  # exige credencial, pero no por cabecera (cookie, OAuth…)
            return True, "", ""

    heredado = datos.get("authentication")
    if isinstance(heredado, dict) and heredado.get("header"):
        return True, str(heredado["header"]), ""
    return False, CABECERA_CLAVE, ""


def _habilidades_de_tarjeta(datos: dict) -> tuple[str, ...]:
    """Skills de la ficha (nombre, para qué sirve y etiquetas), en una línea cada una."""
    habilidades: list[str] = []
    for habilidad in datos.get("skills") or []:
        if not isinstance(habilidad, dict):
            continue
        nombre = str(habilidad.get("name") or "").strip()
        descripcion = str(habilidad.get("description") or "").strip()
        etiquetas = [str(etiqueta).strip() for etiqueta in (habilidad.get("tags") or []) if str(etiqueta).strip()]
        texto = ": ".join(parte for parte in (nombre, descripcion) if parte)
        if etiquetas:
            texto = f"{texto} [{', '.join(etiquetas)}]" if texto else f"[{', '.join(etiquetas)}]"
        if texto:
            habilidades.append(texto)
    return tuple(habilidades)


def _agente_de_tarjeta(datos: object, base: str, assistant_id: str | None, clave: str = "") -> Agente:
    if not isinstance(datos, dict):
        raise ErrorAgenteRemoto("La tarjeta A2A no es un objeto JSON.")

    url = str(datos.get("url") or "")
    version_protocolo = ""
    if not url:
        interfaces = datos.get("supportedInterfaces") or datos.get("supported_interfaces") or []
        for interfaz in interfaces:
            if isinstance(interfaz, dict) and interfaz.get("url"):
                url = str(interfaz["url"])
                version_protocolo = str(
                    interfaz.get("protocolVersion") or interfaz.get("protocol_version") or ""
                )
                break
    if not url:
        raise ErrorAgenteRemoto("La tarjeta A2A no anuncia el endpoint de mensajes.")

    requiere_clave, cabecera_clave, prefijo_clave = _esquema_de_clave(datos)
    return Agente(
        base=base,
        nombre=str(datos.get("name") or base),
        url_a2a=_url_reenviada(base, url),
        assistant_id=assistant_id,
        descripcion=str(datos.get("description") or ""),
        clave=clave,
        habilidades=_habilidades_de_tarjeta(datos),
        requiere_clave=requiere_clave,
        cabecera_clave=cabecera_clave,
        prefijo_clave=prefijo_clave,
        version_protocolo=version_protocolo,
    )


async def descubrir(base: str, timeout: float = 15.0, clave: str = "") -> Agente:
    """Lee la tarjeta del agente y devuelve su endpoint A2A.

    Acepta la raíz del servicio (`https://host`) o el endpoint que suele compartirse
    (`https://host/a2a/<uuid>`): la tarjeta siempre se busca en la raíz y, si el usuario pegó una
    ruta, se respeta como endpoint.
    """
    objetivo = normalizar_url(base)
    partes = urlsplit(objetivo)
    raiz = urlunsplit((partes.scheme, partes.netloc, "", "", ""))
    ruta_usuario = ruta_de_usuario(objetivo)
    try:
        async with httpx.AsyncClient(timeout=timeout, trust_env=False, follow_redirects=True) as cliente:
            try:
                buscados = await cliente.post(f"{raiz}/assistants/search", json={})
                if buscados.status_code < 400:
                    asistentes = buscados.json()
                    if isinstance(asistentes, list) and asistentes:
                        identificador = str(asistentes[0].get("assistant_id") or "")
                        if identificador:
                            tarjeta = await cliente.get(
                                f"{raiz}{RUTA_TARJETA}", params={"assistant_id": identificador}
                            )
                            tarjeta.raise_for_status()
                            return _con_ruta(
                                _agente_de_tarjeta(tarjeta.json(), raiz, identificador, clave), raiz, ruta_usuario
                            )
            except (httpx.HTTPError, ValueError, AttributeError):
                pass  # no es un servidor con catálogo de asistentes: se prueba A2A estándar

            tarjeta = await cliente.get(f"{raiz}{RUTA_TARJETA}")
            tarjeta.raise_for_status()
            return _con_ruta(_agente_de_tarjeta(tarjeta.json(), raiz, None, clave), raiz, ruta_usuario)
    except httpx.TimeoutException as error:
        raise ErrorAgenteRemoto(f"{base} no respondió a tiempo.") from error
    except httpx.HTTPStatusError as error:
        raise ErrorAgenteRemoto(
            f"{base} no publica una tarjeta A2A (HTTP {error.response.status_code}). "
            "Revisa que la URL sea la raíz del servicio y que esté arriba."
        ) from error
    except httpx.HTTPError as error:
        raise ErrorAgenteRemoto(f"No pude conectar con {base}: revisa la URL y la red.") from error
    except ValueError as error:
        raise ErrorAgenteRemoto(f"{base} devolvió una tarjeta A2A que no es JSON.") from error


def _con_ruta(agente: Agente, raiz: str, ruta_usuario: str) -> Agente:
    """Si el usuario pegó el endpoint directo, se usa esa ruta en lugar de la anunciada."""
    if not ruta_usuario:
        return agente
    return Agente(
        base=agente.base,
        nombre=agente.nombre,
        url_a2a=f"{raiz}{ruta_usuario}",
        assistant_id=agente.assistant_id,
        descripcion=agente.descripcion,
        clave=agente.clave,
        habilidades=agente.habilidades,
        requiere_clave=agente.requiere_clave,
        cabecera_clave=agente.cabecera_clave,
        prefijo_clave=agente.prefijo_clave,
        version_protocolo=agente.version_protocolo,
    )


def cabeceras_de(agente: Agente) -> dict[str, str]:
    """Cabeceras de `message/send`: la clave viaja donde la ficha dice que va."""
    cabeceras = {"Accept": "application/json"}
    if agente.version_protocolo:
        cabeceras["A2A-Version"] = agente.version_protocolo
    if agente.clave and agente.cabecera_clave:
        cabeceras[agente.cabecera_clave] = f"{agente.prefijo_clave}{agente.clave}"
    return cabeceras


def _destinos(agente: Agente) -> list[str]:
    """Endpoints a probar: el anunciado y, si el esquema difiere, el que escribió el usuario.

    La ficha aporta la ruta y el usuario el host. Se prefiere `https` para que la clave no viaje
    sin cifrar; si ese host solo escucha en `http` (un servidor de desarrollo, por ejemplo), el
    segundo intento conserva la URL escrita.
    """
    destinos = [agente.url_a2a]
    escrito = urlsplit(agente.base)
    anunciado = urlsplit(agente.url_a2a)
    if escrito.scheme != anunciado.scheme:
        destinos.append(
            urlunsplit((escrito.scheme, anunciado.netloc, anunciado.path, anunciado.query, ""))
        )
    return destinos


async def enviar(agente: Agente, texto: str, context_id: str, timeout: float = 180.0) -> str:
    """Envía la tarea por `message/send` y devuelve el texto de la respuesta."""
    cuerpo = {
        "jsonrpc": "2.0",
        "id": uuid.uuid4().hex,
        "method": "message/send",
        "params": {"message": {
            "role": "user",
            "messageId": uuid.uuid4().hex,
            "contextId": context_id,
            "parts": [{"kind": "text", "text": texto}],
        }},
    }
    destinos = _destinos(agente)
    datos = None
    try:
        async with httpx.AsyncClient(timeout=timeout, trust_env=False) as cliente:
            for destino in destinos:
                try:
                    respuesta = await cliente.post(
                        destino, json=cuerpo, headers=cabeceras_de(agente)
                    )
                    respuesta.raise_for_status()
                    datos = respuesta.json()
                    break
                except httpx.ConnectError:
                    if destino == destinos[-1]:
                        raise
                    continue
    except httpx.TimeoutException as error:
        raise ErrorAgenteRemoto(f"{agente.nombre} agotó el tiempo de respuesta.") from error
    except httpx.HTTPStatusError as error:
        codigo = error.response.status_code
        if codigo in {401, 403}:
            donde = agente.cabecera_clave or "la cabecera que declara su ficha"
            raise ErrorAgenteRemoto(
                f"{agente.nombre} respondió HTTP {codigo}: revisa la clave del agente "
                f"(va en {donde})."
            ) from error
        raise ErrorAgenteRemoto(
            f"{agente.nombre} respondió HTTP {codigo}."
        ) from error
    except httpx.HTTPError as error:
        raise ErrorAgenteRemoto(f"No pude comunicarme con {agente.nombre}.") from error
    except ValueError as error:
        raise ErrorAgenteRemoto(f"{agente.nombre} devolvió una respuesta que no es JSON.") from error

    if not isinstance(datos, dict):
        raise ErrorAgenteRemoto(f"{agente.nombre} devolvió una respuesta inesperada.")
    if datos.get("error"):
        detalle = (datos.get("error") or {}).get("message") if isinstance(datos["error"], dict) else ""
        raise ErrorAgenteRemoto(f"{agente.nombre} devolvió un error A2A: {detalle or 'sin detalle'}")
    resultado = datos.get("result")
    if not isinstance(resultado, dict):
        raise ErrorAgenteRemoto(f"{agente.nombre} no devolvió un resultado A2A válido.")

    estado = str((resultado.get("status") or {}).get("state") or "").lower()
    if estado in {"failed", "canceled", "cancelled", "rejected", "error"}:
        raise ErrorAgenteRemoto(f"{agente.nombre} no completó la tarea (estado: {estado}).")

    texto_respuesta = texto_de(resultado)
    if not texto_respuesta:
        raise ErrorAgenteRemoto(f"{agente.nombre} no devolvió texto.")
    return texto_respuesta


__all__ = ["Agente", "ErrorAgenteRemoto", "cabeceras_de", "descubrir", "enviar", "normalizar_url"]
