"""Lectura de las fichas A2A y elección del agente que sabe.

El coordinador no adivina: lee `/.well-known/agent-card.json` de cada agente de `URLS_AGENTES` y puntúa
la pregunta contra el nombre, la descripción, las skills, sus etiquetas y sus ejemplos. Si nadie alcanza
puntuación, responde que no tiene un agente para eso.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from urllib.parse import urlsplit, urlunsplit

import httpx

from coordinador.config import AgenteConfigurado

RUTA_TARJETA = "/.well-known/agent-card.json"

VACIAS = {
    "a", "al", "algo", "como", "con", "cual", "cuanto", "cuanta", "cuantos", "de", "del", "dime",
    "el", "en", "es", "esa", "ese", "eso", "esta", "este", "esto", "hace", "hacer", "hay", "la",
    "las", "le", "lo", "los", "me", "mi", "mis", "mucho", "necesito", "no", "nos", "o", "para",
    "pero", "por", "puedes", "que", "quien", "quiero", "se", "ser", "si", "sin", "sobre", "su",
    "sus", "te", "tengo", "tiene", "tu", "un", "una", "uno", "y", "ya", "hola", "buenas", "favor",
    "gracias", "ayuda", "ayudame", "sabes", "podrias", "favor", "the", "of", "and", "for", "with",
}


@dataclass
class Ficha:
    """Lo que el coordinador sabe de un agente."""

    url: str
    nombre: str = ""
    descripcion: str = ""
    skills: list[dict] = field(default_factory=list)
    clave: str = ""
    estado: str = "no disponible"
    detalle: str = ""
    endpoint: str = ""

    def resumen_skills(self) -> str:
        nombres = [str(s.get("name") or s.get("id") or "").strip() for s in self.skills]
        nombres = [n for n in nombres if n]
        return "; ".join(nombres) if nombres else "sin skills declaradas"


def _sin_acentos(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn")


def normalizar(texto: str) -> list[str]:
    """Palabras significativas, sin acentos ni signos, en minúsculas."""
    limpio = _sin_acentos((texto or "").lower())
    palabras = re.findall(r"[a-z0-9]{3,}", limpio)
    return [p for p in palabras if p not in VACIAS]


def _raiz(palabra: str) -> str:
    """Raíz sencilla: une plurales y formas verbales («acciones»/«acción», «analiza»/«analizar»)."""
    if len(palabra) > 4:
        if palabra.endswith("es"):
            palabra = palabra[:-2]
        elif palabra.endswith("s"):
            palabra = palabra[:-1]
    if len(palabra) > 4 and palabra.endswith(("ar", "er", "ir")):
        palabra = palabra[:-2]
    if len(palabra) > 4 and palabra.endswith(("a", "o", "e")):
        palabra = palabra[:-1]
    return palabra


def _coinciden(una: str, otra: str) -> bool:
    """Iguales por raíz o con prefijo común suficiente (automatizar / automatización)."""
    if una == otra:
        return True
    corto = min(len(una), len(otra))
    if corto < 6:
        return False
    comunes = 0
    for letra_a, letra_b in zip(una, otra):
        if letra_a != letra_b:
            break
        comunes += 1
    return comunes >= 6 and comunes >= corto - 2


def _palabras_de(ficha: Ficha) -> dict[str, int]:
    """Bolsa de raíces ponderada de la ficha."""
    bolsa: dict[str, int] = {}

    def sumar(texto: str, peso: int) -> None:
        for palabra in normalizar(texto):
            bolsa[_raiz(palabra)] = max(bolsa.get(_raiz(palabra), 0), peso)

    sumar(ficha.nombre, 3)
    for skill in ficha.skills:
        sumar(str(skill.get("name") or ""), 4)
        sumar(" ".join(str(t) for t in skill.get("tags") or []), 4)
        sumar(str(skill.get("description") or ""), 2)
        sumar(" ".join(str(e) for e in skill.get("examples") or []), 1)
    sumar(ficha.descripcion, 1)
    return bolsa


def puntuar(fichas: list[Ficha], texto: str) -> list[tuple[Ficha, int]]:
    """Ordena las fichas por afinidad con el texto de la pregunta."""
    consulta = {_raiz(palabra) for palabra in normalizar(texto)}
    ranking: list[tuple[Ficha, int]] = []
    for ficha in fichas:
        if ficha.estado != "disponible":
            continue
        bolsa = _palabras_de(ficha)
        puntos = sum(
            peso
            for palabra, peso in bolsa.items()
            if any(_coinciden(palabra, buscada) for buscada in consulta)
        )
        ranking.append((ficha, puntos))
    ranking.sort(key=lambda par: par[1], reverse=True)
    return ranking


MINIMO = 3
"""Puntuación mínima para atreverse a elegir: por debajo, el coordinador dice que no tiene agente."""


def elegir(fichas: list[Ficha], texto: str) -> tuple[Ficha | None, list[tuple[Ficha, int]]]:
    """Devuelve el agente que mejor responde y el ranking completo (para `--saltos`)."""
    ranking = puntuar(fichas, texto)
    if not ranking or ranking[0][1] < MINIMO:
        return None, ranking
    return ranking[0][0], ranking


def _endpoint_de(base: str, anunciado: str) -> str:
    """Endpoint A2A: manda el host/esquema configurado y la ruta que anuncia la tarjeta.

    Igual que en el chat web: una tarjeta en Cloud Run anuncia `http://` aunque se le hable por HTTPS,
    y una tarjeta detrás de un túnel anuncia su `127.0.0.1`. La URL configurada manda.
    """
    destino = urlsplit(base)
    ruta = urlsplit(anunciado).path if anunciado else ""
    return urlunsplit((destino.scheme, destino.netloc, ruta.rstrip("/") or "/a2a", "", ""))


async def leer_fichas(entradas: list[AgenteConfigurado], timeout: float = 15.0) -> list[Ficha]:
    """Lee la tarjeta de cada agente. Un agente caído queda marcado, no tumba al coordinador."""
    fichas: list[Ficha] = []
    async with httpx.AsyncClient(timeout=timeout, trust_env=False, follow_redirects=True) as cliente:
        for entrada in entradas:
            ficha = Ficha(url=entrada.url, clave=entrada.clave)
            try:
                respuesta = await cliente.get(f"{entrada.url}{RUTA_TARJETA}")
                respuesta.raise_for_status()
                datos = respuesta.json()
                if not isinstance(datos, dict):
                    raise ValueError("la tarjeta no es un objeto JSON")
                ficha.nombre = str(datos.get("name") or entrada.url)
                ficha.descripcion = str(datos.get("description") or "")
                ficha.skills = list(datos.get("skills") or [])
                ficha.endpoint = _endpoint_de(entrada.url, str(datos.get("url") or ""))
                ficha.estado = "disponible"
                ficha.detalle = ficha.endpoint
            except Exception as error:  # noqa: BLE001 - el estado se informa en la ficha
                ficha.estado = "no disponible"
                ficha.detalle = f"{type(error).__name__}: {error}"
                ficha.endpoint = _endpoint_de(entrada.url, "")
            fichas.append(ficha)
    return fichas
