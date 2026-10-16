"""C1 · Ejercicio 3 · Colgar el loop a propósito y salvarlo con stopping rules.

El caso: A-10, una valija EN BÚSQUEDA (PIR LIM-48213), sin estado final. Con el prompt
"de primer intento" (SISTEMA_INGENUO: "si el estado no es final, volvé a consultar
hasta tenerlo"), el modelo consulta la valija una y otra vez: el estado no va a
cambiar durante la conversación, y nada en el loop le dice que pare.

Cuatro configuraciones, misma consulta:
  1. prompt ingenuo · SIN reglas         → sólo lo frena el fusible del ejercicio (15 vueltas)
  2. prompt ingenuo · sólo max_pasos     → la red de seguridad gruesa
  3. prompt ingenuo · reglas completas   → "repetida" lo corta a la 2ª llamada idéntica
  4. prompt de producción · reglas       → el modelo para solo (el arreglo de fondo)

Uso:
  python src/c1/03_colgar_el_loop.py
  python src/c1/03_colgar_el_loop.py --traza        # la traza completa de cada configuración

Guarda results/c1_stopping_rules.md.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))
from orbitair.agente import SIN_REGLAS, Agente, ReglasDeParada  # noqa: E402
from orbitair.data import load_consultas_c1  # noqa: E402
from orbitair.llm import MOCK, MODELO  # noqa: E402
from orbitair.operaciones import pasajero, reiniciar_db  # noqa: E402
from orbitair.pricing import fmt_usd  # noqa: E402
from orbitair.trayectoria import imprimir_traza  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")
RESULTS = Path(__file__).resolve().parents[2] / "results"
FUSIBLE = 15

CONFIGS = [
    ("1 · ingenuo · sin reglas", "ingenuo", SIN_REGLAS),
    ("2 · ingenuo · sólo max_pasos=6", "ingenuo", ReglasDeParada(max_repeticiones=10**6)),
    ("3 · ingenuo · reglas completas", "ingenuo", ReglasDeParada()),
    ("4 · producción · reglas completas", "produccion", ReglasDeParada()),
]


def main():
    caso = next(c for c in load_consultas_c1() if c["id"] == "A-10")
    if MOCK:
        print("⚠ ORBITAIR_MOCK=1 → el guion obedece al prompt ingenuo siempre. Con la API real el loop también se "
              "cuelga, pero la cantidad de vueltas varía entre corridas.\n")
    reiniciar_db()
    print(f"{caso['id']} · {caso['consulta']}  (pasajero {caso['pasajero_id']})\nModelo {MODELO} · fusible del "
          f"ejercicio: {FUSIBLE} vueltas\n")
    nombre = pasajero(caso["pasajero_id"])["nombre"]
    filas = []
    for titulo, prompt, reglas in CONFIGS:
        r = Agente(caso["pasajero_id"], nombre, prompt=prompt, reglas=reglas, fusible=FUSIBLE).correr(caso["consulta"])
        consultas = r.herramientas.count("rastrear_valija")
        filas.append((titulo, r, consultas))
        print(f"{titulo}")
        if "--traza" in sys.argv:
            imprimir_traza(r, ancho=110)
        print(f"   parada: {r.parada} · {len(r.pasos)} pasos · {consultas} consultas a la valija · {r.tokens:,} tokens"
              f" · {fmt_usd(r.costo_usd)} · {r.latencia_s:.1f} s")
        print(f"   tokens de entrada por paso: {[p.llm.tokens_in for p in r.pasos]}")
        print(f"   → {r.respuesta[:200]}{'…' if len(r.respuesta) > 200 else ''}\n")

    base = filas[-1][1].costo_usd
    peor = filas[0][1].costo_usd
    print(f"Sin reglas, esta consulta cuesta {peor / base:.0f}× la versión que para sola, y la respuesta no mejora: "
          f"el estado era el mismo en la 1ª consulta que en la {filas[0][2]}ª.")
    print(f"Proyección: si el 2% de 10.000 consultas/día cae en un caso así, el loop sin reglas suma "
          f"USD {(peor - base) * 200 * 30:,.2f}/mes (y {filas[0][1].latencia_s - filas[-1][1].latencia_s:.1f} s más de "
          f"espera para cada uno de esos pasajeros). Y eso con un fusible: sin él, no termina.")

    lineas = ["## C1 · Stopping rules", "", f"- {caso['id']} · modelo {MODELO}{' (MOCK)' if MOCK else ''} · fusible "
              f"{FUSIBLE}", "", "| config | parada | pasos | consultas a la valija | tokens | USD |",
              "|---|---|---|---|---|---|"]
    lineas += [f"| {t} | {r.parada} | {len(r.pasos)} | {n} | {r.tokens} | {r.costo_usd:.5f} |" for t, r, n in filas]
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / "c1_stopping_rules.md").write_text("\n".join(lineas), encoding="utf-8")
    print("\n✓ Guardado results/c1_stopping_rules.md")


if __name__ == "__main__":
    main()
