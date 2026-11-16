"""Pruebas de los canales Telegram y WhatsApp (sin salir a la red).

El coordinador se sustituye por un doble que registra las consultas. Así se verifica el contrato de
los canales: secretos, sesión por chat y texto de respuesta. El coordinador real se prueba en
`test_coordinador.py` y el agente en `test_a2a_czz.py`.
"""
from __future__ import annotations

from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from canales.a2a import texto_de
from canales.config import Settings
from canales.coordinador import ErrorCoordinador
from canales.main import crear_app
from canales.telegram import dividir_texto

SECRETO_TELEGRAM = "secreto-telegram-de-prueba"
SECRETO_WHATSAPP = "secreto-whatsapp-de-prueba"


def config(**cambios) -> Settings:
    base = Settings(
        coordinador_url="http://127.0.0.1:8120",
        coordinador_clave="clave-del-coordinador-para-prueba",
        timeout=180.0,
        host="127.0.0.1",
        port=8100,
        canales_token="",
        telegram_token="token-de-prueba",
        telegram_secret=SECRETO_TELEGRAM,
        telegram_api_base="https://api.telegram.org",
        telegram_envio="log",
        whatsapp_habilitado=True,
        whatsapp_secret=SECRETO_WHATSAPP,
        whatsapp_url_interna="http://127.0.0.1:18082",
        whatsapp_timeout=20.0,
        whatsapp_max_caracteres=3500,
    )
    return replace(base, **cambios)


@pytest.fixture
def settings() -> Settings:
    return config()


class CoordinadorFalso:
    def __init__(self, respuesta: str = "análisis del agente", error: Exception | None = None) -> None:
        self.respuesta = respuesta
        self.error = error
        self.llamadas: list[tuple[str, str]] = []

    async def consultar(self, texto: str, sesion: str) -> str:
        self.llamadas.append((texto, sesion))
        if self.error:
            raise self.error
        return f"{self.respuesta}: {texto}"

    async def estado(self) -> dict:
        if self.error:
            raise self.error
        return {
            "ok": True,
            "coordinador": "disponible",
            "agentes": [{"nombre": "agente_cz_A2A", "estado": "disponible"}],
        }


@pytest.fixture
def enviados() -> list[tuple[int, str]]:
    return []


@pytest.fixture
def cliente(settings, enviados):
    coordinador = CoordinadorFalso()
    app = crear_app(settings=settings, coordinador=coordinador)

    async def enviar(_settings, chat_id: int, texto: str) -> None:
        enviados.append((chat_id, texto))

    app.state.enviar_telegram = enviar
    app.state.coordinador_falso = coordinador
    with TestClient(app) as test_client:
        yield test_client


def update_de(texto: str, chat_id: int = 4242) -> dict:
    return {
        "update_id": 1,
        "message": {
            "message_id": 5,
            "date": 0,
            "chat": {"id": chat_id, "type": "private"},
            "text": texto,
        },
    }


def test_ok_y_salud(cliente):
    assert cliente.get("/ok").json()["ok"] is True
    salud = cliente.get("/salud").json()
    assert salud["canales"]["whatsapp"] is True
    assert salud["coordinador"]["estado"] == "disponible"
    assert salud["coordinador"]["agentes"] == ["agente_cz_A2A"]


def test_telegram_rechaza_secreto_invalido(cliente):
    assert cliente.post("/telegram/webhook", json=update_de("hola")).status_code == 403
    respuesta = cliente.post(
        "/telegram/webhook",
        json=update_de("hola"),
        headers={"X-Telegram-Bot-Api-Secret-Token": "otro-secreto"},
    )
    assert respuesta.status_code == 403


def test_telegram_procesa_y_responde(cliente, enviados):
    respuesta = cliente.post(
        "/telegram/webhook",
        json=update_de("¿Cuánto vale AAPL en el mercado US?"),
        headers={"X-Telegram-Bot-Api-Secret-Token": SECRETO_TELEGRAM},
    )
    assert respuesta.status_code == 200
    assert respuesta.json() == {"ok": True, "chat_id": 4242}
    assert cliente.app.state.coordinador_falso.llamadas == [
        ("¿Cuánto vale AAPL en el mercado US?", "telegram:4242")
    ]
    assert enviados and enviados[0][0] == 4242
    assert "análisis del agente" in enviados[0][1]


def test_telegram_ayuda_no_consulta_al_coordinador(cliente, enviados):
    cliente.post(
        "/telegram/webhook",
        json=update_de("/ayuda"),
        headers={"X-Telegram-Bot-Api-Secret-Token": SECRETO_TELEGRAM},
    )
    assert cliente.app.state.coordinador_falso.llamadas == []
    assert "coordinador" in enviados[0][1]


def test_telegram_ignora_updates_sin_texto(cliente):
    respuesta = cliente.post(
        "/telegram/webhook",
        json={"update_id": 2, "message": {"chat": {"id": 1}, "sticker": {}}},
        headers={"X-Telegram-Bot-Api-Secret-Token": SECRETO_TELEGRAM},
    )
    assert respuesta.json() == {"ok": True, "ignorado": True}


def test_telegram_sin_configuracion_responde_503():
    app = crear_app(settings=config(telegram_token="", telegram_secret=""), coordinador=CoordinadorFalso())
    with TestClient(app) as test_client:
        assert test_client.post("/telegram/webhook", json=update_de("hola")).status_code == 503


def test_whatsapp_rechaza_secreto_invalido(cliente):
    respuesta = cliente.post("/whatsapp/mensaje", json={"mensaje": "hola"})
    assert respuesta.status_code == 403


def test_whatsapp_responde_con_la_sesion_del_puente(cliente):
    respuesta = cliente.post(
        "/whatsapp/mensaje",
        json={"mensaje": "Analiza NVDA en US", "session_id": "wa_abc123", "request_id": "wa_def456"},
        headers={"X-WhatsApp-Secret": SECRETO_WHATSAPP},
    )
    assert respuesta.status_code == 200
    assert respuesta.json()["estado"] == "ok"
    assert "análisis del agente" in respuesta.json()["respuesta"]
    assert cliente.app.state.coordinador_falso.llamadas == [("Analiza NVDA en US", "wa_abc123")]


def test_whatsapp_devuelve_200_con_el_error_del_coordinador():
    app = crear_app(
        settings=config(),
        coordinador=CoordinadorFalso(error=ErrorCoordinador("sin conexión")),
    )
    with TestClient(app) as test_client:
        respuesta = test_client.post(
            "/whatsapp/mensaje",
            json={"mensaje": "hola", "session_id": "wa_abc123"},
            headers={"X-WhatsApp-Secret": SECRETO_WHATSAPP},
        )
    # El puente descarta el mensaje si no recibe 200: el error se responde como texto.
    assert respuesta.status_code == 200
    assert respuesta.json()["estado"] == "error"
    assert "sin conexión" in respuesta.json()["respuesta"]


def test_whatsapp_deshabilitado_responde_503():
    app = crear_app(settings=config(whatsapp_habilitado=False), coordinador=CoordinadorFalso())
    with TestClient(app) as test_client:
        respuesta = test_client.post(
            "/whatsapp/mensaje",
            json={"mensaje": "hola"},
            headers={"X-WhatsApp-Secret": SECRETO_WHATSAPP},
        )
    assert respuesta.status_code == 503


def test_gestion_whatsapp_exige_token_si_esta_configurado():
    app = crear_app(settings=config(canales_token="token-operador"), coordinador=CoordinadorFalso())
    with TestClient(app) as test_client:
        assert test_client.get("/whatsapp/estado").status_code == 403
        # Con token pasa la autorización y falla más adelante porque el puente no está corriendo.
        respuesta = test_client.get("/whatsapp/estado?token=token-operador")
        assert respuesta.status_code == 503


def test_texto_de_lee_estado_e_historial():
    con_estado = {"status": {"state": "completed", "message": {"parts": [{"kind": "text", "text": "hola"}]}}}
    assert texto_de(con_estado) == "hola"
    con_historial = {
        "status": {"state": "completed"},
        "history": [{"role": "agent", "parts": [{"kind": "text", "text": "desde historial"}]}],
    }
    assert texto_de(con_historial) == "desde historial"


def test_texto_de_no_duplica_artefacto_y_estado():
    resultado = {
        "status": {"state": "completed", "message": {"parts": [{"kind": "text", "text": "la respuesta"}]}},
        "artifacts": [{"parts": [{"kind": "text", "text": "la respuesta"}]}],
    }
    assert texto_de(resultado) == "la respuesta"


def test_dividir_texto_respeta_el_limite():
    texto = "\n".join(f"línea {i} " + "x" * 60 for i in range(80))
    partes = dividir_texto(texto, limite=1000)
    assert len(partes) > 1
    assert all(len(parte) <= 1000 for parte in partes)
    assert "".join(partes).replace(" ", "").replace("\n", "") == texto.replace(" ", "").replace("\n", "")
