"""C1 · Ejercicio 1 · Anatomía de una llamada con herramientas, desarmada a mano (todavía sin loop).

Una vuelta del agente, paso a paso:
  1. qué herramientas ve el modelo (la especificación: nombre, descripción, JSON Schema)
  2. el modelo PROPONE una llamada (tool_call) — no ejecuta nada
  3. nuestro código valida y ejecuta (ejecutar_tool) y arma la observación (mensaje `tool`)
  4. segunda llamada al modelo con la observación → respuesta... o pide OTRA herramienta

Corre tres consultas: una que necesita una herramienta (A-01), una que no necesita
ninguna (A-06) y una que necesita dos (A-02: después de la primera vuelta el modelo
pide otra herramienta → hace falta un loop, Ejercicio 2). Cierra con el punto de
control: qué pasa si el modelo intenta pasar un `pasajero_id`.

Uso:
  python src/c1/01_una_tool.py
  python src/c1/01_una_tool.py --id A-02 --crudo        # los mensajes tal cual van a la API
  python src/c1/01_una_tool.py --consulta "¿Cómo viene el OA0218?"
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))
from orbitair.agente import SISTEMA  # noqa: E402
from orbitair.data import load_consultas_c1  # noqa: E402
from orbitair.errores import ErrorDeEntrada, ErrorDuro  # noqa: E402
from orbitair.llm import MOCK, MODELO, completar_con_tools, mensaje_tool  # noqa: E402
from orbitair.pricing import fmt_usd  # noqa: E402
from orbitair.tools import Contexto, ejecutar_tool, specs  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")


def arg(flag: str, default=None):
    return sys.argv[sys.argv.index(flag) + 1] if flag in sys.argv else default


def una_vuelta(consulta: str, pasajero_id: str, crudo: bool) -> None:
    tools = specs()
    ctx = Contexto(pasajero_id)
    mensajes = [{"role": "system", "content": SISTEMA.format(pasajero_id=pasajero_id, nombre="pasajero")},
                {"role": "user", "content": consulta}]
    print(f"Pasajero {pasajero_id}: {consulta}\n")

    r1 = completar_con_tools(mensajes, tools)
    print(f"① LLM ({r1.tokens_in}+{r1.tokens_out} tokens, {r1.latencia_s:.2f} s, {fmt_usd(r1.costo_usd)})")
    if crudo:
        print("   mensaje assistant:", json.dumps(r1.mensaje, ensure_ascii=False, indent=2).replace("\n", "\n   "))
    if not r1.tool_calls:
        print(f"   → respondió SIN herramientas: {r1.texto}\n")
        return
    if r1.texto:
        print(f"   pensamiento: {r1.texto}")
    mensajes.append(r1.mensaje)
    for tc in r1.tool_calls:
        print(f"   → propone: {tc.nombre}({tc.argumentos_raw})   [id {tc.id}]")
        try:
            obs = ejecutar_tool(tc.nombre, tc.argumentos, ctx)
        except (ErrorDeEntrada, ErrorDuro) as e:      # el triage completo es el Ejercicio 4
            obs = {"error": str(e)}
        texto_obs = json.dumps(obs, ensure_ascii=False)
        print(f"② ejecutamos nosotros → observación: {texto_obs[:160]}{'…' if len(texto_obs) > 160 else ''}")
        mensajes.append(mensaje_tool(tc.id, obs))

    r2 = completar_con_tools(mensajes, tools)
    print(f"③ LLM con la observación ({r2.tokens_in}+{r2.tokens_out} tokens, {fmt_usd(r2.costo_usd)})")
    if r2.tool_calls:
        pedidas = ", ".join(f"{tc.nombre}({tc.argumentos_raw})" for tc in r2.tool_calls)
        print(f"   → pide OTRA herramienta: {pedidas}")
        print("   Con una sola vuelta no alcanza: hace falta un LOOP que repita ①-③ hasta que responda (Ej. 2).\n")
    else:
        print(f"   → respuesta: {r2.texto}\n")
    print(f"   Total: {r1.tokens_in + r2.tokens_in} tokens de entrada — el historial se reenvía completo en cada "
          f"llamada.\n")


def punto_de_control() -> None:
    print("─" * 100)
    print("Punto de control · ¿qué pasa si el modelo (o un prompt injection) intenta elegir el pasajero?\n")
    ctx = Contexto("P-1001")
    for nombre, argumentos in [("consultar_reserva", {"codigo_reserva": "K7PQ2M", "pasajero_id": "P-2002"}),
                               ("consultar_reserva", {"codigo_reserva": "K7PQ2M"}),
                               ("borrar_reserva", {"codigo_reserva": "M4TR88"})]:
        try:
            ejecutar_tool(nombre, argumentos, ctx)
            print(f"   {nombre}({argumentos}) → se ejecutó (¡no debería!)")
        except Exception as e:  # noqa: BLE001
            print(f"   {nombre}({json.dumps(argumentos)})\n      → {type(e).__name__}: {e}")
    print("\n   El pasajero sale de la sesión (Contexto), no de los argumentos que propone el modelo.")


def main():
    if MOCK:
        print("⚠ ORBITAIR_MOCK=1 → el 'modelo' es un guion determinista (orbitair/mock_agente.py), no un LLM.\n")
    print(f"Modelo: {MODELO} · herramientas: " + ", ".join(t["function"]["name"] for t in specs()))
    spec = specs(["consultar_vuelo"])[0]["function"]
    print(f"Lo que el modelo ve de consultar_vuelo:\n   {json.dumps(spec, ensure_ascii=False)}\n")
    print("─" * 100)
    casos = {c["id"]: c for c in load_consultas_c1()}
    if arg("--consulta"):
        una_vuelta(arg("--consulta"), arg("--pasajero", "P-1001"), "--crudo" in sys.argv)
        return
    ids = [arg("--id")] if arg("--id") else ["A-01", "A-06", "A-02"]
    for i in ids:
        print(f"{i} · {casos[i]['tipo']}")
        una_vuelta(casos[i]["consulta"], casos[i]["pasajero_id"], "--crudo" in sys.argv)
    if not arg("--id"):
        punto_de_control()


if __name__ == "__main__":
    main()
