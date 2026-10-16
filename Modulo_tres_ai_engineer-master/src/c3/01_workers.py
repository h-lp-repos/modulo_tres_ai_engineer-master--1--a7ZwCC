"""C3 · Ejercicio 1 · Los workers: el agente de C2 especializado por dominio, sobre los índices del M2.

Parte A · Mismo pedido, tres alcances. Una pregunta de política buscada con el BM25 global
de C1-C2 y con el retrieval de cada worker (híbrida del M2 + filtro por documento): cada
especialista sólo ve SU política.

Parte B · Cada worker en su dominio. Las consultas de un solo dominio del dataset de C3,
mandadas directo al worker que corresponde (routing "perfecto", a mano): ¿el especialista
resuelve igual que el agente único? Todavía no hay orquestador: eso es el Ejercicio 3.

Uso:
  python src/c3/01_workers.py
  python src/c3/01_workers.py --consulta "¿Me devuelven la plata si me cancelan el vuelo?"
  python src/c3/01_workers.py --dominio equipaje --pregunta "¿Dónde está mi valija OA-582331?"

Guarda results/c3_workers.md.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))
from orbitair import politicas, retrieval  # noqa: E402
from orbitair.data import load_consultas_c3  # noqa: E402
from orbitair.grafo import construir_grafo, entrada_turno  # noqa: E402
from orbitair.historial import observaciones  # noqa: E402
from orbitair.llm import MOCK, MODELO  # noqa: E402
from orbitair.operaciones import pasajero, reiniciar_db  # noqa: E402
from orbitair.pricing import fmt_usd  # noqa: E402
from orbitair.trayectoria import chequear, marca  # noqa: E402
from orbitair.workers import DOMINIOS, config_worker  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")
RESULTS = Path(__file__).resolve().parents[2] / "results"
CONSULTA_A = "¿Me devuelven la plata si me cancelan el vuelo?"


def arg(flag: str, default=None):
    return sys.argv[sys.argv.index(flag) + 1] if flag in sys.argv else default


def parte_a(consulta: str) -> list[str]:
    print(f"── Parte A · «{consulta}»\n")
    filas = [("C1-C2: BM25, todo el corpus", [f["id"] for f in politicas.buscar(consulta)])]
    filas += [(f"worker {d.nombre}: híbrida, sólo {d.documento}",
               [f["id"] for f in retrieval.buscar(consulta, documentos=[d.documento])]) for d in DOMINIOS.values()]
    for nombre, ids in filas:
        print(f"  {nombre:<42} {', '.join(ids) or '— (nada)'}")
    print("\n  Herramientas de cada worker (mínimo privilegio):")
    for d in DOMINIOS:
        print(f"  {d:<11} {', '.join(config_worker(d).herramientas)}   (con acciones: "
              f"{', '.join(config_worker(d, acciones=True).herramientas)})")
    return [f"| {n} | {', '.join(ids)} |" for n, ids in filas]


def correr(dominio: str, caso: dict) -> dict:
    nombre = pasajero(caso["pasajero_id"])["nombre"]
    s = construir_grafo(config_worker(dominio)).invoke(entrada_turno(caso["consulta"], caso["pasajero_id"], nombre))
    return {**s, "herramientas": [o.nombre for o in observaciones(s["mensajes"])]}


def main():
    if MOCK:
        print("⚠ ORBITAIR_MOCK=1 → embeddings por hashing y 'modelo' guionado: sirve para ver el mecanismo.\n")
    reiniciar_db()
    retrieval.indice()                  # construye el índice la primera vez (con la API real: una llamada)
    if arg("--dominio"):
        caso = {"consulta": arg("--pregunta", CONSULTA_A), "pasajero_id": arg("--pasajero", "P-1001")}
        s = correr(arg("--dominio"), caso)
        print(f"worker {arg('--dominio')} · herramientas {s['herramientas']} · parada {s['parada']}\n→ {s['respuesta']}")
        return
    tabla_a = parte_a(arg("--consulta", CONSULTA_A))

    casos = [c for c in load_consultas_c3() if c["tipo"] == "un_dominio"]
    print(f"\n── Parte B · {len(casos)} consultas de un dominio, cada una directo a su worker · {MODELO}\n")
    print(f"{'id':<5} {'worker':<11} {'herramientas':<36} {'parada':<11} {'hechos':<7} {'pasos':<6} USD")
    filas, ok = [], 0
    for c in casos:
        dominio = c["dominios"][0]
        s = correr(dominio, c)
        ch = chequear(c, s["herramientas"], s["parada"], s["respuesta"])
        ok += ch.ok
        print(f"{c['id']:<5} {dominio:<11} {marca(ch.herramientas_ok)} {', '.join(s['herramientas']) or '—':<34} "
              f"{marca(ch.parada_ok)} {s['parada']:<9} {marca(ch.hechos_ok):<7} {s['pasos']:<6} {fmt_usd(s['costo_usd'])}")
        filas.append(f"| {c['id']} | {dominio} | {', '.join(s['herramientas']) or '—'} | {s['parada']} | "
                     f"{marca(ch.ok)} | {s['pasos']} | {s['costo_usd']:.5f} |")
    resumen = f"Trayectoria correcta en {ok}/{len(casos)} con routing a mano."
    print(f"\n{resumen}")

    lineas = ["## C3 · Ejercicio 1 · Workers", "", f"- Modelo {MODELO}{' (MOCK)' if MOCK else ''}", "",
              f"### Parte A · «{arg('--consulta', CONSULTA_A)}»", "", "| buscador | top-3 |", "|---|---|", *tabla_a, "",
              "### Parte B · Cada worker en su dominio", "",
              "| id | worker | herramientas | parada | ok | pasos | USD |", "|---|---|---|---|---|---|---|", *filas, "",
              resumen]
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / "c3_workers.md").write_text("\n".join(lineas), encoding="utf-8")
    print("\n✓ Guardado results/c3_workers.md")


if __name__ == "__main__":
    main()
