"""Persistencia del chat web: equipo de agentes, conversaciones y trazas del flujo.

Dos backends con la misma API: SQLite para local (`WEB_DATOS`, por defecto
`web/.runtime/chat.db`, ignorado por git) y Postgres cuando la ruta es una URL
(`DATABASE_URL` en Heroku). Las tablas van con prefijo `czz_` porque el Postgres del taller es
compartido con otros proyectos.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

PREFIJO_POSTGRES = "postgres"
"""El valor de `WEB_DATOS`/`DATABASE_URL` empieza así cuando el backend es Postgres."""

MAX_CHARLAS = 3
"""Conversaciones que se conservan: las más recientes. Las anteriores se borran con sus mensajes."""


def _ahora() -> str:
    # Con microsegundos: el orden de las conversaciones decide cuáles se conservan.
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


ESQUEMA_SQLITE = """
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

ESQUEMA_POSTGRES = """
CREATE TABLE IF NOT EXISTS czz_equipo (
    url TEXT PRIMARY KEY,
    nombre TEXT NOT NULL DEFAULT '',
    agregado_en TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS czz_charlas (
    id TEXT PRIMARY KEY,
    creada_en TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS czz_mensajes (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    charla_id TEXT NOT NULL,
    rol TEXT NOT NULL,
    texto TEXT NOT NULL,
    flujo TEXT NOT NULL DEFAULT '[]',
    creado_en TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_czz_mensajes_charla ON czz_mensajes(charla_id, id);
"""

# Las consultas se escriben con `?` (SQLite) y se traducen a `%s` en Postgres.
TABLAS = {
    "sqlite": {"equipo": "equipo", "charlas": "charlas", "mensajes": "mensajes"},
    "postgres": {
        "equipo": "czz_equipo",
        "charlas": "czz_charlas",
        "mensajes": "czz_mensajes",
    },
}


def es_postgres(ruta: str | Path) -> bool:
    """¿La ruta es una URL de Postgres en vez del archivo SQLite?"""
    return str(ruta).strip().lower().startswith(PREFIJO_POSTGRES)


class Almacen:
    """Acceso a la base del chat. Cada método es corto y atómico."""

    def __init__(self, ruta: str | Path) -> None:
        self.ruta = str(ruta).strip()
        self._postgres = es_postgres(self.ruta)
        self._tablas = TABLAS["postgres" if self._postgres else "sqlite"]
        self._candado = threading.RLock()
        self._conexion = None
        self._pool = None
        self._ultima_marca: datetime | None = None
        if self._postgres:
            self._abrir_postgres()
        else:
            self._abrir_sqlite()

    # --- arranque ---------------------------------------------------------
    def _abrir_sqlite(self) -> None:
        if self.ruta != ":memory:":
            Path(self.ruta).parent.mkdir(parents=True, exist_ok=True)
        self._conexion = sqlite3.connect(self.ruta, check_same_thread=False)
        self._conexion.row_factory = sqlite3.Row
        with self._candado:
            self._conexion.executescript(ESQUEMA_SQLITE)
            self._conexion.commit()

    def _abrir_postgres(self) -> None:
        try:
            from psycopg.rows import dict_row
            from psycopg_pool import ConnectionPool
        except ImportError as error:  # pragma: no cover - depende del entorno
            raise RuntimeError(
                "Para usar Postgres instala las dependencias: pip install -r requirements.txt"
            ) from error
        # El plan gratuito del taller cierra conexiones inactivas: el pool las repone solo.
        self._pool = ConnectionPool(
            self.ruta,
            min_size=1,
            max_size=4,
            timeout=15,
            kwargs={"row_factory": dict_row, "autocommit": True},
            open=True,
        )
        with self._pool.connection() as conexion:
            conexion.execute(ESQUEMA_POSTGRES)

    def cerrar(self) -> None:
        with self._candado:
            if self._pool is not None:
                self._pool.close()
                self._pool = None
            elif self._conexion is not None:
                self._conexion.close()
                self._conexion = None

    # --- consultas --------------------------------------------------------
    def _sql(self, consulta: str) -> str:
        """Cambia `{tabla}` por su nombre real y los marcadores `?` por `%s` si es Postgres."""
        traducida = consulta.format(**self._tablas)
        if self._postgres:
            traducida = traducida.replace("?", "%s")
        return traducida

    def _leer(self, consulta: str, parametros: tuple = ()) -> list:
        consulta = self._sql(consulta)
        if self._pool is not None:
            with self._pool.connection() as conexion:
                return conexion.execute(consulta, parametros).fetchall()
        with self._candado:
            return self._conexion.execute(consulta, parametros).fetchall()

    def _escribir(self, consultas: list[tuple[str, tuple]]) -> int:
        """Ejecuta una o más sentencias y devuelve las filas afectadas por la primera."""
        traducidas = [(self._sql(c), p) for c, p in consultas]
        if self._pool is not None:
            with self._pool.connection() as conexion, conexion.transaction():
                filas = 0
                for posicion, (consulta, parametros) in enumerate(traducidas):
                    afectadas = conexion.execute(consulta, parametros).rowcount
                    if posicion == 0:
                        filas = afectadas
            return filas
        with self._candado:
            filas = 0
            for posicion, (consulta, parametros) in enumerate(traducidas):
                afectadas = self._conexion.execute(consulta, parametros).rowcount
                if posicion == 0:
                    filas = afectadas
            self._conexion.commit()
            return filas

    # --- equipo -----------------------------------------------------------
    def agentes(self) -> list[dict]:
        filas = self._leer("SELECT url, nombre, agregado_en FROM {equipo} ORDER BY agregado_en, url")
        return [dict(fila) for fila in filas]

    def agregar_agente(self, url: str, nombre: str = "") -> None:
        self._escribir([(
            "INSERT INTO {equipo} (url, nombre, agregado_en) VALUES (?, ?, ?) "
            "ON CONFLICT(url) DO UPDATE SET nombre = excluded.nombre",
            (url, nombre, _ahora()),
        )])

    def quitar_agente(self, url: str) -> bool:
        return self._escribir([("DELETE FROM {equipo} WHERE url = ?", (url,))]) > 0

    # --- conversaciones ---------------------------------------------------
    def _marca_charla(self) -> str:
        """Marca temporal estrictamente creciente.

        En Windows el reloj repite el mismo valor en llamadas seguidas, y el orden decide qué
        conversaciones se conservan: se fuerza que cada marca sea mayor que la anterior.
        """
        with self._candado:
            ahora = datetime.now(timezone.utc)
            if self._ultima_marca is None:
                filas = self._leer("SELECT MAX(creada_en) AS ultima FROM {charlas}")
                guardada = filas[0]["ultima"] if filas else None
                try:
                    self._ultima_marca = datetime.fromisoformat(guardada) if guardada else ahora
                except (TypeError, ValueError):
                    self._ultima_marca = ahora
            if ahora <= self._ultima_marca:
                ahora = self._ultima_marca + timedelta(microseconds=1)
            self._ultima_marca = ahora
            return ahora.isoformat(timespec="microseconds")

    def crear_charla(self) -> str:
        identificador = str(uuid.uuid4())
        self._escribir([(
            "INSERT INTO {charlas} (id, creada_en) VALUES (?, ?)",
            (identificador, self._marca_charla()),
        )])
        self.podar_charlas()
        return identificador

    def podar_charlas(self, limite: int = MAX_CHARLAS) -> int:
        """Borra las conversaciones más viejas y devuelve cuántas quedaron fuera."""
        sobrantes = [
            fila["id"]
            for fila in self._leer("SELECT id FROM {charlas} ORDER BY creada_en DESC, id DESC")
        ][limite:]
        for charla_id in sobrantes:
            self._escribir([
                ("DELETE FROM {mensajes} WHERE charla_id = ?", (charla_id,)),
                ("DELETE FROM {charlas} WHERE id = ?", (charla_id,)),
            ])
        return len(sobrantes)

    def existe_charla(self, charla_id: str) -> bool:
        filas = self._leer("SELECT 1 AS existe FROM {charlas} WHERE id = ?", (charla_id,))
        return bool(filas)

    def charlas(self) -> list[dict]:
        filas = self._leer(
            "SELECT c.id, c.creada_en, "
            "(SELECT COUNT(*) FROM {mensajes} m WHERE m.charla_id = c.id) AS mensajes, "
            "(SELECT texto FROM {mensajes} m WHERE m.charla_id = c.id AND m.rol = 'user' "
            " ORDER BY m.id LIMIT 1) AS titulo "
            "FROM {charlas} c ORDER BY c.creada_en DESC LIMIT ?",
            (MAX_CHARLAS,),
        )
        return [dict(fila) for fila in filas]

    def borrar_charla(self, charla_id: str) -> bool:
        filas = self._escribir([
            ("DELETE FROM {charlas} WHERE id = ?", (charla_id,)),
            ("DELETE FROM {mensajes} WHERE charla_id = ?", (charla_id,)),
        ])
        return filas > 0

    def mensajes(self, charla_id: str) -> list[dict]:
        filas = self._leer(
            "SELECT rol, texto, flujo, creado_en FROM {mensajes} WHERE charla_id = ? ORDER BY id",
            (charla_id,),
        )
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
        self._escribir([(
            "INSERT INTO {mensajes} (charla_id, rol, texto, flujo, creado_en) VALUES (?, ?, ?, ?, ?)",
            (charla_id, rol, texto, json.dumps(flujo or [], ensure_ascii=False), _ahora()),
        )])
