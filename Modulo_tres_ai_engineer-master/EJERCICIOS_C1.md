# Clase 1 · Ejercicios — Anatomía de un agente · loop engineering

**Caso:** el RAG del M2 responde con las políticas de OrbitAir, pero muchas consultas necesitan **datos**: "¿cómo
viene el OA1203?", "¿dónde está mi valija?", "me cancelaron el vuelo, ¿me corresponde algo?". Hoy escribimos a
mano, sin framework, el agente que consulta los sistemas de OrbitAir (vuelos, valijas, reservas) y las políticas,
y le ponemos los bordes que lo hacen confiable: cuándo parar, qué hacer cuando algo falla y qué recordar.

**Cómo se trabaja.** Los ejercicios completan `orbitair/tools.py` (1), `orbitair/agente.py` (2 y 3),
`orbitair/errores.py` (4) y `orbitair/memoria.py` (5). Los scripts de `c1/` ya están escritos: corren y fallan
justo donde falta completar.

**Antes de empezar.** `uv sync` y `cp .env.example .env`. Sin API key: `ORBITAIR_MOCK=1` (el "modelo" es un guion
determinista: sirve para ver el loop, no para juzgar la calidad).

**Datos.** Base de operaciones mock (`data/ops/`: 60 vuelos, 122 reservas, 200 valijas, 40 reembolsos; "hoy" es
2026-10-01) y `data/c1_consultas_agente.jsonl`: 13 consultas de pasajeros etiquetadas por **trayectoria**
(herramientas esperadas, cómo debe terminar, hechos clave de la respuesta).

---

## Ejercicio 1 · Una vuelta, desarmada — 15 min

**Consigna.** Escribir la especificación de `consultar_vuelo` (lo que el modelo ve) y `ejecutar_tool()` (lo que
ejecuta nuestro código: validar la herramienta y sus argumentos, y agregar el pasajero de la sesión).

**Completar** `starter/orbitair/tools.py` (`spec_consultar_vuelo`, `ejecutar_tool`).

**Correr.**
```bash
python starter/c1/01_una_tool.py
python starter/c1/01_una_tool.py --id A-02 --crudo
```

**Se espera ver.** Tres consultas desarmadas en ① el modelo propone → ② ejecutamos → ③ el modelo responde. En una
no usa herramientas; en otra, después de la primera vuelta, pide otra herramienta. Al final, el punto de control.

**Para discutir.** ¿Quién ejecuta la herramienta? ¿Por qué la descripción es parte del prompt? ¿Qué pasaría si
`pasajero_id` fuera un argumento de `consultar_reserva`? ¿Por qué A-02 necesita más de una vuelta?

---

## Ejercicio 2 · El loop ReAct — 25 min

**Consigna.** Completar `Agente.correr()`: repetir razonar → actuar → observar hasta que el modelo responda sin
pedir herramientas. Correrlo sobre las 13 consultas y chequear la trayectoria de cada una.

**Completar** `starter/orbitair/agente.py` (`correr`).

**Correr.**
```bash
python starter/c1/02_loop_react.py
python starter/c1/02_loop_react.py --id A-02
```

**Se espera ver.** Por consulta: herramientas usadas (✓/✗ contra lo esperado), cómo terminó, hechos clave, pasos,
tokens y USD. Con `--id`, la traza completa: pensamiento → acción → observación. Queda en `results/c1_loop.md`.

**Para discutir.** ¿Qué consulta falla todavía y por qué? (pista: el triage es el Ej. 4). ¿Cuántos pasos usa la
consulta más larga? ¿Por qué los tokens de entrada crecen en cada paso?

---

## Ejercicio 3 · Colgar el loop y salvarlo — 20 min

**Consigna.** Con el prompt "de primer intento" y una valija en búsqueda (A-10), el loop no termina. Completar
`ReglasDeParada.evaluar()`: máximo de pasos, llamada repetida, presupuesto y tiempo.

**Completar** `starter/orbitair/agente.py` (`ReglasDeParada.evaluar`).

**Correr** (antes y después de completar).
```bash
python starter/c1/03_colgar_el_loop.py
python starter/c1/03_colgar_el_loop.py --traza
```

**Se espera ver.** Cuatro configuraciones (sin reglas · sólo max_pasos · reglas completas · prompt de producción)
con pasos, consultas a la valija, tokens y USD, y una proyección mensual. Queda en `results/c1_stopping_rules.md`.

**Para discutir.** ¿Por qué el costo crece más rápido que la cantidad de pasos? ¿Qué regla corta antes y cuál es
sólo una red de seguridad? Si las reglas lo salvan, ¿hace falta arreglar el prompt?

---

## Ejercicio 4 · Triage de errores — 15 min

**Consigna.** Completar `clasificar_error()` (reintentar / informar al modelo / abortar) y `ejecutar_con_triage()`
(reintentos con backoff; si se agotan, el error pasa a duro). Correr cinco escenarios con fallas inyectadas.

**Completar** `starter/orbitair/errores.py` (`clasificar_error`, `ejecutar_con_triage`).

**Correr.**
```bash
python starter/c1/04_errores.py
python starter/c1/04_errores.py --sin-triage
```

**Se espera ver.** Por escenario (timeouts, código de otra aerolínea, reserva ajena, base caída): decisión,
intentos, pasos de LLM y cómo terminó. Con `--sin-triage`, lo mismo cuando todo error vuelve al modelo.

**Para discutir.** ¿Qué gana el harness al reintentar en lugar del modelo? ¿Qué le dice al pasajero el agente sin
triage en el caso de la reserva ajena, y por qué es un problema? ¿Qué se hace con un error que nadie anticipó?

---

## Ejercicio 5 · Memoria de corto y largo plazo — 15 min

**Consigna.** Completar `recortar_historial()` (descartar turnos completos hasta entrar en un presupuesto de
tokens) y `extraer_hechos()` (qué guardar de una sesión para la siguiente).

**Completar** `starter/orbitair/memoria.py` (`recortar_historial`, `extraer_hechos`).

**Correr.**
```bash
python starter/c1/05_memoria.py
```

**Se espera ver.** Parte A: una conversación de 3 turnos sin historial, con historial completo, con recorte
ingenuo (la API lo rechaza) y con recorte por turnos. Parte B: los hechos guardados de una sesión y una segunda
sesión ("¿hay novedades de mi valija?") con y sin memoria.

**Para discutir.** ¿Por qué el recorte "últimos N mensajes" rompe la API? ¿Qué se pierde al recortar por turnos?
Con memoria de largo plazo, ¿por qué el agente vuelve a consultar la valija en lugar de responder con lo guardado?

---

## Criterios de aceptación

| Criterio | Cumple si... |
|---|---|
| Herramientas | `ejecutar_tool` rechaza herramientas inexistentes y argumentos de más; el pasajero sale de la sesión. Se puede explicar quién propone y quién ejecuta. |
| Loop | `correr` resuelve las 13 consultas con la trayectoria esperada y toda tool_call recibe su observación. |
| Stopping rules | El caso colgado termina por "repetida" en 2 pasos; hay una tabla de costo con y sin reglas, y una explicación de por qué igual se arregla el prompt. |
| Triage | Los cinco escenarios terminan como dice la tabla (reintentar / informar / abortar) y se puede explicar qué pasa sin triage. |
| Memoria | El historial se recorta por turnos sin romper la API; la segunda sesión usa la memoria para saber qué valija consultar. |

*La solución completa está en `src/` — se muestra recién al cierre de cada ejercicio.*
