"""C3 · Ejercicio 4 · ¿Se justifica el grafo multiagente? Tres arquitecturas, el mismo dataset, con datos.

  agente único  · el grafo de C2 con las 4 herramientas y el MISMO retrieval híbrido (todo el corpus).
  router        · rutear → UN worker (el primer dominio) → respuesta. Sin paralelismo ni síntesis.
  orquestador   · rutear → N workers en paralelo → síntesis.

Las tres comparten modelo, herramientas y retrieval: la única variable es la arquitectura.
Se mide por tipo de consulta (un dominio / cruce / otros): éxito (trayectoria + hechos),
llamadas al LLM, USD y latencia. Y se proyecta según la MEZCLA de tráfico: cuánto de lo que
llega de verdad cruza dominios es lo que decide si el orquestador paga lo que cuesta.

Uso:
  python src/c3/04_se_justifica.py
  python src/c3/04_se_justifica.py --cruces 0.05      # proyección con 5% de consultas que cruzan dominios

Guarda results/c3_arquitecturas.md.
"""
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))
from orbitair import retrieval  # noqa: E402
from orbitair.data import load_consultas_c3  # noqa: E402
from orbitair.grafo import construir_grafo, entrada_turno  # noqa: E402
from orbitair.historial import observaciones  # noqa: E402
from orbitair.llm import MOCK, MODELO  # noqa: E402
from orbitair.operaciones import pasajero, reiniciar_db  # noqa: E402
from orbitair.orquestador import ConfigOrquestador, construir_orquestador, entrada_orquestador, resumen  # noqa: E402
from orbitair.trayectoria import chequear, marca  # noqa: E402
from orbitair.workers import config_worker  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")
RESULTS = Path(__file__).resolve().parents[2] / "results"
TIPOS = ("un_dominio", "cruce", "otros")


def arg(flag: str, default=None):
    return sys.argv[sys.argv.index(flag) + 1] if flag in sys.argv else default


def arquitecturas() -> dict:
    unico = construir_grafo(config_worker(None))
    router = construir_orquestador(ConfigOrquestador(max_workers=1))
    orquestador = construir_orquestador()

    def correr_unico(c, nombre):
        s = unico.invoke(entrada_turno(c["consulta"], c["pasajero_id"], nombre))
        llamadas = s["pasos"] + (s["parada"] not in ("respuesta", "error_duro"))
        return [o.nombre for o in observaciones(s["mensajes"])], s["parada"], s["respuesta"], s["costo_usd"], llamadas

    def correr_orq(grafo):
        def f(c, nombre):
            r = resumen(grafo.invoke(entrada_orquestador(c["consulta"], c["pasajero_id"], nombre)))
            return r["herramientas"], r["parada"], r["respuesta"], r["costo_usd"], r["llamadas_llm"]
        return f

    return {"agente único": correr_unico, "router": correr_orq(router), "orquestador": correr_orq(orquestador)}


def main():
    if MOCK:
        print("⚠ ORBITAIR_MOCK=1 → los tres usan el mismo 'modelo' guionado: la comparación muestra el MECANISMO "
              "(cuántas llamadas, qué se pierde). Re-correr con la API real antes de concluir.\n")
    reiniciar_db()
    retrieval.indice()
    casos = load_consultas_c3()
    arqs = arquitecturas()
    print(f"Modelo {MODELO} · {len(casos)} consultas · {', '.join(arqs)}\n")
    print(f"{'id':<5} {'tipo':<11} " + " ".join(f"{a:<24}" for a in arqs))
    m = {a: {t: [] for t in TIPOS} for a in arqs}
    filas = []
    for c in casos:
        nombre = pasajero(c["pasajero_id"])["nombre"]
        celdas = []
        for a, correr in arqs.items():
            t0 = time.perf_counter()
            herramientas, parada, respuesta, usd, llamadas = correr(c, nombre)
            lat = time.perf_counter() - t0
            ok = chequear(c, herramientas, parada, respuesta).ok
            m[a][c["tipo"]].append((ok, usd, llamadas, lat))
            celdas.append(f"{marca(ok)} {llamadas} LLM · {lat:.2f} s")
        print(f"{c['id']:<5} {c['tipo']:<11} " + " ".join(f"{x:<24}" for x in celdas))
        filas.append(f"| {c['id']} | {c['tipo']} | " + " | ".join(celdas) + " |")

    print(f"\n{'arquitectura':<13} {'tipo':<11} {'éxito':<7} {'LLM/consulta':<13} {'USD/consulta':<13} {'p50 (s)':<8} p95 (s)")
    tabla = []
    for a in arqs:
        for t in TIPOS:
            xs = m[a][t]
            lat = sorted(x[3] for x in xs)
            fila = (a, t, f"{sum(x[0] for x in xs)}/{len(xs)}", f"{statistics.mean(x[2] for x in xs):.1f}",
                    f"{statistics.mean(x[1] for x in xs):.5f}", f"{statistics.median(lat):.2f}",
                    f"{lat[min(len(lat) - 1, int(0.95 * len(lat)))]:.2f}")
            print(f"{fila[0]:<13} {fila[1]:<11} {fila[2]:<7} {fila[3]:<13} {fila[4]:<13} {fila[5]:<8} {fila[6]}")
            tabla.append("| " + " | ".join(fila) + " |")

    # Proyección por mezcla de tráfico: el dataset tiene 9/25 cruces a propósito; la realidad suele tener menos.
    cruces = float(arg("--cruces", 0.10))
    print(f"\nProyección con {cruces:.0%} de consultas que cruzan dominios (y el resto de un dominio):")
    proy = []
    for a in arqs:
        exito = {t: sum(x[0] for x in m[a][t]) / len(m[a][t]) for t in ("un_dominio", "cruce")}
        usd = {t: statistics.mean(x[1] for x in m[a][t]) for t in ("un_dominio", "cruce")}
        e = (1 - cruces) * exito["un_dominio"] + cruces * exito["cruce"]
        u = (1 - cruces) * usd["un_dominio"] + cruces * usd["cruce"]
        print(f"  {a:<13} éxito {e:.0%} · USD {u * 1000:.2f} cada 1.000 consultas")
        proy.append(f"| {a} | {e:.0%} | {u * 1000:.2f} |")

    lineas = ["## C3 · Ejercicio 4 · ¿Se justifica el grafo?", "", f"- Modelo {MODELO}{' (MOCK)' if MOCK else ''}", "",
              "| id | tipo | " + " | ".join(arqs) + " |", "|---|---|" + "---|" * len(arqs), *filas, "",
              "| arquitectura | tipo | éxito | LLM/consulta | USD/consulta | p50 (s) | p95 (s) |",
              "|---|---|---|---|---|---|---|", *tabla, "", f"Proyección con {cruces:.0%} de cruces:", "",
              "| arquitectura | éxito | USD cada 1.000 consultas |", "|---|---|---|", *proy]
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / "c3_arquitecturas.md").write_text("\n".join(lineas), encoding="utf-8")
    print("\n✓ Guardado results/c3_arquitecturas.md")


if __name__ == "__main__":
    main()
