"""Aplicación FastAPI de los canales de `agente_cz_A2A`.

Se ejecuta aparte del coordinador y le habla por HTTP: el agente solo responde al coordinador, así
que este servicio no conoce ni su URL ni su clave. Arranque recomendado:

    .venv\\Scripts\\python.exe scripts\\servidor_canales.py

El supervisor levanta esta API en `CANALES_PORT` (8100) y, si `WHATSAPP_HABILITADO=true`, el puente
Node/Baileys en loopback (`WHATSAPP_URL_INTERNA`, 18082).
"""
from __future__ import annotations

import logging

from fastapi import FastAPI

from canales import telegram, whatsapp
from canales.config import Settings, cargar_settings
from canales.coordinador import CoordinadorA2A

logger = logging.getLogger(__name__)

DESCRIPCION = (
    "Canales de conversación del coordinador A2A: webhook de Telegram y mensajes del puente de "
    "WhatsApp. Cada consulta la atiende el coordinador, que elige al agente y cita cuál respondió."
)


def crear_app(settings: Settings | None = None, coordinador: CoordinadorA2A | None = None) -> FastAPI:
    settings = settings or cargar_settings()

    # La URL de la Bot API incluye el token: no debe quedar en los logs de httpx.
    for ruidoso in ("httpx", "httpcore"):
        logging.getLogger(ruidoso).setLevel(logging.WARNING)

    app = FastAPI(
        title="Canales del coordinador A2A",
        description=DESCRIPCION,
        version="1.0.0",
    )
    app.state.settings = settings
    app.state.coordinador = coordinador or CoordinadorA2A(
        settings.coordinador_url, settings.coordinador_clave, settings.timeout
    )
    app.state.enviar_telegram = telegram.enviar_telegram
    app.state.whatsapp_responder = app.state.coordinador.consultar

    app.include_router(telegram.router)
    app.include_router(
        whatsapp.crear_router(
            whatsapp.CanalWhatsApp(
                habilitado=settings.whatsapp_habilitado,
                secreto=settings.whatsapp_secret,
                url_interna=settings.whatsapp_url_interna,
                timeout=settings.whatsapp_timeout,
                max_caracteres=settings.whatsapp_max_caracteres,
                token_operador=settings.canales_token,
            )
        )
    )

    @app.get("/ok", tags=["salud"])
    async def ok() -> dict:
        return {"ok": True, "coordinador": settings.coordinador_url}

    @app.get("/salud", tags=["salud"])
    async def salud() -> dict:
        estado = "desconocido"
        agentes: list[str] = []
        try:
            datos = await app.state.coordinador.estado()
            estado = "disponible"
            agentes = [
                str(agente.get("nombre") or agente.get("estado") or "")
                for agente in (datos.get("agentes") or [])
                if isinstance(agente, dict)
            ]
        except Exception as error:  # noqa: BLE001 - el estado se informa, no se propaga
            logger.warning("Salud: coordinador no disponible (%s)", type(error).__name__)
            estado = "no disponible"
        return {
            "canales": {"telegram": bool(settings.telegram_token), "whatsapp": settings.whatsapp_habilitado},
            "coordinador": {
                "url": settings.coordinador_url,
                "estado": estado,
                "agentes": agentes,
            },
        }

    return app
