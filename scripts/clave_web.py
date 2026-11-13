"""Genera las credenciales del chat web para pegarlas en `.env`.

    .venv\\Scripts\\python.exe scripts\\clave_web.py
    .venv\\Scripts\\python.exe scripts\\clave_web.py --usuario carlos --clave "mi clave"

Imprime `WEB_USUARIO`, `WEB_CLAVE_HASH` y `WEB_SECRETO`. La clave en claro no se guarda.
"""
from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from web.auth import generar_secreto, hash_clave  # noqa: E402

LARGO_MINIMO = 8


def main() -> int:
    parser = argparse.ArgumentParser(description="Genera el hash de la clave y el secreto de sesión del chat web.")
    parser.add_argument("--usuario", default="carlos", help="usuario que irá en WEB_USUARIO")
    parser.add_argument("--clave", help="clave en claro; si se omite se pide sin mostrar")
    args = parser.parse_args()

    clave = args.clave
    if not clave:
        try:
            clave = getpass.getpass("Clave para el chat web: ")
        except (EOFError, OSError):
            print("No hay consola interactiva: pasa la clave con --clave.", file=sys.stderr)
            return 1

    if len(clave) < LARGO_MINIMO:
        print(f"La clave debe tener al menos {LARGO_MINIMO} caracteres.", file=sys.stderr)
        return 1

    print("\nPega estas líneas en .env (reemplazan las actuales):\n")
    print(f"WEB_USUARIO={args.usuario}")
    print(f"WEB_CLAVE_HASH={hash_clave(clave)}")
    print(f"WEB_SECRETO={generar_secreto()}")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
