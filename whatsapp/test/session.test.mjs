import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, readdir, readFile, writeFile, mkdir, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

import { SesionDurable, TABLA } from '../src/session.mjs';

const SECRETO = 'secreto-de-prueba-para-la-sesion';
const LOGGER = { info() {}, warn() {} };

class PoolFalso {
  constructor() {
    this.filas = new Map();
  }

  async query(sql) {
    if (sql.includes('CREATE TABLE')) return { rows: [] };
    if (sql.trim().startsWith('SELECT')) return { rows: [...this.filas.values()] };
    throw new Error(`consulta inesperada: ${sql}`);
  }

  async connect() {
    const filas = this.filas;
    return {
      async query(sql, params = []) {
        if (/^(BEGIN|COMMIT|ROLLBACK)$/.test(sql.trim())) return { rows: [] };
        if (sql.includes('INSERT INTO')) {
          const [archivo, huella, iv, tag, datos] = params;
          filas.set(archivo, { archivo, huella, iv, tag, datos });
          return { rows: [] };
        }
        if (sql.includes('DELETE FROM')) {
          for (const archivo of params[0]) filas.delete(archivo);
          return { rows: [] };
        }
        throw new Error(`consulta inesperada: ${sql}`);
      },
      release() {},
    };
  }

  async end() {}
}

const carpeta = () => mkdtemp(join(tmpdir(), 'wa-sesion-'));

test('guarda en Postgres y restaura la sesi?n en otra carpeta', async () => {
  const origen = await carpeta();
  await writeFile(join(origen, 'creds.json'), JSON.stringify({ me: { id: '56911112222@s.whatsapp.net' } }));
  await writeFile(join(origen, 'app-state-sync-key-AAAA.json'), '{"clave":"x"}');

  const pool = new PoolFalso();
  const primera = new SesionDurable({
    connectionString: 'postgres://x', secret: SECRETO, directory: origen, Pool: () => {}, logger: LOGGER,
  });
  primera.Pool = function Pool() { return pool; };
  primera.pool = pool;
  assert.equal(await primera.guardar(), true);
  assert.equal(pool.filas.size, 2);
  // El contenido no se guarda en claro.
  const fila = pool.filas.get('creds.json');
  assert.ok(!Buffer.from(fila.datos).toString('utf8').includes('56911112222'));

  const destino = await carpeta();
  const segunda = new SesionDurable({
    connectionString: 'postgres://x', secret: SECRETO, directory: destino, logger: LOGGER,
  });
  segunda.Pool = function Pool() { return pool; };
  assert.equal(await segunda.abrir(), 2);
  const restaurado = JSON.parse(await readFile(join(destino, 'creds.json'), 'utf8'));
  assert.equal(restaurado.me.id, '56911112222@s.whatsapp.net');
  assert.deepEqual((await readdir(destino)).sort(), ['app-state-sync-key-AAAA.json', 'creds.json']);
});

test('con otro WHATSAPP_SECRET no restaura nada y no lanza', async () => {
  const origen = await carpeta();
  await writeFile(join(origen, 'creds.json'), '{"a":1}');
  const pool = new PoolFalso();
  const guardado = new SesionDurable({
    connectionString: 'postgres://x', secret: SECRETO, directory: origen, logger: LOGGER,
  });
  guardado.Pool = function Pool() { return pool; };
  guardado.pool = pool;
  await guardado.guardar();

  const destino = await carpeta();
  const otra = new SesionDurable({
    connectionString: 'postgres://x', secret: 'otro-secreto-distinto', directory: destino, logger: LOGGER,
  });
  otra.Pool = function Pool() { return pool; };
  assert.equal(await otra.abrir(), 0);
  assert.deepEqual(await readdir(destino), []);
});

test('sin DATABASE_URL queda deshabilitada y no toca Postgres', async () => {
  const carpeta_local = await carpeta();
  await writeFile(join(carpeta_local, 'creds.json'), '{"a":1}');
  const sesion = new SesionDurable({ connectionString: '', secret: SECRETO, directory: carpeta_local });
  assert.equal(sesion.habilitada, false);
  assert.equal(await sesion.guardar(), false);
  assert.equal(await sesion.abrir(), 0);
});

test('borra de Postgres los archivos que ya no existen', async () => {
  const carpeta_local = await carpeta();
  await writeFile(join(carpeta_local, 'creds.json'), '{"a":1}');
  await writeFile(join(carpeta_local, 'app-state-sync-key-VIEJA.json'), '{"b":2}');
  const pool = new PoolFalso();
  const sesion = new SesionDurable({
    connectionString: 'postgres://x', secret: SECRETO, directory: carpeta_local, logger: LOGGER,
  });
  sesion.Pool = function Pool() { return pool; };
  sesion.pool = pool;
  await sesion.guardar();
  assert.equal(pool.filas.size, 2);

  await rm(join(carpeta_local, 'app-state-sync-key-VIEJA.json'));
  await writeFile(join(carpeta_local, 'creds.json'), '{"a":2}');
  await sesion.guardar();
  assert.deepEqual([...pool.filas.keys()], ['creds.json']);
});

test('la tabla vive en el prefijo czz_ del Postgres compartido', () => {
  assert.equal(TABLA, 'czz_wa_sesion');
});
