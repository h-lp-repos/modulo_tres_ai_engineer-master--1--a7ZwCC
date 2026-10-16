# Checklist del instructor · qué chequear y evaluar antes de dictar

**AI Engineering 2.0 · M3 — Agentes y Orquestación · Track espejo OrbitAir**

> Todo el repo se construyó y validó en **modo mock** (`ORBITAIR_MOCK=1`): el "modelo" es un guion
> determinista. El mock sirve para ensayar el mecanismo de cada ejercicio; **no** dice nada sobre la calidad
> del agente con un LLM real. Esta lista es lo que el instructor (o el experto) tiene que correr, mirar y
> decidir antes de la cursada. Marcar cada ítem al cerrarlo.

Leyenda: 🔴 bloquea la clase · 🟡 cambia números o textos de la guía · 🟢 revisión de contenido / decisión de criterio.

---

## 0. General (una vez, antes de la primera clase)

- [ ] 🔴 **Setup en la máquina del instructor.** `uv sync`, `cp .env.example .env`, completar `OPENAI_API_KEY`,
      dejar `ORBITAIR_MOCK=0`. Correr `uv run src/c1/02_loop_react.py --id A-01` como prueba de humo.
- [ ] 🟡 **Precios.** Verificar `pricing.json` (`gpt-4.1-mini`, `text-embedding-3-small`) contra la página
      oficial. Todos los USD de las guías salen de ahí.
- [ ] 🟡 **Modelo.** Confirmar que `gpt-4.1-mini` sigue disponible y es el que se quiere usar (`OPENAI_MODEL`).
      Si se cambia, agregarlo a `pricing.json`.
- [ ] 🟢 **Contenido.** Revisar tono, números y coherencia del corpus (`corpus/`, viene del M2) y de los datos de
      operaciones (`data/ops/`). Los escenarios de los ejercicios están en `data/ops/generar_ops.py` (ESCENARIOS).
- [ ] 🟢 **Regla de no-spoiler.** Confirmar que nada de las guías, ejercicios ni código menciona Nubbix / Vaulta.
- [ ] 🟡 **Re-correr cada script con la API real y reemplazar las tablas de la guía** marcadas "(mock)". Costo
      total estimado del módulo con la API real: menos de USD 1. Correr 2-3 veces los scripts con números para
      ver la variabilidad (el modelo no es determinista): en la guía conviene poner rangos, no un número exacto.

---

## Clase 1 · Anatomía de un agente

- [ ] 🟡 `c1/02_loop_react.py`: en mock da 13/13 trayectorias, 2,1 pasos y ~USD 0,0012 por consulta. Con la API
      real mirar sobre todo A-06 (fuera de alcance: ¿responde sin herramientas?), A-07 (vuelo de otra aerolínea:
      ¿pide el código correcto?) y A-09 (permiso: tiene que cortar en `error_duro`).
- [ ] 🔴 `c1/03_colgar_el_loop.py`: **el ejercicio depende de que el prompt ingenuo cuelgue el loop.** El mock lo
      hace siempre (15 vueltas). Verificar que `gpt-4.1-mini` también vuelve a consultar la valija A-10; si no se
      cuelga, endurecer `SISTEMA_INGENUO` en `agente.py` antes de clase. Actualizar la tabla (vueltas, tokens).
- [ ] 🟡 `c1/04_errores.py`: con triage / sin triage. Ver qué hace el modelo real cuando recibe el timeout como
      observación (el mock "reintenta"; el modelo real puede rendirse o inventar).
- [ ] 🟡 `c1/05_memoria.py`: el 400 por mensaje `tool` huérfano lo devuelve la API real igual que el mock;
      confirmar el texto exacto del error para la guía.

## Clase 2 · LangGraph

- [ ] 🟡 `c2/01_migrar_a_langgraph.py`: en mock, misma trayectoria y mismo texto en 13/13. Con la API real el
      **texto** va a diferir (por eso se compara la trayectoria): actualizar la frase de la guía.
- [ ] 🟡 `c2/02_checkpoints.py`: cantidad de checkpoints por turno (10 en mock) y crecimiento de mensajes; con la
      API real el modelo puede hacer otra cantidad de pasos.
- [ ] 🔴 `c2/03_human_in_the_loop.py`: verificar que el modelo real **propone `iniciar_reembolso`** para M4TR88. Si
      no lo hace (responde sin iniciar), el ejercicio no muestra la pausa: ajustar la consulta o la descripción de
      la herramienta.
- [ ] 🟡 `c2/04_streaming.py`: medir latencia del primer evento vs respuesta completa con la API real (la guía
      dice 3-5 s).
- [ ] 🟢 Decidir si se muestra `create_react_agent` en vivo (la guía lo deja como pregunta).
- [ ] 🟢 Una vez, en una regresión completa, `c2/03` terminó con código 1 y no se pudo reproducir (4 de 4
      corridas OK). Sospecha: Windows bloqueando `results/orbitair_ops.db` al rearmarla. Si pasa en clase,
      volver a correr; si se repite, cerrar procesos que tengan la base abierta.

## Clase 3 · Multiagente

- [ ] 🔴 **Router real (`c3/02_routing.py`).** En mock el router es un clasificador por palabras clave y acierta
      25/25: **en mock el Ej. 2 no mide nada de calidad**. Con la API real, anotar exactitud, de más / de menos y
      precisión / recall por dominio, y actualizar la guía. Casos a mirar: M-12 ("demorado… ¿algo para comer?" →
      reembolsos, puede ir a cambios), M-13 (compensación → reembolsos), M-14 ("rueda rota… ¿hasta cuándo
      reclamo?" → equipaje, no reembolsos), M-21 ("¿me devuelven el pasaje?" por una valija).
- [ ] 🟡 **Prompt del router.** Si el router real se equivoca mucho, iterar `SISTEMA_ROUTER` en
      `orquestador.py` (es un buen momento para mostrar la iteración con datos del M1 · C2/C5).
- [ ] 🟡 `c3/03_orquestador.py`: paralelo vs en serie. En mock 0,41 s vs 0,58 s (1,4×); con la API real la
      diferencia es de segundos. Reemplazar los números de la guía.
- [ ] 🔴 **`c3/04_se_justifica.py` es la discusión central de la clase.** Los números del mock (agente único 14/14
      y 6/9; orquestador 14/14 y 9/9, al doble de costo en cruces) son del guion: **re-correr con la API real y
      reescribir el paso 4 de la guía con lo que salga.** Puede pasar que el agente único real resuelva más
      cruces (hace dos búsquedas) o que el orquestador falle por routing: cualquier resultado sirve para la
      discusión, siempre que la guía diga lo que pasó de verdad.
- [ ] 🟡 `c3/05_hitl_multiagente.py`: confirmar que el worker de reembolsos real propone `iniciar_reembolso` y que
      los contadores (corridas por worker, llamadas al LLM) siguen mostrando que equipaje no se re-ejecuta.
- [ ] 🟢 **Etiquetas del dataset** `data/c3_consultas_multiagente.jsonl`: revisar la ruta esperada de los casos
      ambiguos (M-12, M-13, M-14, M-21, M-25) y los `hechos` (fragmentos que la respuesta tiene que contener). Con
      la API real, un hecho que falla puede ser un error del agente **o** un hecho mal elegido: mirar la respuesta
      antes de concluir.
- [ ] 🟢 **Decisión de producto, M-24 (falla parcial).** Hoy: se responde la parte legítima (la valija) y se deriva
      la que dio error de permisos (la reserva ajena). Alternativa conservadora: derivar toda la consulta.
      Confirmar el criterio con el cliente.
- [ ] 🟢 El índice de embeddings (`results/c3_indice_text-embedding-3-small.npz`) se construye la primera vez con
      la API real (~USD 0,0003). Correr `c3/01_workers.py` antes de clase para no esperarlo en vivo.
- [ ] 🟢 Con embeddings reales, revisar la Parte A de `c3/01_workers.py` ("¿Me devuelven la plata si me cancelan
      el vuelo?"): la guía cita los ids del mock.

## Clase 4 · MCP

- [ ] 🔴 **Versión del SDK.** El código usa `mcp` **2.x** (`MCPServer`, `mcp.Client`; se armó con la 2.3.0).
      Después de `uv sync`, correr `python src/c4/01_server.py`. Si el SDK cambió de nuevo (es un paquete que se
      mueve rápido), revisar los imports de `mcp_server.py`, `mcp_cliente.py` y `mcp_terceros.py`. Avisar a los
      alumnos que los tutoriales con `FastMCP` son de la 1.x.
      El 2026-10-05 se contrastaron las APIs de `mcp` 2.x, `langfuse` 4.x y `langgraph` 1.2 con su documentación
      oficial actual (Context7): coinciden. A partir de eso, las tools devuelven `TypedDict` (salida estructurada,
      `structured_content`), el server usa el import corto `from mcp.server import MCPServer` y los scores
      booleanos van a Langfuse como `BOOLEAN`.
- [ ] 🟡 **Tiempos en la máquina del instructor.** Arranque de un server (~1 s en la máquina donde se armó) y
      latencia por `tools/call` (~5-8 ms). Actualizar los pasos 1 y 2 de la guía. En Windows con antivirus el
      arranque puede ser bastante más lento.
- [ ] 🟡 `c4/02_cliente.py` y `c4/04_orquestador_mcp.py` con la API real: confirmar que la trayectoria con MCP
      sigue siendo igual a la local (14/14 y 13/13 en mock). Si difiere, mirar primero las **descripciones** de
      las tools: ahora salen del docstring del server y no de `tools.py` (son el mismo texto, pero conviene
      verificarlo).
- [ ] 🔴 `c4/04_orquestador_mcp.py`, Parte B, con la API real: el modelo tiene que **proponer
      `iniciar_reembolso`** para que se vea la pausa en el host (igual que C2 · Ej. 3 y C3 · Ej. 5).
- [ ] 🟡 **Ensayar la progresión del starter**, que es el corazón de la clase: con `resolver_hasta.py 3`, completar
      los Ej. 1 y 2 y correr `c4/03_seguridad.py` **antes** del Ej. 3. Tiene que dar 8/15 y mostrar que una sesión
      de sólo consulta crea un reembolso. Después del Ej. 3 tiene que dar 15/15.
- [ ] 🟢 **MCP Inspector (opcional, requiere Node).** No se probó con el server 2.x. Si se quiere mostrar:
      `cd src` y `npx @modelcontextprotocol/inspector -e ORBITAIR_PASAJERO_ID=P-1001 -e ORBITAIR_ROL=consulta
      python -m orbitair.mcp_server`. Verificarlo antes de clase; si no anda, `c4/01_server.py` muestra lo mismo.
- [ ] 🟢 **Decisiones de diseño para validar con el cliente:**
      - transporte **stdio** con la sesión por variables de entorno (en producción sería HTTP + OAuth; queda en
        la guía como pregunta, no se implementa);
      - las políticas son **resources** del server, pero `buscar_politica` sigue en el host (el retrieval del M2
        no se mudó al server);
      - el contrato de errores es una **convención nuestra** (etiqueta entre corchetes en el texto del error),
        no algo del protocolo;
      - la auditoría no registra los rechazos por schema (los corta el SDK antes; haría falta un middleware).
- [ ] 🟢 El Ej. 5 usa un server "de terceros" inventado (`mcp_terceros.py`) con una descripción envenenada. Revisar
      que el texto de la instrucción maliciosa sea adecuado para proyectar en clase.

## Clase 5 · Trazabilidad y evals (Langfuse)

- [ ] 🔴 **Langfuse con una cuenta real: no se probó.** Todo se validó en modo local, y el camino de Langfuse sólo
      con credenciales falsas y un host inalcanzable (corre sin romper, pero no exporta). Con un proyecto real en
      Langfuse Cloud (plan gratuito) y las tres variables en el `.env`, verificar:
      - `c5/01_trazas.py`: la traza aparece en la UI con el árbol completo (router, workers en paralelo,
        generations con tokens y costo, tools, retrieval) e imprime el link (en modo local imprime `None`);
      - `c5/02_sesiones.py`: la vista **Sessions** agrupa los turnos y el costo por sesión coincide con la tabla
        del script; el score de sesión `costo_sesion_usd` aparece en la sesión;
      - `c5/03_evals.py`: los scores (ruta_correcta, exito, …) aparecen sobre cada traza;
      - `c5/04_experimentos.py`: se crea el dataset `orbitair-m3-trayectorias` (25 items) y las corridas v1,
        v1-serie y v1-gpt-4.1 aparecen como **dataset runs** comparables. Es la parte con más riesgo: usa
        `dataset.run_experiment` del SDK 4.x (la tarea es síncrona y corre con `max_concurrency=1`).
- [ ] 🔴 **Versión del SDK.** El código usa `langfuse` **4.x** (se armó con la 4.17): `start_as_current_observation`,
      `propagate_attributes`, `create_score`, `get_dataset().run_experiment`. La 3.x tiene otra API.
- [ ] 🟡 **Re-correr C5 con la API real** y actualizar las tablas de la guía. Con el guion el éxito es 25/25 y los
      evals del Ej. 3 no muestran fallas; con el modelo real aparecen (sobre todo de routing). El experimento
      v1-gpt-4.1 llama de verdad a `gpt-4.1` (estimado: ~USD 0,30 para las 25 consultas).
- [ ] 🟡 **Calibrar las tolerancias del gate** (`evals.TOLERANCIAS`) corriendo la línea de base 2-3 veces con la API
      real: la latencia p95 y hasta la ruta varían entre corridas. En mock la latencia es simulada y el gate de
      latencia de v1-serie da +36% (no pasa); con la API real la diferencia en serie debería ser mayor.
- [ ] 🔴 **El Ej. 5 depende de que el prompt ingenuo haga repetir `rastrear_valija`** también con el modelo real
      (lo mismo que C1 · Ej. 3). Si el modelo real no repite, `cortes_por_regla` no se mueve y el ejemplo se cae.
- [ ] 🟢 **PII en las trazas.** Las trazas guardan la consulta del pasajero, códigos y detalles internos de errores
      (en M-24: "la reserva K7PQ2M no pertenece al pasajero P-1001"). Para la clase está bien; decidir si se
      muestra la función `mask` del cliente de Langfuse.
- [ ] 🟢 **Decisiones de diseño para validar con el cliente:** doble escritura (local siempre + Langfuse
      opcional); instrumentación manual (no el `CallbackHandler` de LangChain, porque el cliente LLM es propio);
      el dataset de conversaciones arma 10 sesiones con las 25 consultas de C3 (los turnos son autocontenidos: el
      orquestador no tiene memoria entre turnos); el gate incluye una métrica de comportamiento
      (`cortes_por_regla`, tolerancia 0).

---

*Al cerrar cada ítem 🟡, actualizar la tabla o el texto correspondiente en `GUIA_Cn.md` y borrar la marca
"(mock)".*
