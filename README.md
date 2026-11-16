# `agente_cz_A2A` · agente de acciones + coordinador A2A del equipo

**Entrega del taller A2A en producción.** El sistema está desplegado en Heroku, con tres apps y una
dirección pública HTTPS cada una, sin depender de ningún computador local:

| Pieza                    | Dirección pública                                                                                                     | Qué es                                                                               |
| ------------------------ | ----------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------- |
| Agente `agente_cz_A2A` | [https://agente-cz-acciones-50f663cbb84c.herokuapp.com](https://agente-cz-acciones-50f663cbb84c.herokuapp.com)           | Servicio A2A propio: ficha, `message/send` con clave y `/salud`                   |
| Coordinador              | [https://coordinador-cz-acciones-aabcdf3f447b.herokuapp.com](https://coordinador-cz-acciones-aabcdf3f447b.herokuapp.com) | Supervisor que elige un agente, lo cita, recuerda la conversación y atiende el canal |
| Chat web                 | [https://chat-web-cz-acciones-08a900afb62c.herokuapp.com](https://chat-web-cz-acciones-08a900afb62c.herokuapp.com)       | Consola con login, equipo de hasta 4 agentes remotos y traza del flujo A2A            |

| Integrante          | Agente            | Skill                                                         | Ficha pública                                                                                                                                                                        | Dueño del despliegue          |
| ------------------- | ----------------- | ------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------ |
| Carlos Zapata       | `agente_cz_A2A` | analizar acciones con datos de mercado y fundamentales        | [https://agente-cz-acciones-50f663cbb84c.herokuapp.com/.well-known/agent-card.json](https://agente-cz-acciones-50f663cbb84c.herokuapp.com/.well-known/agent-card.json)                 | Carlos Zapata                  |
| Bryhan (otro grupo) | `agente_bryhan` | perfil, procesos, diseño de datos/IA y comparación técnica | [https://agente-bryhan-624098704764.southamerica-west1.run.app/.well-known/agent-card.json](https://agente-bryhan-624098704764.southamerica-west1.run.app/.well-known/agent-card.json) | Bryhan (extra: agente externo) |

### Prueba directa de cada agente

```powershell
# agente de acciones (con su clave: X-Agente-Clave)
$env:AGENTE_CLAVE = "<clave entregada por vía privada>"
curl.exe -s https://agente-cz-acciones-50f663cbb84c.herokuapp.com/salud
curl.exe -s https://agente-cz-acciones-50f663cbb84c.herokuapp.com/.well-known/agent-card.json
curl.exe -s -X POST https://agente-cz-acciones-50f663cbb84c.herokuapp.com/a2a ^
  -H "Content-Type: application/json" -H "X-Agente-Clave: %AGENTE_CLAVE%" ^
  -d "{\"jsonrpc\":\"2.0\",\"id\":\"1\",\"method\":\"message/send\",\"params\":{\"message\":{\"role\":\"user\",\"messageId\":\"m1\",\"contextId\":\"<uuid>\",\"parts\":[{\"kind\":\"text\",\"text\":\"Analiza NVDA en US\"}]}}}"
```

```powershell
# coordinador (con su clave: X-Coordinador-Clave)
$env:COORDINADOR_CLAVE = "<clave entregada por vía privada>"
curl.exe -s https://coordinador-cz-acciones-aabcdf3f447b.herokuapp.com/salud
curl.exe -s -X POST https://coordinador-cz-acciones-aabcdf3f447b.herokuapp.com/chat ^
  -H "Content-Type: application/json" -H "X-Coordinador-Clave: %COORDINADOR_CLAVE%" ^
  -d "{\"mensaje\":\"Analiza NVDA en US\",\"cliente\":\"profesor\"}"

# recorrido completo con los saltos del supervisor
.venv\Scripts\python.exe scripts\probar_coordinador.py `
  --url https://coordinador-cz-acciones-aabcdf3f447b.herokuapp.com --saltos
```

> Las claves de prueba se entregan al equipo docente por vía privada; no están en el repositorio.
> `.env.example` solo trae valores ficticios.

## Cómo se armó

El agente conserva el perfil de asesoría en acciones de
[`mi-agente-cz`](<../grupo-1-taller-a2a - entrega/mi-agente-cz/README.md>) como **copia independiente**:
su propio grafo, su propio puerto, su propio `.env` y su propio entorno virtual.

> **Proyecto independiente.** Vive en `Taller UAI IA\mi-agente-czz`, fuera del repositorio
> `grupo-1-taller-a2a - entrega`. No comparte código ni entorno con el proyecto del grupo; solo
> intercambia mensajes A2A por HTTP.

| Qué definir          | Esta copia                                                                                                                                                         |
| --------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Grafo / nombre A2A    | `agente_cz_A2A`                                                                                                                                                  |
| En la nube            | [https://agente-cz-acciones-50f663cbb84c.herokuapp.com](https://agente-cz-acciones-50f663cbb84c.herokuapp.com) (Heroku, HTTPS)                                      |
| En local              | `http://127.0.0.1:2029` (`scripts\servidor_agente.py`)                                                                                                         |
| Tipo de servicio      | A2A propio: FastAPI + JSON-RPC `message/send`, ficha y `/salud`                                                                                                |
| Coordinador           | [https://coordinador-cz-acciones-aabcdf3f447b.herokuapp.com](https://coordinador-cz-acciones-aabcdf3f447b.herokuapp.com) (`POST /chat`, canal `POST /telegram`) |
| Canales               | Telegram **y WhatsApp** conectados al coordinador; el chat web queda como extra                                                                                     |
| Autonomía            | Consulta mercado, fundamentales y apuntes sin aprobación; entrega el análisis completo en un turno                                                               |
| Nunca sin una persona | Pagos, compras, ventas o transferencias                                                                                                                            |
| Fuera de alcance      | Lo tributario, legal y normativo: lo declara fuera de alcance y **no supone que exista** un agente de cumplimiento; solo lo menciona si está en el equipo   |

## Contrato A2A

Todo lo que otro agente necesita está en la ficha; no hay acoplamiento al código. El coordinador lee
`.well-known/agent-card.json` de cada URL de `URLS_AGENTES`.

| Paso | Llamada                                                 | Para qué                                                  |
| ---- | ------------------------------------------------------- | ---------------------------------------------------------- |
| 1    | `GET /.well-known/agent-card.json`                    | Leer nombre, skills, límites y el endpoint A2A (público) |
| 2    | `POST /a2a` con `message/send` y `X-Agente-Clave` | Enviar la tarea y recibir la respuesta                     |
| 3    | `GET /salud`                                          | Comprobar que el agente está arriba (público)            |

Reglas del contrato:

- La ficha y `/salud` son **públicas**; `message/send` exige la **clave del agente**
  (`X-Agente-Clave` o `Authorization: Bearer`). Sin clave configurada, el agente rechaza todo (falla
  cerrado).
- El `contextId` del mensaje es el `thread_id` del `MemorySaver`: reutilízalo para que el agente
  recuerde los turnos anteriores de la misma conversación.
- La ficha publica `URL_PUBLICA` (la dirección de Heroku), no la de la máquina donde corre.
- El agente responde en un solo turno con el análisis y la fecha de corte. Si falta el ticker o el
  mercado, devuelve una única pregunta concreta; si solo falta el perfil de riesgo, entrega el
  análisis condicionado en vez de bloquear.
- Un mensaje sin texto (foto, sticker, audio) se responde con que no puede leerlo.

### Datos garantizados

El grafo no deja las cifras al criterio del modelo: el middleware `DatosDelTaller` lee el ticker y el
mercado del mensaje, ejecuta `consultar_acciones` y `consultar_fundamentales` de forma determinista y
entrega el resultado en el mismo turno, entre las etiquetas `<datos_herramientas>`. Así el cliente
siempre recibe el precio y los fundamentales simulados del taller con su fecha de corte, aunque el modelo
hubiera preferido responder de memoria. Ese bloque viaja solo al modelo: el `history` que ve el cliente
A2A sigue siendo `user` / `agent`.

## Cómo ejecutar en local

Tres procesos en tres terminales. El primero es el agente; el segundo, el coordinador; el tercero es
opcional (chat web, extra).

```powershell
cd mi-agente-czz
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
copy .env.example .env            # pega GOOGLE_API_KEY y genera las claves (abajo)

# claves de prueba (nunca se versionan)
.venv\Scripts\python.exe scripts\clave_web.py --usuario carlos   # WEB_* del chat web (extra)
python -c "import secrets; print(secrets.token_urlsafe(24))"     # AGENTE_CLAVE y COORDINADOR_CLAVE
```

```powershell
# terminal 1 · agente A2A propio en 2029
.venv\Scripts\python.exe scripts\servidor_agente.py

# terminal 2 · coordinador en 8120 (lee URLS_AGENTES del .env)
.venv\Scripts\python.exe scripts\servidor_coordinador.py

# terminal 3 · chat web (extra) en 8110
.venv\Scripts\python.exe scripts\servidor_web.py
```

`.env` local de ejemplo:

```dotenv
AGENTE_CLAVE=<clave-del-agente>
A2A_CZZ_CLAVE=<la misma, para el chat web>
URL_PUBLICA=
COORDINADOR_CLAVE=<clave-del-coordinador>
URLS_AGENTES=[{"url": "http://127.0.0.1:2029", "clave": "<clave-del-agente>"}]
```

Comprobaciones:

```powershell
Invoke-RestMethod "http://127.0.0.1:2029/salud"
Invoke-RestMethod "http://127.0.0.1:2029/.well-known/agent-card.json"
Invoke-RestMethod "http://127.0.0.1:8120/salud"
.venv\Scripts\python.exe scripts\probar_coordinador.py --saltos
.venv\Scripts\python.exe scripts\verificar_entrega.py --coordinador http://127.0.0.1:8120 --agente http://127.0.0.1:2029
```

Pruebas automáticas (85 en total; las de integración se saltan si el servidor no está arriba):

```powershell
.venv\Scripts\python.exe -m pytest tests -q
```

## Desplegar en Heroku

Un mismo repositorio sirve las tres apps; cada una elige su rol con la config var `ROL`.

### Desde GitHub (automático, vía actual)

Las tres apps están conectadas al repositorio [https://github.com/czapata1976/a2a-_cz_acciones](https://github.com/czapata1976/a2a-_cz_acciones) desde
el dashboard de Heroku (*Deploy → Deployment method: GitHub*), con **auto-deploy de la rama `main`**:

| App                         | Rama     | Última vía     |
| --------------------------- | -------- | ---------------- |
| `agente-cz-acciones`      | `main` | GitHub → Heroku |
| `coordinador-cz-acciones` | `main` | GitHub → Heroku |
| `chat-web-cz-acciones`    | `main` | GitHub → Heroku |

Un push a `main` construye las tres. No hace falta ningún secreto en GitHub: el token de Heroku ya no
se usa porque no hay `git push` a Heroku desde Actions. El workflow
[`.github/workflows/pruebas.yml`](.github/workflows/pruebas.yml) solo corre `pytest` (89 pruebas) y
**no despliega**: en GitHub quedan 81 en verde y 8 se saltan solas porque necesitan el agente en vivo o
el Postgres. Si quieres desplegar sin cambiar código, usa *Manual deploy → Deploy Branch* en el
dashboard de la app.

> Para conectar una app nueva: *Deploy → GitHub → Connect to GitHub* → repo → rama `main` →
> *Enable Automatic Deploys*. La autorización de la GitHub App de Heroku se hace una sola vez y sirve
> para las tres.

### Desde el computador (manual, solo para recrear todo de cero)

```powershell
# una sola vez
heroku create agente-cz-acciones
heroku create coordinador-cz-acciones
heroku create chat-web-cz-acciones
git remote add agente      https://git.heroku.com/agente-cz-acciones.git
git remote add coordinador https://git.heroku.com/coordinador-cz-acciones.git
git remote add web         https://git.heroku.com/chat-web-cz-acciones.git

# agente
heroku config:set --app agente-cz-acciones ROL=agente GOOGLE_API_KEY=... MODELO=gemini-3.5-flash-lite ^
  AGENTE_CLAVE=... URL_PUBLICA=https://agente-cz-acciones-50f663cbb84c.herokuapp.com WEB_CONCURRENCY=1
git push agente HEAD:main

# coordinador (usa la URL y la clave del agente; también atiende el canal de WhatsApp)
heroku buildpacks:add --index 1 heroku/nodejs --app coordinador-cz-acciones
heroku config:set --app coordinador-cz-acciones ROL=coordinador COORDINADOR_CLAVE=... ^
  "URLS_AGENTES=[{""url"":""https://agente-cz-acciones-50f663cbb84c.herokuapp.com"",""clave"":""...""}]" ^
  TELEGRAM_TOKEN=... TELEGRAM_SECRET=... SALTOS=true WEB_CONCURRENCY=1 ^
  WHATSAPP_HABILITADO=true WHATSAPP_PUENTE=true WHATSAPP_SESION_DURABLE=true ^
  WHATSAPP_SECRET=<16+ caracteres> CANALES_TOKEN=<token del operador> ^
  DATABASE_URL=<el mismo Postgres del taller>
git push coordinador HEAD:main

# chat web (login propio; habla con el agente desplegado por A2A)
heroku config:set --app chat-web-cz-acciones ROL=web WEB_USUARIO=carlos ^
  WEB_CLAVE_HASH=<salida de scripts\clave_web.py> WEB_SECRETO=<salida de scripts\clave_web.py> ^
  A2A_CZZ_URL=https://agente-cz-acciones-50f663cbb84c.herokuapp.com A2A_CZZ_CLAVE=... ^
  DATABASE_URL=<postgres del taller> WEB_CONCURRENCY=1
git push web HEAD:main

# el Procfile declara `web: python scripts/heroku_web.py`
```

`DATABASE_URL` es la base del chat: con Postgres las conversaciones sobreviven a los reinicios del
dyno; sin ella (o con `WEB_DATOS`) el chat usa SQLite en `/tmp` y se pierde en cada reinicio. Las
tablas van con prefijo `czz_` porque el Postgres del taller es compartido.

`WEB_CONCURRENCY=1` es obligatorio: la memoria por conversación vive en el proceso (`MemorySaver`). Con
dos workers, dos mensajes del mismo cliente pueden caer en procesos distintos y la conversación
olvidaría sus turnos.

Ficha para los demás agentes: la tarjeta se genera desde `URL_PUBLICA`, así que no hay que configurarla
a mano en cada arranque.

```powershell
.venv\Scripts\python.exe scripts\configurar_tarjeta.py
# o contra el túnel:  ... --url https://<algo>.trycloudflare.com
```

## Cómo lo invoca otro agente

### Con `httpx` (sin dependencias del SDK)

```python
import os
import uuid
import httpx

BASE = "https://agente-cz-acciones-50f663cbb84c.herokuapp.com"   # o http://127.0.0.1:2029 en local
CLAVE = os.environ["AGENTE_CLAVE"]                                # clave del agente, por vía privada

cuerpo = {
    "jsonrpc": "2.0",
    "id": uuid.uuid4().hex,
    "method": "message/send",
    "params": {"message": {
        "role": "user",
        "messageId": uuid.uuid4().hex,
        "contextId": str(uuid.uuid4()),   # reutilízalo para conservar la memoria
        "parts": [{"kind": "text", "text": "Analiza NVDA en US para un perfil moderado a 12 meses."}],
    }},
}
respuesta = httpx.post(
    f"{BASE}/a2a", json=cuerpo,
    headers={"Accept": "application/json", "X-Agente-Clave": CLAVE}, timeout=180,
).json()
resultado = respuesta["result"]
# El texto viene en `artifacts`; si no hay, en `status.message` o en el último turno del historial.
partes = [p["text"] for a in resultado.get("artifacts") or [] for p in a.get("parts", []) if p.get("kind") == "text"]
if not partes:
    estado = (resultado.get("status") or {}).get("message") or {}
    partes = [p["text"] for p in estado.get("parts", []) if p.get("kind") == "text"]
texto = "\n".join(partes)
```

> Sin `X-Agente-Clave` el endpoint responde **401**. Hay clientes que además exigen
> `Accept: application/json`; enviarlo siempre no estorba.

### Con la colección Bruno

La carpeta `bruno/produccion/` tiene las 16 pruebas de la entrega con sus aserciones (ficha, salud,
`message/send`, 401 sin clave, Telegram y las preguntas del coordinador). Los seis `.bru` de la raíz
son las pruebas sueltas del servidor `langgraph dev` y usan el entorno `local`.

```powershell
# Las claves nunca van en la colección: se leen del entorno del sistema.
$env:COORDINADOR_CLAVE = "<clave-del-coordinador>"
$env:AGENTE_CLAVE      = "<clave-del-agente>"
$env:TELEGRAM_SECRET   = "<secreto-del-canal>"

Push-Location .\bruno
npx --yes @usebruno/cli run produccion --env nube              # contra Heroku
npx --yes @usebruno/cli run produccion --env local-produccion  # contra 8120 y 2029
Pop-Location
```

Resultado esperado: `16 requests`, `44 assertions`, `PASS`. Ojo: el CLI **no entra en subcarpetas**
cuando se lanza con `run .`; hay que apuntar a `produccion`. En la interfaz de Bruno basta abrir la
carpeta `bruno/` y elegir el entorno `nube`.

### Registrar esta copia en el orquestador del grupo

El coordinador de este repositorio la incluye con `URLS_AGENTES`. Si el orquestador del grupo usa otra
lista, agrega esta dirección con su clave:

```dotenv
URLS_AGENTES=[{"url": "https://agente-cz-acciones-50f663cbb84c.herokuapp.com", "clave": "<clave-del-agente>"}]
```

### Quién elige al agente

El supervisor lee las fichas y puntúa la pregunta contra el nombre, la descripción, las skills, sus
etiquetas y sus ejemplos. **Nombrar a un agente basta para elegirlo**: «¿qué hace Bryhan?» no comparte
ninguna otra palabra con su ficha, así que el nombre pesa más que todo lo demás y se tolera una letra de
diferencia («Bryan»). Solo usa el historial cuando la pregunta depende del turno anterior («¿y a 6
meses?»), para que una consulta de otro tema no herede el asunto previo. Si nadie alcanza el mínimo,
responde que no tiene un agente para eso. Cada respuesta empieza con `Respondió: <agente>` y devuelve el
texto del agente sin reescribirlo.

### Extra: chat web con equipo de agentes

El chat (login propio) permite sumar hasta 4 agentes públicos, consultarlos en paralelo y ver la
traza A2A de cada turno.

| Dónde     | Dirección                                                                                                                                |
| ---------- | ----------------------------------------------------------------------------------------------------------------------------------------- |
| En la nube | [https://chat-web-cz-acciones-08a900afb62c.herokuapp.com](https://chat-web-cz-acciones-08a900afb62c.herokuapp.com) (`ROL=web` en Heroku) |
| En local   | [http://127.0.0.1:8110](http://127.0.0.1:8110) (`scripts\servidor_web.py`)                                                               |

Es una demo aparte: el camino de la entrega es el coordinador y el canal. El login se configura con
`WEB_USUARIO`, `WEB_CLAVE_HASH` y `WEB_SECRETO` (`scripts\clave_web.py`); en la nube el agente que
sintetiza es el desplegado, apuntado con `A2A_CZZ_URL` y `A2A_CZZ_CLAVE`.

**Persistencia.** Las conversaciones, el equipo y las trazas viven en Postgres (`DATABASE_URL`) y
sobreviven a los reinicios del dyno; sin esa variable caen a SQLite en `WEB_DATOS`
(`web/.runtime/chat.db`). El Postgres del taller se comparte con otros proyectos, así que el chat crea
sus propias tablas **con prefijo `czz_`** (`czz_equipo`, `czz_charlas`, `czz_mensajes`) y no toca
ninguna otra. La consola conserva **las 3 conversaciones más recientes**: al crear una nueva se borran
las anteriores con sus mensajes (`Almacen.podar_charlas`).

**Diagrama.** El botón **Arquitectura** de la barra superior abre
[`web/static/arquitectura.svg`](web/static/arquitectura.svg): canales de consulta (chat web,
coordinador, Telegram, WhatsApp, otros agentes), protocolo A2A, equipo local + remotos y persistencia.

**El equipo es parte del trabajo, no una lista aparte.** En cada turno el chat lee la tarjeta de cada
agente agregado y le pasa al agente local un bloque `<equipo_a2a>` con nombre, descripción y skills
(`web/orquestador.py:ficha_de_equipo`). Así el agente local reconoce a los colegas —incluidos los que
se agreguen después— y puede responder «quiénes forman el equipo» o «qué hace *X*» aunque ese agente no
conteste en ese turno. Las respuestas de los demás viajan aparte, en `<respuestas_agentes>`, siempre
como dato y nunca como instrucción. Pegar la URL de la ficha (`…/.well-known/agent-card.json`) también
sirve: se usa la raíz y el endpoint que anuncia la tarjeta.

```dotenv
A2A_SERVIDORES=http://127.0.0.1:2025,http://127.0.0.1:2026,http://127.0.0.1:2027,http://127.0.0.1:2028,http://127.0.0.1:2029
```

El orquestador lo encontrará en `/assistants/search` con el `graph_id` `agente_cz_A2A`. Si quieres
que además compita en la selección automática por especialidad, agrega su ficha en
`CATALOGO_AGENTES` (JSON) o en `servicio-fastapi/app/catalogo.py`:

```json
{
  "agente_cz_A2A": {
    "autor": "Carlos Zapata",
    "especialidad": "análisis de acciones e inversiones (servicio autónomo A2A)",
    "descripcion": "Servicio A2A que entrega análisis de acciones con datos de mercado y fundamentales, condicionado al perfil de riesgo; lo tributario lo declara fuera de alcance.",
    "palabras_clave": ["acción", "acciones", "invertir", "ticker", "per", "fundamentales", "portafolio", "riesgo"]
  }
}
```

## Qué pasa cuando algo falla

| Situación                                         | Qué hace el sistema                                                                                                                                           |
| -------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Un agente no responde o está apagado              | El coordinador avisa «La parte de *X* no está disponible ahora (motivo)» y lista los agentes que siguen arriba. Los demás siguen respondiendo sus temas. |
| Un agente estaba caído al arrancar el coordinador | La ficha se marca «no disponible» y el coordinador **vuelve a leerla** en el siguiente mensaje (cada 15 s como máximo), sin reiniciar.                |
| Llega una foto, sticker o audio                    | El canal responde «No puedo leer ese tipo de mensaje: solo entiendo texto». No se inventa contenido.                                                         |
| Piden «ignora tus instrucciones»                 | El coordinador mantiene su rol, lo dice y sigue ofreciendo los agentes del equipo.                                                                             |
| Nadie del equipo sabe                              | «No tengo un agente para eso» y la lista de lo que el equipo cubre.                                                                                          |
| Falta la clave                                     | `/chat`, `/telegram` y `message/send` responden **401**. La ficha y `/salud` siguen siendo públicas.                                            |
| El agente falla a mitad de una consulta            | Devuelve una tarea en estado `failed` con el motivo; el coordinador lo informa como parte no disponible.                                                     |
| Se pierde la sesión de WhatsApp                    | El puente vuelve a `disabled` y hay que revincular con el QR. Con `WHATSAPP_SESION_DURABLE=true` sobrevive a los reinicios porque vive cifrada en `czz_wa_sesion`. |

## Límites conocidos

- **La memoria se pierde al reiniciar** el proceso: `MemorySaver` vive en memoria, un hilo por cliente.
  Un `heroku restart`, un despliegue nuevo o un reinicio del dyno la borran. (Extra no implementado:
  checkpointer en Postgres.)
- **Un solo worker por app.** Con dos procesos, la memoria se repartiría y la conversación olvidaría sus
  turnos; por eso `WEB_CONCURRENCY=1`.
- Los datos de mercado y fundamentales son **simulados del taller**: siempre se cita la fecha de corte.
- La memoria del agente y la del coordinador son independientes: el coordinador guarda la conversación
  y le pasa al agente el `contextId` del hilo.
- El canal de Telegram requiere que el webhook del bot apunte a `https://<coordinador>/telegram` con el
  `TELEGRAM_SECRET`.
- El chat web es un extra de demostración; el camino evaluado es coordinador + Telegram + WhatsApp.
- El túnel de Cloudflare sirve para pruebas locales; **no** forma parte de la entrega (el PDF no lo
  acepta como producción).

## Evidencias

En `evidencias/`:

| Archivo                         | Qué muestra                                                                                                    |
| ------------------------------- | --------------------------------------------------------------------------------------------------------------- |
| `verificacion_resultados.txt` | Recorrido automático de los resultados 1-8, 10 y 11 contra las URLs públicas, con «debía / pasó / estado» |
| `saltos_coordinador.txt`      | Salida de `probar_coordinador.py --saltos`: elección de agente, consulta y cita en cada turno                |
| `agente_apagado.txt`          | Resultado 9: se apaga el agente de acciones, el coordinador avisa y el otro agente sigue respondiendo           |

Regenerar:

```powershell
.venv\Scripts\python.exe scripts\verificar_entrega.py `
  --coordinador https://coordinador-cz-acciones-aabcdf3f447b.herokuapp.com `
  --agente https://agente-cz-acciones-50f663cbb84c.herokuapp.com --guardar
.venv\Scripts\python.exe scripts\probar_coordinador.py `
  --url https://coordinador-cz-acciones-aabcdf3f447b.herokuapp.com --saltos
```

## Notebook

`notebooks/a2a-test.ipynb` recorre el contrato completo: descubrimiento, tarjeta, envío directo,
memoria por `contextId` y una función reutilizable para que un agente supervisor delegue una consulta.
Crea su kernel sin tocar el entorno del servidor:

```powershell
py -3.12 -m venv .venv-notebook
.venv-notebook\Scripts\python.exe -m pip install -r requirements-notebook.txt
.venv-notebook\Scripts\python.exe -m ipykernel install --user --name agente-cz-a2a --display-name "Python (agente_cz_A2A)"
```

> **Por qué un entorno aparte.** `a2a-sdk` sube `google-api-core`, que exige OpenTelemetry ≥ 1.44,
> mientras que `langgraph-api` fija ≤ 0.63b1: instalarlo en `.venv` rompe el servidor. El notebook de
> esta copia usa `httpx` para hablar A2A, así que tampoco necesita `a2a-sdk`; si lo usas en otro
> cliente con `langgraph dev`, fija `protocol_version = "0.3.0"` en la tarjeta (el servidor anuncia
> 1.0 pero responde el JSON de A2A 0.3).

## Exponerlo con un túnel de Cloudflare (solo pruebas locales)

> **No forma parte de la entrega.** El taller pide direcciones públicas reales en la nube; el túnel
> sirve para probar desde otra red antes de desplegar. El sistema de la entrega corre en Heroku.

Cuando el agente que lo invoca está en otra red, el `127.0.0.1` no sirve. Con el servidor arriba:

```powershell
winget install Cloudflare.cloudflared     # una sola vez
.\tunel_cloudflare.ps1                    # o: python tunel_cloudflare.py
```

El script publica el puerto 2029, verifica la tarjeta por la URL pública y guarda la URL en
`tunel.url`. Al terminar: `.\tunel_cloudflare.ps1 -Detener`.

## Canales: Telegram y WhatsApp

Los canales son un **cliente A2A más**: no importan el grafo, hablan con el agente por HTTP. Así el
agente puede reiniciarse sin perder el hilo de los canales y el mismo canal sirve para cualquier
agente A2A del grupo.

| Proceso         | Puerto | Para qué                                                    |
| --------------- | ------ | ------------------------------------------------------------ |
| Agente          | 2029   | `langgraph dev` (A2A)                                      |
| Canales         | 8100   | API de Telegram y WhatsApp (`scripts/servidor_canales.py`) |
| Puente WhatsApp | 18082  | Node + Baileys, solo loopback                                |

### Preparación

```powershell
.venv\Scripts\python.exe -m pip install -r requirements.txt
npm install                       # dependencias del puente WhatsApp (Node 22+)
```

El `.env` trae los bloques de Telegram y WhatsApp. Para WhatsApp, `WHATSAPP_SECRET` debe tener 16 o
más caracteres y `WHATSAPP_HABILITADO=true`.

### Arranque (dos terminales)

```powershell
# terminal 1 · agente A2A
.venv\Scripts\langgraph.exe dev --port 2029

# terminal 2 · canales (levanta también el puente de WhatsApp)
.venv\Scripts\python.exe scripts\servidor_canales.py
```

`Invoke-RestMethod http://127.0.0.1:8100/salud` informa si Telegram y WhatsApp están configurados y
si el agente responde.

### Telegram

**Opción A · webhook** (la de producción). Publica el puerto 8100 con el túnel y registra el webhook:

```powershell
.\tunel_cloudflare.ps1 -Port 8100
.venv\Scripts\python.exe scripts\configurar_telegram.py --url (Get-Content .\tunel.url)
```

El webhook valida `X-Telegram-Bot-Api-Secret-Token` contra `TELEGRAM_SECRET`. Si el mismo bot ya lo
usa otro servicio, este comando **lo reemplaza**.

**Opción B · polling** (local, sin túnel). Solo funciona si el bot no tiene webhook:

```powershell
.venv\Scripts\python.exe scripts\telegram_polling.py
# si el bot ya tiene webhook y quieres que responda este canal:
.venv\Scripts\python.exe scripts\telegram_polling.py --quitar-webhook
```

`TELEGRAM_ENVIO=log` imprime las respuestas en el log en vez de enviarlas: sirve para probar el canal
sin escribirle a un chat real.

### WhatsApp

El puente usa la **conversación contigo mismo** ("Mensajes guardados"): lo que escribes ahí es lo que
responde el agente. Cada mensaje entra por `POST /whatsapp/mensaje` y sigue el **mismo camino que
Telegram**: el supervisor elige un agente del equipo, lo cita (`Respondió: <agente>`) y no reescribe su
texto.

**En producción el canal vive en `coordinador-cz-acciones`.** Esa app suma el buildpack
`heroku/nodejs` (el puente es Node/Baileys) y arranca el puente dentro de su propio dyno
(`WHATSAPP_PUENTE=true`), hablando con la API por loopback. Como el disco del dyno es efímero y Heroku
lo recicla al menos cada 24 h, la sesión vinculada se guarda cifrada en Postgres
(`WHATSAPP_SESION_DURABLE=true`, tabla `czz_wa_sesion` con AES-256-GCM y una llave derivada de
`WHATSAPP_SECRET`): así no hay que volver a escanear el QR en cada deploy. `GET /salud` informa
`canal_whatsapp` y `puente_whatsapp.activo`.

Para vincular el teléfono (una sola vez por sesión perdida), desde tu máquina con `CANALES_TOKEN` en
el entorno:

```powershell
# guarda el QR en qr-whatsapp.png usando la cabecera X-Canales-Token (no ?token=, que quedaría en los logs)
.venv\Scripts\python.exe scripts\qr_whatsapp.py --url https://coordinador-cz-acciones-aabcdf3f447b.herokuapp.com --conectar
# escanéalo desde WhatsApp > Dispositivos vinculados; si expira, repite el comando
```

También se puede hacer a mano: `POST /whatsapp/modo` con `{"modo":"qr"}`, `POST /whatsapp/conectar`,
`GET /whatsapp/qr.png` (con la cabecera) y `GET /whatsapp/estado`. Para vincular con código:
`POST /whatsapp/codigo` con `{"telefono":"56911112222"}` (sin `+` ni separadores) y luego el código en
el teléfono. `POST /whatsapp/desconectar` cierra la sesión.

En local el camino sigue siendo `scripts/servidor_canales.py` (puente en el puerto 18082), con
`WHATSAPP_PUENTE=false` y `WHATSAPP_SESION_DURABLE=false`: la sesión queda en
`whatsapp/.runtime/` (ignorado por git: son credenciales) y no toca el Postgres del taller.

### Endpoints

| Método | Ruta                                                                   | Uso                                 |
| ------- | ---------------------------------------------------------------------- | ----------------------------------- |
| POST    | `/telegram/webhook`                                                  | Telegram (secreto en cabecera)      |
| POST    | `/whatsapp/mensaje`                                                  | Puente Baileys (secreto compartido) |
| GET     | `/whatsapp/estado` · `/qr` · `/qr.png` · `/codigo`          | Estado y vinculación               |
| POST    | `/whatsapp/conectar` · `/desconectar` · `/modo` · `/codigo` | Control de la vinculación          |
| GET     | `/ok` · `/salud`                                                  | Salud del servicio y del agente     |

Si defines `CANALES_TOKEN`, la gestión exige `X-Canales-Token` (o `?token=` para abrir el QR en el
navegador; `scripts\qr_whatsapp.py` usa la cabecera porque la URL queda en los registros del router).

### Pruebas

```powershell
.venv\Scripts\python.exe -m pytest tests\test_canales.py -q   # canales, sin red
npm run whatsapp:test                                          # puente Node
```

## Chat web: login, equipo de agentes y flujo A2A

`web/` es una página de chat que habla A2A con el agente local y con hasta **cuatro agentes remotos**
que agregues por su URL pública. Cada turno se ve en el panel **Flujo A2A**: descubrimiento de cada
tarjeta, consulta en paralelo a los agentes del equipo y síntesis del agente local.

| Proceso  | Puerto | Para qué                                                 |
| -------- | ------ | --------------------------------------------------------- |
| Agente   | 2029   | `langgraph dev` (A2A), también sintetiza               |
| Chat web | 8110   | FastAPI + página estática (`scripts/servidor_web.py`) |

### Preparación

```powershell
.venv\Scripts\python.exe scripts\clave_web.py --usuario carlos
# pega en .env las tres líneas que imprime: WEB_USUARIO, WEB_CLAVE_HASH y WEB_SECRETO
```

`WEB_CLAVE_HASH` es un PBKDF2-SHA256 con sal; la clave en claro no se guarda. `WEB_SECRETO` firma la
cookie de sesión (`HttpOnly`, `SameSite=Lax`, `Secure` cuando se entra por HTTPS, 8 h por defecto).
Cualquier cambio en estas variables exige **reiniciar** `scripts\servidor_web.py`: `.env` se lee al
arrancar, así que con el proceso viejo la clave nueva no vale.

El login devuelve además el mismo token firmado en el cuerpo. La página lo guarda en `sessionStorage`
y lo reenvía en `Authorization: Bearer <token>`: si el navegador descarta la cookie (webviews, cookies
de terceros bloqueadas, incógnito agresivo) la sesión sigue funcionando. El token dura la pestaña y
las escrituras siguen exigiendo `X-Solicitado-Por`, así que no habilita CSRF.

### Arranque

```powershell
# terminal 1 · agente A2A
.venv\Scripts\langgraph.exe dev --port 2029

# terminal 2 · chat web
.venv\Scripts\python.exe scripts\servidor_web.py
```

Abre `http://127.0.0.1:8110`, entra con tu usuario y clave. `Get http://127.0.0.1:8110/salud` informa
el estado del agente local y cuántos agentes remotos hay en el equipo.

### Qué hace cada turno

1. **Descubrimiento** — lee `/.well-known/agent-card.json` de cada agente; si el servidor es
   `langgraph dev`, primero resuelve el `assistant_id` en `/assistants/search`.
2. **Consultas en paralelo** — `message/send` a cada agente remoto, cada uno con su `contextId`
   derivado de la conversación, así recuerdan los turnos anteriores.
3. **Síntesis** — el agente local recibe la pregunta y los aportes de los colegas entre etiquetas
   (`<respuestas_agentes>`) y entrega una sola respuesta. Las respuestas ajenas son datos, no
   instrucciones.
4. **Traza** — cada paso con su URL, latencia, estado y el texto que devolvió el agente.

Sobre el redactor hay cinco **preguntas de ejemplo** que se envían con un clic. Tres muestran el agente
de acciones (análisis de NVDA con perfil y horizonte, precio de SQM-B en CLP y una consulta tributaria
que el agente declara fuera de su alcance) y dos son abiertas al equipo: quiénes lo forman y qué hace
cada uno, y a quién pedirle ayuda para automatizar un proceso.

### Equipo de agentes

- Se agregan por URL (`http` o `https`) y se validan contra la tarjeta antes de guardarlas.
- Tope de **4** agentes remotos; al llegar al tope hay que quitar uno.
- La URL de la tarjeta se reescribe al host que escribiste: un agente publicado por túnel anuncia su
  `127.0.0.1`, que solo existe en su máquina.
- **Clave por agente.** Si la tarjeta declara que `message/send` exige credencial (`securitySchemes`),
  el panel pide la clave en el campo *Clave* y la guarda con ese agente; nunca vuelve por la API. El
  valor viaja en la cabecera que anuncie la ficha (`X-API-Key` en el agente de auditoría, `X-Agente-Clave`
  en `agente_cz_A2A`, `Authorization: Bearer` si declara HTTP Bearer) junto con `A2A-Version` cuando la
  tarjeta publica `supportedInterfaces`. El botón **clave** de un agente ya agregado permite cambiarla
  sin quitarlo del equipo. Sin la clave, el panel lo marca en ámbar como *requiere clave*.
- Si la URL guardada es `http` y la ficha anuncia `https`, se consulta por `https` para no enviar la
  clave sin cifrar; si ese host solo escucha en `http`, se reintenta con la URL escrita.

### Endpoints

| Método               | Ruta                              | Uso                                      |
| --------------------- | --------------------------------- | ---------------------------------------- |
| POST                  | `/api/login` · `/api/logout` | Sesión con cookie firmada               |
| GET                   | `/api/sesion`                   | Usuario, agente y tope de equipo         |
| GET · POST · DELETE | `/api/agentes`                  | Equipo (máximo 4, validado por tarjeta; `clave` opcional por agente) |
| GET · POST           | `/api/charlas`                  | Conversaciones guardadas en SQLite       |
| GET · DELETE         | `/api/charlas/{id}`             | Historial y borrado                      |
| POST                  | `/api/charlas/{id}/mensaje`     | Turno A2A completo con su traza          |
| GET                   | `/ok` · `/salud`             | Salud del servicio y del agente          |

Las escrituras exigen la cabecera `X-Solicitado-Por: chat-web` (la pone la página): un formulario de
otro sitio no puede enviarla. Tras cinco intentos fallidos, el login bloquea ese origen 60 segundos.

### Datos y pruebas

Conversaciones, equipo y trazas viven en `web/.runtime/chat.db` (ignorado por git).

```powershell
.venv\Scripts\python.exe -m pytest tests\test_web.py -q   # login, equipo, orquestación, estáticos
```

## Estructura

```
mi-agente-czz/
├── AGENTS.md  plan.json  langgraph.json  pyproject.toml  package.json
├── requirements.txt  requirements-notebook.txt  .env.example  README.md
├── src/agente_acciones/   graph.py  herramientas.py  prompts.py  tarjeta.py  servidor.py
├── coordinador/         main.py  config.py  supervisor.py  fichas.py  a2a.py  canal.py
├── canales/             main.py  telegram.py  whatsapp.py  agente.py  config.py
├── web/                 main.py  config.py  auth.py  almacen.py  a2a.py  orquestador.py · static/
├── scripts/             servidor_agente.py · servidor_coordinador.py · probar_coordinador.py · verificar_entrega.py · heroku_web.py · servidor_canales.py · servidor_web.py · clave_web.py
├── Procfile · .python-version · .slugignore   ← despliegue en Heroku
├── whatsapp/            src/*.mjs · test/internal.test.mjs   ← puente Node/Baileys
├── bruno/               0-assistant-id · agent-card · 1-configurar-tarjeta · message-send
│                        produccion/ 01..16 (ficha, salud, send, 401, Telegram, coordinador)
├── tunel_cloudflare.ps1 · tunel_cloudflare.py
├── tests/               test_a2a_czz.py · test_servidor_agente.py · test_coordinador.py · test_datos_taller.py · test_canales.py · test_web.py
├── evidencias/          verificacion_resultados.txt · saltos_coordinador.txt · agente_apagado.txt
├── notebooks/           a2a-test.ipynb
└── logs/  evidencias/
```

## Diferencias con `mi-agente-cz`

| Aspecto     | `mi-agente-cz` (original) | `mi-agente-czz` (esta copia)                                             |
| ----------- | --------------------------- | -------------------------------------------------------------------------- |
| Grafo       | `agente_czz`              | `agente_cz_A2A`                                                          |
| Puerto      | 2025                        | 2029 (canales en 8100, chat web en 8110)                                   |
| Entorno     | `.venv` del original      | `.venv`, `.env` y `node_modules` propios                             |
| Identidad   | Agente del taller           | Servicio autónomo para A2A                                                |
| Prompt      | Método de asesoría        | Método + bloque de servicio A2A y respuesta sin bloquear el turno         |
| Canales     | Solo notebook y Bruno       | **Telegram y WhatsApp** operativos, con pruebas                      |
| Interfaz    | Notebook                    | **Chat web con login, equipo de 4 agentes y flujo A2A**, con pruebas |
| Convivencia | —                          | Se puede levantar junto al original sin colisiones                         |

> `.env` contiene claves y está ignorado por git. El zip debe incluir `.env.example`, no `.env` ni
> `whatsapp/.runtime/` (credenciales de la sesión de WhatsApp).
