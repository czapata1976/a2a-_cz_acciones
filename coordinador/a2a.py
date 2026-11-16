"""Cliente A2A del coordinador: envía la pregunta al agente elegido con la clave de ese agente.

La clave va en la cabecera que declare la ficha de cada agente (`X-API-Key`, `X-Agente-Clave` o
`Authorization: Bearer`), incluida `A2A-Version` cuando la anuncia y el agente la acepta. El texto del
agente viaja de vuelta sin tocarlo: el coordinador no reescribe cifras, unidades ni fechas.
"""
from __future__ import annotations

import uuid

import httpx

from canales.a2a import texto_de, variantes_de_cabeceras, version_rechazada
from coordinador.fichas import Ficha


class ErrorAgente(RuntimeError):
    """El agente elegido no respondió o respondió con error."""


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
    variantes = variantes_de_cabeceras(ficha.clave, ficha.cabecera, ficha.prefijo, ficha.version)

    datos = None
    ultimo: object = None
    try:
        async with httpx.AsyncClient(timeout=timeout, trust_env=False) as cliente:
            for cabeceras in variantes:
                respuesta = await cliente.post(ficha.endpoint, json=cuerpo, headers=cabeceras)
                if respuesta.status_code == 401:
                    raise ErrorAgente(f"{ficha.nombre} rechazó la clave del coordinador (401).")
                respuesta.raise_for_status()
                candidato = respuesta.json()
                ultimo = candidato
                if version_rechazada(candidato):
                    continue  # pide otra versión de A2A: se prueba la siguiente variante
                datos = candidato
                break
    except httpx.TimeoutException as error:
        raise ErrorAgente(f"{ficha.nombre} no respondió en {int(timeout)} s.") from error
    except httpx.HTTPStatusError as error:
        raise ErrorAgente(f"{ficha.nombre} respondió HTTP {error.response.status_code}.") from error
    except httpx.HTTPError as error:
        raise ErrorAgente(f"No pude conectar con {ficha.nombre}.") from error
    except ValueError as error:
        raise ErrorAgente(f"{ficha.nombre} devolvió una respuesta que no es JSON.") from error

    if datos is None:
        datos = ultimo
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

    texto_respuesta = texto_de(resultado)
    if not texto_respuesta:
        raise ErrorAgente(f"{ficha.nombre} no devolvió texto.")
    return texto_respuesta
