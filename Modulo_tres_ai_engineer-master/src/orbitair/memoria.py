"""C1 · Memoria del agente: de corto plazo (la conversación) y de largo plazo (entre sesiones).

EJERCICIO 5 · Completar `recortar_historial()` y `extraer_hechos()`.

Un LLM no recuerda nada entre llamadas: la "memoria" es lo que el harness decide
volver a mandarle.

- CORTO PLAZO: el historial de la conversación (los mensajes de turnos anteriores,
  con sus tool_calls y observaciones). Permite "¿y por esa demora me dan algo?".
  Crece en cada turno, así que hay que recortarlo — y recortarlo mal rompe la API:
  un mensaje `tool` cuyo `assistant` con el tool_call quedó afuera es un 400.
  Se recorta por TURNOS completos, nunca por mensajes sueltos.

- LARGO PLAZO: hechos que sobreviven a la sesión (el pasajero vuelve mañana y
  pregunta "¿hay novedades de mi valija?"). No se guarda la conversación entera:
  se extraen hechos (qué valija, qué PIR, qué vuelo) y se inyectan en el system
  prompt de la sesión siguiente. Son PUNTEROS, no estado: "la valija OA-640212
  estaba demorada ayer" no dice cómo está hoy → el agente vuelve a consultar.

La extracción acá es determinista (de las observaciones de las herramientas, no del
texto del pasajero): barata, auditable y sin alucinaciones. La alternativa (pedirle
al LLM un resumen) captura más cosas — preferencias, contexto — pero cuesta tokens
y puede guardar algo que el pasajero nunca dijo.
"""
from __future__ import annotations

import json
from pathlib import Path

from .agente import Agente, Resultado
from .llm import contar_tokens
from .historial import observaciones

MEMORIA_DIR = Path(__file__).resolve().parents[2] / "results" / "memoria"


# ---------------------------------------------------------------------------
# EJERCICIO 5 · Corto plazo: recortar el historial por turnos
# ---------------------------------------------------------------------------
def turnos(mensajes: list[dict]) -> list[list[dict]]:
    """Agrupa el historial en turnos: cada turno empieza en un mensaje `user` e incluye todo lo que sigue."""
    grupos: list[list[dict]] = []
    for m in mensajes:
        if m["role"] == "user" or not grupos:
            grupos.append([])
        grupos[-1].append(m)
    return grupos


def recortar_historial(mensajes: list[dict], max_tokens: int) -> list[dict]:
    """Descarta los turnos MÁS VIEJOS hasta que el historial entre en `max_tokens` (usar `contar_tokens`).

    - Se descartan turnos completos (ver `turnos()`), así nunca queda un `tool` sin su `assistant`.
    - El último turno se conserva siempre, aunque solo ya supere el límite.
    """
    grupos = turnos(mensajes)
    while len(grupos) > 1 and contar_tokens([m for g in grupos for m in g]) > max_tokens:
        grupos.pop(0)
    return [m for g in grupos for m in g]


def recortar_ingenuo(mensajes: list[dict], max_mensajes: int) -> list[dict]:
    """El recorte "obvio": quedarse con los últimos N mensajes. Puede dejar un `tool` huérfano (→ 400)."""
    return mensajes[-max_mensajes:]


class Sesion:
    """Una conversación de varios turnos con el agente de C1: el historial es la memoria de corto plazo."""

    def __init__(self, agente: Agente, max_tokens_historial: int | None = None, recorte: str = "turnos",
                 max_mensajes: int = 6):
        self.agente = agente
        self.historial: list[dict] = []
        self.max_tokens = max_tokens_historial
        self.recorte = recorte
        self.max_mensajes = max_mensajes

    def preguntar(self, texto: str) -> Resultado:
        historial = self.historial
        if self.recorte == "ingenuo":
            historial = recortar_ingenuo(historial, self.max_mensajes)
        elif self.max_tokens:
            historial = recortar_historial(historial, self.max_tokens)
        r = self.agente.correr(texto, historial)
        self.historial = r.mensajes          # el historial (recortado) + este turno
        return r


# ---------------------------------------------------------------------------
# EJERCICIO 5 · Largo plazo: hechos que sobreviven a la sesión
# ---------------------------------------------------------------------------
def extraer_hechos(mensajes: list[dict]) -> dict[str, dict]:
    """Hechos de las observaciones EXITOSAS de la sesión, por clave → datos. Si un objeto se consultó
    varias veces, gana la última observación.

    - rastrear_valija encontrada   → "valija:<codigo>":  {codigo, vuelo, estado, pir, actualizado}
    - consultar_vuelo encontrado   → "vuelo:<codigo>":   {codigo, fecha, estado, demora_min}
    - consultar_reserva encontrada → "reserva:<codigo>": {codigo, vuelos: [códigos]}
    - iniciar_reembolso creado     → "reembolso:<id>":   {id, reserva, estado, monto_usd}
    Usar `observaciones(mensajes)` (cada una con .nombre, .args, .contenido, .error).
    """
    hechos: dict[str, dict] = {}
    for o in observaciones(mensajes):
        c = o.contenido
        if o.error:
            continue
        if o.nombre == "rastrear_valija" and c.get("encontrada"):
            hechos[f"valija:{c['codigo']}"] = {k: c[k] for k in ("codigo", "vuelo", "estado", "pir", "actualizado")}
        elif o.nombre == "consultar_vuelo" and c.get("encontrado"):
            hechos[f"vuelo:{c['codigo']}"] = {k: c[k] for k in ("codigo", "fecha", "estado", "demora_min")}
        elif o.nombre == "consultar_reserva" and c.get("encontrada"):
            hechos[f"reserva:{c['codigo']}"] = {"codigo": c["codigo"], "vuelos": [v["codigo"] for v in c["vuelos"]]}
        elif o.nombre == "iniciar_reembolso" and c.get("creado"):
            hechos[f"reembolso:{c['id']}"] = {k: c[k] for k in ("id", "reserva", "estado", "monto_usd")}
    return hechos


class MemoriaLargoPlazo:
    """Un JSON por pasajero en results/memoria/. En producción: una tabla, con vencimiento y consentimiento."""

    def __init__(self, directorio: Path = MEMORIA_DIR):
        self.dir = directorio

    def _path(self, pasajero_id: str) -> Path:
        return self.dir / f"{pasajero_id}.json"

    def leer(self, pasajero_id: str) -> dict[str, dict]:
        p = self._path(pasajero_id)
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}

    def guardar(self, pasajero_id: str, mensajes: list[dict]) -> dict[str, dict]:
        hechos = {**self.leer(pasajero_id), **extraer_hechos(mensajes)}
        self.dir.mkdir(parents=True, exist_ok=True)
        self._path(pasajero_id).write_text(json.dumps(hechos, ensure_ascii=False, indent=2), encoding="utf-8")
        return hechos

    def olvidar(self, pasajero_id: str) -> None:
        self._path(pasajero_id).unlink(missing_ok=True)

    def contexto(self, pasajero_id: str) -> str:
        """El bloque que se agrega al system prompt de la sesión siguiente ("" si no hay nada)."""
        hechos = self.leer(pasajero_id)
        if not hechos:
            return ""
        lineas = []
        for clave, h in hechos.items():
            tipo = clave.split(":")[0]
            if tipo == "valija":
                lineas.append(f"- valija {h['codigo']} (vuelo {h['vuelo']}{', PIR ' + h['pir'] if h['pir'] else ''}): "
                              f"{h['estado']}, al {h['actualizado']}")
            elif tipo == "vuelo":
                lineas.append(f"- vuelo {h['codigo']} del {h['fecha']}: {h['estado']}")
            elif tipo == "reserva":
                lineas.append(f"- reserva {h['codigo']}: vuelos {', '.join(h['vuelos'])}")
            elif tipo == "reembolso":
                lineas.append(f"- reembolso {h['id']} de la reserva {h['reserva']}: {h['estado']}")
        return ("Memoria de sesiones anteriores con este pasajero (puede estar desactualizada: volvé a consultar "
                "antes de afirmar un estado):\n" + "\n".join(lineas))
