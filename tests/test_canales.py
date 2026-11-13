"""Pruebas de los canales Telegram y WhatsApp (sin salir a la red).

El agente se sustituye por un doble que registra las consultas. Así se verifica el contrato de los
canales: secretos, sesión por chat y texto de respuesta. El notebook y las pruebas A2A cubren el
agente real.
"""
from __future__ import annotations

import uuid
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from canales.agente import ErrorAgente, contexto_de, texto_de
from canales.config import Settings
from canales.main import crear_app
from canales.telegram import dividir_texto

SECRETO_TELEGRAM = "secreto-telegram-de-prueba"
SECRETO_WHATSAPP = "secreto-whatsapp-de-prueba"


def config(**cambios) -> Settings:
    base = Settings(
        a2a_url="http://127.0.0.1:2029",
        a2a_graph="agente_cz_A2A",
        a2a_timeout=180.0,
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


class AgenteFalso:
    def __init__(self, respuesta: str = "análisis del agente", error: Exception | None = None) -> None:
        self.respuesta = respuesta
        self.error = error
        self.llamadas: list[tuple[str, str]] = []

    async def assistant_id(self) -> str:
        return "00000000-0000-0000-0000-000000000000"

    async def consultar(self, texto: str, sesion: str) -> str:
        self.llamadas.append((texto, sesion))
        if self.error:
            raise self.error
        return f"{self.respuesta}: {texto}"


@pytest.fixture
def enviados() -> list[tuple[int, str]]:
    return []


@pytest.fixture
def cliente(settings, enviados):
    agente = AgenteFalso()
    app = crear_app(settings=settings, agente=agente)

    async def enviar(_settings, chat_id: int, texto: str) -> None:
        enviados.append((chat_id, texto))

    app.state.enviar_telegram = enviar
    app.state.agente_falso = agente
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
    assert salud["agente"]["estado"] == "disponible"


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
    assert cliente.app.state.agente_falso.llamadas == [
        ("¿Cuánto vale AAPL en el mercado US?", "telegram-4242")
    ]
    assert enviados and enviados[0][0] == 4242
    assert "análisis del agente" in enviados[0][1]


def test_telegram_ayuda_no_consulta_al_agente(cliente, enviados):
    cliente.post(
        "/telegram/webhook",
        json=update_de("/ayuda"),
        headers={"X-Telegram-Bot-Api-Secret-Token": SECRETO_TELEGRAM},
    )
    assert cliente.app.state.agente_falso.llamadas == []
    assert "agente_cz_A2A" in enviados[0][1]


def test_telegram_ignora_updates_sin_texto(cliente):
    respuesta = cliente.post(
        "/telegram/webhook",
        json={"update_id": 2, "message": {"chat": {"id": 1}, "sticker": {}}},
        headers={"X-Telegram-Bot-Api-Secret-Token": SECRETO_TELEGRAM},
    )
    assert respuesta.json() == {"ok": True, "ignorado": True}


def test_telegram_sin_configuracion_responde_503():
    app = crear_app(settings=config(telegram_token="", telegram_secret=""), agente=AgenteFalso())
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
    assert cliente.app.state.agente_falso.llamadas == [("Analiza NVDA en US", "wa_abc123")]


def test_whatsapp_devuelve_200_con_el_error_del_agente():
    app = crear_app(settings=config(), agente=AgenteFalso(error=ErrorAgente("sin conexión")))
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
    app = crear_app(settings=config(whatsapp_habilitado=False), agente=AgenteFalso())
    with TestClient(app) as test_client:
        respuesta = test_client.post(
            "/whatsapp/mensaje",
            json={"mensaje": "hola"},
            headers={"X-WhatsApp-Secret": SECRETO_WHATSAPP},
        )
    assert respuesta.status_code == 503


def test_gestion_whatsapp_exige_token_si_esta_configurado():
    app = crear_app(settings=config(canales_token="token-operador"), agente=AgenteFalso())
    with TestClient(app) as test_client:
        assert test_client.get("/whatsapp/estado").status_code == 403
        # Con token pasa la autorización y falla más adelante porque el puente no está corriendo.
        respuesta = test_client.get("/whatsapp/estado?token=token-operador")
        assert respuesta.status_code == 503


def test_contexto_estable_por_conversacion():
    primero = contexto_de("telegram-4242")
    assert primero == contexto_de("telegram-4242")
    assert primero != contexto_de("telegram-9999")
    assert str(uuid.UUID(primero)) == primero


def test_texto_de_lee_estado_e_historial():
    con_estado = {"status": {"state": "completed", "message": {"parts": [{"kind": "text", "text": "hola"}]}}}
    assert texto_de(con_estado) == "hola"
    con_historial = {
        "status": {"state": "completed"},
        "history": [{"role": "agent", "parts": [{"kind": "text", "text": "desde historial"}]}],
    }
    assert texto_de(con_historial) == "desde historial"


def test_dividir_texto_respeta_el_limite():
    texto = "\n".join(f"línea {i} " + "x" * 60 for i in range(80))
    partes = dividir_texto(texto, limite=1000)
    assert len(partes) > 1
    assert all(len(parte) <= 1000 for parte in partes)
    assert "".join(partes).replace(" ", "").replace("\n", "") == texto.replace(" ", "").replace("\n", "")
