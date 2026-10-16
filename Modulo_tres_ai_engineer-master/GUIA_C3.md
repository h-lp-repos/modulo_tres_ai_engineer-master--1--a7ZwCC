# Clase 3 — Multiagente · Hands-on OrbitAir

**AI Engineering 2.0 · M3 — Agentes y Orquestación · Track espejo del instructor**

> Regla de no-spoiler: todo lo que se resuelve acá es sobre **OrbitAir** (aerolínea). El estudiante
> transfiere la técnica a su Nubbix Desk o Vaulta Desk por su cuenta. Nada de este repo menciona ni
> resuelve el track del alumno.

> Esta guía es sólo para el instructor. La consigna que se proyecta en clase está en `EJERCICIOS_C3.md`.

## 1. Objetivo de aprendizaje de la clase

Al terminar, el estudiante puede:

- Diseñar un sistema con el patrón **orquestador-workers**: un orquestador que reparte la consulta y workers
  especializados (prompt, herramientas y retrieval acotados a un dominio).
- Implementar **routing por intención** multi-etiqueta con salida estructurada, validarla como un contrato y
  medirla como un clasificador (exactitud, de más, de menos).
- Correr workers **en paralelo** con `Send` de LangGraph, juntar sus resultados con un reducer y sintetizar una
  sola respuesta; medir qué cambia en latencia y qué no en costo.
- Decidir **con datos** cuándo el grafo multiagente se justifica y cuándo es sobre-ingeniería frente al agente
  único de C2.
- Mantener las garantías de C2 adentro del multiagente: la aprobación humana de un worker pausa todo el sistema
  y se reanuda sin repetir trabajo.

## 2. Consigna

> El agente de C2 tiene todas las herramientas y todo el corpus. Con consultas simples anda bien. Pero llegan
> cosas como "perdí la valija en el vuelo que llegó tarde, ¿qué me cubren?": son **dos** problemas (equipaje y
> asistencia por demora), con dos políticas distintas, que se responden por separado (POL-EQ-01 §7.4 lo dice
> explícitamente). Hoy armamos el router equipaje / cambios / reembolsos completo: un orquestador que entiende
> qué partes tiene la consulta, tres especialistas que trabajan **en paralelo** sobre los índices del M2, y una
> síntesis. Y al final, la pregunta incómoda: **¿valió la pena?**

**Ejercicio 1 — Workers.** `AgenteWorker.ejecutar()` y `config_worker()`: el grafo de C2 especializado por
dominio, con su retrieval filtrado por documento y sus herramientas mínimas.

**Ejercicio 2 — Routing por intención.** `validar_ruteo()` y `rutear()`: salida estructurada forzada, validada
como contrato; medir el router sobre las 25 consultas etiquetadas.

**Ejercicio 3 — Orquestador y paralelismo.** `asignar_workers()` (un `Send` por intención) y
`construir_orquestador()`. Recorrido nodo a nodo y paralelo vs en serie.

**Ejercicio 4 — ¿Se justifica el grafo?** Correr y leer: agente único vs router vs orquestador, por tipo de
consulta, con costo y latencia; proyectar según la mezcla de tráfico.

**Ejercicio 5 — Human-in-the-loop en el multiagente.** Correr y leer: el worker de reembolsos pide aprobación
mientras el de equipaje ya terminó.

## 3. Insumo / dataset de inicio

- C1 y C2 resueltos: `python starter/resolver_hasta.py 2`. Los workers **son** el grafo de C2
  (`construir_grafo`) con otra configuración: no se escribe un agente nuevo.
- **Dataset nuevo: `data/c3_consultas_multiagente.jsonl`** — 25 consultas etiquetadas con la **ruta** esperada
  (`dominios`), además de lo que ya tenía C1 (herramientas, parada, hechos): 14 de un dominio, 2 fuera de
  alcance y **9 que cruzan dominios** (incluida "perdí la valija OA-640212 en el OA0761, que llegó tarde", la
  del track). Reusa 9 consultas de C1 con su ruta. Dos campos nuevos: `opcionales` (herramientas que no es error
  usar) y hechos con alternativas (`"ciclos|60 dias"`). Es el dataset de evals de C5.
- **Retrieval del M2** (`orbitair/retrieval.py`, ya resuelto): búsqueda híbrida (embeddings
  `text-embedding-3-small` + BM25 + RRF) con **filtro por documento**, con el mismo contrato que
  `buscar_politica` de C1-C2. Índice local en `results/c3_indice_*.npz` (con la API real: una llamada de
  embeddings la primera vez, ~USD 0,0003).
- Los dominios son las categorías del contrato del M1 (equipaje / cambios / reembolsos / otros), cada uno con
  su documento del M2 (`workers.DOMINIOS`).
- Cambio en C2 (aditivo, no rompe nada): `ConfigAgente.fabrica` dice qué clase de agente arman los nodos. Por
  defecto, el `Agente` de C1; en C3, el `AgenteWorker`.

**Setup previo:** nada nuevo para instalar (LangGraph ya está desde C2). Sin API key: `ORBITAIR_MOCK=1`. Los
números de esta guía son del mock. **Pendiente: re-correr con la API real antes de la cursada** (costo
estimado de la clase completa: menos de USD 0,10).

**Qué hace el mock en C3.** El router es un clasificador por **palabras clave** (`mock_orquestador.py`): parte
la consulta en cláusulas y asigna dominios por vocabulario. En este dataset acierta 25/25, así que **en mock el
Ej. 2 muestra el mecanismo, no la calidad del router**: los errores de routing interesantes (M-12 a "cambios"
por "demorado", over-routing por una palabra de otro dominio) aparecen con el LLM. La síntesis del mock
concatena las respuestas sin repetir oraciones.

## 4. Resolución paso a paso

Tiempos sugeridos para 90 minutos: 20 + 20 + 25 + 15 + 10.

### Paso 1 · Workers sobre los índices del M2 (20 min)

```bash
python starter/resolver_hasta.py 2
python starter/c3/01_workers.py
python starter/c3/01_workers.py --dominio equipaje --pregunta "¿Dónde está mi valija OA-582331?"
```

1. Pizarrón: el patrón. Un orquestador que **no responde**, sólo reparte; workers que **no se ven entre sí**,
   cada uno con su contexto. Un worker = el grafo de C2 + tres restricciones: prompt de especialista, menos
   herramientas, retrieval filtrado. Mostrar la tabla del docstring de `workers.py`.
2. Completar `AgenteWorker.ejecutar()`: si la herramienta no es `buscar_politica`, lo de C1 (`super()`); si es,
   validar los argumentos y llamar a `retrieval.buscar(..., documentos=self.documentos)` **pasando por el
   triage** (`ejecutar_con_triage`). El modelo ve la misma herramienta; cambia lo que hay detrás.
3. Completar `config_worker()`: herramientas del dominio + `buscar_politica` (+ acciones sólo si se piden) y
   `fabrica=partial(AgenteWorker, dominio=...)`.
4. **Parte A** — "¿Me devuelven la plata si me cancelan el vuelo?": el BM25 global de C1-C2 trae
   `POL-EQ-01#3.3, POL-RE-01#3.1, POL-EQ-01#7.4` (¡dos de equipaje!); cada worker trae **sólo su documento**
   (reembolsos: `POL-RE-01#4`, el reembolso involuntario). El filtro va **antes** del top-k: no es "buscar en
   todo y descartar" (eso puede dejar 0 resultados).
5. Las herramientas por worker: el de equipaje **no tiene** `iniciar_reembolso`; el de reembolsos la tiene sólo
   con `acciones=True`. Mínimo privilegio en el código, no en el prompt (como el `pasajero_id` de C1).
6. **Parte B** — las 14 consultas de un dominio, cada una directo a su worker (routing "perfecto", a mano):
   **14/14** (mock). Dejar planteado: ¿quién decide a qué worker va? → Ej. 2.

### Paso 2 · Routing por intención (20 min)

```bash
python starter/c3/02_routing.py
python starter/c3/02_routing.py --id M-17
```

1. Pizarrón: el router es el **triage del M1** con dos cambios: multi-etiqueta (una consulta, varios dominios)
   y devuelve también la **tarea** de cada worker (con los códigos que necesita).
2. Completar `rutear()`: una llamada con `spec_router()` y `tool_choice` **forzado**
   (`{"type": "function", "function": {"name": "rutear_consulta"}}`): el modelo no puede contestar con texto.
   Es la salida estructurada del M1 · C3 con function calling.
3. Completar `validar_ruteo()`: el output del router es un **contrato**. Dominio inventado → se descarta;
   repetido → se une; "otros" junto a dominios reales → se descarta; nada válido → `otros` (fail closed).
   La Parte B del script lo prueba con 5 salidas rotas.
4. Leer las métricas. Por consulta: exacta, **de más** (over-routing: un worker que no hacía falta → costo y
   latencia) y **de menos** (under-routing: una parte queda sin responder → el error caro, porque el sistema
   contesta con confianza la mitad de la pregunta). Por dominio: precisión y recall (cada dominio es un
   clasificador sí/no).
5. En mock: 25/25, USD 0,00044 y 0,06 s por ruteo. **Con la API real** mirar M-12 ("demorado… ¿algo para
   comer?" es reembolsos: la asistencia está en POL-RE-01 §8) y M-14 ("se me rompió una rueda… ¿hasta cuándo
   reclamo?" es equipaje, no reembolsos).
6. `--id M-17`: lo que propuso el modelo y lo que quedó validado. La tarea de reembolsos trae el código del
   vuelo aunque en la consulta esté en la otra frase: lo pide el prompt del router.

### Paso 3 · Orquestador y paralelismo (25 min)

```bash
python starter/c3/03_orquestador.py
python starter/c3/03_orquestador.py --id M-17
python starter/c3/03_orquestador.py --todas
python starter/c3/03_orquestador.py --mermaid
```

1. Pizarrón: el grafo del docstring de `orquestador.py`. Dos estados distintos: el del orquestador
   (`EstadoOrquestador`) y el de cada tarea (`TareaWorker`), que es lo que viaja en cada `Send`.
2. Completar `asignar_workers()`: un `Send("worker", {...})` por intención; si no hay dominios con worker,
   `"fuera_de_alcance"` (responde sin LLM: no todo necesita un modelo).
3. Completar `construir_orquestador()`: `rutear` → (`asignar_workers`) → `worker` → `sintetizar`. Con `Send`,
   `add_conditional_edges` lleva la lista de destinos posibles.
4. El **reducer**: `resultados: Annotated[list, operator.add]`. Cada worker devuelve su resultado y LangGraph los
   junta. Sin reducer, dos workers escribiendo la misma clave en el mismo paso es un `InvalidUpdateError`
   (ver §7). Lo mismo con `costo_usd` y `llamadas_llm`: el costo de la consulta es la suma de todos los agentes.
5. **Parte A** (M-23, tres dudas): los tres workers arrancan a los ~0,33 s y terminan a los ~0,48 s, juntos;
   la síntesis espera a los tres. Con un solo worker, `sintetizar` pasa la respuesta directo (no se paga una
   síntesis que no sintetiza nada).
6. **Parte B** — 9 cruces, paralelo vs en serie: **misma respuesta en 9/9, mismo costo, 0,41 s vs 0,58 s** (mock,
   1,4×). Con la API real cada llamada tarda 1-3 s y cada worker hace 2-3: la diferencia pasa a ser de varios
   segundos por consulta. El paralelismo **no ahorra plata**: ahorra espera.
7. `--todas`: el sistema completo, **ruta correcta en 25/25 y ruta + trayectoria + hechos en 25/25** (mock).
   M-24 es la falla parcial: la reserva es ajena (error duro en el worker de cambios → deriva) y la valija es
   propia. El sistema contesta la valija **y** deriva lo otro. ¿Es lo que queremos? (§6).

### Paso 4 · ¿Se justifica el grafo? (15 min)

```bash
python src/c3/04_se_justifica.py
python src/c3/04_se_justifica.py --cruces 0.02
```

Nada que completar: es la discusión de la clase, con datos.

1. Tres arquitecturas con el **mismo** modelo, herramientas y retrieval: agente único (el grafo de C2 con todo),
   router (un solo worker, sin síntesis) y orquestador. La única variable es la arquitectura.
2. Leer la tabla (mock):

   | arquitectura | un dominio | cruce | LLM/consulta (un dominio · cruce) | USD/consulta (un dominio · cruce) |
   |---|---|---|---|---|
   | agente único | 14/14 | 6/9 | 2,1 · 3,1 | 0,00122 · 0,00226 |
   | router | 14/14 | 5/9 | 3,1 · 3,9 | 0,00161 · 0,00250 |
   | orquestador | 14/14 | **9/9** | 3,1 · 7,4 | 0,00161 · **0,00457** |

3. Lo que dicen los números: en consultas de **un dominio** el orquestador no acierta más y cuesta **+32%** (la
   llamada del router). En **cruces** gana 3 de 9, pero cuesta **el doble** (dos workers + síntesis). El router
   puro es lo peor de los dos mundos en este dataset: paga el ruteo y pierde las partes que no rutea.
4. Mirar **cómo** falla el agente único en los cruces: M-23 (busca la política **una sola vez**, guiado por la
   demora del vuelo: la duda del reembolso a débito queda sin responder), M-24 (un error duro corta **toda** la
   consulta: no le dice dónde está su valija), M-20 (consulta un vuelo que nadie preguntó). En mock es el guion;
   con la API real el modelo a veces hace dos búsquedas, a veces no: por eso se mide.
5. La proyección: el dataset tiene 9/25 cruces a propósito. Con 10% de cruces el orquestador da 100% vs 97% a
   USD 1,90 vs 1,33 cada 1.000 consultas; con `--cruces 0.02`, la diferencia de éxito casi desaparece y el
   costo sigue. **La decisión depende de la mezcla real de tráfico**: medirla antes (en el M1 ya se clasifica).
6. Criterios para llevarse (pizarrón): el grafo multiagente se justifica cuando (a) una fracción relevante de
   consultas tiene partes **independientes** de dominios distintos, (b) los dominios necesitan herramientas o
   permisos distintos (mínimo privilegio), (c) el contexto de un agente único ya no entra o se confunde (muchas
   herramientas, muchos documentos), o (d) hay equipos distintos dueños de cada dominio. Si no: agente único
   con buenas herramientas. **Empezar simple y agregar agentes cuando un número lo pida.**

### Paso 5 · Human-in-the-loop en el multiagente (10 min)

```bash
python src/c3/05_hitl_multiagente.py
python src/c3/05_hitl_multiagente.py --decision rechazar
```

Nada que completar.

1. "Quiero el reembolso de mi reserva M4TR88, que me cancelaron. ¿Y dónde está mi valija OA-582331?" → workers
   de reembolsos (con `acciones=True`) y de equipaje, en paralelo.
2. El worker de reembolsos llega a `iniciar_reembolso` y su nodo `aprobacion` (el de C2) llama a `interrupt()`.
   El interrupt **sube** al orquestador: `get_state()` muestra la tarea `worker` pausada y el pedido del
   supervisor. La base no tiene reembolsos.
3. El worker de equipaje ya terminó: su resultado **ya está guardado** en el checkpoint.
4. Al reanudar (`Command(resume=...)`): equipaje **no se vuelve a ejecutar** (1 corrida); el nodo del worker de
   reembolsos sí se re-ejecuta, pero su subgrafo retoma desde la pausa: **una sola llamada más al LLM** (4 → 5),
   no repite las herramientas. `RE-11040 USD 412 solicitado`.
5. Por qué funciona: el subgrafo del worker se compila **sin checkpointer propio** y hereda el del orquestador
   (`grafo_worker` en `orquestador.py`). Sin checkpointer en el orquestador, no hay desde dónde reanudar (C2).

## 5. Link del repositorio con la solución

`[completar con la URL del repo de la cátedra]`

## 6. Preguntas posibles y respuestas sugeridas

**¿Por qué no un "supervisor" que llama a los workers como herramientas (o `langgraph-supervisor`)?**
Es la otra forma clásica: un LLM supervisor que en un loop decide "ahora llamo al de equipaje, ahora al de
reembolsos". Es más flexible (puede encadenar: la respuesta de uno cambia lo que le pide al otro), pero es
secuencial y cada vuelta del supervisor es otra llamada con todo el historial. Acá las partes son
**independientes**: alcanza con planificar una vez y repartir en paralelo. Si las partes dependen entre sí, el
supervisor gana.

**¿Y handoffs (un agente le pasa la conversación a otro, estilo swarm)?**
Sirven cuando la conversación **cambia** de dominio ("ya está lo de la valija; ahora quiero cambiar el vuelo").
El orquestador sirve cuando una **misma** consulta tiene varias partes. No son excluyentes.

**¿El router tiene que ser un LLM?**
No. Puede ser el clasificador del M1, embeddings contra ejemplos por dominio, o reglas (el mock es eso). Un LLM
entiende mejor las consultas raras y escribe la tarea de cada worker; un clasificador es más barato y rápido.
Medir los dos con el mismo dataset (Ej. 2) y decidir con el número.

**¿Por qué la síntesis es otra llamada? ¿No alcanza con concatenar?**
Concatenar repite saludos, mezcla el orden y no resuelve tensiones entre respuestas. Pero cuesta: se paga sólo
cuando hay más de un worker. Si los workers contradicen (uno dice "sí corresponde", otro "no"), la síntesis no
debería elegir: el prompt le prohíbe agregar datos; en producción, marcar el caso para revisión.

**¿Los workers comparten memoria?**
No, y es a propósito: cada uno ve sólo su tarea (aislamiento de contexto: menos tokens y menos confusión). El
orquestador sólo recibe sus respuestas. Si un worker necesita un dato de otro, es una dependencia: o el router
le pasa el código en la tarea, o el diseño necesita un supervisor.

**¿Qué hacemos con la falla parcial (M-24)?**
Fail closed **por parte**: el worker que pegó el error duro deriva su parte, sin detalles; el resto se responde.
Alternativa más conservadora: si cualquier parte da error de permisos, derivar todo (se pierde la respuesta
legítima). Es una decisión de producto: explicitarla y testearla (en el dataset, M-24 espera `error_duro` y el
hecho de la valija).

**¿Paralelo con `Send` o con `asyncio`/threads a mano?**
`Send` deja el paralelismo en el grafo: el checkpointer guarda el resultado de cada worker, el stream muestra
cuál terminó, y el interrupt de uno no tira el trabajo de los otros (Ej. 5). A mano habría que construir todo eso.

**¿Qué pasa si dos workers piden aprobación a la vez?** (la pregunta abierta del Ej. 5)
Los dos `interrupt()` quedan pendientes juntos: `get_state(config).tasks` trae una tarea por worker, cada una con
su `Interrupt` (y su `id`). Se reanudan en una sola llamada con un mapa id → decisión:
`grafo.invoke(Command(resume={i.id: decision_para(i) for t in estado.tasks for i in t.interrupts}), config)`.
Un `Command(resume=valor)` con un único valor sirve cuando hay **un** interrupt pendiente (el caso del script). Se
probó con la misma estructura del orquestador (Send + subgrafo con interrupt): cada worker recibe su decisión.
En la UI del supervisor eso es una bandeja con varias aprobaciones de la misma consulta.

**¿Cuánto cuesta "partir" en agentes?**
Cada worker repite su system prompt y sus herramientas (tokens de entrada) y hace al menos una llamada; la
consulta cruzada pasó de ~3 a ~7 llamadas. En el M1 el costo era por llamada; en un multiagente es **por
consulta** (C5 lo mide por sesión en Langfuse).

## 7. Errores comunes y cómo resolverlos en vivo

**Workers en paralelo escribiendo una clave sin reducer.**
`InvalidUpdateError: At key 'resultados': Can receive only one value per step. Use an Annotated key to handle
multiple values.` → `Annotated[list, operator.add]` (y lo mismo para el costo).

**`add_conditional_edges` con Send sin la lista de destinos.**
El grafo corre, pero el diagrama dibuja `rutear → END` y el worker desconectado. Pasar
`["worker", "fuera_de_alcance"]`.

**Pasarle al worker el estado del orquestador.**
El `Send` lleva **su** estado (`TareaWorker`): dominio, tarea y lo mínimo. Si se manda todo, el worker ve las
intenciones de los otros y responde de más.

**Filtrar el retrieval después del top-k.**
"Busco en todo y me quedo con los de mi documento": si los 3 mejores eran de otro documento, el worker se queda
sin nada. El filtro va adentro de la búsqueda (`mascara` en BM25, `-inf` en el coseno).

**Router sin validar.**
Un dominio inventado ("vuelos") sin validación hace `KeyError` en `DOMINIOS[...]` o, peor, un worker que no
existe. `validar_ruteo` primero, siempre.

**Darle a cada worker todas las herramientas "por las dudas".**
Se pierde el mínimo privilegio (el de equipaje podría iniciar un reembolso) y el worker se dispersa.

**Comparar arquitecturas cambiando dos cosas a la vez.**
Si el agente único usa BM25 y los workers la híbrida, la diferencia no se sabe de dónde sale. Por eso el
generalista del Ej. 4 es `config_worker(None)`: el mismo retrieval.

## 8. Qué temas se deben reforzar o repasar previo al ejercicio

- El grafo de C2: estado, nodos, edges condicionales, checkpointer, `interrupt`.
- El contrato de triage del M1 (categorías) y la salida estructurada con function calling (M1 · C3).
- Búsqueda híbrida y filtros por metadatos (M2 · C3).
- Concurrencia a nivel conceptual: latencia en paralelo = la del más lento; costo = la suma.

---

*Precios en `pricing.json` verificados en 2026-09; cambian con frecuencia. Verificar en las páginas oficiales de
pricing antes de cada cursada.*
