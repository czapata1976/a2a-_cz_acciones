"""Supervisor de los canales: FastAPI y, si está habilitado, el puente de WhatsApp.

Un solo comando arranca los dos procesos:

    .venv\\Scripts\\python.exe scripts\\servidor_canales.py

Si el puente no puede arrancar (Node o dependencias faltantes), la API de canales sigue disponible
y `/salud` informa que WhatsApp no está operativo. El agente A2A debe estar corriendo aparte.
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
import threading
from logging.handlers import RotatingFileHandler
from pathlib import Path
from urllib.parse import urlparse

RAIZ = Path(__file__).resolve().parents[1]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

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


def _puerto_puente(url: str) -> int:
    return urlparse(url).port or 18082


def _arrancar_puente(settings: Settings) -> subprocess.Popen | None:
    node = shutil.which("node")
    if node is None:
        logger.warning("Node no está instalado; el canal WhatsApp no se iniciará.")
        return None
    script = RAIZ / "whatsapp" / "src" / "main.mjs"
    if not script.is_file():
        logger.warning("No se encontró el puente de WhatsApp en %s.", script)
        return None
    if len(settings.whatsapp_secret) < 16:
        logger.warning("WHATSAPP_SECRET debe tener al menos 16 caracteres; el puente no se inicia.")
        return None

    entorno = dict(os.environ)
    entorno.setdefault("WHATSAPP_ENABLE_CONNECTION", "true")
    entorno.setdefault("WHATSAPP_LOG_LEVEL", "info")
    entorno.update(
        WHATSAPP_SECRET=settings.whatsapp_secret,
        WHATSAPP_INTERNAL_PORT=str(_puerto_puente(settings.whatsapp_url_interna)),
        WHATSAPP_BACKEND_URL=f"http://127.0.0.1:{settings.port}/whatsapp/mensaje",
        WHATSAPP_TIMEOUT_MS=str(int((settings.a2a_timeout + 30) * 1000)),
    )
    try:
        proceso = subprocess.Popen(
            [node, str(script)],
            cwd=str(RAIZ),
            env=entorno,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
    except OSError as error:
        logger.warning("No se pudo iniciar el puente de WhatsApp: %s", error)
        return None

    def bombear() -> None:
        for linea in proceso.stdout or []:
            texto = linea.rstrip()
            if texto:
                logger.info("[puente] %s", texto[:300])

    threading.Thread(target=bombear, daemon=True, name="puente-log").start()
    logger.info("Puente de WhatsApp iniciado (pid=%s).", proceso.pid)
    return proceso


def _detener(proceso: subprocess.Popen | None) -> None:
    if proceso is None or proceso.poll() is not None:
        return
    proceso.terminate()
    try:
        proceso.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proceso.kill()
        proceso.wait(timeout=5)


def main() -> int:
    _configurar_registro()
    try:
        settings = cargar_settings()
    except ConfiguracionInvalida as error:
        logger.error("Configuración inválida: %s", error)
        return 1

    logger.info("Canales en http://%s:%s · agente A2A %s (%s)", settings.host, settings.port, settings.a2a_graph, settings.a2a_url)
    logger.info("Telegram: %s", "listo (webhook)" if settings.telegram_token else "sin TELEGRAM_TOKEN")
    logger.info("WhatsApp: %s", "habilitado" if settings.whatsapp_habilitado else "deshabilitado")

    puente = _arrancar_puente(settings) if settings.whatsapp_habilitado else None

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
        _detener(puente)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
