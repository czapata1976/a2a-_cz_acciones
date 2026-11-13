"""Supervisor del equipo A2A: elige **un** agente, lo cita y recuerda la conversación.

Es un grafo LangGraph con `MemorySaver`: un hilo por cliente (`thread_id`). Dentro del hilo recuerda las
preguntas anteriores, así una pregunta que solo se entiende con la anterior se resuelve; desde otro hilo
no aparece nada. Un reinicio del proceso borra la memoria (límite conocido y declarado).

Reglas que no se negocian:

- La respuesta del agente se devuelve **tal cual**: el coordinador no reescribe cifras, unidades ni fechas.
- Siempre se dice qué agente respondió.
- Si nadie del equipo sabe, dice que no tiene un agente para eso (no inventa).
- Si el agente elegido no responde, avisa que esa parte no está disponible y el resto sigue en pie.
- Un intento de cambiar sus instrucciones no lo convierte en otra cosa.
"""
from __future__ import annotations

import operator
import re
import time
import unicodedata
from dataclasses import dataclass, field
from typing import Annotated, TypedDict

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from coordinador import a2a
from coordinador.fichas import Ficha, elegir, normalizar

SALUDO = (
    "Soy el coordinador del equipo A2A. Puedo preguntar a estos agentes:\n"
    "{agentes}\n\n"
    "Escribe tu pregunta y la paso al agente que corresponde."
)

INYECCION = (
    "Sigo siendo el coordinador del equipo A2A y no cambio mis instrucciones. "
    "Mi trabajo es pasar tu pregunta al agente del equipo que sabe:\n{agentes}"
)

SIN_AGENTE = (
    "No tengo un agente para eso. El equipo cubre lo siguiente:\n{agentes}"
)

CAIDO = (
    "La parte de {agente} no está disponible ahora ({motivo}). Los demás agentes siguen disponibles:\n"
    "{otros}"
)

NO_LEIBLE = (
    "No puedo leer ese tipo de mensaje: solo entiendo texto. Escríbeme tu consulta en palabras."
)

FRASES_INYECCION = (
    "ignora tus instrucciones", "ignora las instrucciones", "olvida tus instrucciones",
    "olvida todo lo anterior", "ignore your instructions", "ignore previous instructions",
    "ignore all previous", "ahora eres", "actua como", "actúa como", "revela tus instrucciones",
    "muestrame tus instrucciones", "muéstrame tus instrucciones", "system prompt", "prompt del sistema",
    "cambia tus reglas", "sin restricciones",
)


class Estado(TypedDict, total=False):
    consulta: str
    historial: Annotated[list[str], operator.add]
    saltos: list[dict]
    agente: str
    endpoint: str
    respuesta: str
    respuesta_agente: str
    motivo: str


@dataclass
class Resultado:
    """Lo que devuelve el coordinador a quien preguntó."""

    respuesta: str
    agente: str | None = None
    motivo: str = "ok"
    saltos: list[dict] = field(default_factory=list)
    respuesta_agente: str = ""
    """Texto exacto que devolvió el agente, antes de citarlo (para comprobar que no se alteró)."""


def _plano(texto: str) -> str:
    sin_acentos = "".join(
        c for c in unicodedata.normalize("NFD", texto or "") if unicodedata.category(c) != "Mn"
    )
    return re.sub(r"\s+", " ", sin_acentos.lower()).strip()


def es_intento_de_inyeccion(texto: str) -> bool:
    plano = _plano(texto)
    return any(frase in plano for frase in FRASES_INYECCION)


CONECTORES_SEGUIMIENTO = (
    "y ", "¿y", "y si", "entonces", "ahora", "el mismo", "la misma", "lo mismo", "eso", "ese",
    "esa", "también", "tambien", "igual", "además", "ademas", "otro horizonte", "ese caso",
)


def es_seguimiento(texto: str) -> bool:
    """True si la pregunta solo se entiende con el turno anterior («¿y a 3 meses?»).

    El historial se usa **solo** en ese caso: si se usara siempre, una consulta de otro tema heredaría
    el asunto de la pregunta previa y acabaría en el agente equivocado.
    """
    plano = _plano(texto)
    if any(plano.startswith(conector) for conector in CONECTORES_SEGUIMIENTO):
        return True
    return len(normalizar(texto)) <= 3


def _lista_agentes(fichas: list[Ficha]) -> str:
    lineas = []
    for ficha in fichas:
        estado = "" if ficha.estado == "disponible" else " (no disponible ahora)"
        lineas.append(f"- {ficha.nombre or ficha.url}: {ficha.resumen_skills()}{estado}")
    return "\n".join(lineas) if lineas else "- (sin agentes configurados)"


def _paso(nombre: str, detalle: str, inicio: float) -> dict:
    return {"paso": nombre, "detalle": detalle, "ms": round((time.perf_counter() - inicio) * 1000)}


class Supervisor:
    """Grafo `elegir → consultar → componer` con memoria por cliente."""

    def __init__(self, fichas: list[Ficha], timeout: float = 60.0, consultar=a2a.consultar) -> None:
        self.fichas = fichas
        self.timeout = timeout
        self._enviar = consultar
        self.checkpointer = MemorySaver()
        self.grafo = self._compilar()

    # --- nodos ------------------------------------------------------------
    async def _elegir(self, estado: Estado) -> dict:
        inicio = time.perf_counter()
        consulta = estado.get("consulta", "")
        historial = list(estado.get("historial") or [])[-3:]
        texto_eleccion = " ".join([*historial, consulta]) if es_seguimiento(consulta) else consulta

        if not normalizar(consulta):
            return {
                "motivo": "saludo",
                "respuesta": SALUDO.format(agentes=_lista_agentes(self.fichas)),
                "respuesta_agente": "",
                "saltos": [_paso("elegir", "saludo: presento el equipo", inicio)],
            }
        if es_intento_de_inyeccion(consulta):
            return {
                "motivo": "inyeccion",
                "respuesta": INYECCION.format(agentes=_lista_agentes(self.fichas)),
                "respuesta_agente": "",
                "saltos": [_paso("elegir", "intento de cambiar instrucciones: no obedezco", inicio)],
            }

        ficha, ranking = elegir(self.fichas, texto_eleccion)
        resumen = ", ".join(f"{f.nombre}={p}" for f, p in ranking[:3]) or "sin candidatos"
        if ficha is None:
            return {
                "motivo": "ninguno",
                "respuesta": SIN_AGENTE.format(agentes=_lista_agentes(self.fichas)),
                "respuesta_agente": "",
                "saltos": [_paso("elegir", f"ningún agente alcanza ({resumen})", inicio)],
            }
        return {
            "motivo": "elegido",
            "agente": ficha.nombre or ficha.url,
            "endpoint": ficha.endpoint,
            "respuesta_agente": "",
            "saltos": [_paso("elegir", f"elijo {ficha.nombre} ({resumen})", inicio)],
        }

    async def _consultar(self, estado: Estado, config: RunnableConfig) -> dict:
        inicio = time.perf_counter()
        nombre = estado.get("agente", "")
        ficha = next((f for f in self.fichas if (f.nombre or f.url) == nombre), None)
        if ficha is None:
            return {
                "motivo": "caido",
                "respuesta": SIN_AGENTE.format(agentes=_lista_agentes(self.fichas)),
                "saltos": [*estado.get("saltos", []), _paso("consultar", "no encontré la ficha elegida", inicio)],
            }
        hilo = str((config.get("configurable") or {}).get("thread_id") or "sin-cliente")
        try:
            texto = await self._enviar(ficha, estado["consulta"], hilo, self.timeout)
        except a2a.ErrorAgente as error:
            otros = "\n".join(
                f"- {f.nombre}: {f.resumen_skills()}"
                for f in self.fichas
                if (f.nombre or f.url) != nombre and f.estado == "disponible"
            ) or "- (ningún otro agente disponible)"
            return {
                "motivo": "caido",
                "respuesta": CAIDO.format(agente=nombre, motivo=error, otros=otros),
                "saltos": [*estado.get("saltos", []), _paso("consultar", f"{nombre} falló: {error}", inicio)],
            }
        return {
            "motivo": "ok",
            "respuesta_agente": texto,
            "saltos": [*estado.get("saltos", []),
                       _paso("consultar", f"{nombre} respondió {len(texto)} caracteres", inicio)],
        }

    async def _componer(self, estado: Estado) -> dict:
        inicio = time.perf_counter()
        motivo = estado.get("motivo", "ok")
        saltos = list(estado.get("saltos", []))
        if motivo in {"saludo", "inyeccion", "ninguno", "caido"}:
            return {"saltos": [*saltos, _paso("componer", "respuesta del coordinador, sin agente", inicio)]}
        texto = estado.get("respuesta_agente", "")
        nombre = estado.get("agente", "")
        endpoint = estado.get("endpoint", "")
        final = f"Respondió: {nombre}\n{endpoint}\n\n{texto}"
        return {
            "respuesta": final,
            "saltos": [*saltos, _paso("componer", f"cito a {nombre} sin alterar su texto", inicio)],
        }

    def _ruta(self, estado: Estado) -> str:
        return "consultar" if estado.get("motivo") == "elegido" else "componer"

    def _compilar(self):
        grafo = StateGraph(Estado)
        grafo.add_node("elegir", self._elegir)
        grafo.add_node("consultar", self._consultar)
        grafo.add_node("componer", self._componer)
        grafo.add_edge(START, "elegir")
        grafo.add_conditional_edges("elegir", self._ruta, {"consultar": "consultar", "componer": "componer"})
        grafo.add_edge("consultar", "componer")
        grafo.add_edge("componer", END)
        return grafo.compile(checkpointer=self.checkpointer)

    # --- uso --------------------------------------------------------------
    async def responder(self, cliente: str, texto: str) -> Resultado:
        estado = await self.grafo.ainvoke(
            {"consulta": texto, "historial": [texto], "saltos": []},
            {"configurable": {"thread_id": cliente}},
        )
        motivo = estado.get("motivo", "ok")
        crudo = estado.get("respuesta_agente", "") if motivo == "ok" else ""
        return Resultado(
            respuesta=estado.get("respuesta", ""),
            agente=estado.get("agente") if motivo == "ok" else None,
            motivo=motivo,
            saltos=list(estado.get("saltos") or []),
            respuesta_agente=crudo,
        )
