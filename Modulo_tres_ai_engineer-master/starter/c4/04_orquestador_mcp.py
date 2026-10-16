"""C4 · Ejercicio 4 · El worker de reembolsos sobre MCP, adentro del orquestador de C3.

El track pide el server "conectado al agente de reembolsos". El orquestador de C3 recibe una
`fabrica_worker`: para el dominio reembolsos arma el worker sobre MCP (una sesión por pasajero);
los otros dos siguen con herramientas locales. Para el resto del sistema es transparente.

Parte A · Las consultas del dataset de C3 que pasan por reembolsos, con el worker local (C3) y
con el worker MCP (sesión de rol "consulta": sólo lectura). Misma ruta y trayectoria.

Parte B · Escribir: "quiero el reembolso". Sesión de rol "reembolsos" (el server ahora sí
publica iniciar_reembolso). ¿Dónde vive la aprobación humana? En el HOST: el grafo de C2 manda
la tool sensible al nodo `aprobacion` antes de llamar al server. El server, además, valida y
audita. Dos capas: el host decide si se pide; el server decide si se puede.

Uso:
  python src/c4/04_orquestador_mcp.py

Guarda results/c4_orquestador_mcp.md.
"""
import json
import sys
import uuid
from pathlib import Path

from langgraph.types import Command

sys.path.insert(0, str(Path(__file__).parents[1]))
from orbitair import operaciones, retrieval  # noqa: E402
from orbitair.data import load_consultas_c3  # noqa: E402
from orbitair.grafo import abrir_checkpointer, construir_grafo  # noqa: E402
from orbitair.llm import MOCK, MODELO  # noqa: E402
from orbitair.mcp_cliente import ClienteMCP, config_worker_mcp  # noqa: E402
from orbitair.mcp_server import AUDITORIA  # noqa: E402
from orbitair.orquestador import ConfigOrquestador, construir_orquestador, entrada_orquestador, resumen  # noqa: E402
from orbitair.trayectoria import chequear, marca  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")
RESULTS = Path(__file__).resolve().parents[2] / "results"
CONSULTA_B = "Quiero el reembolso de mi reserva M4TR88, que me cancelaron."


class SesionesMCP:
    """Una sesión MCP por pasajero (y rol), abierta a demanda. Es lo que haría el host por usuario conectado."""

    def __init__(self, rol: str):
        self.rol, self.clientes, self.grafos = rol, {}, {}

    def fabrica(self, dominio: str, pasajero_id: str):
        if dominio != "reembolsos":
            return None                                       # los otros workers: los de C3
        if pasajero_id not in self.clientes:
            self.clientes[pasajero_id] = ClienteMCP(pasajero_id, rol=self.rol)
            self.grafos[pasajero_id] = construir_grafo(config_worker_mcp("reembolsos", self.clientes[pasajero_id]))
        return self.grafos[pasajero_id]

    def cerrar(self):
        for c in self.clientes.values():
            c.cerrar()


def parte_a() -> list[str]:
    casos = [c for c in load_consultas_c3() if "reembolsos" in c["dominios"]]
    sesiones = SesionesMCP("consulta")
    local = construir_orquestador()
    mcp = construir_orquestador(ConfigOrquestador(fabrica_worker=sesiones.fabrica))
    print(f"── Parte A · {len(casos)} consultas con el dominio reembolsos · worker local vs worker MCP\n")
    print(f"{'id':<5} {'ruta':<30} {'herramientas (MCP)':<50} {'misma':<6} {'ok'}")
    filas, iguales = [], 0
    for c in casos:
        nombre = operaciones.pasajero(c["pasajero_id"])["nombre"]
        r1 = resumen(local.invoke(entrada_orquestador(c["consulta"], c["pasajero_id"], nombre)))
        r2 = resumen(mcp.invoke(entrada_orquestador(c["consulta"], c["pasajero_id"], nombre)))
        misma = sorted(r1["herramientas"]) == sorted(r2["herramientas"]) and r1["parada"] == r2["parada"]
        iguales += misma
        ok = chequear(c, r2["herramientas"], r2["parada"], r2["respuesta"]).ok
        print(f"{c['id']:<5} {', '.join(r2['dominios']):<30} {', '.join(r2['herramientas']):<50} {marca(misma):<6} "
              f"{marca(ok)}")
        filas.append(f"| {c['id']} | {', '.join(r2['dominios'])} | {', '.join(r2['herramientas'])} | {marca(misma)} | "
                     f"{marca(ok)} |")
    llamadas = sum(len(cl.llamadas) for cl in sesiones.clientes.values())
    sesiones.cerrar()
    texto = (f"Misma trayectoria en {iguales}/{len(casos)} · {len(sesiones.clientes)} sesiones MCP (una por pasajero) "
             f"· {llamadas} llamadas al server")
    print(f"\n{texto}\n")
    return ["| id | ruta | herramientas (MCP) | misma | ok |", "|---|---|---|---|---|", *filas, "", texto]


def parte_b() -> list[str]:
    operaciones.reiniciar_db()
    AUDITORIA.unlink(missing_ok=True)
    sesiones = SesionesMCP("reembolsos")
    grafo = construir_orquestador(ConfigOrquestador(fabrica_worker=sesiones.fabrica),
                                  checkpointer=abrir_checkpointer("memoria"))
    cfg = {"configurable": {"thread_id": f"c4-{uuid.uuid4().hex[:6]}"}}
    print(f"── Parte B · «{CONSULTA_B}» · sesión MCP de rol 'reembolsos'\n")
    grafo.invoke(entrada_orquestador(CONSULTA_B, "P-1001", "Lucía Fernández"), cfg)
    pedido = next(t.interrupts[0].value for t in grafo.get_state(cfg).tasks if t.interrupts)
    print(f"   [host] pausa antes de llamar al server: {pedido['herramienta']} {json.dumps(pedido['argumentos'])}")
    escrituras = lambda: [a for a in map(json.loads, open(AUDITORIA, encoding="utf-8"))  # noqa: E731
                          if a["herramienta"] == "iniciar_reembolso"] if AUDITORIA.exists() else []
    print(f"   [server] llamadas a iniciar_reembolso auditadas hasta ahora: {len(escrituras())}")
    final = grafo.invoke(Command(resume={"decision": "aprobar"}), cfg)
    aud = escrituras()
    print("   [supervisor] aprueba → el host recién ahora llama al server")
    print(f"   [server] auditoría: {aud[-1]['pasajero']} ({aud[-1]['rol']}) · iniciar_reembolso "
          f"{aud[-1]['argumentos']} → {aud[-1]['resultado']}")
    res = operaciones.consultar_reserva("M4TR88", "P-1001")["reembolsos"]
    print("   base:", [f"{r['id']} USD {r['monto_usd']:.0f} {r['estado']}" for r in res])
    print(f"\n   → {final['respuesta'][:300]}")
    sesiones.cerrar()
    operaciones.reiniciar_db()
    return ["", f"Parte B: pausa en el host antes de llamar al server; aprobado → {aud[-1]['resultado']} "
                f"({len(aud)} escritura auditada)."]


def main():
    if MOCK:
        print("⚠ ORBITAIR_MOCK=1 → server MCP real, 'modelo' guionado.\n")
    operaciones.reiniciar_db()
    retrieval.indice()
    print(f"Modelo {MODELO}\n")
    lineas = ["## C4 · Ejercicio 4 · El worker de reembolsos sobre MCP", "",
              f"- Modelo {MODELO}{' (MOCK)' if MOCK else ''}", "", *parte_a(), *parte_b()]
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / "c4_orquestador_mcp.md").write_text("\n".join(lineas), encoding="utf-8")
    print("\n✓ Guardado results/c4_orquestador_mcp.md")


if __name__ == "__main__":
    main()
