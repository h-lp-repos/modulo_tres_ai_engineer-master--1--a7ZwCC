# Clase 2 · Ejercicios — LangGraph

**Caso:** el agente de OrbitAir de C1 funciona, pero su lógica de control está escondida en un `while True`.
Ahora hay que sumarle cosas que con ese loop son difíciles: que un supervisor apruebe un reembolso antes de
iniciarlo, que una conversación sobreviva a un reinicio, que el pasajero vea "consultando tu vuelo…" mientras
espera. Hoy lo migramos a LangGraph — **mismo comportamiento, ahora inspeccionable** — y usamos lo que el grafo
da: checkpoints, pausas y streaming.

**Cómo se trabaja.** Los ejercicios completan `orbitair/grafo.py`. Los nodos ya están resueltos y reutilizan las
piezas de C1. Los scripts de `c2/` corren y fallan justo donde falta completar.

**Antes de empezar.** `python starter/resolver_hasta.py 1` (deja C1 resuelto). Sin API key: `ORBITAIR_MOCK=1`.

**Datos.** Las 13 consultas de C1 y un caso nuevo: la reserva M4TR88, con su vuelo cancelado por OrbitAir, y la
pasajera pide el reembolso. `iniciar_reembolso` es la primera herramienta que **escribe**.

---

## Ejercicio 1 · Migrar el loop a un grafo — 25 min

**Consigna.** Completar `ruta_agente()` (a dónde ir después de que el modelo habla) y `construir_grafo()` (nodos,
edges y edges condicionales). Correr las 13 consultas con el agente de C1 y con el grafo, y comparar.

**Completar** `starter/orbitair/grafo.py` (`ruta_agente`, `construir_grafo`).

**Correr.**
```bash
python starter/c2/01_migrar_a_langgraph.py
python starter/c2/01_migrar_a_langgraph.py --id A-02
python starter/c2/01_migrar_a_langgraph.py --mermaid
```

**Se espera ver.** Por consulta: herramientas, parada y pasos con C1 y con el grafo, y si la trayectoria es la
misma. Con `--id`, el recorrido nodo por nodo. Con `--mermaid`, el diagrama. Queda en `results/c2_migracion.md`.

**Para discutir.** ¿Dónde quedó cada `if` del loop de C1? ¿Por qué se compara la trayectoria y no el texto de la
respuesta? ¿Qué nodo hace las stopping rules y por qué es un nodo y no un edge?

---

## Ejercicio 2 · Checkpoints — 20 min

**Consigna.** Completar `abrir_checkpointer()` (en memoria o SQLite). Usarlo para una conversación de 3 turnos en
un mismo thread, para retomarla después de un reinicio y para leer la historia del estado.

**Completar** `starter/orbitair/grafo.py` (`abrir_checkpointer`).

**Correr.**
```bash
python starter/c2/02_checkpoints.py
python starter/c2/02_checkpoints.py --turno 1      # y después, en otro proceso:
python starter/c2/02_checkpoints.py --turno 2
```

**Se espera ver.** El estado del thread creciendo turno a turno; un thread nuevo que no sabe de qué vuelo se
habla; el turno 2 retomado desde SQLite; la lista de checkpoints de un turno y una re-ejecución desde uno de
ellos.

**Para discutir.** ¿Qué reemplaza el checkpointer de lo que hicimos a mano en C1? ¿Qué campos del estado se
acumulan y cuáles se reinician en cada turno, y por qué? ¿Para qué sirve volver a correr desde un checkpoint?

---

## Ejercicio 3 · Human-in-the-loop — 20 min

**Consigna.** Completar `nodo_aprobacion()`: pausar con `interrupt()` antes de `iniciar_reembolso` y, según lo
que decida el supervisor, aprobar, editar los argumentos o rechazar.

**Completar** `starter/orbitair/grafo.py` (`nodo_aprobacion`).

**Correr.**
```bash
python starter/c2/03_human_in_the_loop.py
python starter/c2/03_human_in_the_loop.py --pausar
python starter/c2/03_human_in_the_loop.py --reanudar editar --monto 150
```

**Se espera ver.** El grafo detenido antes de `aprobacion` con lo que ve el supervisor, la base sin cambios
durante la pausa, y el resultado de cada decisión (reembolso creado, creado con otro monto, o no creado y
explicado al pasajero). Con `--pausar` / `--reanudar`, la pausa sobrevive al proceso.

**Para discutir.** ¿Qué herramientas deberían pedir aprobación y cuáles no? ¿Qué pasa con el código que está
antes de `interrupt()` cuando se reanuda? ¿Por qué el rechazo vuelve al modelo como observación?

---

## Ejercicio 4 · Streaming de estados — 10 min

**Consigna.** Correr el grafo con `stream()` en distintos modos y leer qué emite cada uno.

**Correr.**
```bash
python starter/c2/04_streaming.py
python starter/c2/04_streaming.py --modo values
python starter/c2/04_streaming.py --id A-11 --fallas
```

**Se espera ver.** Eventos con su tiempo: qué nodo terminó y qué cambió (`updates`), el estado completo
(`values`) y el progreso de las herramientas, incluidos los reintentos (`custom`).

**Para discutir.** ¿Qué modo le sirve a la app del pasajero y cuál a quien depura? ¿Cambia la latencia total o
la percibida?

---

## Ejercicio 5 · Debugging del grafo — 15 min

**Consigna.** Al migrar, alguien sacó el nodo de control "porque el modelo sabe cuándo parar". Correr el caso de
la valija en búsqueda con el prompt ingenuo, encontrar el problema con la forma del grafo y la historia del
estado, y comprobar el arreglo.

**Correr.**
```bash
python starter/c2/05_debug_grafo.py
```

**Se espera ver.** Las aristas de los dos grafos, un `GraphRecursionError`, la historia del estado step a step
(qué nodo corrió y qué pidió el modelo) y el mismo caso con el nodo de control.

**Para discutir.** ¿Por qué `recursion_limit` no reemplaza a las stopping rules? ¿Qué información da la historia
del estado que no da el mensaje de error? ¿Subir el límite arregla algo?

---

## Criterios de aceptación

| Criterio | Cumple si... |
|---|---|
| Migración | El grafo reproduce la trayectoria de C1 en las 13 consultas, y se puede señalar en el diagrama dónde quedó cada decisión del loop. |
| Checkpoints | La conversación de 3 turnos funciona por `thread_id`, sobrevive a un reinicio con SQLite, y los contadores por turno se reinician. |
| Human-in-the-loop | `iniciar_reembolso` nunca se ejecuta sin una decisión; aprobar, editar y rechazar dejan la base como corresponde. |
| Streaming | Se puede explicar qué emite cada modo y para qué se usa. |
| Debugging | El bug se diagnostica desde la historia del estado (no subiendo el límite) y el arreglo termina el caso por "repetida". |

*La solución completa está en `src/` — se muestra recién al cierre de cada ejercicio.*
