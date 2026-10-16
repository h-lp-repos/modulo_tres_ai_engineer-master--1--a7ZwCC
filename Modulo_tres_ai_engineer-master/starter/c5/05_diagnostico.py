"""C5 · Ejercicio 5 · Diagnóstico con trazas: un deploy que "anda bien" y cuesta de más.

Alguien "mejoró" el prompt del worker de equipaje para que siempre dé el estado definitivo de la
valija (es el prompt ingenuo de C1 · Ej. 3, ahora adentro de un worker). Se despliega como v2.

1. El experimento v2 sobre el dataset, contra la línea de base (Ejercicio 4).
2. ¿Qué dicen las métricas de calidad? ¿Y el gate?
3. ¿Dónde está el problema? Bajar de las métricas a los casos (delta de costo v1 → v2), del caso a su
   traza, y de la traza a la observación que se repite.

Nada que completar: es leer trazas como en producción.

Uso:
  python src/c5/05_diagnostico.py

Necesita la línea de base del Ejercicio 4 (si no está, corre v1 primero).
"""
import json
import sys
from collections import Counter
from functools import lru_cache, partial
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))
from orbitair import retrieval, trazas  # noqa: E402
from orbitair.data import load_consultas_c3  # noqa: E402
from orbitair.evals import EXPERIMENTOS, LINEA_BASE, chequear_regresion, experimento  # noqa: E402
from orbitair.grafo import ConfigAgente, construir_grafo  # noqa: E402
from orbitair.llm import MOCK, MODELO  # noqa: E402
from orbitair.operaciones import pasajero, reiniciar_db  # noqa: E402
from orbitair.orquestador import ConfigOrquestador, construir_orquestador  # noqa: E402
from orbitair.workers import AgenteWorker, config_worker  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")


@lru_cache(maxsize=1)
def worker_equipaje_v2():
    """El worker de equipaje con el prompt "ingenuo" de C1 (el resto, igual que en C3)."""
    return construir_grafo(ConfigAgente(prompt="ingenuo", herramientas=config_worker("equipaje").herramientas,
                                        fabrica=partial(AgenteWorker, dominio="equipaje")))


def main():
    if MOCK:
        print("⚠ ORBITAIR_MOCK=1 → el guion obedece al prompt ingenuo siempre (con la API real también, casi siempre).\n")
    reiniciar_db()
    retrieval.indice()
    casos = load_consultas_c3()
    nombres = {c["pasajero_id"]: pasajero(c["pasajero_id"])["nombre"] for c in casos}
    if not LINEA_BASE.exists():
        print("No hay línea de base: corro v1 primero (Ejercicio 4).")
        m = experimento("v1", construir_orquestador(), casos, nombres)
        LINEA_BASE.write_text(json.dumps({"run": "v1", "metricas": m}, indent=1), encoding="utf-8")
    base = json.loads(LINEA_BASE.read_text(encoding="utf-8"))
    v1 = json.loads((EXPERIMENTOS / f"{base['run']}.json").read_text(encoding="utf-8"))

    print(f"── 1 · Deploy v2: el worker de equipaje con el prompt nuevo · modelo {MODELO}\n")
    cfg = ConfigOrquestador(fabrica_worker=lambda d, _: worker_equipaje_v2() if d == "equipaje" else None)
    m2 = experimento("v2", construir_orquestador(cfg), casos, nombres)
    trazas.cerrar()
    mb = base["metricas"]
    for k in ("exito", "ruta_correcta", "herramientas_correctas", "hechos"):
        print(f"   {k:<24} {mb[k]:.0%} → {m2[k]:.0%}")
    for k in ("llamadas_por_consulta", "costo_por_consulta", "latencia_p95_s", "cortes_por_regla"):
        print(f"   {k:<24} {mb[k]:.5g} → {m2[k]:.5g}")

    print("\n── 2 · El gate")
    problemas = chequear_regresion(m2, mb)
    for p in problemas:
        print(f"   ✗ {p}")
    if not problemas:
        print("   ✓ pasa")
    print("   Calidad igual y costo casi igual (las stopping rules de C1 contienen el daño): lo único que se movió es\n"
          "   cuántas veces un worker terminó cortado por una regla. Sin esa métrica de COMPORTAMIENTO en el gate, v2\n"
          "   pasaba. La respuesta es la misma; lo que cambió es CÓMO se llega.")

    print("\n── 3 · ¿Dónde? Del agregado al caso, del caso a la traza")
    v2 = json.loads((EXPERIMENTOS / "v2.json").read_text(encoding="utf-8"))
    antes = {c["id"]: c for c in v1["casos"]}
    deltas = sorted(((c["costo_usd"] - antes[c["id"]]["costo_usd"], c) for c in v2["casos"]), key=lambda x: -x[0])
    print(f"\n   {'caso':<5} {'Δ USD':<10} {'LLM v1 → v2':<13} cortes por regla")
    for d, c in deltas[:5]:
        print(f"   {c['id']:<5} +${d:<9.5f} {antes[c['id']]['llamadas_llm']} → {c['llamadas_llm']:<8} {c['cortes_por_regla']}")
    afectados = [c["id"] for d, c in deltas if d > 1e-9]
    print(f"\n   Casos que empeoraron: {', '.join(afectados)}")
    tipo = {c["id"]: c for c in casos}
    comunes = set.intersection(*(set(tipo[i]["dominios"]) for i in afectados)) if afectados else set()
    print(f"   ¿Qué tienen en común? Todos pasan por: {', '.join(sorted(comunes)) or '(nada en común)'}")

    peor = deltas[0][1]
    obs = trazas.leer_traza(peor["traza_id"])
    print(f"\n   La traza de {peor['id']} en v2:\n\n   " + trazas.arbol(peor["traza_id"]).replace("\n", "\n   "))
    repetidas = Counter((o["nombre"], json.dumps(o["input"], sort_keys=True)) for o in obs if o["tipo"] == "tool")
    for (nombre, args), n in repetidas.items():
        if n > 1:
            print(f"\n   ⚠ {nombre}({args}) se llamó {n} veces con los mismos argumentos.")
    if any(o["nombre"] == "cierre" for o in obs):
        print("   ⚠ el worker terminó en el nodo `cierre`: lo cortó una stopping rule (C1), no paró solo.")
    print("\n   Diagnóstico: el prompt nuevo hace que el worker vuelva a consultar la valija hasta tener un estado final.\n"
          "   Las stopping rules lo cortan (por eso la respuesta no cambia), pero cada vuelta es una llamada al LLM\n"
          "   con todo el historial. Sin trazas, esto se ve como \"subió la factura\"; con trazas, es una línea.")


if __name__ == "__main__":
    main()
