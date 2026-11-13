"""Aplicación FastAPI del chat web de `agente_cz_A2A`.

Arranque recomendado:

    .venv\\Scripts\\python.exe scripts\\servidor_web.py

La página es un cliente A2A más: habla con el agente local (síntesis) y con hasta cuatro agentes
remotos que el usuario agrega por su URL pública. Las credenciales viven en `.env` (`WEB_USUARIO`,
`WEB_CLAVE_HASH`, `WEB_SECRETO`).
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from web import a2a, orquestador
from web.almacen import Almacen
from web.auth import LimiteIntentos, crear_cookie, leer_cookie, verificar_clave
from web.config import MAX_AGENTES, Settings, cargar_settings

logger = logging.getLogger(__name__)

NOMBRE_COOKIE = "sesion_czz"
CABECERA_CSRF = "x-solicitado-por"
VALOR_CSRF = "chat-web"
ESTATICOS = Path(__file__).parent / "static"

CABECERAS_SEGURIDAD = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": (
        "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; "
        "connect-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
    ),
}


class Credenciales(BaseModel):
    usuario: str = Field(min_length=1, max_length=80)
    clave: str = Field(min_length=1, max_length=200)


class NuevoAgente(BaseModel):
    url: str = Field(min_length=8, max_length=500)


class NuevoMensaje(BaseModel):
    texto: str = Field(min_length=1, max_length=8000)


def crear_app(settings: Settings | None = None, almacen: Almacen | None = None) -> FastAPI:
    settings = settings or cargar_settings()
    almacen = almacen or Almacen(settings.ruta_datos)
    # La consola conserva las últimas MAX_CHARLAS conversaciones: limpia lo que haya sobrado.
    almacen.podar_charlas()
    intentos = LimiteIntentos()

    for ruidoso in ("httpx", "httpcore"):
        logging.getLogger(ruidoso).setLevel(logging.WARNING)

    app = FastAPI(title="Chat A2A de agente_cz_A2A", version="1.0.0", docs_url=None, redoc_url=None)
    app.state.settings = settings
    app.state.almacen = almacen

    @app.middleware("http")
    async def seguridad(request: Request, llamar):
        respuesta = await llamar(request)
        for clave, valor in CABECERAS_SEGURIDAD.items():
            respuesta.headers.setdefault(clave, valor)
        return respuesta

    def exigir_csrf(request: Request) -> None:
        if request.headers.get(CABECERA_CSRF) != VALOR_CSRF:
            raise HTTPException(status_code=403, detail="Falta la cabecera de la página.")

    def usuario_actual(request: Request) -> str:
        usuario = leer_cookie(request.cookies.get(NOMBRE_COOKIE), settings.secreto)
        if usuario is None:
            # Respaldo para navegadores que no conservan la cookie (webviews, cookies de terceros
            # bloqueadas): la misma sesión firmada viaja en la cabecera Authorization.
            autorizacion = request.headers.get("authorization", "")
            if autorizacion.lower().startswith("bearer "):
                usuario = leer_cookie(autorizacion[7:].strip(), settings.secreto)
        if usuario is None:
            raise HTTPException(status_code=401, detail="Sesión no válida o vencida.")
        return usuario

    def _es_https(request: Request) -> bool:
        esquema = request.headers.get("x-forwarded-proto", request.url.scheme)
        return esquema.split(",")[0].strip().lower() == "https"

    # --- sesión -----------------------------------------------------------
    @app.post("/api/login")
    async def login(datos: Credenciales, request: Request, response: Response) -> dict:
        origen = request.client.host if request.client else "desconocido"
        espera = intentos.bloqueado(origen)
        if espera:
            raise HTTPException(
                status_code=429,
                detail=f"Demasiados intentos fallidos. Espera {espera} segundos.",
            )
        valido = datos.usuario == settings.usuario and verificar_clave(datos.clave, settings.clave_hash)
        if not valido:
            intentos.fallo(origen)
            logger.warning("Login fallido para %r desde %s", datos.usuario, origen)
            raise HTTPException(status_code=401, detail="Usuario o clave incorrectos.")
        intentos.exito(origen)
        token = crear_cookie(settings.usuario, settings.secreto, settings.horas_sesion)
        response.set_cookie(
            NOMBRE_COOKIE,
            token,
            max_age=int(settings.horas_sesion * 3600),
            httponly=True,
            samesite="lax",
            secure=_es_https(request),
            path="/",
        )
        logger.info("Sesión iniciada por %s desde %s", settings.usuario, origen)
        # El token va también en el cuerpo: si el navegador descarta la cookie, la página lo
        # reenvía en `Authorization` y la sesión sigue funcionando.
        return {"usuario": settings.usuario, "token": token}

    @app.post("/api/logout")
    async def logout(response: Response, usuario: str = Depends(usuario_actual)) -> dict:
        response.delete_cookie(NOMBRE_COOKIE, path="/")
        return {"usuario": usuario, "salida": True}

    @app.get("/api/sesion")
    async def sesion(usuario: str = Depends(usuario_actual)) -> dict:
        return {
            "usuario": usuario,
            "agente": settings.a2a_graph,
            "agente_url": settings.a2a_url,
            "maximo_agentes": MAX_AGENTES,
        }

    # --- equipo de agentes ------------------------------------------------
    async def _estado_remoto(agente_guardado: dict) -> dict:
        try:
            agente = await a2a.descubrir(agente_guardado["url"], timeout=min(10.0, settings.a2a_timeout))
        except Exception as error:  # noqa: BLE001 - el panel muestra el estado, no lo propaga
            return {**agente_guardado, "estado": "no disponible", "detalle": str(error)}
        return {
            "url": agente_guardado["url"],
            "nombre": agente.nombre or agente_guardado["nombre"],
            "estado": "disponible",
            "detalle": agente.url_a2a,
        }

    @app.get("/api/agentes")
    async def agentes(usuario: str = Depends(usuario_actual)) -> dict:
        guardados = almacen.agentes()
        estados = await asyncio.gather(*(_estado_remoto(agente) for agente in guardados))
        estado_local = "no disponible"
        detalle_local = ""
        try:
            local = await a2a.descubrir(settings.a2a_url, timeout=min(10.0, settings.a2a_timeout))
            estado_local, detalle_local = "disponible", local.nombre
        except Exception as error:  # noqa: BLE001
            detalle_local = str(error)
        return {
            "local": {
                "nombre": settings.a2a_graph,
                "url": settings.a2a_url,
                "estado": estado_local,
                "detalle": detalle_local,
                "rol": "sintetiza",
            },
            "remotos": list(estados),
            "maximo": MAX_AGENTES,
        }

    @app.post("/api/agentes")
    async def agregar_agente(
        datos: NuevoAgente, request: Request, usuario: str = Depends(usuario_actual)
    ) -> dict:
        exigir_csrf(request)
        try:
            url = a2a.normalizar_url(datos.url)
        except a2a.ErrorAgenteRemoto as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

        guardados = almacen.agentes()
        ya_esta = any(item["url"] == url for item in guardados)
        if not ya_esta and len(guardados) >= MAX_AGENTES:
            raise HTTPException(
                status_code=409,
                detail=f"El equipo ya tiene {MAX_AGENTES} agentes remotos: quita uno antes de agregar otro.",
            )
        try:
            agente = await a2a.descubrir(url, timeout=min(20.0, settings.a2a_timeout))
        except a2a.ErrorAgenteRemoto as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

        almacen.agregar_agente(url, agente.nombre)
        logger.info("Agente agregado al equipo: %s (%s)", agente.nombre, url)
        return {"url": url, "nombre": agente.nombre, "estado": "disponible", "detalle": agente.url_a2a}

    @app.delete("/api/agentes")
    async def quitar_agente(
        datos: NuevoAgente, request: Request, usuario: str = Depends(usuario_actual)
    ) -> dict:
        exigir_csrf(request)
        try:
            url = a2a.normalizar_url(datos.url)
        except a2a.ErrorAgenteRemoto as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        if not almacen.quitar_agente(url):
            raise HTTPException(status_code=404, detail="Ese agente no está en el equipo.")
        return {"url": url, "quitado": True}

    # --- conversaciones ---------------------------------------------------
    @app.get("/api/charlas")
    async def charlas(usuario: str = Depends(usuario_actual)) -> list[dict]:
        return almacen.charlas()

    @app.post("/api/charlas")
    async def nueva_charla(request: Request, usuario: str = Depends(usuario_actual)) -> dict:
        exigir_csrf(request)
        return {"id": almacen.crear_charla()}

    @app.get("/api/charlas/{charla_id}")
    async def leer_charla(charla_id: str, usuario: str = Depends(usuario_actual)) -> dict:
        if not almacen.existe_charla(charla_id):
            raise HTTPException(status_code=404, detail="Esa conversación no existe.")
        return {"id": charla_id, "mensajes": almacen.mensajes(charla_id)}

    @app.delete("/api/charlas/{charla_id}")
    async def borrar_charla(
        charla_id: str, request: Request, usuario: str = Depends(usuario_actual)
    ) -> dict:
        exigir_csrf(request)
        if not almacen.borrar_charla(charla_id):
            raise HTTPException(status_code=404, detail="Esa conversación no existe.")
        return {"id": charla_id, "borrada": True}

    @app.post("/api/charlas/{charla_id}/mensaje")
    async def enviar_mensaje(
        charla_id: str,
        datos: NuevoMensaje,
        request: Request,
        usuario: str = Depends(usuario_actual),
    ):
        exigir_csrf(request)
        if not almacen.existe_charla(charla_id):
            raise HTTPException(status_code=404, detail="Esa conversación no existe.")
        texto = datos.texto.strip()
        if not texto:
            raise HTTPException(status_code=400, detail="El mensaje está vacío.")

        urls = [agente["url"] for agente in almacen.agentes()][:MAX_AGENTES]
        almacen.agregar_mensaje(charla_id, "user", texto)
        resultado = await orquestador.ejecutar(settings, texto, charla_id, urls)
        almacen.agregar_mensaje(charla_id, "assistant", resultado["respuesta"], resultado["flujo"])

        if not resultado["respuesta"]:
            return JSONResponse(
                status_code=502,
                content={"error": resultado["error"] or "Ningún agente respondió.", "flujo": resultado["flujo"]},
            )
        return resultado

    # --- salud y página ---------------------------------------------------
    @app.get("/ok")
    async def ok() -> dict:
        return {"ok": True, "agente": settings.a2a_graph, "equipo": len(almacen.agentes())}

    @app.get("/salud")
    async def salud() -> dict:
        estado = "desconocido"
        try:
            await a2a.descubrir(settings.a2a_url, timeout=min(8.0, settings.a2a_timeout))
            estado = "disponible"
        except Exception as error:  # noqa: BLE001
            logger.warning("Salud: agente local no disponible (%s)", type(error).__name__)
            estado = "no disponible"
        return {
            "web": {"host": settings.host, "port": settings.port, "usuario": settings.usuario},
            "agente": {"nombre": settings.a2a_graph, "url": settings.a2a_url, "estado": estado},
            "equipo": {"remotos": len(almacen.agentes()), "maximo": MAX_AGENTES},
        }

    if ESTATICOS.is_dir():
        app.mount("/static", StaticFiles(directory=str(ESTATICOS)), name="estaticos")

    @app.get("/")
    async def inicio() -> FileResponse:
        return FileResponse(
            ESTATICOS / "index.html",
            headers={"Cache-Control": "no-store"},
        )

    return app
