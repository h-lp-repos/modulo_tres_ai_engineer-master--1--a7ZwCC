import json
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parents[2] / "data"


def load_jsonl(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def load_consultas_c1() -> list[dict]:
    """C1: consultas de pasajeros para el agente, etiquetadas por TRAYECTORIA esperada.

    `herramientas`: qué herramientas debería usar (sin orden; [] = ninguna).
    `parada`: cómo debería terminar ("respuesta" o "error_duro").
    `hechos`: fragmentos que la respuesta tiene que contener (sin tildes ni mayúsculas).
    `tipo`: qué ejercita (una_tool, datos+politica, sin_tool, error_entrada, permiso, colgado...).
    Es la semilla del dataset de evals de trayectoria de C5.
    """
    return load_jsonl(DATA_DIR / "c1_consultas_agente.jsonl")

def load_consultas_c3() -> list[dict]:
    """C3: consultas para el sistema multiagente, etiquetadas con la RUTA esperada.

    Los mismos campos que C1, más `dominios`: qué workers tienen que intervenir (["otros"] = ninguno).
    `herramientas` es la unión de lo que usan todos los workers; `tipo`: un_dominio, cruce u otros.
    Incluye consultas que cruzan dominios ("perdí la valija en el vuelo que llegó tarde"). Es el dataset
    de evals de trayectoria de C5.
    """
    return load_jsonl(DATA_DIR / "c3_consultas_multiagente.jsonl")


def load_conversaciones_c5() -> list[dict]:
    """C5: el dataset de CONVERSACIONES. Cada una es una sesión de un pasajero con 1-3 turnos; cada turno es el
    id de una consulta etiquetada de C3 (así cada turno trae su ruta, herramientas, parada y hechos esperados).
    10 sesiones, 25 turnos: las 25 consultas de C3, agrupadas como llegarían en conversaciones reales."""
    return load_jsonl(DATA_DIR / "c5_conversaciones.jsonl")
