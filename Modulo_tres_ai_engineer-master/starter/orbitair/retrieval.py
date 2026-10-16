"""C3 · El retrieval del M2 detrás de `buscar_politica`: búsqueda híbrida con filtro por documento.

Ya resuelto: viene del M2 (C1 embeddings · C3 híbrida y filtros por metadatos), en
versión compacta y sin vector DB. En C1-C2 el agente buscaba con BM25 sobre todo el
corpus (orbitair/politicas.py). En C3 cada worker busca SÓLO en el documento de su
dominio, con la configuración del M2:

    consulta ─┬─► vectorial (coseno contra los embeddings de los fragmentos) ─┐
              └─► BM25 (match exacto: códigos, clases de tarifa, siglas)     ─┴─► RRF ─► top-k

Mismo CONTRATO que en C1-C2 (consulta → [{id, titulo, texto}]): para el agente es
transparente, cambia lo que hay detrás. Eso es lo que permite enchufar "los índices
del M2" sin tocar el loop ni el grafo.

El FILTRO (`documentos=["POL-EQ-01"]`) se aplica ANTES de elegir el top-k, igual que
en la vector DB del M2: no es "buscar en todo y descartar lo que no es mío" (eso puede
devolver 0 resultados si los 3 mejores eran de otro documento), es buscar sólo en lo mío.

Índice: los embeddings de los fragmentos se calculan una vez y quedan en
results/c3_indice_<modelo>.npz (88 fragmentos: con la API real cuesta ~USD 0,0003).
Es un índice local (numpy): para este corpus alcanza y no suma dependencias. En el M2 · C3
se vio cómo se migra a Chroma, pgvector o Pinecone sin cambiar este contrato.

Modo mock (ORBITAIR_MOCK=1): embeddings por hashing de palabras y n-gramas (los del
M2). Palabras compartidas → vectores parecidos; NO entiende sinónimos.
"""
from __future__ import annotations

import hashlib
import math
import os
import re
import unicodedata
from collections import Counter, defaultdict
from functools import lru_cache
from pathlib import Path

import numpy as np
import tiktoken

from .bm25 import BM25
from .corpus import Fragmento, fragmentos_por_subseccion
from . import trazas
from .llm import MOCK

MODELO_EMBEDDINGS = os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")
RESULTS = Path(__file__).resolve().parents[2] / "results"
K_RRF = 60
CANDIDATOS = 20          # cuántos resultados aporta cada buscador antes de fusionar
DIM_MOCK = 512

DOCUMENTOS = {"POL-EQ-01": "Equipaje", "POL-TC-01": "Tarifas y cambios", "POL-RE-01": "Reembolsos y compensaciones"}


# ---------------------------------------------------------------------------
# Embeddings (OpenAI o mock)
# ---------------------------------------------------------------------------
_cliente = None
_enc = None


def contar_tokens(textos: list[str]) -> int:
    global _enc
    if _enc is None:
        _enc = tiktoken.get_encoding("cl100k_base")       # el tokenizador de text-embedding-3-*
    return sum(len(_enc.encode(t)) for t in textos)


def embeddear(textos: list[str]) -> np.ndarray:
    """Una fila por texto, normalizada (norma 1: el producto punto es el coseno)."""
    global _cliente
    if MOCK:
        return np.stack([_vector_mock(t) for t in textos])
    if _cliente is None:
        from openai import OpenAI
        _cliente = OpenAI()
    vectores = []
    for i in range(0, len(textos), 256):
        r = _cliente.embeddings.create(model=MODELO_EMBEDDINGS, input=textos[i:i + 256])
        vectores += [d.embedding for d in sorted(r.data, key=lambda d: d.index)]
    v = np.array(vectores, dtype=np.float32)
    return v / np.linalg.norm(v, axis=1, keepdims=True)


_STOP = set("""de la el los las un una unos unas y o u a en por para con sin del al que se su sus
es son lo le les mi mis me tu te nos como mas pero si no ya este esta estos estas ese esa eso
hay ser fue muy puedo puede cual cuales cuanto cuanta the an of to in and or is my it on for""".split())


def _vector_mock(texto: str) -> np.ndarray:
    """Hashing de palabras (stem de 5 letras), bigramas y 4-gramas de caracteres (M2 · C1)."""
    t = unicodedata.normalize("NFKD", texto.lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    palabras = [w for w in re.findall(r"[a-z0-9]+", t) if w not in _STOP and len(w) > 1]
    stems = [w[:5] for w in palabras]
    rasgos = Counter(f"w:{s}" for s in stems)
    rasgos.update(f"b:{a}_{b}" for a, b in zip(stems, stems[1:]))
    rasgos.update(f"c:{w[i:i + 4]}" for w in palabras if len(w) >= 5 for i in range(len(w) - 3))
    v = np.zeros(DIM_MOCK, dtype=np.float32)
    for rasgo, n in rasgos.items():
        h = int(hashlib.md5(rasgo.encode()).hexdigest(), 16)
        peso = (1 + math.log(n)) * {"w": 1.0, "b": 0.5, "c": 0.25}[rasgo[0]]
        v[h % DIM_MOCK] += peso if (h >> 64) & 1 else -peso
    return v / max(float(np.linalg.norm(v)), 1e-12)


# ---------------------------------------------------------------------------
# Índice
# ---------------------------------------------------------------------------
class Indice:
    def __init__(self, fragmentos: list[Fragmento], vectores: np.ndarray):
        self.fragmentos = fragmentos
        self.vectores = vectores
        self.docs = np.array([f.doc for f in fragmentos])
        self.bm25 = BM25([f"{f.ruta}\n{f.texto}" for f in fragmentos])

    def mascara(self, documentos: list[str] | None) -> np.ndarray:
        return np.ones(len(self.fragmentos), bool) if not documentos else np.isin(self.docs, documentos)

    def vectorial(self, consulta: str, k: int, mascara: np.ndarray) -> list[int]:
        s = self.vectores @ embeddear([consulta])[0]
        s = np.where(mascara, s, -np.inf)
        return [int(i) for i in np.argsort(-s)[:k] if np.isfinite(s[i])]

    def lexica(self, consulta: str, k: int, mascara: np.ndarray) -> list[int]:
        return [i for i, _ in self.bm25.buscar(consulta, k, mascara)]


def fusion_rrf(rankings: list[list[int]], k: int = K_RRF) -> list[tuple[int, float]]:
    """Reciprocal Rank Fusion (M2 · C3 · Ej. 4): suma 1/(k + posición) en cada ranking."""
    puntajes: dict[int, float] = defaultdict(float)
    for ranking in rankings:
        for posicion, i in enumerate(ranking, 1):
            puntajes[i] += 1 / (k + posicion)
    return sorted(puntajes.items(), key=lambda x: -x[1])


@lru_cache(maxsize=1)
def indice() -> Indice:
    """Carga el índice de results/ o lo construye (embeddea los fragmentos una sola vez)."""
    frags = fragmentos_por_subseccion()
    nombre = "mock" if MOCK else MODELO_EMBEDDINGS
    path = RESULTS / f"c3_indice_{nombre}.npz"
    ids = [f.id for f in frags]
    if path.exists():
        guardado = np.load(path, allow_pickle=False)
        if list(guardado["ids"]) == ids:
            return Indice(frags, guardado["vectores"])
    vectores = embeddear([f"{f.titulo}\n{f.texto}" for f in frags])
    RESULTS.mkdir(exist_ok=True)
    np.savez(path, ids=np.array(ids), vectores=vectores)
    return Indice(frags, vectores)


# ---------------------------------------------------------------------------
# La búsqueda (mismo contrato que politicas.buscar)
# ---------------------------------------------------------------------------
def buscar(consulta: str, k: int = 3, documentos: list[str] | None = None, modo: str = "hibrida",
           max_chars: int = 900) -> list[dict]:
    """Top-k fragmentos [{id, titulo, texto}]. `documentos`: filtro por código (None = todo el corpus).
    `modo`: "hibrida" (default, la del M2), "vectorial" o "bm25"."""
    with trazas.observacion("retrieval", "retriever", input={"consulta": consulta, "documentos": documentos,
                                                            "modo": modo}) as o:
        resultado = _buscar(consulta, k, documentos, modo, max_chars)
        o.output = [r["id"] for r in resultado]           # C5: qué fragmentos trajo (el diagnóstico R vs G del M2)
    return resultado


def _buscar(consulta: str, k: int, documentos: list[str] | None, modo: str, max_chars: int) -> list[dict]:
    ix = indice()
    m = ix.mascara(documentos)
    if modo == "bm25":
        top = ix.lexica(consulta, k, m)
    elif modo == "vectorial":
        top = ix.vectorial(consulta, k, m)
    elif modo == "hibrida":
        top = [i for i, _ in fusion_rrf([ix.vectorial(consulta, CANDIDATOS, m),
                                         ix.lexica(consulta, CANDIDATOS, m)])[:k]]
    else:
        raise ValueError(f"modo de búsqueda desconocido: {modo}")
    frags = ix.fragmentos
    return [{"id": frags[i].id, "titulo": frags[i].ruta.split(" > ", 1)[-1],
             "texto": frags[i].texto[:max_chars] + ("…" if len(frags[i].texto) > max_chars else "")} for i in top]
