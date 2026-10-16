"""C3 · Ejercicio 2 · Routing por intención: ¿a qué especialistas va cada consulta?

El router es el triage del M1 (equipaje / cambios / reembolsos / otros), con dos cambios:
es MULTI-ETIQUETA (una consulta puede tocar varios dominios) y además de la etiqueta
devuelve la TAREA de cada especialista. Se mide como un clasificador, contra la ruta
etiquetada en el dataset de C3:

- exactitud de la ruta: el conjunto de dominios es exactamente el esperado;
- de más (over-routing): se suma un worker que no hacía falta → más costo y latencia;
- de menos (under-routing): falta un worker → una parte de la consulta queda sin responder.
  Es el error caro: el sistema contesta con confianza la mitad de la pregunta.

Parte B · El contrato. La salida del router se valida antes de usarla (`validar_ruteo`):
un dominio inventado, uno repetido, "otros" mezclado con dominios reales, basura.

Uso:
  python src/c3/02_routing.py
  python src/c3/02_routing.py --id M-17          # la llamada del router: lo que propuso y lo que se validó

Guarda results/c3_routing.md.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))
from orbitair.data import load_consultas_c3  # noqa: E402
from orbitair.llm import MOCK, MODELO  # noqa: E402
from orbitair.orquestador import rutear, validar_ruteo  # noqa: E402
from orbitair.pricing import fmt_usd  # noqa: E402
from orbitair.trayectoria import marca  # noqa: E402
from orbitair.workers import DOMINIOS  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")
RESULTS = Path(__file__).resolve().parents[2] / "results"
ROTOS = [
    ("dominio inventado", [{"dominio": "vuelos", "tarea": "estado del OA1203"}]),
    ("dominio repetido", [{"dominio": "equipaje", "tarea": "valija OA-582331"},
                          {"dominio": "equipaje", "tarea": "gastos por demora de la valija"}]),
    ("'otros' con dominios reales", [{"dominio": "otros", "tarea": "saludo"},
                                     {"dominio": "reembolsos", "tarea": "plazo de acreditación"}]),
    ("no es una lista", "equipaje"),
    ("vacío", []),
]


def arg(flag: str, default=None):
    return sys.argv[sys.argv.index(flag) + 1] if flag in sys.argv else default


def detalle(caso: dict) -> None:
    r = rutear(caso["consulta"])
    print(f"{caso['id']} · {caso['consulta']}\n")
    print(f"  esperado: {caso['dominios']}")
    propuesto = r.llm.tool_calls[0].argumentos if r.llm and r.llm.tool_calls else {}
    print(f"  el modelo propuso ({r.llm.tokens_in}+{r.llm.tokens_out} tokens · {fmt_usd(r.llm.costo_usd)} · "
          f"{r.llm.latencia_s:.2f} s):\n{json.dumps(propuesto, ensure_ascii=False, indent=4)}")
    print(f"  validado: {json.dumps(r.intenciones, ensure_ascii=False)}")
    if r.descartadas:
        print(f"  descartado: {r.descartadas}")


def main():
    casos = load_consultas_c3()
    if MOCK:
        print("⚠ ORBITAIR_MOCK=1 → el router es un clasificador por palabras clave (orbitair/mock_orquestador.py). "
              "La exactitud del router con LLM se mide con la API real.\n")
    if arg("--id"):
        detalle(next(c for c in casos if c["id"] == arg("--id")))
        return

    print(f"Router {MODELO} · {len(casos)} consultas etiquetadas con su ruta\n")
    print(f"{'id':<5} {'tipo':<11} {'esperado':<34} {'router':<34} {'ok':<3} {'de más':<11} {'de menos'}")
    filas, usd, lat = [], 0.0, []
    por_dom = {d: {"tp": 0, "fp": 0, "fn": 0} for d in [*DOMINIOS, "otros"]}
    for c in casos:
        r = rutear(c["consulta"])
        esp, got = set(c["dominios"]), set(r.dominios)
        ok = esp == got
        for d in por_dom:
            por_dom[d]["tp"] += d in esp and d in got
            por_dom[d]["fp"] += d not in esp and d in got
            por_dom[d]["fn"] += d in esp and d not in got
        usd += r.llm.costo_usd if r.llm else 0.0
        lat.append(r.llm.latencia_s if r.llm else 0.0)
        mas, menos = sorted(got - esp), sorted(esp - got)
        print(f"{c['id']:<5} {c['tipo']:<11} {', '.join(c['dominios']):<34} {', '.join(r.dominios):<34} {marca(ok):<3} "
              f"{', '.join(mas) or '':<11} {', '.join(menos)}")
        filas.append((c, r.dominios, ok, mas, menos))

    n = len(casos)
    exactos = sum(f[2] for f in filas)
    por_tipo = {t: (sum(f[2] for f in filas if f[0]["tipo"] == t), sum(f[0]["tipo"] == t for f in filas))
                for t in ("un_dominio", "cruce", "otros")}
    resumen = (f"Ruta exacta en {exactos}/{n} ({', '.join(f'{t} {a}/{b}' for t, (a, b) in por_tipo.items())}) · "
               f"de más en {sum(bool(f[3]) for f in filas)} · de menos en {sum(bool(f[4]) for f in filas)} · "
               f"{fmt_usd(usd / n)} y {sum(lat) / n:.2f} s por ruteo")
    print(f"\n{resumen}\n")
    print(f"{'dominio':<11} {'precisión':<10} {'recall':<8} (multi-etiqueta: cada dominio es un clasificador sí/no)")
    lineas_dom = []
    for d, m in por_dom.items():
        p = m["tp"] / (m["tp"] + m["fp"]) if m["tp"] + m["fp"] else 1.0
        rc = m["tp"] / (m["tp"] + m["fn"]) if m["tp"] + m["fn"] else 1.0
        print(f"{d:<11} {p:<10.0%} {rc:<8.0%}")
        lineas_dom.append(f"| {d} | {p:.0%} | {rc:.0%} |")

    print("\n── Parte B · El contrato del router: salidas rotas\n")
    lineas_b = []
    for nombre, propuesta in ROTOS:
        validas, descartadas = validar_ruteo(propuesta, "(consulta)")
        print(f"  {nombre:<28} → {[i['dominio'] for i in validas]}   descartado: {descartadas or '—'}")
        lineas_b.append(f"| {nombre} | {', '.join(i['dominio'] for i in validas)} | {len(descartadas)} |")

    lineas = ["## C3 · Ejercicio 2 · Routing por intención", "", f"- Router {MODELO}{' (MOCK: reglas)' if MOCK else ''}",
              "", "| id | tipo | esperado | router | ok | de más | de menos |", "|---|---|---|---|---|---|---|"]
    lineas += [f"| {c['id']} | {c['tipo']} | {', '.join(c['dominios'])} | {', '.join(d)} | {marca(ok)} | "
               f"{', '.join(mas)} | {', '.join(menos)} |" for c, d, ok, mas, menos in filas]
    lineas += ["", resumen, "", "| dominio | precisión | recall |", "|---|---|---|", *lineas_dom, "",
               "### Salidas rotas", "", "| caso | queda | descartadas |", "|---|---|---|", *lineas_b]
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / "c3_routing.md").write_text("\n".join(lineas), encoding="utf-8")
    print("\n✓ Guardado results/c3_routing.md")


if __name__ == "__main__":
    main()
