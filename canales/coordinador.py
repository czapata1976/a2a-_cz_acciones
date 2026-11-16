"""Cliente del coordinador A2A al que se conectan los canales.

Los canales **no hablan con el agente**: el coordinador es el único que guarda su clave y el que
elige qué agente responde. Cada chat conserva su identificador de sesión, que el coordinador usa para
recordar la conversación y para citar al agente que respondió.
"""
from __future__ import annotations

import httpx

from canales.errores import ErrorCanal


class ErrorCoordinador(ErrorCanal):
    """El coordinador no está disponible o no devolvió una respuesta utilizable."""


class CoordinadorA2A:
    def __init__(self, base_url: str, clave: str, timeout: float = 180.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.clave = clave
        self.timeout = timeout

    async def consultar(self, texto: str, sesion: str) -> str:
        """Envía la consulta a `POST /chat` y devuelve lo que respondió el coordinador."""
        limpio = (texto or "").strip()
        if not limpio:
            raise ErrorCoordinador("La consulta está vacía.")
        try:
            async with httpx.AsyncClient(timeout=self.timeout, trust_env=False) as cliente:
                respuesta = await cliente.post(
                    f"{self.base_url}/chat",
                    json={"mensaje": limpio, "cliente": sesion},
                    headers={"X-Coordinador-Clave": self.clave},
                )
                respuesta.raise_for_status()
                datos = respuesta.json()
        except httpx.TimeoutException as error:
            raise ErrorCoordinador(
                "El coordinador agotó el tiempo de respuesta. Intenta de nuevo."
            ) from error
        except httpx.HTTPStatusError as error:
            codigo = error.response.status_code
            if codigo in {401, 403}:
                raise ErrorCoordinador(
                    "El coordinador rechazó la clave: revisa COORDINADOR_CLAVE."
                ) from error
            raise ErrorCoordinador(f"El coordinador respondió con un error HTTP {codigo}.") from error
        except httpx.HTTPError as error:
            raise ErrorCoordinador(
                f"No pude comunicarme con el coordinador en {self.base_url}."
            ) from error
        except ValueError as error:
            raise ErrorCoordinador("El coordinador devolvió una respuesta que no es JSON.") from error

        if not isinstance(datos, dict) or not isinstance(datos.get("respuesta"), str):
            raise ErrorCoordinador("El coordinador no devolvió una respuesta válida.")
        if not datos["respuesta"].strip():
            raise ErrorCoordinador("El coordinador no devolvió texto.")
        return datos["respuesta"]

    async def estado(self) -> dict:
        """`GET /salud` del coordinador: qué agentes tiene y cómo están."""
        try:
            async with httpx.AsyncClient(
                timeout=min(10.0, self.timeout), trust_env=False
            ) as cliente:
                respuesta = await cliente.get(f"{self.base_url}/salud")
                respuesta.raise_for_status()
                datos = respuesta.json()
        except httpx.HTTPError as error:
            raise ErrorCoordinador(f"El coordinador no responde en {self.base_url}.") from error
        except ValueError as error:
            raise ErrorCoordinador("El coordinador devolvió un estado que no es JSON.") from error
        if not isinstance(datos, dict):
            raise ErrorCoordinador("El coordinador devolvió un estado inesperado.")
        return datos


__all__ = ["CoordinadorA2A", "ErrorCoordinador"]
