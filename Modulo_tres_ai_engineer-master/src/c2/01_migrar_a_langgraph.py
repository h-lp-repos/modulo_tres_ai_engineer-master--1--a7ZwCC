"""C2 · Ejercicio 1 · Migrar el loop de C1 a LangGraph y comprobar que se comporta igual.

Corre las 13 consultas de C1 con el agente a mano (orbitair/agente.py) y con el grafo
(orbitair/grafo.py), y compara la TRAYECTORIA: herramientas usadas, en qué orden,
cómo terminó y cuántos pasos de LLM. "Mismo comportamiento" se comprueba con datos,
no a ojo.

Con la API real, el texto de la respuesta puede variar entre dos corridas aunque el
código sea el mismo (el modelo no es determinista): por eso se compara la trayectoria
y los hechos clave, no el texto exacto.

Uso:
  python src/c2/01_migrar_a_langgraph.py
  python src/c2/01_migrar_a_langgraph.py --id A-02      # el recorrido del grafo nodo por nodo
  python src/c2/01_migrar_a_langgraph.py --mermaid      # el diagrama del grafo (pegar en mermaid.live)

Guarda results/c2_migracion.md y results/c2_grafo.mmd.
"""
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))
from orbitair.agente import Agente  # noqa: E402
from orbitair.data import load_consultas_c1  # noqa: E402
from orbitair.grafo import construir_grafo, entrada_turno  # noqa: E402
from orbitair.historial import observaciones  # noqa: E402
from orbitair.llm import MOCK, MODELO  # noqa: E402
from orbitair.operaciones import pasajero, reiniciar_db  # noqa: E402
from orbitair.pricing import fmt_usd  # noqa: E402
from orbitair.trayectoria import chequear, marca  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")
RESULTS = Path(__file__).resolve().parents[2] / "results"


def arg(flag: str, default=None):
    return sys.argv[sys.argv.index(flag) + 1] if flag in sys.argv else default


def recorrido(grafo, caso: dict) -> None:
    """El grafo paso a paso: qué nodo corrió y qué cambió en el estado (stream_mode="updates")."""
    cfg = {"configurable": {"thread_id": str(uuid.uuid4())}}
    print(f"{caso['id']} · {caso['consulta']}\n")
    for evento in grafo.stream(entrada_turno(caso["consulta"], caso["pasajero_id"]), cfg, stream_mode="updates"):
        for nodo, cambios in evento.items():
            resumen = []
            for k, v in (cambios or {}).items():
                if k == "mensajes":
                    for m in v:
                        if m.get("tool_calls"):
                            resumen.append("pide " + ", ".join(f"{t['function']['name']}({t['function']['arguments']})"
                                                               for t in m["tool_calls"]))
                        elif m["role"] == "tool":
                            resumen.append(f"observación {m['content'][:80]}…")
                        else:
                            resumen.append(f"responde: {str(m['content'])[:90]}…")
                elif k in ("pasos", "parada", "firmas"):
                    resumen.append(f"{k}={v}")
            print(f"  - {nodo:<13} {' · '.join(resumen) or '(sin cambios)'}")
    print()


def main():
    casos = load_consultas_c1()
    grafo = construir_grafo()           # sin checkpointer: los checkpoints son el Ejercicio 2
    mermaid = grafo.get_graph().draw_mermaid()
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / "c2_grafo.mmd").write_text(mermaid, encoding="utf-8")
    if "--mermaid" in sys.argv:
        print(mermaid)
        return
    if MOCK:
        print("⚠ ORBITAIR_MOCK=1 → el guion es determinista: las respuestas tienen que salir idénticas.\n")
    reiniciar_db()
    if arg("--id"):
        recorrido(grafo, next(c for c in casos if c["id"] == arg("--id")))
        return

    print(f"Modelo {MODELO} · {len(casos)} consultas · C1 (loop a mano) vs C2 (LangGraph)\n")
    print(f"{'id':<5} {'herramientas C1 → C2':<58} {'parada':<22} {'pasos':<7} {'mismo':<6} {'C2 ok'}")
    filas, iguales = [], 0
    for c in casos:
        nombre = pasajero(c["pasajero_id"])["nombre"]
        r1 = Agente(c["pasajero_id"], nombre).correr(c["consulta"])
        cfg = {"configurable": {"thread_id": f"{c['id']}-{uuid.uuid4().hex[:6]}"}}
        s2 = grafo.invoke(entrada_turno(c["consulta"], c["pasajero_id"], nombre), cfg)
        h2 = [o.nombre for o in observaciones(s2["mensajes"])]
        mismo = r1.herramientas == h2 and r1.parada == s2["parada"] and len(r1.pasos) == s2["pasos"]
        iguales += mismo
        ok2 = chequear(c, h2, s2["parada"], s2["respuesta"]).ok
        h = f"{','.join(r1.herramientas) or '—'} → {'=' if h2 == r1.herramientas else ','.join(h2) or '—'}"
        parada = f"{r1.parada} → {s2['parada']}"
        pasos = f"{len(r1.pasos)} → {s2['pasos']}"
        print(f"{c['id']:<5} {h:<58} {parada:<22} {pasos:<7} {marca(mismo):<6} {marca(ok2)}")
        filas.append((c["id"], r1, s2, h2, mismo, ok2))

    n = len(casos)
    texto_igual = sum(r1.respuesta == s2["respuesta"] for _, r1, s2, *_ in filas)
    usd1 = sum(r1.costo_usd for _, r1, *_ in filas) / n
    usd2 = sum(s2["costo_usd"] for _, _, s2, *_ in filas) / n
    resumen = (f"Misma trayectoria en {iguales}/{n} · mismo texto de respuesta en {texto_igual}/{n} · "
               f"trayectoria correcta (C2) en {sum(f[5] for f in filas)}/{n} · USD por consulta: C1 {fmt_usd(usd1)} "
               f"· C2 {fmt_usd(usd2)}")
    print(f"\n{resumen}")
    lineas = ["## C2 · Migración a LangGraph", "", f"- Modelo {MODELO}{' (MOCK)' if MOCK else ''}", "",
              "| id | herramientas C1 | herramientas C2 | parada C1 → C2 | pasos C1 → C2 | misma trayectoria |",
              "|---|---|---|---|---|---|"]
    lineas += [f"| {i} | {', '.join(r1.herramientas) or '—'} | {', '.join(h2) or '—'} | {r1.parada} → {s2['parada']} | "
               f"{len(r1.pasos)} → {s2['pasos']} | {marca(m)} |" for i, r1, s2, h2, m, _ in filas]
    lineas += ["", resumen]
    (RESULTS / "c2_migracion.md").write_text("\n".join(lineas), encoding="utf-8")
    print("\n✓ Guardado results/c2_migracion.md y results/c2_grafo.mmd")


if __name__ == "__main__":
    main()
