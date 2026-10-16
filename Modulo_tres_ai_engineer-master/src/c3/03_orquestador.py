"""C3 · Ejercicio 3 · El orquestador: rutear → workers en paralelo (Send) → sintetizar.

Parte A · Una consulta que cruza tres dominios, nodo a nodo (stream "updates"): el router
reparte, los tres workers arrancan juntos y la síntesis espera a que terminen todos.

Parte B · Paralelo vs en serie. Las consultas que cruzan dominios, con los workers en
paralelo (Send) y uno detrás de otro. Misma respuesta, distinta latencia: en paralelo
se paga el worker más lento; en serie, la suma. El COSTO es el mismo.

Parte C (--todas) · El sistema completo sobre las 25 consultas: ruta, trayectoria y hechos.

Uso:
  python src/c3/03_orquestador.py
  python src/c3/03_orquestador.py --id M-17
  python src/c3/03_orquestador.py --todas
  python src/c3/03_orquestador.py --mermaid      # el diagrama (pegar en https://mermaid.live)

Guarda results/c3_orquestador.md y results/c3_orquestador.mmd.
"""
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))
from orbitair import retrieval  # noqa: E402
from orbitair.data import load_consultas_c3  # noqa: E402
from orbitair.llm import MOCK, MODELO  # noqa: E402
from orbitair.operaciones import pasajero, reiniciar_db  # noqa: E402
from orbitair.orquestador import ConfigOrquestador, construir_orquestador, entrada_orquestador, resumen  # noqa: E402
from orbitair.pricing import fmt_usd  # noqa: E402
from orbitair.trayectoria import chequear, marca  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")
RESULTS = Path(__file__).resolve().parents[2] / "results"


def arg(flag: str, default=None):
    return sys.argv[sys.argv.index(flag) + 1] if flag in sys.argv else default


def entrada(caso: dict) -> dict:
    return entrada_orquestador(caso["consulta"], caso["pasajero_id"], pasajero(caso["pasajero_id"])["nombre"])


def recorrido(grafo, caso: dict) -> None:
    print(f"{caso['id']} · {caso['consulta']}\n")
    t0 = time.perf_counter()
    for evento in grafo.stream(entrada(caso), stream_mode="updates"):
        for nodo, cambios in evento.items():
            t = time.perf_counter() - t0
            cambios = cambios or {}
            if nodo == "rutear":
                print(f"  {t:5.2f} s  rutear       → {len(cambios['intenciones'])} intención(es)")
                for i in cambios["intenciones"]:
                    print(f"                     {i['dominio']:<11} «{i['tarea']}»")
            elif nodo in ("worker", "workers_en_serie"):
                for r in cambios["resultados"]:
                    print(f"  {t:5.2f} s  worker {r['dominio']:<11} corrió de {r['inicio_s']:.2f} a {r['fin_s']:.2f} s · "
                          f"{', '.join(r['herramientas']) or '—'} · {r['pasos']} pasos · {fmt_usd(r['costo_usd'])}")
                    print(f"                     → {r['respuesta'][:150]}{'…' if len(r['respuesta']) > 150 else ''}")
            elif nodo == "sintetizar":
                extra = "una llamada al LLM" if cambios.get("llamadas_llm") else "un solo worker: pasa directo, sin LLM"
                print(f"  {t:5.2f} s  sintetizar   ({extra}) · parada={cambios['parada']}\n\n  → {cambios['respuesta']}")
            else:
                print(f"  {t:5.2f} s  {nodo} → {cambios.get('respuesta')}")
    print()


def comparar_latencia(paralelo, serie, casos: list[dict]) -> list[str]:
    print(f"── Parte B · {len(casos)} consultas que cruzan dominios · paralelo vs en serie\n")
    print(f"{'id':<5} {'workers':<8} {'paralelo':<10} {'en serie':<10} {'misma respuesta':<16} USD")
    filas, lp, ls = [], [], []
    for c in casos:
        t = time.perf_counter(); sp = paralelo.invoke(entrada(c)); tp = time.perf_counter() - t
        t = time.perf_counter(); ss = serie.invoke(entrada(c)); ts = time.perf_counter() - t
        igual = sp["respuesta"] == ss["respuesta"]
        lp.append(tp); ls.append(ts)
        print(f"{c['id']:<5} {len(sp['resultados']):<8} {tp:<10.2f} {ts:<10.2f} {marca(igual):<16} "
              f"{fmt_usd(sp['costo_usd'])} · {fmt_usd(ss['costo_usd'])}")
        filas.append(f"| {c['id']} | {len(sp['resultados'])} | {tp:.2f} | {ts:.2f} | {marca(igual)} |")
    texto = (f"Latencia media: paralelo {statistics.mean(lp):.2f} s · en serie {statistics.mean(ls):.2f} s "
             f"({statistics.mean(ls) / statistics.mean(lp):.1f}× más lento). El costo no cambia.")
    print(f"\n{texto}\n")
    return ["| id | workers | paralelo (s) | en serie (s) | misma respuesta |", "|---|---|---|---|---|", *filas, "", texto]


def todas(grafo, casos: list[dict]) -> list[str]:
    print(f"── Parte C · el sistema completo sobre {len(casos)} consultas\n")
    print(f"{'id':<5} {'tipo':<11} {'ruta':<32} {'herramientas':<6} {'parada':<7} {'hechos':<7} {'LLM':<4} USD")
    filas, oks = [], {"ruta": 0, "trayectoria": 0}
    for c in casos:
        r = resumen(grafo.invoke(entrada(c)))
        ch = chequear(c, r["herramientas"], r["parada"], r["respuesta"])
        ruta = sorted(r["dominios"]) == sorted(c["dominios"])
        oks["ruta"] += ruta
        oks["trayectoria"] += ruta and ch.ok
        print(f"{c['id']:<5} {c['tipo']:<11} {marca(ruta)} {', '.join(r['dominios']):<30} {marca(ch.herramientas_ok):<6} "
              f"{marca(ch.parada_ok):<7} {marca(ch.hechos_ok):<7} {r['llamadas_llm']:<4} {fmt_usd(r['costo_usd'])}")
        filas.append(f"| {c['id']} | {c['tipo']} | {', '.join(r['dominios'])} | {marca(ruta)} | {marca(ch.ok)} | "
                     f"{r['llamadas_llm']} | {r['costo_usd']:.5f} |")
    texto = (f"Ruta correcta en {oks['ruta']}/{len(casos)} · ruta + trayectoria + hechos en "
             f"{oks['trayectoria']}/{len(casos)}")
    print(f"\n{texto}")
    return ["| id | tipo | ruta | ruta ok | trayectoria ok | LLM | USD |", "|---|---|---|---|---|---|---|", *filas, "", texto]


def main():
    casos = load_consultas_c3()
    paralelo = construir_orquestador()
    mermaid = paralelo.get_graph().draw_mermaid()
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / "c3_orquestador.mmd").write_text(mermaid, encoding="utf-8")
    if "--mermaid" in sys.argv:
        print(mermaid)
        return
    if MOCK:
        print("⚠ ORBITAIR_MOCK=1 → router por reglas y 'modelo' guionado (latencia simulada ~0,05 s por llamada; "
              "con la API real, 1-3 s: la diferencia paralelo/serie se nota mucho más).\n")
    reiniciar_db()
    retrieval.indice()
    print(f"Modelo {MODELO}\n")
    if arg("--id"):
        recorrido(paralelo, next(c for c in casos if c["id"] == arg("--id")))
        return
    lineas = ["## C3 · Ejercicio 3 · Orquestador", "", f"- Modelo {MODELO}{' (MOCK)' if MOCK else ''}", ""]
    if "--todas" in sys.argv:
        lineas += todas(paralelo, casos)
    else:
        print("── Parte A · el recorrido de una consulta con tres dominios\n")
        recorrido(paralelo, next(c for c in casos if c["id"] == "M-23"))
        serie = construir_orquestador(ConfigOrquestador(paralelo=False))
        lineas += comparar_latencia(paralelo, serie, [c for c in casos if c["tipo"] == "cruce"])
    (RESULTS / "c3_orquestador.md").write_text("\n".join(lineas), encoding="utf-8")
    print("\n✓ Guardado results/c3_orquestador.md y results/c3_orquestador.mmd")


if __name__ == "__main__":
    main()
