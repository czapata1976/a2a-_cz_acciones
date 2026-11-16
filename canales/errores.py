"""Errores que un canal puede contar al usuario tal cual.

Vive aparte de cualquier cliente (`canales/coordinador.py`, `coordinador/a2a.py`) para que un
servicio que monte el canal de WhatsApp pueda distinguir «no responde» de un fallo inesperado sin
depender del cliente concreto.
"""
from __future__ import annotations


class ErrorCanal(RuntimeError):
    """Fallo con un motivo que se puede mostrar en el chat."""
