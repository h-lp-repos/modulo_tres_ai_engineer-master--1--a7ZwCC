"""C5 · Trazas: qué hizo el sistema, paso por paso, con su costo y su latencia.

EJERCICIO 1 · Completar `Observacion.registrar_llm()` y `Observacion.registrar_tool()`.

El modelo de datos es el de Langfuse (y el de OpenTelemetry, sobre el que está construido):

    SESIÓN  (session_id: una conversación; varios turnos)
     └─ TRAZA  (un turno: la consulta del pasajero → la respuesta; user_id, tags, metadata)
         └─ OBSERVACIONES anidadas, cada una con inicio, fin, input, output y nivel:
              span        · un paso (un nodo del grafo)
              agent       · un worker de C3
              generation  · una llamada al LLM: modelo, tokens, costo
              tool        · una herramienta: argumentos, resultado, reintentos, error
    SCORES  (sobre una traza o una sesión: "ruta_correcta = 1", "costo_usd = 0.004")

Doble escritura:
- LOCAL, siempre: cada traza queda en results/c5_trazas/<traza_id>.json y en un índice
  (results/c5_trazas/indice.jsonl). Los evals de C5 leen de acá: corren igual con o sin cuenta.
- LANGFUSE, si hay credenciales (LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY y LANGFUSE_BASE_URL en
  el .env; `ORBITAIR_TRAZAS=local` lo apaga): la misma traza se manda a Langfuse (Cloud o
  self-hosted) con el SDK oficial, para verla en la UI, filtrar por sesión y usar sus datasets.

Instrumentar es envolver: `llm.completar_con_tools` abre una generation, el nodo `herramientas`
de C2 abre un tool por llamada, los nodos de los grafos y los workers abren spans. El contexto
(¿dentro de qué traza estoy?) viaja en una ContextVar: llega también a los workers que LangGraph
corre en paralelo en otros hilos. Fuera de una traza, todo es un no-op: C1-C4 corren igual.
"""
from __future__ import annotations

import json
import os
import threading
import time
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any, Iterator

from dotenv import load_dotenv

load_dotenv()

RESULTS = Path(__file__).resolve().parents[2] / "results"
TRAZAS_DIR = RESULTS / "c5_trazas"
INDICE = TRAZAS_DIR / "indice.jsonl"
SCORES = RESULTS / "c5_scores.jsonl"

LANGFUSE = bool(os.getenv("LANGFUSE_PUBLIC_KEY") and os.getenv("LANGFUSE_SECRET_KEY")) \
    and os.getenv("ORBITAIR_TRAZAS", "") != "local"
_TIPOS_LANGFUSE = {"traza": "agent", "agent": "agent", "span": "span", "generation": "generation", "tool": "tool",
                   "chain": "chain", "retriever": "retriever"}


# ---------------------------------------------------------------------------
# Observación
# ---------------------------------------------------------------------------
@dataclass
class Observacion:
    nombre: str
    tipo: str                                  # traza, span, agent, generation, tool, chain
    traza_id: str
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:16])
    padre_id: str | None = None
    inicio: float = field(default_factory=time.time)
    fin: float | None = None
    input: Any = None
    output: Any = None
    metadata: dict = field(default_factory=dict)
    nivel: str = "DEFAULT"                     # DEFAULT, WARNING, ERROR (los niveles de Langfuse)
    estado: str | None = None                  # mensaje de estado: el error, "pausa (interrupt)"...
    modelo: str | None = None
    tokens_in: int = 0
    tokens_out: int = 0
    costo_usd: float = 0.0
    _lf: Any = field(default=None, repr=False)  # la observación de Langfuse espejo, si hay

    @property
    def duracion_s(self) -> float:
        return (self.fin or time.time()) - self.inicio

    def actualizar(self, **cambios) -> None:
        for k, v in cambios.items():
            setattr(self, k, v)

    # -----------------------------------------------------------------------
    # EJERCICIO 1 · Qué se registra de una llamada al LLM
    # -----------------------------------------------------------------------
    def registrar_llm(self, r) -> None:
        """`r` es la RespuestaLLM (orbitair/llm.py). Registrar en esta generation:
        - modelo (`r.modelo`), tokens_in, tokens_out y costo_usd (`r.costo_usd`): con eso Langfuse suma el costo
          por traza, por sesión y por usuario;
        - output: el texto y las tool_calls pedidas ({"texto": ..., "tool_calls": [{"nombre", "argumentos"}]}):
          sin las tool_calls, la traza no dice POR QUÉ el agente hizo lo que hizo;
        - metadata["latencia_s"] = r.latencia_s.
        """
        self.actualizar(modelo=r.modelo, tokens_in=r.tokens_in, tokens_out=r.tokens_out, costo_usd=r.costo_usd,
                        output={"texto": r.texto, "tool_calls": [{"nombre": t.nombre, "argumentos": t.argumentos}
                                                                 for t in r.tool_calls]})
        self.metadata["latencia_s"] = round(r.latencia_s, 3)

    # -----------------------------------------------------------------------
    # EJERCICIO 1 · Qué se registra de una herramienta
    # -----------------------------------------------------------------------
    def registrar_tool(self, res) -> None:
        """`res` es el ResultadoTool del triage de C1 (orbitair/errores.py). Registrar:
        - output: `res.contenido` (lo que vio el modelo);
        - metadata: `decision` del triage e `intentos` (cuántos, y el error de cada uno);
        - nivel "ERROR" si hubo error duro, "WARNING" si no salió bien al primer intento (reintento o error de
          entrada), y `estado` con el último error. Así en la UI se filtran las trazas con problemas.
        """
        self.output = res.contenido
        self.metadata.update(decision=res.decision, intentos=len(res.intentos),
                             errores=[i.error for i in res.intentos if i.error])
        if res.error_duro is not None:
            self.actualizar(nivel="ERROR", estado=str(res.error_duro))
        elif res.decision:
            self.actualizar(nivel="WARNING", estado=next((i.error for i in reversed(res.intentos) if i.error), None))

    def a_dict(self) -> dict:
        # No `asdict`: copiaría en profundidad `_lf` (el span de Langfuse, que no se puede copiar).
        return {f.name: getattr(self, f.name) for f in fields(self) if f.name != "_lf"}


class _Nula(Observacion):
    """Lo que devuelve `observacion()` fuera de una traza: acepta todo y no registra nada (C1-C4 corren igual)."""

    def actualizar(self, **cambios) -> None:
        pass

    def registrar_llm(self, r) -> None:
        pass

    def registrar_tool(self, res) -> None:
        pass


# ---------------------------------------------------------------------------
# Contexto y almacenamiento
# ---------------------------------------------------------------------------
_actual: ContextVar[Observacion | None] = ContextVar("orbitair_observacion_actual", default=None)
_abiertas: dict[str, list[Observacion]] = {}
_lock = threading.Lock()
_cliente_lf = None


def langfuse():
    """El cliente de Langfuse (lazy). Lee LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY y LANGFUSE_BASE_URL."""
    global _cliente_lf
    if _cliente_lf is None:
        from langfuse import get_client
        _cliente_lf = get_client()
    return _cliente_lf


def traza_actual() -> str | None:
    o = _actual.get()
    return o.traza_id if o else None


def _a_json(x: Any) -> Any:
    return json.loads(json.dumps(x, ensure_ascii=False, default=str))


def _cerrar_en_langfuse(o: Observacion) -> None:
    if o._lf is None:
        return
    extra = {}
    if o.tipo == "generation":
        extra = {"model": o.modelo, "usage_details": {"input": o.tokens_in, "output": o.tokens_out},
                 "cost_details": {"total": o.costo_usd}}
    o._lf.update(output=_a_json(o.output), metadata=_a_json(o.metadata), level=o.nivel,
                 status_message=o.estado, **extra)


@contextmanager
def _observar(o: Observacion, cm_langfuse=None) -> Iterator[Observacion]:
    token = _actual.set(o)
    lf_ctx = cm_langfuse.__enter__() if cm_langfuse is not None else None
    o._lf = lf_ctx
    try:
        yield o
    except BaseException as e:
        if type(e).__name__ == "GraphInterrupt":           # human-in-the-loop: no es un error
            o.actualizar(nivel="WARNING", estado="pausa (interrupt): esperando una decisión humana")
        else:
            o.actualizar(nivel="ERROR", estado=f"{type(e).__name__}: {e}")
        raise
    finally:
        o.fin = time.time()
        try:
            _cerrar_en_langfuse(o)
        finally:
            if cm_langfuse is not None:
                cm_langfuse.__exit__(None, None, None)
            _actual.reset(token)


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------
@contextmanager
def traza(nombre: str, *, session_id: str | None = None, user_id: str | None = None, input: Any = None,
          tags: list[str] | None = None, metadata: dict | None = None) -> Iterator[Observacion]:
    """Abre una TRAZA (un turno). Todo lo que se observe adentro queda anidado en ella.
    `session_id` agrupa trazas en una conversación; `user_id` (el pasajero) permite filtrar y sumar por usuario;
    `tags` y `metadata` (versión del sistema, id del caso del dataset…) permiten comparar corridas."""
    metadata = dict(metadata or {}, session_id=session_id, user_id=user_id, tags=list(tags or []))
    cm_lf, propagar = None, None
    if LANGFUSE:
        from langfuse import propagate_attributes
        cm_lf = langfuse().start_as_current_observation(as_type="agent", name=nombre, input=_a_json(input))
    raiz = Observacion(nombre, "traza", traza_id="", input=input, metadata=metadata)
    with _observar(raiz, cm_lf):
        if LANGFUSE:
            propagar = propagate_attributes(
                session_id=session_id, user_id=user_id, tags=list(tags or []), trace_name=nombre,
                metadata={k: str(v)[:200] for k, v in (metadata or {}).items()
                          if k not in ("session_id", "user_id", "tags")})
            propagar.__enter__()
        raiz.traza_id = (langfuse().get_current_trace_id() if LANGFUSE else None) or uuid.uuid4().hex
        with _lock:
            _abiertas[raiz.traza_id] = [raiz]
        try:
            yield raiz
        finally:
            if propagar is not None:
                propagar.__exit__(None, None, None)
    _guardar(raiz)


@contextmanager
def observacion(nombre: str, tipo: str = "span", *, input: Any = None, metadata: dict | None = None,
                modelo: str | None = None) -> Iterator[Observacion]:
    """Una observación hija de la actual. Sin traza activa no registra nada (no-op)."""
    padre = _actual.get()
    if padre is None:
        yield _Nula(nombre, tipo, traza_id="")                # fuera de una traza: no-op
        return
    o = Observacion(nombre, tipo, traza_id=padre.traza_id, padre_id=padre.id, input=input,
                    metadata=dict(metadata or {}), modelo=modelo)
    with _lock:
        _abiertas.setdefault(o.traza_id, []).append(o)
    cm_lf = None
    if LANGFUSE:
        cm_lf = langfuse().start_as_current_observation(
            as_type=_TIPOS_LANGFUSE.get(tipo, "span"), name=nombre, input=_a_json(input),
            **({"model": modelo} if tipo == "generation" and modelo else {}))
    with _observar(o, cm_lf):
        yield o


def nodo(nombre: str, fn, tipo: str = "span"):
    """Envuelve una función de nodo de LangGraph en una observación (para instrumentar un grafo sin tocarlo)."""
    def envuelto(estado):
        with observacion(nombre, tipo):
            return fn(estado)
    envuelto.__name__ = getattr(fn, "__name__", nombre)
    return envuelto


def puntuar(traza_id: str, nombre: str, valor: float | bool | str, comentario: str | None = None,
            session_id: str | None = None) -> None:
    """Un SCORE sobre una traza (o sobre una sesión, con `session_id`). Booleanos → 1/0 de tipo BOOLEAN."""
    tipo = "BOOLEAN" if isinstance(valor, bool) else "CATEGORICAL" if isinstance(valor, str) else "NUMERIC"
    v = float(valor) if not isinstance(valor, str) else valor
    RESULTS.mkdir(exist_ok=True)
    with _lock, open(SCORES, "a", encoding="utf-8") as f:
        f.write(json.dumps({"traza_id": traza_id, "session_id": session_id, "nombre": nombre, "valor": v,
                            "tipo": tipo, "comentario": comentario}, ensure_ascii=False) + "\n")
    if LANGFUSE:
        langfuse().create_score(name=nombre, value=v, data_type=tipo, comment=comentario,
                                **({"session_id": session_id} if session_id else {"trace_id": traza_id}))


def cerrar() -> None:
    """Antes de terminar el proceso: Langfuse manda en segundo plano y hay que vaciar la cola."""
    if LANGFUSE:
        langfuse().flush()


def url(traza_id: str) -> str | None:
    if not LANGFUSE:
        return None
    try:
        return langfuse().get_trace_url(trace_id=traza_id)
    except Exception:  # noqa: BLE001
        return None


# ---------------------------------------------------------------------------
# Almacenamiento local
# ---------------------------------------------------------------------------
def _guardar(raiz: Observacion) -> None:
    with _lock:
        obs = _abiertas.pop(raiz.traza_id, [raiz])
    TRAZAS_DIR.mkdir(parents=True, exist_ok=True)
    datos = [_a_json(o.a_dict()) for o in obs]
    (TRAZAS_DIR / f"{raiz.traza_id}.json").write_text(json.dumps(datos, ensure_ascii=False, indent=1),
                                                       encoding="utf-8")
    gens = [o for o in obs if o.tipo == "generation"]
    with _lock, open(INDICE, "a", encoding="utf-8") as f:
        f.write(json.dumps(_a_json({
            "traza_id": raiz.traza_id, "nombre": raiz.nombre, "session_id": raiz.metadata.get("session_id"),
            "user_id": raiz.metadata.get("user_id"), "tags": raiz.metadata.get("tags"), "metadata": raiz.metadata,
            "inicio": raiz.inicio, "latencia_s": raiz.duracion_s, "llamadas_llm": len(gens),
            "tokens": sum(o.tokens_in + o.tokens_out for o in gens), "costo_usd": sum(o.costo_usd for o in gens),
            "errores": sum(o.nivel == "ERROR" for o in obs), "advertencias": sum(o.nivel == "WARNING" for o in obs),
            "nivel": raiz.nivel, "output": raiz.output}), ensure_ascii=False) + "\n")


def limpiar() -> None:
    """Borra las trazas y los scores locales (para empezar un ejercicio de cero)."""
    if TRAZAS_DIR.exists():
        for p in TRAZAS_DIR.glob("*"):
            p.unlink()
    SCORES.unlink(missing_ok=True)


def leer_indice(filtro_tag: str | None = None) -> list[dict]:
    if not INDICE.exists():
        return []
    filas = [json.loads(l) for l in open(INDICE, encoding="utf-8") if l.strip()]
    return [f for f in filas if filtro_tag is None or filtro_tag in (f.get("tags") or [])]


def leer_traza(traza_id: str) -> list[dict]:
    return json.loads((TRAZAS_DIR / f"{traza_id}.json").read_text(encoding="utf-8"))


def leer_scores() -> list[dict]:
    return [json.loads(l) for l in open(SCORES, encoding="utf-8")] if SCORES.exists() else []


# ---------------------------------------------------------------------------
# La traza en la terminal (lo que muestra la UI de Langfuse, en texto)
# ---------------------------------------------------------------------------
_MARCAS = {"traza": "◆", "agent": "◇", "span": "·", "generation": "✦", "tool": "⚙", "chain": "·", "retriever": "⌕"}


def arbol(traza_id: str, ancho: int = 70) -> str:
    obs = leer_traza(traza_id)
    t0 = min(o["inicio"] for o in obs)
    hijos: dict[str | None, list[dict]] = {}
    for o in sorted(obs, key=lambda o: o["inicio"]):
        hijos.setdefault(o["padre_id"], []).append(o)
    lineas = []

    def detalle(o: dict) -> str:
        if o["tipo"] == "generation":
            pedidas = [t["nombre"] for t in (o["output"] or {}).get("tool_calls", [])]
            return (f"{o['tokens_in']}+{o['tokens_out']} tok · ${o['costo_usd']:.5f}"
                    + (f" → pide {', '.join(pedidas)}" if pedidas else " → responde"))
        if o["tipo"] == "retriever":
            return f"→ {', '.join(o['output'] or [])}"
        if o["tipo"] == "tool":
            return f"{json.dumps(o['input'], ensure_ascii=False)[:40]}" + (
                f" · {o['metadata'].get('intentos')} intentos" if (o["metadata"] or {}).get("intentos", 1) > 1 else "")
        return ""

    def visitar(o: dict, prefijo: str) -> None:
        marca = {"ERROR": " ✗", "WARNING": " ⚠"}.get(o["nivel"], "")
        desde, dur = o["inicio"] - t0, (o["fin"] or o["inicio"]) - o["inicio"]
        texto = f"{prefijo}{_MARCAS.get(o['tipo'], '·')} {o['nombre']}{marca}"
        lineas.append(f"{texto:<46} {desde:6.2f}s +{dur:5.2f}s  {detalle(o)}"[:ancho + 60]
                      + (f"\n{' ' * (len(prefijo) + 4)}{o['estado']}" if o["estado"] else ""))
        for h in hijos.get(o["id"], []):
            visitar(h, prefijo + "  ")

    for raiz in hijos.get(None, []):
        visitar(raiz, "")
    return "\n".join(lineas)
