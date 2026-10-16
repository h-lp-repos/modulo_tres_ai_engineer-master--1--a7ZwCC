# Clase 3 · Ejercicios — Multiagente

**Caso:** el agente de OrbitAir de C2 tiene todas las herramientas y todas las políticas. Con consultas simples
anda bien, pero llegan cosas como "perdí la valija en el vuelo que llegó tarde, ¿qué me cubren?": dos problemas,
dos políticas, dos derechos que se responden por separado. Hoy armamos el router equipaje / cambios /
reembolsos: un **orquestador** que entiende qué partes tiene la consulta, tres **especialistas** que trabajan en
paralelo sobre los índices del M2, y una **síntesis**. Y al final, con datos: ¿valió la pena?

**Cómo se trabaja.** Los ejercicios completan `orbitair/workers.py` y `orbitair/orquestador.py`. Cada worker es el
grafo de C2 con otra configuración. Los scripts de `c3/` corren y fallan justo donde falta completar.

**Antes de empezar.** `python starter/resolver_hasta.py 2` (deja C1 y C2 resueltos). Sin API key: `ORBITAIR_MOCK=1`.

**Datos.** `data/c3_consultas_multiagente.jsonl`: 25 consultas etiquetadas con la **ruta** esperada (qué
especialistas tienen que intervenir), las herramientas, cómo termina y los hechos clave. 14 de un dominio, 2
fuera de alcance y 9 que cruzan dominios. El retrieval de los workers es la búsqueda híbrida del M2, con filtro
por documento.

---

## Ejercicio 1 · Workers — 20 min

**Consigna.** Completar `AgenteWorker.ejecutar()` (que `buscar_politica` use el retrieval del M2 filtrado por el
documento del worker, pasando por el triage) y `config_worker()` (las herramientas de cada worker y su fábrica).

**Completar** `starter/orbitair/workers.py` (`AgenteWorker.ejecutar`, `config_worker`).

**Correr.**
```bash
python starter/c3/01_workers.py
python starter/c3/01_workers.py --dominio equipaje --pregunta "¿Dónde está mi valija OA-582331?"
```

**Se espera ver.** Una misma pregunta de política buscada en todo el corpus y por cada worker (cada uno sólo ve
su documento), las herramientas de cada worker, y las consultas de un dominio resueltas por su especialista.
Queda en `results/c3_workers.md`.

**Para discutir.** ¿Qué gana un worker por saber menos? ¿Por qué el filtro va antes del top-k y no después?
¿Dónde está el mínimo privilegio: en el prompt o en el código?

---

## Ejercicio 2 · Routing por intención — 20 min

**Consigna.** Completar `rutear()` (una llamada al LLM con salida estructurada forzada: los dominios y la tarea de
cada uno) y `validar_ruteo()` (la salida del router es un contrato: validarla antes de usarla). Medir el router
sobre las 25 consultas.

**Completar** `starter/orbitair/orquestador.py` (`validar_ruteo`, `rutear`).

**Correr.**
```bash
python starter/c3/02_routing.py
python starter/c3/02_routing.py --id M-17
```

**Se espera ver.** Por consulta: la ruta esperada, la del router, y si sobró o faltó algún especialista.
Exactitud por tipo de consulta, precisión y recall por dominio, costo y latencia del ruteo, y qué hace la
validación con 5 salidas rotas. Queda en `results/c3_routing.md`.

**Para discutir.** ¿Qué error es más caro: mandar un especialista de más o uno de menos? ¿Por qué el router
devuelve una tarea y no sólo una etiqueta? ¿Tiene que ser un LLM?

---

## Ejercicio 3 · Orquestador y paralelismo — 25 min

**Consigna.** Completar `asignar_workers()` (un `Send` por intención, o fuera de alcance) y
`construir_orquestador()` (rutear → workers → sintetizar). Seguir una consulta de tres dominios nodo a nodo y
comparar los workers en paralelo con los workers en serie.

**Completar** `starter/orbitair/orquestador.py` (`asignar_workers`, `construir_orquestador`).

**Correr.**
```bash
python starter/c3/03_orquestador.py
python starter/c3/03_orquestador.py --id M-17
python starter/c3/03_orquestador.py --todas
python starter/c3/03_orquestador.py --mermaid
```

**Se espera ver.** Las intenciones del router, cuándo arrancó y terminó cada worker, la síntesis; la latencia en
paralelo vs en serie con el mismo costo; y con `--todas`, ruta y trayectoria de las 25 consultas. Queda en
`results/c3_orquestador.md` y `results/c3_orquestador.mmd`.

**Para discutir.** ¿Qué junta los resultados de los workers si terminan en cualquier orden? ¿El paralelismo
ahorra plata o tiempo? ¿Qué hace el sistema en M-24, donde una parte es de otra pasajera y la otra no?

---

## Ejercicio 4 · ¿Se justifica el grafo? — 15 min

**Consigna.** Correr las 25 consultas con tres arquitecturas que comparten modelo, herramientas y retrieval:
agente único, router (un solo especialista) y orquestador. Comparar por tipo de consulta y proyectar según
cuántas consultas cruzan dominios en la realidad.

**Correr.**
```bash
python starter/c3/04_se_justifica.py
python starter/c3/04_se_justifica.py --cruces 0.02
```

**Se espera ver.** Por arquitectura y tipo: éxito, llamadas al LLM, USD y latencia; y la proyección de éxito y
costo cada 1.000 consultas para una mezcla de tráfico. Queda en `results/c3_arquitecturas.md`.

**Para discutir.** ¿En qué consultas el orquestador no aporta nada y cuánto cuesta igual? ¿Qué porcentaje de
consultas cruzadas haría falta para que valga la pena? ¿Qué otros motivos (permisos, equipos, contexto) lo
justificarían aunque el éxito fuera el mismo?

---

## Ejercicio 5 · Human-in-the-loop en el multiagente — 10 min

**Consigna.** El worker de reembolsos puede iniciar el trámite (con aprobación, como en C2). Correr una consulta
que pide un reembolso y pregunta por una valija: ver dónde se detiene el sistema, qué pasa con el worker que ya
terminó y qué se repite al reanudar.

**Correr.**
```bash
python starter/c3/05_hitl_multiagente.py
python starter/c3/05_hitl_multiagente.py --decision rechazar
```

**Se espera ver.** El orquestador pausado con el pedido de aprobación del worker, la base sin cambios, el
resultado del otro worker ya guardado y, al reanudar, cuántas veces corrió cada worker y cuántas llamadas al LLM
hizo.

**Para discutir.** ¿Por qué el worker de equipaje no vuelve a correr? ¿Qué tiene que tener el orquestador para
que esto funcione? ¿Qué pasaría si dos workers pidieran aprobación a la vez?

---

## Criterios de aceptación

| Criterio | Cumple si... |
|---|---|
| Workers | Cada worker busca sólo en su documento, tiene sólo las herramientas de su dominio y resuelve las consultas de un dominio. |
| Routing | El router devuelve dominios y tareas validados; se reporta exactitud, de más y de menos sobre las 25 consultas. |
| Orquestador | Los workers corren en paralelo (se ve en los tiempos), sus resultados se juntan con un reducer y la síntesis sólo se paga con más de un worker. |
| ¿Se justifica? | La decisión de arquitectura se defiende con éxito, costo y latencia por tipo de consulta, y con la mezcla de tráfico. |
| HITL | La herramienta sensible nunca se ejecuta sin decisión, y al reanudar no se repite el trabajo de los workers. |

*La solución completa está en `src/` — se muestra recién al cierre de cada ejercicio.*
