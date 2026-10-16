# Clase 2 — LangGraph · Hands-on OrbitAir

**AI Engineering 2.0 · M3 — Agentes y Orquestación · Track espejo del instructor**

> Regla de no-spoiler: todo lo que se resuelve acá es sobre **OrbitAir** (aerolínea). El estudiante
> transfiere la técnica a su Nubbix Desk o Vaulta Desk por su cuenta. Nada de este repo menciona ni
> resuelve el track del alumno.

> Esta guía es sólo para el instructor. La consigna que se proyecta en clase está en `EJERCICIOS_C2.md`.

## 1. Objetivo de aprendizaje de la clase

Al terminar, el estudiante puede:

- Modelar un agente como **grafo de estado**: un estado tipado, nodos que lo actualizan y edges (fijos y
  condicionales) que deciden el próximo paso.
- Migrar el loop escrito a mano en C1 a LangGraph y **comprobar con datos** que el comportamiento no cambió.
- Usar **checkpoints** para tener memoria de conversación por `thread_id`, sobrevivir a un reinicio del proceso,
  leer la historia del estado y re-ejecutar desde un punto del pasado.
- Incorporar **human-in-the-loop**: pausar el grafo antes de una acción con efectos y reanudarlo con la decisión
  de un humano (aprobar, editar, rechazar).
- Usar el **streaming de estados** para la UI y para trazas, y **depurar el grafo** leyendo su estado.

## 2. Consigna

> El agente de C1 funciona, pero su lógica de control está escondida en un `while True` con cinco `return`. Si
> mañana hay que agregar "antes de iniciar un reembolso, que lo apruebe un supervisor", o retomar una
> conversación después de un reinicio, o mostrarle al pasajero "consultando tu vuelo…", hay que reescribir el
> loop. Hoy lo migramos a LangGraph: **mismo comportamiento, ahora inspeccionable**. Y aprovechamos lo que el
> grafo ya trae: checkpoints, pausas y streaming.

**Ejercicio 1 — Migrar.** `ruta_agente()` y `construir_grafo()`: el loop de C1 como grafo. Correr las 13
consultas con los dos agentes y comparar trayectorias.

**Ejercicio 2 — Checkpoints.** `abrir_checkpointer()`: conversación por thread, reinicio con SQLite, historia del
estado y time travel.

**Ejercicio 3 — Human-in-the-loop.** `nodo_aprobacion()`: `iniciar_reembolso` (la primera herramienta que escribe)
se pausa con `interrupt()`; un supervisor aprueba, edita el monto o rechaza.

**Ejercicio 4 — Streaming.** Correr y leer: `updates`, `values` y `custom` (progreso de las herramientas y
reintentos en vivo).

**Ejercicio 5 — Debugging del grafo.** Un bug de migración (se "simplificó" el nodo de control): encontrarlo con la
forma del grafo y la historia del estado.

## 3. Insumo / dataset de inicio

- El agente de C1 resuelto: `python starter/resolver_hasta.py 1`. Los nodos del grafo **reutilizan** sus piezas
  (`Agente.llamar_llm`, `Agente.ejecutar` con el triage, `ReglasDeParada.evaluar`, `Agente.cerrar`).
- Las 13 consultas de C1 (`data/c1_consultas_agente.jsonl`), para comprobar la migración.
- La base de operaciones de C1. Escenario nuevo para el Ej. 3: la reserva **M4TR88** de Lucía Fernández (P-1001),
  vuelo OA1388 SCL→LIM **cancelado por causa operativa**, familia Clásica, USD 412 con tarjeta de crédito: le
  corresponde el reembolso involuntario (POL-RE-01 §4).
- Herramienta nueva: `iniciar_reembolso` (escribe en la base; motivo validado contra un enum; rechaza si ya hay un
  reembolso en curso). Está marcada como **sensible** (`tools.SENSIBLES`).

**Setup previo:** `uv sync` instala `langgraph` y `langgraph-checkpoint-sqlite`. Sin API key: `ORBITAIR_MOCK=1`.
Los números de esta guía son del mock. **Pendiente: re-correr con la API real antes de la cursada.**

**Una decisión de diseño para explicar al empezar.** Los nodos llaman al mismo cliente de C1
(`orbitair/llm.py`), no a `ChatOpenAI` de LangChain. Así se ve que LangGraph es sobre **el control del flujo** y
que la migración no toca el modelo ni las herramientas. La alternativa prearmada (`create_react_agent`) se discute en §6.

## 4. Resolución paso a paso

Tiempos sugeridos para 90 minutos: 25 + 20 + 20 + 10 + 15.

### Paso 1 · Migrar el loop a un grafo (25 min)

```bash
python starter/resolver_hasta.py 1
python starter/c2/01_migrar_a_langgraph.py
python starter/c2/01_migrar_a_langgraph.py --id A-02
python starter/c2/01_migrar_a_langgraph.py --mermaid    # pegar en https://mermaid.live
```

1. Pizarrón: cada variable local del loop de C1 pasa a ser un campo del **estado** (`EstadoAgente`): `mensajes`
   (con reducer `operator.add`: los nodos devuelven mensajes nuevos y LangGraph los concatena), `pasos`,
   `costo_usd`, `firmas`, `parada`, `respuesta`. Cada `if` del loop pasa a ser un **edge condicional**.
2. Mostrar el diagrama del docstring de `grafo.py` y los nodos ya resueltos en `crear_nodos()`: son 5-10 líneas
   cada uno y llaman a C1.
3. Completar `ruta_agente()`: sin tool_calls pendientes → `"fin"`; alguna sensible → `"aprobacion"`; si no →
   `"herramientas"`.
4. Completar `construir_grafo()`: `add_node`, `add_edge(START, "control")`, los tres `add_conditional_edges`
   (control, agente, herramientas) y `compile()`.
5. Leer la comparación (mock): **misma trayectoria en 13/13**, mismo texto de respuesta en 13/13, mismo costo por
   consulta. Con la API real el texto puede variar entre corridas (no determinismo): por eso se compara la
   trayectoria y los hechos clave, no el string.
6. `--id A-02` muestra el recorrido nodo por nodo (`stream_mode="updates"`):
   `control → agente (pide consultar_vuelo) → herramientas → control → agente (pide buscar_politica) →
   herramientas → control → agente (responde)`. Es la misma traza de C1, ahora con nombre de nodo.

### Paso 2 · Checkpoints (20 min)

```bash
python starter/c2/02_checkpoints.py
python starter/c2/02_checkpoints.py --turno 1     # y en OTRA terminal / proceso:
python starter/c2/02_checkpoints.py --turno 2
```

1. Completar `abrir_checkpointer()`: `InMemorySaver()` o `SqliteSaver(sqlite3.connect(path,
   check_same_thread=False))`.
2. **Parte A.** Los 3 turnos de C1 · Ej. 5 en un mismo `thread_id`: el estado del thread crece (6 → 8 → 12
   mensajes) y T2 ("¿y a qué hora sale ahora ese vuelo?") se resuelve con el historial. En un thread nuevo, T2
   pregunta "¿de qué vuelo me hablás?". Lo que en C1 era la clase `Sesion` ahora es el checkpointer.
3. **Parte B.** Con SQLite, cada turno usa un grafo y una conexión nuevos: "al abrir: el thread ya tiene 6
   mensajes guardados". Para que se vea de verdad, correr `--turno 1` y `--turno 2` como dos procesos.
4. **Parte C.** `get_state_history()`: **10 checkpoints** para un turno de A-02 (uno por super-step: entrada,
   control, agente, herramientas…). Cada uno tiene `next` (qué nodo viene), los valores del estado y su
   `checkpoint_id`. Time travel: `grafo.invoke(None, config_de_un_checkpoint)` re-ejecuta desde ahí y crea una
   **rama** (la historia pasa de 10 a 17 checkpoints; la original sigue).
5. **Punto crítico — qué se reinicia por turno.** `mensajes` acumula toda la conversación, pero `pasos`, `firmas`,
   `costo_usd` y `parada` son **por turno** (`entrada_turno()` los pone en cero). Si no, en el turno 3 las stopping
   rules contarían los pasos de los turnos 1 y 2 y cortarían una consulta sana.

### Paso 3 · Human-in-the-loop (20 min)

```bash
python starter/c2/03_human_in_the_loop.py
python starter/c2/03_human_in_the_loop.py --pausar              # corre hasta la pausa y termina el proceso
python starter/c2/03_human_in_the_loop.py --reanudar editar --monto 150
```

1. Pizarrón: leer es reversible, **escribir no**. `iniciar_reembolso` crea un trámite: antes de ejecutarlo, un
   supervisor decide. El grafo ya lo prevé: `ruta_agente` manda las herramientas sensibles a `aprobacion`.
2. Completar `nodo_aprobacion()`: tomar la tool_call sensible, `decision = interrupt({...})` con lo que el
   supervisor necesita, y según la decisión: aprobar (nada), editar (`overrides` con los argumentos corregidos)
   o rechazar (un mensaje `tool` con `{"rechazado": true, ...}`, así `herramientas` no la ejecuta y el modelo sabe
   por qué).
3. Leer la salida: el agente consulta la reserva, el vuelo y la política, propone `iniciar_reembolso(M4TR88,
   cancelacion_involuntaria)` y **se detiene** (`next = ('aprobacion',)`), sin nada escrito en la base. Tres
   supervisores:
   - aprobar → `RE-11040 USD 412 solicitado`;
   - editar → `RE-11040 USD 206 solicitado`;
   - rechazar → la base sigue sin reembolsos y el agente le explica al pasajero que un supervisor no lo aprobó.
4. `--pausar` / `--reanudar`: el estado de la pausa vive en `results/c2_hitl.db`. El supervisor puede aprobar
   horas después, desde otro proceso. Sin checkpointer el grafo igual se detiene, pero no queda estado guardado:
   no hay desde dónde reanudar.
5. **Punto crítico — idempotencia.** Al reanudar, `nodo_aprobacion` se ejecuta **otra vez desde el principio** y
   `interrupt()` devuelve la decisión. Todo lo que esté antes de `interrupt()` tiene que poder repetirse sin
   efectos (no escribir en la base, no mandar mails ahí).

### Paso 4 · Streaming de estados (10 min)

```bash
python src/c2/04_streaming.py
python src/c2/04_streaming.py --modo values
python src/c2/04_streaming.py --id A-11 --fallas
```

Nada que completar.

1. `stream_mode=["updates", "custom"]`: cada nodo que termina emite qué cambió; el nodo `herramientas` emite
   además eventos propios con `get_stream_writer()` ("consultar_vuelo: ejecutando / ok").
2. `--id A-11 --fallas`: con 2 timeouts inyectados se ven los reintentos **en vivo** ("sin respuesta, reintento
   en 0.2 s… 0.4 s… ok (3 intentos)"). Eso es lo que la app le puede mostrar al pasajero mientras espera.
3. Primer evento a los ~0,01 s vs respuesta completa a ~0,5 s en mock (con la API real, 3-5 s): la latencia total
   es la misma, la **percibida** no (conexión con M1 · C1).
4. `--modo values`: el estado completo después de cada paso. Pesado para la UI, útil para depurar.
5. El modo `messages` (tokens del LLM a medida que se generan) necesita un chat model de LangChain; con el
   cliente propio no aplica. Ver §6.

### Paso 5 · Debugging del grafo (15 min)

```bash
python src/c2/05_debug_grafo.py
```

Nada que completar: es un ejercicio de lectura.

1. El "bug": al migrar alguien sacó el nodo `control` ("total, el modelo sabe cuándo parar"). Con el prompt
   ingenuo de C1 y A-10, el grafo da vueltas `agente → herramientas → agente…`.
2. **La forma**: comparar las aristas. Sin control, `herramientas → agente` cierra un ciclo cuya única salida
   depende del modelo.
3. **LangGraph corta solo**: `GraphRecursionError: Recursion limit of 12 reached`. Es su red de seguridad, pero
   corta con una **excepción** (el pasajero no recibe respuesta), cuenta super-steps del grafo (no pasos de LLM)
   y no sabe de costo ni de repeticiones. No reemplaza a las stopping rules.
4. **La historia**: aunque el grafo explotó, el estado quedó en el checkpointer. La tabla step a step muestra
   `agente → herramientas` alternando y la misma llamada `rastrear_valija({"codigo": "OA-771045"})` 6 veces:
   "6 llamadas, 1 distinta". El diagnóstico sale del estado, no de agregar prints.
5. **El arreglo**: con `control`, el mismo caso termina en `parada=repetida`, 2 pasos de LLM.

## 5. Link del repositorio con la solución

`[completar con la URL del repo de la cátedra]`

## 6. Preguntas posibles y respuestas sugeridas

**¿No es más fácil `create_react_agent` (`langgraph.prebuilt`)?**
Arma un grafo equivalente (agente ↔ herramientas) con muy poco código, con `ChatOpenAI` + `ToolNode`. Sirve para prototipar.
Pero las stopping rules quedan reducidas al `recursion_limit`, el triage de errores al manejo por defecto de
`ToolNode`, y la aprobación humana hay que agregarla igual. Para producción conviene el grafo explícito; para un
demo, el prebuilt. Mostrarlo comparando las aristas de los dos grafos.

**¿Por qué no usamos `ChatOpenAI` y los mensajes de LangChain?**
Para que la migración cambie sólo la orquestación. Con `ChatOpenAI` se gana el stream de tokens (modo
`messages`) y la integración con el ecosistema; se paga otra capa de abstracción sobre el modelo. Las dos son
válidas: lo importante es que el estado del grafo sea el estado del sistema.

**¿Qué diferencia hay entre un nodo y un edge condicional?**
El nodo **hace** algo y actualiza el estado; el edge condicional **decide** a dónde ir leyendo el estado y no lo
modifica. Si una función de ruta necesita escribir el estado, es un nodo (por eso `control` es un nodo: guarda
el motivo de parada).

**¿El checkpointer guarda también las herramientas ejecutadas? ¿Qué pasa si el proceso se cae a la mitad?**
Guarda el estado después de cada super-step. Si el proceso cae durante `herramientas`, al retomar ese nodo se
vuelve a ejecutar: las herramientas de escritura tienen que ser idempotentes o chequear si ya se hicieron
(`iniciar_reembolso` rechaza si ya hay uno en curso).

**¿Y `stream_events`? La documentación nueva lo usa en todos los ejemplos.**
LangGraph 1.2 suma `grafo.stream_events(input, config, version="v3")`: devuelve un objeto con proyecciones
tipadas (`.output`, `.interrupted`, `.interrupts`) en lugar de tuplas por modo. La propia librería lo marca como
**experimental** ("the v3 API is experimental and may change"), así que la clase usa `stream(stream_mode=...)`,
que es estable y sigue vigente. Vale mostrarlo como lo que viene: si un alumno copia un ejemplo de la documentación
actual, va a ver `stream_events` y conviene que sepa que es la misma idea.

**¿InMemorySaver o SQLite/Postgres?**
InMemory para tests y notebooks. En producción, persistente y compartido entre réplicas (Postgres:
`langgraph-checkpoint-postgres`). SQLite alcanza para una sola máquina y para la clase.

**¿Human-in-the-loop en todas las herramientas?**
No: sólo en las que tienen efectos y riesgo (dinero, datos de terceros, acciones irreversibles). Pedir aprobación
para consultar un vuelo es fricción sin beneficio. Criterio: ¿qué cuesta deshacerlo?

**¿Cómo se ve esto en producción?**
El `interrupt` devuelve el pedido de aprobación; la app lo manda a una cola o panel del supervisor; cuando decide,
otro proceso hace `invoke(Command(resume=...), config)` con el mismo `thread_id`. En C5 esto se traza en Langfuse.

## 7. Errores comunes y cómo resolverlos en vivo

**Devolver el estado completo desde un nodo con `mensajes`.** Con el reducer `operator.add`, devolver
`{"mensajes": s["mensajes"] + [nuevo]}` **duplica** el historial. Los nodos devuelven sólo lo nuevo.

**Olvidar reiniciar los contadores por turno.** Las reglas cortan en el turno 3 por pasos de turnos anteriores.
`entrada_turno()` los pone en cero.

**Usar `interrupt()` sin checkpointer.** El grafo se detiene y devuelve el `__interrupt__`, pero no guarda el
estado: `Command(resume=...)` no tiene de dónde seguir. Compilar con un checkpointer y pasar siempre `thread_id`.

**Reanudar con `invoke(input_nuevo)` en lugar de `invoke(Command(resume=...))`.** Arranca un turno nuevo y la
tool_call pendiente queda sin respuesta.

**Efectos antes de `interrupt()`.** Se repiten al reanudar.

**`sqlite3.connect` sin `check_same_thread=False`.** LangGraph puede usar la conexión desde otro hilo:
`ProgrammingError`.

**Subir el `recursion_limit` para "arreglar" el GraphRecursionError.** Esconde el bug (Ej. 5). Primero mirar la
historia del estado.

## 8. Qué temas se deben reforzar o repasar previo al ejercicio

- El loop de C1 completo: stopping rules, triage, memoria de corto plazo.
- Grafos dirigidos, ciclos y máquinas de estado (a nivel conceptual).
- `TypedDict` y `Annotated` en Python.
- Latencia real vs percibida (M1 · C1).

---

*Precios en `pricing.json` verificados en 2026-09; cambian con frecuencia. Verificar en las páginas oficiales de
pricing antes de cada cursada.*
