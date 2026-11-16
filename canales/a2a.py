"""Utilidades A2A que comparten los clientes del proyecto.

Vive aparte de cualquier cliente concreto: el chat web y el coordinador leen la misma tarjeta y el
mismo resultado A2A, y así no hay dos versiones de la misma regla.
"""
from __future__ import annotations

CABECERA_CLAVE = "X-Agente-Clave"
"""Cabecera con la que este proyecto pide la clave cuando la ficha no dice otra cosa."""


def texto_de(resultado: dict) -> str:
    """Extrae el texto de un resultado A2A: mensaje, artefactos, `status.message` o historial.

    Se usa la primera fuente que traiga texto, no todas: hay servidores que repiten la misma
    respuesta en los artefactos y en `status.message` y concatenarlas la duplicaría. Algunos
    agentes devuelven un `Message` completo en `result` (con `parts` en la raíz) en vez de una
    `Task`, así que esa forma se lee primero.
    """
    estado = resultado.get("status") or {}
    grupos = []
    if isinstance(resultado.get("parts"), list):
        grupos.append([resultado])
    grupos.append(resultado.get("artifacts") or [])
    if isinstance(estado, dict):
        grupos.append([estado.get("message") or {}])
    grupos.append(
        [
            turno
            for turno in reversed(resultado.get("history") or [])
            if isinstance(turno, dict)
            and str(turno.get("role", "")).lower() in {"agent", "assistant"}
        ][:1]
    )
    for grupo in grupos:
        partes = [
            parte["text"].strip()
            for objeto in grupo
            if isinstance(objeto, dict)
            for parte in (objeto.get("parts") or [])
            if isinstance(parte, dict) and isinstance(parte.get("text"), str) and parte["text"].strip()
        ]
        if partes:
            return "\n".join(partes)
    return ""


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


def _hay_requisitos(datos: dict) -> bool:
    """¿La ficha declara explícitamente qué esquemas exige?"""
    for fuente in ("securityRequirements", "security_requirements", "security"):
        valor = datos.get(fuente)
        if isinstance(valor, list) and valor:
            return True
    return False


def seguridad_de_tarjeta(datos: dict) -> tuple[bool, str, str]:
    """(¿exige clave?, cabecera, prefijo) según cómo la declare la ficha.

    Cubre el A2A actual (`securitySchemes` con `securityRequirements`, como el agente de auditoría
    que usa `X-API-Key`), el formato propio anterior (`authentication.header`, como
    `agente_cz_A2A`) y las fichas que no declaran nada.

    Una ficha que **declara** esquemas pero no declara requisitos los ofrece como opcionales (hay
    agentes así: anuncian `bearer` y responden sin clave). En ese caso no se exige credencial, pero
    se recuerda la cabecera para el caso de que el usuario guarde una.
    """
    declarados = datos.get("securitySchemes") or datos.get("security_schemes") or {}
    if not isinstance(declarados, dict):
        declarados = {}
    requeridos = [nombre for nombre in _nombres_requeridos(datos) if nombre in declarados]
    obligatorio = bool(requeridos) or (_hay_requisitos(datos) and bool(declarados))
    for nombre in requeridos or list(declarados):
        detalle = _detalle_esquema(declarados.get(nombre))
        cabecera, prefijo = _cabecera_de(detalle)
        if cabecera:
            return obligatorio, cabecera, prefijo
        if detalle and obligatorio:  # exige credencial, pero no por cabecera (cookie, OAuth…)
            return True, "", ""

    heredado = datos.get("authentication")
    if isinstance(heredado, dict) and heredado.get("header"):
        return True, str(heredado["header"]), ""
    return False, CABECERA_CLAVE, ""


def endpoint_y_version(datos: dict) -> tuple[str, str]:
    """URL del endpoint y `protocolVersion` de la interfaz que anuncia la ficha."""
    url = str(datos.get("url") or "")
    if url:
        return url, ""
    interfaces = datos.get("supportedInterfaces") or datos.get("supported_interfaces") or []
    for interfaz in interfaces:
        if isinstance(interfaz, dict) and interfaz.get("url"):
            version = interfaz.get("protocolVersion") or interfaz.get("protocol_version") or ""
            return str(interfaz["url"]), str(version)
    return "", ""


def version_rechazada(datos: object) -> bool:
    """El agente contestó que no soporta la versión de A2A que se le anunció."""
    if not isinstance(datos, dict):
        return False
    error = datos.get("error")
    if not isinstance(error, dict):
        return False
    mensaje = str(error.get("message") or "").lower()
    return "version" in mensaje and (
        "not supported" in mensaje or "unsupported" in mensaje or "expected" in mensaje
    )


def variantes_de_cabeceras(
    clave: str, cabecera: str, prefijo: str, version: str
) -> list[dict[str, str]]:
    """Cabeceras de `message/send` aceptables, en orden.

    La ficha anuncia la versión del protocolo (1.0), pero el manejador del agente puede exigir otra
    en la cabecera (`0.3`); si rechaza la anunciada se reintenta con `0.3` y, por último, sin
    `A2A-Version`, que es lo que esperan los servidores que no la usan.
    """
    base: dict[str, str] = {"Accept": "application/json"}
    if version:
        base["A2A-Version"] = version
    if clave and cabecera:
        base[cabecera] = f"{prefijo}{clave}"
    if not version:
        return [base]
    sin_version = {nombre: valor for nombre, valor in base.items() if nombre != "A2A-Version"}
    variantes = [base]
    if version != "0.3":
        variantes.append({**sin_version, "A2A-Version": "0.3"})
    variantes.append(sin_version)
    return variantes


__all__ = [
    "CABECERA_CLAVE",
    "endpoint_y_version",
    "seguridad_de_tarjeta",
    "texto_de",
    "variantes_de_cabeceras",
    "version_rechazada",
]
