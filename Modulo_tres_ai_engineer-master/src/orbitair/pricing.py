"""Costo por token, normalizado (mismo criterio que en M1).

Todo se expresa en USD por 1M tokens y el costo final en USD. Los modelos de
embeddings sólo cobran input: no generan tokens de salida.
"""
import json
from pathlib import Path

PRICING_PATH = Path(__file__).resolve().parents[2] / "pricing.json"


def load_pricing() -> dict:
    with open(PRICING_PATH, encoding="utf-8") as f:
        return json.load(f)


def cost_usd(provider: str, model: str, input_tokens: int, output_tokens: int = 0) -> float:
    """Costo en USD de una llamada. Lanza KeyError si el modelo no está en pricing.json."""
    p = load_pricing()[provider][model]
    return (input_tokens * p["input"] + output_tokens * p["output"]) / 1_000_000


def fmt_usd(x: float) -> str:
    """Formato legible: embeddear el corpus entero cuesta fracciones de centavo."""
    return f"${x:.6f}"
