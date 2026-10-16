"""C3 · El sistema multiagente de OrbitAir: orquestador + 3 workers, con routing por intención y paralelismo.

EJERCICIO 2 · Completar `validar_ruteo()` y `rutear()` (routing por intención).
EJERCICIO 3 · Completar `asignar_workers()` y `construir_orquestador()` (fan-out en paralelo con Send).

Patrón orquestador-workers:

                                ┌──► worker equipaje ───┐
    START ──► rutear ──(Send)───┼──► worker cambios ────┼──► sintetizar ──► END
                 │              └──► worker reembolsos ─┘
                 └──► fuera_de_alcance ──► END            (dominio "otros": sin LLM)

1. RUTEAR (una llamada al LLM, con salida estructurada): ¿qué dominios toca la consulta y qué
   parte le toca a cada uno? Es el triage del M1 (equipaje / cambios / reembolsos / otros),
   ahora multi-etiqueta: "perdí la valija en el vuelo que me demoraron" son DOS intenciones.
2. WORKERS (orbitair/workers.py): cada intención va a su especialista — el grafo de C2 con su
   prompt, sus herramientas y su retrieval filtrado. Con `Send` corren EN PARALELO: la latencia
   es la del worker más lento, no la suma.
3. SINTETIZAR: si hubo más de un worker, una llamada más combina las respuestas en una sola.
   Si hubo uno, su respuesta pasa directo (no se paga una síntesis que no sintetiza nada).

El estado del orquestador acumula los resultados de los workers con un reducer
(`operator.add`): cada worker devuelve SU resultado y LangGraph los junta, aunque terminen
en cualquier orden. Lo mismo con el costo y las llamadas al LLM: el costo por consulta del
sistema es la suma de todos los agentes que intervinieron.
"""
from __future__ import annotations

import operator
import time
from dataclasses import dataclass
from functools import lru_cache
from typing import Annotated, Callable, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from . import trazas
from .agente import DERIVACION
from .grafo import entrada_turno, construir_grafo
from .historial import observaciones
from .llm import RespuestaLLM, completar_con_tools
from .workers import DOMINIOS, config_worker

FUERA_DE_ALCANCE = ("Solo puedo ayudarte con consultas sobre vuelos, equipaje, reservas, reembolsos y políticas de "
                    "OrbitAir. ¿Tenés alguna consulta sobre tu viaje?")
MARCA_TAREA = "[Orquestador]"        # así llega la tarea al worker (el mock la reconoce)

# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------
SISTEMA_ROUTER = """Sos el orquestador del centro de atención de OrbitAir. No le respondés al pasajero: decidís qué
especialistas tienen que intervenir y qué parte de la consulta resuelve cada uno.

Especialistas:
""" + "\n".join(f"- {d.nombre}: {d.descripcion}" for d in DOMINIOS.values()) + """
- otros: saludos o consultas que no son sobre OrbitAir (no tiene especialista).

Reglas:
- Una consulta puede tener varias partes: asigná un especialista por parte, sin repetir especialista.
- Usá el mínimo necesario: si una parte la resuelve un especialista, no agregues otro "por las dudas".
- En cada tarea escribí qué tiene que resolver ese especialista y copiá los códigos que necesita (vuelo OA…,
  valija OA-…, PIR, reserva), aunque en la consulta aparezcan en otra parte.
- Si la consulta es sólo "otros", devolvé únicamente "otros".

Ejemplo: "Perdí la valija OA-123456 en el OA0100, que salió 5 horas tarde. ¿Qué me cubren?" →
equipaje: "estado de la valija OA-123456 y gastos que cubre OrbitAir por equipaje demorado";
reembolsos: "asistencia o compensación que corresponde por la demora del vuelo OA0100"."""

SISTEMA_SINTESIS = """Sos el redactor final del centro de atención de OrbitAir. Recibís la consulta del pasajero y las
respuestas de los especialistas que la resolvieron por partes. Escribí UNA respuesta al pasajero que:
- responda todas las partes, en el orden de la consulta;
- use sólo lo que dicen los especialistas: no agregues datos, montos ni plazos;
- conserve las citas a la política entre corchetes, ej. [POL-RE-01#8.1];
- si un especialista derivó a un agente humano, mantené esa derivación.
Español, cordial, sin repetir saludos: hasta 7 oraciones."""


def spec_router() -> dict:
    """La salida estructurada del router, como una herramienta que el modelo está OBLIGADO a llamar."""
    return {"type": "function", "function": {
        "name": "rutear_consulta",
        "description": "Asigna cada parte de la consulta del pasajero al especialista que la resuelve.",
        "parameters": {"type": "object", "additionalProperties": False, "required": ["intenciones"], "properties": {
            "intenciones": {"type": "array", "minItems": 1, "items": {
                "type": "object", "additionalProperties": False, "required": ["dominio", "tarea"],
                "properties": {"dominio": {"type": "string", "enum": [*DOMINIOS, "otros"]},
                               "tarea": {"type": "string",
                                         "description": "Qué parte resuelve este especialista, con los códigos."}}}}}}}}


# ---------------------------------------------------------------------------
# EJERCICIO 2 · Routing por intención
# ---------------------------------------------------------------------------
@dataclass
class Ruteo:
    intenciones: list[dict]               # [{"dominio": ..., "tarea": ...}], ya validadas
    llm: RespuestaLLM | None = None
    descartadas: list[dict] | None = None  # lo que propuso el modelo y no pasó la validación

    @property
    def dominios(self) -> list[str]:
        return [i["dominio"] for i in self.intenciones]


def validar_ruteo(propuestas: object, consulta: str) -> tuple[list[dict], list[dict]]:
    """La salida del router es un CONTRATO (M1 · C3): se valida antes de usarla. Devuelve (válidas, descartadas).

    - Cada intención: dict con `dominio` en DOMINIOS u "otros" y `tarea` string; si no, se descarta.
    - Un dominio repetido se une en una sola intención (las tareas se concatenan con " · ").
    - "otros" junto a dominios reales se descarta (la consulta sí es sobre OrbitAir).
    - Sin ninguna válida (o si `propuestas` no es una lista): [{"dominio": "otros", "tarea": consulta}].
      Fail closed: lo que no se entiende no se manda a un worker a improvisar.
    """
    # TODO:
    # validas: dict[dominio, intención] (para unir los repetidos) · descartadas: list (si no es lista: [propuestas])
    # por cada p: si no es dict, o p["dominio"] no está en (*DOMINIOS, "otros"), o p["tarea"] no es str → descartar
    #             si el dominio ya está → validas[d]["tarea"] += " · " + p["tarea"]; si no → agregarlo
    # si hay "otros" y algún otro dominio → descartar "otros"
    # return list(validas.values()) or [{"dominio": "otros", "tarea": consulta}], descartadas
    raise NotImplementedError("Ejercicio 2: validar la salida del router")


def rutear(consulta: str) -> Ruteo:
    """Una llamada al LLM con `spec_router()` y `tool_choice` FORZADO a "rutear_consulta":
    `{"type": "function", "function": {"name": "rutear_consulta"}}` (el modelo no puede contestar con texto).
    Mensajes: system SISTEMA_ROUTER + user con la consulta. Tomar `argumentos["intenciones"]` de la primera
    tool_call (si no hay, None), validarlas con `validar_ruteo` y devolver el Ruteo con la RespuestaLLM.
    """
    # TODO:
    # r = completar_con_tools([{"role": "system", "content": SISTEMA_ROUTER}, {"role": "user", "content": consulta}],
    #                         [spec_router()], tool_choice={"type": "function", "function": {"name": "rutear_consulta"}},
    #                         max_tokens=300)
    # propuestas = r.tool_calls[0].argumentos.get("intenciones") if r.tool_calls else None
    # validas, descartadas = validar_ruteo(propuestas, consulta)
    # return Ruteo(validas, r, descartadas)
    raise NotImplementedError("Ejercicio 2: routing por intención")


# ---------------------------------------------------------------------------
# Estado
# ---------------------------------------------------------------------------
class ResultadoWorker(TypedDict):
    dominio: str
    tarea: str
    respuesta: str
    parada: str
    herramientas: list[str]
    pasos: int
    costo_usd: float
    inicio_s: float          # desde el comienzo de la consulta (para ver el paralelismo)
    fin_s: float


class EstadoOrquestador(TypedDict, total=False):
    consulta: str
    pasajero_id: str
    nombre: str
    t0: float
    intenciones: list[dict]
    resultados: Annotated[list[ResultadoWorker], operator.add]     # cada worker suma el suyo
    costo_usd: Annotated[float, operator.add]                      # router + workers + síntesis
    llamadas_llm: Annotated[int, operator.add]
    respuesta: str
    parada: str


class TareaWorker(TypedDict):
    """Lo que recibe cada worker por `Send`: su propio estado, no el del orquestador."""
    dominio: str
    tarea: str
    consulta: str
    pasajero_id: str
    nombre: str
    t0: float


def entrada_orquestador(consulta: str, pasajero_id: str, nombre: str = "") -> EstadoOrquestador:
    return {"consulta": consulta, "pasajero_id": pasajero_id, "nombre": nombre, "t0": time.perf_counter(),
            "resultados": [], "costo_usd": 0.0, "llamadas_llm": 0}


@dataclass(frozen=True)
class ConfigOrquestador:
    paralelo: bool = True               # False: los workers corren uno detrás de otro (C3 · Ej. 3)
    max_workers: int | None = None      # 1: "router" puro, un solo especialista y sin síntesis (C3 · Ej. 4)
    acciones: bool = False              # True: el worker de reembolsos puede iniciar_reembolso (C3 · Ej. 5)
    retrieval_modo: str = "hibrida"
    # C4: (dominio, pasajero_id) → grafo del worker, o None para el de C3. Así un worker usa el server MCP.
    fabrica_worker: Callable[[str, str], object] | None = None


@lru_cache(maxsize=None)
def grafo_worker(dominio: str, acciones: bool = False, retrieval_modo: str = "hibrida"):
    """El grafo de C2 del worker, compilado una vez. SIN checkpointer propio: si el orquestador tiene uno,
    el subgrafo lo hereda (así un interrupt adentro del worker pausa todo el sistema, C3 · Ej. 5)."""
    return construir_grafo(config_worker(dominio, acciones, retrieval_modo))


def correr_worker(t: TareaWorker, cfg: ConfigOrquestador) -> ResultadoWorker:
    """Corre el worker de `t["dominio"]` sobre su tarea (lo usan el nodo paralelo y el en serie)."""
    inicio = time.perf_counter() - t["t0"]
    mensaje = f"{MARCA_TAREA} Consulta del pasajero: «{t['consulta']}»\nTu parte ({t['dominio']}): {t['tarea']}"
    grafo = cfg.fabrica_worker(t["dominio"], t["pasajero_id"]) if cfg.fabrica_worker else None
    with trazas.observacion(f"worker {t['dominio']}", "agent", input=t["tarea"]) as o:     # C5: un span por worker
        final = (grafo or grafo_worker(t["dominio"], cfg.acciones, cfg.retrieval_modo)).invoke(
            entrada_turno(mensaje, t["pasajero_id"], t["nombre"]))
        o.actualizar(output=final["respuesta"], metadata={"parada": final["parada"], "pasos": final["pasos"]})
    return {"dominio": t["dominio"], "tarea": t["tarea"], "respuesta": final["respuesta"], "parada": final["parada"],
            "herramientas": [o.nombre for o in observaciones(final["mensajes"])], "pasos": final["pasos"],
            "costo_usd": final["costo_usd"], "inicio_s": inicio, "fin_s": time.perf_counter() - t["t0"]}


def _llamadas(r: ResultadoWorker) -> int:
    """Llamadas al LLM de un worker: sus pasos, más el cierre si lo cortó una stopping rule."""
    return r["pasos"] + (r["parada"] not in ("respuesta", "error_duro"))


# ---------------------------------------------------------------------------
# Nodos (ya resueltos)
# ---------------------------------------------------------------------------
def crear_nodos(cfg: ConfigOrquestador) -> dict:
    def nodo_rutear(s: EstadoOrquestador) -> dict:
        r = rutear(s["consulta"])
        intenciones = r.intenciones[:cfg.max_workers] if cfg.max_workers else r.intenciones
        return {"intenciones": intenciones, "costo_usd": r.llm.costo_usd if r.llm else 0.0,
                "llamadas_llm": 1 if r.llm else 0}

    def worker(t: TareaWorker) -> dict:
        r = correr_worker(t, cfg)
        return {"resultados": [r], "costo_usd": r["costo_usd"], "llamadas_llm": _llamadas(r)}

    def workers_en_serie(s: EstadoOrquestador) -> dict:
        rs = [correr_worker({**i, "consulta": s["consulta"], "pasajero_id": s["pasajero_id"],
                             "nombre": s.get("nombre", ""), "t0": s["t0"]}, cfg)
              for i in s["intenciones"] if i["dominio"] in DOMINIOS]
        return {"resultados": rs, "costo_usd": sum(r["costo_usd"] for r in rs),
                "llamadas_llm": sum(_llamadas(r) for r in rs)}

    def sintetizar(s: EstadoOrquestador) -> dict:
        orden = [i["dominio"] for i in s["intenciones"]]
        rs = sorted(s["resultados"], key=lambda r: orden.index(r["dominio"]))
        parada = "error_duro" if any(r["parada"] == "error_duro" for r in rs) else "respuesta"
        if len(rs) == 1:
            return {"respuesta": rs[0]["respuesta"], "parada": parada}
        partes = "\n\n".join(f"Respuesta del especialista en {r['dominio']} (su parte: {r['tarea']}):\n{r['respuesta']}"
                             for r in rs)
        llm = completar_con_tools([{"role": "system", "content": SISTEMA_SINTESIS},
                                   {"role": "user", "content": f"Consulta del pasajero: «{s['consulta']}»\n\n{partes}"}],
                                  max_tokens=600)
        return {"respuesta": llm.texto, "parada": parada, "costo_usd": llm.costo_usd, "llamadas_llm": 1}

    def fuera_de_alcance(s: EstadoOrquestador) -> dict:
        return {"respuesta": FUERA_DE_ALCANCE, "parada": "respuesta"}

    def rutear_observado(s: EstadoOrquestador) -> dict:
        with trazas.observacion("rutear", "chain", input=s["consulta"]) as o:
            cambios = nodo_rutear(s)
            o.output = cambios["intenciones"]        # C5 · Ej. 3: los evals leen la ruta de acá
        return cambios

    # C5: el router, la síntesis y el fuera de alcance, observados (los workers abren su span en correr_worker).
    return {"rutear": rutear_observado, "worker": worker, "workers_en_serie": workers_en_serie,
            "sintetizar": trazas.nodo("sintetizar", sintetizar), "fuera_de_alcance": trazas.nodo("fuera_de_alcance",
                                                                                                 fuera_de_alcance)}


# ---------------------------------------------------------------------------
# EJERCICIO 3 · Fan-out: un Send por intención
# ---------------------------------------------------------------------------
def asignar_workers(s: EstadoOrquestador) -> list[Send] | str:
    """Edge condicional después de `rutear`.

    - Sin intenciones de un dominio con worker (sólo "otros") → "fuera_de_alcance".
    - Si no, un `Send("worker", TareaWorker)` por intención: dominio y tarea de la intención, más consulta,
      pasajero_id, nombre y t0 del estado. Cada Send es una ejecución del nodo `worker` con SU estado;
      LangGraph corre todos los Send del mismo paso en paralelo.
    """
    # TODO:
    # intenciones = las de s["intenciones"] cuyo dominio está en DOMINIOS
    # sin intenciones → return "fuera_de_alcance"
    # return [Send("worker", {"dominio": ..., "tarea": ..., "consulta": s["consulta"], "pasajero_id": s["pasajero_id"],
    #                         "nombre": s.get("nombre", ""), "t0": s["t0"]}) for i in intenciones]
    raise NotImplementedError("Ejercicio 3: fan-out con Send")


def ruta_en_serie(s: EstadoOrquestador) -> str:
    return "workers_en_serie" if any(i["dominio"] in DOMINIOS for i in s.get("intenciones", [])) \
        else "fuera_de_alcance"


# ---------------------------------------------------------------------------
# EJERCICIO 3 · Armar el orquestador
# ---------------------------------------------------------------------------
def construir_orquestador(cfg: ConfigOrquestador | None = None, checkpointer=None):
    """Nodos de `crear_nodos(cfg)`. Edges:

      START → rutear
      rutear ─(asignar_workers)→ worker (N veces, en paralelo) | fuera_de_alcance
      worker → sintetizar → END · fuera_de_alcance → END
    `cfg.paralelo=False`: en lugar de `worker`, el nodo `workers_en_serie` con `ruta_en_serie`
      (rutear ─→ workers_en_serie | fuera_de_alcance; workers_en_serie → sintetizar).
    Ojo: con Send, `add_conditional_edges` necesita la lista de destinos posibles: ["worker", "fuera_de_alcance"].
    """
    # TODO:
    # cfg = cfg or ConfigOrquestador(); nodos = crear_nodos(cfg)
    # ejecutor = "worker" si cfg.paralelo, si no "workers_en_serie"
    # g = StateGraph(EstadoOrquestador); add_node de "rutear", ejecutor, "sintetizar", "fuera_de_alcance"
    # g.add_edge(START, "rutear")
    # g.add_conditional_edges("rutear", asignar_workers (o ruta_en_serie), [ejecutor, "fuera_de_alcance"])
    # g.add_edge(ejecutor, "sintetizar"); g.add_edge("sintetizar", END); g.add_edge("fuera_de_alcance", END)
    # return g.compile(checkpointer=checkpointer)
    raise NotImplementedError("Ejercicio 3: armar el orquestador")


# ---------------------------------------------------------------------------
# Resumen de una corrida (para los scripts)
# ---------------------------------------------------------------------------
def resumen(s: EstadoOrquestador) -> dict:
    rs = s.get("resultados", [])
    return {"dominios": [i["dominio"] for i in s.get("intenciones", [])],
            "herramientas": [h for r in rs for h in r["herramientas"]], "parada": s.get("parada"),
            "respuesta": s.get("respuesta", ""), "costo_usd": s.get("costo_usd", 0.0),
            "llamadas_llm": s.get("llamadas_llm", 0), "derivo": any(r["respuesta"] == DERIVACION for r in rs)}
