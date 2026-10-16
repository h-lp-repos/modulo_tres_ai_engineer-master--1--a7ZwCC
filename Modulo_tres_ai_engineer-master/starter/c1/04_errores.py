"""C1 · Ejercicio 4 · Triage de errores: recuperables vs duros.

Cinco escenarios con fallas inyectadas en el sistema de operaciones (orbitair/operaciones.py):

  E1 · timeout x2 en el sistema de valijas (A-11)  → REINTENTAR: el harness reintenta, el modelo ni se entera
  E2 · timeout x5 (A-11)                           → los reintentos se agotan: pasa a duro → derivación
  E3 · código de vuelo de otra aerolínea (A-07)    → INFORMAR_AL_MODELO: el modelo explica y pide el dato
  E4 · reserva de otra pasajera (A-09)             → ABORTAR: no se reintenta ni se le pasa nada al modelo
  E5 · base de operaciones caída (A-01)            → ABORTAR: derivación

Con --sin-triage, todos los errores vuelven al modelo como texto (lo que pasa si nadie
diseña el triage): mirar E1 (el modelo "reintenta" gastando pasos de LLM, y la regla
de repetidas lo corta) y E4.

Uso:
  python src/c1/04_errores.py
  python src/c1/04_errores.py --sin-triage
  python src/c1/04_errores.py --traza

Guarda results/c1_errores.md.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))
from orbitair import operaciones  # noqa: E402
from orbitair.agente import Agente  # noqa: E402
from orbitair.data import load_consultas_c1  # noqa: E402
from orbitair.errores import (INFORMAR_AL_MODELO, ErrorDeEntrada, ErrorDelSistema, ErrorDePermisos,  # noqa: E402
                              ErrorTransitorio, Intento, ResultadoTool, clasificar_error)
from orbitair.llm import MOCK, MODELO  # noqa: E402
from orbitair.pricing import fmt_usd  # noqa: E402
from orbitair.tools import ejecutar_tool  # noqa: E402
from orbitair.trayectoria import imprimir_traza  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")
RESULTS = Path(__file__).resolve().parents[2] / "results"

ESCENARIOS = [
    ("E1", "timeout x2 en valijas", "A-11", ("rastrear_valija", ["timeout", "timeout"])),
    ("E2", "timeout x5 en valijas", "A-11", ("rastrear_valija", ["timeout"] * 5)),
    ("E3", "vuelo de otra aerolínea", "A-07", None),
    ("E4", "reserva de otra pasajera", "A-09", None),
    ("E5", "base de operaciones caída", "A-01", ("db", ["caida"])),
]


class AgenteSinTriage(Agente):
    """Todo error vuelve al modelo como observación, sin reintentos ni cortes."""

    def ejecutar(self, tc):
        try:
            return ResultadoTool(True, ejecutar_tool(tc.nombre, tc.argumentos, self.ctx, self.herramientas),
                                 None, [Intento(1, None)])
        except Exception as e:  # noqa: BLE001
            return ResultadoTool(False, {"error": f"{type(e).__name__}: {e}"}, INFORMAR_AL_MODELO,
                                 [Intento(1, f"{type(e).__name__}: {e}")])


def main():
    sin_triage = "--sin-triage" in sys.argv
    casos = {c["id"]: c for c in load_consultas_c1()}
    if MOCK:
        print("⚠ ORBITAIR_MOCK=1 → el 'modelo' es un guion: ante un timeout que le llega como texto, reintenta.\n")
    print(f"Modelo {MODELO} · triage {'APAGADO (todo vuelve al modelo)' if sin_triage else 'activo'} · "
          f"hasta 2 reintentos con backoff 0.2 s / 0.4 s\n")
    print("Clasificación (clasificar_error):")
    for e in (ErrorTransitorio("timeout"), ErrorDeEntrada("formato"), ErrorDePermisos("ajena"),
              ErrorDelSistema("caído"), KeyError("inesperado")):
        print(f"   {type(e).__name__:<18} → {clasificar_error(e)}")
    print()
    clase = AgenteSinTriage if sin_triage else Agente
    filas = []
    for eid, titulo, cid, falla in ESCENARIOS:
        operaciones.reiniciar_db()
        operaciones.limpiar_fallas()
        c = casos[cid]
        agente = clase(c["pasajero_id"], operaciones.pasajero(c["pasajero_id"])["nombre"])
        if falla:
            operaciones.inyectar_fallas(*falla)
        r = agente.correr(c["consulta"])
        operaciones.limpiar_fallas()
        acciones = [a for p in r.pasos for a in p.acciones]
        decisiones = [a.resultado.decision or "ok" for a in acciones]
        intentos = sum(len(a.resultado.intentos) for a in acciones)
        filas.append((eid, titulo, cid, r, decisiones, intentos))
        print(f"{eid} · {titulo} · {cid}: {c['consulta']}")
        if "--traza" in sys.argv:
            imprimir_traza(r, ancho=110)
        else:
            for a in acciones:
                errores = [i.error for i in a.resultado.intentos if i.error]
                print(f"   {a.tool_call.nombre}: {len(a.resultado.intentos)} intento(s) · decisión: "
                      f"{a.resultado.decision or 'ok'}" + (f" · último error: {errores[-1]}" if errores else ""))
            print(f"   parada: {r.parada} · {len(r.pasos)} pasos de LLM · {r.tokens:,} tokens · {fmt_usd(r.costo_usd)}"
                  f" · {r.latencia_s:.1f} s")
            print(f"   → {r.respuesta[:200]}{'…' if len(r.respuesta) > 200 else ''}")
        print()

    lineas = ["## C1 · Triage de errores", "", f"- Modelo {MODELO}{' (MOCK)' if MOCK else ''} · triage "
              f"{'APAGADO' if sin_triage else 'activo'}", "",
              "| escenario | consulta | decisiones | intentos | pasos LLM | parada | USD |", "|---|---|---|---|---|---|---|"]
    lineas += [f"| {e} · {t} | {c} | {', '.join(d) or '—'} | {i} | {len(r.pasos)} | {r.parada} | {r.costo_usd:.5f} |"
               for e, t, c, r, d, i in filas]
    RESULTS.mkdir(exist_ok=True)
    nombre = "c1_errores_sin_triage.md" if sin_triage else "c1_errores.md"
    (RESULTS / nombre).write_text("\n".join(lineas), encoding="utf-8")
    print(f"✓ Guardado results/{nombre}")


if __name__ == "__main__":
    main()
