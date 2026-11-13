"""Publica la ficha del agente en su Agent Card (nombre y descripción).

`langgraph dev` crea el asistente con una descripción genérica; otro agente descubre este servicio
por la tarjeta, así que conviene dejarle una descripción que explique qué resuelve y qué no.

Uso (con el servidor arriba):
    .venv\\Scripts\\python.exe scripts\\configurar_tarjeta.py
    .venv\\Scripts\\python.exe scripts\\configurar_tarjeta.py --url https://<algo>.trycloudflare.com
"""
from __future__ import annotations

import argparse
import os

import httpx
from dotenv import load_dotenv

DESCRIPCION = (
    "Servicio A2A autónomo de Carlos Zapata: analiza acciones con datos de mercado y fundamentales "
    "(PER, deuda/patrimonio y márgenes), entrega una decisión condicionada al perfil de riesgo y al "
    "horizonte, y declara fuera de alcance lo contable o tributario. No ejecuta pagos ni inversiones."
)


def main() -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(description="Configura la Agent Card de agente_cz_A2A")
    parser.add_argument("--url", default=os.environ.get("A2A_CZZ_URL", "http://127.0.0.1:2029"))
    parser.add_argument("--graph", default=os.environ.get("A2A_CZZ_GRAPH", "agente_cz_A2A"))
    args = parser.parse_args()

    with httpx.Client(base_url=args.url, timeout=30) as cliente:
        asistentes = cliente.post("/assistants/search", json={"graph_id": args.graph}).json()
        if not asistentes:
            print(f"No encontré el grafo {args.graph} en {args.url}. ¿Está levantado el servidor?")
            return 1
        assistant_id = asistentes[0]["assistant_id"]

        ficha = cliente.patch(
            f"/assistants/{assistant_id}",
            json={"name": args.graph, "description": DESCRIPCION},
        ).json()
        print(f"Asistente {ficha.get('assistant_id', assistant_id)} actualizado.")

        tarjeta = cliente.get(
            "/.well-known/agent-card.json", params={"assistant_id": assistant_id}
        ).json()
        print(f"Tarjeta: {tarjeta.get('name')} · {tarjeta.get('description')}")
        print(f"Endpoint A2A: {tarjeta.get('url')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
