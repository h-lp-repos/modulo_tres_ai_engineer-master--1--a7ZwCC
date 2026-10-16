"""C2 · Ejercicio 4 · Streaming de estados: ver el grafo mientras corre, no sólo al final.

`grafo.invoke()` devuelve el estado final: el pasajero mira una pantalla vacía hasta
que todo termina. `grafo.stream()` emite eventos a medida que pasan. Modos:

  - "updates": después de cada nodo, qué cambió en el estado (ideal para trazas y logs)
  - "values":  el estado COMPLETO después de cada paso (pesado, útil para depurar)
  - "custom":  lo que el nodo emite con `get_stream_writer()` — en `herramientas`:
               "consultando consultar_vuelo...", reintentos (ideal para la UI del pasajero)
  - "messages": tokens del LLM a medida que se generan. Requiere un chat model de LangChain
               (ChatOpenAI); con nuestro cliente propio no aplica (ver la guía).

Se combinan pasando una lista: stream_mode=["updates", "custom"] → eventos (modo, dato).

Uso:
  python src/c2/04_streaming.py                    # A-02 con updates + custom, con tiempos
  python src/c2/04_streaming.py --modo values
  python src/c2/04_streaming.py --id A-11 --fallas # timeouts inyectados: los reintentos se ven en vivo
"""
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))
from orbitair import operaciones  # noqa: E402
from orbitair.data import load_consultas_c1  # noqa: E402
from orbitair.grafo import abrir_checkpointer, construir_grafo, entrada_turno  # noqa: E402
from orbitair.llm import MOCK, MODELO  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")


def arg(flag: str, default=None):
    return sys.argv[sys.argv.index(flag) + 1] if flag in sys.argv else default


def describir_update(nodo: str, cambios: dict) -> str:
    cambios = cambios or {}
    partes = []
    for m in cambios.get("mensajes", []):
        if m.get("tool_calls"):
            partes.append("pide " + ", ".join(t["function"]["name"] for t in m["tool_calls"]))
        elif m["role"] == "assistant":
            partes.append("respuesta lista")
        elif m["role"] == "tool":
            partes.append("observación")
    if cambios.get("parada"):
        partes.append(f"parada={cambios['parada']}")
    return f"{nodo}: {', '.join(partes) or 'sin cambios relevantes'}"


def main():
    modo = arg("--modo", "updates")
    caso = next(c for c in load_consultas_c1() if c["id"] == arg("--id", "A-02"))
    if MOCK:
        print("⚠ ORBITAIR_MOCK=1 → latencias simuladas: con la API real, cada paso del LLM tarda ~1 s.\n")
    operaciones.reiniciar_db()
    if "--fallas" in sys.argv:
        operaciones.inyectar_fallas("rastrear_valija", ["timeout", "timeout"])
    grafo = construir_grafo(checkpointer=abrir_checkpointer("memoria"))
    cfg = {"configurable": {"thread_id": str(uuid.uuid4())}}
    print(f"Modelo {MODELO} · {caso['id']}: {caso['consulta']} · stream_mode={[modo, 'custom']}\n")

    t0 = time.perf_counter()
    primero = None
    for tipo, dato in grafo.stream(entrada_turno(caso["consulta"], caso["pasajero_id"]), cfg,
                                   stream_mode=[modo, "custom"]):
        t = time.perf_counter() - t0
        primero = primero or t
        if tipo == "custom":
            extra = f" ({dato['intentos']} intentos)" if dato.get("intentos", 1) > 1 else ""
            print(f"  {t:6.2f} s  [custom]  {dato['herramienta']}: {dato['estado']}{extra}")
        elif tipo == "updates":
            for nodo, cambios in dato.items():
                print(f"  {t:6.2f} s  [update]  {describir_update(nodo, cambios)}")
        else:   # values
            print(f"  {t:6.2f} s  [values]  {len(dato.get('mensajes', []))} mensajes · pasos={dato.get('pasos')} · "
                  f"parada={dato.get('parada')} · claves={sorted(dato)}")
    total = time.perf_counter() - t0
    operaciones.limpiar_fallas()
    final = grafo.get_state(cfg).values
    print(f"\n  → {final['respuesta']}\n")
    print(f"Primer evento a los {primero:.2f} s · respuesta completa a los {total:.2f} s. Con invoke() el pasajero "
          f"no ve nada durante {total:.2f} s; con stream() puede ver 'consultando tu vuelo…' desde el primer paso.")


if __name__ == "__main__":
    main()
