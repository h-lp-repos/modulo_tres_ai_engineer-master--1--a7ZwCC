"""C2 · Ejercicio 5 · Debugging del grafo: un bug introducido en la migración, encontrado con el estado.

El bug: al migrar se "simplificó" el grafo y se sacó el nodo `control` (las stopping rules
de C1). Con el prompt ingenuo y la valija en búsqueda (A-10), el grafo da vueltas
agente → herramientas → agente... hasta que LangGraph lo corta con su propia red de
seguridad: `recursion_limit` (25 super-steps por defecto; acá 12) → GraphRecursionError.

Cómo se depura:
  1. Mirar la forma del grafo (Mermaid): ¿hay un ciclo sin salida que no dependa del modelo?
  2. Leer la historia del estado en el checkpointer: qué nodo corrió en cada step y qué
     herramienta se pidió. El patrón salta a la vista (la misma llamada, una y otra vez).
  3. Arreglar y comprobar: con el nodo `control` el mismo caso termina en "repetida".

`recursion_limit` NO reemplaza a las stopping rules: corta con una excepción (sin respuesta
para el pasajero), cuenta pasos del grafo y no del LLM, y no sabe nada de costo ni de
repeticiones.

Uso:
  python src/c2/05_debug_grafo.py
"""
import sys
import uuid
from pathlib import Path

from langgraph.errors import GraphRecursionError

sys.path.insert(0, str(Path(__file__).parents[1]))
from orbitair.data import load_consultas_c1  # noqa: E402
from orbitair.grafo import RESULTS, ConfigAgente, abrir_checkpointer, construir_grafo, entrada_turno  # noqa: E402
from orbitair.llm import MOCK, MODELO  # noqa: E402
from orbitair.operaciones import reiniciar_db  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")
LIMITE = 12


def main():
    caso = next(c for c in load_consultas_c1() if c["id"] == "A-10")
    if MOCK:
        print("⚠ ORBITAIR_MOCK=1 → el guion obedece siempre al prompt ingenuo.\n")
    reiniciar_db()
    cfg_agente = ConfigAgente(prompt="ingenuo")
    print(f"Modelo {MODELO} · prompt ingenuo · {caso['id']}: {caso['consulta']}\n")

    # 1 · La forma del grafo
    roto = construir_grafo(cfg_agente, checkpointer=abrir_checkpointer("memoria"), con_control=False)
    sano = construir_grafo(cfg_agente, checkpointer=abrir_checkpointer("memoria"))
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / "c2_grafo_sin_control.mmd").write_text(roto.get_graph().draw_mermaid(), encoding="utf-8")
    aristas = lambda g: sorted(f"{e.source}→{e.target}" for e in g.get_graph().edges)  # noqa: E731
    print("1 · Forma del grafo (también en results/c2_grafo_sin_control.mmd)")
    print(f"   sin control: {', '.join(aristas(roto))}")
    print(f"   con control: {', '.join(aristas(sano))}\n")

    # 2 · Correrlo y leer la historia del estado
    cfg = {"configurable": {"thread_id": f"debug-{uuid.uuid4().hex[:6]}"}, "recursion_limit": LIMITE}
    print(f"2 · Correr el grafo sin control (recursion_limit={LIMITE})")
    try:
        roto.invoke(entrada_turno(caso["consulta"], caso["pasajero_id"]), cfg)
        print("   terminó sin error (¿el modelo paró solo?)")
    except GraphRecursionError as e:
        print(f"   ✗ GraphRecursionError: {str(e).splitlines()[0]}")
    historia = list(reversed(list(roto.get_state_history(cfg))))
    print(f"\n   La historia quedó en el checkpointer ({len(historia)} checkpoints). Step a step:")
    print(f"   {'step':>4}  {'nodo que corrió':<15} {'pasos LLM':>9}  qué pidió el modelo")
    for i, snap in enumerate(historia):
        nodo = ",".join(historia[i - 1].next) if i else ""      # lo que estaba "por correr" en el checkpoint anterior
        ultimo = (snap.values.get("mensajes") or [{}])[-1]
        pedido = ", ".join(f"{t['function']['name']}({t['function']['arguments']})"
                           for t in ultimo.get("tool_calls") or []) if ultimo.get("role") == "assistant" else ""
        nodo = nodo if nodo and nodo != "__start__" else "(entrada)"
        print(f"   {snap.metadata.get('step', '?'):>4}  {nodo or '·':<15} {snap.values.get('pasos', 0):>9}  {pedido}")
    firmas = historia[-1].values.get("firmas", [])
    print(f"\n   Diagnóstico: {len(firmas)} llamadas, {len(set(firmas))} distinta(s): {sorted(set(firmas))}. "
          f"El modelo pide lo mismo esperando otro resultado y nada en el grafo lo frena.\n")

    # 3 · El arreglo
    cfg2 = {"configurable": {"thread_id": f"debug-{uuid.uuid4().hex[:6]}"}, "recursion_limit": LIMITE}
    final = sano.invoke(entrada_turno(caso["consulta"], caso["pasajero_id"]), cfg2)
    print(f"3 · Con el nodo control: parada={final['parada']} · {final['pasos']} pasos de LLM · "
          f"{len(final['firmas'])} llamadas a la herramienta")
    print(f"   → {final['respuesta'][:180]}…")


if __name__ == "__main__":
    main()
