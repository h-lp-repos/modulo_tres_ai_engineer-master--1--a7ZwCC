"""C2 · Ejercicio 2 · Checkpoints: el estado del grafo se guarda después de cada paso, por thread.

Parte A · Conversación sin armar el historial a mano. Los 3 turnos de C1 · Ej. 5 en un
mismo `thread_id`: el checkpointer guarda los mensajes y el grafo los recupera solo.
Se compara con un thread nuevo (sin historia).

Parte B · Sobrevivir a un reinicio. Con SqliteSaver (results/c2_checkpoints.db) el turno 1
y el turno 2 corren con grafos y conexiones DISTINTAS (como si el proceso se hubiera
reiniciado entre medio). Para hacerlo en dos procesos de verdad:
    python src/c2/02_checkpoints.py --turno 1
    python src/c2/02_checkpoints.py --turno 2

Parte C · La historia del estado. `get_state_history()` lista un checkpoint por paso:
qué nodo viene, cuántos mensajes había, cuántos pasos de LLM. Y "time travel": volver
a correr desde un checkpoint del pasado.

Uso:
  python src/c2/02_checkpoints.py
  python src/c2/02_checkpoints.py --parte C
"""
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))
from orbitair.grafo import RESULTS, abrir_checkpointer, construir_grafo, entrada_turno  # noqa: E402
from orbitair.historial import observaciones  # noqa: E402
from orbitair.llm import MOCK, MODELO, contar_tokens  # noqa: E402
from orbitair.operaciones import reiniciar_db  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")
PASAJERO, NOMBRE = "P-1001", "Lucía Fernández"
TURNOS = ["Estoy en Ezeiza, el OA0417 está demorado hace horas. ¿Me tienen que dar algo para comer?",
          "¿Y a qué hora sale ahora ese vuelo?",
          "Gracias. Otra cosa: ¿dónde está mi valija OA-582331?"]
THREAD_SQLITE = "lucia-sqlite"


def arg(flag: str, default=None):
    return sys.argv[sys.argv.index(flag) + 1] if flag in sys.argv else default


def turno(grafo, thread: str, texto: str, i: int) -> dict:
    cfg = {"configurable": {"thread_id": thread}}
    s = grafo.invoke(entrada_turno(texto, PASAJERO, NOMBRE), cfg)
    usadas = [o.nombre for o in observaciones(s["mensajes"])]
    print(f"   T{i} {texto}")
    print(f"      mensajes en el estado del thread: {len(s['mensajes'])} (~{contar_tokens(s['mensajes']):,} tokens) · "
          f"herramientas acumuladas: {usadas}")
    print(f"      → {s['respuesta'][:160]}{'…' if len(s['respuesta']) > 160 else ''}")
    return s


def parte_a() -> None:
    print("PARTE A · Memoria de conversación con InMemorySaver\n")
    grafo = construir_grafo(checkpointer=abrir_checkpointer("memoria"))
    thread = f"lucia-{uuid.uuid4().hex[:6]}"
    print(f"── thread_id={thread} (los 3 turnos en el mismo thread)")
    for i, t in enumerate(TURNOS, 1):
        turno(grafo, thread, t, i)
    print(f"\n── thread nuevo, sólo el turno 2")
    turno(grafo, f"otro-{uuid.uuid4().hex[:6]}", TURNOS[1], 2)
    print("\n   Mismo grafo, mismo código: lo que cambia es el thread_id. El historial que en C1 armábamos a mano "
          "(Sesion) ahora lo guarda el checkpointer.\n")


def parte_b(solo_turno: int | None) -> None:
    print("PARTE B · Sobrevivir a un reinicio con SqliteSaver (results/c2_checkpoints.db)\n")
    db = RESULTS / "c2_checkpoints.db"
    if solo_turno in (None, 1):
        for sufijo in ("", "-wal", "-shm"):
            Path(f"{db}{sufijo}").unlink(missing_ok=True)
    for i in ([solo_turno] if solo_turno else [1, 2]):
        grafo = construir_grafo(checkpointer=abrir_checkpointer("sqlite", db))     # grafo y conexión nuevos
        print(f"── proceso {'actual' if solo_turno else f'simulado #{i}'}: grafo recién construido, thread_id="
              f"{THREAD_SQLITE}")
        previo = grafo.get_state({"configurable": {"thread_id": THREAD_SQLITE}}).values
        print(f"   al abrir: el thread ya tiene {len(previo.get('mensajes', []))} mensajes guardados")
        turno(grafo, THREAD_SQLITE, TURNOS[i - 1], i)
        print()


def parte_c() -> None:
    print("PARTE C · Historia del estado y time travel\n")
    grafo = construir_grafo(checkpointer=abrir_checkpointer("memoria"))
    cfg = {"configurable": {"thread_id": "historia"}}
    grafo.invoke(entrada_turno(TURNOS[0], PASAJERO, NOMBRE), cfg)
    historia = list(grafo.get_state_history(cfg))            # del más nuevo al más viejo
    print(f"{len(historia)} checkpoints para un turno de {TURNOS[0][:40]}…\n")
    print(f"   {'step':>4}  {'próximo nodo':<15} {'mensajes':>8} {'pasos LLM':>9}  checkpoint_id")
    for snap in reversed(historia):
        v = snap.values
        print(f"   {snap.metadata.get('step', '?'):>4}  {','.join(snap.next) or '(fin)':<15} "
              f"{len(v.get('mensajes', [])):>8} {v.get('pasos', 0):>9}  {snap.config['configurable']['checkpoint_id']}")

    # Time travel: volver al checkpoint en el que el próximo nodo era 'herramientas' por primera vez.
    destino = next(s for s in reversed(historia) if s.next == ("herramientas",))
    print(f"\n── Time travel: volver a correr desde step {destino.metadata['step']} (antes de ejecutar "
          f"{[tc['function']['name'] for tc in destino.values['mensajes'][-1]['tool_calls']]})")
    final = grafo.invoke(None, destino.config)      # None = no agregar input: continuar desde ese punto
    print(f"   → {final['respuesta'][:160]}…")
    print(f"   La historia del thread ahora tiene {len(list(grafo.get_state_history(cfg)))} checkpoints: la "
          f"re-ejecución es una RAMA nueva desde el step {destino.metadata['step']}; la original sigue ahí.")
    print("   Con la API real la rama puede terminar distinto (el modelo no es determinista): así se "
          "reproduce y depura un paso puntual sin repetir toda la conversación.")


def main():
    if MOCK:
        print("⚠ ORBITAIR_MOCK=1 → el 'modelo' es un guion determinista.\n")
    print(f"Modelo {MODELO} · pasajera {PASAJERO}\n")
    reiniciar_db()
    solo = int(arg("--turno")) if arg("--turno") else None
    parte = arg("--parte") or ("B" if solo else None)
    if parte in (None, "A"):
        parte_a()
    if parte in (None, "B"):
        parte_b(solo)
    if parte in (None, "C"):
        parte_c()


if __name__ == "__main__":
    main()
