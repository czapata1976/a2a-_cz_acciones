"""Punto de entrada único para Heroku.

Un mismo repositorio despliega tres apps; cada una elige su rol con la config var `ROL`:

    ROL=agente       → servidor A2A del agente (src/agente_acciones/servidor.py), que solo responde
                       al coordinador (es el único que tiene su clave)
    ROL=coordinador  → coordinador + canales de Telegram y WhatsApp (coordinador/main.py)
    ROL=web          → chat web con login (web/main.py), cliente del coordinador

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

from dotenv import load_dotenv  # noqa: E402

# En Heroku no hay `.env` (queda fuera del slug): las variables llegan como config vars. En local
# permite arrancar con el mismo punto de entrada para probar los tres roles.
load_dotenv(RAIZ / ".env")

logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO").upper(),
                    format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("heroku")

APPS = {
    "agente": "src.agente_acciones.servidor:crear_app",
    "coordinador": "coordinador.main:crear_app",
    "web": "web.main:crear_app",
}

ROLES_CON_CLAVE = {
    "agente": ("AGENTE_CLAVE", "sin clave el agente rechaza todos los mensajes"),
    "coordinador": ("COORDINADOR_CLAVE", "sin clave /chat rechaza todos los mensajes"),
    "web": ("WEB_CLAVE_HASH", "sin WEB_USUARIO y WEB_CLAVE_HASH el chat web no arranca"),
}


def main() -> int:
    rol = (os.environ.get("ROL") or "").strip().lower()
    if rol not in APPS:
        logger.error("Define ROL=agente, ROL=coordinador o ROL=web (recibido: %r).", rol)
        return 2
    puerto = int(os.environ.get("PORT") or 8080)

    variable, motivo = ROLES_CON_CLAVE[rol]
    if not (os.environ.get(variable) or "").strip():
        logger.error("Falta %s: %s.", variable, motivo)
        return 1
    if rol == "web" and not (os.environ.get("WEB_USUARIO") or "").strip():
        logger.error("Falta WEB_USUARIO: es el usuario del login del chat web.")
        return 1
    if rol == "web" and len((os.environ.get("WEB_SECRETO") or "").strip()) < 32:
        logger.error("Falta WEB_SECRETO (32 caracteres o más): firma la cookie de sesión.")
        return 1
    if rol == "web" and len((os.environ.get("COORDINADOR_CLAVE") or "").strip()) < 8:
        logger.error(
            "Falta COORDINADOR_CLAVE: el chat web no habla con el agente, solo con el coordinador."
        )
        return 1
    if rol == "web" and (os.environ.get("A2A_CZZ_CLAVE") or "").strip():
        logger.warning(
            "A2A_CZZ_CLAVE ya no se usa en el chat web (el agente solo responde al coordinador): "
            "quítala de esta app."
        )

    import uvicorn

    logger.info("Rol=%s en 0.0.0.0:%s", rol, puerto)
    # La memoria por conversación vive en el proceso (MemorySaver). Con varios workers, dos peticiones
    # del mismo cliente pueden caer en procesos distintos y la conversación «olvidaría» sus turnos.
    logger.info("Workers: 1 (la memoria en proceso exige un solo proceso)")
    uvicorn.run(
        APPS[rol],
        factory=True,
        host="0.0.0.0",
        port=puerto,
        workers=1,
        access_log=False,
        server_header=False,
        proxy_headers=True,
        forwarded_allow_ips="*",
        timeout_graceful_shutdown=20,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
