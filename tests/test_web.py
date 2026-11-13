"""Pruebas del chat web (sin salir a la red).

El agente se sustituye por dobles de `web.a2a`, así se verifica la autenticación, el tope de cuatro
agentes, el abanico en paralelo y la síntesis. La prueba real del agente está en `test_a2a_czz.py`.
"""
from __future__ import annotations

import os

import pytest
from dotenv import load_dotenv
from fastapi.testclient import TestClient

from web import a2a
from web.almacen import Almacen, es_postgres
from web.auth import crear_cookie, hash_clave
from web.config import Settings
from web.main import NOMBRE_COOKIE, crear_app

CLAVE = "clave-de-prueba-1234"
SECRETO = "s" * 48
CABECERAS = {"X-Solicitado-Por": "chat-web"}
LOCAL = "http://127.0.0.1:2029"


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        host="127.0.0.1",
        port=8110,
        usuario="carlos",
        clave_hash=hash_clave(CLAVE, iteraciones=1000),
        secreto=SECRETO,
        horas_sesion=1.0,
        a2a_url=LOCAL,
        a2a_graph="agente_cz_A2A",
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
    """Descubrimiento y envío falsos: devuelven la URL del agente como texto."""
    llamadas: list[tuple[str, str, str]] = []

    async def descubrir(base: str, timeout: float = 15.0, clave: str = '') -> a2a.Agente:
        return agente(base)

    async def enviar(instancia: a2a.Agente, texto: str, context_id: str, timeout: float = 180.0) -> str:
        llamadas.append((instancia.base, texto, context_id))
        if instancia.base == LOCAL:
            return "síntesis del equipo"
        return f"aporte de {instancia.base}"

    monkeypatch.setattr(a2a, "descubrir", descubrir)
    monkeypatch.setattr(a2a, "enviar", enviar)
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
    assert equipo["local"]["nombre"] == "agente_cz_A2A"


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
    assert datos["respuesta"] == "síntesis del equipo"
    assert datos["error"] is None

    tipos = [paso["tipo"] for paso in datos["flujo"]]
    assert tipos == [
        "descubrimiento", "descubrimiento", "descubrimiento", "consulta", "consulta", "sintesis",
    ]
    consultas = [paso for paso in datos["flujo"] if paso["tipo"] == "consulta"]
    assert {paso["url"] for paso in consultas} == {"https://uno.example.com", "https://dos.example.com"}
    assert all(paso["estado"] == "ok" for paso in datos["flujo"])

    # las respuestas de los colegas llegaron como dato, entre etiquetas
    peticion_local = [llamada for llamada in sin_red if llamada[0] == LOCAL][-1][1]
    assert "<respuestas_agentes>" in peticion_local
    assert "aporte de https://uno.example.com" in peticion_local
    assert "aporte de https://dos.example.com" in peticion_local

    # y la ficha del equipo va en cada turno, para que reconozca a los agentes agregados
    assert "<equipo_a2a>" in peticion_local
    assert "agente-uno.example.com: revisa procesos" in peticion_local
    assert "evaluar procesos: ordena y prioriza el flujo [procesos]" in peticion_local


def test_el_equipo_es_dato_aunque_los_remotos_fallen(cliente: TestClient, monkeypatch):
    """El agente local conoce a sus colegas por la tarjeta, respondan o no en ese turno."""
    entrar(cliente)
    llamadas: list[str] = []

    async def descubrir(base: str, timeout: float = 15.0, clave: str = '') -> a2a.Agente:
        return agente(base)

    async def enviar(instancia: a2a.Agente, texto: str, context_id: str, timeout: float = 180.0) -> str:
        if instancia.base == LOCAL:
            llamadas.append(texto)
            return "no tengo un agente para eso, pero mi equipo sí: agente-uno.example.com"
        raise a2a.ErrorAgenteRemoto("sin respuesta")

    monkeypatch.setattr(a2a, "descubrir", descubrir)
    monkeypatch.setattr(a2a, "enviar", enviar)
    cliente.post("/api/agentes", json={"url": "https://uno.example.com"}, headers=CABECERAS)
    charla = cliente.post("/api/charlas", headers=CABECERAS).json()["id"]

    respuesta = cliente.post(
        f"/api/charlas/{charla}/mensaje", json={"texto": "¿Qué hace el agente uno?"}, headers=CABECERAS
    )
    assert respuesta.status_code == 200, respuesta.text
    assert llamadas, "el agente local debe recibir el turno"
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


def test_turno_sin_agente_local_avisa(cliente: TestClient, monkeypatch):
    entrar(cliente)
    charla = cliente.post("/api/charlas", headers=CABECERAS).json()["id"]

    async def descubrir(base: str, timeout: float = 15.0, clave: str = ''):
        if base == LOCAL:
            raise a2a.ErrorAgenteRemoto("sin agente local")
        return agente(base)

    async def enviar(instancia: a2a.Agente, texto: str, context_id: str, timeout: float = 180.0):
        return "aporte remoto"

    monkeypatch.setattr(a2a, "descubrir", descubrir)
    monkeypatch.setattr(a2a, "enviar", enviar)
    cliente.post("/api/agentes", json={"url": "https://uno.example.com"}, headers=CABECERAS)

    datos = cliente.post(
        f"/api/charlas/{charla}/mensaje", json={"texto": "Hola"}, headers=CABECERAS
    ).json()
    assert "aporte remoto" in datos["respuesta"]
    assert "sin síntesis" in datos["error"]
    assert datos["flujo"][-1]["tipo"] == "sintesis"
    assert datos["flujo"][-1]["estado"] == "error"


def test_turno_sin_respuestas_devuelve_502(cliente: TestClient, monkeypatch):
    entrar(cliente)
    charla = cliente.post("/api/charlas", headers=CABECERAS).json()["id"]

    async def falla(base: str, timeout: float = 15.0, clave: str = ''):
        raise a2a.ErrorAgenteRemoto("no hay agente")

    monkeypatch.setattr(a2a, "descubrir", falla)
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
    assert datos["agente"]["estado"] == "disponible"
    assert datos["equipo"]["maximo"] == 4
    assert cliente.get("/ok").json()["ok"] is True


def test_detecta_ruta_de_postgres():
    assert es_postgres("postgresql://usuario:clave@host:5432/base")
    assert es_postgres("postgres://usuario:clave@host/base")
    assert not es_postgres("web/.runtime/chat.db")
    assert not es_postgres(":memory:")


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
