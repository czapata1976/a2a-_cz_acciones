"""Supervisor de los canales: FastAPI y, si est? habilitado, el puente de WhatsApp.

Un solo comando arranca los dos procesos:

    .venv\\Scripts\\python.exe scripts\\servidor_canales.py

Si el puente no puede arrancar (Node o dependencias faltantes), la API de canales sigue disponible
y `/salud` informa que WhatsApp no est? operativo. El agente A2A debe estar corriendo aparte.
"""
from __future__ import annotations

import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from canales import puente as puente_whatsapp  # noqa: E402
from canales.config import ConfiguracionInvalida, Settings, cargar_settings  # noqa: E402

logger = logging.getLogger("canales.supervisor")


def _configurar_registro() -> None:
    nivel = os.environ.get("LOG_LEVEL", "INFO").upper()
    formato = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    raiz = logging.getLogger()
    raiz.setLevel(nivel)
    consola = logging.StreamHandler(sys.stdout)
    consola.setFormatter(formato)
    raiz.addHandler(consola)
    carpeta = RAIZ / "logs"
    carpeta.mkdir(parents=True, exist_ok=True)
    archivo = RotatingFileHandler(
        carpeta / "canales.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8"
    )
    archivo.setFormatter(formato)
    raiz.addHandler(archivo)
    for ruidoso in ("httpx", "httpcore"):
        logging.getLogger(ruidoso).setLevel(logging.WARNING)


def main() -> int:
    _configurar_registro()
    try:
        settings = cargar_settings()
    except ConfiguracionInvalida as error:
        logger.error("Configuraci?n inv?lida: %s", error)
        return 1

    logger.info("Canales en http://%s:%s ? agente A2A %s (%s)", settings.host, settings.port, settings.a2a_graph, settings.a2a_url)
    logger.info("Telegram: %s", "listo (webhook)" if settings.telegram_token else "sin TELEGRAM_TOKEN")
    logger.info("WhatsApp: %s", "habilitado" if settings.whatsapp_habilitado else "deshabilitado")

    proceso = None
    if settings.whatsapp_habilitado:
        proceso = puente_whatsapp.arrancar(
            secreto=settings.whatsapp_secret,
            url_interna=settings.whatsapp_url_interna,
            backend_url=f"http://127.0.0.1:{settings.port}/whatsapp/mensaje",
            timeout_s=settings.a2a_timeout,
            database_url=os.environ.get("DATABASE_URL", ""),
        )

    import uvicorn

    try:
        uvicorn.run(
            "canales.main:crear_app",
            factory=True,
            host=settings.host,
            port=settings.port,
            access_log=False,
            server_header=False,
            timeout_graceful_shutdown=20,
        )
    finally:
        puente_whatsapp.detener(proceso)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
