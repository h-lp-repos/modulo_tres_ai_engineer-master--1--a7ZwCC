"""Leer el historial de mensajes: qué herramientas se llamaron, con qué argumentos y qué devolvieron.

Ya resuelto. Lo usan la memoria de largo plazo (orbitair/memoria.py), el mock y los
scripts que muestran trazas. En el formato de OpenAI, la llamada (en el mensaje
`assistant`, con un id) y su resultado (en un mensaje `tool` con ese mismo id) van
en mensajes distintos: acá se vuelven a juntar.
"""
from __future__ import annotations

import json
from dataclasses import dataclass


@dataclass
class Obs:
    nombre: str
    args: dict
    contenido: dict

    @property
    def firma(self) -> str:
        return f"{self.nombre}({json.dumps(self.args, sort_keys=True, ensure_ascii=False)})"

    @property
    def error(self) -> str | None:
        return self.contenido.get("error")


def observaciones(mensajes: list[dict]) -> list[Obs]:
    """Una Obs por cada resultado de herramienta, en orden, con la llamada que lo produjo."""
    llamadas: dict[str, tuple[str, dict]] = {}
    obs = []
    for m in mensajes:
        for tc in m.get("tool_calls") or []:
            try:
                args = json.loads(tc["function"]["arguments"] or "{}")
            except json.JSONDecodeError:
                args = {}
            llamadas[tc["id"]] = (tc["function"]["name"], args if isinstance(args, dict) else {})
        if m.get("role") == "tool" and m.get("tool_call_id") in llamadas:
            nombre, args = llamadas[m["tool_call_id"]]
            try:
                contenido = json.loads(m["content"])
            except (json.JSONDecodeError, TypeError):
                contenido = {"texto": m["content"]}
            obs.append(Obs(nombre, args, contenido if isinstance(contenido, dict) else {"valor": contenido}))
    return obs
