"""BM25: búsqueda léxica, a mano. Viene resuelto del M2 (C3 · Ejercicio 3), sin cambios.

En el M3 lo usa `buscar_politica` (orbitair/politicas.py) y el mock del agente.

Un embedding responde "¿de qué habla este texto?". BM25 responde otra pregunta:
"¿qué tan seguido aparecen en este texto las palabras de la consulta, y qué tan
raras son esas palabras en el corpus?". No entiende sinónimos ni idiomas, pero
tiene algo que al embedding le cuesta: el MATCH EXACTO de tokens raros. Una "K"
de clase de reserva, un "BUE", un "LIM-48213" son casi ruido para un embedding
y oro para BM25, porque aparecen en uno o dos chunks de todo el corpus.

Para un término t de la consulta y un chunk d:

    IDF(t)     = ln(1 + (N - df(t) + 0.5) / (df(t) + 0.5))      raro en el corpus → pesa más
    score(t,d) = IDF(t) · tf·(k1 + 1) / (tf + k1·(1 - b + b·|d|/avgdl))

    tf = veces que t aparece en d · |d| = largo de d en tokens · avgdl = largo promedio
    k1 (1.5): satura la frecuencia — la 5ª aparición suma mucho menos que la 1ª.
    b (0.75): normaliza por largo — un chunk largo tiene más palabras "de casualidad".

El score del chunk es la suma sobre los términos de la consulta.
"""
from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter

import numpy as np

# Stopwords en español (y un par en inglés). Ojo: "y" es stopword... y también la clase de reserva Y.
_STOP = set("""a al algo como con cual cuales cuando cuanto cuanta cuantos de del desde donde el ella
ellos en entre era es esa ese eso esta estas este esto estos fue ha hay la las le les lo los me mi mis
muy mas me nos o para pero por porque que se si sin sobre su sus te tengo tiene tu un una uno unos unas
y ya yo e u puedo puede hace tan the of to and or is my it on for in an""".split())


def tokenizar(texto: str) -> list[str]:
    """Minúsculas, sin tildes, tokens alfanuméricos, sin stopwords. Sin stemming: "rueda" ≠ "ruedas"."""
    t = unicodedata.normalize("NFKD", texto.lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    return [w for w in re.findall(r"[a-z0-9]+", t) if w not in _STOP]


class BM25:
    def __init__(self, textos: list[str], k1: float = 1.5, b: float = 0.75):
        self.k1, self.b = k1, b
        self.docs = [Counter(tokenizar(t)) for t in textos]      # tf por chunk
        self.largos = np.array([sum(d.values()) for d in self.docs], dtype=float)
        self.avgdl = float(self.largos.mean())
        self.df = Counter(t for d in self.docs for t in d)       # en cuántos chunks aparece cada término
        self.N = len(self.docs)

    def idf(self, termino: str) -> float:
        df = self.df.get(termino, 0)
        return math.log(1 + (self.N - df + 0.5) / (df + 0.5))

    # -----------------------------------------------------------------------
    # Puntaje BM25 de cada chunk para una consulta (M2 · C3 · Ejercicio 3)
    # -----------------------------------------------------------------------
    def puntajes(self, consulta: str) -> np.ndarray:
        """Un puntaje por chunk (mismo orden que `textos`). 0 si no comparte ningún término."""
        scores = np.zeros(self.N)
        for t in set(tokenizar(consulta)):
            if t not in self.df:
                continue
            idf = self.idf(t)
            for i, d in enumerate(self.docs):
                tf = d.get(t, 0)
                if tf:
                    scores[i] += idf * tf * (self.k1 + 1) / (
                        tf + self.k1 * (1 - self.b + self.b * self.largos[i] / self.avgdl))
        return scores

    # -----------------------------------------------------------------------
    # Helpers (ya resueltos)
    # -----------------------------------------------------------------------
    def buscar(self, consulta: str, k: int = 5, mascara: np.ndarray | None = None) -> list[tuple[int, float]]:
        """Top-k [(índice, puntaje)] con puntaje > 0. `mascara`: chunks permitidos (filtro por metadatos)."""
        s = self.puntajes(consulta)
        if mascara is not None:
            s = np.where(mascara, s, 0.0)
        top = np.argsort(-s)[:k]
        return [(int(i), float(s[i])) for i in top if s[i] > 0]

    def explicar(self, consulta: str, i: int) -> list[tuple[str, int, float, float]]:
        """Por qué el chunk i sacó su puntaje: [(término, df, idf, aporte)], de mayor a menor aporte."""
        filas = []
        for t in set(tokenizar(consulta)):
            tf = self.docs[i].get(t, 0)
            aporte = 0.0
            if tf:
                aporte = self.idf(t) * tf * (self.k1 + 1) / (
                    tf + self.k1 * (1 - self.b + self.b * self.largos[i] / self.avgdl))
            filas.append((t, self.df.get(t, 0), self.idf(t), aporte))
        return sorted(filas, key=lambda f: -f[3])
