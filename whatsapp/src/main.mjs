import { Gateway } from './gateway.mjs';
import { eligibleText } from './guard.mjs';
import { createInternalServer } from './server.mjs';
import { SesionDurable } from './session.mjs';
import { defaultDirectory, Store } from './store.mjs';

const secret = process.env.WHATSAPP_SECRET ?? '';
const port = Number(process.env.WHATSAPP_INTERNAL_PORT ?? 18082);

// La sesi?n durable se activa de forma expl?cita: en local el `.env` tambi?n tiene `DATABASE_URL`
// (la base del taller) y no conviene que un puente de escritorio se apropie de la sesi?n de Heroku.
const durable = process.env.WHATSAPP_SESION_DURABLE === 'true';
const sesion = new SesionDurable({
  connectionString: durable ? process.env.DATABASE_URL ?? '' : '',
  secret,
  directory: defaultDirectory,
  logger: {
    info: (datos, mensaje) => process.stdout.write(`sesion ${mensaje} ${JSON.stringify(datos)}\n`),
    warn: (datos, mensaje) => process.stdout.write(`sesion ${mensaje} ${JSON.stringify(datos)}\n`),
  },
});

// Antes de abrir la conexi?n: el puente lee las credenciales del disco, as? que hay que restaurarlas.
await sesion.abrir();

const createGateway = () =>
  new Gateway({
    parse: (item, identities) => {
      const text = eligibleText(item, identities);
      return text ? { kind: 'text', text } : null;
    },
    openStore: () => Store.open({ directory: defaultDirectory, alGuardar: () => sesion.guardar() }),
  });

const { server, close } = createInternalServer({ createGateway, secret });
server.listen(port, '127.0.0.1', () => {
  // Sin contenido, credenciales ni c?digos en registros.
  process.stdout.write(`whatsapp bridge listening on 127.0.0.1:${port}\n`);
});

for (const signal of ['SIGTERM', 'SIGINT']) {
  process.once(signal, () => {
    server.close();
    void close()
      .finally(() => sesion.cerrar())
      .finally(() => process.exit(0));
    setTimeout(() => process.exit(1), 20000).unref();
  });
}
