"""Deja el starter con las clases ANTERIORES resueltas, copiando los archivos desde src/.

Cada clase construye sobre la anterior (C2 migra a LangGraph el agente de C1, etc.).
Antes de empezar la clase N, correr:

    python starter/resolver_hasta.py 1      # antes de C2: deja C1 resuelto, C2 con TODOs
    python starter/resolver_hasta.py 2      # antes de C3: deja C1 y C2 resueltos, C3 con TODOs
    python starter/resolver_hasta.py 3      # antes de C4: deja C1 a C3 resueltos, C4 con TODOs
    python starter/resolver_hasta.py 4      # antes de C5: deja C1 a C4 resueltos, C5 con TODOs
    python starter/resolver_hasta.py 0      # volver TODO a esqueleto (requiere git: git checkout starter/)

Sólo copia los archivos de las clases indicadas; los de la clase en curso quedan con sus TODOs.
"""
import shutil
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parents[1]
SRC, STARTER = ROOT / "src", ROOT / "starter"

ARCHIVOS_POR_CLASE = {
    1: ["orbitair/tools.py", "orbitair/agente.py", "orbitair/errores.py", "orbitair/memoria.py"],
    2: ["orbitair/grafo.py"],
    3: ["orbitair/workers.py", "orbitair/orquestador.py"],
    4: ["orbitair/mcp_server.py", "orbitair/mcp_cliente.py"],
    5: ["orbitair/trazas.py", "orbitair/evals.py"],
}


def main():
    hasta = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    if hasta == 0:
        sys.exit("Para volver al esqueleto: git checkout -- starter/")
    copiados = []
    for clase, archivos in ARCHIVOS_POR_CLASE.items():
        if clase > hasta:
            continue
        for rel in archivos:
            shutil.copy(SRC / rel, STARTER / rel)
            copiados.append(rel)
    print(f"✓ Clases 1..{hasta} resueltas en starter/ ({len(copiados)} archivos copiados desde src/):")
    for rel in copiados:
        print(f"  starter/{rel}")
    siguiente = hasta + 1
    if siguiente in ARCHIVOS_POR_CLASE:
        print(f"\nLa clase {siguiente} queda con sus TODOs en: "
              + ", ".join(f"starter/{r}" for r in ARCHIVOS_POR_CLASE[siguiente]))


if __name__ == "__main__":
    main()
