"""Cliente A2A del coordinador: envía la pregunta al agente elegido con la clave de ese agente.

El texto del agente viaja de vuelta sin tocarlo: el coordinador no reescribe cifras, unidades ni fechas.
"""
from __future__ import annotations

import uuid

import httpx

from coordinador.fichas import Ficha


class ErrorAgente(RuntimeError):
    """El agente elegido no respondió o respondió con error."""


def _texto_de(resultado: dict) -> str:
    """Artefactos, `status.message` o el último turno del agente en el historial.

    Hay servidores que devuelven el texto solo en `status.message` (A2A 0.3.0) y otros en artefactos.
    """
    estado = resultado.get("status") or {}
    candidatos = [resultado.get("artifacts") or [], [estado.get("message") or {}]]
    for grupo in candidatos:
        partes = [
            parte["text"]
            for objeto in grupo
            if isinstance(objeto, dict)
            for parte in objeto.get("parts", [])
            if isinstance(parte, dict) and isinstance(parte.get("text"), str)
        ]
        partes = [p.strip() for p in partes if p.strip()]
        if partes:
            return "\n".join(partes)
    for turno in reversed(resultado.get("history") or []):
        if not isinstance(turno, dict) or str(turno.get("role", "")).lower() not in {"agent", "assistant"}:
            continue
        partes = [
            p["text"].strip()
            for p in turno.get("parts", [])
            if isinstance(p, dict) and isinstance(p.get("text"), str) and p["text"].strip()
        ]
        if partes:
            return "\n".join(partes)
    return ""


async def consultar(ficha: Ficha, texto: str, conversacion: str, timeout: float = 60.0) -> str:
    """Envía `message/send` al agente y devuelve su texto tal cual."""
    cuerpo = {
        "jsonrpc": "2.0",
        "id": uuid.uuid4().hex,
        "method": "message/send",
        "params": {"message": {
            "role": "user",
            "messageId": uuid.uuid4().hex,
            "contextId": conversacion,
            "parts": [{"kind": "text", "text": texto}],
        }},
    }
    cabeceras = {"Accept": "application/json"}
    if ficha.clave:
        cabeceras["X-Agente-Clave"] = ficha.clave

    try:
        async with httpx.AsyncClient(timeout=timeout, trust_env=False) as cliente:
            respuesta = await cliente.post(ficha.endpoint, json=cuerpo, headers=cabeceras)
            if respuesta.status_code == 401:
                raise ErrorAgente(f"{ficha.nombre} rechazó la clave del coordinador (401).")
            respuesta.raise_for_status()
            datos = respuesta.json()
    except httpx.TimeoutException as error:
        raise ErrorAgente(f"{ficha.nombre} no respondió en {int(timeout)} s.") from error
    except httpx.HTTPStatusError as error:
        raise ErrorAgente(f"{ficha.nombre} respondió HTTP {error.response.status_code}.") from error
    except httpx.HTTPError as error:
        raise ErrorAgente(f"No pude conectar con {ficha.nombre}.") from error
    except ValueError as error:
        raise ErrorAgente(f"{ficha.nombre} devolvió una respuesta que no es JSON.") from error

    if not isinstance(datos, dict):
        raise ErrorAgente(f"{ficha.nombre} devolvió una respuesta inesperada.")
    if datos.get("error"):
        detalle = datos["error"].get("message") if isinstance(datos["error"], dict) else ""
        raise ErrorAgente(f"{ficha.nombre} devolvió un error: {detalle or 'sin detalle'}")

    resultado = datos.get("result") or {}
    estado = str((resultado.get("status") or {}).get("state") or "").lower()
    if estado in {"failed", "canceled", "cancelled", "rejected", "error"}:
        mensaje = (resultado.get("status") or {}).get("message") or {}
        detalle = next(
            (p.get("text", "") for p in mensaje.get("parts", []) if isinstance(p, dict)), ""
        )
        raise ErrorAgente(f"{ficha.nombre} no completó la tarea ({estado}). {detalle}".strip())

    texto_respuesta = _texto_de(resultado)
    if not texto_respuesta:
        raise ErrorAgente(f"{ficha.nombre} no devolvió texto.")
    return texto_respuesta
