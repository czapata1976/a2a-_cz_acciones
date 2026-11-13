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

from canales.agente import texto_de

RUTA_TARJETA = "/.well-known/agent-card.json"


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
    """Usa el host y el esquema con que entró el usuario, y la ruta que anuncia la tarjeta.

    Hay dos casos reales: un agente publicado por túnel anuncia su `127.0.0.1` (host equivocado) y un
    agente en Cloud Run anuncia `http://` aunque se le hable por HTTPS (esquema equivocado). En ambos
    manda la URL que escribió el usuario; la tarjeta solo aporta la ruta del endpoint.
    """
    anfitrion = urlsplit(base)
    anunciada = urlsplit(url_tarjeta)
    return urlunsplit((anfitrion.scheme, anfitrion.netloc, anunciada.path or "/", anunciada.query, ""))


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
    if not url:
        interfaces = datos.get("supportedInterfaces") or datos.get("supported_interfaces") or []
        for interfaz in interfaces:
            if isinstance(interfaz, dict) and interfaz.get("url"):
                url = str(interfaz["url"])
                break
    if not url:
        raise ErrorAgenteRemoto("La tarjeta A2A no anuncia el endpoint de mensajes.")

    return Agente(
        base=base,
        nombre=str(datos.get("name") or base),
        url_a2a=_url_reenviada(base, url),
        assistant_id=assistant_id,
        descripcion=str(datos.get("description") or ""),
        clave=clave,
        habilidades=_habilidades_de_tarjeta(datos),
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
    )


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
    cabeceras = {"Accept": "application/json"}
    if agente.clave:
        cabeceras["X-Agente-Clave"] = agente.clave
    try:
        async with httpx.AsyncClient(timeout=timeout, trust_env=False) as cliente:
            respuesta = await cliente.post(agente.url_a2a, json=cuerpo, headers=cabeceras)
            respuesta.raise_for_status()
            datos = respuesta.json()
    except httpx.TimeoutException as error:
        raise ErrorAgenteRemoto(f"{agente.nombre} agotó el tiempo de respuesta.") from error
    except httpx.HTTPStatusError as error:
        raise ErrorAgenteRemoto(
            f"{agente.nombre} respondió HTTP {error.response.status_code}."
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


__all__ = ["Agente", "ErrorAgenteRemoto", "descubrir", "enviar", "normalizar_url"]
