"""Utilidades de las respuestas A2A que consumen los clientes del proyecto.

Vive aparte de cualquier cliente concreto: los canales hablan con el coordinador y el chat web con
los agentes remotos del equipo, y ambos leen el texto igual.
"""
from __future__ import annotations


def texto_de(resultado: dict) -> str:
    """Extrae el texto de un resultado A2A: artefactos, `status.message` o historial.

    Se usa la primera fuente que traiga texto, no todas: hay servidores que repiten la misma
    respuesta en los artefactos y en `status.message` y concatenarlas la duplicaría.
    """
    estado = resultado.get("status") or {}
    grupos = [resultado.get("artifacts") or []]
    if isinstance(estado, dict):
        grupos.append([estado.get("message") or {}])
    grupos.append(
        [
            turno
            for turno in reversed(resultado.get("history") or [])
            if isinstance(turno, dict)
            and str(turno.get("role", "")).lower() in {"agent", "assistant"}
        ][:1]
    )
    for grupo in grupos:
        partes = [
            parte["text"].strip()
            for objeto in grupo
            if isinstance(objeto, dict)
            for parte in (objeto.get("parts") or [])
            if isinstance(parte, dict) and isinstance(parte.get("text"), str) and parte["text"].strip()
        ]
        if partes:
            return "\n".join(partes)
    return ""


__all__ = ["texto_de"]
