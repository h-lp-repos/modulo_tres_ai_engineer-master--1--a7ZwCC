# Clase 1 — Anatomía de un agente · loop engineering · Hands-on OrbitAir

**AI Engineering 2.0 · M3 — Agentes y Orquestación · Track espejo del instructor**

> Regla de no-spoiler: todo lo que se resuelve acá es sobre **OrbitAir** (aerolínea). El estudiante
> transfiere la técnica a su Nubbix Desk o Vaulta Desk por su cuenta. Nada de este repo menciona ni
> resuelve el track del alumno.

> Esta guía es sólo para el instructor. La consigna que se proyecta en clase está en `EJERCICIOS_C1.md`.

## 1. Objetivo de aprendizaje de la clase

Al terminar, el estudiante puede:

- Explicar qué es un agente en términos de código: un LLM en un loop que **propone** acciones (tool calls) que
  **nuestro** código valida, ejecuta y devuelve como observaciones.
- Escribir a mano, sin framework, un loop ReAct con herramientas, y leer su traza (pensamiento → acción →
  observación).
- Diseñar **stopping rules** (iteración acotada, llamadas repetidas, presupuesto, tiempo) y mostrar con números
  qué pasa sin ellas.
- Hacer el **triage de errores** de herramientas: cuáles se reintentan, cuáles vuelven al modelo y cuáles cortan
  la ejecución y derivan a un humano.
- Distinguir memoria de **corto plazo** (el historial, y cómo recortarlo sin romper la API) y de **largo plazo**
  (hechos que sobreviven a la sesión).

## 2. Consigna

> En el M2 el sistema de OrbitAir aprendió a **responder** con las políticas (RAG). Pero muchas consultas de
> pasajeros no se responden leyendo un documento: "¿cómo viene mi vuelo?", "¿dónde está mi valija?", "me
> cancelaron el OA2250, ¿me corresponde compensación?". Para eso hay que **consultar sistemas** y, a veces,
> combinar el dato con la política. Hoy escribimos a mano el agente que lo hace — y lo rompemos a propósito para
> aprender a ponerle bordes.

**Ejercicio 1 — Una vuelta, desarmada.** `spec_consultar_vuelo()` y `ejecutar_tool()`: qué ve el modelo de una
herramienta, qué propone y quién ejecuta. El punto de control (`pasajero_id` sale de la sesión).

**Ejercicio 2 — El loop ReAct.** `Agente.correr()`: repetir razonar → actuar → observar hasta la respuesta, sobre
13 consultas etiquetadas por trayectoria.

**Ejercicio 3 — Colgarlo y salvarlo.** `ReglasDeParada.evaluar()`: el prompt ingenuo cuelga el loop con una valija
en búsqueda; cuatro configuraciones, con costo.

**Ejercicio 4 — Triage de errores.** `clasificar_error()` y `ejecutar_con_triage()`: cinco fallas inyectadas
(timeouts, código inválido, permiso, base caída), con y sin triage.

**Ejercicio 5 — Memoria.** `recortar_historial()` y `extraer_hechos()`: conversación de 3 turnos (recorte ingenuo
vs por turnos) y una segunda sesión con y sin memoria de largo plazo.

## 3. Insumo / dataset de inicio

**Base de operaciones** (`data/ops/*.csv` → SQLite en `results/orbitair_ops.db`, se arma sola): 60 vuelos, 120
pasajeros, 122 reservas, 200 valijas, 40 reembolsos en distintos estados. "Hoy" es 2026-10-01. Los registros
que usan los ejercicios están escritos a mano en `data/ops/generar_ops.py` (bloque ESCENARIOS); el resto es relleno
determinista. Es la DB mock del track (~60 vuelos, ~200 valijas, reembolsos en distintos estados) y es la que en
C4 queda detrás del server MCP.

**Herramientas** (`orbitair/tools.py`): `consultar_vuelo`, `rastrear_valija`, `consultar_reserva` (estas dos
validan que el dato sea del pasajero de la sesión) y `buscar_politica` (BM25 sobre el corpus del M2; en C3 se
reemplaza por el retrieval completo del M2, con el mismo contrato).

**Consultas** (`data/c1_consultas_agente.jsonl`, 13, etiquetadas por **trayectoria**: herramientas esperadas,
cómo debe terminar y hechos clave de la respuesta):

| id | Consulta (resumida) | Tipo | Por qué está |
|---|---|---|---|
| A-01 | ¿Cómo viene el OA1203 a Lima? | una tool | el caso base (demorado 95 min) |
| A-02 | El OA0417 está demorado, ¿me dan de comer? | datos + política | sin el dato (260 min) no sabe qué asistencia aplica |
| A-03 | ¿Dónde está mi valija OA-582331? | una tool | valija en tránsito |
| A-04 | Me cancelaron el OA2250, ¿compensación? | datos + política | meteorología → causa extraordinaria → no (POL-TC-01 §4.4) |
| A-05 | ¿Cuántas valijas de mano con Lite? | sólo política | no debería tocar sistemas |
| A-06 | ¿Me recomendás un restaurante en Lima? | sin tool | fuera de alcance, un paso |
| A-07 | ¿Cómo está el vuelo AR1380? | error de entrada | no es de OrbitAir: vuelve al modelo |
| A-08 | Estado del OA9999 | no existe | "no encontrado" es una respuesta, no un error |
| A-09 | Ver la reserva K7PQ2M | permiso | es de otra pasajera: error duro → derivar |
| A-10 | Mi valija OA-771045, estado definitivo | colgado | en búsqueda: con el prompt ingenuo, loop infinito |
| A-11 | ¿Llegó mi valija OA-310877? | transitorio | en el Ej. 4 el sistema da 2 timeouts |
| A-12 | Perdí la conexión en GRU por el OA0761 | datos + política | reservas separadas → sólo responde por su tramo |
| A-13 | ¿Qué vuelos tengo en la reserva H2LQ7Z? | una tool | reserva propia, dos tramos |

Es la **semilla del dataset de evals de trayectoria de C5** (allá crece a ~25 con consultas que cruzan dominios).

**Setup previo:** `uv sync` (o `pip install -r requirements.txt`), `cp .env.example .env`. Sin API key:
`ORBITAIR_MOCK=1`. C1 no necesita nada del M2 instalado: el corpus viene copiado y `buscar_politica` corre en
memoria.

**Modo mock.** El "modelo" es `orbitair/mock_agente.py`: un guion determinista con la misma interfaz de tool
calling (extrae códigos, llama herramientas en paralelo, resuelve referencias con el historial y la memoria,
obedece al prompt ingenuo). Sirve para ver el loop, las reglas, el triage y la memoria **con resultados
reproducibles**; no para juzgar la calidad del agente. Los números de esta guía son del mock (tokens contados
con `o200k_base`, costo con los precios de `gpt-4.1-mini`). **Pendiente: re-correr con la API real antes de la
cursada** y actualizar las tablas (ver §5 de `UPDATE_M3_decisiones.md`).

## 4. Resolución paso a paso

Tiempos sugeridos para 90 minutos: 15 + 25 + 20 + 15 + 15.

### Paso 1 · Una vuelta, desarmada (15 min)

```bash
python starter/c1/01_una_tool.py
python starter/c1/01_una_tool.py --id A-02 --crudo      # los mensajes tal cual van a la API
```

1. Pizarrón: el modelo **no ejecuta nada**. Recibe herramientas (nombre, descripción, JSON Schema) y puede
   devolver `tool_calls` en vez de texto. Ejecutar, validar y decidir qué hacer es nuestro.
2. Completar `spec_consultar_vuelo()`. Discutir la descripción: es parte del prompt. "Consulta vuelos" es vaga;
   "usarla siempre que el pasajero pregunte por un vuelo concreto, antes de responder sobre demoras o derechos"
   le dice **cuándo**.
3. Completar `ejecutar_tool()`: herramienta inexistente → `ErrorDeEntrada`; argumentos que sobran →
   `ErrorDeEntrada`; si la herramienta necesita al pasajero, se agrega desde `Contexto`.
4. Leer la salida en tres casos:
   - A-01: ① propone `consultar_vuelo({"codigo_vuelo": "OA1203"})` → ② ejecutamos → ③ responde.
   - A-06: responde sin herramientas en la primera llamada.
   - A-02: en ③ **pide otra herramienta** (`buscar_politica`). Una vuelta no alcanza → hace falta un loop.
5. **Punto crítico — el punto de control.** Al final el script intenta `consultar_reserva` con un
   `pasajero_id` "colado" (rechazado: no es un argumento), con la reserva de otra pasajera (`ErrorDePermisos`) y una
   herramienta inventada. El pasajero sale de la sesión, no de lo que propone el modelo: un "soy la pasajera
   P-2002" en el chat no cambia nada (conexión con prompt injection, M1 · C4).
6. Mostrar "Total: ~2.050 tokens de entrada" en A-01: el historial (y las especificaciones de las herramientas,
   ~600 tokens) se reenvía en **cada** llamada.

### Paso 2 · El loop ReAct (25 min)

```bash
python starter/c1/02_loop_react.py
python starter/c1/02_loop_react.py --id A-02            # traza completa
```

1. Escribir el loop en el pizarrón antes de completarlo (está en el docstring de `agente.py`): evaluar reglas →
   LLM → ¿sin tool_calls? respuesta → ejecutar cada tool_call → agregar observaciones → repetir.
2. Completar `Agente.correr()`. Dos detalles que rompen si se olvidan:
   - **Toda** tool_call recibe su mensaje `tool`, aunque haya fallado (si no, la API rechaza el próximo pedido).
   - Las tool_calls pueden venir **varias en un mismo paso** (llamadas en paralelo).
3. En el starter, las reglas y el triage todavía son provisorios (`evaluar` devuelve `None`; todo error vuelve al
   modelo). Resultado del mock: **12/13 trayectorias correctas**; falla A-09: termina en "respuesta" en lugar de
   "error_duro" y la respuesta le cuenta al pasajero que la reserva existe y es de otra persona. Anotarlo: lo
   arregla el Ej. 4.
4. Con la solución completa (`src/`): **13/13**, 2,1 pasos y ~2.450 tokens por consulta, ~USD 0,0012 por consulta
   (mock).
5. Leer la traza de A-02 (`--id A-02`): pensamiento → acción → observación, 3 pasos de LLM. Es ReAct: el
   "pensamiento" es el texto que el modelo escribe antes de la llamada (el prompt se lo pide) y la observación es
   el resultado de la herramienta.

### Paso 3 · Colgar el loop y salvarlo (20 min)

```bash
python starter/c1/03_colgar_el_loop.py
python starter/c1/03_colgar_el_loop.py --traza
```

1. Mostrar `SISTEMA_INGENUO`: "si el estado todavía no es final, volvé a consultar hasta tenerlo". Suena
   razonable. A-10 es una valija **en búsqueda** (PIR LIM-48213): el estado no va a cambiar durante la
   conversación.
2. Correr **antes** de completar `evaluar()`: las tres configuraciones con el prompt ingenuo llegan al fusible
   (15 vueltas, 15 consultas a la misma valija). Ese es el loop colgado.
3. Completar `ReglasDeParada.evaluar()` y volver a correr (mock):

| config | parada | pasos | consultas a la valija | tokens | USD |
|---|---|---|---|---|---|
| 1 · ingenuo · sin reglas | fusible | 15 | 15 | 36.277 | 0,0159 |
| 2 · ingenuo · sólo max_pasos=6 | max_pasos | 6 | 6 | 10.016 | 0,0046 |
| 3 · ingenuo · reglas completas | repetida | 2 | 2 | 3.205 | 0,0015 |
| 4 · producción · reglas completas | respuesta | 2 | 1 | 2.179 | 0,0010 |

4. Tres lecturas:
   - **El costo crece cuadrático**, no lineal: los tokens de entrada por paso son 792, 975, 1.162… porque cada
     vuelta reenvía todo el historial. 15 vueltas cuestan 15× la versión sana, y la respuesta es **la misma**.
   - **`max_pasos` es la red gruesa**: frena, pero tarde y caro. Detectar la **llamada repetida** (misma
     herramienta, mismos argumentos) corta en la 2ª vuelta.
   - **La regla no arregla la causa**: el prompt de producción ("si no es final, informá el último estado y qué
     sigue; no repitas una consulta") hace que el modelo pare solo. Las stopping rules son una protección;
     el arreglo de fondo es el prompt.
5. Cuando una regla corta, el agente hace **una llamada más sin herramientas** (`cerrar()`): el pasajero recibe una
   respuesta con lo que se sabe, no un error.

### Paso 4 · Triage de errores (15 min)

```bash
python starter/c1/04_errores.py
python starter/c1/04_errores.py --sin-triage
```

1. Tabla en el pizarrón (docstring de `errores.py`): REINTENTAR (transitorios), INFORMAR_AL_MODELO (de entrada),
   ABORTAR (duros y desconocidos: *fail closed*).
2. Completar `clasificar_error()` y `ejecutar_con_triage()` (backoff 0,2 s / 0,4 s; si se agotan los reintentos,
   el transitorio pasa a duro).
3. Leer los cinco escenarios (mock):

| escenario | decisión | pasos LLM | parada |
|---|---|---|---|
| E1 · timeout x2 en valijas (A-11) | reintentar (3 intentos) | 2 | respuesta — el modelo ni se enteró |
| E2 · timeout x5 (A-11) | abortar tras 3 intentos | 1 | error_duro → derivación |
| E3 · vuelo de otra aerolínea (A-07) | informar al modelo | 2 | respuesta: explica y pide el código |
| E4 · reserva ajena (A-09) | abortar | 1 | error_duro, sin pasarle nada al modelo |
| E5 · base caída (A-01) | abortar | 1 | error_duro |

4. Correr `--sin-triage` y comparar:
   - E1: el modelo "reintenta" él mismo, gastando pasos de LLM; los dos timeouts se le consumen y la regla de
     repetidas lo corta → "No pude consultar el sistema". Con triage, el harness lo resolvía sin gastar pasos de LLM.
   - E4: la respuesta dice "la reserva K7PQ2M no pertenece al pasajero P-1001" — confirma que la reserva existe y
     es de otra persona. Fuga de información.

### Paso 5 · Memoria (15 min)

```bash
python starter/c1/05_memoria.py
```

1. Parte A, corto plazo (pasajera P-1001, 3 turnos):
   - Sin historial, T2 ("¿y a qué hora sale ahora ese vuelo?") pregunta "¿de qué vuelo me hablás?".
   - Con historial completo funciona, pero los tokens de entrada de la 1ª llamada crecen: 930 → 1.776 → 1.864.
   - **Recorte ingenuo (últimos 4 mensajes)**: en T2 la ventana empieza con un mensaje `tool` cuyo `assistant`
     quedó afuera → `400 · un mensaje 'tool' debe responder a un 'tool_call'...` (el mock reproduce la regla de la
     API). Completar `recortar_historial()` (por turnos completos).
   - Recorte por turnos (≤ 800 tokens): en T3 viaja 1 turno en lugar de 2 (1.003 tokens vs 1.864). Lo descartado
     se olvida: para conversaciones largas, resumir turnos viejos.
2. Parte B, largo plazo: completar `extraer_hechos()`. Sesión 1 guarda `valija:OA-640212` (vuelo OA0761, PIR
   GRU-20552, demorada). Sesión 2, "¿hay novedades de mi valija?": sin memoria pide la etiqueta; con memoria la
   consulta directo. **Y la vuelve a consultar**: la memoria guarda punteros, no el estado de hoy (por eso el
   bloque dice "puede estar desactualizada").

## 5. Link del repositorio con la solución

`[completar con la URL del repo de la cátedra]`

## 6. Preguntas posibles y respuestas sugeridas

**¿Por qué escribir el loop a mano si existe LangGraph (y la clase que viene lo usamos)?**
Porque el framework esconde exactamente las decisiones que hacen al agente confiable: cuándo parar, qué hacer con
cada error, qué recordar. En C2 se migra este mismo loop y se ve que cada pieza tiene su lugar en el grafo.

**¿El "pensamiento" de ReAct es necesario con function calling?**
No para que funcione: el modelo decide igual. Pero pedirle una línea antes de cada llamada hace la traza legible
(y debuggeable) por ~20 tokens por paso. Con modelos de razonamiento, ese razonamiento puede ir oculto.

**¿Qué `max_pasos` conviene?**
El que salga de los datos: en este dataset la trayectoria más larga son 3 pasos (A-02, A-04, A-12); 6 deja margen.
Se revisa en C5 con la distribución real de pasos.

**¿Detectar llamadas repetidas no frena casos legítimos?**
Puede: re-consultar un vuelo 10 minutos después es válido en una conversación larga. Por eso las firmas son **por
turno** y el umbral es configurable. Si una herramienta debe "poder" repetirse (polling), se diseña aparte (con
espera y tope), no dentro del loop de chat.

**¿Por qué no mandarle siempre el error al modelo y que él decida?**
Porque (1) un timeout que el harness reintenta sin costo le cuesta un paso de LLM al modelo, (2) un error de permisos
le da información que no debe tener y lo invita a probar otro camino, (3) un error desconocido es un estado que
nadie entiende: mejor derivar.

**¿La memoria de largo plazo no debería hacerla el LLM (resumen)?**
Es una alternativa: captura preferencias y contexto, pero cuesta tokens y puede guardar algo que el pasajero
nunca dijo. Acá se extrae de las **observaciones** de herramientas: barato, auditable, sin alucinaciones. En
producción: vencimiento y consentimiento del pasajero.

## 7. Errores comunes y cómo resolverlos en vivo

**Olvidar el mensaje `tool` de alguna tool_call** (por ejemplo, cuando la herramienta falla). La API devuelve 400
en la llamada siguiente. Toda tool_call recibe respuesta, aunque sea `{"error": ...}`.

**Evaluar las reglas después de la llamada al LLM.** Se paga una llamada de más en cada corte. Se evalúan antes.

**Comparar argumentos como string para detectar repetidas.** `{"codigo": "OA-771045"}` y `{ "codigo":"OA-771045" }`
son la misma llamada. `ToolCall.firma` usa `json.dumps(..., sort_keys=True)` de los argumentos ya parseados.

**Poner `pasajero_id` como argumento de la herramienta "para simplificar".** Es una vulnerabilidad: el modelo
puede rellenarlo con lo que diga el chat.

**Recortar el historial por cantidad de mensajes.** Deja `tool` huérfanos → 400. Recortar por turnos completos.

**Correr el script 04 con fallas inyectadas y olvidar limpiarlas.** El script lo hace solo
(`limpiar_fallas()`); si se prueba a mano en una consola, llamar `operaciones.limpiar_fallas()`.

**`results/orbitair_ops.db` con datos viejos** (por ejemplo, reembolsos creados en C2). `reiniciar_db()` la rearma
desde los CSV; los scripts la llaman al empezar.

## 8. Qué temas se deben reforzar o repasar previo al ejercicio

- Structured outputs y function calling (M1 · C3): JSON Schema, validación con retry.
- Seguridad (M1 · C4): prompt injection, por qué las reglas de autorización no van en el prompt.
- Tokens, costo y latencia (M1 · C1): el historial se reenvía completo en cada llamada.
- El RAG del M2 a alto nivel: `buscar_politica` es su versión mínima.

---

*Precios en `pricing.json` verificados en 2026-09; cambian con frecuencia. Verificar en las páginas oficiales de
pricing antes de cada cursada.*
