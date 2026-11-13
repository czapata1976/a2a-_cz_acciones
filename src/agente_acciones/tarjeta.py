"""Ficha pública del agente (`/.well-known/agent-card.json`).

La ficha dice qué hace y qué **no** hace: es lo que lee el coordinador para elegir al agente y lo que
lee el equipo docente para probarlo. La URL es la dirección pública de la nube (`URL_PUBLICA`), no la
de la máquina donde corre.
"""
from __future__ import annotations

NOMBRE = "agente_cz_A2A"
VERSION = "1.0.0"
PROTOCOLO = "0.3.0"

DESCRIPCION = (
    "Asesor de acciones de Carlos Zapata. Analiza un ticker de la bolsa de EE. UU. (US) o de Chile (CL) "
    "con datos de mercado y fundamentales simulados del taller (PER, deuda/patrimonio y márgenes), cita "
    "la fecha de corte, entrega una decisión condicionada al perfil de riesgo y al horizonte, y explica "
    "qué invalidaría la tesis. NO ejecuta compras, ventas, pagos ni transferencias; NO asesora en "
    "materia tributaria, legal o normativa (lo deriva al agente de auditoría); NO entrega precios reales "
    "de mercado ni cubre instrumentos distintos de acciones."
)

SKILLS = [
    {
        "id": "analisis-acciones",
        "name": "Analizar una acción",
        "description": (
            "Analiza una acción con datos de mercado y fundamentales simulados del taller y devuelve "
            "precio, fecha de corte, PER, deuda/patrimonio, márgenes, lectura, tesis, riesgos y una "
            "decisión condicionada al perfil y al horizonte. Necesita ticker y mercado (US o CL). Las "
            "contingencias tributarias o legales no las evalúa: las deriva al agente de auditoría."
        ),
        "tags": [
            "acciones", "invertir", "inversión", "bolsa", "ticker", "per", "fundamentales",
            "márgenes", "endeudamiento", "portafolio", "riesgo", "valuación", "dividendos",
            "impuestos", "tributario", "legal", "vale", "valor", "chile", "comparar",
            "comparación", "mercado",
        ],
        "examples": [
            "Analiza NVDA en US para un perfil moderado a 12 meses.",
            "¿Cuánto vale SQM-B en Chile?",
            "Compárame AAPL y MSFT en el mercado US.",
            "¿Cuánto impuesto pago por las ganancias de NVDA en Chile?",
        ],
        "inputModes": ["text/plain"],
        "outputModes": ["text/plain"],
    },
    {
        "id": "criterios-de-inversion",
        "name": "Explicar los criterios de inversión",
        "description": (
            "Explica con qué criterios se evalúa una decisión de inversión y conceptos como PER, "
            "diversificación y riesgo. No entrega datos de un ticker sin consultarlos."
        ),
        "tags": ["criterios", "método", "conceptos", "diversificación", "educación financiera"],
        "examples": ["¿Qué criterios usas para evaluar una acción?"],
        "inputModes": ["text/plain"],
        "outputModes": ["text/plain"],
    },
]


def construir_tarjeta(url_publica: str) -> dict:
    """Devuelve la ficha A2A con la dirección pública del servicio."""
    base = (url_publica or "").rstrip("/")
    return {
        "name": NOMBRE,
        "description": DESCRIPCION,
        "url": f"{base}/a2a" if base else "/a2a",
        "version": VERSION,
        "protocolVersion": PROTOCOLO,
        "preferredTransport": "JSONRPC",
        "capabilities": {"streaming": False, "pushNotifications": False},
        "defaultInputModes": ["text/plain"],
        "defaultOutputModes": ["text/plain"],
        "skills": SKILLS,
        "authentication": {
            "schemes": ["apiKey"],
            "header": "X-Agente-Clave",
            "description": (
                "La ficha y /salud son públicas. Enviar un mensaje por message/send exige la clave del "
                "agente en la cabecera X-Agente-Clave (o Authorization: Bearer)."
            ),
        },
    }
