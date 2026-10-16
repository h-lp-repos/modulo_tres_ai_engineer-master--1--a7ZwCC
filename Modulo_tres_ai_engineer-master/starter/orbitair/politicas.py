"""Búsqueda en las políticas de OrbitAir, para la herramienta `buscar_politica` del agente.

Ya resuelto, y deliberadamente MÍNIMO: BM25 (el de M2 · C3) sobre las secciones del
corpus (un fragmento por subsección, ids `POL-RE-01#8.1`). No hace falta API key
ni índice: C1 y C2 son sobre el LOOP del agente, no sobre el retrieval.

En C3 (multiagente) cada worker usa el retrieval del M2 (orbitair/retrieval.py:
híbrida embeddings + BM25 + RRF, filtrada por el documento de su dominio). Para el
agente es transparente: la herramienta mantiene el mismo contrato (consulta →
fragmentos con id), cambia lo que hay detrás.
"""
from __future__ import annotations

from functools import lru_cache

from .bm25 import BM25
from .corpus import Fragmento, fragmentos_por_subseccion


@lru_cache(maxsize=1)
def _indice() -> tuple[list[Fragmento], BM25]:
    frags = fragmentos_por_subseccion()
    return frags, BM25([f"{f.ruta}\n{f.texto}" for f in frags])


def buscar(consulta: str, k: int = 3, max_chars: int = 900) -> list[dict]:
    """Top-k fragmentos [{id, titulo, texto}] para una consulta. Lista vacía si nada comparte términos."""
    frags, bm25 = _indice()
    return [{"id": frags[i].id, "titulo": frags[i].ruta.split(" > ", 1)[-1],
             "texto": frags[i].texto[:max_chars] + ("…" if len(frags[i].texto) > max_chars else "")}
            for i, _ in bm25.buscar(consulta, k)]
