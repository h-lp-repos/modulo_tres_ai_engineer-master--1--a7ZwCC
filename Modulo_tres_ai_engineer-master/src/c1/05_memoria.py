"""C1 · Ejercicio 5 · Memoria de corto plazo (la conversación) y de largo plazo (entre sesiones).

Parte A · Corto plazo. Una conversación de 3 turnos con la pasajera P-1001:
  T1 "Estoy en Ezeiza, el OA0417 está demorado hace horas. ¿Me tienen que dar algo para comer?"
  T2 "¿Y a qué hora sale ahora ese vuelo?"                          ← "ese vuelo": ¿cuál?
  T3 "Gracias. Otra cosa: ¿dónde está mi valija OA-582331?"
  - sin historial: cada turno es una conversación nueva (T2 no sabe de qué vuelo se habla)
  - con historial completo: funciona, pero los tokens de entrada crecen turno a turno
  - recorte ingenuo (últimos 4 mensajes): deja un mensaje `tool` huérfano → la API lo rechaza (400)
  - recorte por turnos (orbitair/memoria.py · recortar_historial): entra en el presupuesto y no rompe

Parte B · Largo plazo. Sesión 1: "Mi valija OA-640212 no llegó a São Paulo, ¿qué pasó?".
Se extraen hechos de las observaciones y se guardan. Sesión 2, otro día: "Hola, ¿hay
novedades de mi valija?" — sin memoria vs con memoria.

Uso:
  python src/c1/05_memoria.py
  python src/c1/05_memoria.py --parte A
  python src/c1/05_memoria.py --parte B
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))
from orbitair.agente import Agente  # noqa: E402
from orbitair.llm import MOCK, MODELO, ErrorDeAPI  # noqa: E402
from orbitair.memoria import MemoriaLargoPlazo, Sesion, turnos  # noqa: E402
from orbitair.operaciones import reiniciar_db  # noqa: E402
from orbitair.pricing import fmt_usd  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")
PASAJERO, NOMBRE = "P-1001", "Lucía Fernández"
TURNOS = ["Estoy en Ezeiza, el OA0417 está demorado hace horas. ¿Me tienen que dar algo para comer?",
          "¿Y a qué hora sale ahora ese vuelo?",
          "Gracias. Otra cosa: ¿dónde está mi valija OA-582331?"]


def arg(flag: str, default=None):
    return sys.argv[sys.argv.index(flag) + 1] if flag in sys.argv else default


def conversar(titulo: str, sesion_por_turno, nota: str = "") -> None:
    print(f"── {titulo}")
    sesion = None
    for i, texto in enumerate(TURNOS, 1):
        sesion = sesion_por_turno(sesion)
        try:
            r = sesion.preguntar(texto)
        except ErrorDeAPI as e:
            print(f"   T{i} ✗ la API rechazó el pedido: {e}")
            print(f"      historial enviado: {[m['role'] for m in getattr(sesion, '_enviado', [])] or '—'}\n")
            return
        except Exception as e:  # noqa: BLE001 — en modo real, openai.BadRequestError
            if type(e).__name__ != "BadRequestError":
                raise
            print(f"   T{i} ✗ la API rechazó el pedido (400): {str(e)[:160]}\n")
            return
        primer = r.pasos[0].llm if r.pasos else r.cierre
        print(f"   T{i} {texto}")
        print(f"      herramientas {r.herramientas or '—'} · tokens de entrada de la 1ª llamada: {primer.tokens_in:,} · "
              f"turnos en el historial enviado: {len(turnos(r.mensajes)) - 1} · {fmt_usd(r.costo_usd)}")
        print(f"      → {r.respuesta[:170]}{'…' if len(r.respuesta) > 170 else ''}")
    if nota:
        print(f"   {nota}")
    print()


class SesionEspia(Sesion):
    """Igual que Sesion, pero guarda los roles de lo que mandó (para mostrar el historial roto)."""

    def preguntar(self, texto):
        from orbitair.memoria import recortar_ingenuo
        self._enviado = recortar_ingenuo(self.historial, self.max_mensajes) if self.recorte == "ingenuo" \
            else self.historial
        return super().preguntar(texto)


def parte_a() -> None:
    print("PARTE A · Memoria de corto plazo\n")
    agente = Agente(PASAJERO, NOMBRE)
    conversar("1 · sin historial (cada turno arranca de cero)", lambda s: Sesion(agente))
    conversar("2 · historial completo", lambda s: s or Sesion(agente),
              "Funciona, pero cada turno reenvía todos los anteriores: los tokens de entrada sólo crecen.")
    conversar("3 · recorte ingenuo: últimos 4 mensajes", lambda s: s or SesionEspia(agente, recorte="ingenuo",
                                                                                    max_mensajes=4))
    conversar("4 · recorte por turnos: historial ≤ 800 tokens", lambda s: s or Sesion(agente, 800),
              "Entra en el presupuesto descartando turnos viejos completos. El precio: lo descartado se olvida "
              "(para eso: resumir turnos viejos, o memoria de largo plazo).")


def parte_b() -> None:
    print("PARTE B · Memoria de largo plazo\n")
    memoria = MemoriaLargoPlazo()
    memoria.olvidar(PASAJERO)
    s1 = "Mi valija OA-640212 no llegó a São Paulo, ¿qué pasó?"
    r = Agente(PASAJERO, NOMBRE).correr(s1)
    print(f"── Sesión 1 · {s1}\n   herramientas {r.herramientas} → {r.respuesta}\n")
    hechos = memoria.guardar(PASAJERO, r.mensajes)
    print(f"   Hechos guardados en results/memoria/{PASAJERO}.json:")
    print("   " + json.dumps(hechos, ensure_ascii=False, indent=2).replace("\n", "\n   "))
    bloque = memoria.contexto(PASAJERO)
    print("\n   Bloque que se agrega al system prompt de la próxima sesión:\n   " + bloque.replace("\n", "\n   ") + "\n")

    s2 = "Hola, ¿hay novedades de mi valija?"
    for titulo, mem in (("sin memoria de largo plazo", ""), ("con memoria de largo plazo", bloque)):
        r = Agente(PASAJERO, NOMBRE, memoria=mem).correr(s2)
        print(f"── Sesión 2 ({titulo}) · {s2}\n   herramientas {r.herramientas or '—'} · {len(r.pasos)} pasos → "
              f"{r.respuesta}\n")
    print("   Con memoria, el agente sabe QUÉ valija es, pero igual la vuelve a consultar: la memoria guarda "
          "punteros, no el estado de hoy.")


def main():
    if MOCK:
        print("⚠ ORBITAIR_MOCK=1 → el 'modelo' es un guion: resuelve referencias ('esa demora', 'mi valija') con "
              "reglas.\n")
    print(f"Modelo {MODELO} · pasajera {PASAJERO} ({NOMBRE})\n")
    reiniciar_db()
    parte = arg("--parte")
    if parte in (None, "A"):
        parte_a()
    if parte in (None, "B"):
        parte_b()


if __name__ == "__main__":
    main()
