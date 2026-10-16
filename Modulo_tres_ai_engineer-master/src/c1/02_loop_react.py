"""C1 · Ejercicio 2 · El loop ReAct a mano, sobre las 13 consultas de pasajeros.

Corre el agente (orbitair/agente.py) con las stopping rules de producción y chequea
la TRAYECTORIA de cada consulta contra lo etiquetado en el dataset: herramientas
usadas, cómo terminó, hechos clave en la respuesta, pasos, tokens y USD.

Uso:
  python src/c1/02_loop_react.py
  python src/c1/02_loop_react.py --id A-02        # traza completa: pensamiento → acción → observación
  python src/c1/02_loop_react.py --ids A-01,A-04

Guarda results/c1_loop.md (la tabla) y results/c1_loop.jsonl (las trazas, para comparar en C2).
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))
from orbitair.agente import Agente  # noqa: E402
from orbitair.data import load_consultas_c1  # noqa: E402
from orbitair.llm import MOCK, MODELO  # noqa: E402
from orbitair.operaciones import pasajero, reiniciar_db  # noqa: E402
from orbitair.pricing import fmt_usd  # noqa: E402
from orbitair.trayectoria import chequear, imprimir_traza, marca  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")
RESULTS = Path(__file__).resolve().parents[2] / "results"


def arg(flag: str, default=None):
    return sys.argv[sys.argv.index(flag) + 1] if flag in sys.argv else default


def main():
    casos = load_consultas_c1()
    ids = arg("--ids", arg("--id"))
    if ids:
        casos = [c for c in casos if c["id"] in ids.split(",")]
    detalle = len(casos) == 1
    if MOCK:
        print("⚠ ORBITAIR_MOCK=1 → el 'modelo' es un guion determinista: sirve para ver el loop, no para juzgar "
              "la calidad.\n")
    reiniciar_db()
    print(f"Agente {MODELO} · stopping rules de producción · {len(casos)} consultas\n")

    filas, trazas = [], []
    for c in casos:
        p = pasajero(c["pasajero_id"])
        r = Agente(c["pasajero_id"], p["nombre"]).correr(c["consulta"])
        ch = chequear(c, r.herramientas, r.parada, r.respuesta)
        filas.append((c, r, ch))
        trazas.append({"id": c["id"], "herramientas": r.herramientas, "parada": r.parada, "pasos": len(r.pasos),
                       "respuesta": r.respuesta, "tokens": r.tokens, "costo_usd": r.costo_usd})
        print(f"{c['id']} · {c['tipo']} · {c['consulta']}")
        if detalle:
            imprimir_traza(r)
            print(f"\n  nota: {c['nota']}")
        else:
            extra = (f" (faltan {ch.faltan})" if ch.faltan else "") + (f" (sobran {ch.sobran})" if ch.sobran else "")
            print(f"   {marca(ch.herramientas_ok)} herramientas {r.herramientas or '—'}{extra}   "
                  f"{marca(ch.parada_ok)} parada {r.parada}   {marca(ch.hechos_ok)} hechos   "
                  f"{len(r.pasos)} pasos · {r.tokens} tokens · {fmt_usd(r.costo_usd)} · {r.latencia_s:.1f} s")
            print(f"   → {r.respuesta[:220]}{'…' if len(r.respuesta) > 220 else ''}\n")

    n = len(filas)
    ok = sum(ch.ok for _, _, ch in filas)
    tok = sum(r.tokens for _, r, _ in filas)
    usd = sum(r.costo_usd for _, r, _ in filas)
    pasos = sum(len(r.pasos) for _, r, _ in filas)
    resumen = (f"Trayectoria correcta en {ok}/{n} · herramientas {sum(ch.herramientas_ok for *_, ch in filas)}/{n} · "
               f"parada {sum(ch.parada_ok for *_, ch in filas)}/{n} · hechos {sum(ch.hechos_ok for *_, ch in filas)}/{n}"
               f" · {pasos / n:.1f} pasos y {tok / n:,.0f} tokens por consulta · {fmt_usd(usd / n)} por consulta")
    print(resumen)
    if detalle:
        return
    lineas = ["## C1 · Loop ReAct a mano", "", f"- Modelo {MODELO}{' (MOCK)' if MOCK else ''} · stopping rules de "
              "producción", "", "| id | tipo | herramientas | parada | hechos | pasos | tokens | USD |",
              "|---|---|---|---|---|---|---|---|"]
    for c, r, ch in filas:
        lineas.append(f"| {c['id']} | {c['tipo']} | {marca(ch.herramientas_ok)} {', '.join(r.herramientas) or '—'} | "
                      f"{marca(ch.parada_ok)} {r.parada} | {marca(ch.hechos_ok)} | {len(r.pasos)} | {r.tokens} | "
                      f"{r.costo_usd:.5f} |")
    lineas += ["", resumen]
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / "c1_loop.md").write_text("\n".join(lineas), encoding="utf-8")
    with open(RESULTS / "c1_loop.jsonl", "w", encoding="utf-8") as f:
        f.writelines(json.dumps(t, ensure_ascii=False) + "\n" for t in trazas)
    print("\n✓ Guardado results/c1_loop.md y results/c1_loop.jsonl")


if __name__ == "__main__":
    main()
