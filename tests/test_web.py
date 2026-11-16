"""Pruebas del chat web (sin salir a la red).

El coordinador y los agentes remotos se sustituyen por dobles, así se verifica la autenticación, el
tope de cuatro agentes, el abanico en paralelo y el cierre del turno por el coordinador. El agente
real se prueba en `test_a2a_czz.py` y el coordinador en `test_coordinador.py`.
"""
from __future__ import annotations

import asyncio
import os
import socket
from pathlib import Path

import pytest
from dotenv import load_dotenv
from fastapi.testclient import TestClient

from web import a2a, coordinador, orquestador
from web.almacen import Almacen, es_postgres
from web.auth import crear_cookie, hash_clave
from web.config import ConfiguracionInvalida, Settings, cargar_settings
from web.main import NOMBRE_COOKIE, crear_app

from tests.a2a_falso import servidor

CLAVE = "clave-de-prueba-1234"
SECRETO = "s" * 48
CABECERAS = {"X-Solicitado-Por": "chat-web"}
COORDINADOR = "http://127.0.0.1:8120"


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        host="127.0.0.1",
        port=8110,
        usuario="carlos",
        clave_hash=hash_clave(CLAVE, iteraciones=1000),
        secreto=SECRETO,
        horas_sesion=1.0,
        coordinador_url=COORDINADOR,
        coordinador_clave="clave-del-coordinador-para-prueba",
        agente_sintesis="agente_cz_A2A",
        a2a_timeout=30.0,
        ruta_datos=str(tmp_path / "chat.db"),
    )


@pytest.fixture
def almacen() -> Almacen:
    return Almacen(":memory:")


@pytest.fixture
def cliente(settings, almacen) -> TestClient:
    with TestClient(crear_app(settings, almacen)) as prueba:
        yield prueba


def url_postgres() -> str:
    """`DATABASE_URL` del `.env`, si hay Postgres a mano."""
    load_dotenv()
    return (os.environ.get("DATABASE_URL") or "").strip()


def entrar(cliente: TestClient) -> TestClient:
    respuesta = cliente.post("/api/login", json={"usuario": "carlos", "clave": CLAVE})
    assert respuesta.status_code == 200, respuesta.text
    return cliente


def agente(base: str) -> a2a.Agente:
    return a2a.Agente(
        base=base,
        nombre=f"agente-{base.split('//')[-1]}",
        url_a2a=f"{base}/a2a/00000000-0000-0000-0000-000000000000",
        assistant_id="00000000-0000-0000-0000-000000000000",
        descripcion="revisa procesos y diseño de datos",
        habilidades=("evaluar procesos: ordena y prioriza el flujo [procesos]",),
    )


@pytest.fixture
def sin_red(monkeypatch):
    """Coordinador y agentes remotos falsos: el chat no sale a la red."""
    llamadas: list[dict] = []

    async def descubrir(base: str, timeout: float = 15.0, clave: str = '') -> a2a.Agente:
        return agente(base)

    async def enviar(instancia: a2a.Agente, texto: str, context_id: str, timeout: float = 180.0) -> str:
        llamadas.append({"tipo": "remoto", "url": instancia.base, "texto": texto})
        return f"aporte de {instancia.base}"

    async def estado(base: str, timeout: float = 10.0) -> dict:
        return {"ok": True, "agentes": [{"nombre": "agente_cz_A2A", "estado": "disponible"}]}

    async def consultar(
        base: str, clave: str, texto: str, cliente: str, agente: str = "", timeout: float = 180.0
    ) -> dict:
        llamadas.append({
            "tipo": "coordinador", "url": base, "cliente": cliente,
            "texto": texto, "agente": agente, "clave": clave,
        })
        return {
            "respuesta": "Respondió: agente_cz_A2A\nhttp://127.0.0.1:2029/a2a\n\nsíntesis del equipo",
            "agente": "agente_cz_A2A",
            "motivo": "ok",
            "respuesta_agente": "síntesis del equipo",
            "saltos": [],
        }

    monkeypatch.setattr(a2a, "descubrir", descubrir)
    monkeypatch.setattr(a2a, "enviar", enviar)
    monkeypatch.setattr(coordinador, "estado", estado)
    monkeypatch.setattr(coordinador, "consultar", consultar)
    return llamadas


# --- página y sesión ------------------------------------------------------
def test_pagina_y_estaticos_se_sirven(cliente: TestClient):
    pagina = cliente.get("/")
    assert pagina.status_code == 200
    assert "Consola A2A" in pagina.text
    assert "default-src 'self'" in pagina.headers["content-security-policy"]
    assert cliente.get("/static/app.js").status_code == 200
    assert cliente.get("/static/estilos.css").status_code == 200


def test_sin_sesion_no_hay_api(cliente: TestClient):
    assert cliente.get("/api/sesion").status_code == 401
    assert cliente.get("/api/charlas").status_code == 401


def test_login_logout_y_sesion(cliente: TestClient):
    entrar(cliente)
    assert cliente.get("/api/sesion").json()["usuario"] == "carlos"
    assert cliente.post("/api/logout").status_code == 200
    assert cliente.get("/api/sesion").status_code == 401


def test_clave_incorrecta(cliente: TestClient):
    respuesta = cliente.post("/api/login", json={"usuario": "carlos", "clave": "otra"})
    assert respuesta.status_code == 401
    assert NOMBRE_COOKIE not in respuesta.cookies


def test_usuario_incorrecto(cliente: TestClient):
    respuesta = cliente.post("/api/login", json={"usuario": "intruso", "clave": CLAVE})
    assert respuesta.status_code == 401


def test_cookie_manipulada_y_vencida(settings: Settings, cliente: TestClient):
    valida = crear_cookie("carlos", SECRETO, 1)
    cliente.cookies.set(NOMBRE_COOKIE, valida[:-2] + "xx")
    assert cliente.get("/api/sesion").status_code == 401

    cliente.cookies.set(NOMBRE_COOKIE, crear_cookie("carlos", SECRETO, -1))
    assert cliente.get("/api/sesion").status_code == 401

    cliente.cookies.set(NOMBRE_COOKIE, crear_cookie("carlos", "otro-secreto-de-48-caracteres-xxxxxxxxxxxx", 1))
    assert cliente.get("/api/sesion").status_code == 401


def test_login_devuelve_token_de_respaldo(cliente: TestClient):
    respuesta = cliente.post("/api/login", json={"usuario": "carlos", "clave": CLAVE})
    token = respuesta.json()["token"]
    # El token sirve como cabecera cuando el navegador descarta la cookie.
    cliente.cookies.clear()
    assert cliente.get("/api/sesion").status_code == 401
    autorizado = cliente.get("/api/sesion", headers={"Authorization": f"Bearer {token}"})
    assert autorizado.status_code == 200
    assert autorizado.json()["usuario"] == "carlos"
    # La escritura sigue exigiendo la cabecera de la página.
    assert cliente.post(
        "/api/charlas", headers={"Authorization": f"Bearer {token}"}
    ).status_code == 403
    assert cliente.post(
        "/api/charlas", headers={"Authorization": f"Bearer {token}", **CABECERAS}
    ).status_code == 200


def test_token_invalido_es_rechazado(cliente: TestClient):
    assert cliente.get(
        "/api/sesion", headers={"Authorization": "Bearer inventado.firma"}
    ).status_code == 401
    sesion = cliente.post("/api/login", json={"usuario": "carlos", "clave": CLAVE}).json()
    cliente.cookies.clear()
    manipulado = sesion["token"][:-2] + "xx"
    assert cliente.get(
        "/api/sesion", headers={"Authorization": f"Bearer {manipulado}"}
    ).status_code == 401


def test_bloqueo_tras_cinco_fallos(cliente: TestClient):
    for _ in range(5):
        assert cliente.post("/api/login", json={"usuario": "carlos", "clave": "mala"}).status_code == 401
    assert cliente.post("/api/login", json={"usuario": "carlos", "clave": CLAVE}).status_code == 429


def test_escritura_sin_cabecera_de_pagina(cliente: TestClient):
    entrar(cliente)
    assert cliente.post("/api/charlas").status_code == 403


# --- equipo de agentes ----------------------------------------------------
def test_equipo_valida_url(cliente: TestClient, sin_red):
    entrar(cliente)
    assert cliente.post("/api/agentes", json={"url": "ftp://agente"}, headers=CABECERAS).status_code == 400
    assert cliente.post("/api/agentes", json={"url": "http://agente?a=1"}, headers=CABECERAS).status_code == 400

    alta = cliente.post("/api/agentes", json={"url": "https://uno.trycloudflare.com/"}, headers=CABECERAS)
    assert alta.status_code == 200
    assert alta.json()["url"] == "https://uno.trycloudflare.com"

    equipo = cliente.get("/api/agentes").json()
    assert equipo["maximo"] == 4
    assert [item["url"] for item in equipo["remotos"]] == ["https://uno.trycloudflare.com"]
    assert equipo["local"]["nombre"] == "coordinador"


def test_tarjeta_con_http_usa_el_esquema_de_la_url_escrita():
    # Cloud Run anuncia `http://` aunque se le hable por HTTPS: el endpoint debe quedarse en https.
    tarjeta = {
        "name": "agente_bryhan",
        "url": "http://agente.example.run.app/a2a/abc",
        "protocolVersion": "0.3.0",
    }
    agente_remoto = a2a._agente_de_tarjeta(tarjeta, "https://agente.example.run.app", None)
    assert agente_remoto.url_a2a == "https://agente.example.run.app/a2a/abc"
    assert agente_remoto.nombre == "agente_bryhan"


def test_tarjeta_local_detras_de_tunel_se_reescribe():
    # Un agente por túnel anuncia su 127.0.0.1, que solo existe en su máquina.
    tarjeta = {"name": "local", "url": "http://127.0.0.1:2029/a2a/xyz"}
    agente_remoto = a2a._agente_de_tarjeta(tarjeta, "https://algo.trycloudflare.com", None)
    assert agente_remoto.url_a2a == "https://algo.trycloudflare.com/a2a/xyz"


def test_url_pegada_con_endpoint_respeta_la_ruta_del_usuario():
    # El usuario puede pegar `https://host/a2a/<uuid>` en vez de la raíz.
    anunciado = a2a.Agente(
        base="https://host.example.com", nombre="remoto",
        url_a2a="https://host.example.com/a2a/otro-id", assistant_id=None,
    )
    assert a2a._con_ruta(anunciado, "https://host.example.com", "/a2a/elegido").url_a2a == \
        "https://host.example.com/a2a/elegido"
    # Sin ruta del usuario, se usa la anunciada.
    assert a2a._con_ruta(anunciado, "https://host.example.com", "").url_a2a == \
        "https://host.example.com/a2a/otro-id"


def test_url_de_la_ficha_se_trata_como_raiz():
    # Pegar la tarjeta (`/.well-known/agent-card.json`) no debe convertirse en el endpoint.
    anunciado = a2a.Agente(
        base="https://host.example.com", nombre="remoto",
        url_a2a="https://host.example.com/a2a/abc", assistant_id=None,
    )
    ruta = a2a.ruta_de_usuario("https://host.example.com/.well-known/agent-card.json")
    assert a2a._con_ruta(anunciado, "https://host.example.com", ruta).url_a2a == \
        "https://host.example.com/a2a/abc"


def test_tarjeta_que_pide_clave_por_cabecera_dice_cual():
    # Ficha real del agente de auditoría: `supportedInterfaces`, `securitySchemes` y su requisito.
    tarjeta = {
        "name": "agente-ale-ubi",
        "supportedInterfaces": [
            {
                "url": "https://agente.example.com/a2a",
                "protocolBinding": "JSONRPC",
                "protocolVersion": "1.0",
            }
        ],
        "securitySchemes": {
            "apiKey": {
                "apiKeySecurityScheme": {
                    "description": "Clave de acceso configurada en el servidor (API_KEYS).",
                    "location": "header",
                    "name": "X-API-Key",
                }
            }
        },
        "securityRequirements": [{"schemes": {"apiKey": {}}}],
    }
    remoto = a2a._agente_de_tarjeta(tarjeta, "https://agente.example.com", None, "k-123")
    assert remoto.requiere_clave
    assert remoto.cabecera_clave == "X-API-Key"
    cabeceras = a2a.cabeceras_de(remoto)
    assert cabeceras["X-API-Key"] == "k-123"
    # Su endpoint exige la versión de protocolo que anuncia la interfaz.
    assert cabeceras["A2A-Version"] == "1.0"
    assert "Authorization" not in cabeceras


def test_tarjeta_con_bearer_usa_authorization():
    tarjeta = {
        "name": "remoto",
        "url": "https://host.example.com/a2a",
        "securitySchemes": {"bearer": {"type": "http", "scheme": "bearer"}},
        "securityRequirements": [{"schemes": {"bearer": {}}}],
    }
    remoto = a2a._agente_de_tarjeta(tarjeta, "https://host.example.com", None, "k")
    assert remoto.cabecera_clave == "Authorization"
    assert a2a.cabeceras_de(remoto)["Authorization"] == "Bearer k"


def test_ficha_propia_con_authentication_indica_su_cabecera():
    tarjeta = {
        "name": "agente_cz_A2A",
        "url": "https://host.example.com/a2a",
        "authentication": {"schemes": ["apiKey"], "header": "X-Agente-Clave"},
    }
    remoto = a2a._agente_de_tarjeta(tarjeta, "https://host.example.com", None, "k")
    assert remoto.requiere_clave
    assert a2a.cabeceras_de(remoto)["X-Agente-Clave"] == "k"


def test_ficha_que_declara_esquema_sin_requisito_no_exige_clave():
    """Como agente_bryhan: anuncia bearerAuth, pero securityRequirements está vacío."""
    tarjeta = {
        "name": "agente_bryhan",
        "url": "https://host.example.com/a2a",
        "securitySchemes": {"bearerAuth": {"type": "http", "scheme": "bearer"}},
        "securityRequirements": None,
    }
    remoto = a2a._agente_de_tarjeta(tarjeta, "https://host.example.com", None)
    assert remoto.requiere_clave is False
    # La cabecera se recuerda por si el usuario guarda una clave, y no se envía credencial vacía.
    assert remoto.cabecera_clave == "Authorization"
    assert a2a.cabeceras_de(remoto) == {"Accept": "application/json"}
    # Con clave guardada, viaja en la cabecera que declara la ficha.
    con_clave = a2a._agente_de_tarjeta(tarjeta, "https://host.example.com", None, "k")
    assert a2a.cabeceras_de(con_clave)["Authorization"] == "Bearer k"


def test_tarjeta_sin_esquema_no_exige_clave():
    tarjeta = {"name": "remoto", "url": "https://host.example.com/a2a"}
    remoto = a2a._agente_de_tarjeta(tarjeta, "https://host.example.com", None, "k")
    assert remoto.requiere_clave is False
    # Sin declaración se mantiene la cabecera propia del proyecto.
    assert a2a.cabeceras_de(remoto) == {"Accept": "application/json", "X-Agente-Clave": "k"}
    # Y sin clave no se envía credencial ninguna.
    assert a2a.cabeceras_de(a2a._agente_de_tarjeta(tarjeta, "https://host.example.com", None)) == {
        "Accept": "application/json"
    }


def test_la_ruta_a2a_es_la_raiz_del_agente():
    # Pegar el endpoint que anuncia la ficha (`/a2a`) no debe registrar un segundo agente igual.
    assert a2a.normalizar_url("https://host.example.com/a2a") == "https://host.example.com"
    assert a2a.normalizar_url("https://host.example.com/a2a/") == "https://host.example.com"
    # Con identificador sí es un endpoint propio (Cloud Run) y se respeta.
    assert a2a.normalizar_url("https://host.example.com/a2a/abc-123") == \
        "https://host.example.com/a2a/abc-123"


def test_una_url_http_no_baja_el_esquema_que_anuncia_la_ficha():
    # La clave de un agente no debe viajar sin cifrar solo porque la URL guardada diga http.
    tarjeta = {"name": "ale", "url": "https://agente.example.com/a2a"}
    remoto = a2a._agente_de_tarjeta(tarjeta, "http://agente.example.com", None)
    assert remoto.url_a2a == "https://agente.example.com/a2a"


TARJETA_AUDITORIA = {
    "name": "agente-ale-ubi",
    "supportedInterfaces": [
        {"url": "{base}/a2a", "protocolBinding": "JSONRPC", "protocolVersion": "1.0"}
    ],
    "securitySchemes": {
        "apiKey": {"apiKeySecurityScheme": {"location": "header", "name": "X-API-Key"}}
    },
    "securityRequirements": [{"schemes": {"apiKey": {}}}],
}


def test_envia_la_clave_donde_la_pide_la_ficha_aunque_el_agente_quiera_otra_version():
    """Caso real: X-API-Key y un manejador que espera `0.3` aunque la ficha anuncie `1.0`."""
    with servidor(TARJETA_AUDITORIA, clave="k-123", versiones=("0.3",), texto="no cumple") as falso:
        agente = asyncio.run(a2a.descubrir(falso.base, clave="k-123"))
        assert agente.cabecera_clave == "X-API-Key"
        texto = asyncio.run(a2a.enviar(agente, "¿cumple la empresa?", "ctx-1"))

    assert texto == "no cumple"
    consultas = [p for p in falso.peticiones if p["path"].rstrip("/") == "/a2a"]
    assert [p["headers"].get("A2A-Version") for p in consultas] == ["1.0", "0.3"]
    assert all(p["headers"].get("X-API-Key") == "k-123" for p in consultas)


def test_lee_una_respuesta_que_es_un_mensaje_y_no_una_tarea():
    with servidor(TARJETA_AUDITORIA, clave="k-123", texto="alerta en el SII") as falso:
        agente = asyncio.run(a2a.descubrir(falso.base, clave="k-123"))
        assert asyncio.run(a2a.enviar(agente, "hola", "ctx-2")) == "alerta en el SII"


def test_sin_cabecera_de_version_tambien_habla_con_el_agente():
    # Tercera variante: hay servidores que rechazan toda versión y solo aceptan sin `A2A-Version`.
    with servidor(TARJETA_AUDITORIA, clave="k-123", versiones=("0.2",), texto="responde igual") as falso:
        agente = asyncio.run(a2a.descubrir(falso.base, clave="k-123"))
        assert asyncio.run(a2a.enviar(agente, "hola", "ctx-3")) == "responde igual"

    consultas = [p for p in falso.peticiones if p["path"].rstrip("/") == "/a2a"]
    assert [p["headers"].get("A2A-Version") for p in consultas] == ["1.0", "0.3", None]


def test_agente_que_no_escucha_se_informa_por_su_nombre():
    # Sin conexión no hay nada que reintentar: el aviso habla del agente caído, no de su versión.
    with socket.socket() as libre:
        libre.bind(("127.0.0.1", 0))
        puerto = libre.getsockname()[1]
    remoto = a2a.Agente(
        base=f"http://127.0.0.1:{puerto}",
        nombre="agente-caido",
        url_a2a=f"http://127.0.0.1:{puerto}/a2a",
        assistant_id=None,
        version_protocolo="1.0",
    )
    with pytest.raises(a2a.ErrorAgenteRemoto) as error:
        asyncio.run(a2a.enviar(remoto, "hola", "ctx-4", timeout=8.0))
    assert "No pude comunicarme con agente-caido" in str(error.value)


def test_tarjeta_aporta_descripcion_y_habilidades():
    tarjeta = {
        "name": "agente_bryhan",
        "description": "perfil, procesos y diseño de datos",
        "url": "https://agente.example.run.app/a2a",
        "skills": [
            {"name": "Evaluar procesos", "description": "ordena y prioriza flujos", "tags": ["procesos"]},
            {"name": "Comparar IA", "description": "compara modelos y herramientas"},
            "no-es-un-objeto",
        ],
    }
    agente_remoto = a2a._agente_de_tarjeta(tarjeta, "https://agente.example.run.app", None)
    assert agente_remoto.descripcion.startswith("perfil, procesos")
    assert agente_remoto.habilidades == (
        "Evaluar procesos: ordena y prioriza flujos [procesos]",
        "Comparar IA: compara modelos y herramientas",
    )


def test_equipo_tope_de_cuatro(cliente: TestClient, sin_red):
    entrar(cliente)
    for numero in range(4):
        alta = cliente.post(
            "/api/agentes", json={"url": f"https://agente{numero}.example.com"}, headers=CABECERAS
        )
        assert alta.status_code == 200, alta.text
    quinta = cliente.post("/api/agentes", json={"url": "https://agente5.example.com"}, headers=CABECERAS)
    assert quinta.status_code == 409
    assert len(cliente.get("/api/agentes").json()["remotos"]) == 4


def test_equipo_agente_inalcanzable(cliente: TestClient, monkeypatch):
    entrar(cliente)

    async def descubre(base: str, timeout: float = 15.0, clave: str = '') -> a2a.Agente:
        return agente(base)

    monkeypatch.setattr(a2a, "descubrir", descubre)
    assert cliente.post(
        "/api/agentes", json={"url": "https://caido.example.com"}, headers=CABECERAS
    ).status_code == 200

    async def falla(base: str, timeout: float = 15.0, clave: str = ''):
        raise a2a.ErrorAgenteRemoto(f"{base} no respondió a tiempo.")

    monkeypatch.setattr(a2a, "descubrir", falla)
    respuesta = cliente.post("/api/agentes", json={"url": "https://otro.example.com"}, headers=CABECERAS)
    assert respuesta.status_code == 400
    assert "no respondió" in respuesta.json()["detail"]
    assert cliente.get("/api/agentes").json()["remotos"][0]["estado"] == "no disponible"


def test_la_clave_del_agente_se_guarda_y_llega_al_turno(cliente: TestClient, monkeypatch):
    entrar(cliente)
    vistas: dict[str, str] = {}

    async def descubrir(base: str, timeout: float = 15.0, clave: str = "") -> a2a.Agente:
        vistas[base] = clave
        return agente(base)

    async def enviar(instancia: a2a.Agente, texto: str, context_id: str, timeout: float = 180.0) -> str:
        return "síntesis del equipo" if instancia.base == LOCAL else "aporte"

    monkeypatch.setattr(a2a, "descubrir", descubrir)
    monkeypatch.setattr(a2a, "enviar", enviar)

    alta = cliente.post(
        "/api/agentes",
        json={"url": "https://ale.example.com", "clave": "clave-de-ale"},
        headers=CABECERAS,
    )
    assert alta.status_code == 200
    # La credencial se guarda, pero nunca vuelve por la API.
    assert "clave-de-ale" not in cliente.get("/api/agentes").text

    charla = cliente.post("/api/charlas", headers=CABECERAS).json()["id"]
    cliente.post(f"/api/charlas/{charla}/mensaje", json={"texto": "¿cumple?"}, headers=CABECERAS)
    assert vistas["https://ale.example.com"] == "clave-de-ale"

    # Volver a agregarlo sin clave (por ejemplo para refrescar el nombre) no la borra.
    cliente.post("/api/agentes", json={"url": "https://ale.example.com"}, headers=CABECERAS)
    charla = cliente.post("/api/charlas", headers=CABECERAS).json()["id"]
    cliente.post(f"/api/charlas/{charla}/mensaje", json={"texto": "otra"}, headers=CABECERAS)
    assert vistas["https://ale.example.com"] == "clave-de-ale"


def test_panel_avisa_cuando_falta_la_clave(cliente: TestClient, monkeypatch):
    entrar(cliente)

    async def descubrir(base: str, timeout: float = 15.0, clave: str = "") -> a2a.Agente:
        return a2a.Agente(
            base=base,
            nombre="agente-ale-ubi",
            url_a2a=f"{base}/a2a",
            assistant_id=None,
            clave=clave,
            requiere_clave=True,
            cabecera_clave="X-API-Key",
        )

    monkeypatch.setattr(a2a, "descubrir", descubrir)
    cliente.post("/api/agentes", json={"url": "https://ale.example.com"}, headers=CABECERAS)

    remoto = cliente.get("/api/agentes").json()["remotos"][0]
    assert remoto["estado"] == "requiere clave"
    assert "X-API-Key" in remoto["detalle"]

    cliente.post(
        "/api/agentes",
        json={"url": "https://ale.example.com", "clave": "k"},
        headers=CABECERAS,
    )
    assert cliente.get("/api/agentes").json()["remotos"][0]["estado"] == "disponible"


def test_quitar_agente(cliente: TestClient, sin_red):
    entrar(cliente)
    cliente.post("/api/agentes", json={"url": "https://uno.example.com"}, headers=CABECERAS)
    respuesta = cliente.request(
        "DELETE", "/api/agentes", json={"url": "https://uno.example.com"}, headers=CABECERAS
    )
    assert respuesta.status_code == 200
    assert cliente.get("/api/agentes").json()["remotos"] == []
    repetido = cliente.request(
        "DELETE", "/api/agentes", json={"url": "https://uno.example.com"}, headers=CABECERAS
    )
    assert repetido.status_code == 404


# --- turno de chat --------------------------------------------------------
def test_turno_consulta_remotos_y_sintetiza(cliente: TestClient, sin_red):
    entrar(cliente)
    for url in ("https://uno.example.com", "https://dos.example.com"):
        cliente.post("/api/agentes", json={"url": url}, headers=CABECERAS)
    charla = cliente.post("/api/charlas", headers=CABECERAS).json()["id"]

    respuesta = cliente.post(
        f"/api/charlas/{charla}/mensaje", json={"texto": "Analiza NVDA en US"}, headers=CABECERAS
    )
    assert respuesta.status_code == 200, respuesta.text
    datos = respuesta.json()
    # la respuesta abre diciendo quién del equipo la aportó y luego el texto del agente
    assert datos["respuesta"] == (
        "**Respondió**: agente-uno.example.com y agente-dos.example.com\n\nsíntesis del equipo"
    )
    assert datos["error"] is None

    tipos = [paso["tipo"] for paso in datos["flujo"]]
    assert tipos == [
        "descubrimiento", "descubrimiento", "descubrimiento", "consulta", "consulta", "sintesis",
    ]
    consultas = [paso for paso in datos["flujo"] if paso["tipo"] == "consulta"]
    assert {paso["url"] for paso in consultas} == {"https://uno.example.com", "https://dos.example.com"}
    assert all(paso["estado"] == "ok" for paso in datos["flujo"])

    # las respuestas de los colegas llegaron como dato, entre etiquetas
    cierre = [llamada for llamada in sin_red if llamada["tipo"] == "coordinador"][-1]
    peticion_local = cierre["texto"]
    assert "<respuestas_agentes>" in peticion_local
    assert "aporte de https://uno.example.com" in peticion_local
    assert "aporte de https://dos.example.com" in peticion_local
    # el turno se cierra en el coordinador, con su clave y con el agente que sintetiza fijado
    assert cierre["url"] == COORDINADOR
    assert cierre["clave"] == "clave-del-coordinador-para-prueba"
    assert cierre["agente"] == "agente_cz_A2A"
    assert cierre["cliente"] == f"web:{charla}"

    # y la ficha del equipo va en cada turno, para que reconozca a los agentes agregados
    assert "<equipo_a2a>" in peticion_local
    assert "agente-uno.example.com: revisa procesos" in peticion_local
    assert "evaluar procesos: ordena y prioriza el flujo [procesos]" in peticion_local


def test_el_equipo_es_dato_aunque_los_remotos_fallen(cliente: TestClient, monkeypatch):
    """El agente conoce a sus colegas por la tarjeta, respondan o no en ese turno."""
    entrar(cliente)
    llamadas: list[str] = []

    async def descubrir(base: str, timeout: float = 15.0, clave: str = '') -> a2a.Agente:
        return agente(base)

    async def enviar(instancia: a2a.Agente, texto: str, context_id: str, timeout: float = 180.0) -> str:
        raise a2a.ErrorAgenteRemoto("sin respuesta")

    async def estado(base: str, timeout: float = 10.0) -> dict:
        return {"ok": True, "agentes": [{"nombre": "agente_cz_A2A", "estado": "disponible"}]}

    async def consultar(
        base: str, clave: str, texto: str, cliente: str, agente: str = "", timeout: float = 180.0
    ) -> dict:
        llamadas.append(texto)
        return {
            "respuesta": "Respondió: agente_cz_A2A\n\nno tengo un agente para eso, pero mi equipo sí",
            "agente": "agente_cz_A2A",
            "motivo": "ok",
            "respuesta_agente": "no tengo un agente para eso, pero mi equipo sí: agente-uno.example.com",
            "saltos": [],
        }

    monkeypatch.setattr(a2a, "descubrir", descubrir)
    monkeypatch.setattr(a2a, "enviar", enviar)
    monkeypatch.setattr(coordinador, "estado", estado)
    monkeypatch.setattr(coordinador, "consultar", consultar)
    cliente.post("/api/agentes", json={"url": "https://uno.example.com"}, headers=CABECERAS)
    charla = cliente.post("/api/charlas", headers=CABECERAS).json()["id"]

    respuesta = cliente.post(
        f"/api/charlas/{charla}/mensaje", json={"texto": "¿Qué hace el agente uno?"}, headers=CABECERAS
    )
    assert respuesta.status_code == 200, respuesta.text
    assert llamadas, "el coordinador debe cerrar el turno"
    assert "<equipo_a2a>" in llamadas[-1]
    assert "agente-uno.example.com" in llamadas[-1]
    assert "<respuestas_agentes>" not in llamadas[-1]


def test_turno_guarda_conversacion(cliente: TestClient, sin_red):
    entrar(cliente)
    charla = cliente.post("/api/charlas", headers=CABECERAS).json()["id"]
    cliente.post(f"/api/charlas/{charla}/mensaje", json={"texto": "Hola"}, headers=CABECERAS)

    detalle = cliente.get(f"/api/charlas/{charla}").json()
    assert [mensaje["rol"] for mensaje in detalle["mensajes"]] == ["user", "assistant"]
    assert detalle["mensajes"][1]["texto"] == "síntesis del equipo"
    assert detalle["mensajes"][1]["flujo"]
    assert cliente.get("/api/charlas").json()[0]["mensajes"] == 2


def test_si_el_agente_deriva_el_tema_se_entrega_la_respuesta_del_colega(cliente: TestClient, monkeypatch):
    """Caso real: el agente del proyecto dice «fuera de alcance» y el colega ya respondió."""
    entrar(cliente)

    async def descubrir(base: str, timeout: float = 15.0, clave: str = '') -> a2a.Agente:
        return agente(base)

    async def enviar(instancia: a2a.Agente, texto: str, context_id: str, timeout: float = 180.0) -> str:
        return "**No cumple.** Declaraciones al día: no. Multa 2025 de la CMF por entrega tardía de EEFF."

    async def estado(base: str, timeout: float = 10.0) -> dict:
        return {"ok": True, "agentes": [{"nombre": "agente_cz_A2A", "estado": "disponible"}]}

    async def consultar(
        base: str, clave: str, texto: str, cliente: str, agente: str = "", timeout: float = 180.0
    ) -> dict:
        negativa = (
            "Fuera de alcance: contingencias normativas, tributarias, legales o regulatorias.\n"
            "Motivo: la consulta pide evaluar cumplimiento."
        )
        return {
            "respuesta": f"Respondió: agente_cz_A2A\n\n{negativa}",
            "agente": "agente_cz_A2A",
            "motivo": "ok",
            "respuesta_agente": negativa,
            "saltos": [],
        }

    monkeypatch.setattr(a2a, "descubrir", descubrir)
    monkeypatch.setattr(a2a, "enviar", enviar)
    monkeypatch.setattr(coordinador, "estado", estado)
    monkeypatch.setattr(coordinador, "consultar", consultar)
    cliente.post(
        "/api/agentes", json={"url": "https://ale.example.com", "clave": "k"}, headers=CABECERAS
    )
    charla = cliente.post("/api/charlas", headers=CABECERAS).json()["id"]

    datos = cliente.post(
        f"/api/charlas/{charla}/mensaje",
        json={"texto": "¿Cumple con la normativa la empresa 77.987.654-3?"},
        headers=CABECERAS,
    ).json()

    # el usuario ve la respuesta del colega, con su texto intacto y a nombre de quién la dio
    assert "No cumple" in datos["respuesta"]
    assert "Multa 2025 de la CMF" in datos["respuesta"]
    assert "agente-ale.example.com" in datos["respuesta"]
    assert "Fuera de alcance" not in datos["respuesta"]
    assert datos["respuesta"].startswith("**agente-ale.example.com**")
    assert datos["error"] is None
    assert "fuera de su alcance" in datos["flujo"][-1]["detalle"]


def test_si_el_agente_deriva_y_nadie_respondio_se_respeta_su_negativa(cliente: TestClient, monkeypatch):
    entrar(cliente)
    negativa = "Fuera de alcance: contingencias normativas, tributarias, legales o regulatorias."

    async def descubrir(base: str, timeout: float = 15.0, clave: str = '') -> a2a.Agente:
        raise a2a.ErrorAgenteRemoto("sin tarjeta")

    async def estado(base: str, timeout: float = 10.0) -> dict:
        return {"ok": True, "agentes": [{"nombre": "agente_cz_A2A", "estado": "disponible"}]}

    async def consultar(
        base: str, clave: str, texto: str, cliente: str, agente: str = "", timeout: float = 180.0
    ) -> dict:
        return {
            "respuesta": negativa, "agente": "agente_cz_A2A", "motivo": "ok",
            "respuesta_agente": negativa, "saltos": [],
        }

    monkeypatch.setattr(a2a, "descubrir", descubrir)
    monkeypatch.setattr(coordinador, "estado", estado)
    monkeypatch.setattr(coordinador, "consultar", consultar)
    cliente.post("/api/agentes", json={"url": "https://uno.example.com"}, headers=CABECERAS)
    charla = cliente.post("/api/charlas", headers=CABECERAS).json()["id"]

    datos = cliente.post(
        f"/api/charlas/{charla}/mensaje", json={"texto": "¿Cuánto impuesto pago por NVDA?"},
        headers=CABECERAS,
    ).json()
    assert datos["respuesta"] == negativa
    assert datos["error"] is None


def test_el_turno_pide_entregar_el_aporte_cuando_el_tema_queda_fuera_de_alcance():
    peticion = orquestador.mensaje_de_sintesis(
        "¿Cumple con la normativa la empresa 77.987.654-3?",
        [(agente("https://ale.example.com"), "**No cumple.** Multa de la CMF.")],
        "agente_cz_A2A",
        [agente("https://ale.example.com")],
    )
    assert "<respuestas_agentes>" in peticion
    assert "la respuesta del turno es la suya" in peticion
    # y el turno pide no abrir con el veredicto del colega como si fuera propio
    assert "Empieza nombrando al agente del equipo" in peticion


def test_la_respuesta_abre_con_quien_respondio():
    aportes = [(agente("https://ale.example.com"), "**No cumple.** Multa de la CMF.")]
    texto = orquestador.con_atribucion("**No cumple.** Multa de la CMF en 2025.", aportes)
    assert texto.startswith("**Respondió**: agente-ale.example.com")
    assert "**No cumple.**" in texto  # el contenido del agente no se altera


def test_si_el_texto_ya_nombra_al_colega_no_se_toca():
    aportes = [(agente("https://ale.example.com"), "**No cumple.** Multa de la CMF.")]
    original = "**Agente responsable**: agente-ale.example.com\n\n**No cumple.** Multa de la CMF."
    assert orquestador.con_atribucion(original, aportes) == original


def test_sin_aportes_la_respuesta_queda_igual():
    assert orquestador.con_atribucion("Análisis de SQM-B", []) == "Análisis de SQM-B"


def test_turno_sin_coordinador_avisa(cliente: TestClient, monkeypatch):
    entrar(cliente)
    charla = cliente.post("/api/charlas", headers=CABECERAS).json()["id"]

    async def descubrir(base: str, timeout: float = 15.0, clave: str = ''):
        return agente(base)

    async def enviar(instancia: a2a.Agente, texto: str, context_id: str, timeout: float = 180.0):
        return "aporte remoto"

    async def sin_coordinador(base: str, timeout: float = 10.0):
        raise coordinador.ErrorCoordinador("sin coordinador")

    monkeypatch.setattr(a2a, "descubrir", descubrir)
    monkeypatch.setattr(a2a, "enviar", enviar)
    monkeypatch.setattr(coordinador, "estado", sin_coordinador)
    cliente.post("/api/agentes", json={"url": "https://uno.example.com"}, headers=CABECERAS)

    datos = cliente.post(
        f"/api/charlas/{charla}/mensaje", json={"texto": "Hola"}, headers=CABECERAS
    ).json()
    assert "aporte remoto" in datos["respuesta"]
    assert "coordinador" in datos["error"]
    assert datos["flujo"][-1]["tipo"] == "sintesis"
    assert datos["flujo"][-1]["estado"] == "error"


def test_turno_sin_respuestas_devuelve_502(cliente: TestClient, monkeypatch):
    entrar(cliente)
    charla = cliente.post("/api/charlas", headers=CABECERAS).json()["id"]

    async def falla(base: str, timeout: float = 15.0, clave: str = ''):
        raise a2a.ErrorAgenteRemoto("no hay agente")

    async def sin_coordinador(base: str, timeout: float = 10.0):
        raise coordinador.ErrorCoordinador("no hay coordinador")

    monkeypatch.setattr(a2a, "descubrir", falla)
    monkeypatch.setattr(coordinador, "estado", sin_coordinador)
    respuesta = cliente.post(
        f"/api/charlas/{charla}/mensaje", json={"texto": "Hola"}, headers=CABECERAS
    )
    assert respuesta.status_code == 502
    assert respuesta.json()["flujo"][0]["estado"] == "error"


def test_charla_inexistente(cliente: TestClient, sin_red):
    entrar(cliente)
    assert cliente.get("/api/charlas/no-existe").status_code == 404
    assert cliente.post(
        "/api/charlas/no-existe/mensaje", json={"texto": "Hola"}, headers=CABECERAS
    ).status_code == 404


def test_salud_informa_equipo(cliente: TestClient, sin_red):
    entrar(cliente)
    datos = cliente.get("/salud").json()
    assert datos["coordinador"]["estado"] == "disponible"
    assert datos["equipo"]["maximo"] == 4
    assert cliente.get("/ok").json()["ok"] is True


def test_conserva_solo_las_tres_conversaciones_ultimas(cliente: TestClient, sin_red):
    entrar(cliente)
    creadas = [
        cliente.post("/api/charlas", headers=CABECERAS).json()["id"] for _ in range(5)
    ]
    guardadas = [charla["id"] for charla in cliente.get("/api/charlas").json()]
    assert guardadas == list(reversed(creadas[-3:]))
    for vieja in creadas[:2]:
        assert cliente.get(f"/api/charlas/{vieja}").status_code == 404


def test_pagina_enlaza_el_diagrama_de_arquitectura(cliente: TestClient):
    pagina = cliente.get("/").text
    assert "/static/arquitectura.svg" in pagina
    diagrama = cliente.get("/static/arquitectura.svg")
    assert diagrama.status_code == 200
    assert "image/svg+xml" in diagrama.headers["content-type"]
    assert "Chat web" in diagrama.text and "Telegram" in diagrama.text


def test_ejemplos_incluyen_preguntas_abiertas_al_equipo(cliente: TestClient):
    guion = cliente.get("/static/app.js").text
    assert "¿Qué agentes forman el equipo y qué hace cada uno?" in guion
    assert "¿Quién del equipo puede ayudarme a automatizar un proceso?" in guion
    assert "¿Qué observaciones tiene en el SII el RUT 77.987.654-3?" in guion
    assert "todavía no defino mi perfil de riesgo" not in guion


def test_detecta_ruta_de_postgres():
    assert es_postgres("postgresql://usuario:clave@host:5432/base")
    assert es_postgres("postgres://usuario:clave@host/base")
    assert not es_postgres("web/.runtime/chat.db")
    assert not es_postgres(":memory:")


def test_el_chat_y_los_canales_no_guardan_la_clave_del_agente():
    """El agente solo responde al coordinador: nadie más conoce su clave ni su URL."""
    raiz = Path(__file__).resolve().parents[1]
    for relativo in (
        "web/config.py",
        "web/main.py",
        "web/orquestador.py",
        "web/coordinador.py",
        "canales/config.py",
        "canales/main.py",
        "canales/coordinador.py",
    ):
        texto = (raiz / relativo).read_text(encoding="utf-8")
        for prohibido in ("AGENTE_CLAVE", "A2A_CZZ_CLAVE", "X-Agente-Clave", "message/send"):
            assert prohibido not in texto, f"{relativo} no debe conocer {prohibido}"


def test_las_settings_del_chat_exigen_la_clave_del_coordinador(monkeypatch, tmp_path):
    monkeypatch.setattr("web.config.load_dotenv", lambda *args, **kwargs: None)
    monkeypatch.setenv("WEB_USUARIO", "carlos")
    monkeypatch.setenv("WEB_CLAVE_HASH", hash_clave("clave", iteraciones=1000))
    monkeypatch.setenv("WEB_SECRETO", "s" * 48)
    monkeypatch.setenv("WEB_DATOS", str(tmp_path / "chat.db"))
    monkeypatch.delenv("COORDINADOR_CLAVE", raising=False)
    with pytest.raises(ConfiguracionInvalida):
        cargar_settings()


def test_almacen_postgres_guarda_borra_y_usa_tablas_propias():
    url = url_postgres()
    if not url:
        pytest.skip("sin DATABASE_URL: no hay Postgres para probar")
    almacen = Almacen(url)
    try:
        charla = almacen.crear_charla()
        almacen.agregar_mensaje(charla, "user", "prueba postgres", [{"tipo": "prueba"}])
        almacen.agregar_mensaje(charla, "assistant", "respuesta")
        assert almacen.existe_charla(charla)
        mensajes = almacen.mensajes(charla)
        assert [m["rol"] for m in mensajes] == ["user", "assistant"]
        assert mensajes[0]["flujo"] == [{"tipo": "prueba"}]
        assert almacen.borrar_charla(charla)
        assert not almacen.existe_charla(charla)
        assert almacen.mensajes(charla) == []
    finally:
        almacen.cerrar()
