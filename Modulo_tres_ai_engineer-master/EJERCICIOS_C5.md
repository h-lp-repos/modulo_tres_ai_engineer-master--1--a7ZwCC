# Clase 5 · Ejercicios — Trazabilidad y evals de agentes

**Caso:** el sistema de OrbitAir sale a producción. Aparecen las preguntas que no se contestan mirando el código:
¿por qué esta respuesta tardó tanto? ¿cuánto cuesta atender a un pasajero (una conversación entera, no una
llamada)? ¿la versión nueva es mejor o sólo distinta? Hoy lo instrumentamos con **Langfuse**, evaluamos su
**trayectoria** sobre las trazas y ponemos el **gate** que decide si un cambio se despliega.

**Cómo se trabaja.** Los ejercicios completan `orbitair/trazas.py` (qué se registra) y `orbitair/evals.py` (cómo
se evalúa). La instrumentación del sistema ya está puesta (LLM, herramientas, nodos, workers, retrieval). Los
scripts de `c5/` corren y fallan justo donde falta completar.

**Antes de empezar.** `uv sync` y `python starter/resolver_hasta.py 4`. Para ver la UI de Langfuse: completar
`LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY` y `LANGFUSE_BASE_URL` en el `.env`. Sin claves, todo queda en
`results/c5_trazas/` y los ejercicios corren igual. Sin API key de OpenAI: `ORBITAIR_MOCK=1`.

**Datos.** `data/c5_conversaciones.jsonl`: 10 conversaciones (25 turnos). Cada turno es una consulta etiquetada de
C3, con su ruta, herramientas, parada y hechos esperados.

---

## Ejercicio 1 · Instrumentar y leer una traza — 20 min

**Consigna.** Decidir qué se registra de cada llamada al LLM (`registrar_llm`) y de cada herramienta
(`registrar_tool`), y correr una consulta adentro de una traza con sus atributos (`atender`). Leer la traza.

**Completar** `starter/orbitair/trazas.py` (`Observacion.registrar_llm`, `Observacion.registrar_tool`) y
`starter/orbitair/evals.py` (`atender`).

**Correr.**
```bash
python starter/c5/01_trazas.py
python starter/c5/01_trazas.py --id M-24
python starter/c5/01_trazas.py --id M-23
```

**Se espera ver.** El árbol de la traza: router, workers en paralelo, generations con tokens y costo, tools con
sus argumentos, retrieval con los fragmentos, síntesis; cuándo empezó y cuánto duró cada paso; los errores
marcados. Con Langfuse, el link a la traza.

**Para discutir.** ¿Por qué registrar las tool_calls que pidió el modelo y no sólo su texto? ¿Para qué sirven
`session_id`, `user_id` y los tags? ¿Cuál es el camino crítico de la latencia?

---

## Ejercicio 2 · Sesiones y costo por sesión — 15 min

**Consigna.** Correr las 10 conversaciones (cada una, una sesión) y completar `resumen_sesiones()`: turnos,
llamadas, tokens, costo y latencia por sesión. Abrir la sesión más cara hasta el turno que la explica.

**Completar** `starter/orbitair/evals.py` (`resumen_sesiones`).

**Correr.**
```bash
python starter/c5/02_sesiones.py
```

**Se espera ver.** Las sesiones ordenadas por costo, la mediana y el máximo, el costo por turno, una proyección
cada 1.000 conversaciones y la traza del turno más caro de la sesión más cara. Queda en `results/c5_sesiones.md`.

**Para discutir.** ¿Qué hace cara a una sesión: la cantidad de turnos o el tipo de consulta? ¿Por qué al negocio
le importa el costo por sesión y no por llamada?

---

## Ejercicio 3 · Evals de trayectoria — 25 min

**Consigna.** Reconstruir la trayectoria **desde la traza** (`trayectoria_de_traza`) y evaluarla contra lo
etiquetado (`evaluar_trayectoria`): ruta, herramientas, parada, hechos y éxito end-to-end. Cada métrica queda
como score sobre su traza.

**Completar** `starter/orbitair/evals.py` (`trayectoria_de_traza`, `evaluar_trayectoria`).

**Correr.**
```bash
python starter/c5/03_evals.py
```

**Se espera ver.** Por consulta: cada métrica y el éxito; el éxito end-to-end total y por tipo de consulta; cuántas
sesiones salieron bien de punta a punta; y las fallas con su traza. Queda en `results/c5_evals.md`.

**Para discutir.** ¿Por qué evaluar desde la traza y no desde lo que devuelve el sistema? Si cada turno sale bien
el 90% de las veces, ¿cuántas conversaciones de 3 turnos salen bien? ¿Qué hacemos si la etiqueta estaba mal?

---

## Ejercicio 4 · Datasets, experimentos y gate de regresión — 15 min

**Consigna.** Subir el dataset, correr tres versiones del sistema como experimentos y completar
`chequear_regresion()`: el gate que compara cada versión con la línea de base, en calidad, costo, latencia y
comportamiento.

**Completar** `starter/orbitair/evals.py` (`chequear_regresion`).

**Correr.**
```bash
python starter/c5/04_experimentos.py
python starter/c5/04_experimentos.py --gate v1-serie
```

**Se espera ver.** Las métricas de cada versión al lado de la línea de base y, para cada una, si pasa el gate y
por qué no. Con `--gate`, el código de salida (lo que usa CI). Queda en `results/c5_experimentos.md`.

**Para discutir.** Las tres versiones tienen el mismo éxito: ¿cuáles desplegarían? ¿Por qué un cambio de modelo
puede cambiar cómo se comportan las stopping rules? ¿Cómo se eligen las tolerancias?

---

## Ejercicio 5 · Diagnóstico con trazas — 15 min

**Consigna.** Alguien "mejoró" el prompt del worker de equipaje y lo despliega como v2. Correr el experimento,
pasarlo por el gate y, si no pasa, encontrar la causa bajando de las métricas a los casos y de los casos a las
trazas.

**Correr.**
```bash
python starter/c5/05_diagnostico.py
```

**Se espera ver.** Las métricas de v2 contra la línea de base, el resultado del gate, los casos que empeoraron y
qué tienen en común, y la traza donde se ve el problema.

**Para discutir.** ¿Por qué los evals de calidad no lo detectan? ¿Qué lo contiene y qué lo revela? ¿Qué métrica
agregarían al gate de su propio sistema después de ver esto?

---

## Criterios de aceptación

| Criterio | Cumple si... |
|---|---|
| Instrumentación | Cada consulta es una traza con sesión, usuario y tags; las generations tienen modelo, tokens, costo y tool_calls; las tools, resultado, intentos y nivel. |
| Sesiones | Se reporta el costo por sesión y se puede bajar de la sesión más cara a la observación que la explica. |
| Evals | La trayectoria se lee de la traza; se reportan éxito end-to-end por consulta y por sesión, con scores sobre cada traza. |
| Gate | Las versiones se comparan contra una línea de base fija en calidad, costo, latencia y comportamiento, con código de salida para CI. |
| Diagnóstico | La causa de una regresión se señala en una traza concreta, no se deduce de un promedio. |

*La solución completa está en `src/` — se muestra recién al cierre de cada ejercicio.*
