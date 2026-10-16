"""C2 · El agente de C1 migrado a LangGraph: mismo comportamiento, ahora como grafo de estado.

EJERCICIO 1 · Completar `ruta_agente()` y `construir_grafo()`.
EJERCICIO 2 · Completar `abrir_checkpointer()`.
EJERCICIO 3 · Completar `nodo_aprobacion()` (human-in-the-loop).

El loop de C1 tenía la lógica de control escondida en un `while True` con `return`s.
En LangGraph esa misma lógica se vuelve explícita:

                      ┌─────────────────────────────────────────────┐
                      ▼                                             │
    START ──► control ──► agente ──► herramientas ──────────────────┘
                 │          │  │          │
                 ▼          │  ▼          ▼
              cierre        │ aprobacion  escalar        (aprobacion ──► herramientas)
                 │          ▼     (C2·Ej3)    │
                 └──────►  END  ◄─────────────┘

- ESTADO (`EstadoAgente`): todo lo que el loop de C1 tenía en variables locales
  (mensajes, pasos, costo, firmas, parada) ahora vive en un dict tipado que el grafo
  guarda después de cada nodo. Ese estado ES el estado del sistema.
- NODOS: funciones estado → actualización parcial del estado. Reutilizan las piezas
  de C1 (`Agente.llamar_llm`, `Agente.ejecutar`, `ReglasDeParada.evaluar`): la
  migración cambia la orquestación, no el modelo ni las herramientas.
- EDGES: fijos (herramientas → control) o condicionales (después de `agente`: ¿pidió
  herramientas?, ¿alguna necesita aprobación?).
- CHECKPOINTS: con un checkpointer, el estado se persiste después de cada paso, por
  `thread_id`. Eso da memoria de conversación sin armar el historial a mano (C1 · Ej. 5),
  retomar después de un corte, inspeccionar la historia del estado y pausar para que un
  humano apruebe.

Nota sobre el modelo: los nodos llaman al mismo cliente de C1 (orbitair/llm.py) y no a
`ChatOpenAI` de LangChain. Es deliberado: el grafo no depende del cliente del modelo, y
así se ve que LangGraph es sobre el CONTROL del flujo. La alternativa prearmada
(`langgraph.prebuilt.create_react_agent` con `ChatOpenAI` + `ToolNode`) se discute en
la guía: arma un grafo equivalente con menos código, pero esconde las stopping rules y el triage.
"""
from __future__ import annotations

import operator
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated, Callable, TypedDict

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from . import trazas
from .agente import DERIVACION, Agente, EstadoLoop, ReglasDeParada
from .llm import ToolCall, _parsear, mensaje_tool
from .tools import HERRAMIENTAS_C1, SENSIBLES

RESULTS = Path(__file__).resolve().parents[2] / "results"


# ---------------------------------------------------------------------------
# Estado
# ---------------------------------------------------------------------------
class EstadoAgente(TypedDict, total=False):
    # Acumulan a lo largo de toda la conversación (el reducer `operator.add` concatena listas):
    mensajes: Annotated[list[dict], operator.add]
    # Fijos por conversación (thread):
    pasajero_id: str
    nombre: str
    # Por turno: se reinician con cada mensaje nuevo del pasajero (`entrada_turno`):
    pasos: int
    costo_usd: float
    inicio: float
    firmas: list[str]
    overrides: dict[str, dict]            # C2 · Ej. 3: argumentos editados por el supervisor, por tool_call_id
    parada: str | None
    respuesta: str | None


def entrada_turno(texto: str, pasajero_id: str, nombre: str = "") -> EstadoAgente:
    """Lo que se le pasa al grafo en cada turno: el mensaje nuevo y los contadores del turno en cero."""
    return {"mensajes": [{"role": "user", "content": texto}], "pasajero_id": pasajero_id, "nombre": nombre,
            "pasos": 0, "costo_usd": 0.0, "inicio": time.time(), "firmas": [], "overrides": {}, "parada": None,
            "respuesta": None}


@dataclass
class ConfigAgente:
    """Lo mismo que configuraba al Agente de C1. El pasajero NO va acá: sale del estado de cada thread.

    `fabrica` (C3): qué clase de agente arman los nodos. Por defecto el Agente de C1; en C3 un
    worker especializado (orbitair/workers.py) con su prompt y su retrieval filtrado."""
    prompt: str = "produccion"
    reglas: ReglasDeParada = field(default_factory=ReglasDeParada)
    herramientas: list[str] = field(default_factory=lambda: list(HERRAMIENTAS_C1))
    fabrica: Callable[..., Agente] = Agente


def tool_calls_pendientes(mensajes: list[dict]) -> list[ToolCall]:
    """Las tool_calls del último mensaje `assistant` que todavía no tienen su mensaje `tool`."""
    respondidas = {m["tool_call_id"] for m in mensajes if m["role"] == "tool"}
    ultimo = next((m for m in reversed(mensajes) if m["role"] == "assistant"), {})
    return [ToolCall(tc["id"], tc["function"]["name"], _parsear(tc["function"]["arguments"]),
                     tc["function"]["arguments"])
            for tc in ultimo.get("tool_calls") or [] if tc["id"] not in respondidas]


# ---------------------------------------------------------------------------
# Nodos (ya resueltos: reutilizan C1)
# ---------------------------------------------------------------------------
def crear_nodos(cfg: ConfigAgente) -> dict:
    def agente_c1(s: EstadoAgente) -> Agente:
        return cfg.fabrica(s["pasajero_id"], s.get("nombre", ""), prompt=cfg.prompt, reglas=cfg.reglas,
                           herramientas=cfg.herramientas)

    def control(s: EstadoAgente) -> dict:
        """Las stopping rules de C1, como nodo: se evalúan antes de cada llamada al LLM."""
        motivo = cfg.reglas.evaluar(EstadoLoop(s.get("pasos", 0), s.get("costo_usd", 0.0),
                                               time.time() - s.get("inicio", time.time()), s.get("firmas", [])))
        return {"parada": motivo}

    def agente(s: EstadoAgente) -> dict:
        r = agente_c1(s).llamar_llm(s["mensajes"])
        cambios = {"mensajes": [r.mensaje], "pasos": s.get("pasos", 0) + 1,
                   "costo_usd": s.get("costo_usd", 0.0) + r.costo_usd}
        if not r.tool_calls:
            cambios.update(respuesta=r.texto, parada="respuesta")
        return cambios

    def herramientas(s: EstadoAgente) -> dict:
        """Ejecuta las tool_calls pendientes con el triage de C1. Avisa el progreso por el stream "custom"."""
        avisar = get_stream_writer()
        ag, nuevos, firmas, duro = agente_c1(s), [], list(s.get("firmas", [])), False
        for tc in tool_calls_pendientes(s["mensajes"]):
            if tc.id in s.get("overrides", {}):
                tc = ToolCall(tc.id, tc.nombre, s["overrides"][tc.id], tc.argumentos_raw)
            avisar({"herramienta": tc.nombre, "argumentos": tc.argumentos, "estado": "ejecutando"})

            def dormir(segundos: float, nombre: str = tc.nombre) -> None:
                avisar({"herramienta": nombre, "estado": f"sin respuesta, reintento en {segundos:.1f} s"})
                time.sleep(segundos)

            with trazas.observacion(tc.nombre, "tool", input=tc.argumentos) as o:     # C5: cada herramienta, observada
                res = ag.ejecutar(tc, dormir)
                o.registrar_tool(res)
            avisar({"herramienta": tc.nombre, "estado": "ok" if res.ok else res.decision, "intentos": len(res.intentos)})
            nuevos.append(mensaje_tool(tc.id, res.contenido))
            firmas.append(tc.firma)
            duro = duro or res.error_duro is not None
        return {"mensajes": nuevos, "firmas": firmas, **({"parada": "error_duro"} if duro else {})}

    def cierre(s: EstadoAgente) -> dict:
        r = agente_c1(s).cerrar(s["mensajes"], s["parada"])
        return {"mensajes": [r.mensaje], "respuesta": r.texto, "costo_usd": s.get("costo_usd", 0.0) + r.costo_usd}

    def escalar(s: EstadoAgente) -> dict:
        return {"mensajes": [{"role": "assistant", "content": DERIVACION}], "respuesta": DERIVACION}

    nodos = {"control": control, "agente": agente, "herramientas": herramientas, "cierre": cierre,
             "escalar": escalar, "aprobacion": nodo_aprobacion}
    # C5: cada nodo, una observación en la traza (salvo `control`, que no hace trabajo: sólo ensuciaría la traza).
    return {k: f if k == "control" else trazas.nodo(k, f) for k, f in nodos.items()}


# ---------------------------------------------------------------------------
# Rutas (edges condicionales)
# ---------------------------------------------------------------------------
def ruta_control(s: EstadoAgente) -> str:
    return "cierre" if s.get("parada") else "agente"


def ruta_herramientas(s: EstadoAgente) -> str:
    return "escalar" if s.get("parada") == "error_duro" else "control"


# ---------------------------------------------------------------------------
# EJERCICIO 1 · A dónde ir después de que el modelo habla
# ---------------------------------------------------------------------------
def ruta_agente(s: EstadoAgente) -> str:
    """"fin" si el modelo respondió sin pedir herramientas; "aprobacion" si alguna de las tool_calls
    pendientes es SENSIBLE (iniciar_reembolso); si no, "herramientas"."""
    # TODO:
    # pendientes = tool_calls_pendientes(s["mensajes"])
    # sin pendientes → "fin" · alguna con .nombre en SENSIBLES → "aprobacion" · si no → "herramientas"
    raise NotImplementedError("Ejercicio 1: ruta después del nodo agente")


# ---------------------------------------------------------------------------
# EJERCICIO 1 · Armar el grafo
# ---------------------------------------------------------------------------
def construir_grafo(cfg: ConfigAgente | None = None, checkpointer=None, con_control: bool = True):
    """Nodos: control, agente, herramientas, aprobacion, cierre, escalar (de `crear_nodos`).

    Edges:
      START → control
      control      ─(ruta_control)→      agente | cierre
      agente       ─(ruta_agente)→       herramientas | aprobacion | END ("fin")
      aprobacion   → herramientas
      herramientas ─(ruta_herramientas)→ control | escalar
      cierre → END · escalar → END
    `con_control=False` (C2 · Ej. 5): sin el nodo control → START → agente y herramientas → agente.
    Devuelve el grafo compilado con `checkpointer`.
    """
    cfg = cfg or ConfigAgente()
    nodos = crear_nodos(cfg)
    g = StateGraph(EstadoAgente)
    # TODO:
    # 1. g.add_node(nombre, fn) por cada nodo de `nodos` (con_control=False: sin "control" ni "cierre").
    # 2. entrada = "control" (o "agente" si con_control=False) → g.add_edge(START, entrada).
    # 3. con_control: g.add_conditional_edges("control", ruta_control, {"agente": "agente", "cierre": "cierre"})
    #    y g.add_edge("cierre", END).
    # 4. g.add_conditional_edges("agente", ruta_agente, {"herramientas": ..., "aprobacion": ..., "fin": END}).
    # 5. g.add_edge("aprobacion", "herramientas").
    # 6. g.add_conditional_edges("herramientas", ruta_herramientas, {"control": entrada, "escalar": "escalar"}).
    # 7. g.add_edge("escalar", END) y return g.compile(checkpointer=checkpointer).
    raise NotImplementedError("Ejercicio 1: armar el grafo")


# ---------------------------------------------------------------------------
# EJERCICIO 2 · Checkpointer
# ---------------------------------------------------------------------------
def abrir_checkpointer(tipo: str = "memoria", path: Path = RESULTS / "c2_checkpoints.db"):
    """"memoria": `InMemorySaver()` (vive lo que vive el proceso).
    "sqlite": `SqliteSaver` sobre `sqlite3.connect(path, check_same_thread=False)` (sobrevive al proceso).
    """
    # TODO:
    # "memoria" → InMemorySaver()
    # "sqlite"  → from langgraph.checkpoint.sqlite import SqliteSaver; crear la carpeta de `path`;
    #             SqliteSaver(sqlite3.connect(path, check_same_thread=False))
    # otro      → ValueError
    raise NotImplementedError("Ejercicio 2: checkpointer")


# ---------------------------------------------------------------------------
# EJERCICIO 3 · Human-in-the-loop
# ---------------------------------------------------------------------------
def nodo_aprobacion(s: EstadoAgente) -> dict:
    """Pausa el grafo antes de ejecutar una herramienta sensible y espera la decisión de un supervisor.

    1. Tomar la tool_call sensible pendiente (`tool_calls_pendientes` + `SENSIBLES`).
    2. `decision = interrupt({...})` con lo que el supervisor necesita para decidir: herramienta, argumentos,
       pasajero y la consulta original. El grafo se detiene acá; se reanuda con
       `grafo.invoke(Command(resume={"decision": ...}), config)` y `interrupt` devuelve ese dict.
    3. Según `decision["decision"]`:
       - "aprobar": no cambia nada (→ herramientas la ejecuta).
       - "editar":  `{"overrides": {tool_call_id: {**argumentos, **decision["argumentos"]}}}`.
       - "rechazar": responder la tool_call con un mensaje `tool` {"rechazado": True, "detalle": ...}
         para que herramientas NO la ejecute y el modelo sepa por qué.
    Ojo: al reanudar, el nodo se ejecuta DE NUEVO desde el principio; todo lo que esté antes de
    `interrupt` tiene que poder repetirse sin efectos.
    """
    # TODO (los 3 pasos del docstring):
    # tc = <la tool_call sensible pendiente>
    # consulta = <el último mensaje "user">
    # decision = interrupt({"herramienta": ..., "argumentos": ..., "pasajero_id": ..., "consulta": ...,
    #                       "tool_call_id": tc.id})
    # "editar"   → return {"overrides": {**s.get("overrides", {}), tc.id: {**tc.argumentos, **decision["argumentos"]}}}
    # "rechazar" → return {"mensajes": [mensaje_tool(tc.id, {"rechazado": True, "detalle": "..."})]}
    # "aprobar"  → return {}
    raise NotImplementedError("Ejercicio 3: human-in-the-loop")
