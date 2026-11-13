# `agente_cz_A2A` · copia autónoma del agente de Carlos Zapata

Servicio **A2A (Agent2Agent)** que expone el mismo perfil de asesoría en acciones de
[`mi-agente-cz`](<../grupo-1-taller-a2a - entrega/mi-agente-cz/README.md>), pero como una **copia independiente**: su propio grafo,
su propio puerto, su propio `.env` y su propio entorno virtual. Se puede levantar solo, junto al
agente original o junto al resto de los agentes del grupo, y está pensado para que **otro agente lo
descubra y lo invoque** sin intervención humana.

> **Proyecto independiente.** Vive en `Taller UAI IA\mi-agente-czz`, fuera del repositorio
> `grupo-1-taller-a2a - entrega`. No comparte código ni entorno con el proyecto del grupo; solo
> intercambia mensajes A2A por HTTP.

| Qué definir | Esta copia |
| --- | --- |
| Grafo / nombre A2A | `agente_cz_A2A` |
| Dónde corre | `http://127.0.0.1:2029` |
| Tipo de servicio | A2A nativo de `langgraph dev` (JSON-RPC sobre HTTP) |
| Canales | Telegram (`8100/telegram/webhook` o polling) y WhatsApp (puente Baileys en 18082) |
| Chat web | `http://127.0.0.1:8110` con login, equipo de hasta 4 agentes remotos y traza del flujo A2A |
| Autonomía | Consulta mercado, fundamentales y apuntes sin aprobación; entrega el análisis completo en un turno |
| Nunca sin una persona | Pagos, compras, ventas o transferencias |
| Fuera de alcance | Lo tributario, legal y normativo: lo deriva al agente de auditoría |

## Contrato A2A

Todo lo que otro agente necesita está en la tarjeta del agente; no hay acoplamiento al código.

| Paso | Llamada | Para qué |
| --- | --- | --- |
| 1 | `POST /assistants/search` con `{"graph_id": "agente_cz_A2A"}` | Obtener el `assistant_id` (UUID) |
| 2 | `GET /.well-known/agent-card.json?assistant_id=<uuid>` | Leer nombre, descripción, skills y `url` del endpoint A2A |
| 3 | `POST /a2a/<uuid>` con `message/send` | Enviar la tarea y recibir la respuesta |

Reglas del contrato:

- El `contextId` del mensaje es el `thread_id` del servidor: reutilízalo para que el agente recuerde
  los turnos anteriores de la misma conversación.
- La tarjeta anuncia la URL local. Si se publica por túnel, el cliente remoto debe reescribir
  `supported_interfaces[].url` antes de enviar.
- El agente responde en un solo turno con el análisis y la fecha de corte. Si falta el ticker o el
  mercado, devuelve una única pregunta concreta; si solo falta el perfil de riesgo, entrega el
  análisis condicionado en vez de bloquear.

### Datos garantizados

El grafo no deja las cifras al criterio del modelo: el middleware `DatosDelTaller` lee el ticker y el
mercado del mensaje, ejecuta `consultar_acciones` y `consultar_fundamentales` de forma determinista y
entrega el resultado en el mismo turno, entre las etiquetas `<datos_herramientas>`. Así el cliente
siempre recibe el precio y los fundamentales simulados del taller con su fecha de corte, aunque el modelo
hubiera preferido responder de memoria. Ese bloque viaja solo al modelo: el `history` que ve el cliente
A2A sigue siendo `user` / `agent`.

## Cómo ejecutar

```powershell
cd mi-agente-czz
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
copy .env.example .env            # y pega tu GOOGLE_API_KEY
.venv\Scripts\langgraph.exe dev --port 2029
```

> Mientras edites el proyecto usa `--no-reload`: el watcher de `langgraph dev` recarga el servidor ante
> cualquier cambio de archivo y, en Windows, el proceso termina en lugar de reiniciarse.

Comprobaciones:

```powershell
Invoke-RestMethod "http://127.0.0.1:2029/ok"
Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:2029/assistants/search" `
  -ContentType "application/json" -Body '{"graph_id":"agente_cz_A2A"}'
Invoke-RestMethod "http://127.0.0.1:2029/.well-known/agent-card.json?assistant_id=<uuid>"
```

Pruebas (las de A2A se saltan si el servidor no está arriba; comparan el texto final con las cifras
que devuelven las herramientas, no con el JSON completo):

```powershell
.venv\Scripts\python.exe -m pytest tests -q
```

Ficha para los demás agentes: `langgraph dev` crea el asistente con una descripción genérica. Tras
cada arranque, publica la descripción real en la Agent Card:

```powershell
.venv\Scripts\python.exe scripts\configurar_tarjeta.py
# o contra el túnel:  ... --url https://<algo>.trycloudflare.com
```

## Cómo lo invoca otro agente

### Con `httpx` (sin dependencias del SDK)

```python
import uuid
import httpx

BASE = "http://127.0.0.1:2029"
GRAFO = "agente_cz_A2A"

assistant_id = httpx.post(
    f"{BASE}/assistants/search", json={"graph_id": GRAFO}, timeout=10
).json()[0]["assistant_id"]

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
    f"{BASE}/a2a/{assistant_id}", json=cuerpo, headers={"Accept": "application/json"}, timeout=180
).json()
resultado = respuesta["result"]
# El texto viene en `artifacts` en el primer turno y en el último turno del `history` en los siguientes.
partes = [p["text"] for a in resultado.get("artifacts") or [] for p in a.get("parts", []) if p.get("kind") == "text"]
if not partes:
    ultimo = next((m for m in reversed(resultado.get("history") or []) if m.get("role") == "agent"), None)
    partes = [p["text"] for p in (ultimo or {}).get("parts", []) if p.get("kind") == "text"]
texto = "\n".join(partes)
```

> El endpoint rechaza las peticiones sin `Accept: application/json` (responde
> `{"error":"Accept header must include application/json"}`).

### Con la colección Bruno

`bruno/0-assistant-id` resuelve el UUID, `bruno/agent-card` lee la tarjeta y `bruno/message-send`
hace el envío. El entorno `local` ya apunta al puerto 2029 y al grafo `agente_cz_A2A`.

### Registrar esta copia en el orquestador del grupo

El servicio del grupo (`grupo-1-taller-a2a - entrega/servicio-fastapi/`) descubre los agentes por los
servidores que tenga configurados. Para incluirlo, agrega el puerto en su `.env`:

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
    "descripcion": "Servicio A2A que entrega análisis de acciones con datos de mercado y fundamentales, condicionado al perfil de riesgo, y deriva lo tributario al agente de auditoría.",
    "palabras_clave": ["acción", "acciones", "invertir", "ticker", "per", "fundamentales", "portafolio", "riesgo"]
  }
}
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

## Exponerlo con un túnel de Cloudflare

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

| Proceso | Puerto | Para qué |
| --- | --- | --- |
| Agente | 2029 | `langgraph dev` (A2A) |
| Canales | 8100 | API de Telegram y WhatsApp (`scripts/servidor_canales.py`) |
| Puente WhatsApp | 18082 | Node + Baileys, solo loopback |

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
responde el agente. Para vincular el teléfono:

```powershell
# 1. elegir QR (por defecto el puente pide código por teléfono)
Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8100/whatsapp/modo" `
  -ContentType "application/json" -Body '{"modo":"qr"}'
# 2. abrir la sesión
Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8100/whatsapp/conectar"
# 3. ver el QR y escanearlo desde WhatsApp > Dispositivos vinculados
Start-Process "http://127.0.0.1:8100/whatsapp/qr.png"
```

Para vincular con código: `POST /whatsapp/codigo` con `{"telefono":"56911112222"}` (sin `+` ni
separadores) y luego el código en el teléfono. Estado y cierre:
`GET /whatsapp/estado`, `POST /whatsapp/desconectar`.

La sesión vinculada queda en `whatsapp/.runtime/` (ignorado por git: son credenciales).

### Endpoints

| Método | Ruta | Uso |
| --- | --- | --- |
| POST | `/telegram/webhook` | Telegram (secreto en cabecera) |
| POST | `/whatsapp/mensaje` | Puente Baileys (secreto compartido) |
| GET | `/whatsapp/estado` · `/qr` · `/qr.png` · `/codigo` | Estado y vinculación |
| POST | `/whatsapp/conectar` · `/desconectar` · `/modo` · `/codigo` | Control de la vinculación |
| GET | `/ok` · `/salud` | Salud del servicio y del agente |

Si defines `CANALES_TOKEN`, la gestión exige `X-Canales-Token` (o `?token=` para abrir el QR en el
navegador).

### Pruebas

```powershell
.venv\Scripts\python.exe -m pytest tests\test_canales.py -q   # canales, sin red
npm run whatsapp:test                                          # puente Node
```

## Chat web: login, equipo de agentes y flujo A2A

`web/` es una página de chat que habla A2A con el agente local y con hasta **cuatro agentes remotos**
que agregues por su URL pública. Cada turno se ve en el panel **Flujo A2A**: descubrimiento de cada
tarjeta, consulta en paralelo a los agentes del equipo y síntesis del agente local.

| Proceso | Puerto | Para qué |
| --- | --- | --- |
| Agente | 2029 | `langgraph dev` (A2A), también sintetiza |
| Chat web | 8110 | FastAPI + página estática (`scripts/servidor_web.py`) |

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

Sobre el redactor hay cinco **preguntas de ejemplo** que se envían con un clic. Cada una muestra una
capacidad distinta y está probada contra el agente real: análisis de una acción de EE. UU. con perfil y
horizonte, precio de una acción chilena en CLP, análisis cuando falta el perfil de riesgo (condiciona y
pregunta al final), los criterios de evaluación de los apuntes y una consulta tributaria que se deriva
al agente de auditoría.

### Equipo de agentes

- Se agregan por URL (`http` o `https`) y se validan contra la tarjeta antes de guardarlas.
- Tope de **4** agentes remotos; al llegar al tope hay que quitar uno.
- La URL de la tarjeta se reescribe al host que escribiste: un agente publicado por túnel anuncia su
  `127.0.0.1`, que solo existe en su máquina.

### Endpoints

| Método | Ruta | Uso |
| --- | --- | --- |
| POST | `/api/login` · `/api/logout` | Sesión con cookie firmada |
| GET | `/api/sesion` | Usuario, agente y tope de equipo |
| GET · POST · DELETE | `/api/agentes` | Equipo (máximo 4, validado por tarjeta) |
| GET · POST | `/api/charlas` | Conversaciones guardadas en SQLite |
| GET · DELETE | `/api/charlas/{id}` | Historial y borrado |
| POST | `/api/charlas/{id}/mensaje` | Turno A2A completo con su traza |
| GET | `/ok` · `/salud` | Salud del servicio y del agente |

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
├── src/agente_acciones/   graph.py  herramientas.py  prompts.py
├── canales/             main.py  telegram.py  whatsapp.py  agente.py  config.py
├── web/                 main.py  config.py  auth.py  almacen.py  a2a.py  orquestador.py · static/
├── scripts/             configurar_tarjeta.py · configurar_telegram.py · servidor_canales.py · servidor_web.py · clave_web.py · telegram_polling.py
├── whatsapp/            src/*.mjs · test/internal.test.mjs   ← puente Node/Baileys
├── bruno/               0-assistant-id · agent-card · 1-configurar-tarjeta · message-send
├── tunel_cloudflare.ps1 · tunel_cloudflare.py
├── tests/               test_a2a_czz.py · test_datos_taller.py · test_canales.py · test_web.py
├── notebooks/           a2a-test.ipynb
└── logs/  evidencias/
```

## Diferencias con `mi-agente-cz`

| Aspecto | `mi-agente-cz` (original) | `mi-agente-czz` (esta copia) |
| --- | --- | --- |
| Grafo | `agente_czz` | `agente_cz_A2A` |
| Puerto | 2025 | 2029 (canales en 8100, chat web en 8110) |
| Entorno | `.venv` del original | `.venv`, `.env` y `node_modules` propios |
| Identidad | Agente del taller | Servicio autónomo para A2A |
| Prompt | Método de asesoría | Método + bloque de servicio A2A y respuesta sin bloquear el turno |
| Canales | Solo notebook y Bruno | **Telegram y WhatsApp** operativos, con pruebas |
| Interfaz | Notebook | **Chat web con login, equipo de 4 agentes y flujo A2A**, con pruebas |
| Convivencia | — | Se puede levantar junto al original sin colisiones |

> `.env` contiene claves y está ignorado por git. El zip debe incluir `.env.example`, no `.env` ni
> `whatsapp/.runtime/` (credenciales de la sesión de WhatsApp).
