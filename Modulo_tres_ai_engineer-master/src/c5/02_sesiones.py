"""C5 · Ejercicio 2 · Sesiones: el costo de una CONVERSACIÓN, no de una llamada.

Corre el dataset de conversaciones (data/c5_conversaciones.jsonl: 10 sesiones, 25 turnos, cada
turno una consulta etiquetada de C3). Cada turno es una traza; todas las de una conversación
comparten `session_id`. Después agrupa por sesión: turnos, llamadas al LLM, tokens, costo,
latencia, errores. Es la vista "Sessions" de Langfuse.

El costo que importa para el negocio es por sesión (lo que cuesta atender a un pasajero), y una
sesión cara suele explicarse por UN turno: hay que poder bajar de la sesión a la traza.

Uso:
  python src/c5/02_sesiones.py
  python src/c5/02_sesiones.py --version v1       # la etiqueta de la corrida (tag de las trazas)

Deja las trazas para el Ejercicio 3 y guarda results/c5_sesiones.md.
"""
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))
from orbitair import retrieval, trazas  # noqa: E402
from orbitair.data import load_consultas_c3, load_conversaciones_c5  # noqa: E402
from orbitair.evals import correr_conversaciones, resumen_sesiones  # noqa: E402
from orbitair.llm import MOCK, MODELO  # noqa: E402
from orbitair.operaciones import pasajero, reiniciar_db  # noqa: E402
from orbitair.orquestador import construir_orquestador  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")
RESULTS = Path(__file__).resolve().parents[2] / "results"


def arg(flag: str, default=None):
    return sys.argv[sys.argv.index(flag) + 1] if flag in sys.argv else default


def main():
    version = arg("--version", "v1")
    if MOCK:
        print("⚠ ORBITAIR_MOCK=1 → los costos son de tokens contados sobre el guion: sirven para comparar, no como "
              "presupuesto.\n")
    reiniciar_db()
    retrieval.indice()
    trazas.limpiar()
    conversaciones = load_conversaciones_c5()
    casos = {c["id"]: c for c in load_consultas_c3()}
    nombres = {c["pasajero_id"]: pasajero(c["pasajero_id"])["nombre"] for c in conversaciones}
    print(f"Modelo {MODELO} · {len(conversaciones)} conversaciones · "
          f"{sum(len(c['turnos']) for c in conversaciones)} turnos · versión '{version}'\n")
    correr_conversaciones(construir_orquestador(), conversaciones, casos, nombres, version)

    sesiones = resumen_sesiones(trazas.leer_indice(version))
    for s in sesiones:                                  # el costo de la sesión, como score de SESIÓN
        trazas.puntuar("", "costo_sesion_usd", s["costo_usd"], session_id=s["session_id"])
    trazas.cerrar()

    print(f"{'sesión':<22} {'pasajero':<8} {'turnos':<7} {'LLM':<5} {'tokens':<8} {'USD':<10} {'latencia':<9} "
          f"{'err/adv'}")
    filas = []
    for s in sesiones:
        print(f"{s['session_id']:<22} {s['user_id']:<8} {s['turnos']:<7} {s['llamadas_llm']:<5} {s['tokens']:<8,} "
              f"${s['costo_usd']:<9.5f} {s['latencia_s']:>5.2f} s   {s['errores']}/{s['advertencias']}")
        filas.append(f"| {s['session_id']} | {s['user_id']} | {s['turnos']} | {s['llamadas_llm']} | {s['tokens']} | "
                     f"{s['costo_usd']:.5f} | {s['latencia_s']:.2f} | {s['errores']}/{s['advertencias']} |")

    costos = sorted(s["costo_usd"] for s in sesiones)
    por_turno = sum(costos) / sum(s["turnos"] for s in sesiones)
    resumen = (f"Costo por sesión: mediana ${statistics.median(costos):.5f} · máx ${costos[-1]:.5f} · "
               f"total ${sum(costos):.5f} · costo por turno ${por_turno:.5f} · "
               f"proyección: ${statistics.mean(costos) * 1000:.2f} cada 1.000 conversaciones")
    print(f"\n{resumen}")

    cara = sesiones[0]
    turnos = sorted((f for f in trazas.leer_indice(version) if f["session_id"] == cara["session_id"]),
                    key=lambda f: f["inicio"])
    print(f"\nLa sesión más cara ({cara['session_id']}), turno por turno:")
    for f in turnos:
        print(f"  turno {f['metadata'].get('turno')} · {f['metadata'].get('caso')} · {f['llamadas_llm']} LLM · "
              f"${f['costo_usd']:.5f} · traza {f['traza_id'][:12]}…")
    mas_caro = max(turnos, key=lambda f: f["costo_usd"])
    print(f"\n  El turno más caro ({mas_caro['metadata'].get('caso')}), abierto:\n")
    print("  " + trazas.arbol(mas_caro["traza_id"]).replace("\n", "\n  "))

    RESULTS.mkdir(exist_ok=True)
    (RESULTS / "c5_sesiones.md").write_text("\n".join([
        "## C5 · Ejercicio 2 · Costo por sesión", "", f"- Modelo {MODELO}{' (MOCK)' if MOCK else ''} · versión {version}",
        "", "| sesión | pasajero | turnos | LLM | tokens | USD | latencia (s) | err/adv |", "|---|---|---|---|---|---|---|---|",
        *filas, "", resumen]), encoding="utf-8")
    print("\n✓ Guardado results/c5_sesiones.md (las trazas quedan para el Ejercicio 3)")


if __name__ == "__main__":
    main()
