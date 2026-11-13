import { createCipheriv, createDecipheriv, createHash, randomBytes, scryptSync } from 'node:crypto';
import { mkdir, readdir, readFile, writeFile } from 'node:fs/promises';
import { resolve } from 'node:path';

/**
 * Sesi?n de WhatsApp durable en Postgres.
 *
 * En Heroku el disco del dyno es ef?mero y se recicla al menos cada 24 h: si las credenciales de
 * Baileys solo viven en `whatsapp/.runtime/`, hay que volver a escanear el QR en cada reinicio. Esta
 * clase guarda esos archivos en una tabla propia (`czz_wa_sesion`, mismo Postgres del taller) y los
 * restaura al arrancar. El contenido va cifrado con AES-256-GCM y una llave derivada de
 * `WHATSAPP_SECRET`, porque la base es compartida con otros proyectos.
 *
 * El puente sigue escribiendo en disco (es lo que espera `useMultiFileAuthState`); Postgres es la
 * copia que sobrevive al dyno. Sin `DATABASE_URL` la clase queda deshabilitada y todo funciona como
 * antes, solo en local.
 */
export const TABLA = 'czz_wa_sesion';
const SAL = 'czz-wa-sesion';
const ARCHIVO = /^[A-Za-z0-9._-]{1,120}\.json$/;

const llave = (secreto) => scryptSync(secreto, SAL, 32);

/** Quita `sslmode` de la URL: la configuración de SSL se fija en el Pool. */
export function sinSslmode(url) {
    try {
        const partes = new URL(url);
        partes.searchParams.delete('sslmode');
        partes.searchParams.delete('uselibpqcompat');
        return partes.toString();
    } catch {
        return url;
    }
}

function cifrar(clave, texto) {
    const iv = randomBytes(12);
    const cifrador = createCipheriv('aes-256-gcm', clave, iv);
    const datos = Buffer.concat([cifrador.update(texto, 'utf8'), cifrador.final()]);
    return { iv, tag: cifrador.getAuthTag(), datos };
}

function descifrar(clave, iv, tag, datos) {
    const descifrador = createDecipheriv('aes-256-gcm', clave, iv);
    descifrador.setAuthTag(tag);
    return Buffer.concat([descifrador.update(datos), descifrador.final()]).toString('utf8');
}

export class SesionDurable {
    constructor({ connectionString = '', secret = '', directory, Pool = null, logger = null } = {}) {
        Object.assign(this, {
            connectionString,
            secret,
            directory: resolve(directory),
            Pool,
            logger,
            pool: null,
            huellas: new Map(),
            cola: Promise.resolve(),
        });
    }

    get habilitada() {
        return Boolean(this.connectionString && this.secret);
    }

    async _conectar() {
        if (this.pool) return this.pool;
        const Pool = this.Pool ?? (await import('pg')).Pool;
        this.pool = new Pool({
            // El `sslmode=require` de la URL acaba exigiendo la cadena completa del certificado, que el
            // Postgres del taller no entrega. Se quita de la cadena y se fija el SSL aquí: lo que se
            // guarda ya va cifrado con AES-256-GCM, así que la confidencialidad no depende del servidor.
            connectionString: sinSslmode(this.connectionString),
            ssl: { rejectUnauthorized: false },
            max: 1,
            // La base del taller es compartida: no retener conexiones si algo se cuelga.
            idleTimeoutMillis: 30000,
            connectionTimeoutMillis: 10000,
        });
        await this.pool.query(
            `CREATE TABLE IF NOT EXISTS ${TABLA} (
                archivo text PRIMARY KEY,
                huella text NOT NULL,
                iv bytea NOT NULL,
                tag bytea NOT NULL,
                datos bytea NOT NULL,
                actualizado_en timestamptz NOT NULL DEFAULT now()
            )`,
        );
        return this.pool;
    }

    async _archivos() {
        try {
            const nombres = await readdir(this.directory);
            return nombres.filter((nombre) => ARCHIVO.test(nombre)).sort();
        } catch {
            return [];
        }
    }

    /** Restaura la sesi?n guardada; devuelve cu?ntos archivos recuper?. Nunca lanza. */
    async abrir() {
        if (!this.habilitada) return 0;
        try {
            await mkdir(this.directory, { recursive: true, mode: 0o700 });
            const pool = await this._conectar();
            const { rows } = await pool.query(
                `SELECT archivo, huella, iv, tag, datos FROM ${TABLA} ORDER BY archivo`,
            );
            const clave = llave(this.secret);
            let restaurados = 0;
            for (const fila of rows) {
                if (!ARCHIVO.test(String(fila.archivo))) continue;
                try {
                    const texto = descifrar(clave, fila.iv, fila.tag, fila.datos);
                    await writeFile(resolve(this.directory, fila.archivo), texto, { mode: 0o600 });
                    this.huellas.set(fila.archivo, fila.huella);
                    restaurados++;
                } catch {
                    // La llave cambi? (otro WHATSAPP_SECRET): la fila no sirve y hay que revincular.
                    this.logger?.warn({ archivo: fila.archivo }, 'sesi?n guardada ilegible; se ignora');
                }
            }
            if (!restaurados && (await this._archivos()).length) {
                // Primera vez con base de datos: sube la sesi?n que ya estaba en disco.
                await this.guardar();
            }
            this.logger?.info({ restaurados }, 'sesi?n de WhatsApp restaurada');
            return restaurados;
        } catch (error) {
            this.logger?.warn({ detalle: error?.message }, 'no pude restaurar la sesi?n de WhatsApp');
            return 0;
        }
    }

    /** Copia a Postgres los archivos que cambiaron. Serializa las llamadas. */
    guardar() {
        this.cola = this.cola.then(() => this._guardar()).catch(() => false);
        return this.cola;
    }

    async _guardar() {
        if (!this.habilitada) return false;
        try {
            const pool = await this._conectar();
            const clave = llave(this.secret);
            const nombres = await this._archivos();
            if (!nombres.length) return false;
            const cambios = [];
            for (const nombre of nombres) {
                const texto = await readFile(resolve(this.directory, nombre), 'utf8');
                const huella = createHash('sha256').update(texto).digest('hex');
                if (this.huellas.get(nombre) === huella) continue;
                cambios.push({ nombre, huella, ...cifrar(clave, texto) });
            }
            const obsoletos = [...this.huellas.keys()].filter((nombre) => !nombres.includes(nombre));
            if (!cambios.length && !obsoletos.length) return true;

            const cliente = await pool.connect();
            try {
                await cliente.query('BEGIN');
                for (const cambio of cambios) {
                    await cliente.query(
                        `INSERT INTO ${TABLA} (archivo, huella, iv, tag, datos, actualizado_en)
                         VALUES ($1, $2, $3, $4, $5, now())
                         ON CONFLICT (archivo) DO UPDATE
                         SET huella = EXCLUDED.huella, iv = EXCLUDED.iv, tag = EXCLUDED.tag,
                             datos = EXCLUDED.datos, actualizado_en = now()`,
                        [cambio.nombre, cambio.huella, cambio.iv, cambio.tag, cambio.datos],
                    );
                }
                if (obsoletos.length) {
                    await cliente.query(`DELETE FROM ${TABLA} WHERE archivo = ANY($1::text[])`, [obsoletos]);
                }
                await cliente.query('COMMIT');
            } catch (error) {
                await cliente.query('ROLLBACK');
                throw error;
            } finally {
                cliente.release();
            }
            for (const cambio of cambios) this.huellas.set(cambio.nombre, cambio.huella);
            for (const nombre of obsoletos) this.huellas.delete(nombre);
            return true;
        } catch (error) {
            this.logger?.warn({ detalle: error?.message }, 'no pude guardar la sesi?n de WhatsApp');
            return false;
        }
    }

    async cerrar() {
        const pool = this.pool;
        this.pool = null;
        if (pool) await pool.end().catch(() => {});
    }
}
