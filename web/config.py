"""Configuración del chat web de `agente_cz_A2A`.

Igual que los canales, la web es un cliente A2A: no importa el grafo, así que el agente puede
reiniciarse sin que se pierda el hilo de las conversaciones. Las credenciales viven en `.env`.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

MAX_AGENTES = 4
"""Tope de agentes remotos que se pueden sumar al equipo del proyecto."""


class ConfiguracionInvalida(ValueError):
    """Falta un dato obligatorio o tiene un formato que no se puede usar."""


def _texto(nombre: str, defecto: str = "") -> str:
    return (os.environ.get(nombre) or defecto).strip()


def _entero(nombre: str, defecto: int, minimo: int, maximo: int) -> int:
    crudo = _texto(nombre)
    if not crudo:
        return defecto
    try:
        valor = int(crudo)
    except ValueError as error:
        raise ConfiguracionInvalida(f"{nombre} debe ser un número entero.") from error
    if not minimo <= valor <= maximo:
        raise ConfiguracionInvalida(f"{nombre} debe estar entre {minimo} y {maximo}.")
    return valor


def _decimal(nombre: str, defecto: float, minimo: float, maximo: float) -> float:
    crudo = _texto(nombre)
    if not crudo:
        return defecto
    try:
        valor = float(crudo)
    except ValueError as error:
        raise ConfiguracionInvalida(f"{nombre} debe ser un número.") from error
    if not minimo <= valor <= maximo:
        raise ConfiguracionInvalida(f"{nombre} debe estar entre {minimo} y {maximo}.")
    return valor


@dataclass(frozen=True)
class Settings:
    """Parámetros del servicio web, de la sesión y del agente que sintetiza."""

    host: str
    port: int
    usuario: str
    clave_hash: str
    secreto: str
    horas_sesion: float
    a2a_url: str
    a2a_graph: str
    a2a_timeout: float
    ruta_datos: str
    a2a_clave: str = ""
    max_agentes: int = MAX_AGENTES


def cargar_settings() -> Settings:
    load_dotenv()

    usuario = _texto("WEB_USUARIO")
    clave_hash = _texto("WEB_CLAVE_HASH")
    if not usuario or not clave_hash:
        raise ConfiguracionInvalida(
            "Faltan WEB_USUARIO y WEB_CLAVE_HASH. Genera el hash con: "
            ".venv\\Scripts\\python.exe scripts\\clave_web.py"
        )
    secreto = _texto("WEB_SECRETO")
    if len(secreto) < 32:
        raise ConfiguracionInvalida(
            "WEB_SECRETO debe tener al menos 32 caracteres: firma la cookie de sesión. "
            "Genera uno con: .venv\\Scripts\\python.exe scripts\\clave_web.py"
        )
    if not clave_hash.startswith("pbkdf2_sha256$"):
        raise ConfiguracionInvalida(
            "WEB_CLAVE_HASH debe ser un hash pbkdf2_sha256 generado por scripts\\clave_web.py."
        )

    return Settings(
        host=_texto("WEB_HOST", "127.0.0.1"),
        port=_entero("WEB_PORT", 8110, 1, 65535),
        usuario=usuario,
        clave_hash=clave_hash,
        secreto=secreto,
        horas_sesion=_decimal("WEB_HORAS_SESION", 8.0, 0.1, 168.0),
        a2a_url=_texto("A2A_CZZ_URL", "http://127.0.0.1:2029").rstrip("/"),
        a2a_graph=_texto("A2A_CZZ_GRAPH", "agente_cz_A2A"),
        a2a_timeout=_decimal("A2A_TIMEOUT", 180.0, 5.0, 600.0),
        ruta_datos=_texto("WEB_DATOS", "web/.runtime/chat.db"),
        a2a_clave=_texto("A2A_CZZ_CLAVE") or _texto("AGENTE_CLAVE"),
    )
