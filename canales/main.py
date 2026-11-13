"""Aplicación FastAPI de los canales de `agente_cz_A2A`.

Se ejecuta aparte del servidor del agente y habla con él por A2A. Arranque recomendado:

    .venv\\Scripts\\python.exe scripts\\servidor_canales.py

El supervisor levanta esta API en `CANALES_PORT` (8100) y, si `WHATSAPP_HABILITADO=true`, el puente
Node/Baileys en loopback (`WHATSAPP_URL_INTERNA`, 18082).
"""
from __future__ import annotations

import logging

from fastapi import FastAPI

from canales import telegram, whatsapp
from canales.agente import AgenteA2A
from canales.config import Settings, cargar_settings

logger = logging.getLogger(__name__)

DESCRIPCION = (
    "Canales de conversación del servicio A2A agente_cz_A2A: webhook de Telegram y mensajes del "
    "puente de WhatsApp. Las respuestas las genera el agente en su propio proceso."
)


def crear_app(settings: Settings | None = None, agente: AgenteA2A | None = None) -> FastAPI:
    settings = settings or cargar_settings()

    # La URL de la Bot API incluye el token: no debe quedar en los logs de httpx.
    for ruidoso in ("httpx", "httpcore"):
        logging.getLogger(ruidoso).setLevel(logging.WARNING)

    app = FastAPI(
        title="Canales de agente_cz_A2A",
        description=DESCRIPCION,
        version="1.0.0",
    )
    app.state.settings = settings
    app.state.agente = agente or AgenteA2A(
        settings.a2a_url, settings.a2a_graph, settings.a2a_timeout
    )
    app.state.enviar_telegram = telegram.enviar_telegram

    app.include_router(telegram.router)
    app.include_router(whatsapp.router)

    @app.get("/ok", tags=["salud"])
    async def ok() -> dict:
        return {"ok": True, "agente": settings.a2a_graph}

    @app.get("/salud", tags=["salud"])
    async def salud() -> dict:
        estado_agente = "desconocido"
        try:
            await app.state.agente.assistant_id()
            estado_agente = "disponible"
        except Exception as error:  # noqa: BLE001 - el estado se informa, no se propaga
            logger.warning("Salud: agente no disponible (%s)", type(error).__name__)
            estado_agente = "no disponible"
        return {
            "canales": {"telegram": bool(settings.telegram_token), "whatsapp": settings.whatsapp_habilitado},
            "agente": {"nombre": settings.a2a_graph, "url": settings.a2a_url, "estado": estado_agente},
        }

    return app
