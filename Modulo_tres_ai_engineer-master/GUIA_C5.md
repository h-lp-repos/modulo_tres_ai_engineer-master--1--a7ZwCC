# Clase 5 — Trazabilidad y evals de agentes · Hands-on OrbitAir

**AI Engineering 2.0 · M3 — Agentes y Orquestación · Track espejo del instructor**

> Regla de no-spoiler: todo lo que se resuelve acá es sobre **OrbitAir** (aerolínea). El estudiante
> transfiere la técnica a su Nubbix Desk o Vaulta Desk por su cuenta. Nada de este repo menciona ni
> resuelve el track del alumno.

> Esta guía es sólo para el instructor. La consigna que se proyecta en clase está en `EJERCICIOS_C5.md`.

## 1. Objetivo de aprendizaje de la clase

Al terminar, el estudiante puede:

- **Instrumentar** un sistema multiagente con el modelo de Langfuse: trazas, observaciones anidadas (spans,
  generations, tools), **sesiones** y **scores**, y leer una traza para entender qué hizo el sistema.
- Medir el **costo por sesión** (una conversación, no una llamada) y bajar de la sesión cara al turno y a la
  observación que la explica.
- Diseñar **evals de trayectoria** que se calculan **desde la traza**: ruta, herramientas, parada, hechos y
  **éxito end-to-end**, por consulta y por sesión.
- Armar un **dataset de conversaciones**, correr **experimentos** que comparan versiones y poner un **gate de
  regresión** (calidad, costo, latencia y comportamiento) que se pueda correr en CI.

## 2. Consigna

> El sistema de OrbitAir ya enruta, consulta, pide aprobación y habla MCP. Mañana sale a producción y aparecen
> las preguntas que no se contestan mirando el código: ¿por qué esta respuesta tardó 9 segundos? ¿cuánto nos
> cuesta atender a un pasajero, no una llamada? ¿la versión nueva del prompt es mejor o sólo distinta? Hoy lo
> instrumentamos con Langfuse, armamos los evals de trayectoria sobre las trazas y ponemos el gate que decide si
> un cambio se despliega.

**Ejercicio 1 — Instrumentar.** `Observacion.registrar_llm()`, `Observacion.registrar_tool()` y `atender()`: qué
se registra de cada llamada y de cada herramienta, y qué atributos lleva la traza. Leer una traza.

**Ejercicio 2 — Sesiones.** `resumen_sesiones()`: 10 conversaciones (25 turnos), costo y latencia por sesión, y
la sesión más cara abierta hasta el turno que la explica.

**Ejercicio 3 — Evals de trayectoria.** `trayectoria_de_traza()` y `evaluar_trayectoria()`: la trayectoria
leída de la traza, los scores sobre cada traza, el éxito end-to-end por consulta y por sesión.

**Ejercicio 4 — Datasets, experimentos y gate.** `chequear_regresion()`: tres versiones contra la línea de base;
el gate que se corre en CI.

**Ejercicio 5 — Diagnóstico con trazas.** Correr y leer: un deploy que pasa los evals de calidad y lo frena una
métrica de comportamiento; encontrar la causa en las trazas.

## 3. Insumo / dataset de inicio

- C1 a C4 resueltos: `python starter/resolver_hasta.py 4`.
- **El sistema a instrumentar** es el orquestador de C3 (router + workers en paralelo + síntesis).
- **Dataset de conversaciones nuevo: `data/c5_conversaciones.jsonl`** — 10 sesiones (1 a 3 turnos) armadas con
  las **25 consultas etiquetadas de C3**: cada turno es el id de un caso, así cada turno trae su ruta,
  herramientas, parada y hechos esperados. Es el "dataset de conversaciones" del temario, y el de C3 es su
  dataset de items (Ej. 4).
- **SDK `langfuse` 4.x** (sobre OpenTelemetry): `start_as_current_observation`, `propagate_attributes`,
  `create_score`, datasets y `run_experiment`. `uv sync` lo instala.
- Ya resuelto: la capa de trazas (`orbitair/trazas.py`: contexto, doble escritura, árbol en la terminal), la
  instrumentación de `llm.py`, de los nodos de los grafos de C2 y C3, de las herramientas y del retrieval, y el
  runner de experimentos.

**Doble escritura (decisión de diseño para explicar al empezar).** Cada traza se guarda **siempre** en local
(`results/c5_trazas/`) y, **si hay credenciales** (`LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`,
`LANGFUSE_BASE_URL` en el `.env`), también en Langfuse. Los evals leen de la copia local: la clase corre igual
con o sin cuenta, y con cuenta se muestra la UI (trazas, sesiones, scores, datasets y comparación de corridas).
Langfuse Cloud tiene plan gratuito; también se puede usar self-hosted cambiando la URL.

**Setup previo:** `uv sync`; para la UI, crear un proyecto en Langfuse Cloud y completar las tres variables del
`.env`. Sin API key de OpenAI: `ORBITAIR_MOCK=1`. Los números de esta guía son del mock, en modo local.

**Instrumentar sin ensuciar.** Fuera de una traza, toda la instrumentación es un no-op: C1 a C4 corren exactamente
igual (se verificó: mismas trayectorias, mismos costos). El contexto de la traza viaja en una `ContextVar` y llega
también a los workers que LangGraph corre en paralelo en otros hilos.

## 4. Resolución paso a paso

Tiempos sugeridos para 90 minutos: 20 + 15 + 25 + 15 + 15.

### Paso 1 · Instrumentar y leer una traza (20 min)

```bash
python starter/resolver_hasta.py 4
python starter/c5/01_trazas.py
python starter/c5/01_trazas.py --id M-24
python starter/c5/01_trazas.py --id M-23
```

1. Pizarrón: el modelo de datos del docstring de `trazas.py` — **sesión → traza → observaciones** (span, agent,
   generation, tool, retriever) **+ scores**. Es el de Langfuse y el de OpenTelemetry.
2. Mostrar dónde ya está la instrumentación (es poca y envuelve, no reescribe): `llm.completar_con_tools` abre
   una *generation*; el nodo `herramientas` de C2, una *tool* por llamada; `correr_worker`, un *agent* por
   worker; `retrieval.buscar`, un *retriever* con los ids de los fragmentos.
3. Completar `registrar_llm()`: modelo, tokens, **costo** y el output **con las tool_calls**. Sin las tool_calls,
   la traza muestra qué pasó pero no **por qué** el agente lo hizo.
4. Completar `registrar_tool()`: output, decisión del triage, intentos y **nivel** (ERROR para error duro,
   WARNING para reintento o error de entrada). El nivel es lo que permite filtrar "las trazas con problemas".
5. Completar `atender()`: la traza con `session_id`, `user_id` (el pasajero), `tags` y `metadata` (el caso del
   dataset, la versión). Sin esos atributos, las trazas no se pueden agrupar ni comparar.
6. Leer M-17 (mock): `rutear` → **dos workers que arrancan juntos** (0,36 s) → cada uno con sus generations, tools
   y el retrieval con los fragmentos → `sintetizar`. **8 llamadas al LLM, 9.842 tokens, USD 0,0050, 0,74 s.**
   Señalar cuál es el camino crítico (el worker más lento) y qué pesa más en tokens (el historial que se reenvía
   en cada vuelta: C1).
7. `--id M-24`: la tool `consultar_reserva` en **✗** con su estado, el nodo `escalar` y el otro worker que
   responde igual. El error se ve en un segundo.

### Paso 2 · Sesiones y costo por sesión (15 min)

```bash
python starter/c5/02_sesiones.py
```

1. Completar `resumen_sesiones()`: agrupar las trazas por `session_id` y sumar turnos, llamadas, tokens, costo,
   latencia, errores. Es la vista "Sessions" de Langfuse.
2. Leer la tabla (mock): 10 sesiones, **USD 0,064 en total, mediana USD 0,0057 por sesión, máxima USD 0,0129**
   (S-03, tres turnos de cancelaciones), **USD 0,0026 por turno**, proyección USD 6,44 cada 1.000 conversaciones.
3. Bajar de la sesión al turno: en S-03 el turno caro es M-19 (cruce cambios + reembolsos, 8 llamadas). Abrirlo:
   dos workers, cada uno con dos o tres generations. Lo que encarece una sesión es **la cantidad de turnos que
   cruzan dominios**, no la cantidad de turnos (S-07 tiene 3 turnos y es la más barata: dos son fuera de alcance,
   sin LLM de worker).
4. El costo de cada sesión queda como **score de sesión** (`costo_sesion_usd`). Con Langfuse, la UI permite
   ordenar sesiones por costo y por usuario.
5. Nota: el orquestador de C3 no tiene memoria entre turnos (C2 sí); las conversaciones del dataset tienen turnos
   autocontenidos. La sesión es una forma de **agrupar** trazas: no depende de cómo se guarde la memoria.

### Paso 3 · Evals de trayectoria sobre las trazas (25 min)

```bash
python starter/c5/03_evals.py
```

1. Pizarrón: evaluar un agente ≠ evaluar una respuesta. Dos agentes pueden decir lo mismo y uno haber consultado
   tres sistemas de más o haber llegado de casualidad. Y la trayectoria se lee **de la traza**: es lo que pasó,
   y es lo mismo que hay en producción (no un log armado para el eval).
2. Completar `trayectoria_de_traza()`: ruta (el output de `rutear`), herramientas (las *tool* en orden),
   parada y respuesta (la raíz), llamadas, costo, `cortes_por_regla` (nodos `cierre`), errores de tools.
3. Completar `evaluar_trayectoria()`: ruta, herramientas, parada (con `chequear` de C1, que respeta `opcionales`),
   **hechos como fracción** (0..1, no todo-o-nada: se ve si mejora de a poco) y **éxito end-to-end** (las cuatro).
4. Leer (mock): **éxito end-to-end 25/25, sesiones exitosas 10/10, 4,5 llamadas y USD 0,0026 por consulta**. Con
   el guion todo pasa: decirlo explícitamente. Con la API real aparecen fallas (sobre todo de routing, C3 · Ej. 2):
   el script lista cada una con su traza y abre la primera.
5. **Sesión exitosa = todos sus turnos exitosos**: con 90% de éxito por turno, una sesión de 3 turnos sale bien
   ~73% de las veces. Es la métrica que siente el pasajero.
6. Cada métrica queda como **score** sobre su traza (220 scores en `results/c5_scores.jsonl`). En Langfuse: filtrar
   "exito = 0", ordenar por costo, graficar por versión.
7. ¿Y la calidad del texto? Para eso está el LLM-as-judge del M1 · C5 (y la faithfulness del M2 · C5): es otro
   score más sobre la misma traza. Acá nos concentramos en lo propio de un agente: la trayectoria.

### Paso 4 · Datasets, experimentos y el gate (15 min)

```bash
python starter/c5/04_experimentos.py
python starter/c5/04_experimentos.py --gate v1-serie ; echo $?
```

1. El dataset: las 25 consultas como items `{input, expected_output, metadata}` (local; con Langfuse, un Dataset
   cuyos items van con id: subirlo dos veces no duplica). Un **experimento** corre una versión sobre todo el
   dataset; con Langfuse usa `dataset.run_experiment` y la corrida queda vinculada al dataset para compararla en
   la UI.
2. Completar `chequear_regresion()`: calidad → caída **absoluta**; costo, llamadas y latencia → suba **relativa**;
   conteos de comportamiento (`cortes_por_regla`) → suba **absoluta**. Tolerancias en `evals.TOLERANCIAS`.
3. Leer (mock), contra la línea de base v1:

   | versión | éxito | costo / consulta | p95 | cortes | gate |
   |---|---|---|---|---|---|
   | v1 (base) | 100% | USD 0,00258 | 0,50 s | 0 | pasa |
   | v1-serie | 100% | USD 0,00258 | 0,68 s (+36%) | 0 | **no pasa: latencia** |
   | v1-gpt-4.1 | 100% | USD 0,01289 (**+400%**) | 0,50 s | 1 | **no pasa: costo y cortes** |

4. Lo que enseña cada una: **v1-serie** tiene la misma calidad y el mismo costo, pero es más lenta: el gate no es
   sólo de calidad. **v1-gpt-4.1** no mejora nada en este dataset y cuesta 5 veces más; además, un worker de M-22
   terminó cortado por la regla de **presupuesto** de C1 (USD 0,01 por turno): ese presupuesto se calibró para
   el modelo chico. Cambiar de modelo cambia los umbrales.
5. `--gate <run>` sale con código 1 si hay regresión: es el paso de CI antes de desplegar (los umbrales de
   regresión del M1 · C5, ahora para un agente). En mock la latencia es simulada (~50 ms por llamada): el gate de
   latencia hay que calibrarlo con la API real.

### Paso 5 · Diagnóstico con trazas (15 min)

```bash
python src/c5/05_diagnostico.py
```

Nada que completar.

1. El "deploy" v2: el worker de equipaje con el prompt que "siempre da el estado definitivo de la valija" (el
   prompt ingenuo de C1 · Ej. 3, ahora adentro de un worker).
2. Las métricas (mock): **calidad igual (100%), costo casi igual (+0,5%), llamadas 4,52 → 4,68, cortes por regla
   0 → 6**. El gate lo frena **sólo** por `cortes_por_regla`. Preguntar: ¿qué hubiera pasado sin esa métrica?
   (pasaba: las stopping rules de C1 contienen el daño y la respuesta no cambia).
3. Bajar a los casos: los que empeoraron (M-23, M-24, M-06, M-05) **todos pasan por equipaje**.
4. Abrir la traza de M-23: en el worker de equipaje, `rastrear_valija("OA-582331")` **dos veces** con los mismos
   argumentos y el nodo `cierre` (cortado por la regla "repetida"). El diagnóstico sale de la traza: el prompt hace
   volver a consultar un estado que no va a cambiar.
5. Cierre del módulo: **la observabilidad no reemplaza a las stopping rules** (C1 contuvo el daño) **ni las
   stopping rules a la observabilidad** (sin trazas, esto era "subió un poco la factura"). Lo que se mide define
   lo que se ve: un gate sólo de calidad hubiera desplegado v2.

## 5. Link del repositorio con la solución

`[completar con la URL del repo de la cátedra]`

## 6. Preguntas posibles y respuestas sugeridas

**¿Por qué no usamos el `CallbackHandler` de Langfuse para LangChain/LangGraph?**
Traza los nodos del grafo automáticamente, pero las llamadas al modelo se hacen con nuestro cliente propio (decisión
de C2), que el handler no ve como generations. Instrumentar a mano en tres puntos (LLM, tools, nodos) da control
sobre qué se registra y deja la misma traza con o sin LangChain. Con `ChatOpenAI`, el handler sería la opción
rápida.

**¿Qué pasa con los datos sensibles en las trazas?**
Las trazas tienen la consulta del pasajero, códigos de reserva y, en los errores, detalles internos (M-24 muestra
"la reserva K7PQ2M no pertenece al pasajero P-1001"). Es útil para operar y es PII (M1 · C4). Langfuse permite una
función de `mask` en el cliente para enmascarar antes de enviar; además, controlar quién accede al proyecto y la
retención. Lo que **no** se hace es dejar de trazar.

**¿Cada cuánto se corren los evals? ¿Sobre qué?**
El dataset (offline) en cada cambio, como gate de CI. En producción, sobre una muestra de trazas reales (online),
con evaluadores que no necesitan etiqueta (costo, cortes por regla, errores, LLM-as-judge) y alimentando el
dataset con los casos nuevos que fallan.

**¿Por qué el éxito end-to-end exige todo (ruta, herramientas, parada, hechos)?**
Porque cualquiera de las cuatro que falle es una mala experiencia o un riesgo (consultar de más es costo; consultar
de menos es responder sin datos; parar mal es colgarse o derivar sin motivo). Las métricas parciales sirven para
diagnosticar **dónde** falla; el éxito end-to-end, para decidir.

**¿Y si la etiqueta está mal?**
Pasa. Por eso el script de evals lista las fallas con su traza: leerla antes de concluir. Si el agente tenía razón,
se corrige el dataset (y se versiona): el dataset también es código.

**¿Cuánto cuesta la observabilidad?**
En tokens, nada (no hay llamadas extra). En latencia, el SDK manda en segundo plano (por eso `trazas.cerrar()`
hace `flush` al terminar). En plata, el plan de Langfuse y el almacenamiento: muestrear en producción si el volumen
es alto.

**¿Sesión en Langfuse = memoria de la conversación?**
No: la sesión agrupa trazas para verlas y medirlas juntas. La memoria es lo que el sistema le vuelve a mandar al
modelo (C1 · Ej. 5, checkpoints de C2). Pueden coincidir (thread_id como session_id) pero son cosas distintas.

## 7. Errores comunes y cómo resolverlos en vivo

**No ver nada en Langfuse.**
El SDK manda en segundo plano: en un script corto, sin `flush` al final, el proceso termina antes de mandar.
`trazas.cerrar()` lo hace. Verificar las tres variables del `.env` (y la región: `cloud.langfuse.com` vs
`us.cloud.langfuse.com`).

**Atributos de traza puestos tarde.**
`session_id` y `user_id` se propagan a las observaciones creadas **después** de `propagate_attributes`: ponerlos al
abrir la traza (lo hace `trazas.traza`). Si no, el costo por sesión de Langfuse no suma las primeras llamadas.

**Evaluar con el estado en memoria en lugar de la traza.**
Funciona en el script y no sirve en producción, donde sólo hay trazas. La trayectoria se lee de la traza.

**Medir sólo calidad.**
v1-serie, v1-gpt-4.1 y v2 tienen 100% de éxito. Sin costo, latencia y comportamiento en el gate, las tres pasan.

**Comparar corridas con datasets distintos.**
La línea de base y la versión nueva tienen que correr sobre los mismos items (por eso el dataset se versiona y los
items tienen id).

**Tolerancias de cero en métricas ruidosas.**
Con la API real, la latencia y hasta la ruta varían entre corridas: tolerancia 0 hace que el gate falle siempre.
Calibrarlas corriendo la línea de base 2-3 veces.

## 8. Qué temas se deben reforzar o repasar previo al ejercicio

- Evals del M1 · C5 (dataset etiquetado, umbrales de regresión) y del M2 · C5 (retrieval vs generación).
- El orquestador de C3 y las stopping rules de C1 (el Ej. 5 depende de ellas).
- Percentiles (p50, p95) y la diferencia entre métricas por llamada, por consulta y por sesión.
- Conceptos de observabilidad: traza, span, contexto; qué es OpenTelemetry a nivel conceptual.

---

*Precios en `pricing.json` verificados en 2026-09; cambian con frecuencia. Verificar en las páginas oficiales de
pricing antes de cada cursada.*
