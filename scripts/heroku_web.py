"""Punto de entrada único para Heroku.

Un mismo repositorio despliega dos apps; cada una elige su rol con la config var `ROL`:

    ROL=agente       → servidor A2A del agente (src/agente_acciones/servidor.py)
    ROL=coordinador  → coordinador + canal de Telegram (coordinador/main.py)

Heroku entrega el puerto en `PORT`; el proceso escucha en 0.0.0.0.
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO").upper(),
                    format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("heroku")

APPS = {
    "agente": "src.agente_acciones.servidor:crear_app",
    "coordinador": "coordinador.main:crear_app",
}


def main() -> int:
    rol = (os.environ.get("ROL") or "").strip().lower()
    if rol not in APPS:
        logger.error("Define ROL=agente o ROL=coordinador (recibido: %r).", rol)
        return 2
    puerto = int(os.environ.get("PORT") or 8080)

    if rol == "agente" and not (os.environ.get("AGENTE_CLAVE") or "").strip():
        logger.error("Falta AGENTE_CLAVE: sin clave el agente rechaza todos los mensajes.")
        return 1
    if rol == "coordinador" and not (os.environ.get("COORDINADOR_CLAVE") or "").strip():
        logger.error("Falta COORDINADOR_CLAVE: sin clave /chat rechaza todos los mensajes.")
        return 1

    import uvicorn

    logger.info("Rol=%s en 0.0.0.0:%s", rol, puerto)
    uvicorn.run(
        APPS[rol],
        factory=True,
        host="0.0.0.0",
        port=puerto,
        access_log=False,
        server_header=False,
        proxy_headers=True,
        forwarded_allow_ips="*",
        timeout_graceful_shutdown=20,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
