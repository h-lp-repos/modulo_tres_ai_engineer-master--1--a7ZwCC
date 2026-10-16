"""C5 · Evals de agentes SOBRE TRAZAS: trayectoria, éxito end-to-end, costo por sesión y regresiones.

EJERCICIO 1 · Completar `atender()` (correr una consulta dentro de una traza, con sus atributos).
EJERCICIO 2 · Completar `resumen_sesiones()` (costo, latencia y llamadas por SESIÓN).
EJERCICIO 3 · Completar `trayectoria_de_traza()` y `evaluar_trayectoria()` (evals de trayectoria + scores).
EJERCICIO 4 · Completar `chequear_regresion()` (el gate contra la línea de base).

En el M1 se evaluaba una respuesta; en el M2, retrieval y generación por separado. Un agente
además DECIDE: a qué workers ir, qué herramientas usar, cuándo parar. Dos agentes pueden dar la
misma respuesta y uno haber consultado tres sistemas de más, o haber llegado de casualidad. Por
eso se evalúa la TRAYECTORIA, y se la lee de la TRAZA (no de un log armado aparte): la traza es
lo que pasó de verdad, y es lo mismo que se mira en producción.

    dataset etiquetado ──► el sistema corre, observado ──► trazas ──► trayectoria ──► scores
    (C3 + conversaciones)        (orbitair/trazas.py)                 (de la traza)    (a la traza)

Métricas por consulta (scores sobre la traza): ruta_correcta, herramientas_correctas,
parada_correcta, hechos (0..1), exito (las cuatro: éxito end-to-end), llamadas_llm, costo_usd,
cortes_por_regla (cuántas veces un worker terminó por una stopping rule).
Por SESIÓN: turnos, costo, latencia, éxito de la sesión (todos sus turnos).
"""
from __future__ import annotations

import json
import statistics
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from . import trazas
from .orquestador import entrada_orquestador
from .trayectoria import _norm, chequear

RESULTS = Path(__file__).resolve().parents[2] / "results"
EXPERIMENTOS = RESULTS / "c5_experimentos"
LINEA_BASE = RESULTS / "c5_linea_base.json"
DATASET_LANGFUSE = "orbitair-m3-trayectorias"

# Cuánto puede empeorar cada métrica antes de que el gate lo trate como regresión.
# Calidad (más es mejor): caída ABSOLUTA máxima. Costo / llamadas / latencia (menos es mejor): suba RELATIVA máxima.
# Conteos de comportamiento (cortes por una stopping rule): suba ABSOLUTA máxima. En un sistema sano es 0.
TOLERANCIAS = {"exito": 0.04, "ruta_correcta": 0.04, "hechos": 0.05,
               "costo_por_consulta": 0.15, "llamadas_por_consulta": 0.15, "latencia_p95_s": 0.25,
               "cortes_por_regla": 0}
MENOS_ES_MEJOR = {"costo_por_consulta", "llamadas_por_consulta", "latencia_p95_s"}
CONTEOS = {"cortes_por_regla"}


@dataclass
class Corrida:
    traza_id: str
    session_id: str
    caso_id: str | None
    latencia_s: float
    estado: dict                 # el estado final del orquestador


# ---------------------------------------------------------------------------
# EJERCICIO 1 · Atender una consulta, observada
# ---------------------------------------------------------------------------
def atender(grafo, consulta: str, pasajero_id: str, nombre: str = "", *, session_id: str,
            tags: list[str] | None = None, metadata: dict | None = None) -> Corrida:
    """Corre el orquestador para `consulta` DENTRO de una traza (`trazas.traza("consulta", ...)`) con:
    session_id, user_id=pasajero_id, input=consulta, tags y metadata. Adentro: `grafo.invoke(entrada_orquestador(
    consulta, pasajero_id, nombre))` y, al terminar, `t.output = {"respuesta": ..., "parada": ...}`.
    Devolver la Corrida (traza_id de la traza, caso_id = metadata["caso"] si está, latencia medida afuera)."""
    t0 = time.perf_counter()
    with trazas.traza("consulta", session_id=session_id, user_id=pasajero_id, input=consulta, tags=tags,
                      metadata=metadata) as t:
        s = grafo.invoke(entrada_orquestador(consulta, pasajero_id, nombre))
        t.output = {"respuesta": s["respuesta"], "parada": s["parada"]}
    return Corrida(t.traza_id, session_id, (metadata or {}).get("caso"), time.perf_counter() - t0, s)


def correr_conversaciones(grafo, conversaciones: list[dict], casos: dict[str, dict], nombres: dict[str, str],
                          version: str, tags: list[str] | None = None) -> list[Corrida]:
    """Cada conversación es una sesión; cada turno, una traza con su caso del dataset (ya resuelto)."""
    corridas = []
    for conv in conversaciones:
        session_id = f"{conv['id']}·{version}·{uuid.uuid4().hex[:4]}"
        for n, caso_id in enumerate(conv["turnos"], 1):
            caso = casos[caso_id]
            corridas.append(atender(grafo, caso["consulta"], conv["pasajero_id"], nombres[conv["pasajero_id"]],
                                    session_id=session_id, tags=[version, *(tags or [])],
                                    metadata={"caso": caso_id, "turno": n, "conversacion": conv["id"],
                                              "version": version}))
    return corridas


# ---------------------------------------------------------------------------
# EJERCICIO 2 · Costo por sesión
# ---------------------------------------------------------------------------
def resumen_sesiones(indice: list[dict]) -> list[dict]:
    """Agrupa las filas del índice de trazas (`trazas.leer_indice()`) por `session_id` y devuelve, por sesión:
    {"session_id", "user_id", "turnos", "llamadas_llm", "tokens", "costo_usd", "latencia_s", "errores",
     "advertencias"} (sumas de sus trazas), ordenado de la sesión más cara a la más barata.
    Es lo que Langfuse muestra en "Sessions": el costo de una conversación, no de una llamada."""
    sesiones: dict[str, dict] = {}
    for f in indice:
        s = sesiones.setdefault(f["session_id"], {"session_id": f["session_id"], "user_id": f["user_id"], "turnos": 0,
                                                  "llamadas_llm": 0, "tokens": 0, "costo_usd": 0.0, "latencia_s": 0.0,
                                                  "errores": 0, "advertencias": 0})
        s["turnos"] += 1
        for k in ("llamadas_llm", "tokens", "costo_usd", "latencia_s", "errores", "advertencias"):
            s[k] += f[k]
    return sorted(sesiones.values(), key=lambda s: -s["costo_usd"])


# ---------------------------------------------------------------------------
# EJERCICIO 3 · La trayectoria, leída de la traza
# ---------------------------------------------------------------------------
def trayectoria_de_traza(observaciones: list[dict]) -> dict:
    """De las observaciones de UNA traza (`trazas.leer_traza(id)`), reconstruir lo que hizo el sistema:
    - "dominios": el output de la observación "rutear" (lista de intenciones → sus `dominio`); [] si no hay;
    - "herramientas": los nombres de las observaciones de tipo "tool", en orden de inicio;
    - "parada" y "respuesta": del output de la raíz (la observación sin padre);
    - "llamadas_llm" (cuántas "generation"), "costo_usd" (su suma), "latencia_s" (duración de la raíz),
      "cortes_por_regla" (observaciones "cierre": un worker cortado por una stopping rule) y
      "errores_tool" (tools con nivel ERROR).
    """
    raiz = next(o for o in observaciones if o["padre_id"] is None)
    rutear = next((o for o in observaciones if o["nombre"] == "rutear"), None)
    gens = [o for o in observaciones if o["tipo"] == "generation"]
    tools = sorted((o for o in observaciones if o["tipo"] == "tool"), key=lambda o: o["inicio"])
    salida = raiz["output"] or {}
    return {"dominios": [i["dominio"] for i in (rutear or {}).get("output") or []],
            "herramientas": [o["nombre"] for o in tools], "parada": salida.get("parada"),
            "respuesta": salida.get("respuesta", ""), "llamadas_llm": len(gens),
            "costo_usd": sum(o["costo_usd"] for o in gens), "latencia_s": (raiz["fin"] or raiz["inicio"]) - raiz["inicio"],
            "cortes_por_regla": sum(o["nombre"] == "cierre" for o in observaciones),
            "errores_tool": sum(o["tipo"] == "tool" and o["nivel"] == "ERROR" for o in tools)}


# ---------------------------------------------------------------------------
# EJERCICIO 3 · Evaluar la trayectoria contra lo etiquetado
# ---------------------------------------------------------------------------
def evaluar_trayectoria(caso: dict, tray: dict) -> dict:
    """Scores de una traza contra su caso del dataset (C3):
    - "ruta_correcta": el CONJUNTO de dominios es el esperado (`caso["dominios"]`);
    - "herramientas_correctas", "parada_correcta": de `trayectoria.chequear(caso, ...)` (respeta `opcionales`);
    - "hechos": fracción de hechos esperados presentes en la respuesta (0..1; alternativas con "|",
      comparando con `_norm`), no sólo todo-o-nada: así se ve si la respuesta mejora de a poco;
    - "exito": ruta + herramientas + parada correctas y hechos == 1 (éxito END-TO-END);
    - y las de costo, sin juzgarlas: "llamadas_llm", "costo_usd", "cortes_por_regla".
    """
    ch = chequear(caso, tray["herramientas"], tray["parada"], tray["respuesta"])
    hechos = caso.get("hechos", [])
    presentes = sum(any(_norm(a) in _norm(tray["respuesta"]) for a in h.split("|")) for h in hechos)
    frac = presentes / len(hechos) if hechos else 1.0
    ruta = sorted(set(tray["dominios"])) == sorted(set(caso["dominios"]))
    return {"ruta_correcta": ruta, "herramientas_correctas": ch.herramientas_ok, "parada_correcta": ch.parada_ok,
            "hechos": frac, "exito": ruta and ch.herramientas_ok and ch.parada_ok and frac == 1.0,
            "llamadas_llm": tray["llamadas_llm"], "costo_usd": tray["costo_usd"],
            "cortes_por_regla": tray["cortes_por_regla"]}


def puntuar_traza(traza_id: str, evaluacion: dict) -> None:
    """Cada métrica, un score sobre la traza (en Langfuse: filtrables, graficables, comparables entre corridas)."""
    for nombre, valor in evaluacion.items():
        trazas.puntuar(traza_id, nombre, valor)


def metricas(evaluaciones: list[dict], latencias: list[float]) -> dict:
    """Agregados de una corrida: tasas (ruta, herramientas, parada, éxito), hechos medio, costo y llamadas por
    consulta, latencia p95."""
    n = len(evaluaciones)
    lat = sorted(latencias)
    return {"consultas": n,
            **{k: sum(e[k] for e in evaluaciones) / n for k in ("exito", "ruta_correcta", "herramientas_correctas",
                                                                 "parada_correcta", "hechos")},
            "costo_por_consulta": statistics.mean(e["costo_usd"] for e in evaluaciones),
            "llamadas_por_consulta": statistics.mean(e["llamadas_llm"] for e in evaluaciones),
            "cortes_por_regla": sum(e["cortes_por_regla"] for e in evaluaciones),
            "latencia_p95_s": lat[min(n - 1, int(0.95 * n))]}


# ---------------------------------------------------------------------------
# EJERCICIO 4 · El gate de regresión
# ---------------------------------------------------------------------------
def chequear_regresion(actual: dict, base: dict, tolerancias: dict = TOLERANCIAS) -> list[str]:
    """Una línea por cada métrica de `tolerancias` que empeoró más de lo tolerado respecto de `base`:
    - calidad (exito, ruta_correcta, hechos): regresión si actual < base - tolerancia (caída absoluta);
    - MENOS_ES_MEJOR (costo, llamadas, latencia): regresión si actual > base · (1 + tolerancia) (suba relativa);
    - CONTEOS (cortes_por_regla): regresión si actual > base + tolerancia (suba absoluta: con base 0, cualquier corte).
    Lista vacía: no hay regresión. Ej.: "costo_por_consulta: 0.00182 → 0.00231 (+27%, tolerancia +15%)".
    """
    problemas = []
    for m, tol in tolerancias.items():
        a, b = actual[m], base[m]
        if m in CONTEOS:
            if a > b + tol:
                problemas.append(f"{m}: {b} → {a} (tolerancia +{tol})")
        elif m in MENOS_ES_MEJOR:
            if a > b * (1 + tol):
                problemas.append(f"{m}: {b:.5g} → {a:.5g} ({(a / b - 1) * 100:+.0f}%, tolerancia +{tol:.0%})")
        elif a < b - tol:
            problemas.append(f"{m}: {b:.0%} → {a:.0%} ({(a - b) * 100:+.0f} pts, tolerancia -{tol * 100:.0f} pts)")
    return problemas


# ---------------------------------------------------------------------------
# Datasets y experimentos (ya resuelto)
# ---------------------------------------------------------------------------
def item_de_caso(caso: dict) -> dict:
    """Un caso de C3 como item de dataset: input (lo que entra), expected_output (la trayectoria esperada)."""
    return {"input": {"consulta": caso["consulta"], "pasajero_id": caso["pasajero_id"]},
            "expected_output": {k: caso[k] for k in ("dominios", "herramientas", "opcionales", "parada", "hechos")},
            "metadata": {"id": caso["id"], "tipo": caso["tipo"]}}


def subir_dataset(casos: list[dict]) -> str:
    """Local: results/c5_experimentos/dataset.jsonl. Con Langfuse, además, el dataset en Langfuse (los items
    llevan el id del caso como id: subirlo dos veces no duplica)."""
    EXPERIMENTOS.mkdir(parents=True, exist_ok=True)
    with open(EXPERIMENTOS / "dataset.jsonl", "w", encoding="utf-8") as f:
        f.writelines(json.dumps(item_de_caso(c), ensure_ascii=False) + "\n" for c in casos)
    if trazas.LANGFUSE:
        lf = trazas.langfuse()
        try:
            lf.create_dataset(name=DATASET_LANGFUSE, description="M3 · OrbitAir · consultas etiquetadas por trayectoria")
        except Exception:  # noqa: BLE001 — ya existe: los items se actualizan por id (upsert)
            pass
        for c in casos:
            it = item_de_caso(c)
            lf.create_dataset_item(dataset_name=DATASET_LANGFUSE, id=f"orbitair-{c['id']}", **it)
        return f"Langfuse: dataset '{DATASET_LANGFUSE}' ({len(casos)} items) + local"
    return f"local: {EXPERIMENTOS / 'dataset.jsonl'} ({len(casos)} items)"


def experimento(run: str, grafo, casos: list[dict], nombres: dict[str, str]) -> dict:
    """Corre el sistema sobre todos los casos, evalúa cada traza, puntúa y devuelve las métricas de la corrida.
    Con Langfuse usa `dataset.run_experiment` (la corrida queda vinculada al dataset y se compara en la UI)."""
    resultados: list[tuple[dict, Corrida, dict]] = []

    def tarea(caso: dict) -> dict:
        corrida = atender(grafo, caso["consulta"], caso["pasajero_id"], nombres[caso["pasajero_id"]],
                          session_id=f"exp·{run}·{caso['id']}", tags=[run, "experimento"],
                          metadata={"caso": caso["id"], "run": run})
        ev = evaluar_trayectoria(caso, trayectoria_de_traza(trazas.leer_traza(corrida.traza_id)))
        resultados.append((caso, corrida, ev))
        return ev

    if trazas.LANGFUSE:
        from langfuse import Evaluation
        por_id = {c["id"]: c for c in casos}
        dataset = trazas.langfuse().get_dataset(DATASET_LANGFUSE)
        dataset.run_experiment(
            name="trayectorias", run_name=run, max_concurrency=1,
            task=lambda *, item, **_: tarea(por_id[item.metadata["id"]]),
            evaluators=[lambda *, output, **_: [
                Evaluation(name=k, value=v, data_type="BOOLEAN") if isinstance(v, bool)
                else Evaluation(name=k, value=float(v), data_type="NUMERIC") for k, v in output.items()]])
    else:
        for c in casos:
            tarea(c)
            _, corrida, ev = resultados[-1]
            puntuar_traza(corrida.traza_id, ev)
    m = metricas([ev for *_, ev in resultados], [co.latencia_s for _, co, _ in resultados])
    EXPERIMENTOS.mkdir(parents=True, exist_ok=True)
    (EXPERIMENTOS / f"{run}.json").write_text(json.dumps(
        {"run": run, "metricas": m, "casos": [{"id": c["id"], "traza_id": co.traza_id, **ev}
                                              for c, co, ev in resultados]}, ensure_ascii=False, indent=1),
        encoding="utf-8")
    return m
