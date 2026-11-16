"""Cliente del coordinador A2A del proyecto.

El chat web **no habla con el agente**: el coordinador es el único que guarda su clave. Cada turno
se le manda por `POST /chat` (cabecera `X-Coordinador-Clave`) y él elige el agente, lo consulta y
dice quién respondió. `/salud` sirve para mostrar el estado del equipo en el panel.
"""
from __future__ import annotations

import httpx


class ErrorCoordinador(RuntimeError):
    """El coordinador no está disponible, rechazó la clave o no devolvió una respuesta usable."""


def _base(url: str) -> str:
    return (url or "").rstrip("/")


async def estado(base: str, timeout: float = 10.0) -> dict:
    """`GET /salud`: qué agentes tiene el coordinador y en qué estado."""
    try:
        async with httpx.AsyncClient(timeout=timeout, trust_env=False) as cliente:
            respuesta = await cliente.get(f"{_base(base)}/salud")
            respuesta.raise_for_status()
            datos = respuesta.json()
    except httpx.TimeoutException as error:
        raise ErrorCoordinador(f"{base} no respondió a tiempo.") from error
    except httpx.HTTPStatusError as error:
        raise ErrorCoordinador(
            f"{base} respondió HTTP {error.response.status_code} en /salud."
        ) from error
    except httpx.HTTPError as error:
        raise ErrorCoordinador(f"No pude conectar con el coordinador en {base}.") from error
    except ValueError as error:
        raise ErrorCoordinador("El coordinador devolvió un estado que no es JSON.") from error

    if not isinstance(datos, dict):
        raise ErrorCoordinador("El coordinador devolvió un estado inesperado.")
    return datos


async def consultar(
    base: str,
    clave: str,
    texto: str,
    cliente: str,
    agente: str = "",
    timeout: float = 180.0,
) -> dict:
    """`POST /chat`: la consulta entra por el coordinador y vuelve con quién respondió.

    `agente` fija el agente del equipo que debe responder; sin él, el supervisor elige.
    """
    cuerpo: dict = {"mensaje": texto, "cliente": cliente}
    if agente:
        cuerpo["agente"] = agente
    cabeceras = {"X-Coordinador-Clave": clave}
    try:
        async with httpx.AsyncClient(timeout=timeout, trust_env=False) as http:
            respuesta = await http.post(f"{_base(base)}/chat", json=cuerpo, headers=cabeceras)
            respuesta.raise_for_status()
            datos = respuesta.json()
    except httpx.TimeoutException as error:
        raise ErrorCoordinador("El coordinador agotó el tiempo de respuesta.") from error
    except httpx.HTTPStatusError as error:
        codigo = error.response.status_code
        if codigo in {401, 403}:
            raise ErrorCoordinador(
                "El coordinador rechazó la clave: revisa COORDINADOR_CLAVE."
            ) from error
        raise ErrorCoordinador(f"El coordinador respondió HTTP {codigo}.") from error
    except httpx.HTTPError as error:
        raise ErrorCoordinador(f"No pude comunicarme con el coordinador en {base}.") from error
    except ValueError as error:
        raise ErrorCoordinador("El coordinador devolvió una respuesta que no es JSON.") from error

    if not isinstance(datos, dict) or not isinstance(datos.get("respuesta"), str):
        raise ErrorCoordinador("El coordinador no devolvió una respuesta válida.")
    return datos


__all__ = ["ErrorCoordinador", "consultar", "estado"]
