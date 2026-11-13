## Blueprint · Agente `agente_cz_A2A` · copia autónoma del agente de Carlos Zapata

**Taller A2A · Grupo 1** — Alejandra Ubilla, Carlos Monroy, Bryhan Cortes y Carlos Zapata.

| Qué definir | Esta copia |
|---|---|
| Rol y alcance | **Hace:** analiza acciones con datos de mercado y fundamentales, compara alternativas y entrega una decisión condicionada al perfil. **No hace:** pagos, ejecución de inversiones, ni asesoría tributaria o legal. |
| Herramientas | `consultar_mis_apuntes(tema)`, `consultar_acciones(ticker, pais)`, `consultar_fundamentales(ticker, pais)` y `derivar_a_cumplimiento(motivo)`. Datos simulados, coherentes entre sí y con fecha de corte. |
| Autonomía | **Decide solo:** consultar mercado, fundamentales y apuntes, y responder en un único turno. **Nunca sin una persona:** ejecutar pagos, compras, ventas o inversiones. |
| Cuándo pide ayuda | **Pregunta si falta:** el ticker o el mercado. **Condiciona y pregunta al final:** perfil de riesgo y horizonte. **Deriva a otro especialista cuando:** la consulta es tributaria o normativa. |
| Dónde se ejecuta | `http://127.0.0.1:2029` · grafo `agente_cz_A2A` |
| Cómo lo usan | Otro agente lo descubre por `/assistants/search`, lee su Agent Card y le envía la tarea por `message/send` con un `contextId` propio. |
| Canales | **Telegram** (webhook en `8100/telegram/webhook` o polling) y **WhatsApp** (puente Baileys en `18082`, mensajes de la conversación propia). Ambos consultan al agente por A2A. |

### Del diseño al código
- **Rol y alcance**, **autonomía** y **cuándo pide ayuda** → reglas del prompt (`src/agente_acciones/prompts.py`).
- **Herramientas** → lista `HERRAMIENTAS` (`src/agente_acciones/herramientas.py`).
- **Dónde se ejecuta** → `langgraph.json` y el puerto 2029.
- **Cómo lo usan** → `README.md` (contrato A2A), `bruno/`, `notebooks/a2a-test.ipynb` y `tests/`.
