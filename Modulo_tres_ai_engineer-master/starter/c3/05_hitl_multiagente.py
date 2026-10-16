"""C3 · Ejercicio 5 · Human-in-the-loop adentro del multiagente: un worker pausa todo el sistema.

El worker de reembolsos se arma con acciones (`iniciar_reembolso`, la herramienta sensible de
C2). Es el MISMO grafo de C2, con su nodo `aprobacion` y su `interrupt()`, ahora corriendo
como worker, en paralelo con otro. Preguntas:

1. ¿Dónde se detiene? El interrupt sube desde el subgrafo del worker hasta el orquestador:
   `get_state()` del orquestador muestra la tarea pausada y el pedido de aprobación.
2. ¿Qué pasa con el otro worker, que ya terminó? Su resultado queda guardado en el checkpoint
   (pending writes del super-step): al reanudar NO se vuelve a ejecutar.
3. ¿Y el worker pausado? Su nodo se re-ejecuta, pero el subgrafo retoma desde su propio
   checkpoint: no repite las herramientas ni las llamadas al LLM que ya hizo.

Sin checkpointer en el orquestador no hay desde dónde reanudar (C2 · Ej. 3).

Uso:
  python src/c3/05_hitl_multiagente.py
  python src/c3/05_hitl_multiagente.py --decision rechazar
"""
import json
import sys
import uuid
from collections import Counter
from pathlib import Path

from langgraph.types import Command

sys.path.insert(0, str(Path(__file__).parents[1]))
from orbitair import agente, operaciones, orquestador, retrieval  # noqa: E402
from orbitair.grafo import abrir_checkpointer  # noqa: E402
from orbitair.llm import MOCK, MODELO  # noqa: E402
from orbitair.orquestador import ConfigOrquestador, construir_orquestador, entrada_orquestador  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")
PASAJERO, NOMBRE = "P-1001", "Lucía Fernández"
CONSULTA = "Quiero el reembolso de mi reserva M4TR88, que me cancelaron. ¿Y dónde está mi valija OA-582331?"


def arg(flag: str, default=None):
    return sys.argv[sys.argv.index(flag) + 1] if flag in sys.argv else default


# Contadores: cuántas veces corre cada worker y cuántas llamadas al LLM hace (para ver qué se repite al reanudar).
corridas, llamadas = Counter(), Counter()
_correr_worker, _completar = orquestador.correr_worker, agente.completar_con_tools


def correr_worker_contado(t, cfg):
    corridas[t["dominio"]] += 1
    return _correr_worker(t, cfg)


def completar_contado(mensajes, *a, **kw):
    sistema = mensajes[0]["content"]
    llamadas[next((d for d in ("equipaje", "cambios", "reembolsos") if f"especialista en {d}" in sistema), "?")] += 1
    return _completar(mensajes, *a, **kw)


orquestador.correr_worker = correr_worker_contado
agente.completar_con_tools = completar_contado


def reembolsos() -> list[str]:
    r = operaciones.consultar_reserva("M4TR88", PASAJERO)["reembolsos"]
    return [f"{x['id']} USD {x['monto_usd']:.0f} {x['estado']}" for x in r] or ["ninguno"]


def contadores(momento: str) -> None:
    print(f"   {momento}: corridas de cada worker {dict(corridas)} · llamadas al LLM por worker {dict(llamadas)}")


def main():
    if MOCK:
        print("⚠ ORBITAIR_MOCK=1 → el 'modelo' pide el reembolso cuando el vuelo de la reserva está cancelado.\n")
    operaciones.reiniciar_db()
    retrieval.indice()
    print(f"Modelo {MODELO} · {PASAJERO}: {CONSULTA}\n")
    grafo = construir_orquestador(ConfigOrquestador(acciones=True), checkpointer=abrir_checkpointer("memoria"))
    cfg = {"configurable": {"thread_id": f"hitl-c3-{uuid.uuid4().hex[:6]}"}}

    print("── 1 · Corre hasta la pausa")
    grafo.invoke(entrada_orquestador(CONSULTA, PASAJERO, NOMBRE), cfg)
    estado = grafo.get_state(cfg)
    print(f"   el orquestador está detenido antes de: {estado.next}")
    for tarea in estado.tasks:
        if tarea.interrupts:
            print(f"   tarea pausada: nodo '{tarea.name}' · namespace del subgrafo: {tarea.id[:8]}…")
            print(f"   lo que ve el supervisor: {json.dumps(tarea.interrupts[0].value, ensure_ascii=False)}")
    print(f"   intenciones: {[i['dominio'] for i in estado.values['intenciones']]} · resultados ya guardados en el "
          f"checkpoint: {[r['dominio'] for r in estado.values.get('resultados', [])]}")
    print(f"   reembolsos de M4TR88 en la base: {reembolsos()}")
    contadores("antes de reanudar")

    decision = arg("--decision", "aprobar")
    resume = {"aprobar": {"decision": "aprobar"},
              "rechazar": {"decision": "rechazar", "motivo": "la pasajera aceptó la reprogramación"}}[decision]
    print(f"\n── 2 · El supervisor decide: {decision}")
    final = grafo.invoke(Command(resume=resume), cfg)
    print(f"   reembolsos de M4TR88 en la base: {reembolsos()}")
    contadores("después de reanudar")
    print("   → el worker de equipaje no se volvió a ejecutar; el de reembolsos sí, pero retomó su subgrafo "
          "desde la pausa (una sola llamada más al LLM: la respuesta).")
    print(f"\n── 3 · Respuesta al pasajero (parada={final['parada']}, {final['llamadas_llm']} llamadas al LLM)\n")
    print(f"   {final['respuesta']}")
    operaciones.reiniciar_db()


if __name__ == "__main__":
    main()
