"""Consulta o cambia el webhook de Telegram del canal.

Uso:
    .venv\\Scripts\\python.exe scripts\\configurar_telegram.py
    .venv\\Scripts\\python.exe scripts\\configurar_telegram.py --url https://<algo>.trycloudflare.com
    .venv\\Scripts\\python.exe scripts\\configurar_telegram.py --quitar

Sin argumentos muestra el estado del bot y del webhook. Con `--url` registra
`<url>/telegram/webhook` y el secreto de `TELEGRAM_SECRET`; con `--quitar` elimina el webhook
(útil antes de usar `scripts/telegram_polling.py`).

Un bot solo puede tener un webhook: si el mismo bot lo usa otro servicio, este comando lo reemplaza.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import httpx

RAIZ = Path(__file__).resolve().parents[1]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from canales.config import cargar_settings  # noqa: E402


def _api(cliente: httpx.Client, base: str, token: str, metodo: str, **datos) -> dict:
    respuesta = cliente.post(f"{base}/bot{token}/{metodo}", json=datos or None)
    cuerpo = respuesta.json()
    if not cuerpo.get("ok"):
        raise SystemExit(f"Telegram rechazó {metodo}: {cuerpo.get('description')}")
    return cuerpo["result"]


def main() -> int:
    parser = argparse.ArgumentParser(description="Webhook de Telegram para agente_cz_A2A")
    grupo = parser.add_mutually_exclusive_group()
    grupo.add_argument("--url", help="URL pública del túnel; se registra <url>/telegram/webhook")
    grupo.add_argument("--quitar", action="store_true", help="elimina el webhook actual")
    args = parser.parse_args()

    settings = cargar_settings()
    if not settings.telegram_token:
        print("Falta TELEGRAM_TOKEN en .env.")
        return 1

    with httpx.Client(timeout=30, trust_env=False) as cliente:
        bot = _api(cliente, settings.telegram_api_base, settings.telegram_token, "getMe")
        print(f"Bot: @{bot.get('username')} ({bot.get('id')})")

        if args.quitar:
            _api(cliente, settings.telegram_api_base, settings.telegram_token, "deleteWebhook", drop_pending_updates=False)
            print("Webhook eliminado. El bot queda libre para polling.")
            return 0

        if args.url:
            if not settings.telegram_secret:
                print("Falta TELEGRAM_SECRET en .env: Telegram no validaría el webhook.")
                return 1
            destino = args.url.rstrip("/") + "/telegram/webhook"
            _api(
                cliente,
                settings.telegram_api_base,
                settings.telegram_token,
                "setWebhook",
                url=destino,
                secret_token=settings.telegram_secret,
                allowed_updates=["message", "edited_message"],
            )
            print(f"Webhook registrado: {destino}")
        info = _api(cliente, settings.telegram_api_base, settings.telegram_token, "getWebhookInfo")
        print(f"Webhook actual: {info.get('url') or '(ninguno)'}")
        if info.get("last_error_message"):
            print(f"Último error de Telegram: {info['last_error_message']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
