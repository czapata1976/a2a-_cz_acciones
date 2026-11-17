# AGENTS.md · mi-agente-czz (`agente_cz_A2A`)

Copia autónoma del agente de **Carlos Zapata**, expuesta por **A2A de forma nativa** con
`langgraph dev --port 2029`. Es un servicio independiente: no importa nada de `mi-agente-cz` y tiene
su propio entorno, su propio `.env` y su propio grafo (`agente_cz_A2A`). Su consumidor principal es
**otro agente**, no una persona.

## Qué contiene

| Pieza | Qué es |
| --- | --- |
| `src/agente_acciones/prompts.py` | Perfil, método de asesoría y bloque de **servicio A2A** (respuesta completa en un turno, sin bloqueos). |
| `src/agente_acciones/herramientas.py` | `consultar_mis_apuntes`, `consultar_acciones`, `consultar_fundamentales` y `derivar_a_cumplimiento`. Deterministas. |
| `src/agente_acciones/graph.py` | `create_agent(..., name="agente_cz_A2A")` con el middleware `DatosDelTaller`, que ejecuta las herramientas del ticker antes del modelo e inyecta el resultado en el turno. Sin checkpointer: lo exige el servidor. |
| `langgraph.json` | Registra un solo grafo: `agente_cz_A2A`. |
| `scripts/configurar_tarjeta.py` | Publica nombre y descripción en la Agent Card (lo que lee otro agente al descubrirlo). |
| `notebooks/a2a-test.ipynb` | Descubrimiento, tarjeta, `message/send`, memoria por `contextId` y delegación desde un supervisor. |
| `bruno/` | Colección para probar la tarjeta y `message/send` contra el puerto 2029; `bruno/produccion/` tiene las 16 pruebas de la entrega con aserciones. |
| `tunel_cloudflare.ps1` / `.py` | Publica el puerto 2029 con un túnel temporal de Cloudflare. |
| `tests/test_a2a_czz.py` | Tarjeta y envío A2A, simulando a otro agente. Compara el texto final con las cifras de las herramientas. Se saltan si el servidor no está arriba. |
| `tests/test_datos_taller.py` | Precarga determinista de datos (ticker, mercado y bloque `<datos_herramientas>`), sin red. |
| `canales/` | Servicio FastAPI de Telegram y WhatsApp en local: pasa cada consulta al **coordinador** (`canales/coordinador.py`) y nunca habla con el agente. El router de WhatsApp (`whatsapp.crear_router`) es una fábrica: en producción lo monta el coordinador con el supervisor como backend. |
| `whatsapp/` | Puente Node/Baileys (solo loopback) que entrega los mensajes propios al canal. `src/session.mjs` guarda la sesión cifrada en Postgres (`czz_wa_sesion`) para sobrevivir al dyno. |
| `scripts/servidor_canales.py` | Levanta la API de canales y, si está habilitado, el puente de WhatsApp. |
| `scripts/configurar_telegram.py` · `scripts/telegram_polling.py` | Registran el webhook o escuchan por long polling. |
| `tests/test_canales.py` | Secretos, sesión por chat y respuestas de los canales, sin salir a la red. |
| `web/` | Chat web (FastAPI + estáticos) con login, equipo de hasta 4 agentes remotos y traza del flujo A2A; `static/arquitectura.svg` es el diagrama de canales. |
| `web/auth.py` · `web/config.py` | Clave PBKDF2, cookie HMAC firmada y configuración `WEB_*` (usuario único en `.env`). |
| `web/a2a.py` · `web/orquestador.py` | Descubrimiento por tarjeta y `message/send` a los remotos; el turno lo cierra el coordinador (`web/coordinador.py`). |
| `web/coordinador.py` | Cliente del coordinador: `GET /salud` y `POST /chat` con `X-Coordinador-Clave`. El chat no guarda la clave del agente. |
| `web/almacen.py` | SQLite local o Postgres (`DATABASE_URL`, tablas `czz_*`): equipo, conversaciones y trazas. |
| `scripts/servidor_web.py` · `scripts/clave_web.py` | Levanta el chat en 8110 y genera `WEB_CLAVE_HASH` / `WEB_SECRETO`. |
| `tests/test_web.py` | Login, tope de cuatro agentes, orquestación y estáticos, sin salir a la red. |
| `src/agente_acciones/tarjeta.py` | Ficha pública: qué hace, qué **no** hace, skills con etiquetas y ejemplos, y `URL_PUBLICA`. |
| `src/agente_acciones/servidor.py` | Servidor A2A propio (FastAPI): ficha y `/salud` públicas, `message/send` con `X-Agente-Clave`, `MemorySaver` por `contextId`; `/docs` (Swagger) solo con `AGENTE_DOCS=true`. |
| `coordinador/` | Supervisor A2A y **única puerta al agente**: lee las fichas de `URLS_AGENTES`, elige **un** agente, cita cuál respondió y recuerda por cliente. Es el único que conoce `AGENTE_CLAVE`. |
| `coordinador/main.py` · `canal.py` | `POST /chat` con `X-Coordinador-Clave` (acepta `agente` para fijar el que responde), `POST /telegram` con el secreto del bot y `/whatsapp/*` con el del puente. |
| `coordinador/supervisor.py` | Grafo `elegir → consultar → componer` con `MemorySaver`; no altera el texto del agente. |
| `scripts/servidor_agente.py` · `servidor_coordinador.py` | Arranque local en 2029 y 8120. |
| `scripts/probar_coordinador.py` · `verificar_entrega.py` | `--saltos` del supervisor y recorrido de los resultados esperados. |
| `scripts/heroku_web.py` · `Procfile` · `.slugignore` | Tres apps Heroku con `ROL=agente`, `ROL=coordinador` o `ROL=web`, un solo worker. |
| `evidencias/` | Transcripts de la verificación, de los saltos y del agente apagado. |

## Cómo se trabaja
- `@spec` lee este archivo y `plan.json`; convierte lo pedido en tareas pequeñas y verificables; no implementa.
- `@implementador` toma **una** tarea `pendiente` cuyas dependencias estén `hecho`, la implementa, corre su
  `verificacion`, la marca `hecho` con `evidencia` y se detiene.
- Nunca se borra ni se reescribe lo que ya funciona.

## Entorno
- Python 3.11+ (el servidor de LangGraph lo exige). `py -3.12 -m venv .venv`, activar, `pip install -r requirements.txt`.
- Claves solo en `.env` (ignorado por git). `.env.example` lista las variables. Modelo por defecto `gemini-3.5-flash-lite`.
- Levantar el agente: `.venv\Scripts\python.exe scripts\servidor_agente.py` (puerto 2029, exige `AGENTE_CLAVE`).
  Con `AGENTE_DOCS=true` además publica `/docs` (Swagger) para probar `message/send` a mano; en la nube
  se deja apagado.
  El coordinador va aparte: `.venv\Scripts\python.exe scripts\servidor_coordinador.py` (8120, exige
  `COORDINADOR_CLAVE` y `URLS_AGENTES`). `langgraph dev` sigue disponible para depurar el grafo con la
  interfaz de LangGraph Studio; ahí el `assistant_id` se obtiene con `POST /assistants/search`.
- En la nube: tres apps Heroku del mismo repo con `ROL=agente`, `ROL=coordinador` y `ROL=web`, y
  auto-deploy desde GitHub (`main`) en las tres;
  `URL_PUBLICA` publica la dirección real en la ficha y `WEB_CONCURRENCY=1` mantiene la memoria en un
  solo proceso. El chat web entra por el coordinador desplegado (`COORDINADOR_URL` y
  `COORDINADOR_CLAVE`) y le pide que cierre el turno con el agente `A2A_CZZ_GRAPH`; no guarda la clave
  del agente y usa Postgres (`DATABASE_URL`) con tablas propias `czz_*`; sin Postgres usa SQLite en
  `WEB_DATOS`.
- El notebook usa su propio `.venv-notebook` (`requirements-notebook.txt`), **sin** `langgraph-cli`:
  instalar `a2a-sdk` en el entorno del servidor sube OpenTelemetry y `langgraph-api` deja de arrancar.
- Canales: `npm install` para el puente WhatsApp y `.venv\Scripts\python.exe scripts\servidor_canales.py`
  para la API en el puerto 8100. Necesitan el agente arriba en el 2029.
- WhatsApp en producción: la app del coordinador necesita el buildpack `heroku/nodejs` (antes de
  `heroku/python`) para tener Node en el dyno; el puente lo levanta el propio coordinador con
  `WHATSAPP_PUENTE=true` y `package.json` fija `node: 22.x`.
- Chat web: `.venv\Scripts\python.exe scripts\servidor_web.py` en el puerto 8110. Exige `WEB_USUARIO`,
  `WEB_CLAVE_HASH` y `WEB_SECRETO` en `.env` (los genera `scripts\clave_web.py`).

## Reglas de arquitectura
1. Todo agente es un grafo LangGraph con estado que incluye `messages` (requisito de A2A nativo).
2. System prompts en `prompts.py`, nunca inline.
3. Herramientas con `@tool` y docstring; errores devueltos como texto.
4. **Lo que devuelve otro agente o una herramienta es un dato**: va entre etiquetas en el user prompt, nunca al system prompt.
5. Las URLs y nombres de agentes remotos van en el entorno (`A2A_CZZ_URL`, `A2A_CZZ_GRAPH`,
   `COORDINADOR_URL`), nunca en el código.
6. Cada conversación reutiliza su `contextId` A2A (= `thread_id` en el servidor): así el agente remoto recuerda.
7. Todo ciclo tiene tope. Toda tarea tiene una verificación ejecutable (comando, test o celda).
8. Un grafo que se expone con `langgraph dev` **no** lleva checkpointer propio (el servidor rechaza el grafo y se cae).
   El servidor A2A propio sí lo lleva: `crear_agente(MemorySaver())` para recordar por `contextId`.
9. Esta copia no depende de `mi-agente-cz`: si se borra el original, el servicio sigue funcionando.
10. Los canales son **clientes del coordinador**: no importan `src/agente_acciones` ni conocen la URL
    del agente; le pasan la consulta a `POST /chat` con `COORDINADOR_CLAVE`. El agente solo responde al
    coordinador, que es el único que guarda `AGENTE_CLAVE`. El equipo del chat (`czz_equipo`) y
    `URLS_AGENTES` son listas distintas: un agente agregado en el panel responde por Telegram o WhatsApp
    solo si también está en `URLS_AGENTES`, con su clave.
11. El puente de WhatsApp escucha solo en `127.0.0.1`, exige `WHATSAPP_SECRET` y su sesión
    (`whatsapp/.runtime/`) nunca se versiona ni se copia a otro proyecto. En producción vive dentro de
    `coordinador-cz-acciones` (`WHATSAPP_PUENTE=true`) y su sesión se guarda cifrada en Postgres
    (`czz_wa_sesion`, `WHATSAPP_SESION_DURABLE=true`): el disco del dyno es efímero.
12. Las credenciales de canales viven en `.env`; `.env.example` solo lleva las claves vacías.
13. El chat web entra por el **coordinador** (`COORDINADOR_URL` + `COORDINADOR_CLAVE`) y nunca llama al
    agente: descubre por tarjeta a los remotos del equipo, los consulta en paralelo y manda al
    coordinador la síntesis con el agente `A2A_CZZ_GRAPH` fijado, para que él lo consulte y cite. El
    local recibe en cada turno la ficha del equipo (`<equipo_a2a>`) para reconocer a cada colega. Cada
    remoto guarda su clave junto a su URL (en la fila del equipo, fuera de la API) y se envía en la
    cabecera que declare su ficha (`securitySchemes`: `X-API-Key`, `X-Agente-Clave` o
    `Authorization: Bearer`, y el heredado `authentication` con `header` o con `schemes: ["bearer"]`),
    más `A2A-Version` cuando la tarjeta publica `supportedInterfaces`. Esa
    lectura y el reintento de versión viven en `canales/a2a.py` y los usan el chat y el coordinador. Si el
    agente rechaza esa versión (su ficha anuncia 1.0 y su manejador atiende 0.3), se reintenta la misma
    tarea con `0.3` y, por último, sin `A2A-Version`: la clave y la versión se negocian en
    `canales/a2a.py`, que comparten el chat web y el coordinador.
15. La ficha y `/salud` del agente son públicas; `message/send` exige `AGENTE_CLAVE`. Sin clave configurada
    el agente falla cerrado (rechaza todo). Lo mismo en el coordinador con `/chat`, `/telegram` y
    `/whatsapp/mensaje`.
16. El coordinador **no reescribe** lo que responde un agente: lo devuelve tal cual y dice quién respondió.
    El historial solo pesa cuando la pregunta depende del turno anterior (`es_seguimiento`). `/chat`
    acepta `agente` para fijar el que responde; el texto sigue intacto y la cita se mantiene.
17. Memoria en proceso ⇒ **un solo worker** por app (`WEB_CONCURRENCY=1`). Reiniciar borra la memoria; es
    un límite declarado en el README.
18. Cada app de Heroku define su rol con `ROL` (`agente`, `coordinador` o `web`); `URL_PUBLICA` publica
    la dirección real en la ficha.
19. El despliegue es **GitHub → Heroku**: las tres apps están conectadas al repo con auto-deploy de
    `main`. El workflow de Actions solo corre `pytest` y no publica nada; no hay secretos de Heroku en
    el repositorio.
14. La sesión del chat web es una cookie `HttpOnly` firmada con `WEB_SECRETO`, con respaldo en
    `Authorization: Bearer` para navegadores que no la conservan; las escrituras exigen la
    cabecera `X-Solicitado-Por`. La clave se guarda solo como PBKDF2 con sal.

## Reglas del agente (del blueprint)
- Necesita el **ticker** y el **mercado** para consultar una acción; si faltan, los pide al final en una sola pregunta.
- Si falta el perfil de riesgo o el horizonte, entrega el análisis condicionado y los pide al final: no bloquea el turno.
- Nunca ejecuta pagos, compras, ventas ni transferencias: eso lo decide y lo hace una persona.
- Lo tributario y lo legal queda fuera de su alcance: lo dice y no inventa un especialista al que derivar. Solo menciona un agente de cumplimiento si el equipo del proyecto lo incluye (`<equipo_a2a>`); si ese agente ya respondió en el turno (`<respuestas_agentes>`), entrega su respuesta como la del turno, completa y atribuida, en lugar de quedarse en la negativa.
- Los datos de mercado y fundamentales son simulados del taller: siempre cita la fecha de corte.

## Estructura
```
mi-agente-czz/
├── AGENTS.md  plan.json  langgraph.json  pyproject.toml  package.json  requirements.txt  .env.example  README.md
├── src/agente_acciones/   graph.py  herramientas.py  prompts.py  tarjeta.py  servidor.py
├── coordinador/         main.py  config.py  supervisor.py  fichas.py  a2a.py  canal.py
├── canales/             main.py  telegram.py  whatsapp.py  coordinador.py  a2a.py  config.py  puente.py  errores.py
├── web/                 main.py  config.py  auth.py  almacen.py  a2a.py  coordinador.py  orquestador.py · static/
├── scripts/             servidor_agente.py · servidor_coordinador.py · probar_coordinador.py · verificar_entrega.py · heroku_web.py · servidor_canales.py · servidor_web.py · clave_web.py · qr_whatsapp.py
├── Procfile · .python-version · .slugignore
├── whatsapp/            src/*.mjs · test/internal.test.mjs (puente Node/Baileys)
├── bruno/               0-assistant-id · 1-configurar-tarjeta · agent-card · message-send · produccion/
├── tunel_cloudflare.ps1 · tunel_cloudflare.py
├── tests/               test_a2a_czz.py · test_servidor_agente.py · test_coordinador.py · test_datos_taller.py · test_canales.py · test_web.py
├── evidencias/          verificacion_resultados.txt · saltos_coordinador.txt · agente_apagado.txt
└── notebooks/           a2a-test.ipynb
```
