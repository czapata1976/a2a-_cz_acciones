"""Servidor A2A mínimo en loopback para probar los clientes sin salir a la red.

Cubre los dos casos que dan problemas reales: un agente que pide la clave en otra cabecera y otro
cuyo manejador exige una versión de A2A distinta de la que anuncia su ficha.
"""
from __future__ import annotations

import json
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace


@contextmanager
def servidor(
    tarjeta: dict,
    *,
    clave: str = "",
    cabecera: str = "X-API-Key",
    versiones: tuple[str, ...] = (),
    texto: str = "respuesta del agente",
    forma: str = "message",
):
    """Publica `tarjeta` y un `POST /a2a` que respeta la clave y la versión declaradas.

    `{base}` dentro de la tarjeta se reemplaza por la URL real del servidor. `versiones` son las
    versiones de A2A que acepta el manejador; cualquier otra se rechaza como hace un servidor real.
    `forma` decide si el resultado es un `Message` (parts en la raíz) o una `Task`.
    """
    peticiones: list[dict] = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args) -> None:  # silencio: la prueba ya revisa las peticiones
            pass

        def _json(self, codigo: int, datos: dict) -> None:
            cuerpo = json.dumps(datos).encode()
            self.send_response(codigo)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(cuerpo)))
            self.end_headers()
            self.wfile.write(cuerpo)

        def do_GET(self) -> None:  # noqa: N802 - nombre que exige http.server
            base = f"http://{self.headers.get('host')}"
            self._json(200, json.loads(json.dumps(tarjeta).replace("{base}", base)))

        def do_POST(self) -> None:  # noqa: N802
            self.rfile.read(int(self.headers.get("Content-Length") or 0))
            peticiones.append({"path": self.path, "headers": dict(self.headers)})
            if clave and self.headers.get(cabecera) != clave:
                self._json(401, {"detail": "Clave de acceso ausente o inválida."})
                return
            version = self.headers.get("A2A-Version")
            if versiones and version and version not in versiones:
                self._json(200, {"jsonrpc": "2.0", "id": "1", "error": {
                    "code": -32603,
                    "message": (
                        f"A2A version '{version}' is not supported by this handler. "
                        f"Expected version '{versiones[0]}'."
                    ),
                }})
                return
            if forma == "task":
                resultado = {
                    "kind": "task",
                    "status": {"state": "completed", "message": {
                        "role": "agent", "parts": [{"kind": "text", "text": texto}],
                    }},
                }
            else:
                resultado = {
                    "kind": "message",
                    "messageId": "m-1",
                    "parts": [{"kind": "text", "text": texto}],
                }
            self._json(200, {"jsonrpc": "2.0", "id": "1", "result": resultado})

    servidor_http = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    hilo = threading.Thread(target=servidor_http.serve_forever, daemon=True)
    hilo.start()
    try:
        yield SimpleNamespace(
            base=f"http://127.0.0.1:{servidor_http.server_address[1]}",
            peticiones=peticiones,
        )
    finally:
        servidor_http.shutdown()
        servidor_http.server_close()


__all__ = ["servidor"]
