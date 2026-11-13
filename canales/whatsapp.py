"""Canal WhatsApp: mensajes del puente Baileys y gestión de la vinculación.

El puente (Node + Baileys, en `whatsapp/`) escucha solo en loopback, envía cada mensaje propio a
`POST /whatsapp/mensaje` y exige el secreto compartido `WHATSAPP_SECRET`. Los endpoints de gestión
(estado, conectar, QR, código) se protegen con `CANALES_TOKEN` si está configurado.
"""
from __future__ import annotations

import base64
import logging
import secrets
from typing import Literal

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field

from canales.agente import ErrorAgente
from canales.config import Settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/whatsapp", tags=["whatsapp"])

MENSAJE_AYUDA = (
    "Hola. Soy el canal WhatsApp de agente_cz_A2A, el asesor de acciones de Carlos Zapata.\n\n"
    "Escríbeme una consulta con el ticker y el mercado, por ejemplo:\n"
    "  ¿Cuánto vale AAPL en el mercado US?\n"
    "  Compara NVDA y MSFT en US para un horizonte de 3 años.\n\n"
    "No ejecuto pagos ni inversiones; lo tributario lo deriva a un especialista."
)

MENSAJES_ERROR_PUENTE = {
    "operator_authentication_required": "El puente rechazó la credencial del servicio.",
    "connection_not_authorized": "La vinculación no está autorizada en este despliegue.",
    "disconnect_before_new_attempt": "Desconecta el intento anterior antes de iniciar otro.",
    "link_mode_unavailable": "No se puede cambiar el modo de vinculación en este momento.",
    "pairing_not_ready": "WhatsApp todavía no habilitó la solicitud de código.",
    "invalid_phone": "El número debe tener entre 7 y 15 dígitos, sin + ni separadores.",
    "invalid_link_mode": "El modo de vinculación debe ser code o qr.",
    "invalid_input": "La solicitud al puente no tiene el formato esperado.",
    "not_found": "El puente no reconoce la operación solicitada.",
}


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


def autorizar_operador(request: Request) -> None:
    """Protege la gestión del puente cuando `CANALES_TOKEN` está configurado."""
    settings: Settings = request.app.state.settings
    if not settings.canales_token:
        return
    recibido = request.headers.get("x-canales-token") or request.query_params.get("token") or ""
    if not secrets.compare_digest(recibido.encode("utf-8"), settings.canales_token.encode("utf-8")):
        raise HTTPException(status_code=403, detail="Token de operador inválido.")


class ClientePuente:
    """Traduce el API interno del puente a llamadas HTTP con el secreto compartido."""

    def __init__(self, settings: Settings) -> None:
        self.base_url = settings.whatsapp_url_interna
        self.secreto = settings.whatsapp_secret
        self.timeout = settings.whatsapp_timeout

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
                codigo, "El puente no pudo completar la operación; revisa el estado."
            )
            estado = 422 if respuesta.status_code in {400, 422} else 409 if respuesta.status_code == 409 else 503
            raise HTTPException(status_code=estado, detail=mensaje)
        if not isinstance(datos, dict):
            raise HTTPException(status_code=502, detail="El puente devolvió una respuesta inválida.")
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


def _puente(request: Request) -> ClientePuente:
    settings: Settings = request.app.state.settings
    if not (settings.whatsapp_habilitado and settings.whatsapp_secret):
        raise HTTPException(
            status_code=503,
            detail="El canal WhatsApp no está habilitado: revisa WHATSAPP_HABILITADO y WHATSAPP_SECRET.",
        )
    return ClientePuente(settings)


@router.post("/mensaje", response_model=RespuestaWhatsApp)
async def mensaje_entrante(request: Request, cuerpo: MensajeWhatsApp) -> RespuestaWhatsApp:
    """Recibe un mensaje del puente, consulta al agente y devuelve el texto de respuesta."""
    settings: Settings = request.app.state.settings
    if not (settings.whatsapp_habilitado and settings.whatsapp_secret):
        raise HTTPException(status_code=503, detail="El canal WhatsApp no está habilitado.")

    recibido = request.headers.get("x-whatsapp-secret", "")
    if not secrets.compare_digest(
        recibido.encode("utf-8"), settings.whatsapp_secret.encode("utf-8")
    ):
        raise HTTPException(status_code=403, detail="Secreto de WhatsApp inválido.")

    texto = cuerpo.mensaje.strip()
    if texto.lower() in {"/start", "/help", "/ayuda"}:
        return RespuestaWhatsApp(respuesta=MENSAJE_AYUDA, estado="ok")

    sesion = cuerpo.session_id or "wa-local"
    try:
        respuesta = await request.app.state.agente.consultar(texto, sesion)
    except ErrorAgente as error:
        logger.warning("WhatsApp: %s", error)
        return RespuestaWhatsApp(
            respuesta=_recortar(f"No pude responder la consulta: {error}", settings.whatsapp_max_caracteres),
            estado="error",
        )
    except Exception:
        logger.exception("WhatsApp: error inesperado")
        return RespuestaWhatsApp(
            respuesta="No pude procesar tu mensaje. Intenta nuevamente en un momento.",
            estado="error",
        )

    return RespuestaWhatsApp(
        respuesta=_recortar(respuesta, settings.whatsapp_max_caracteres), estado="ok"
    )


@router.get("/estado")
async def estado(request: Request, _: None = Depends(autorizar_operador)) -> dict:
    return await _puente(request).estado()


@router.post("/conectar")
async def conectar(request: Request, _: None = Depends(autorizar_operador)) -> dict:
    return await _puente(request).conectar()


@router.post("/desconectar")
async def desconectar(request: Request, _: None = Depends(autorizar_operador)) -> dict:
    return await _puente(request).desconectar()


@router.post("/modo")
async def cambiar_modo(
    request: Request, cuerpo: ModoVinculacion, _: None = Depends(autorizar_operador)
) -> dict:
    return await _puente(request).modo(cuerpo.modo)


@router.get("/codigo")
async def consultar_codigo(request: Request, _: None = Depends(autorizar_operador)) -> dict:
    return await _puente(request).codigo()


@router.post("/codigo")
async def solicitar_codigo(
    request: Request, cuerpo: TelefonoVinculacion, _: None = Depends(autorizar_operador)
) -> dict:
    return await _puente(request).codigo(cuerpo.telefono)


@router.get("/qr")
async def consultar_qr(request: Request, _: None = Depends(autorizar_operador)) -> dict:
    return await _puente(request).qr()


@router.get("/qr.png", include_in_schema=False)
async def ver_qr(request: Request, _: None = Depends(autorizar_operador)) -> Response:
    """Devuelve el QR como imagen para escanearlo desde el móvil."""
    datos = await _puente(request).qr()
    imagen = datos.get("imagen")
    if not isinstance(imagen, str) or ";base64," not in imagen:
        raise HTTPException(status_code=404, detail="Todavía no hay un QR disponible.")
    try:
        contenido = base64.b64decode(imagen.split(";base64,", 1)[1])
    except ValueError as error:
        raise HTTPException(status_code=502, detail="El puente devolvió un QR inválido.") from error
    return Response(content=contenido, media_type="image/png", headers={"Cache-Control": "no-store"})
