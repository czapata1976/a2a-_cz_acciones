"""Arranque del puente de WhatsApp (Node + Baileys) como subproceso.

Lo usan dos procesos: el servicio de canales en local y la app del coordinador en Heroku, donde el
puente vive en el mismo dyno y habla con la API por loopback. Si Node o las dependencias no est?n, se
avisa y el servicio sigue funcionando sin el canal: el puente es opcional.
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import threading
from pathlib import Path
from urllib.parse import urlparse

RAIZ = Path(__file__).resolve().parents[1]
logger = logging.getLogger("canales.puente")

MINIMO_SECRETO = 16


def puerto_de(url: str) -> int:
    """Puerto de loopback donde escucha el API interno del puente."""
    return urlparse(url).port or 18082


def arrancar(
    *,
    secreto: str,
    url_interna: str,
    backend_url: str,
    timeout_s: float,
    auth_dir: str = "",
    database_url: str = "",
) -> subprocess.Popen | None:
    """Lanza el puente y devuelve el proceso, o `None` si no puede arrancar."""
    node = shutil.which("node")
    if node is None:
        logger.warning("Node no est? instalado; el canal WhatsApp no se iniciar?.")
        return None
    script = RAIZ / "whatsapp" / "src" / "main.mjs"
    if not script.is_file():
        logger.warning("No se encontr? el puente de WhatsApp en %s.", script)
        return None
    if len(secreto) < MINIMO_SECRETO:
        logger.warning("WHATSAPP_SECRET debe tener al menos %s caracteres; el puente no se inicia.", MINIMO_SECRETO)
        return None

    entorno = dict(os.environ)
    entorno.setdefault("WHATSAPP_ENABLE_CONNECTION", "true")
    entorno.setdefault("WHATSAPP_LOG_LEVEL", "info")
    entorno.update(
        WHATSAPP_SECRET=secreto,
        WHATSAPP_INTERNAL_PORT=str(puerto_de(url_interna)),
        WHATSAPP_BACKEND_URL=backend_url,
        WHATSAPP_TIMEOUT_MS=str(int((timeout_s + 30) * 1000)),
    )
    if auth_dir:
        entorno["WHATSAPP_AUTH_DIR"] = auth_dir
    if database_url:
        entorno["DATABASE_URL"] = database_url
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


def detener(proceso: subprocess.Popen | None) -> None:
    """Termina el puente sin dejar el proceso hu?rfano."""
    if proceso is None or proceso.poll() is not None:
        return
    proceso.terminate()
    try:
        proceso.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proceso.kill()
        proceso.wait(timeout=5)
