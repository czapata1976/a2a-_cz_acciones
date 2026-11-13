"""Configuración del coordinador.

Todo por entorno, nada de secretos en el código. `URLS_AGENTES` acepta dos formatos:

    URLS_AGENTES=https://agente-1.herokuapp.com,https://agente-bryhan.example.com
    URLS_AGENTES=[{"url": "https://agente-1.herokuapp.com", "clave": "clave-1"},
                  {"url": "https://agente-bryhan.example.com", "clave": ""}]

La clave es la del agente: se envía en `X-Agente-Clave`. Un agente sin clave (público) puede omitirla.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

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
class AgenteConfigurado:
    url: str
    clave: str = ""


@dataclass(frozen=True)
class Settings:
    host: str
    port: int
    clave: str
    agentes: list[AgenteConfigurado] = field(default_factory=list)
    timeout_agente: float = 60.0
    telegram_token: str = ""
    telegram_secret: str = ""
    telegram_api_base: str = "https://api.telegram.org"
    saltos: bool = False

    @property
    def canal_telegram(self) -> bool:
        return bool(self.telegram_token and self.telegram_secret)


def _leer_agentes(crudo: str) -> list[AgenteConfigurado]:
    if not crudo:
        return []
    if crudo.lstrip().startswith("["):
        try:
            datos = json.loads(crudo)
        except ValueError as error:
            raise ConfiguracionInvalida("URLS_AGENTES no es un JSON válido.") from error
        if not isinstance(datos, list):
            raise ConfiguracionInvalida("URLS_AGENTES debe ser una lista.")
        agentes = []
        for item in datos:
            if isinstance(item, str):
                agentes.append(AgenteConfigurado(url=item.strip().rstrip("/")))
            elif isinstance(item, dict) and item.get("url"):
                agentes.append(AgenteConfigurado(
                    url=str(item["url"]).strip().rstrip("/"), clave=str(item.get("clave") or "").strip()
                ))
            else:
                raise ConfiguracionInvalida("Cada entrada de URLS_AGENTES necesita `url`.")
        return agentes
    return [AgenteConfigurado(url=parte.strip().rstrip("/")) for parte in crudo.split(",") if parte.strip()]


def cargar_settings() -> Settings:
    load_dotenv()

    clave = _texto("COORDINADOR_CLAVE")
    if len(clave) < 8:
        raise ConfiguracionInvalida(
            "COORDINADOR_CLAVE debe tener al menos 8 caracteres: protege POST /chat. "
            "Genera una con: python -c \"import secrets; print(secrets.token_urlsafe(24))\""
        )
    agentes = _leer_agentes(_texto("URLS_AGENTES"))
    if not agentes:
        raise ConfiguracionInvalida(
            "URLS_AGENTES está vacío: el coordinador necesita al menos un agente para elegir."
        )

    return Settings(
        host=_texto("COORDINADOR_HOST", "0.0.0.0"),
        port=_entero("PORT", _entero("COORDINADOR_PORT", 8120, 1, 65535), 1, 65535),
        clave=clave,
        agentes=agentes,
        timeout_agente=float(_entero("TIMEOUT_AGENTE", 60, 5, 300)),
        telegram_token=_texto("TELEGRAM_TOKEN"),
        telegram_secret=_texto("TELEGRAM_SECRET"),
        telegram_api_base=_texto("TELEGRAM_API_BASE", "https://api.telegram.org").rstrip("/"),
        saltos=_booleano("SALTOS", False),
    )
