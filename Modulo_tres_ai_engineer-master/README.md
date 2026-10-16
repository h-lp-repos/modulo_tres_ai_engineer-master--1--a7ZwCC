# Track OrbitAir · M3 — Hands-on del instructor

**AI Engineering 2.0 · M3 — Agentes y Orquestación · Track espejo del instructor**

> Regla de no-spoiler: todo lo que se resuelve acá es sobre **OrbitAir** (aerolínea). El estudiante
> transfiere la técnica a su Nubbix Desk o Vaulta Desk por su cuenta. Nada de este repo menciona ni
> resuelve el track del alumno.

OrbitAir es una aerolínea regional ficticia de LATAM. En el M1 su sistema aprendió a clasificar consultas de
pasajeros; en el M2, a responderlas con sus políticas oficiales (RAG). En el M3 aprende a **actuar**: un agente
que consulta los sistemas de OrbitAir (estado de vuelos, valijas, reservas), combina el dato con la política y,
cuando hace falta, inicia un trámite — con un humano aprobando lo que tiene efectos. Se construye clase a clase:
loop a mano → LangGraph → multiagente → MCP → trazabilidad y evals.

**Estado:** C1 a C5 completas (anatomía de un agente, LangGraph, multiagente, MCP, trazabilidad y evals),
validadas en modo mock.
Qué tiene que chequear el instructor antes de dictar (corridas con la API real, decisiones): `CHECKLIST_INSTRUCTOR.md`.

El repo tiene tres capas, cada una con un lector distinto:

| Archivo / carpeta | Para quién | Qué es |
|---|---|---|
| `README.md` (este) | Cualquiera, primera lectura | Índice del repo: estructura, setup, qué mirar según el rol. |
| **`GUIA_C1.md` … `GUIA_C5.md`** | **Instructor, antes de la clase** | La guía de 8 pasos de cada clase: objetivo, consigna, dataset, resolución, preguntas, errores. |
| **`EJERCICIOS_C1.md` … `EJERCICIOS_C5.md`** | **Se proyecta en clase** | Las consignas de los ejercicios de cada clase, qué se espera ver y qué discutir. |
| **`starter/`** | **El instructor lo abre y completa en vivo** | Mismo código que la solución, con las funciones clave vaciadas (`TODO` + `NotImplementedError`). Los scripts ya corren y fallan justo donde falta completar. |
| `src/` | Se muestra al cierre de cada ejercicio | La solución de referencia. |

```
orbitair-m3/
├── README.md                     ← este índice
├── GUIA_C1.md … GUIA_C5.md       ← guía de 8 pasos de cada clase (instructor)
├── EJERCICIOS_C1.md … _C5.md     ← consignas de cada clase (se proyectan)
├── CHECKLIST_INSTRUCTOR.md       ← qué correr con la API real y qué decidir antes de dictar
├── pyproject.toml                ← dependencias (uv sync) · requirements.txt para pip
├── pricing.json                  ← precios por 1M tokens (VERIFICAR antes de cada cursada)
├── .env.example                  ← API key + modelo + modo mock (+ claves de Langfuse, opcionales)
├── corpus/                       ← políticas de OrbitAir (las mismas del M2: equipaje, tarifas, reembolsos)
├── data/
│   ├── ops/                           ← base de operaciones mock: vuelos (60), pasajeros (120), reservas (122),
│   │   │                                 valijas (200), reembolsos (40) + generar_ops.py (determinista)
│   ├── c1_consultas_agente.jsonl      ← 13 consultas etiquetadas por TRAYECTORIA (herramientas, parada, hechos)
│   ├── c3_consultas_multiagente.jsonl ← 25 consultas etiquetadas con la RUTA esperada (9 cruzan dominios)
│   └── c5_conversaciones.jsonl        ← 10 conversaciones (25 turnos, cada uno un caso de C3): sesiones para C5
├── src/
│   ├── orbitair/                 ← librería mínima (crece clase a clase)
│   │   ├── llm.py                C1 · cliente de chat con tool calling: tokens, costo, latencia, mock
│   │   ├── operaciones.py        C1 · la base de operaciones (SQLite), permisos por pasajero, fallas inyectables
│   │   ├── politicas.py          C1 · buscar_politica: BM25 sobre el corpus (en C3: el retrieval del M2)
│   │   ├── tools.py              C1 · especificaciones de las herramientas + ejecutar_tool (punto de control)
│   │   ├── errores.py            C1 · triage de errores: reintentar / informar al modelo / abortar
│   │   ├── agente.py             C1 · el loop ReAct a mano, stopping rules, cierre forzado, prompts
│   │   ├── memoria.py            C1 · corto plazo (recorte por turnos) y largo plazo (hechos entre sesiones)
│   │   ├── grafo.py              C2 · el agente como grafo de LangGraph: estado, nodos, edges, checkpoints, HITL
│   │   ├── retrieval.py          C3 · el retrieval del M2: híbrida (embeddings + BM25 + RRF) con filtro por documento
│   │   ├── workers.py            C3 · los 3 especialistas: el grafo de C2 con su prompt, herramientas y documento
│   │   ├── orquestador.py        C3 · router por intención, workers en paralelo (Send), síntesis
│   │   ├── mcp_server.py         C4 · el server MCP: tools, resources, prompts; permisos por rol, auditoría
│   │   ├── mcp_cliente.py        C4 · el agente como cliente MCP (stdio), errores tipados → triage, defensas del host
│   │   ├── mcp_terceros.py       C4 · un server "de la comunidad" con tool poisoning y colisión de nombres
│   │   ├── trazas.py             C5 · trazas/observaciones/scores (local + Langfuse), árbol de la traza en la terminal
│   │   ├── evals.py              C5 · atender observado, costo por sesión, evals de trayectoria, gate, experimentos
│   │   ├── historial.py · trayectoria.py   lectura de tool calls del historial · chequeo de trayectorias
│   │   ├── mock_agente.py        el "modelo" del modo mock (guion determinista con la interfaz de tool calling)
│   │   ├── mock_orquestador.py   C3 · el router (por palabras clave) y la síntesis del modo mock
│   │   └── bm25.py · corpus.py · data.py · pricing.py   (bm25 y corpus vienen del M2 sin cambios)
│   ├── c1/
│   │   ├── 01_una_tool.py            Ej. 1 · una vuelta desarmada: el modelo propone, el código ejecuta
│   │   ├── 02_loop_react.py          Ej. 2 · el loop sobre las 13 consultas, con chequeo de trayectoria
│   │   ├── 03_colgar_el_loop.py      Ej. 3 · prompt ingenuo + valija en búsqueda: sin reglas vs con reglas
│   │   ├── 04_errores.py             Ej. 4 · cinco fallas inyectadas, con y sin triage (--sin-triage)
│   │   └── 05_memoria.py             Ej. 5 · recorte ingenuo vs por turnos; segunda sesión con y sin memoria
│   ├── c2/
│   │   ├── 01_migrar_a_langgraph.py  Ej. 1 · C1 vs grafo en las 13 consultas (--id: recorrido nodo a nodo)
│   │   ├── 02_checkpoints.py         Ej. 2 · thread_id, reinicio con SQLite (--turno), historia y time travel
│   │   ├── 03_human_in_the_loop.py   Ej. 3 · interrupt antes de iniciar_reembolso (--pausar / --reanudar)
│   │   ├── 04_streaming.py           Ej. 4 · updates / values / custom (--fallas: reintentos en vivo)
│   │   └── 05_debug_grafo.py         Ej. 5 · bug de migración: GraphRecursionError e historia del estado
│   ├── c3/
│   │   ├── 01_workers.py             Ej. 1 · retrieval filtrado por worker; cada worker en su dominio
│   │   ├── 02_routing.py             Ej. 2 · el router sobre las 25 consultas: exacta, de más, de menos; salidas rotas
│   │   ├── 03_orquestador.py         Ej. 3 · recorrido nodo a nodo (--id), paralelo vs en serie, --todas, --mermaid
│   │   ├── 04_se_justifica.py        Ej. 4 · agente único vs router vs orquestador, por tipo de consulta (--cruces)
│   │   └── 05_hitl_multiagente.py    Ej. 5 · interrupt adentro de un worker: qué se repite al reanudar
│   ├── c4/
│   │   ├── 01_server.py              Ej. 1 · el server desde un cliente: tools/list (--schema), call, resources, prompts
│   │   ├── 02_cliente.py             Ej. 2 · worker local vs worker sobre MCP; triage a través del protocolo
│   │   ├── 03_seguridad.py           Ej. 3 · batería de 15 ataques contra el server y auditoría
│   │   ├── 04_orquestador_mcp.py     Ej. 4 · el worker de reembolsos sobre MCP en el orquestador; HITL en el host
│   │   └── 05_terceros.py            Ej. 5 · exfiltración de la sesión, colisión de nombres, tool poisoning
│   └── c5/
│       ├── 01_trazas.py              Ej. 1 · una consulta trazada y su árbol (--id); link a Langfuse si hay claves
│       ├── 02_sesiones.py            Ej. 2 · 10 conversaciones: costo y latencia por sesión; la sesión más cara, abierta
│       ├── 03_evals.py               Ej. 3 · evals de trayectoria desde las trazas: éxito end-to-end, por sesión, scores
│       ├── 04_experimentos.py        Ej. 4 · dataset, experimentos (v1, v1-serie, v1-gpt-4.1), gate (--gate: exit 1)
│       └── 05_diagnostico.py         Ej. 5 · un deploy que pasa los evals de calidad: encontrar la causa en las trazas
├── starter/                      ← espejo exacto de src/ (esqueleto con TODOs) + resolver_hasta.py
└── results/                      ← base SQLite, checkpoints, memoria, tablas generadas (no se versiona)
```

Qué queda vacío en `starter/` (lo que se escribe en vivo). C1: `spec_consultar_vuelo()` y `ejecutar_tool()` en
`tools.py`, `Agente.correr()` y `ReglasDeParada.evaluar()` en `agente.py`, `clasificar_error()` y
`ejecutar_con_triage()` en `errores.py`, `recortar_historial()` y `extraer_hechos()` en `memoria.py`. C2:
`ruta_agente()`, `construir_grafo()`, `abrir_checkpointer()` y `nodo_aprobacion()` en `grafo.py`. C3:
`AgenteWorker.ejecutar()` y `config_worker()` en `workers.py`; `validar_ruteo()`, `rutear()`, `asignar_workers()`
y `construir_orquestador()` en `orquestador.py`. C4: `registrar_consultar_vuelo()`, `registrar_politicas()`,
`registrar_prompts()`, `herramientas_permitidas()` y `ejecutar_auditado()` en `mcp_server.py`; `spec_openai()` y
`ClienteMCP.llamar()` en `mcp_cliente.py` (hasta el Ej. 3 el server usa versiones provisorias: todos los roles ven
todas las tools y los errores no se traducen). C5: `Observacion.registrar_llm()` y `registrar_tool()` en `trazas.py`;
`atender()`, `resumen_sesiones()`, `trayectoria_de_traza()`, `evaluar_trayectoria()` y `chequear_regresion()` en
`evals.py`. Mientras no se
completan los ejercicios 3 y 4 de C1, el starter usa versiones provisorias (sin reglas; sin triage: todo error
vuelve al modelo), así el loop del Ej. 2 ya corre — y se ve qué falla sin ellas. Antes de C2:
`python starter/resolver_hasta.py 1`; antes de C3: `python starter/resolver_hasta.py 2`; antes de C4: `... 3`; antes de C5: `... 4`. Todo lo demás (base de operaciones, herramientas, nodos del grafo, mock,
tablas) viene resuelto para que la clase se gaste en los conceptos y no en plomería.

### Setup (2 minutos, antes de la clase)

Recomendado: [`uv`](https://docs.astral.sh/uv/).

```bash
uv sync                                   # crea .venv e instala todo desde pyproject.toml
cp .env.example .env                      # completar OPENAI_API_KEY (o dejar ORBITAIR_MOCK=1)
uv run src/c1/02_loop_react.py            # `uv run` usa el venv sin activarlo
```

Alternativa con pip clásico:

```bash
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

En las guías y ejercicios los comandos aparecen como `python ...`; con uv es `uv run ...` (o activar el venv y
usar `python` igual).

Sin API key o para ensayar sin gastar: `ORBITAIR_MOCK=1` en el `.env`. Todo corre igual: el "modelo" es un
guion determinista (`orbitair/mock_agente.py`) con la misma interfaz de tool calling — extrae códigos, llama
herramientas, resuelve referencias con la memoria, obedece al prompt ingenuo que cuelga el loop. Alcanza para
ensayar el loop, las stopping rules, el triage, la memoria y el grafo con resultados reproducibles; **no** para
juzgar la calidad del agente: eso se ve con la API real.

La base de operaciones (`results/orbitair_ops.db`) se arma sola desde `data/ops/*.csv` la primera vez; los
scripts la reinician al empezar (C2 · Ej. 3 escribe reembolsos).

**C4 (MCP):** el server corre como subproceso por stdio; no necesita puertos ni cuentas. **C5 (Langfuse):** con
`LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY` y `LANGFUSE_BASE_URL` en el `.env` las trazas también se ven en
Langfuse (Cloud tiene plan gratuito); sin ellas, todo queda en `results/c5_trazas/` y los evals corren igual.
Antes de dictar, revisar `CHECKLIST_INSTRUCTOR.md`.

---

*Precios en `pricing.json` verificados en 2026-09; cambian con frecuencia. Verificar en las páginas oficiales
de pricing antes de cada cursada.*
