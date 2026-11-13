"""Arranca el chat web de `agente_cz_A2A` en `WEB_PORT` (8110 por defecto).

    .venv\\Scripts\\python.exe scripts\\servidor_web.py

El agente A2A debe estar corriendo aparte (`.venv\\Scripts\\langgraph.exe dev --port 2029`). Se puede
levantar junto a los canales: usan puertos distintos.
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

from web.config import ConfiguracionInvalida, cargar_settings  # noqa: E402

logger = logging.getLogger("web.supervisor")


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
    archivo = RotatingFileHandler(carpeta / "web.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    archivo.setFormatter(formato)
    raiz.addHandler(archivo)
    for ruidoso in ("httpx", "httpcore"):
        logging.getLogger(ruidoso).setLevel(logging.WARNING)


def main() -> int:
    _configurar_registro()
    try:
        settings = cargar_settings()
    except ConfiguracionInvalida as error:
        logger.error("Configuración inválida: %s", error)
        return 1

    logger.info("Chat web en http://%s:%s · usuario %s", settings.host, settings.port, settings.usuario)
    logger.info("Agente local %s en %s · hasta %s agentes remotos", settings.a2a_graph, settings.a2a_url, settings.max_agentes)

    import uvicorn

    uvicorn.run(
        "web.main:crear_app",
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
