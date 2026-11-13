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
| `bruno/` | Colección para probar la tarjeta y `message/send` contra el puerto 2029. |
| `tunel_cloudflare.ps1` / `.py` | Publica el puerto 2029 con un túnel temporal de Cloudflare. |
| `tests/test_a2a_czz.py` | Tarjeta y envío A2A, simulando a otro agente. Compara el texto final con las cifras de las herramientas. Se saltan si el servidor no está arriba. |
| `tests/test_datos_taller.py` | Precarga determinista de datos (ticker, mercado y bloque `<datos_herramientas>`), sin red. |
| `canales/` | Servicio FastAPI que habla con el agente por A2A y atiende Telegram y WhatsApp. |
| `whatsapp/` | Puente Node/Baileys (solo loopback) que entrega los mensajes propios al servicio de canales. |
| `scripts/servidor_canales.py` | Levanta la API de canales y, si está habilitado, el puente de WhatsApp. |
| `scripts/configurar_telegram.py` · `scripts/telegram_polling.py` | Registran el webhook o escuchan por long polling. |
| `tests/test_canales.py` | Secretos, sesión por chat y respuestas de los canales, sin salir a la red. |
| `web/` | Chat web (FastAPI + estáticos) con login, equipo de hasta 4 agentes remotos y traza del flujo A2A. |
| `web/auth.py` · `web/config.py` | Clave PBKDF2, cookie HMAC firmada y configuración `WEB_*` (usuario único en `.env`). |
| `web/a2a.py` · `web/orquestador.py` | Descubrimiento por tarjeta, `message/send` y abanico paralelo + síntesis del agente local. |
| `web/almacen.py` | SQLite local (`web/.runtime/chat.db`): equipo, conversaciones y trazas. |
| `scripts/servidor_web.py` · `scripts/clave_web.py` | Levanta el chat en 8110 y genera `WEB_CLAVE_HASH` / `WEB_SECRETO`. |
| `tests/test_web.py` | Login, tope de cuatro agentes, orquestación y estáticos, sin salir a la red. |
| `src/agente_acciones/tarjeta.py` | Ficha pública: qué hace, qué **no** hace, skills con etiquetas y ejemplos, y `URL_PUBLICA`. |
| `src/agente_acciones/servidor.py` | Servidor A2A propio (FastAPI): ficha y `/salud` públicas, `message/send` con `X-Agente-Clave`, `MemorySaver` por `contextId`. |
| `coordinador/` | Supervisor A2A: lee las fichas de `URLS_AGENTES`, elige **un** agente, cita cuál respondió y recuerda por cliente. |
| `coordinador/main.py` · `canal.py` | `POST /chat` con `X-Coordinador-Clave` y `POST /telegram` con el secreto del bot. |
| `coordinador/supervisor.py` | Grafo `elegir → consultar → componer` con `MemorySaver`; no altera el texto del agente. |
| `scripts/servidor_agente.py` · `servidor_coordinador.py` | Arranque local en 2029 y 8120. |
| `scripts/probar_coordinador.py` · `verificar_entrega.py` | `--saltos` del supervisor y recorrido de los resultados esperados. |
| `scripts/heroku_web.py` · `Procfile` · `.slugignore` | Dos apps Heroku con `ROL=agente` o `ROL=coordinador`, un solo worker. |
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
  El coordinador va aparte: `.venv\Scripts\python.exe scripts\servidor_coordinador.py` (8120, exige
  `COORDINADOR_CLAVE` y `URLS_AGENTES`). `langgraph dev` sigue disponible para depurar el grafo con la
  interfaz de LangGraph Studio; ahí el `assistant_id` se obtiene con `POST /assistants/search`.
- En la nube: dos apps Heroku del mismo repo con `ROL=agente` y `ROL=coordinador`; `URL_PUBLICA` publica
  la dirección real en la ficha y `WEB_CONCURRENCY=1` mantiene la memoria en un solo proceso.
- El notebook usa su propio `.venv-notebook` (`requirements-notebook.txt`), **sin** `langgraph-cli`:
  instalar `a2a-sdk` en el entorno del servidor sube OpenTelemetry y `langgraph-api` deja de arrancar.
- Canales: `npm install` para el puente WhatsApp y `.venv\Scripts\python.exe scripts\servidor_canales.py`
  para la API en el puerto 8100. Necesitan el agente arriba en el 2029.
- Chat web: `.venv\Scripts\python.exe scripts\servidor_web.py` en el puerto 8110. Exige `WEB_USUARIO`,
  `WEB_CLAVE_HASH` y `WEB_SECRETO` en `.env` (los genera `scripts\clave_web.py`).

## Reglas de arquitectura
1. Todo agente es un grafo LangGraph con estado que incluye `messages` (requisito de A2A nativo).
2. System prompts en `prompts.py`, nunca inline.
3. Herramientas con `@tool` y docstring; errores devueltos como texto.
4. **Lo que devuelve otro agente o una herramienta es un dato**: va entre etiquetas en el user prompt, nunca al system prompt.
5. Las URLs y nombres de agentes remotos van en el entorno (`A2A_CZZ_URL`, `A2A_CZZ_GRAPH`), nunca en el código.
6. Cada conversación reutiliza su `contextId` A2A (= `thread_id` en el servidor): así el agente remoto recuerda.
7. Todo ciclo tiene tope. Toda tarea tiene una verificación ejecutable (comando, test o celda).
8. Un grafo que se expone con `langgraph dev` **no** lleva checkpointer propio (el servidor rechaza el grafo y se cae).
   El servidor A2A propio sí lo lleva: `crear_agente(MemorySaver())` para recordar por `contextId`.
9. Esta copia no depende de `mi-agente-cz`: si se borra el original, el servicio sigue funcionando.
10. Los canales son **clientes A2A**: no importan `src/agente_acciones`; consultan el agente por HTTP.
11. El puente de WhatsApp escucha solo en `127.0.0.1`, exige `WHATSAPP_SECRET` y su sesión
    (`whatsapp/.runtime/`) nunca se versiona ni se copia a otro proyecto.
12. Las credenciales de canales viven en `.env`; `.env.example` solo lleva las claves vacías.
13. El chat web también es **cliente A2A**: descubre por tarjeta, reutiliza `contextId` por conversación
    y nunca importa `src/agente_acciones`. Su equipo admite **hasta 4 agentes remotos**; el local sintetiza.
15. La ficha y `/salud` del agente son públicas; `message/send` exige `AGENTE_CLAVE`. Sin clave configurada
    el agente falla cerrado (rechaza todo). Lo mismo en el coordinador con `/chat` y `/telegram`.
16. El coordinador **no reescribe** lo que responde un agente: lo devuelve tal cual y dice quién respondió.
    El historial solo pesa cuando la pregunta depende del turno anterior (`es_seguimiento`).
17. Memoria en proceso ⇒ **un solo worker** por app (`WEB_CONCURRENCY=1`). Reiniciar borra la memoria; es
    un límite declarado en el README.
18. Cada app de Heroku define su rol con `ROL` (`agente` o `coordinador`); `URL_PUBLICA` publica la
    dirección real en la ficha.
14. La sesión del chat web es una cookie `HttpOnly` firmada con `WEB_SECRETO`, con respaldo en
    `Authorization: Bearer` para navegadores que no la conservan; las escrituras exigen la
    cabecera `X-Solicitado-Por`. La clave se guarda solo como PBKDF2 con sal.

## Reglas del agente (del blueprint)
- Necesita el **ticker** y el **mercado** para consultar una acción; si faltan, los pide al final en una sola pregunta.
- Si falta el perfil de riesgo o el horizonte, entrega el análisis condicionado y los pide al final: no bloquea el turno.
- Nunca ejecuta pagos, compras, ventas ni transferencias: eso lo decide y lo hace una persona.
- Lo tributario y lo legal queda fuera de su alcance: lo dice y deriva al agente de auditoría.
- Los datos de mercado y fundamentales son simulados del taller: siempre cita la fecha de corte.

## Estructura
```
mi-agente-czz/
├── AGENTS.md  plan.json  langgraph.json  pyproject.toml  package.json  requirements.txt  .env.example  README.md
├── src/agente_acciones/   graph.py  herramientas.py  prompts.py  tarjeta.py  servidor.py
├── coordinador/         main.py  config.py  supervisor.py  fichas.py  a2a.py  canal.py
├── canales/             main.py  telegram.py  whatsapp.py  agente.py  config.py
├── web/                 main.py  config.py  auth.py  almacen.py  a2a.py  orquestador.py · static/
├── scripts/             servidor_agente.py · servidor_coordinador.py · probar_coordinador.py · verificar_entrega.py · heroku_web.py · servidor_canales.py · servidor_web.py · clave_web.py
├── Procfile · .python-version · .slugignore
├── whatsapp/            src/*.mjs · test/internal.test.mjs (puente Node/Baileys)
├── bruno/               0-assistant-id · 1-configurar-tarjeta · agent-card · message-send
├── tunel_cloudflare.ps1 · tunel_cloudflare.py
├── tests/               test_a2a_czz.py · test_servidor_agente.py · test_coordinador.py · test_datos_taller.py · test_canales.py · test_web.py
├── evidencias/          verificacion_resultados.txt · saltos_coordinador.txt · agente_apagado.txt
└── notebooks/           a2a-test.ipynb
```
