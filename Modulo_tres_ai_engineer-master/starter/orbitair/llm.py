"""Cliente de chat con TOOL CALLING (se suma en C1 del M3: el modelo ya no sólo responde, elige acciones).

En el M2 el LLM recibía un prompt y devolvía texto. Un agente necesita otra cosa:
que el modelo pueda decir "antes de responder, ejecutá esta función con estos
argumentos". Eso es tool calling: se le pasan al modelo las herramientas
disponibles (nombre, descripción, JSON Schema de los argumentos) y su respuesta
puede traer `tool_calls` en lugar de (o además de) texto.

El MODELO NO EJECUTA NADA: sólo propone la llamada. Ejecutarla, validar sus
argumentos, decidir qué hacer si falla y cuándo dejar de llamarlo es trabajo
nuestro — eso es el loop del agente (orbitair/agente.py).

Cada llamada cuenta: tokens, latencia y costo quedan en `RespuestaLLM`, igual que
en M1 y M2. Un solo proveedor (OpenAI, gpt-4.1-mini).

Modo mock (ORBITAIR_MOCK=1): no hay llamada de red. El "modelo" es
orbitair/mock_agente.py, un guion determinista que recibe los mismos mensajes y
herramientas y devuelve texto o tool_calls con el mismo formato que la API.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field

import tiktoken
from dotenv import load_dotenv

from . import trazas
from .pricing import cost_usd

load_dotenv()

MOCK = os.getenv("ORBITAIR_MOCK", "0") == "1"
MODELO = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")


class ErrorDeAPI(Exception):
    """Lo que la API rechaza antes de generar (ej. un mensaje `tool` huérfano). En modo real es un 400."""


@dataclass
class ToolCall:
    id: str
    nombre: str
    argumentos: dict              # ya parseados; {} si el JSON vino roto
    argumentos_raw: str           # el string tal cual lo generó el modelo

    @property
    def firma(self) -> str:
        """Identidad de la llamada (nombre + argumentos), para detectar repeticiones."""
        return f"{self.nombre}({json.dumps(self.argumentos, sort_keys=True, ensure_ascii=False)})"


@dataclass
class RespuestaLLM:
    texto: str
    tool_calls: list[ToolCall]
    modelo: str
    tokens_in: int
    tokens_out: int
    latencia_s: float
    mensaje: dict = field(default_factory=dict)     # el mensaje `assistant` para agregar al historial

    @property
    def costo_usd(self) -> float:
        return cost_usd("openai", self.modelo, self.tokens_in, self.tokens_out)


def mensaje_tool(tool_call_id: str, contenido: dict | str) -> dict:
    """La observación: el resultado de una herramienta vuelve al modelo como mensaje `tool`."""
    if not isinstance(contenido, str):
        contenido = json.dumps(contenido, ensure_ascii=False)
    return {"role": "tool", "tool_call_id": tool_call_id, "content": contenido}


_enc = None


def contar_tokens(mensajes: list[dict]) -> int:
    """Aproximación con o200k_base (el tokenizador de gpt-4.1): para el mock y para presupuestos."""
    global _enc
    if _enc is None:
        _enc = tiktoken.get_encoding("o200k_base")
    return sum(len(_enc.encode(json.dumps(m, ensure_ascii=False))) for m in mensajes)


def validar_mensajes(mensajes: list[dict]) -> None:
    """Las dos reglas de la API sobre tool calling (en modo real las aplica OpenAI y devuelve un 400):
    1. todo mensaje `tool` responde a un `tool_call` de un mensaje `assistant` ANTERIOR;
    2. todo `tool_call` de un `assistant` tiene su mensaje `tool` antes del siguiente mensaje que no sea `tool`.
    """
    pendientes: set[str] = set()
    for i, m in enumerate(mensajes):
        rol = m.get("role")
        if rol == "tool":
            if m.get("tool_call_id") not in pendientes:
                raise ErrorDeAPI(f"400 · messages[{i}]: un mensaje 'tool' debe responder a un 'tool_call' "
                                 f"de un mensaje 'assistant' anterior (tool_call_id={m.get('tool_call_id')}).")
            pendientes.discard(m["tool_call_id"])
            continue
        if pendientes:
            raise ErrorDeAPI(f"400 · messages[{i}]: faltan las respuestas 'tool' de {sorted(pendientes)}.")
        if rol == "assistant":
            pendientes = {tc["id"] for tc in m.get("tool_calls") or []}
    if pendientes:
        raise ErrorDeAPI(f"400 · faltan las respuestas 'tool' de {sorted(pendientes)}.")


def _parsear(raw: str) -> dict:
    try:
        args = json.loads(raw or "{}")
        return args if isinstance(args, dict) else {}
    except json.JSONDecodeError:
        return {}


_cliente = None


def completar_con_tools(mensajes: list[dict], tools: list[dict] | None = None, *, tool_choice: str | dict = "auto",
                        max_tokens: int = 500, temperature: float = 0.0) -> RespuestaLLM:
    """La llamada de chat, OBSERVADA (C5): dentro de una traza queda como una generation con modelo, tokens y
    costo (orbitair/trazas.py). Fuera de una traza es exactamente la llamada de C1."""
    nombres = [t["function"]["name"] for t in tools or []]
    with trazas.observacion(MODELO, "generation", input=mensajes, modelo=MODELO,
                            metadata={"tools": nombres, "tool_choice": tool_choice}) as g:
        r = _completar_con_tools(mensajes, tools, tool_choice=tool_choice, max_tokens=max_tokens,
                                 temperature=temperature)
        g.registrar_llm(r)
    return r


def _completar_con_tools(mensajes: list[dict], tools: list[dict] | None = None, *, tool_choice: str | dict = "auto",
                         max_tokens: int = 500, temperature: float = 0.0) -> RespuestaLLM:
    """Una llamada de chat. `tools`: especificaciones en formato OpenAI (orbitair/tools.py).
    `tool_choice="none"`: el modelo ve las herramientas (el historial las menciona) pero sólo puede responder
    con texto. Se usa para cerrar un loop que cortó una stopping rule.
    `tool_choice={"type": "function", "function": {"name": ...}}` (C3): OBLIGA a llamar esa herramienta; así el
    router del orquestador devuelve siempre una salida estructurada."""
    global _cliente
    if MOCK:
        from .mock_agente import decidir
        validar_mensajes(mensajes)
        t0 = time.perf_counter()
        texto, llamadas = decidir(mensajes, tools if tools and tool_choice != "none" else [])
        msg = {"role": "assistant", "content": texto or None}
        if llamadas:
            msg["tool_calls"] = [{"id": c["id"], "type": "function",
                                  "function": {"name": c["nombre"], "arguments": json.dumps(c["argumentos"],
                                                                                            ensure_ascii=False)}}
                                 for c in llamadas]
        time.sleep(0.05 + len(texto or "") / 8000)      # latencia simulada, del orden de un modelo chico
        tcs = [ToolCall(c["id"], c["nombre"], c["argumentos"], json.dumps(c["argumentos"], ensure_ascii=False))
               for c in llamadas]
        tin = contar_tokens(mensajes) + (contar_tokens(tools) if tools else 0)
        return RespuestaLLM(texto or "", tcs, MODELO, tin, contar_tokens([msg]), time.perf_counter() - t0, msg)

    if _cliente is None:
        from openai import OpenAI
        _cliente = OpenAI()
    kwargs = {"tools": tools, "tool_choice": tool_choice} if tools else {}
    t0 = time.perf_counter()
    r = _cliente.chat.completions.create(model=MODELO, temperature=temperature, max_tokens=max_tokens,
                                         messages=mensajes, **kwargs)
    m = r.choices[0].message
    tcs = [ToolCall(tc.id, tc.function.name, _parsear(tc.function.arguments), tc.function.arguments)
           for tc in m.tool_calls or []]
    msg = {"role": "assistant", "content": m.content}
    if m.tool_calls:
        msg["tool_calls"] = [{"id": tc.id, "type": "function",
                              "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                             for tc in m.tool_calls]
    return RespuestaLLM(m.content or "", tcs, MODELO, r.usage.prompt_tokens, r.usage.completion_tokens,
                        time.perf_counter() - t0, msg)
