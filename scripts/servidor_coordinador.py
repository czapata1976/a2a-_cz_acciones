"""Arranca el coordinador del equipo.

    .venv\\Scripts\\python.exe scripts\\servidor_coordinador.py

Necesita `COORDINADOR_CLAVE` y `URLS_AGENTES`. Escucha en `PORT` si existe (Heroku); si no, en
`COORDINADOR_PORT` (8120).
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

logger = logging.getLogger("coordinador")


def _registro() -> None:
    formato = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    raiz = logging.getLogger()
    raiz.setLevel(os.environ.get("LOG_LEVEL", "INFO").upper())
    consola = logging.StreamHandler(sys.stdout)
    consola.setFormatter(formato)
    raiz.addHandler(consola)
    carpeta = RAIZ / "logs"
    carpeta.mkdir(parents=True, exist_ok=True)
    archivo = RotatingFileHandler(carpeta / "coordinador.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    archivo.setFormatter(formato)
    raiz.addHandler(archivo)
    for ruidoso in ("httpx", "httpcore"):
        logging.getLogger(ruidoso).setLevel(logging.WARNING)


def main() -> int:
    from coordinador.config import ConfiguracionInvalida, cargar_settings
    from dotenv import load_dotenv

    load_dotenv()
    _registro()

    try:
        settings = cargar_settings()
    except ConfiguracionInvalida as error:
        logger.error("Configuración inválida: %s", error)
        return 1

    logger.info("Coordinador con %s agente(s) · canal Telegram: %s",
                len(settings.agentes), "sí" if settings.canal_telegram else "no")

    import uvicorn

    uvicorn.run(
        "coordinador.main:crear_app",
        factory=True,
        host=settings.host,
        port=settings.port,
        access_log=False,
        server_header=False,
        timeout_graceful_shutdown=20,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
