"""Errores que un canal puede contar al usuario tal cual.

Vive aparte de `canales.agente` para que cualquier servicio que monte el canal de WhatsApp (el
coordinador, por ejemplo) pueda distinguir «el agente no responde» de un fallo inesperado sin depender
del cliente A2A concreto.
"""
from __future__ import annotations


class ErrorCanal(RuntimeError):
    """Fallo con un motivo que se puede mostrar en el chat."""
