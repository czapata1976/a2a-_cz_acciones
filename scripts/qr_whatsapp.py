"""Trae el QR del canal de WhatsApp a un PNG local.

Usa la cabecera `X-Canales-Token`, no `?token=`: la URL queda en los registros del router de Heroku
y un token ah? es un token filtrado. Con `--conectar` adem?s pone el modo QR y abre la sesi?n, que es
lo que hace falta la primera vez o cuando la sesi?n se perdi?.

    .venv\\Scripts\\python.exe scripts\\qr_whatsapp.py --conectar
    .venv\\Scripts\\python.exe scripts\\qr_whatsapp.py --url https://<app>.herokuapp.com --conectar
"""
from __future__ import annotations

import argparse
import base64
import os
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from dotenv import load_dotenv  # noqa: E402


def main() -> int:
    load_dotenv(RAIZ / ".env")
    parser = argparse.ArgumentParser(description="Descarga el QR del canal de WhatsApp.")
    parser.add_argument("--url", default=os.environ.get("COORDINADOR_URL", "http://127.0.0.1:8120"))
    parser.add_argument("--token", default=os.environ.get("CANALES_TOKEN", ""))
    parser.add_argument("--salida", default="qr-whatsapp.png")
    parser.add_argument("--conectar", action="store_true", help="pide modo QR y abre la sesi?n antes")
    args = parser.parse_args()

    if not args.token:
        print("Falta CANALES_TOKEN (en .env o con --token): la gesti?n del canal lo exige.")
        return 1

    import httpx

    base = args.url.rstrip("/")
    cabeceras = {"X-Canales-Token": args.token}
    try:
        with httpx.Client(timeout=45, trust_env=False, headers=cabeceras) as cliente:
            if args.conectar:
                cliente.post(f"{base}/whatsapp/modo", json={"modo": "qr"}).raise_for_status()
                cliente.post(f"{base}/whatsapp/conectar").raise_for_status()
            estado = cliente.get(f"{base}/whatsapp/estado")
            estado.raise_for_status()
            print("estado del puente:", estado.json())
            datos = cliente.get(f"{base}/whatsapp/qr")
            datos.raise_for_status()
    except httpx.HTTPError as error:
        print(f"No pude consultar el QR: {error}")
        return 1

    imagen = (datos.json() or {}).get("imagen")
    if not isinstance(imagen, str) or ";base64," not in imagen:
        print("Todav?a no hay QR: espera unos segundos y repite, o revisa `estado`.")
        return 1
    destino = Path(args.salida)
    destino.write_bytes(base64.b64decode(imagen.split(";base64,", 1)[1]))
    print(f"QR guardado en {destino.resolve()}")
    print("Escan?alo desde WhatsApp > Dispositivos vinculados. Si expira, repite el comando.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
