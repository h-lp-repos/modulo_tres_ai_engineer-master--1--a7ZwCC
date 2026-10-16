"""C1 · El agente de OrbitAir escrito a mano: loop ReAct, stopping rules y triage de errores.

EJERCICIO 2 · Completar `Agente.correr()` (el loop).
EJERCICIO 3 · Completar `ReglasDeParada.evaluar()` (las stopping rules).

Un agente es un LLM en un loop que puede actuar:

    mensajes = [system, pregunta]
    repetir:
        ¿alguna stopping rule dice que paremos?  → cerrar con lo que hay
        respuesta = LLM(mensajes, herramientas)                     ← razonar (Re)
        si no pidió herramientas                 → es la respuesta final
        por cada tool_call: ejecutar con triage                     ← actuar (Act)
        agregar las observaciones a los mensajes                    ← observar
        si hubo un error duro                    → cortar y derivar

El loop en sí es corto. Lo que lo hace confiable está en sus bordes:
cuándo parar (stopping rules), qué hacer cuando una herramienta falla (triage) y
qué recordar (memoria, orbitair/memoria.py). En C2 este mismo loop se migra a
LangGraph sin cambiar su comportamiento.

Hay tres formas de terminar, y cada una queda registrada en `Resultado.parada`:
- "respuesta": el modelo respondió sin pedir herramientas (parada natural).
- una stopping rule ("max_pasos", "repetida", "presupuesto", "tiempo"): el harness
  corta y pide una última respuesta SIN herramientas, con lo que se sabe hasta ahí.
- "error_duro": una herramienta falló de forma no recuperable → mensaje fijo de
  derivación a un humano (no se le pide nada más al modelo).
"""
from __future__ import annotations

import time
from collections import Counter
from dataclasses import dataclass, field

from .errores import ResultadoTool, ejecutar_con_triage
from .llm import RespuestaLLM, ToolCall, completar_con_tools, mensaje_tool
from .operaciones import HOY
from .tools import HERRAMIENTAS_C1, Contexto, ejecutar_tool, specs

# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------
SISTEMA = f"""Sos el agente de atención al pasajero de la aerolínea OrbitAir. Hoy es {HOY}.
Atendés al pasajero {{pasajero_id}} ({{nombre}}).

Cómo trabajás:
- Para datos de vuelos, valijas o reservas, usá las herramientas: nunca inventes un estado, un horario ni un monto.
- Para reglas, derechos, plazos o montos de la política, usá buscar_politica y citá el id del fragmento entre
  corchetes, ej. [POL-RE-01#8.1].
- Antes de cada llamada a una herramienta, escribí en una línea qué vas a hacer y por qué.
- Si falta un dato para usar una herramienta (ej. el código de vuelo), pedíselo al pasajero en lugar de suponerlo.
- Si el estado de algo todavía no es final, informá el último estado, cuándo se actualizó y qué sigue.
  No repitas una consulta que ya hiciste con los mismos datos: el resultado no va a cambiar en esta conversación.
- Si la consulta no es sobre OrbitAir, decilo amablemente y no uses herramientas.
- Español, cordial y breve: 2 a 5 oraciones."""

# C1 · Ejercicio 3: la versión "de primer intento" del prompt. La instrucción sobre el estado
# final parece razonable ("no le des al pasajero algo a medias") y es la que cuelga el loop.
SISTEMA_INGENUO = f"""Sos el agente de atención al pasajero de la aerolínea OrbitAir. Hoy es {HOY}.
Atendés al pasajero {{pasajero_id}} ({{nombre}}).

- Usá las herramientas para consultar vuelos, valijas, reservas y políticas. Citá las políticas con su id.
- Antes de cada llamada a una herramienta, escribí en una línea qué vas a hacer y por qué.
- Cuando consultes una valija, asegurate de darle al pasajero el estado definitivo: si el estado todavía no es
  final, volvé a consultar hasta tenerlo.
- Español, cordial y breve."""

PROMPTS = {"produccion": SISTEMA, "ingenuo": SISTEMA_INGENUO}

CIERRE = ("[Control del sistema] Se cortó la ejecución: {motivo}. No llames más herramientas. Respondé al pasajero "
          "con la información que ya obtuviste, aclarando qué quedó pendiente y cuál es el próximo paso.")
DERIVACION = ("No puedo completar esta consulta por este medio. Te derivo con un agente del centro de atención "
              "de OrbitAir, que va a seguir el caso con vos.")


# ---------------------------------------------------------------------------
# Traza
# ---------------------------------------------------------------------------
@dataclass
class Accion:
    tool_call: ToolCall
    resultado: ResultadoTool


@dataclass
class Paso:
    numero: int
    llm: RespuestaLLM
    acciones: list[Accion] = field(default_factory=list)

    @property
    def pensamiento(self) -> str:
        return self.llm.texto.strip()


@dataclass
class Resultado:
    pregunta: str
    respuesta: str
    parada: str                                # "respuesta", "max_pasos", "repetida", "presupuesto", "tiempo", "error_duro"
    pasos: list[Paso]
    mensajes: list[dict]                       # el historial completo (sin el system)
    latencia_s: float = 0.0
    cierre: RespuestaLLM | None = None         # la llamada extra sin herramientas, si una regla cortó el loop

    @property
    def llamadas_llm(self) -> list[RespuestaLLM]:
        return [p.llm for p in self.pasos] + ([self.cierre] if self.cierre else [])

    @property
    def tokens(self) -> int:
        return sum(r.tokens_in + r.tokens_out for r in self.llamadas_llm)

    @property
    def costo_usd(self) -> float:
        return sum(r.costo_usd for r in self.llamadas_llm)

    @property
    def herramientas(self) -> list[str]:
        return [a.tool_call.nombre for p in self.pasos for a in p.acciones]


# ---------------------------------------------------------------------------
# EJERCICIO 3 · Stopping rules
# ---------------------------------------------------------------------------
@dataclass
class EstadoLoop:
    """Lo que las reglas miran antes de cada vuelta. Se arma en `correr()` (C1) o desde el estado del grafo (C2)."""
    pasos: int = 0                    # llamadas al LLM hechas en este turno
    costo_usd: float = 0.0
    segundos: float = 0.0
    firmas: list[str] = field(default_factory=list)     # ToolCall.firma de cada herramienta ejecutada


@dataclass
class ReglasDeParada:
    max_pasos: int = 6                # iteración acotada: nunca más de N vueltas
    max_repeticiones: int = 2         # la misma herramienta con los mismos argumentos
    max_usd: float = 0.01             # presupuesto por turno
    max_segundos: float = 60.0

    def evaluar(self, e: EstadoLoop) -> str | None:
        """None si se puede dar otra vuelta; si no, el motivo: "max_pasos", "repetida", "presupuesto" o "tiempo".

        "repetida": alguna firma aparece `max_repeticiones` veces o más (el modelo pide lo mismo esperando
        un resultado distinto). Se evalúa ANTES de cada llamada al LLM.
        """
        # TODO (Ejercicio 3), en este orden:
        # 1. e.pasos >= self.max_pasos                                       → "max_pasos"
        # 2. la firma más repetida (Counter(e.firmas)) aparece >= max_repeticiones veces → "repetida"
        # 3. e.costo_usd >= self.max_usd                                     → "presupuesto"
        # 4. e.segundos >= self.max_segundos                                 → "tiempo"
        # Provisorio hasta el Ejercicio 3: ninguna regla (sólo el fusible del Agente frena el loop).
        return None


SIN_REGLAS = ReglasDeParada(max_pasos=10**6, max_repeticiones=10**6, max_usd=float("inf"), max_segundos=float("inf"))


# ---------------------------------------------------------------------------
# El agente
# ---------------------------------------------------------------------------
class Agente:
    def __init__(self, pasajero_id: str, nombre: str = "", prompt: str = "produccion",
                 reglas: ReglasDeParada | None = None, herramientas: list[str] = HERRAMIENTAS_C1,
                 memoria: str = "", fusible: int = 15):
        """`fusible`: tope de vueltas que NO es una stopping rule de diseño sino una protección del
        ejercicio, para que "sin reglas" no corra para siempre (y para mostrar cuánto habría gastado)."""
        self.ctx = Contexto(pasajero_id)
        self.sistema = PROMPTS[prompt].format(pasajero_id=pasajero_id, nombre=nombre or "pasajero")
        if memoria:
            self.sistema += "\n\n" + memoria
        self.reglas = reglas or ReglasDeParada()
        self.herramientas = herramientas
        self.tools = specs(herramientas)
        self.fusible = fusible

    # -- piezas que reutiliza el grafo de C2 --------------------------------
    def llamar_llm(self, historial: list[dict], con_herramientas: bool = True) -> RespuestaLLM:
        return completar_con_tools([{"role": "system", "content": self.sistema}, *historial], self.tools,
                                   tool_choice="auto" if con_herramientas else "none")

    def ejecutar(self, tc: ToolCall, dormir=time.sleep) -> ResultadoTool:
        """`dormir`: la espera entre reintentos (C2 la envuelve para avisar el reintento por el stream)."""
        return ejecutar_con_triage(lambda: ejecutar_tool(tc.nombre, tc.argumentos, self.ctx, self.herramientas),
                                   dormir=dormir)

    def cerrar(self, historial: list[dict], motivo: str) -> RespuestaLLM:
        """Una última llamada SIN herramientas: el modelo no puede pedir nada más, sólo responder."""
        return self.llamar_llm([*historial, {"role": "user", "content": CIERRE.format(motivo=motivo)}],
                               con_herramientas=False)

    # -----------------------------------------------------------------------
    # EJERCICIO 2 · El loop
    # -----------------------------------------------------------------------
    def correr(self, pregunta: str, historial: list[dict] | None = None) -> Resultado:
        """Corre el loop ReAct para `pregunta`. `historial`: mensajes de turnos anteriores (memoria de corto plazo).

        Por cada vuelta:
        1. Armar el EstadoLoop (pasos, costo, segundos, firmas) y evaluar las reglas. Si alguna corta:
           `self.cerrar(...)` y devolver Resultado con parada=<motivo>. También cortar si se llegó al fusible.
        2. `r = self.llamar_llm(mensajes)`; guardar el Paso y agregar `r.mensaje` a los mensajes.
        3. Sin `r.tool_calls` → devolver Resultado(parada="respuesta", respuesta=r.texto).
        4. Por cada tool_call: `self.ejecutar(tc)`, registrar la Accion y agregar
           `mensaje_tool(tc.id, resultado.contenido)`. Todas las tool_calls reciben su mensaje `tool`.
        5. Si alguna terminó con `error_duro` → devolver Resultado(parada="error_duro", respuesta=DERIVACION).
        """
        t0 = time.perf_counter()
        mensajes = [*(historial or []), {"role": "user", "content": pregunta}]
        pasos: list[Paso] = []
        firmas: list[str] = []

        def fin(respuesta: str, parada: str, cierre: RespuestaLLM | None = None) -> Resultado:
            if cierre:
                mensajes.append(cierre.mensaje)
            elif parada == "error_duro":
                mensajes.append({"role": "assistant", "content": respuesta})
            return Resultado(pregunta, respuesta, parada, pasos, mensajes, time.perf_counter() - t0, cierre)

        # TODO: el loop (los 5 pasos del docstring). Esqueleto:
        # while True:
        #     estado = EstadoLoop(len(pasos), <costo acumulado de los pasos>, time.perf_counter() - t0, firmas)
        #     motivo = self.reglas.evaluar(estado) or ("fusible" if len(pasos) >= self.fusible else None)
        #     if motivo: cerrar con self.cerrar(mensajes, motivo) y devolver fin(c.texto, motivo, c)
        #     r = self.llamar_llm(mensajes) → Paso(len(pasos) + 1, r) a `pasos`, r.mensaje a `mensajes`
        #     sin r.tool_calls → return fin(r.texto, "respuesta")
        #     por cada tc: res = self.ejecutar(tc) → Accion, firmas.append(tc.firma),
        #                  mensajes.append(mensaje_tool(tc.id, res.contenido))
        #     si algún res.error_duro → return fin(DERIVACION, "error_duro")
        raise NotImplementedError("Ejercicio 2: el loop ReAct")
