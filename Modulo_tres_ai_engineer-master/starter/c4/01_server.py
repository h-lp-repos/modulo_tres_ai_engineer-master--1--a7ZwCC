"""C4 · Ejercicio 1 · El server MCP de OrbitAir: tools, resources y prompts, vistos desde un cliente.

Lanza el server (orbitair/mcp_server.py) como proceso, con la sesión de una pasajera, y
recorre el protocolo como lo haría cualquier host:

  initialize      → qué server es y qué ofrece
  tools/list      → nombre, descripción, inputSchema y outputSchema (¡armados desde los type hints!) y annotations
  tools/call      → consultar_vuelo
  resources/list  → estáticos y plantillas (politica://{codigo})
  resources/read  → un documento de política y el pasajero de la sesión
  prompts/list    → plantillas que elige el USUARIO
  prompts/get     → el mensaje que el host le manda al modelo

Para explorarlo a mano con una UI: MCP Inspector (requiere Node). Ver GUIA_C4.md.

Uso:
  python src/c4/01_server.py
  python src/c4/01_server.py --schema          # el inputSchema y el outputSchema de cada tool

Guarda results/c4_server.md.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))
from orbitair.mcp_cliente import ClienteMCP  # noqa: E402
from orbitair.operaciones import reiniciar_db  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")
RESULTS = Path(__file__).resolve().parents[2] / "results"
PASAJERO = "P-1001"


def main():
    reiniciar_db()
    lineas = ["## C4 · Ejercicio 1 · El server MCP de OrbitAir", ""]
    with ClienteMCP(PASAJERO, rol="consulta") as c:
        print(f"── initialize: server lanzado con la sesión {PASAJERO} · rol 'consulta' · {c.conexion_s:.2f} s "
              f"(arrancar el proceso + handshake)\n")

        print("── tools/list (lo que el modelo va a ver)")
        lineas += ["| tool | solo lectura | argumentos | descripción |", "|---|---|---|---|"]
        for h in c.herramientas.values():
            args = ", ".join(f"{k}{'' if k in h.schema.get('required', []) else '?'}: "
                             f"{v.get('type') or '|'.join(x.get('type', '?') for x in v.get('anyOf', []))}"
                             for k, v in h.schema["properties"].items())
            print(f"  {h.nombre}({args})   readOnlyHint={h.solo_lectura} · salida estructurada: "
                  f"{'sí (' + str(len(h.salida.get('properties', {}))) + ' campos)' if h.salida else 'no'}")
            print(f"      {h.descripcion[:140]}{'…' if len(h.descripcion) > 140 else ''}")
            if "--schema" in sys.argv:
                print("      inputSchema:  " + json.dumps(h.schema, ensure_ascii=False))
                print("      outputSchema: " + json.dumps(h.salida, ensure_ascii=False))
            lineas.append(f"| {h.nombre} | {h.solo_lectura} | {args} | {h.descripcion[:90]}… |")
        if "iniciar_reembolso" in c.herramientas:
            print("  ⚠ iniciar_reembolso aparece en una sesión de SÓLO CONSULTA: falta el Ejercicio 3 (permisos por rol)\n")
        else:
            print("  (iniciar_reembolso no aparece: el rol 'consulta' no la tiene → Ejercicio 3)\n")

        print("── tools/call consultar_vuelo {\"codigo_vuelo\": \"oa 1203\"}")
        r = c.llamar("consultar_vuelo", {"codigo_vuelo": "oa 1203"})
        print(f"  → {json.dumps(r, ensure_ascii=False)}   ({c.llamadas[-1][1] * 1000:.0f} ms)\n")

        print("── resources/list")
        recursos = c.recursos()
        for uri in recursos:
            print(f"  {uri}")
        print("\n── resources/read politica://POL-RE-01 (primeras líneas)")
        print("  " + "\n  ".join(c.leer_recurso("politica://POL-RE-01").splitlines()[:5]))
        print(f"\n── resources/read pasajero://sesion\n  {c.leer_recurso('pasajero://sesion')}\n")

        print("── prompts/list y prompts/get reclamo_equipaje {\"pir\": \"GRU-20552\"}")
        prompts = c.prompts()
        print(f"  {prompts}")
        for m in c.prompt("reclamo_equipaje", {"pir": "GRU-20552"}):
            print(f"  [{m['role']}] {m['content']}")

    lineas += ["", f"Resources: {', '.join(recursos)}", "", f"Prompts: {', '.join(prompts)}"]
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / "c4_server.md").write_text("\n".join(lineas), encoding="utf-8")
    print("\n✓ Guardado results/c4_server.md")


if __name__ == "__main__":
    main()
