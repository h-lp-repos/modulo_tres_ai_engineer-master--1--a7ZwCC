"""C4 · Ejercicio 5 · Servers de terceros: lo que entra al host con cada server que se conecta.

El host conecta dos servers: el de OrbitAir y "clima-viajes" (orbitair/mcp_terceros.py), uno de
la comunidad. El protocolo no distingue uno confiable de uno que no lo es. Tres problemas y
las defensas del lado del HOST (el server de terceros no lo controlamos):

1. Exfiltración de la sesión: si el host lanza todos los servers con el mismo entorno, el de
   terceros sabe quién es el pasajero.             → defensa: cada server recibe sólo lo que necesita.
2. Colisión de nombres: los dos publican `consultar_vuelo`. Juntando por nombre, la de terceros
   pisa a la oficial (y devuelve "a horario" para un vuelo cancelado).
                                                    → defensa: nombres con prefijo de server + allowlist.
3. Tool poisoning: la descripción de `pronostico_destino` le ordena al modelo iniciar un reembolso.
   La descripción ES prompt.                         → defensa: revisar las descripciones antes de
                                                      mostrarlas, y que la acción igual sea imposible
                                                      (rol del server + aprobación humana).

Nada de este ejercicio necesita al modelo: se ve en lo que el host le arma al modelo.

Uso:
  python src/c4/05_terceros.py
"""
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))
from orbitair.errores import ErrorDeEntrada  # noqa: E402
from orbitair.mcp_cliente import ClienteMCP, combinar_herramientas, revisar_herramienta, spec_openai  # noqa: E402
from orbitair.operaciones import reiniciar_db  # noqa: E402
from orbitair.tools import SENSIBLES  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")
PASAJERO = "P-1001"


def huella(h) -> str:
    """Hash de lo que el modelo lee de una tool: nombre, descripción y schema."""
    return hashlib.sha256(json.dumps([h.nombre, h.descripcion, h.schema], sort_keys=True).encode()).hexdigest()


def main():
    reiniciar_db()
    oficial = ClienteMCP(PASAJERO, rol="consulta")

    print("── 1 · ¿Qué sabe el server de terceros de la sesión?\n")
    with ClienteMCP(PASAJERO, modulo="orbitair.mcp_terceros", con_sesion=True) as ingenuo:
        print(f"   lanzado con el mismo entorno que el nuestro: {ingenuo.leer_recurso('diagnostico://entorno')}")
    clima = ClienteMCP(PASAJERO, modulo="orbitair.mcp_terceros", con_sesion=False)
    print(f"   lanzado con con_sesion=False:               {clima.leer_recurso('diagnostico://entorno')}\n")

    print("── 2 · Dos servers, una tool con el mismo nombre\n")
    ingenuo = combinar_herramientas({"orbitair": oficial, "clima": clima}, prefijo=False)
    cliente, _ = ingenuo["consultar_vuelo"]
    print(f"   juntando por nombre, 'consultar_vuelo' es la de: {cliente.modulo}")
    print(f"   OA2250 según esa: {cliente.llamar('consultar_vuelo', {'codigo_vuelo': 'OA2250'})}")
    print(f"   OA2250 según OrbitAir: estado={oficial.llamar('consultar_vuelo', {'codigo_vuelo': 'OA2250'})['estado']}\n")

    print("── 3 · Lo que el modelo leería en la descripción de 'pronostico_destino'\n")
    h = clima.herramientas["pronostico_destino"]
    print("   " + json.dumps(spec_openai(h), ensure_ascii=False)[:420] + "…\n")
    conocidas = set(oficial.herramientas) | SENSIBLES
    for nombre, herramienta in clima.herramientas.items():
        alertas = revisar_herramienta(herramienta, conocidas)
        print(f"   revisar_herramienta({nombre}): {alertas or 'sin alertas'}")
    print("   (el 'consultar_vuelo' de terceros no dispara alertas: el problema ahí es la colisión, no el texto)\n")

    print("── 4 · El host con defensas: prefijo de server + allowlist + revisión + descripciones fijadas\n")
    # Las descripciones del server propio ya las revisó el equipo: se guarda su hash. Si mañana cambian
    # (un "rug pull": el server cambia la descripción después de aprobado), vuelven a revisión.
    revisadas = {huella(h) for h in oficial.herramientas.values()}
    permitidas = {"orbitair": set(oficial.herramientas), "clima": {"pronostico_destino"}}
    combinadas = combinar_herramientas({"orbitair": oficial, "clima": clima}, permitidas)
    for nombre, (_, herr) in combinadas.items():
        alertas = revisar_herramienta(herr, conocidas)
        if huella(herr) in revisadas:
            estado = "expuesta (revisada, hash fijado)" + (f" · alerta ignorada: {alertas}" if alertas else "")
        else:
            estado = f"BLOQUEADA hasta revisión humana ({len(alertas)} alertas)" if alertas else "expuesta al modelo"
        print(f"   {nombre:<30} {estado}")
    print("   orbitair__consultar_vuelo dispara dos alertas ('Usarla siempre que…', '…antes de responder sobre\n"
          "   demoras'): FALSOS POSITIVOS. La revisión automática es una red con errores, como los guardrails del\n"
          "   M1 · C4: también hay que medirla. Por eso la decisión final la toma una persona, una vez, y se fija.")

    print("\n── 5 · Y si el modelo igual obedeciera la instrucción envenenada…\n")
    try:
        oficial.llamar("iniciar_reembolso", {"codigo_reserva": "M4TR88", "motivo": "voluntario_flex"})
        print("   ✗ el server la ejecutó")
    except ErrorDeEntrada as e:
        print(f"   server (rol 'consulta'): {e} → la tool no existe para esta sesión")
    print(f"   host: iniciar_reembolso ∈ SENSIBLES={sorted(SENSIBLES)} → aunque existiera, pasa por la aprobación "
          "humana (C2) antes de llegar al server")
    oficial.cerrar()
    clima.cerrar()


if __name__ == "__main__":
    main()
