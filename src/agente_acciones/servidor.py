"""Servidor A2A propio de `agente_cz_A2A` (FastAPI + JSON-RPC).

Expone lo que pide el taller:

- `GET /.well-known/agent-card.json` — ficha pública con qué hace y qué no, y su `URL_PUBLICA`.
- `GET /salud` — público, informa si el agente y el modelo están listos.
- `POST /a2a` — JSON-RPC `message/send`; exige la clave del agente (`X-Agente-Clave` o
  `Authorization: Bearer`). Sin clave responde 401.

La memoria por conversación vive aquí: el `contextId` de A2A es el `thread_id` del `MemorySaver`, así que
una conversación recuerda sus turnos. Un reinicio del proceso la borra (límite conocido y declarado).

Arranque:

    .venv\\Scripts\\python.exe scripts\\servidor_agente.py
"""
from __future__ import annotations

import hmac
import logging
import os
import time
import uuid

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import MemorySaver

from src.agente_acciones.tarjeta import NOMBRE, construir_tarjeta

logger = logging.getLogger("agente.servidor")

NO_LEIBLE = (
    "No puedo leer ese tipo de mensaje: solo trabajo con texto. Cuéntame en palabras qué acción quieres "
    "analizar (por ejemplo: «analiza NVDA en US para un perfil moderado»)."
)

EJEMPLO_A2A = {
    "jsonrpc": "2.0",
    "id": "1",
    "method": "message/send",
    "params": {
        "message": {
            "role": "user",
            "messageId": "m1",
            "contextId": "ctx-prueba",
            "parts": [{"kind": "text", "text": "Analiza NVDA en US para un perfil moderado a 12 meses."}],
        }
    },
}

# `atender_a2a` recibe el `Request` en crudo (necesita las cabeceras y el JSON sin validar), así que
# FastAPI no describe el cuerpo: esto lo documenta para que Swagger pueda enviarlo.
CUERPO_A2A = {
    "summary": "message/send",
    "description": "Envía una consulta de texto y devuelve la tarea A2A completada. Reutiliza "
                   "`contextId` para que la conversación recuerde sus turnos.",
    "parameters": [{
        "name": "X-Agente-Clave",
        "in": "header",
        "required": False,
        "description": "Clave del agente. También se acepta `Authorization: Bearer <clave>`.",
        "schema": {"type": "string"},
    }],
    "requestBody": {
        "required": True,
        "content": {"application/json": {
            "schema": {
                "type": "object",
                "required": ["jsonrpc", "id", "method", "params"],
                "properties": {
                    "jsonrpc": {"type": "string", "example": "2.0"},
                    "id": {"type": "string", "example": "1"},
                    "method": {"type": "string", "enum": ["message/send"]},
                    "params": {
                        "type": "object",
                        "required": ["message"],
                        "properties": {"message": {
                            "type": "object",
                            "required": ["role", "messageId", "parts"],
                            "properties": {
                                "role": {"type": "string", "enum": ["user", "agent"]},
                                "messageId": {"type": "string", "example": "m1"},
                                "contextId": {"type": "string", "example": "ctx-prueba",
                                              "description": "Hilo de la conversación (memoria del agente)."},
                                "parts": {
                                    "type": "array",
                                    "items": {
                                        "type": "object",
                                        "required": ["kind", "text"],
                                        "properties": {
                                            "kind": {"type": "string", "enum": ["text"]},
                                            "text": {"type": "string"},
                                        },
                                    },
                                },
                            },
                        }},
                    },
                },
            },
            "example": EJEMPLO_A2A,
        }},
    },
}


def _clave_configurada() -> str:
    return (os.environ.get("AGENTE_CLAVE") or "").strip()


def _docs_habilitados() -> bool:
    """`AGENTE_DOCS=true` publica `/docs` y `/redoc` para probar a mano; apagado por defecto."""
    return (os.environ.get("AGENTE_DOCS") or "").strip().lower() in {"1", "true", "si", "sí", "yes", "on"}


def _url_publica(request: Request) -> str:
    """`URL_PUBLICA` si está definida; si no, la dirección con la que llegó la petición."""
    fija = (os.environ.get("URL_PUBLICA") or "").strip().rstrip("/")
    if fija:
        return fija
    esquema = request.headers.get("x-forwarded-proto", request.url.scheme).split(",")[0].strip()
    host = request.headers.get("x-forwarded-host", request.headers.get("host", request.url.netloc))
    return f"{esquema}://{host}".rstrip("/")


def _texto_de_parte(partes: object) -> str | None:
    """Primer texto del mensaje; `None` si no hay texto (foto, sticker, audio, dato)."""
    if not isinstance(partes, list):
        return None
    for parte in partes:
        if isinstance(parte, dict) and parte.get("kind") == "text" and isinstance(parte.get("text"), str):
            texto = parte["text"].strip()
            if texto:
                return texto
    return None


def _mensaje(rol: str, texto: str, context_id: str) -> dict:
    return {"kind": "message", "role": rol, "messageId": uuid.uuid4().hex, "contextId": context_id,
            "parts": [{"kind": "text", "text": texto}]}


def crear_app(agente=None) -> FastAPI:
    """Construye la app. `agente` se inyecta en las pruebas; en producción se arma con `crear_agente`."""
    if agente is None:
        from src.agente_acciones.graph import crear_agente

        agente = crear_agente(MemorySaver())

    app = FastAPI(
        title=f"A2A {NOMBRE}",
        description="Servidor A2A del agente. `message/send` exige la clave; `/docs` solo se publica "
                    "con `AGENTE_DOCS=true`.",
        version="1.0.0",
        docs_url="/docs" if _docs_habilitados() else None,
        redoc_url="/redoc" if _docs_habilitados() else None,
    )
    app.state.agente = agente

    @app.middleware("http")
    async def utf8(request: Request, llamar):
        """Declara `charset=utf-8` en el JSON: sin eso, PowerShell y otros clientes lo leen como latin-1."""
        respuesta = await llamar(request)
        tipo = respuesta.headers.get("content-type", "")
        if tipo.startswith("application/json") and "charset" not in tipo:
            respuesta.headers["content-type"] = f"{tipo}; charset=utf-8"
        return respuesta

    def clave_valida(request: Request) -> bool:
        esperada = _clave_configurada()
        if not esperada:
            return False  # sin clave configurada no se atiende: falla cerrado
        recibida = (request.headers.get("x-agente-clave") or "").strip()
        if not recibida:
            autorizacion = request.headers.get("authorization", "")
            if autorizacion.lower().startswith("bearer "):
                recibida = autorizacion[7:].strip()
        return bool(recibida) and hmac.compare_digest(recibida, esperada)

    @app.get("/.well-known/agent-card.json")
    async def tarjeta(request: Request) -> JSONResponse:
        return JSONResponse(construir_tarjeta(_url_publica(request)))

    @app.get("/salud")
    async def salud() -> dict:
        return {
            "ok": True,
            "agente": NOMBRE,
            "estado": "disponible",
            "clave_configurada": bool(_clave_configurada()),
            "modelo": os.environ.get("MODELO", "gemini-3.5-flash-lite"),
            "memoria": "MemorySaver en proceso (se pierde al reiniciar)",
        }

    @app.get("/ok")
    async def ok() -> dict:
        return {"ok": True, "agente": NOMBRE}

    async def atender_a2a(request: Request):
        if not clave_valida(request):
            logger.warning("Mensaje A2A rechazado: sin clave válida")
            return JSONResponse(
                status_code=401,
                content={"error": {"code": -32001, "message": "Falta la clave del agente o no es válida."}},
            )
        try:
            cuerpo = await request.json()
        except ValueError:
            return JSONResponse(status_code=400, content={"error": {"code": -32700, "message": "JSON inválido."}})

        if not isinstance(cuerpo, dict) or cuerpo.get("method") != "message/send":
            return JSONResponse(
                status_code=200,
                content={"jsonrpc": "2.0", "id": cuerpo.get("id") if isinstance(cuerpo, dict) else None,
                         "error": {"code": -32601, "message": "Método no soportado: usa message/send."}},
            )

        mensaje = (cuerpo.get("params") or {}).get("message") or {}
        context_id = str(mensaje.get("contextId") or uuid.uuid4())
        texto = _texto_de_parte(mensaje.get("parts"))

        if texto is None:
            respuesta = NO_LEIBLE
        else:
            try:
                estado = await app.state.agente.ainvoke(
                    {"messages": [HumanMessage(content=texto)]},
                    {"configurable": {"thread_id": context_id}},
                )
                respuesta = _ultimo_texto(estado)
            except Exception as error:  # noqa: BLE001 - se informa como tarea fallida
                logger.exception("Fallo al ejecutar el agente")
                return JSONResponse(
                    status_code=200,
                    content={
                        "jsonrpc": "2.0", "id": cuerpo.get("id"),
                        "result": {
                            "kind": "task", "id": str(uuid.uuid4()), "contextId": context_id,
                            "status": {"state": "failed", "timestamp": _ahora(),
                                       "message": _mensaje("agent", f"No pude completar la consulta: {error}", context_id)},
                            "artifacts": [],
                        },
                    },
                )

        return JSONResponse(
            status_code=200,
            content={
                "jsonrpc": "2.0", "id": cuerpo.get("id"),
                "result": {
                    "kind": "task",
                    "id": str(uuid.uuid4()),
                    "contextId": context_id,
                    "status": {"state": "completed", "timestamp": _ahora(),
                               "message": _mensaje("agent", respuesta, context_id)},
                    "artifacts": [{
                        "artifactId": uuid.uuid4().hex,
                        "name": "respuesta",
                        "parts": [{"kind": "text", "text": respuesta}],
                    }],
                },
            },
        )

    app.post("/a2a", openapi_extra=CUERPO_A2A)(atender_a2a)
    app.post("/a2a/{identificador}", include_in_schema=False)(atender_a2a)
    return app


def _ahora() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _ultimo_texto(estado: dict) -> str:
    """Último mensaje del agente en el estado devuelto por el grafo."""
    mensajes = estado.get("messages") or []
    for mensaje in reversed(mensajes):
        if getattr(mensaje, "type", "") in {"ai", "assistant"}:
            contenido = mensaje.content
            if isinstance(contenido, str) and contenido.strip():
                return contenido.strip()
            if isinstance(contenido, list):
                trozos = [p.get("text", "") for p in contenido if isinstance(p, dict)]
                unido = "\n".join(t for t in trozos if t).strip()
                if unido:
                    return unido
    return "No pude generar una respuesta."
