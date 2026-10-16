"""C4 · Ejercicio 2 · El agente como cliente MCP: mismas herramientas, ahora en otro proceso.

Parte A · Mismo comportamiento. Las consultas de un dominio del dataset de C3, cada una con su
worker de C3 (herramientas locales) y con el mismo worker sobre MCP (las herramientas de datos
vienen del server). Como en C2: el cambio es de INFRAESTRUCTURA, la trayectoria tiene que ser
la misma. Se mide cuánto agrega el protocolo por llamada.

Parte B · El triage a través del protocolo. El server tiene fallas inyectadas (2 timeouts en el
sistema de valijas) y una reserva ajena: los errores llegan tipados ([transitorio],
[permisos]) y el triage de C1 decide igual que con las herramientas locales.

Uso:
  python src/c4/02_cliente.py
  python src/c4/02_cliente.py --parte B

Guarda results/c4_cliente.md.
"""
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))
from orbitair import retrieval  # noqa: E402
from orbitair.data import load_consultas_c3  # noqa: E402
from orbitair.grafo import construir_grafo, entrada_turno  # noqa: E402
from orbitair.historial import observaciones  # noqa: E402
from orbitair.llm import MOCK, MODELO  # noqa: E402
from orbitair.mcp_cliente import AgenteConMCP, ClienteMCP, config_worker_mcp  # noqa: E402
from orbitair.operaciones import pasajero, reiniciar_db  # noqa: E402
from orbitair.trayectoria import chequear, marca  # noqa: E402
from orbitair.workers import config_worker  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")
RESULTS = Path(__file__).resolve().parents[2] / "results"


def arg(flag: str, default=None):
    return sys.argv[sys.argv.index(flag) + 1] if flag in sys.argv else default


def correr(cfg, caso: dict) -> dict:
    nombre = pasajero(caso["pasajero_id"])["nombre"]
    s = construir_grafo(cfg).invoke(entrada_turno(caso["consulta"], caso["pasajero_id"], nombre))
    return {**s, "herramientas": [o.nombre for o in observaciones(s["mensajes"])]}


def parte_a() -> list[str]:
    casos = [c for c in load_consultas_c3() if c["tipo"] == "un_dominio"]
    clientes = {p: ClienteMCP(p, rol="consulta") for p in sorted({c["pasajero_id"] for c in casos})}
    print(f"── Parte A · {len(casos)} consultas · worker de C3 (local) vs el mismo worker sobre MCP · {MODELO}\n")
    print(f"   sesiones MCP: {', '.join(f'{p} ({c.conexion_s:.2f} s)' for p, c in clientes.items())}\n")
    print(f"{'id':<5} {'worker':<11} {'herramientas local → MCP':<52} {'parada':<10} {'misma':<6} {'MCP ok'}")
    filas, iguales = [], 0
    for c in casos:
        d = c["dominios"][0]
        local = correr(config_worker(d), c)
        remoto = correr(config_worker_mcp(d, clientes[c["pasajero_id"]]), c)
        misma = local["herramientas"] == remoto["herramientas"] and local["parada"] == remoto["parada"]
        iguales += misma
        ok = chequear(c, remoto["herramientas"], remoto["parada"], remoto["respuesta"]).ok
        h = f"{', '.join(local['herramientas']) or '—'} → {'=' if misma else ', '.join(remoto['herramientas'])}"
        print(f"{c['id']:<5} {d:<11} {h:<52} {remoto['parada']:<10} {marca(misma):<6} {marca(ok)}")
        filas.append(f"| {c['id']} | {d} | {', '.join(local['herramientas']) or '—'} | "
                     f"{', '.join(remoto['herramientas']) or '—'} | {marca(misma)} | {marca(ok)} |")
    tiempos = [t for cl in clientes.values() for _, t in cl.llamadas]
    for cl in clientes.values():
        cl.cerrar()
    resumen = (f"Misma trayectoria en {iguales}/{len(casos)} · {len(tiempos)} llamadas tools/call, "
               f"{statistics.median(tiempos) * 1000:.0f} ms de mediana (proceso local por stdio; por HTTP se suma la red)")
    print(f"\n{resumen}\n")
    return ["| id | worker | local | MCP | misma | ok |", "|---|---|---|---|---|---|", *filas, "", resumen]


def parte_b() -> list[str]:
    print("── Parte B · el triage de C1, a través del protocolo\n")
    lineas = []
    fallas = {"rastrear_valija": ["timeout", "timeout"]}
    with ClienteMCP("P-1001", rol="consulta", fallas=fallas) as cliente:
        for consulta, nota in [("¿Llegó mi valija OA-310877?", "2 timeouts inyectados en el server"),
                               ("Quiero ver los datos de la reserva K7PQ2M", "reserva de otra pasajera")]:
            ag = AgenteConMCP("P-1001", "Lucía Fernández", cliente=cliente, dominio="equipaje",
                              herramientas=["rastrear_valija", "consultar_reserva", "buscar_politica"])
            r = ag.correr(consulta)
            print(f"  «{consulta}» ({nota})")
            for p in r.pasos:
                for a in p.acciones:
                    for i in a.resultado.intentos:
                        print(f"     intento {i.numero}: {i.error or 'ok'}"
                              + (f" → el cliente reintenta en {i.espera_s:.1f} s" if i.espera_s else ""))
                    print(f"     decisión del triage: {a.resultado.decision or 'ninguna (salió bien)'} · "
                          f"lo que ve el modelo: {str(a.resultado.contenido)[:90]}")
            print(f"     parada={r.parada} → {r.respuesta[:120]}\n")
            lineas.append(f"| {consulta} | {nota} | {r.parada} |")
    return ["| consulta | escenario | parada |", "|---|---|---|", *lineas]


def main():
    if MOCK:
        print("⚠ ORBITAIR_MOCK=1 → el server es real (otro proceso, protocolo MCP); el 'modelo' es el guion.\n")
    reiniciar_db()
    retrieval.indice()
    lineas = ["## C4 · Ejercicio 2 · El agente como cliente MCP", "", f"- Modelo {MODELO}{' (MOCK)' if MOCK else ''}", ""]
    if arg("--parte", "AB") in ("A", "AB"):
        lineas += parte_a()
    if arg("--parte", "AB") in ("B", "AB"):
        lineas += ["", *parte_b()]
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / "c4_cliente.md").write_text("\n".join(lineas), encoding="utf-8")
    print("✓ Guardado results/c4_cliente.md")


if __name__ == "__main__":
    main()
