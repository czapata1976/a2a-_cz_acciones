"""Canal de Telegram conectado al coordinador.

El webhook exige el secreto compartido (`X-Telegram-Bot-Api-Secret-Token`) y responde a la misma
persona. Cada chat conserva su hilo de memoria. Un mensaje que no es texto (foto, sticker, audio,
documento) se responde con que el coordinador no puede leerlo.
"""
from __future__ import annotations

import logging

import httpx

logger = logging.getLogger("coordinador.canal")

TROZO = 4000
TIPOS_NO_LEIBLES = {"photo", "sticker", "voice", "audio", "video", "document", "video_note", "animation"}


def tipo_de_mensaje(mensaje: dict) -> str:
    """`texto`, `no_leible` o `ignorar` (sin mensaje útil)."""
    if not isinstance(mensaje, dict):
        return "ignorar"
    if isinstance(mensaje.get("text"), str) and mensaje["text"].strip():
        return "texto"
    if TIPOS_NO_LEIBLES & set(mensaje.keys()):
        return "no_leible"
    return "ignorar"


def dividir(texto: str, tope: int = TROZO) -> list[str]:
    """Telegram corta en 4096; se parte sin romper palabras."""
    if len(texto) <= tope:
        return [texto]
    trozos: list[str] = []
    resto = texto
    while resto:
        if len(resto) <= tope:
            trozos.append(resto)
            break
        corte = resto.rfind("\n", 0, tope)
        if corte < tope // 2:
            corte = resto.rfind(" ", 0, tope)
        if corte < tope // 2:
            corte = tope
        trozos.append(resto[:corte])
        resto = resto[corte:].lstrip("\n")
    return trozos


async def enviar(token: str, base: str, chat_id: int | str, texto: str) -> None:
    """Envía el texto al chat por la Bot API."""
    if not token:
        logger.info("[telegram:log] chat=%s · %s", chat_id, texto[:200])
        return
    async with httpx.AsyncClient(timeout=20, trust_env=False) as cliente:
        for trozo in dividir(texto):
            try:
                respuesta = await cliente.post(
                    f"{base}/bot{token}/sendMessage",
                    json={"chat_id": chat_id, "text": trozo, "disable_web_page_preview": True},
                )
                if respuesta.status_code >= 400:
                    logger.warning("Telegram respondió %s al enviar", respuesta.status_code)
            except httpx.HTTPError as error:
                logger.warning("No pude enviar a Telegram: %s", error)
