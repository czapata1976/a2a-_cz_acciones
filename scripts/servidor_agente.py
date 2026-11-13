"""Arranca el servidor A2A propio del agente.

    .venv\\Scripts\\python.exe scripts\\servidor_agente.py

Necesita `AGENTE_CLAVE` (protege `message/send`) y, en la nube, `URL_PUBLICA` para que la ficha anuncie
su dirección real. Escucha en `PORT` si existe (Heroku); si no, en `AGENTE_PORT` (2029).
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

logger = logging.getLogger("agente")


def _registro() -> None:
    formato = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    raiz = logging.getLogger()
    raiz.setLevel(os.environ.get("LOG_LEVEL", "INFO").upper())
    consola = logging.StreamHandler(sys.stdout)
    consola.setFormatter(formato)
    raiz.addHandler(consola)
    carpeta = RAIZ / "logs"
    carpeta.mkdir(parents=True, exist_ok=True)
    archivo = RotatingFileHandler(carpeta / "agente.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    archivo.setFormatter(formato)
    raiz.addHandler(archivo)
    for ruidoso in ("httpx", "httpcore", "google_genai"):
        logging.getLogger(ruidoso).setLevel(logging.WARNING)


def main() -> int:
    from dotenv import load_dotenv

    load_dotenv()
    _registro()

    if not (os.environ.get("AGENTE_CLAVE") or "").strip():
        logger.error(
            "Falta AGENTE_CLAVE: sin clave, message/send rechaza todo (falla cerrado). "
            "Genera una con: python -c \"import secrets; print(secrets.token_urlsafe(24))\""
        )
        return 1

    import uvicorn

    puerto = int(os.environ.get("PORT") or os.environ.get("AGENTE_PORT") or 2029)
    logger.info("Agente A2A en http://0.0.0.0:%s · URL_PUBLICA=%s", puerto,
                os.environ.get("URL_PUBLICA") or "(la de la petición)")
    uvicorn.run(
        "src.agente_acciones.servidor:crear_app",
        factory=True,
        host="0.0.0.0",
        port=puerto,
        access_log=False,
        server_header=False,
        timeout_graceful_shutdown=20,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
