"""API del coordinador: `POST /chat` con clave, canal de Telegram y salud.

Arranque:

    .venv\\Scripts\\python.exe scripts\\servidor_coordinador.py

Todo lo que entra (API o canal) pasa por el mismo supervisor: elige un agente, cita cuál respondió y
conserva la memoria por cliente. Sin la clave del coordinador, `/chat` rechaza; sin el secreto, el
endpoint de Telegram rechaza.
"""
from __future__ import annotations

import hmac
import logging
import time
from contextlib import asynccontextmanager

from fastapi import BackgroundTasks, FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from coordinador import canal
from coordinador.config import Settings, cargar_settings
from coordinador.fichas import Ficha, leer_fichas
from coordinador.supervisor import NO_LEIBLE, Supervisor

logger = logging.getLogger("coordinador.api")


class Consulta(BaseModel):
    mensaje: object = Field(default=None, description="Texto de la consulta")
    cliente: str = Field(default="api", max_length=120, description="Identificador de la conversación")


def crear_app(
    settings: Settings | None = None,
    fichas: list[Ficha] | None = None,
    supervisor: Supervisor | None = None,
) -> FastAPI:
    settings = settings or cargar_settings()

    @asynccontextmanager
    async def ciclo(app: FastAPI):
        if fichas is None:
            app.state.fichas = await leer_fichas(settings.agentes)
        else:
            app.state.fichas = fichas
        if supervisor is None:
            app.state.supervisor = Supervisor(app.state.fichas, settings.timeout_agente)
        else:
            app.state.supervisor = supervisor
        app.state.ultima_lectura = (
            0.0 if any(ficha.estado != "disponible" for ficha in app.state.fichas) else time.monotonic()
        )
        logger.info(
            "Coordinador listo con %s agente(s): %s",
            len(app.state.fichas),
            ", ".join(f.nombre for f in app.state.fichas) or "ninguno",
        )
        yield

    app = FastAPI(title="Coordinador A2A del equipo", version="1.0.0", docs_url=None, redoc_url=None,
                  lifespan=ciclo)

    def clave_valida(request: Request) -> bool:
        recibida = (request.headers.get("x-coordinador-clave") or "").strip()
        if not recibida:
            autorizacion = request.headers.get("authorization", "")
            if autorizacion.lower().startswith("bearer "):
                recibida = autorizacion[7:].strip()
        return bool(recibida) and hmac.compare_digest(recibida, settings.clave)

    def secreto_valido(request: Request) -> bool:
        if not settings.telegram_secret:
            return False
        recibido = (request.headers.get("x-telegram-bot-api-secret-token") or "").strip()
        return bool(recibido) and hmac.compare_digest(recibido, settings.telegram_secret)

    REFRESCO_MINIMO = 15.0

    async def refrescar_si_hace_falta(app: FastAPI) -> None:
        """Vuelve a leer las fichas si alguna quedó marcada como no disponible.

        Sin esto, un agente que estaba caído al arrancar el coordinador quedaría descartado para
        siempre, aunque volviera a estar arriba.
        """
        fichas_actuales = getattr(app.state, "fichas", []) or []
        if all(ficha.estado == "disponible" for ficha in fichas_actuales):
            return
        if time.monotonic() - getattr(app.state, "ultima_lectura", 0.0) < REFRESCO_MINIMO:
            return
        try:
            nuevas = await leer_fichas(settings.agentes, timeout=min(8.0, settings.timeout_agente))
        except Exception:  # noqa: BLE001 - se conserva la última lectura
            logger.warning("No pude refrescar las fichas; sigo con la última lectura")
            return
        app.state.fichas = nuevas
        app.state.supervisor.fichas = nuevas
        app.state.ultima_lectura = time.monotonic()
        logger.info("Fichas refrescadas: %s", ", ".join(f"{f.nombre}={f.estado}" for f in nuevas))

    # --- consulta directa por API ----------------------------------------
    @app.post("/chat")
    async def chat(datos: Consulta, request: Request):
        if not clave_valida(request):
            logger.warning("POST /chat rechazado: sin clave válida")
            return JSONResponse(status_code=401, content={"detail": "Falta la clave del coordinador o no es válida."})

        if not isinstance(datos.mensaje, str) or not datos.mensaje.strip():
            return {"respuesta": NO_LEIBLE, "agente": None, "motivo": "no_texto", "saltos": []}

        await refrescar_si_hace_falta(app)
        resultado = await app.state.supervisor.responder(datos.cliente or "api", datos.mensaje.strip())
        if settings.saltos:
            for salto in resultado.saltos:
                logger.info("[salto] %-9s %s", salto["paso"], salto["detalle"])
        return {
            "respuesta": resultado.respuesta,
            "agente": resultado.agente,
            "motivo": resultado.motivo,
            "respuesta_agente": resultado.respuesta_agente,
            "saltos": resultado.saltos,
        }

    # --- canal de Telegram -----------------------------------------------
    @app.post("/telegram")
    async def telegram(request: Request, tareas: BackgroundTasks):
        if not secreto_valido(request):
            logger.warning("POST /telegram rechazado: secreto inválido")
            return JSONResponse(status_code=401, content={"detail": "Secreto del canal inválido."})
        try:
            actualizacion = await request.json()
        except ValueError:
            return JSONResponse(status_code=400, content={"detail": "JSON inválido."})

        mensaje = (actualizacion or {}).get("message") or {}
        chat_id = (mensaje.get("chat") or {}).get("id")
        if chat_id is None:
            return {"ok": True, "ignorado": True}

        clase = canal.tipo_de_mensaje(mensaje)
        if clase == "texto":
            texto = mensaje["text"].strip()
        elif clase == "no_leible":
            texto = ""
        else:
            return {"ok": True, "ignorado": True}

        tareas.add_task(_atender_telegram, app, settings, chat_id, texto, clase)
        return {"ok": True}

    async def _atender_telegram(app: FastAPI, settings: Settings, chat_id, texto: str, clase: str) -> None:
        try:
            if clase != "texto":
                resultado = None
                respuesta = NO_LEIBLE
            else:
                resultado = await app.state.supervisor.responder(f"telegram:{chat_id}", texto)
                respuesta = resultado.respuesta
            if resultado and settings.saltos:
                for salto in resultado.saltos:
                    logger.info("[salto] %-9s %s", salto["paso"], salto["detalle"])
            await canal.enviar(settings.telegram_token, settings.telegram_api_base, chat_id, respuesta)
        except Exception:  # noqa: BLE001 - el webhook ya respondió 200
            logger.exception("Fallo atendiendo el mensaje de Telegram")

    # --- descubrimiento y salud ------------------------------------------
    @app.get("/agentes")
    async def agentes() -> dict:
        return {
            "agentes": [
                {
                    "nombre": ficha.nombre or ficha.url,
                    "url": ficha.url,
                    "endpoint": ficha.endpoint,
                    "estado": ficha.estado,
                    "skills": [str(s.get("name") or s.get("id") or "") for s in ficha.skills],
                }
                for ficha in app.state.fichas
            ]
        }

    @app.post("/agentes/refrescar")
    async def refrescar(request: Request):
        if not clave_valida(request):
            return JSONResponse(status_code=401, content={"detail": "Falta la clave del coordinador."})
        app.state.fichas = await leer_fichas(settings.agentes)
        app.state.supervisor.fichas = app.state.fichas
        return {"agentes": len(app.state.fichas)}

    @app.get("/salud")
    async def salud() -> dict:
        fichas_actuales = getattr(app.state, "fichas", []) or []
        return {
            "ok": True,
            "coordinador": "disponible",
            "agentes": [
                {"nombre": f.nombre or f.url, "estado": f.estado} for f in fichas_actuales
            ],
            "canal_telegram": settings.canal_telegram,
            "memoria": "MemorySaver en proceso, un hilo por cliente (se pierde al reiniciar)",
        }

    @app.get("/ok")
    async def ok() -> dict:
        return {"ok": True}

    @app.get("/")
    async def inicio() -> dict:
        return {
            "servicio": "Coordinador A2A del equipo",
            "chat": "POST /chat con la cabecera X-Coordinador-Clave",
            "canal": "POST /telegram con el secreto de Telegram",
            "salud": "GET /salud",
            "agentes": "GET /agentes",
        }

    return app
