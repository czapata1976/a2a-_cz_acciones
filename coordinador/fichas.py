"""Lectura de las fichas A2A y elección del agente que sabe.

El coordinador no adivina: lee `/.well-known/agent-card.json` de cada agente de `URLS_AGENTES` y puntúa
la pregunta contra el nombre, la descripción, las skills, sus etiquetas y sus ejemplos. Nombrar al agente
(«¿qué hace Bryhan?») pesa más que cualquier palabra de su ficha. Si nadie alcanza puntuación, responde
que no tiene un agente para eso.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from urllib.parse import urlsplit, urlunsplit

import httpx

from canales.a2a import endpoint_y_version, seguridad_de_tarjeta
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
    cabecera: str = "X-Agente-Clave"
    """Cabecera donde el agente pide su clave, según su ficha."""
    prefijo: str = ""
    version: str = ""
    """`protocolVersion` de la interfaz que anuncia la ficha (puede venir vacía)."""

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


NOMBRE = 6
"""Puntos por nombrar al agente en la pregunta.

«¿Qué hace Bryhan?» no trae ninguna palabra de la ficha, solo el nombre: con el peso normal del nombre
(3) se quedaba por debajo del mínimo y el coordinador contestaba que no tenía un agente para eso. Nombrar
a alguien del equipo es la señal más fuerte que hay y basta por sí sola para elegirlo.
"""


def _casi_igual(una: str, otra: str) -> bool:
    """El mismo nombre con una letra de diferencia («bryan»/«bryhan»)."""
    if una == otra:
        return True
    corta, larga = sorted((una, otra), key=len)
    if len(corta) < 5 or len(larga) - len(corta) > 1:
        return False
    i = 0
    while i < len(corta) and corta[i] == larga[i]:
        i += 1
    if len(corta) == len(larga):
        return corta[i + 1:] == larga[i + 1:]
    return corta[i:] == larga[i + 1:]


def _nombres_propios(fichas: list[Ficha]) -> dict[str, set[str]]:
    """Palabras del nombre que identifican a **un** agente: el prefijo «agente» no distingue a nadie."""
    por_url = {ficha.url: {_raiz(palabra) for palabra in normalizar(ficha.nombre)} for ficha in fichas}
    vistos: dict[str, int] = {}
    for palabras in por_url.values():
        for palabra in palabras:
            vistos[palabra] = vistos.get(palabra, 0) + 1
    return {url: {p for p in palabras if vistos[p] == 1} for url, palabras in por_url.items()}


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
    propios = _nombres_propios(fichas)
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
        if any(
            _coinciden(nombre, buscada) or _casi_igual(nombre, buscada)
            for nombre in propios.get(ficha.url, set())
            for buscada in consulta
        ):
            puntos += NOMBRE
        ranking.append((ficha, puntos))
    ranking.sort(key=lambda par: par[1], reverse=True)
    return ranking


MINIMO = 4
"""Puntuación mínima para atreverse a elegir: por debajo, el coordinador dice que no tiene agente.

Con 3, una pregunta de seguimiento corta («¿y si el horizonte fuera 3 meses?») alcanzaba por dos palabras
sueltas de la ficha y acababa en el agente equivocado."""


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
                anunciado, ficha.version = endpoint_y_version(datos)
                _, ficha.cabecera, ficha.prefijo = seguridad_de_tarjeta(datos)
                ficha.endpoint = _endpoint_de(entrada.url, anunciado)
                ficha.estado = "disponible"
                ficha.detalle = ficha.endpoint
            except Exception as error:  # noqa: BLE001 - el estado se informa en la ficha
                ficha.estado = "no disponible"
                ficha.detalle = f"{type(error).__name__}: {error}"
                ficha.endpoint = _endpoint_de(entrada.url, "")
            fichas.append(ficha)
    return fichas
