"""C5 · Ejercicio 1 · Instrumentar el sistema multiagente y leer una traza.

Corre una consulta del dataset de C3 adentro de una traza y la muestra como la muestra la UI
de Langfuse: el árbol de observaciones (router → workers en paralelo → nodos → generations y
tools → síntesis), con cuándo empezó cada una, cuánto duró, tokens, costo y errores.

Con credenciales de Langfuse en el .env, la traza también se manda a Langfuse y se imprime su
link. Sin credenciales (o con ORBITAIR_TRAZAS=local), queda sólo en results/c5_trazas/.

Uso:
  python src/c5/01_trazas.py                  # M-17: valija demorada + vuelo con demora
  python src/c5/01_trazas.py --id M-24        # falla parcial: una tool con error duro
  python src/c5/01_trazas.py --id M-23        # tres workers en paralelo
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))
from orbitair import retrieval, trazas  # noqa: E402
from orbitair.data import load_consultas_c3  # noqa: E402
from orbitair.evals import atender  # noqa: E402
from orbitair.llm import MOCK, MODELO  # noqa: E402
from orbitair.operaciones import pasajero, reiniciar_db  # noqa: E402
from orbitair.orquestador import construir_orquestador  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")


def arg(flag: str, default=None):
    return sys.argv[sys.argv.index(flag) + 1] if flag in sys.argv else default


def main():
    if MOCK:
        print("⚠ ORBITAIR_MOCK=1 → 'modelo' guionado: tokens y costo se cuentan igual (con tiktoken y pricing.json).\n")
    print(f"Trazas: {'Langfuse + local' if trazas.LANGFUSE else 'local (results/c5_trazas)'} · modelo {MODELO}\n")
    reiniciar_db()
    retrieval.indice()
    caso = next(c for c in load_consultas_c3() if c["id"] == arg("--id", "M-17"))
    grafo = construir_orquestador()
    corrida = atender(grafo, caso["consulta"], caso["pasajero_id"], pasajero(caso["pasajero_id"])["nombre"],
                      session_id=f"demo-{caso['id']}", tags=["c5", "demo"], metadata={"caso": caso["id"]})
    trazas.cerrar()

    print(f"{caso['id']} · {caso['consulta']}\n")
    print(trazas.arbol(corrida.traza_id))
    fila = next(f for f in trazas.leer_indice() if f["traza_id"] == corrida.traza_id)
    print(f"\nTraza {corrida.traza_id} · sesión {fila['session_id']} · usuario {fila['user_id']} · tags {fila['tags']}")
    print(f"Total: {fila['llamadas_llm']} llamadas al LLM · {fila['tokens']:,} tokens · ${fila['costo_usd']:.5f} · "
          f"{fila['latencia_s']:.2f} s · {fila['errores']} errores · {fila['advertencias']} advertencias")
    print(f"\n→ {corrida.estado['respuesta'][:300]}")
    if trazas.LANGFUSE:
        print(f"\nEn Langfuse: {trazas.url(corrida.traza_id)}")
    print(f"\n✓ Guardado results/c5_trazas/{corrida.traza_id}.json")


if __name__ == "__main__":
    main()
