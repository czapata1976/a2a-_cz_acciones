"""Configuración del chat web de `agente_cz_A2A`.

Igual que los canales, la web es un cliente del coordinador: no importa el grafo ni guarda la clave
del agente, así que el agente solo responde a quien el coordinador le manda. Las credenciales viven
en `.env`.
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
    """Parámetros del servicio web, de la sesión y del coordinador que atiende el turno."""

    host: str
    port: int
    usuario: str
    clave_hash: str
    secreto: str
    horas_sesion: float
    coordinador_url: str
    coordinador_clave: str
    agente_sintesis: str
    """Agente del equipo que el coordinador consulta para sintetizar el turno."""
    a2a_timeout: float
    ruta_datos: str
    """Archivo SQLite o URL de Postgres (`postgresql://…`)."""
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
    coordinador_url = _texto("COORDINADOR_URL", "http://127.0.0.1:8120").rstrip("/")
    coordinador_clave = _texto("COORDINADOR_CLAVE")
    if len(coordinador_clave) < 8:
        raise ConfiguracionInvalida(
            "Falta COORDINADOR_CLAVE: el chat no habla con el agente, solo con el coordinador, y "
            "sin su clave /chat rechaza todo. Usa la misma del coordinador."
        )

    return Settings(
        host=_texto("WEB_HOST", "127.0.0.1"),
        port=_entero("WEB_PORT", 8110, 1, 65535),
        usuario=usuario,
        clave_hash=clave_hash,
        secreto=secreto,
        horas_sesion=_decimal("WEB_HORAS_SESION", 8.0, 0.1, 168.0),
        coordinador_url=coordinador_url,
        coordinador_clave=coordinador_clave,
        agente_sintesis=_texto("A2A_CZZ_GRAPH", "agente_cz_A2A"),
        a2a_timeout=_decimal("A2A_TIMEOUT", 180.0, 5.0, 600.0),
        ruta_datos=_texto("WEB_DATOS") or _texto("DATABASE_URL") or "web/.runtime/chat.db",
    )
