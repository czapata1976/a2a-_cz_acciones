"""Recibe mensajes de Telegram por long polling, sin túnel ni webhook.

Uso:
    .venv\\Scripts\\python.exe scripts\\telegram_polling.py
    .venv\\Scripts\\python.exe scripts\\telegram_polling.py --quitar-webhook

Un bot solo puede tener un webhook o un polling activo. Por eso, si el bot ya tiene un webhook
(el servicio del grupo lo usa), el script se detiene y lo explica. `--quitar-webhook` lo elimina de
forma explícita: a partir de ese momento ese bot responde por este canal y no por el anterior.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path
from types import SimpleNamespace

import httpx

RAIZ = Path(__file__).resolve().parents[1]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from canales.config import cargar_settings  # noqa: E402
from canales.coordinador import CoordinadorA2A  # noqa: E402
from canales.telegram import enviar_telegram, extraer_mensaje, procesar_mensaje  # noqa: E402

logger = logging.getLogger("canales.telegram_polling")


async def _api(cliente: httpx.AsyncClient, token: str, metodo: str, **datos) -> dict:
    respuesta = await cliente.post(f"https://api.telegram.org/bot{token}/{metodo}", json=datos)
    cuerpo = respuesta.json()
    if not cuerpo.get("ok"):
        raise RuntimeError(f"Telegram rechazó {metodo}: {cuerpo.get('description')}")
    return cuerpo["result"]


async def ejecutar(quitar_webhook: bool) -> int:
    settings = cargar_settings()
    if not settings.telegram_token:
        logger.error("Falta TELEGRAM_TOKEN en .env.")
        return 1

    app = SimpleNamespace(state=SimpleNamespace(
        settings=settings,
        coordinador=CoordinadorA2A(
            settings.coordinador_url, settings.coordinador_clave, settings.timeout
        ),
        enviar_telegram=enviar_telegram,
    ))

    async with httpx.AsyncClient(timeout=60, trust_env=False) as cliente:
        bot = await _api(cliente, settings.telegram_token, "getMe")
        logger.info("Bot @%s autenticado.", bot.get("username"))

        if quitar_webhook:
            await _api(cliente, settings.telegram_token, "deleteWebhook", drop_pending_updates=False)
            logger.info("Webhook eliminado: este bot queda atendido por el polling.")
        else:
            info = await _api(cliente, settings.telegram_token, "getWebhookInfo")
            if info.get("url"):
                logger.error(
                    "El bot tiene un webhook activo (%s). Un bot no puede usar webhook y polling a la vez.\n"
                    "Si quieres que responda este canal, ejecuta de nuevo con --quitar-webhook.",
                    info["url"],
                )
                return 1

        offset = 0
        logger.info("Escuchando mensajes (Ctrl+C para detener)...")
        while True:
            updates = await _api(
                cliente,
                settings.telegram_token,
                "getUpdates",
                offset=offset,
                timeout=25,
                allowed_updates=["message", "edited_message"],
            )
            for update in updates:
                offset = max(offset, int(update.get("update_id", 0)) + 1)
                mensaje = extraer_mensaje(update)
                if mensaje is None:
                    continue
                chat_id, texto = mensaje
                logger.info("Mensaje de chat %s", chat_id)
                await procesar_mensaje(app, chat_id, texto)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    # La URL de la Bot API incluye el token: httpx no debe registrarla.
    for ruidoso in ("httpx", "httpcore"):
        logging.getLogger(ruidoso).setLevel(logging.WARNING)
    parser = argparse.ArgumentParser(description="Telegram por polling para agente_cz_A2A")
    parser.add_argument(
        "--quitar-webhook",
        action="store_true",
        help="elimina el webhook del bot antes de escuchar (afecta a cualquier otro servicio que use el bot)",
    )
    args = parser.parse_args()
    try:
        return asyncio.run(ejecutar(args.quitar_webhook))
    except KeyboardInterrupt:
        logger.info("Polling detenido.")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
