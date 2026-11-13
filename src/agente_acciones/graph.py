"""Grafo `agente_cz_A2A` · copia autónoma del agente de Carlos Zapata · Taller A2A · Grupo 1.

Asesor experto en acciones: prompt con método explícito y herramientas deterministas
(`consultar_acciones`, `consultar_fundamentales` y `consultar_mis_apuntes`). El `name` es el que
otro agente usa para descubrirlo por A2A, así que debe ser único: este servicio corre en su propio
puerto (2029) y se puede levantar junto a `agente_czz` sin colisiones.
"""
import json
import os
import re

from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import HumanMessage
from langchain_google_genai import ChatGoogleGenerativeAI

from src.agente_acciones.herramientas import (
    ACCIONES,
    HERRAMIENTAS,
    consultar_acciones,
    consultar_fundamentales,
)
from src.agente_acciones.prompts import SYSTEM_AGENTE

load_dotenv()

modelo = ChatGoogleGenerativeAI(model=os.environ.get("MODELO", "gemini-3.5-flash-lite"))

PATRON_CL = re.compile(r"\bCL\b|CHILE|SANTIAGO", re.IGNORECASE)
PATRON_US = re.compile(r"\bUS\b|\bUSA\b|EE\.?\s?UU\.?|ESTADOS UNIDOS|NASDAQ|NYSE", re.IGNORECASE)
PATRON_CONSULTA = re.compile(r"<consulta>(.*?)</consulta>", re.DOTALL | re.IGNORECASE)


def _mercado_mencionado(texto: str) -> str:
    if PATRON_CL.search(texto):
        return "CL"
    if PATRON_US.search(texto):
        return "US"
    return ""


def _consulta_del_texto(texto: str) -> tuple[str, str] | None:
    """Primer ticker cubierto que aparece en el mensaje, con el mercado que menciona el usuario."""
    # En una síntesis, el mensaje trae la pregunta dentro de <consulta> y los aportes de otros
    # agentes después: solo cuenta la pregunta, o un colega hablando de Chile cambiaría el mercado.
    envuelta = PATRON_CONSULTA.search(texto)
    if envuelta:
        texto = envuelta.group(1)
    plano = texto.upper()
    mencionado = _mercado_mencionado(texto)
    for ticker, pais in ACCIONES:
        if re.search(rf"(?<![A-Z0-9]){re.escape(ticker)}(?![A-Z0-9])", plano):
            return ticker, mencionado or pais
    return None


def _resultado(herramienta, ticker: str, mercado: str) -> str:
    return json.dumps(herramienta.invoke({"ticker": ticker, "pais": mercado}), ensure_ascii=False)


def _bloque_datos(ticker: str, mercado: str) -> str:
    return (
        "<datos_herramientas>\n"
        f'consultar_acciones("{ticker}", "{mercado}") devolvió: '
        f"{_resultado(consultar_acciones, ticker, mercado)}\n"
        f'consultar_fundamentales("{ticker}", "{mercado}") devolvió: '
        f"{_resultado(consultar_fundamentales, ticker, mercado)}\n"
        "Estas son las cifras y la fecha de corte que debes usar, tal cual, en la respuesta.\n"
        "</datos_herramientas>"
    )


class DatosDelTaller(AgentMiddleware):
    """Entrega al modelo el resultado de las herramientas en el mismo turno.

    El modelo, por sí solo, a veces responde de memoria e inventa precios y fundamentales (se
    observó con AAPL). Aquí las herramientas se ejecutan de forma determinista cuando el mensaje
    trae un ticker cubierto y el resultado viaja en el mensaje del usuario, entre etiquetas: lo que
    devuelve una herramienta es un dato, nunca una instrucción de sistema.
    """

    def _con_datos(self, request):
        if request.messages and isinstance(request.messages[-1], HumanMessage):
            consulta = _consulta_del_texto(str(request.messages[-1].content))
            if consulta:
                return request.override(
                    messages=[*request.messages, HumanMessage(content=_bloque_datos(*consulta))]
                )
        return request

    def wrap_model_call(self, request, handler):
        return handler(self._con_datos(request))

    async def awrap_model_call(self, request, handler):
        return await handler(self._con_datos(request))


def crear_agente(checkpointer=None):
    """Arma el grafo. `langgraph dev` lo pide sin checkpointer; el servidor propio se lo pasa para
    recordar cada conversación por `thread_id` (el `contextId` de A2A)."""
    return create_agent(
        model=modelo,
        tools=HERRAMIENTAS,
        system_prompt=SYSTEM_AGENTE,
        middleware=[DatosDelTaller()],
        checkpointer=checkpointer,
        name="agente_cz_A2A",
    )


graph = crear_agente()
