# Clase 4 · Ejercicios — MCP (Model Context Protocol)

**Caso:** las herramientas de OrbitAir viven adentro del agente: si otro asistente de la empresa las quiere usar,
hay que copiarle el código. Hoy las publicamos **una vez**, como un server MCP — consultar vuelo, rastrear
valija, consultar reserva, iniciar reembolso, las políticas y dos plantillas — y las usamos desde el worker de
reembolsos. Después lo atacamos: ¿quién puede hacer qué, y cómo lo sabemos?

**Cómo se trabaja.** Los ejercicios completan `orbitair/mcp_server.py` (el server) y `orbitair/mcp_cliente.py`
(el agente como cliente). El server corre como **otro proceso**: el cliente lo lanza y le pasa la sesión (qué
pasajero, qué rol). Los scripts de `c4/` corren y fallan justo donde falta completar.

**Antes de empezar.** `uv sync` (instala el SDK `mcp` 2.x) y `python starter/resolver_hasta.py 3`. Sin API key:
`ORBITAIR_MOCK=1` (el server es real; sólo el "modelo" es un guion).

---

## Ejercicio 1 · Construir el server — 25 min

**Consigna.** Registrar en el server una tool (`consultar_vuelo`), dos resources (`politica://{codigo}` y
`pasajero://sesion`) y dos prompts (`reclamo_equipaje`, `seguimiento_reembolso`). Recorrerlos desde un cliente.

**Completar** `starter/orbitair/mcp_server.py` (`registrar_consultar_vuelo`, `registrar_politicas`,
`registrar_prompts`).

**Correr.**
```bash
python starter/c4/01_server.py
python starter/c4/01_server.py --schema
```

**Se espera ver.** El arranque del server, las tools con su schema (armado desde los type hints), una llamada a
`consultar_vuelo`, los resources y su contenido, y el mensaje que arma un prompt. Queda en `results/c4_server.md`.

**Para discutir.** ¿Quién decide usar una tool, un resource y un prompt? ¿Por qué el docstring de la función es
parte del prompt del agente? ¿Por qué aparece `iniciar_reembolso` en una sesión de sólo consulta?

---

## Ejercicio 2 · El agente como cliente — 20 min

**Consigna.** Completar `spec_openai()` (de la tool del server a la especificación que ve el modelo) y
`ClienteMCP.llamar()` (llamar a la tool y convertir los errores del server en los del triage de C1). Comparar el
worker de C3 con el mismo worker sobre MCP.

**Completar** `starter/orbitair/mcp_cliente.py` (`spec_openai`, `ClienteMCP.llamar`).

**Correr.**
```bash
python starter/c4/02_cliente.py
python starter/c4/02_cliente.py --parte B
```

**Se espera ver.** Las consultas de un dominio con herramientas locales y sobre MCP, con la misma trayectoria, y
cuánto tarda cada llamada al server. En la Parte B: un timeout del server que el cliente reintenta y un error de
permisos que deriva. Queda en `results/c4_cliente.md`.

**Para discutir.** ¿Se entera el modelo de que la herramienta vive en otro proceso? ¿Qué pasa con el triage si el
server no dice qué tipo de error fue?

---

## Ejercicio 3 · Seguridad y permisos del server — 25 min

**Consigna.** Correr la batería de ataques contra el server tal como está. Después completar
`herramientas_permitidas()` (qué tools existen para cada rol) y `ejecutar_auditado()` (re-chequeo de permisos,
tope de llamadas, errores con categoría y sin detalles de más, auditoría), y volver a correrla.

**Completar** `starter/orbitair/mcp_server.py` (`herramientas_permitidas`, `ejecutar_auditado`).

**Correr.**
```bash
python starter/c4/03_seguridad.py
```

**Se espera ver.** Para cada ataque (rol sin permiso, datos de otro pasajero, identidad colada en los argumentos,
inyección, inputs gigantes o fuera de rango, path traversal, agente desbocado, sesión inválida, prompt
injection): el resultado esperado y el obtenido, antes y después. Y el resumen de la auditoría. Queda en
`results/c4_seguridad.md`.

**Para discutir.** ¿Qué ya estaba protegido antes de tocar nada, y por quién? ¿Por qué un error de permisos no da
detalles? ¿Qué intentos no quedan en la auditoría?

---

## Ejercicio 4 · El worker de reembolsos sobre MCP — 10 min

**Consigna.** Correr el orquestador de C3 con el worker de reembolsos conectado al server. Después pedir un
reembolso y seguir quién decide qué.

**Correr.**
```bash
python starter/c4/04_orquestador_mcp.py
```

**Se espera ver.** Las consultas que pasan por reembolsos con la misma trayectoria que en C3, y en el pedido de
reembolso: la pausa del host antes de llamar al server, la aprobación, y la escritura auditada en el server.
Queda en `results/c4_orquestador_mcp.md`.

**Para discutir.** ¿Dónde vive la aprobación humana: en el host o en el server? ¿Qué decide cada uno?

---

## Ejercicio 5 · Servers de terceros — 10 min

**Consigna.** Conectar al host, además del server de OrbitAir, un server de la comunidad ("clima-viajes"). Ver
qué recibe ese server, qué pasa cuando los dos publican una tool con el mismo nombre y qué dice la descripción de
su tool. Aplicar las defensas del host.

**Correr.**
```bash
python starter/c4/05_terceros.py
```

**Se espera ver.** La sesión que se filtra (y que deja de filtrarse), la tool oficial pisada por la de terceros,
la descripción envenenada que leería el modelo, las alertas de la revisión (incluidos falsos positivos) y qué
queda expuesto al modelo con las defensas.

**Para discutir.** ¿Quién escribe el prompt de nuestro agente cuando conectamos un server ajeno? ¿Alcanza con un
detector de descripciones sospechosas? ¿Qué capa frena la acción si el modelo obedece igual?

---

## Criterios de aceptación

| Criterio | Cumple si... |
|---|---|
| Server | Expone tools, resources y prompts; el schema de cada tool sale de su firma y la identidad no es un argumento. |
| Cliente | El worker sobre MCP reproduce la trayectoria del worker local, y los errores del server llegan al triage con su categoría. |
| Seguridad | La batería da el resultado esperado en todos los ataques; cada llamada queda auditada; una sesión inválida no arranca. |
| Integración | El worker de reembolsos usa el server dentro del orquestador y la escritura pasa por aprobación humana antes de llegar al server. |
| Terceros | Se puede explicar cada problema del Ej. 5 y la defensa del host que lo resuelve. |

*La solución completa está en `src/` — se muestra recién al cierre de cada ejercicio.*
