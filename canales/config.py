"""Configuración del servicio de canales (Telegram y WhatsApp) de `agente_cz_A2A`.

Lee `.env` del proyecto. Los canales son un cliente A2A del agente: no lo importan ni comparten
proceso, así que el agente puede reiniciarse sin tocar las conversaciones de los canales.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv


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


def _booleano(nombre: str, defecto: bool = False) -> bool:
    crudo = _texto(nombre).lower()
    if not crudo:
        return defecto
    if crudo in {"1", "true", "si", "sí", "yes", "on"}:
        return True
    if crudo in {"0", "false", "no", "off"}:
        return False
    raise ConfiguracionInvalida(f"{nombre} debe ser true o false.")


@dataclass(frozen=True)
class Settings:
    """Parámetros del servicio y del agente al que consulta."""

    a2a_url: str
    a2a_graph: str
    a2a_timeout: float
    host: str
    port: int
    canales_token: str
    telegram_token: str
    telegram_secret: str
    telegram_api_base: str
    telegram_envio: str
    whatsapp_habilitado: bool
    whatsapp_secret: str
    whatsapp_url_interna: str
    whatsapp_timeout: float
    whatsapp_max_caracteres: int


def cargar_settings() -> Settings:
    load_dotenv()

    envio = _texto("TELEGRAM_ENVIO", "api").lower()
    if envio not in {"api", "log"}:
        raise ConfiguracionInvalida("TELEGRAM_ENVIO debe ser api o log.")

    return Settings(
        a2a_url=_texto("A2A_CZZ_URL", "http://127.0.0.1:2029").rstrip("/"),
        a2a_graph=_texto("A2A_CZZ_GRAPH", "agente_cz_A2A"),
        a2a_timeout=_decimal("A2A_TIMEOUT", 180.0, 5.0, 600.0),
        host=_texto("CANALES_HOST", "127.0.0.1"),
        port=_entero("CANALES_PORT", 8100, 1, 65535),
        canales_token=_texto("CANALES_TOKEN"),
        telegram_token=_texto("TELEGRAM_TOKEN"),
        telegram_secret=_texto("TELEGRAM_SECRET"),
        telegram_api_base=_texto("TELEGRAM_API_BASE", "https://api.telegram.org").rstrip("/"),
        telegram_envio=envio,
        whatsapp_habilitado=_booleano("WHATSAPP_HABILITADO", False),
        whatsapp_secret=_texto("WHATSAPP_SECRET"),
        whatsapp_url_interna=_texto("WHATSAPP_URL_INTERNA", "http://127.0.0.1:18082").rstrip("/"),
        whatsapp_timeout=_decimal("WHATSAPP_TIMEOUT", 20.0, 1.0, 120.0),
        whatsapp_max_caracteres=_entero("WHATSAPP_MAX_CARACTERES", 3500, 500, 4096),
    )
