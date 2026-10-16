"""C5 · Ejercicio 3 · Evals de trayectoria sobre las trazas: éxito end-to-end, por turno y por sesión.

Lee las trazas que dejó el Ejercicio 2 (no vuelve a correr el sistema): de cada traza reconstruye
la trayectoria (ruta, herramientas, parada, respuesta, costo) y la compara con lo etiquetado en
el dataset de C3. Cada métrica queda como SCORE sobre su traza (en Langfuse: filtrables y
comparables entre versiones). Después agrega:

- por consulta: tasa de éxito end-to-end, ruta, herramientas, parada, hechos; por tipo de consulta;
- por sesión: una conversación es exitosa si TODOS sus turnos lo son;
- las fallas, con su traza, para leerlas.

Uso:
  python src/c5/03_evals.py
  python src/c5/03_evals.py --version v1

Guarda results/c5_evals.md.
"""
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))
from orbitair import trazas  # noqa: E402
from orbitair.data import load_consultas_c3  # noqa: E402
from orbitair.evals import evaluar_trayectoria, metricas, puntuar_traza, trayectoria_de_traza  # noqa: E402
from orbitair.llm import MOCK, MODELO  # noqa: E402
from orbitair.trayectoria import marca  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")
RESULTS = Path(__file__).resolve().parents[2] / "results"


def arg(flag: str, default=None):
    return sys.argv[sys.argv.index(flag) + 1] if flag in sys.argv else default


def main():
    version = arg("--version", "v1")
    indice = sorted(trazas.leer_indice(version), key=lambda f: f["inicio"])
    if not indice:
        sys.exit(f"No hay trazas de la versión '{version}': correr antes c5/02_sesiones.py")
    if MOCK:
        print("⚠ ORBITAIR_MOCK=1 → con el guion el sistema acierta casi todo: el Ejercicio 5 trae una regresión de "
              "verdad. Con la API real, acá aparecen las fallas.\n")
    casos = {c["id"]: c for c in load_consultas_c3()}
    print(f"Modelo {MODELO} · {len(indice)} trazas de la versión '{version}' · evaluadas contra el dataset de C3\n")
    print(f"{'caso':<5} {'tipo':<11} {'ruta':<5} {'herr.':<6} {'parada':<7} {'hechos':<7} {'éxito':<6} {'LLM':<4} USD")
    evaluaciones, filas = [], []
    por_sesion: dict[str, list[bool]] = defaultdict(list)
    for f in indice:
        caso = casos[f["metadata"]["caso"]]
        tray = trayectoria_de_traza(trazas.leer_traza(f["traza_id"]))
        ev = evaluar_trayectoria(caso, tray)
        puntuar_traza(f["traza_id"], ev)
        evaluaciones.append((caso, f, ev))
        por_sesion[f["session_id"]].append(ev["exito"])
        print(f"{caso['id']:<5} {caso['tipo']:<11} {marca(ev['ruta_correcta']):<5} {marca(ev['herramientas_correctas']):<6} "
              f"{marca(ev['parada_correcta']):<7} {ev['hechos']:<7.0%} {marca(ev['exito']):<6} {ev['llamadas_llm']:<4} "
              f"${ev['costo_usd']:.5f}")
        filas.append(f"| {caso['id']} | {caso['tipo']} | {marca(ev['ruta_correcta'])} | "
                     f"{marca(ev['herramientas_correctas'])} | {marca(ev['parada_correcta'])} | {ev['hechos']:.0%} | "
                     f"{marca(ev['exito'])} | {ev['llamadas_llm']} | {ev['costo_usd']:.5f} |")
    for s, exitos in por_sesion.items():
        trazas.puntuar("", "sesion_exitosa", all(exitos), session_id=s)
    trazas.cerrar()

    m = metricas([ev for *_, ev in evaluaciones], [f["latencia_s"] for _, f, _ in evaluaciones])
    print(f"\nÉxito end-to-end {m['exito']:.0%} · ruta {m['ruta_correcta']:.0%} · herramientas "
          f"{m['herramientas_correctas']:.0%} · parada {m['parada_correcta']:.0%} · hechos {m['hechos']:.0%} · "
          f"{m['llamadas_por_consulta']:.1f} LLM y ${m['costo_por_consulta']:.5f} por consulta · p95 {m['latencia_p95_s']:.2f} s")
    print("Por tipo: " + " · ".join(
        f"{t} {sum(e['exito'] for c, _, e in evaluaciones if c['tipo'] == t)}/{sum(c['tipo'] == t for c, *_ in evaluaciones)}"
        for t in ("un_dominio", "cruce", "otros")))
    sesiones_ok = sum(all(v) for v in por_sesion.values())
    print(f"Sesiones exitosas (todos sus turnos): {sesiones_ok}/{len(por_sesion)}")

    fallas = [(c, f, e) for c, f, e in evaluaciones if not e["exito"]]
    if fallas:
        print(f"\nFallas ({len(fallas)}): leer la traza antes de concluir (¿falló el agente o la etiqueta?)")
        for c, f, e in fallas:
            que = [k for k in ("ruta_correcta", "herramientas_correctas", "parada_correcta") if not e[k]]
            que += [f"hechos {e['hechos']:.0%}"] if e["hechos"] < 1 else []
            print(f"  {c['id']} · {', '.join(que)} · traza {f['traza_id']}" + (
                f" · {trazas.url(f['traza_id'])}" if trazas.LANGFUSE else ""))
        print(f"\n  La primera, abierta:\n\n  " + trazas.arbol(fallas[0][1]["traza_id"]).replace("\n", "\n  "))
    else:
        print("\nSin fallas en esta corrida.")

    RESULTS.mkdir(exist_ok=True)
    (RESULTS / "c5_evals.md").write_text("\n".join([
        "## C5 · Ejercicio 3 · Evals de trayectoria", "", f"- Modelo {MODELO}{' (MOCK)' if MOCK else ''} · versión {version}",
        "", "| caso | tipo | ruta | herramientas | parada | hechos | éxito | LLM | USD |", "|---|---|---|---|---|---|---|---|---|",
        *filas, "", f"Éxito end-to-end {m['exito']:.0%} · ruta {m['ruta_correcta']:.0%} · sesiones exitosas "
        f"{sesiones_ok}/{len(por_sesion)} · USD por consulta {m['costo_por_consulta']:.5f}"]), encoding="utf-8")
    print("\n✓ Scores guardados en las trazas (results/c5_scores.jsonl) y tabla en results/c5_evals.md")


if __name__ == "__main__":
    main()
