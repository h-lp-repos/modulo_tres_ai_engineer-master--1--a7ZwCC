"""C2 · Ejercicio 3 · Human-in-the-loop: el agente propone iniciar un reembolso y un supervisor decide.

`iniciar_reembolso` es la primera herramienta que ESCRIBE (crea el trámite en la base).
El grafo la manda al nodo `aprobacion`, que llama a `interrupt()`: la ejecución se
detiene, el estado queda guardado en el checkpointer y el grafo devuelve lo que el
supervisor necesita para decidir. Se reanuda con `Command(resume={...})`.

La pasajera P-1001 escribe: "Me cancelaron el vuelo de la reserva M4TR88. Quiero el
reembolso." (OA1388 cancelado por causa operativa). Tres supervisores, tres threads:
  - aprobar  → se ejecuta tal cual → reembolso de USD 412 en estado "solicitado"
  - editar   → el supervisor corrige el monto (USD 206) → se ejecuta con el monto editado
  - rechazar → no se ejecuta; el modelo recibe el rechazo como observación y se lo explica

Y la pausa sobrevive al proceso (el supervisor aprueba horas después, desde otro lado):
  python src/c2/03_human_in_the_loop.py --pausar                       # corre hasta el interrupt y sale
  python src/c2/03_human_in_the_loop.py --reanudar aprobar             # otro proceso: retoma y decide
  python src/c2/03_human_in_the_loop.py --reanudar editar --monto 206
"""
import json
import sys
import uuid
from pathlib import Path

from langgraph.types import Command

sys.path.insert(0, str(Path(__file__).parents[1]))
from orbitair import operaciones  # noqa: E402
from orbitair.grafo import RESULTS, ConfigAgente, abrir_checkpointer, construir_grafo, entrada_turno  # noqa: E402
from orbitair.historial import observaciones  # noqa: E402
from orbitair.llm import MOCK, MODELO  # noqa: E402
from orbitair.tools import HERRAMIENTAS_C2  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")
PASAJERO, NOMBRE = "P-1001", "Lucía Fernández"
CONSULTA = "Me cancelaron el vuelo de la reserva M4TR88. Quiero el reembolso."
DB_HITL = RESULTS / "c2_hitl.db"
THREAD = "reembolso-M4TR88"
CFG = ConfigAgente(herramientas=HERRAMIENTAS_C2)


def arg(flag: str, default=None):
    return sys.argv[sys.argv.index(flag) + 1] if flag in sys.argv else default


def decision_de(tipo: str, monto: float) -> dict:
    return {"aprobar": {"decision": "aprobar"},
            "editar": {"decision": "editar", "argumentos": {"monto_usd": monto}},
            "rechazar": {"decision": "rechazar", "motivo": "el pasajero ya aceptó la reprogramación por teléfono"}}[tipo]


def mostrar_pausa(estado) -> None:
    pedido = estado.interrupts[0].value
    print(f"   [pausa] el grafo se detuvo antes de: {estado.next}")
    print(f"   lo que ve el supervisor: {json.dumps(pedido, ensure_ascii=False)}")
    pasos_previos = [o.nombre for o in observaciones(estado.values["mensajes"])]
    print(f"   herramientas que ya corrió el agente: {pasos_previos} · reembolsos de M4TR88 en la base: "
          f"{reembolsos()}")


def reembolsos() -> list[str]:
    r = operaciones.consultar_reserva("M4TR88", PASAJERO)["reembolsos"]
    return [f"{x['id']} USD {x['monto_usd']:.0f} {x['estado']}" for x in r] or ["ninguno"]


def reanudar(grafo, cfg: dict, tipo: str, monto: float) -> None:
    final = grafo.invoke(Command(resume=decision_de(tipo, monto)), cfg)
    print(f"   [reanuda] supervisor: {tipo}{f' (USD {monto:.0f})' if tipo == 'editar' else ''}")
    print(f"   reembolsos de M4TR88 en la base: {reembolsos()}")
    print(f"   → {final['respuesta']}\n")


def tres_supervisores() -> None:
    grafo = construir_grafo(CFG, checkpointer=abrir_checkpointer("memoria"))
    for tipo in ("aprobar", "editar", "rechazar"):
        operaciones.reiniciar_db()
        cfg = {"configurable": {"thread_id": f"{tipo}-{uuid.uuid4().hex[:6]}"}}
        print(f"── Supervisor que va a {tipo.upper()}")
        grafo.invoke(entrada_turno(CONSULTA, PASAJERO, NOMBRE), cfg)
        mostrar_pausa(grafo.get_state(cfg))
        reanudar(grafo, cfg, tipo, 206.0)


def main():
    if MOCK:
        print("⚠ ORBITAIR_MOCK=1 → el 'modelo' es un guion: pide el reembolso cuando el vuelo de la reserva está "
              "cancelado.\n")
    print(f"Modelo {MODELO} · pasajera {PASAJERO}: {CONSULTA}\n")
    monto = float(arg("--monto", 206))
    if "--pausar" in sys.argv:
        operaciones.reiniciar_db()
        for sufijo in ("", "-wal", "-shm"):
            Path(f"{DB_HITL}{sufijo}").unlink(missing_ok=True)
        grafo = construir_grafo(CFG, checkpointer=abrir_checkpointer("sqlite", DB_HITL))
        cfg = {"configurable": {"thread_id": THREAD}}
        grafo.invoke(entrada_turno(CONSULTA, PASAJERO, NOMBRE), cfg)
        mostrar_pausa(grafo.get_state(cfg))
        print(f"\n   El proceso termina acá. El estado quedó en {DB_HITL.name} (thread {THREAD}).")
        print("   Retomar: python src/c2/03_human_in_the_loop.py --reanudar aprobar|editar|rechazar")
    elif arg("--reanudar"):
        grafo = construir_grafo(CFG, checkpointer=abrir_checkpointer("sqlite", DB_HITL))
        cfg = {"configurable": {"thread_id": THREAD}}
        estado = grafo.get_state(cfg)
        if not estado.interrupts:
            sys.exit("No hay nada pendiente de aprobación en ese thread: correr primero con --pausar.")
        print(f"── Proceso nuevo: el thread {THREAD} está pausado en {estado.next}")
        reanudar(grafo, cfg, arg("--reanudar"), monto)
    else:
        tres_supervisores()
        operaciones.reiniciar_db()


if __name__ == "__main__":
    main()
