"""Chequeos de trayectoria y formato de trazas (ya resuelto).

Un agente no se evalúa sólo por su respuesta: dos agentes pueden decir lo mismo y uno
haber consultado tres sistemas de más, o haber llegado de casualidad. Acá se mira la
TRAYECTORIA contra lo etiquetado en el dataset:

- ¿usó las herramientas esperadas (ni más, ni menos)?
- ¿terminó como debía ("respuesta" o "error_duro")?
- ¿la respuesta contiene los hechos clave?
- ¿cuántos pasos, tokens y USD le costó?

Es la versión mínima de los evals de trayectoria de C5 (allí, con Langfuse y un
dataset más grande). C2 la usa para comprobar que la migración a LangGraph no
cambió el comportamiento.
"""
from __future__ import annotations

import json
import unicodedata
from dataclasses import dataclass


def _norm(t: str) -> str:
    t = unicodedata.normalize("NFKD", (t or "").lower())
    return "".join(c for c in t if not unicodedata.combining(c))


@dataclass
class Chequeo:
    herramientas_ok: bool
    parada_ok: bool
    hechos_ok: bool
    faltan: list[str]
    sobran: list[str]

    @property
    def ok(self) -> bool:
        return self.herramientas_ok and self.parada_ok and self.hechos_ok


def chequear(caso: dict, herramientas: list[str], parada: str, respuesta: str) -> Chequeo:
    """C3 suma dos campos opcionales al dataset: `opcionales` (herramientas que no son error usar, ej. consultar
    el vuelo antes de cotizar un cambio) y hechos con alternativas ("ciclos|60 dias": alcanza con una)."""
    esperadas, usadas = set(caso["herramientas"]), set(herramientas) - set(caso.get("opcionales", []))
    hechos_ok = all(any(_norm(alt) in _norm(respuesta) for alt in h.split("|")) for h in caso.get("hechos", []))
    return Chequeo(esperadas == usadas, parada == caso["parada"], hechos_ok,
                   sorted(esperadas - usadas), sorted(usadas - esperadas))


def marca(ok: bool) -> str:
    return "✓" if ok else "✗"


def imprimir_traza(resultado, ancho: int = 150) -> None:
    """Pensamiento → acción → observación, paso por paso (Resultado de C1)."""
    for p in resultado.pasos:
        print(f"  [{p.numero}] LLM · {p.llm.tokens_in}+{p.llm.tokens_out} tokens · {p.llm.latencia_s:.2f} s")
        if p.pensamiento and p.acciones:
            print(f"      pensamiento: {p.pensamiento}")
        for a in p.acciones:
            print(f"      acción:      {a.tool_call.nombre}({json.dumps(a.tool_call.argumentos, ensure_ascii=False)})")
            for i in a.resultado.intentos:
                if i.error:
                    extra = f" → reintento en {i.espera_s:.1f} s" if i.espera_s else ""
                    print(f"      ⚠ intento {i.numero}: {i.error}{extra}")
            obs = json.dumps(a.resultado.contenido, ensure_ascii=False)
            print(f"      observación: {obs[:ancho]}{'…' if len(obs) > ancho else ''}")
    if resultado.cierre:
        print(f"  [corte] por {resultado.parada} → una llamada más, sin herramientas "
              f"({resultado.cierre.tokens_in}+{resultado.cierre.tokens_out} tokens)")
    print(f"  respuesta ({resultado.parada}): {resultado.respuesta}")
