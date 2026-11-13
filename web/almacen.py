"""Persistencia del chat web: equipo de agentes, conversaciones y trazas del flujo.

SQLite del propio proyecto (`WEB_DATOS`, por defecto `web/.runtime/chat.db`, ignorado por git).
Una sola conexión con candado: la API es asíncrona pero las consultas son instantáneas.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path


def _ahora() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


ESQUEMA = """
CREATE TABLE IF NOT EXISTS equipo (
    url TEXT PRIMARY KEY,
    nombre TEXT NOT NULL DEFAULT '',
    agregado_en TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS charlas (
    id TEXT PRIMARY KEY,
    creada_en TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS mensajes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    charla_id TEXT NOT NULL,
    rol TEXT NOT NULL,
    texto TEXT NOT NULL,
    flujo TEXT NOT NULL DEFAULT '[]',
    creado_en TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_mensajes_charla ON mensajes(charla_id, id);
"""


class Almacen:
    """Acceso a la base del chat. Cada método es corto y atómico."""

    def __init__(self, ruta: str | Path) -> None:
        self.ruta = str(ruta)
        if self.ruta != ":memory:":
            Path(self.ruta).parent.mkdir(parents=True, exist_ok=True)
        self._candado = threading.Lock()
        self._conexion = sqlite3.connect(self.ruta, check_same_thread=False)
        self._conexion.row_factory = sqlite3.Row
        with self._candado:
            self._conexion.executescript(ESQUEMA)
            self._conexion.commit()

    def cerrar(self) -> None:
        with self._candado:
            self._conexion.close()

    # --- equipo -----------------------------------------------------------
    def agentes(self) -> list[dict]:
        with self._candado:
            filas = self._conexion.execute(
                "SELECT url, nombre, agregado_en FROM equipo ORDER BY agregado_en, url"
            ).fetchall()
        return [dict(fila) for fila in filas]

    def agregar_agente(self, url: str, nombre: str = "") -> None:
        with self._candado:
            self._conexion.execute(
                "INSERT INTO equipo (url, nombre, agregado_en) VALUES (?, ?, ?) "
                "ON CONFLICT(url) DO UPDATE SET nombre = excluded.nombre",
                (url, nombre, _ahora()),
            )
            self._conexion.commit()

    def quitar_agente(self, url: str) -> bool:
        with self._candado:
            cursor = self._conexion.execute("DELETE FROM equipo WHERE url = ?", (url,))
            self._conexion.commit()
        return cursor.rowcount > 0

    # --- conversaciones ---------------------------------------------------
    def crear_charla(self) -> str:
        identificador = str(uuid.uuid4())
        with self._candado:
            self._conexion.execute(
                "INSERT INTO charlas (id, creada_en) VALUES (?, ?)", (identificador, _ahora())
            )
            self._conexion.commit()
        return identificador

    def existe_charla(self, charla_id: str) -> bool:
        with self._candado:
            fila = self._conexion.execute(
                "SELECT 1 FROM charlas WHERE id = ?", (charla_id,)
            ).fetchone()
        return fila is not None

    def charlas(self) -> list[dict]:
        with self._candado:
            filas = self._conexion.execute(
                "SELECT c.id, c.creada_en, "
                "(SELECT COUNT(*) FROM mensajes m WHERE m.charla_id = c.id) AS mensajes, "
                "(SELECT texto FROM mensajes m WHERE m.charla_id = c.id AND m.rol = 'user' "
                " ORDER BY m.id LIMIT 1) AS titulo "
                "FROM charlas c ORDER BY c.creada_en DESC"
            ).fetchall()
        return [dict(fila) for fila in filas]

    def borrar_charla(self, charla_id: str) -> bool:
        with self._candado:
            cursor = self._conexion.execute("DELETE FROM charlas WHERE id = ?", (charla_id,))
            self._conexion.execute("DELETE FROM mensajes WHERE charla_id = ?", (charla_id,))
            self._conexion.commit()
        return cursor.rowcount > 0

    def mensajes(self, charla_id: str) -> list[dict]:
        with self._candado:
            filas = self._conexion.execute(
                "SELECT rol, texto, flujo, creado_en FROM mensajes WHERE charla_id = ? ORDER BY id",
                (charla_id,),
            ).fetchall()
        return [
            {
                "rol": fila["rol"],
                "texto": fila["texto"],
                "flujo": json.loads(fila["flujo"] or "[]"),
                "creado_en": fila["creado_en"],
            }
            for fila in filas
        ]

    def agregar_mensaje(
        self, charla_id: str, rol: str, texto: str, flujo: list[dict] | None = None
    ) -> None:
        with self._candado:
            self._conexion.execute(
                "INSERT INTO mensajes (charla_id, rol, texto, flujo, creado_en) VALUES (?, ?, ?, ?, ?)",
                (charla_id, rol, texto, json.dumps(flujo or [], ensure_ascii=False), _ahora()),
            )
            self._conexion.commit()
