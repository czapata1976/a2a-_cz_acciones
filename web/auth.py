"""Autenticación del chat web: hash de la clave y cookie de sesión firmada.

Sin dependencias nuevas: PBKDF2-HMAC-SHA256 para la clave y HMAC-SHA256 para firmar la cookie.
La cookie viaja HttpOnly, así que el JavaScript de la página nunca ve el secreto de sesión.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import threading
import time

ITERACIONES = 200_000
ALGORITMO = "pbkdf2_sha256"
MAX_INTENTOS = 5
BLOQUEO_SEGUNDOS = 60


def _b64(datos: bytes) -> str:
    return base64.urlsafe_b64encode(datos).decode("ascii").rstrip("=")


def _de_b64(texto: str) -> bytes:
    relleno = "=" * (-len(texto) % 4)
    return base64.urlsafe_b64decode(texto + relleno)


def hash_clave(clave: str, iteraciones: int = ITERACIONES, sal: bytes | None = None) -> str:
    """Devuelve `pbkdf2_sha256$<iteraciones>$<sal>$<hash>` listo para `.env`."""
    if not clave:
        raise ValueError("La clave no puede estar vacía.")
    sal = sal or secrets.token_bytes(16)
    derivada = hashlib.pbkdf2_hmac("sha256", clave.encode("utf-8"), sal, iteraciones)
    return f"{ALGORITMO}${iteraciones}${_b64(sal)}${_b64(derivada)}"


def verificar_clave(clave: str, guardado: str) -> bool:
    """Compara la clave con el hash guardado sin filtrar tiempos."""
    try:
        algoritmo, iteraciones, sal, esperado = guardado.split("$", 3)
        if algoritmo != ALGORITMO:
            return False
        derivada = hashlib.pbkdf2_hmac(
            "sha256", (clave or "").encode("utf-8"), _de_b64(sal), int(iteraciones)
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(_b64(derivada), esperado)


def generar_secreto(largo: int = 48) -> str:
    """Secreto aleatorio para firmar cookies (se pega en `WEB_SECRETO`)."""
    return secrets.token_urlsafe(largo)


def _firma(carga: str, secreto: str) -> str:
    return _b64(hmac.new(secreto.encode("utf-8"), carga.encode("ascii"), hashlib.sha256).digest())


def crear_cookie(usuario: str, secreto: str, horas: float) -> str:
    """Cookie `payload.firma` con el usuario y su vencimiento."""
    vence = int(time.time() + horas * 3600)
    carga = _b64(json.dumps({"u": usuario, "e": vence}, separators=(",", ":")).encode("utf-8"))
    return f"{carga}.{_firma(carga, secreto)}"


def leer_cookie(valor: str | None, secreto: str) -> str | None:
    """Devuelve el usuario si la firma es válida y la sesión no venció."""
    if not valor or "." not in valor:
        return None
    carga, firma = valor.rsplit(".", 1)
    if not hmac.compare_digest(firma, _firma(carga, secreto)):
        return None
    try:
        datos = json.loads(_de_b64(carga))
        usuario = str(datos["u"])
        vence = int(datos["e"])
    except (ValueError, KeyError, TypeError):
        return None
    if vence < int(time.time()):
        return None
    return usuario


class LimiteIntentos:
    """Frena la fuerza bruta: N fallos seguidos bloquean el origen unos segundos."""

    def __init__(self, maximo: int = MAX_INTENTOS, segundos: int = BLOQUEO_SEGUNDOS) -> None:
        self.maximo = maximo
        self.segundos = segundos
        self._fallos: dict[str, tuple[int, float]] = {}
        self._candado = threading.Lock()

    def bloqueado(self, origen: str) -> int:
        """Segundos que faltan para reintentar, o 0 si puede intentar."""
        with self._candado:
            fallos, hasta = self._fallos.get(origen, (0, 0.0))
            if hasta and hasta > time.monotonic():
                return max(1, int(hasta - time.monotonic()))
            if hasta:
                self._fallos.pop(origen, None)
                return 0
            return 0 if fallos < self.maximo else self.segundos

    def fallo(self, origen: str) -> None:
        with self._candado:
            fallos, hasta = self._fallos.get(origen, (0, 0.0))
            if hasta and hasta > time.monotonic():
                return
            fallos += 1
            if fallos >= self.maximo:
                self._fallos[origen] = (0, time.monotonic() + self.segundos)
            else:
                self._fallos[origen] = (fallos, 0.0)

    def exito(self, origen: str) -> None:
        with self._candado:
            self._fallos.pop(origen, None)
