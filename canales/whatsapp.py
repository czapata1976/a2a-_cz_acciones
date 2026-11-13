"""Canal WhatsApp: mensajes del puente Baileys y gesti?n de la vinculaci?n.

El puente (Node + Baileys, en `whatsapp/`) escucha solo en loopback, env?a cada mensaje propio a
`POST /whatsapp/mensaje` y exige el secreto compartido `WHATSAPP_SECRET`. Los endpoints de gesti?n
(estado, conectar, QR, c?digo) se protegen con el token de operador si est? configurado.

El router se construye con `crear_router`, as? lo monta tanto el servicio de canales (que consulta al
agente por A2A) como el coordinador (que elige un agente del equipo con su supervisor). Quien monta el
router deja en `app.state.whatsapp_responder` la funci?n `async (texto, sesion) -> str`.
"""
from __future__ import annotations

import base64
import logging
import secrets
from dataclasses import dataclass
from typing import Awaitable, Callable, Literal

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field

from canales.errores import ErrorCanal

logger = logging.getLogger(__name__)

MENSAJE_AYUDA = (
    "Hola. Soy el canal WhatsApp de agente_cz_A2A, el asesor de acciones de Carlos Zapata.\n\n"
    "Escr?beme una consulta con el ticker y el mercado, por ejemplo:\n"
    "  ?Cu?nto vale AAPL en el mercado US?\n"
    "  Compara NVDA y MSFT en US para un horizonte de 3 a?os.\n\n"
    "No ejecuto pagos ni inversiones; lo tributario lo deriva a un especialista."
)

MENSAJES_ERROR_PUENTE = {
    "operator_authentication_required": "El puente rechaz? la credencial del servicio.",
    "connection_not_authorized": "La vinculaci?n no est? autorizada en este despliegue.",
    "disconnect_before_new_attempt": "Desconecta el intento anterior antes de iniciar otro.",
    "link_mode_unavailable": "No se puede cambiar el modo de vinculaci?n en este momento.",
    "pairing_not_ready": "WhatsApp todav?a no habilit? la solicitud de c?digo.",
    "invalid_phone": "El n?mero debe tener entre 7 y 15 d?gitos, sin + ni separadores.",
    "invalid_link_mode": "El modo de vinculaci?n debe ser code o qr.",
    "invalid_input": "La solicitud al puente no tiene el formato esperado.",
    "not_found": "El puente no reconoce la operaci?n solicitada.",
}

Responder = Callable[[str, str], Awaitable[str]]
"""Consulta `(texto, sesion)` y devuelve el texto que se env?a al chat."""


@dataclass(frozen=True)
class CanalWhatsApp:
    """Ajustes del canal y del puente, ya resueltos por el servicio que lo monta."""

    habilitado: bool
    secreto: str
    url_interna: str = "http://127.0.0.1:18082"
    timeout: float = 20.0
    max_caracteres: int = 3500
    token_operador: str = ""
    ayuda: str | Callable[[], str] | None = MENSAJE_AYUDA
    """Texto para /start, /help y /ayuda. Una función permite armarlo con el equipo del momento; con
    `None` el mensaje llega al agente."""


class MensajeWhatsApp(BaseModel):
    """Mensaje entregado por el puente local, ya validado en el celular."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    mensaje: str = Field(min_length=1, max_length=2000)
    session_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]{1,64}$")
    request_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]{1,64}$")


class RespuestaWhatsApp(BaseModel):
    respuesta: str
    estado: str


class ModoVinculacion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    modo: Literal["code", "qr"]


class TelefonoVinculacion(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    telefono: str = Field(pattern=r"^[1-9][0-9]{6,14}$")


def _recortar(texto: str, limite: int) -> str:
    if len(texto) <= limite:
        return texto
    sufijo = "\n\n(recortado)"
    return texto[: max(1, limite - len(sufijo))].rstrip() + sufijo


class ClientePuente:
    """Traduce el API interno del puente a llamadas HTTP con el secreto compartido."""

    def __init__(self, canal: CanalWhatsApp) -> None:
        self.base_url = canal.url_interna
        self.secreto = canal.secreto
        self.timeout = canal.timeout

    async def _peticion(self, metodo: str, ruta: str, json: dict | None = None) -> dict:
        try:
            async with httpx.AsyncClient(timeout=self.timeout, trust_env=False) as cliente:
                respuesta = await cliente.request(
                    metodo,
                    f"{self.base_url}{ruta}",
                    headers={"X-WhatsApp-Secret": self.secreto},
                    json=json,
                )
        except httpx.HTTPError as error:
            raise HTTPException(
                status_code=503,
                detail="El puente de WhatsApp no responde. Revisa el proceso del canal.",
            ) from error

        try:
            datos = respuesta.json()
        except ValueError:
            datos = {}

        if respuesta.status_code >= 400:
            codigo = str(datos.get("error") or "whatsapp_operation_failed")
            mensaje = MENSAJES_ERROR_PUENTE.get(
                codigo, "El puente no pudo completar la operaci?n; revisa el estado."
            )
            estado = 422 if respuesta.status_code in {400, 422} else 409 if respuesta.status_code == 409 else 503
            raise HTTPException(status_code=estado, detail=mensaje)
        if not isinstance(datos, dict):
            raise HTTPException(status_code=502, detail="El puente devolvi? una respuesta inv?lida.")
        return datos

    async def estado(self) -> dict:
        return await self._peticion("GET", "/internal/estado")

    async def conectar(self) -> dict:
        return await self._peticion("POST", "/internal/conectar")

    async def desconectar(self) -> dict:
        return await self._peticion("POST", "/internal/desconectar")

    async def modo(self, modo: str) -> dict:
        return await self._peticion("POST", "/internal/modo", {"modo": modo})

    async def codigo(self, telefono: str | None = None) -> dict:
        if telefono is None:
            return await self._peticion("GET", "/internal/codigo")
        return await self._peticion("POST", "/internal/codigo", {"telefono": telefono})

    async def qr(self) -> dict:
        return await self._peticion("GET", "/internal/qr")


def crear_router(canal: CanalWhatsApp) -> APIRouter:
    """Construye el router de WhatsApp para un canal ya configurado."""
    router = APIRouter(prefix="/whatsapp", tags=["whatsapp"])

    def autorizar_operador(request: Request) -> None:
        """Protege la gesti?n del puente cuando hay token de operador configurado."""
        if not canal.token_operador:
            return
        recibido = request.headers.get("x-canales-token") or request.query_params.get("token") or ""
        if not secrets.compare_digest(recibido.encode("utf-8"), canal.token_operador.encode("utf-8")):
            raise HTTPException(status_code=403, detail="Token de operador inv?lido.")

    def puente(request: Request) -> ClientePuente:
        if not (canal.habilitado and canal.secreto):
            raise HTTPException(
                status_code=503,
                detail="El canal WhatsApp no est? habilitado: revisa WHATSAPP_HABILITADO y WHATSAPP_SECRET.",
            )
        return ClientePuente(canal)

    @router.post("/mensaje", response_model=RespuestaWhatsApp)
    async def mensaje_entrante(request: Request, cuerpo: MensajeWhatsApp) -> RespuestaWhatsApp:
        """Recibe un mensaje del puente, consulta al agente y devuelve el texto de respuesta."""
        if not (canal.habilitado and canal.secreto):
            raise HTTPException(status_code=503, detail="El canal WhatsApp no est? habilitado.")

        recibido = request.headers.get("x-whatsapp-secret", "")
        if not secrets.compare_digest(recibido.encode("utf-8"), canal.secreto.encode("utf-8")):
            raise HTTPException(status_code=403, detail="Secreto de WhatsApp inv?lido.")

        texto = cuerpo.mensaje.strip()
        if texto.lower() in {"/start", "/help", "/ayuda"}:
            ayuda = canal.ayuda() if callable(canal.ayuda) else canal.ayuda
            if ayuda:
                return RespuestaWhatsApp(respuesta=ayuda, estado="ok")

        responder: Responder = request.app.state.whatsapp_responder
        try:
            respuesta = await responder(texto, cuerpo.session_id or "wa-local")
        except ErrorCanal as error:
            logger.warning("WhatsApp: %s", error)
            return RespuestaWhatsApp(
                respuesta=_recortar(f"No pude responder la consulta: {error}", canal.max_caracteres),
                estado="error",
            )
        except Exception:
            logger.exception("WhatsApp: error inesperado")
            return RespuestaWhatsApp(
                respuesta="No pude procesar tu mensaje. Intenta nuevamente en un momento.",
                estado="error",
            )

        return RespuestaWhatsApp(respuesta=_recortar(respuesta, canal.max_caracteres), estado="ok")

    @router.get("/estado")
    async def estado(request: Request, _: None = Depends(autorizar_operador)) -> dict:
        return await puente(request).estado()

    @router.post("/conectar")
    async def conectar(request: Request, _: None = Depends(autorizar_operador)) -> dict:
        return await puente(request).conectar()

    @router.post("/desconectar")
    async def desconectar(request: Request, _: None = Depends(autorizar_operador)) -> dict:
        return await puente(request).desconectar()

    @router.post("/modo")
    async def cambiar_modo(
        request: Request, cuerpo: ModoVinculacion, _: None = Depends(autorizar_operador)
    ) -> dict:
        return await puente(request).modo(cuerpo.modo)

    @router.get("/codigo")
    async def consultar_codigo(request: Request, _: None = Depends(autorizar_operador)) -> dict:
        return await puente(request).codigo()

    @router.post("/codigo")
    async def solicitar_codigo(
        request: Request, cuerpo: TelefonoVinculacion, _: None = Depends(autorizar_operador)
    ) -> dict:
        return await puente(request).codigo(cuerpo.telefono)

    @router.get("/qr")
    async def consultar_qr(request: Request, _: None = Depends(autorizar_operador)) -> dict:
        return await puente(request).qr()

    @router.get("/qr.png", include_in_schema=False)
    async def ver_qr(request: Request, _: None = Depends(autorizar_operador)) -> Response:
        """Devuelve el QR como imagen para escanearlo desde el m?vil."""
        datos = await puente(request).qr()
        imagen = datos.get("imagen")
        if not isinstance(imagen, str) or ";base64," not in imagen:
            raise HTTPException(status_code=404, detail="Todav?a no hay un QR disponible.")
        try:
            contenido = base64.b64decode(imagen.split(";base64,", 1)[1])
        except ValueError as error:
            raise HTTPException(status_code=502, detail="El puente devolvi? un QR inv?lido.") from error
        return Response(content=contenido, media_type="image/png", headers={"Cache-Control": "no-store"})

    return router
