"""Cliente A2A del agente `agente_cz_A2A`.

Los canales no importan el grafo: descubren el asistente en el servidor, leen su tarjeta y le envían
la tarea por `message/send`. Cada conversación conserva su `contextId` (derivado del chat), que el
servidor usa como `thread_id` para recordar los turnos anteriores.
"""
from __future__ import annotations

import time
import uuid

import httpx

NAMESPACE_CONTEXTOS = uuid.UUID("6f9619ff-8b86-d011-b42d-00c04fc964ff")


class ErrorAgente(RuntimeError):
    """El agente no está disponible o no devolvió una respuesta utilizable."""


def contexto_de(sesion: str) -> str:
    """UUID estable por conversación: el mismo chat reutiliza siempre su `thread_id`."""
    return str(uuid.uuid5(NAMESPACE_CONTEXTOS, sesion))


def texto_de(resultado: dict) -> str:
    """Extrae el texto de un resultado A2A (`status.message`, artefactos o historial)."""
    partes: list[str] = []

    def _agregar(objeto: dict | None) -> None:
        if not isinstance(objeto, dict):
            return
        for parte in objeto.get("parts") or []:
            if isinstance(parte, dict) and isinstance(parte.get("text"), str):
                partes.append(parte["text"])

    estado = resultado.get("status") or {}
    if isinstance(estado, dict):
        _agregar(estado.get("message"))
    for artefacto in resultado.get("artifacts") or []:
        _agregar(artefacto)
    if not any(p.strip() for p in partes):
        for turno in reversed(resultado.get("history") or []):
            if isinstance(turno, dict) and str(turno.get("role", "")).lower() in {"agent", "assistant"}:
                _agregar(turno)
                break
    return "\n".join(parte.strip() for parte in partes if parte.strip()).strip()


class AgenteA2A:
    def __init__(self, base_url: str, grafo: str, timeout: float = 180.0, ttl_cache: float = 30.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.grafo = grafo
        self.timeout = timeout
        self.ttl_cache = ttl_cache
        self._assistant_id: str | None = None
        self._cache_ts = 0.0

    async def assistant_id(self, forzar: bool = False) -> str:
        if (
            not forzar
            and self._assistant_id
            and (time.monotonic() - self._cache_ts) < self.ttl_cache
        ):
            return self._assistant_id
        try:
            async with httpx.AsyncClient(timeout=10, trust_env=False) as cliente:
                respuesta = await cliente.post(
                    f"{self.base_url}/assistants/search", json={"graph_id": self.grafo}
                )
                respuesta.raise_for_status()
                asistentes = respuesta.json()
        except httpx.HTTPError as error:
            raise ErrorAgente(
                f"No puedo conectar con el agente en {self.base_url}. "
                "Levanta el servidor: .venv\\Scripts\\langgraph.exe dev --port 2029"
            ) from error
        except ValueError as error:
            raise ErrorAgente("El servidor del agente devolvió una respuesta que no es JSON.") from error

        if not isinstance(asistentes, list) or not asistentes:
            raise ErrorAgente(f"El agente {self.grafo} no está registrado en {self.base_url}.")
        self._assistant_id = str(asistentes[0]["assistant_id"])
        self._cache_ts = time.monotonic()
        return self._assistant_id

    async def consultar(self, texto: str, sesion: str) -> str:
        """Envía la tarea y devuelve el texto de la respuesta."""
        limpio = (texto or "").strip()
        if not limpio:
            raise ErrorAgente("La consulta está vacía.")
        assistant_id = await self.assistant_id()
        cuerpo = {
            "jsonrpc": "2.0",
            "id": uuid.uuid4().hex,
            "method": "message/send",
            "params": {"message": {
                "role": "user",
                "messageId": uuid.uuid4().hex,
                "contextId": contexto_de(sesion),
                "parts": [{"kind": "text", "text": limpio}],
            }},
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout, trust_env=False) as cliente:
                respuesta = await cliente.post(f"{self.base_url}/a2a/{assistant_id}", json=cuerpo)
                respuesta.raise_for_status()
                datos = respuesta.json()
        except httpx.TimeoutException as error:
            raise ErrorAgente("El agente agotó el tiempo de respuesta. Intenta de nuevo.") from error
        except httpx.HTTPStatusError as error:
            if error.response.status_code == 404:
                self._assistant_id = None
                raise ErrorAgente("El agente se reinició y cambió su identificador. Reintenta.") from error
            raise ErrorAgente(f"El agente respondió con un error HTTP {error.response.status_code}.") from error
        except httpx.HTTPError as error:
            raise ErrorAgente("No pude comunicarme con el agente. Revisa que siga arriba.") from error
        except ValueError as error:
            raise ErrorAgente("El agente devolvió una respuesta que no es JSON.") from error

        if not isinstance(datos, dict):
            raise ErrorAgente("El agente devolvió una respuesta inesperada.")
        if datos.get("error"):
            raise ErrorAgente("El agente devolvió un error A2A. Revisa su terminal.")
        resultado = datos.get("result")
        if not isinstance(resultado, dict):
            raise ErrorAgente("El agente no devolvió un resultado A2A válido.")

        estado = (resultado.get("status") or {}).get("state")
        if isinstance(estado, str) and estado.lower() in {"failed", "canceled", "cancelled", "rejected", "error"}:
            raise ErrorAgente(f"El agente no completó la tarea (estado: {estado}).")

        texto_respuesta = texto_de(resultado)
        if not texto_respuesta:
            raise ErrorAgente("El agente no devolvió texto. Revisa su terminal.")
        return texto_respuesta
