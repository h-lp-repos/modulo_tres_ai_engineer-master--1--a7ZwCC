"""C5 · Ejercicio 4 · Datasets y experimentos: comparar versiones con datos y frenar regresiones.

1. El dataset: las 25 consultas de C3 como items {input, expected_output, metadata}. Local siempre;
   con Langfuse, además un Dataset en Langfuse (los items no se duplican: van con id).
2. Un EXPERIMENTO corre una versión del sistema sobre todo el dataset: cada item, una traza con sus
   scores. Con Langfuse, la corrida queda vinculada al dataset y se compara en la UI.
3. La LÍNEA DE BASE: las métricas de la versión aprobada (results/c5_linea_base.json).
4. El GATE: una versión nueva no pasa si empeora más de lo tolerado en calidad, costo, llamadas o
   latencia (`chequear_regresion`). Con `--gate` el script sale con código 1: es lo que corre en CI
   antes de desplegar (los umbrales de regresión del M1 · C5, ahora para un agente).

Acá se comparan tres versiones contra la línea de base (v1, el orquestador de C3):
  v1-serie   · los mismos workers, en serie (C3 · Ej. 3): misma calidad, ¿y la latencia?
  v1-gpt-4.1 · el modelo grande en todos los agentes: ¿mejora la calidad lo que cuesta?

Uso:
  python src/c5/04_experimentos.py                       # v1 y v1-serie; fija la línea de base si no hay
  python src/c5/04_experimentos.py --fijar-linea-base    # vuelve a fijarla con la v1 de esta corrida
  python src/c5/04_experimentos.py --gate v1-serie       # sólo el gate sobre una corrida guardada (para CI)

Guarda results/c5_experimentos/<run>.json, results/c5_linea_base.json y results/c5_experimentos.md.
"""
import json
import sys
from contextlib import contextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))
from orbitair import llm, retrieval, trazas  # noqa: E402
from orbitair.data import load_consultas_c3  # noqa: E402
from orbitair.evals import (CONTEOS, EXPERIMENTOS, LINEA_BASE, MENOS_ES_MEJOR, TOLERANCIAS,  # noqa: E402
                            chequear_regresion, experimento, subir_dataset)
from orbitair.llm import MOCK, MODELO  # noqa: E402
from orbitair.operaciones import pasajero, reiniciar_db  # noqa: E402
from orbitair.orquestador import ConfigOrquestador, construir_orquestador  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")
RESULTS = Path(__file__).resolve().parents[2] / "results"
METRICAS = ["exito", "ruta_correcta", "herramientas_correctas", "hechos", "llamadas_por_consulta",
            "costo_por_consulta", "latencia_p95_s", "cortes_por_regla"]


def arg(flag: str, default=None):
    return sys.argv[sys.argv.index(flag) + 1] if flag in sys.argv else default


def fmt(m: str, v: float) -> str:
    return f"{v:.0%}" if m in ("exito", "ruta_correcta", "herramientas_correctas", "hechos") else \
        f"${v:.5f}" if m == "costo_por_consulta" else f"{v:.2f}" if isinstance(v, float) else str(v)


@contextmanager
def modelo(nombre: str | None):
    """Corre el experimento con otro modelo (debe estar en pricing.json). Sin nombre: el del .env."""
    anterior = llm.MODELO
    llm.MODELO = nombre or anterior
    try:
        yield
    finally:
        llm.MODELO = anterior


def gate(run: str, actual: dict, base: dict) -> bool:
    problemas = chequear_regresion(actual, base)
    if problemas:
        print(f"  ✗ GATE {run}: NO PASA ({len(problemas)} regresiones)")
        for p in problemas:
            print(f"      {p}")
    else:
        print(f"  ✓ GATE {run}: pasa")
    return not problemas


def main():
    if arg("--gate"):                                     # modo CI: sin correr nada
        run = arg("--gate")
        actual = json.loads((EXPERIMENTOS / f"{run}.json").read_text(encoding="utf-8"))["metricas"]
        base = json.loads(LINEA_BASE.read_text(encoding="utf-8"))
        sys.exit(0 if gate(run, actual, base["metricas"]) else 1)

    if MOCK:
        print("⚠ ORBITAIR_MOCK=1 → latencias simuladas y 'modelo' guionado: el mecanismo del gate es el mismo.\n")
    reiniciar_db()
    retrieval.indice()
    casos = load_consultas_c3()
    nombres = {c["pasajero_id"]: pasajero(c["pasajero_id"])["nombre"] for c in casos}
    print(f"Dataset: {subir_dataset(casos)}\nModelo {MODELO}\n")

    corridas = {}
    for run, cfg, nombre_modelo in [("v1", ConfigOrquestador(), None),
                                    ("v1-serie", ConfigOrquestador(paralelo=False), None),
                                    ("v1-gpt-4.1", ConfigOrquestador(), "gpt-4.1")]:
        print(f"── Experimento {run} ({len(casos)} items, modelo {nombre_modelo or llm.MODELO})…")
        with modelo(nombre_modelo):
            corridas[run] = experimento(run, construir_orquestador(cfg), casos, nombres)
    trazas.cerrar()

    if "--fijar-linea-base" in sys.argv or not LINEA_BASE.exists():
        LINEA_BASE.write_text(json.dumps({"run": "v1", "metricas": corridas["v1"]}, indent=1), encoding="utf-8")
        print(f"\nLínea de base fijada: v1 → {LINEA_BASE.name}")
    base = json.loads(LINEA_BASE.read_text(encoding="utf-8"))

    print(f"\n{'métrica':<24} {'línea de base':<15} " + " ".join(f"{r:<12}" for r in corridas))
    filas = []
    for m in METRICAS:
        print(f"{m:<24} {fmt(m, base['metricas'][m]):<15} " + " ".join(f"{fmt(m, c[m]):<12}" for c in corridas.values()))
        filas.append(f"| {m} | {fmt(m, base['metricas'][m])} | " + " | ".join(fmt(m, c[m]) for c in corridas.values()) + " |")
    print("\nTolerancias: " + ", ".join(f"{k} +{v}" if k in CONTEOS else f"{k} {'+' if k in MENOS_ES_MEJOR else '-'}{v:.0%}"
                                        for k, v in TOLERANCIAS.items()))
    resultados = {run: gate(run, m, base["metricas"]) for run, m in corridas.items()}

    RESULTS.mkdir(exist_ok=True)
    (RESULTS / "c5_experimentos.md").write_text("\n".join([
        "## C5 · Ejercicio 4 · Experimentos", "", f"- Modelo {MODELO}{' (MOCK)' if MOCK else ''} · línea de base: "
        f"{base['run']}", "", "| métrica | línea de base | " + " | ".join(corridas) + " |",
        "|---|---|" + "---|" * len(corridas), *filas, "",
        *[f"- gate {r}: {'pasa' if ok else 'NO PASA'}" for r, ok in resultados.items()]]), encoding="utf-8")
    print("\n✓ Guardado results/c5_experimentos.md · en CI: python src/c5/04_experimentos.py --gate <run>")


if __name__ == "__main__":
    main()
