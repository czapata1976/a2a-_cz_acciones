"""Pruebas del servidor A2A propio del agente (sin red y sin modelo).

Se inyecta un agente falso que registra el `thread_id` con que se le llamó, así se verifica la memoria
por `contextId`. La tarjeta y `/salud` deben ser públicas; `message/send` debe exigir la clave.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage

from src.agente_acciones.servidor import NO_LEIBLE, crear_app
from src.agente_acciones.tarjeta import DESCRIPCION, NOMBRE

CLAVE = "clave-del-agente-de-prueba"
CABECERA = {"X-Agente-Clave": CLAVE}


class AgenteFalso:
    """Devuelve un texto fijo y anota el hilo con que lo invocaron."""

    def __init__(self, texto: str = "respuesta del agente", error: Exception | None = None) -> None:
        self.texto = texto
        self.error = error
        self.hilos: list[str] = []

    async def ainvoke(self, entrada, config):
        self.hilos.append(config["configurable"]["thread_id"])
        if self.error:
            raise self.error
        return {"messages": [*entrada["messages"], AIMessage(content=self.texto)]}


@pytest.fixture
def agente() -> AgenteFalso:
    return AgenteFalso()


@pytest.fixture
def cliente(monkeypatch, agente) -> TestClient:
    monkeypatch.setenv("AGENTE_CLAVE", CLAVE)
    monkeypatch.setenv("URL_PUBLICA", "https://agente-cz.herokuapp.com")
    with TestClient(crear_app(agente)) as prueba:
        yield prueba


def enviar(cliente: TestClient, texto: str, context_id: str = "ctx-1", partes=None, **kw):
    cuerpo = {
        "jsonrpc": "2.0", "id": "1", "method": "message/send",
        "params": {"message": {
            "role": "user", "messageId": "m1", "contextId": context_id,
            "parts": partes or [{"kind": "text", "text": texto}],
        }},
    }
    return cliente.post("/a2a", json=cuerpo, **kw)


# --- ficha y salud --------------------------------------------------------
def test_tarjeta_es_publica_y_apunta_a_la_url_publica(cliente: TestClient):
    respuesta = cliente.get("/.well-known/agent-card.json")
    assert respuesta.status_code == 200
    tarjeta = respuesta.json()
    assert tarjeta["name"] == NOMBRE
    assert tarjeta["url"] == "https://agente-cz.herokuapp.com/a2a"
    assert "NO ejecuta" in tarjeta["description"]
    assert tarjeta["description"] == DESCRIPCION
    assert len(tarjeta["skills"]) >= 2
    assert all(skill.get("tags") for skill in tarjeta["skills"])


def test_salud_es_publica(cliente: TestClient):
    datos = cliente.get("/salud").json()
    assert datos["ok"] is True
    assert datos["estado"] == "disponible"
    assert datos["clave_configurada"] is True
    assert "MemorySaver" in datos["memoria"]


# --- clave ----------------------------------------------------------------
def test_sin_clave_rechaza(cliente: TestClient, agente: AgenteFalso):
    assert enviar(cliente, "hola").status_code == 401
    assert enviar(cliente, "hola", headers={"X-Agente-Clave": "incorrecta"}).status_code == 401
    assert agente.hilos == []


def test_con_clave_responde(cliente: TestClient, agente: AgenteFalso):
    respuesta = enviar(cliente, "Analiza NVDA en US", headers=CABECERA)
    assert respuesta.status_code == 200
    resultado = respuesta.json()["result"]
    assert resultado["status"]["state"] == "completed"
    assert resultado["artifacts"][0]["parts"][0]["text"] == "respuesta del agente"
    assert resultado["status"]["message"]["parts"][0]["text"] == "respuesta del agente"


def test_acepta_authorization_bearer(cliente: TestClient):
    respuesta = enviar(cliente, "hola", headers={"Authorization": f"Bearer {CLAVE}"})
    assert respuesta.status_code == 200


def test_sin_clave_configurada_falla_cerrado(monkeypatch, agente):
    monkeypatch.delenv("AGENTE_CLAVE", raising=False)
    with TestClient(crear_app(agente)) as prueba:
        assert enviar(prueba, "hola", headers=CABECERA).status_code == 401


# --- memoria y mensajes ---------------------------------------------------
def test_context_id_es_el_hilo_de_memoria(cliente: TestClient, agente: AgenteFalso):
    enviar(cliente, "primera", context_id="conversacion-a", headers=CABECERA)
    enviar(cliente, "segunda", context_id="conversacion-a", headers=CABECERA)
    enviar(cliente, "otra", context_id="conversacion-b", headers=CABECERA)
    assert agente.hilos == ["conversacion-a", "conversacion-a", "conversacion-b"]


def test_mensaje_sin_texto_responde_que_no_puede_leerlo(cliente: TestClient, agente: AgenteFalso):
    partes = [{"kind": "file", "file": {"uri": "https://ejemplo/foto.jpg", "mimeType": "image/jpeg"}}]
    respuesta = enviar(cliente, "", partes=partes, headers=CABECERA)
    assert respuesta.status_code == 200
    texto = respuesta.json()["result"]["artifacts"][0]["parts"][0]["text"]
    assert texto == NO_LEIBLE
    assert agente.hilos == []


def test_error_del_agente_devuelve_tarea_fallida(monkeypatch):
    monkeypatch.setenv("AGENTE_CLAVE", CLAVE)
    with TestClient(crear_app(AgenteFalso(error=RuntimeError("modelo caído")))) as prueba:
        respuesta = enviar(prueba, "hola", headers=CABECERA)
    resultado = respuesta.json()["result"]
    assert resultado["status"]["state"] == "failed"
    assert "modelo caído" in resultado["status"]["message"]["parts"][0]["text"]


def test_metodo_no_soportado(cliente: TestClient):
    respuesta = cliente.post("/a2a", json={"jsonrpc": "2.0", "id": "1", "method": "tasks/get"}, headers=CABECERA)
    assert respuesta.status_code == 200
    assert respuesta.json()["error"]["code"] == -32601
