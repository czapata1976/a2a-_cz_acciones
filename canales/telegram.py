"""Canal Telegram: recibe updates y responde con lo que diga el coordinador.

Dos formas de recibir mensajes:

- **Webhook** (`POST /telegram/webhook`): la que usa Telegram en producción; exige
  `TELEGRAM_SECRET` y una URL pública (túnel de Cloudflare).
- **Polling** (`scripts/telegram_polling.py`): útil en local, sin túnel. Requiere que el bot no
  tenga un webhook activo.

`TELEGRAM_ENVIO=log` imprime la respuesta en el log en lugar de enviarla: sirve para probar el
canal sin escribirle a un chat real.
"""
from __future__ import annotations

import logging
import secrets

import httpx
from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Request

from canales.config import Settings
from canales.coordinador import ErrorCoordinador

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/telegram", tags=["telegram"])

LIMITE_TELEGRAM = 4000

MENSAJE_AYUDA = (
    "Hola. Soy el canal Telegram del coordinador A2A: recibo tu consulta y la paso al agente del "
    "equipo que sabe responderla, diciéndote cuál fue.\n\n"
    "Escríbeme una consulta con el ticker y el mercado, por ejemplo:\n"
    "  ¿Cuánto vale AAPL en el mercado US?\n"
    "  Compara NVDA y MSFT en US para un horizonte de 3 años.\n\n"
    "El agente analiza mercado y fundamentales, y dice qué revisar antes de invertir. "
    "No ejecuta pagos ni inversiones, y lo tributario lo deja fuera de su alcance."
)


def extraer_mensaje(update: dict) -> tuple[int, str] | None:
    """Devuelve (chat_id, texto) del update, o None si no es un mensaje de texto."""
    mensaje = update.get("message") or update.get("edited_message")
    if not isinstance(mensaje, dict):
        return None
    texto = mensaje.get("text")
    chat = mensaje.get("chat") or {}
    chat_id = chat.get("id") if isinstance(chat, dict) else None
    if not isinstance(texto, str) or not texto.strip() or chat_id is None:
        return None
    return int(chat_id), texto.strip()


def dividir_texto(texto: str, limite: int = LIMITE_TELEGRAM) -> list[str]:
    """Parte la respuesta en mensajes válidos para Telegram, sin cortar palabras."""
    restante = texto.strip()
    partes: list[str] = []
    while len(restante) > limite:
        corte = restante.rfind("\n", 0, limite)
        if corte < limite // 2:
            corte = restante.rfind(" ", 0, limite)
        if corte < limite // 2:
            corte = limite
        partes.append(restante[:corte].rstrip())
        restante = restante[corte:].lstrip()
    if restante:
        partes.append(restante)
    return partes


async def enviar_telegram(settings: Settings, chat_id: int, texto: str) -> None:
    """Envía la respuesta al chat, o la deja en el log si `TELEGRAM_ENVIO=log`."""
    if settings.telegram_envio == "log":
        logger.info("Telegram (log) chat=%s respuesta=%s", chat_id, texto[:1500])
        return
    if not settings.telegram_token:
        raise RuntimeError("TELEGRAM_TOKEN no configurado.")
    url = f"{settings.telegram_api_base}/bot{settings.telegram_token}/sendMessage"
    async with httpx.AsyncClient(timeout=30, trust_env=False) as cliente:
        for parte in dividir_texto(texto):
            respuesta = await cliente.post(url, json={"chat_id": chat_id, "text": parte})
            respuesta.raise_for_status()


async def procesar_mensaje(app, chat_id: int, texto: str) -> None:
    """Consulta al coordinador y responde; se ejecuta en segundo plano tras el webhook."""
    settings: Settings = app.state.settings

    if texto.lower() in {"/start", "/help", "/ayuda"}:
        respuesta = MENSAJE_AYUDA
    else:
        try:
            respuesta = await app.state.coordinador.consultar(texto, f"telegram:{chat_id}")
        except ErrorCoordinador as error:
            logger.warning("Telegram: %s", error)
            respuesta = f"No pude responder la consulta: {error}"
        except Exception:
            logger.exception("Telegram: error inesperado")
            respuesta = "No pude procesar tu mensaje. Intenta nuevamente en un momento."

    try:
        await app.state.enviar_telegram(settings, chat_id, respuesta)
    except Exception:
        logger.exception("Telegram: no se pudo enviar la respuesta")


@router.post("/webhook")
async def telegram_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    x_telegram_bot_api_secret_token: str | None = Header(default=None),
) -> dict:
    settings: Settings = request.app.state.settings
    if not settings.telegram_token:
        raise HTTPException(status_code=503, detail="TELEGRAM_TOKEN no configurado.")
    if not settings.telegram_secret:
        raise HTTPException(status_code=503, detail="TELEGRAM_SECRET no configurado.")

    recibido = x_telegram_bot_api_secret_token or ""
    if not secrets.compare_digest(
        recibido.encode("utf-8"), settings.telegram_secret.encode("utf-8")
    ):
        raise HTTPException(status_code=403, detail="Secreto de Telegram inválido.")

    try:
        update = await request.json()
    except Exception as error:
        raise HTTPException(status_code=400, detail="El cuerpo no es un update JSON válido.") from error
    if not isinstance(update, dict):
        raise HTTPException(status_code=400, detail="El update debe ser un objeto JSON.")

    mensaje = extraer_mensaje(update)
    if mensaje is None:
        return {"ok": True, "ignorado": True}
    chat_id, texto = mensaje

    background_tasks.add_task(procesar_mensaje, request.app, chat_id, texto)
    return {"ok": True, "chat_id": chat_id}
