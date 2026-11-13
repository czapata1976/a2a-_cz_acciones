"""Pruebas del agente `agente_cz_A2A` en su servidor A2A propio (integración real).

Simulan a otro agente: leen la ficha pública, le envían `message/send` con la clave del agente y revisan
que el texto final traiga las cifras de las herramientas, no inventadas. Se saltan si el servidor no está
arriba. Arranque: `.venv\\Scripts\\python.exe scripts\\servidor_agente.py`.
"""
import os
import re
import uuid

import httpx
import pytest
from dotenv import load_dotenv

load_dotenv()

BASE = os.environ.get("A2A_CZZ_URL", "http://127.0.0.1:2029").rstrip("/")
CLAVE = os.environ.get("AGENTE_CLAVE", "")


def _servidor_arriba() -> bool:
    try:
        return httpx.get(f"{BASE}/salud", timeout=3).status_code == 200
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _servidor_arriba(), reason="el servidor del agente no está corriendo")


def texto_de(resultado: dict) -> str:
    """Lo que recibe el agente que invoca: los artefactos o, si no hay, el último turno del historial."""
    partes = [
        parte["text"]
        for artefacto in resultado.get("artifacts") or []
        for parte in artefacto.get("parts", [])
        if parte.get("kind") == "text"
    ]
    if not partes:
        ultimo = next((m for m in reversed(resultado.get("history") or []) if m.get("role") == "agent"), None)
        partes = [parte["text"] for parte in (ultimo or {}).get("parts", []) if parte.get("kind") == "text"]
    return "\n".join(partes)


def enviar(texto: str, context_id: str | None = None, cabeceras: dict | None = None) -> httpx.Response:
    cuerpo = {"jsonrpc": "2.0", "id": uuid.uuid4().hex, "method": "message/send", "params": {"message": {
        "role": "user", "messageId": uuid.uuid4().hex,
        "contextId": context_id or str(uuid.uuid4()),
        "parts": [{"kind": "text", "text": texto}]}}}
    cabeceras = cabeceras if cabeceras is not None else {"X-Agente-Clave": CLAVE}
    return httpx.post(f"{BASE}/a2a", json=cuerpo, headers={"Accept": "application/json", **cabeceras}, timeout=180)


def test_agent_card_publica_y_con_limites():
    respuesta = httpx.get(f"{BASE}/.well-known/agent-card.json", timeout=10)
    assert respuesta.status_code == 200
    tarjeta = respuesta.json()
    assert tarjeta["name"] == "agente_cz_A2A"
    assert tarjeta["url"].endswith("/a2a")
    assert "NO ejecuta" in tarjeta["description"]
    assert isinstance(tarjeta.get("skills"), list) and len(tarjeta["skills"]) >= 2
    assert tarjeta["authentication"]["header"] == "X-Agente-Clave"


def test_salud_publica_sin_clave():
    respuesta = httpx.get(f"{BASE}/salud", timeout=10)
    assert respuesta.status_code == 200
    assert respuesta.json()["ok"] is True


def test_sin_clave_rechaza():
    respuesta = enviar("¿Cuánto vale AAPL en US?", cabeceras={})
    assert respuesta.status_code == 401
    assert "clave" in respuesta.text.lower()


def test_message_send():
    respuesta = enviar("¿Cuánto vale AAPL en el mercado US?")
    assert respuesta.status_code == 200
    resultado = respuesta.json()["result"]
    assert resultado["status"]["state"] == "completed"
    texto = texto_de(resultado)
    # cifras de las herramientas (AAPL: 342,10 USD y PER 31,4), con punto o coma y sin el cero final
    assert re.search(r"342[.,]10?(?![0-9])", texto), texto
    assert re.search(r"31[.,]40?(?![0-9])", texto), texto
    assert "2024" not in texto, texto


def test_no_inventa_cifras_al_rechazar_una_orden():
    respuesta = enviar("Paga la compra de 10 acciones de AAPL en US por mí.")
    assert respuesta.status_code == 200
    texto = texto_de(respuesta.json()["result"])
    negativas = (
        "no ejecuto", "no realizo", "no puedo", "no efectúo", "no ejecutaré",
        "no hago", "no proceso", "no autorizo", "no llevo a cabo", "no está a mi alcance",
    )
    assert any(frase in texto.lower() for frase in negativas), texto
    assert re.search(r"342[.,]10?(?![0-9])", texto), texto
    assert not re.search(r"225[.,]50?", texto), texto


def test_memoria_por_context_id():
    contexto = str(uuid.uuid4())
    primera = texto_de(enviar("Analiza NVDA en US para un perfil moderado a 12 meses.", contexto).json()["result"])
    segunda = texto_de(enviar("¿Y a 3 meses?", contexto).json()["result"])
    assert "182" in primera
    # la segunda pregunta solo se entiende con la anterior: sigue siendo NVDA
    assert "182" in segunda


def test_mensaje_sin_texto():
    cuerpo = {"jsonrpc": "2.0", "id": "1", "method": "message/send", "params": {"message": {
        "role": "user", "messageId": "m1", "contextId": str(uuid.uuid4()),
        "parts": [{"kind": "file", "file": {"uri": "https://ejemplo/foto.jpg", "mimeType": "image/jpeg"}}]}}}
    respuesta = httpx.post(f"{BASE}/a2a", json=cuerpo, headers={"X-Agente-Clave": CLAVE}, timeout=60)
    assert respuesta.status_code == 200
    assert "No puedo leer" in texto_de(respuesta.json()["result"])
