"""El "modelo" del modo mock para el orquestador de C3: router por palabras clave y síntesis por plantilla.

Ya resuelto, no tocar. Lo llama orbitair/mock_agente.py cuando la llamada es del router
(herramienta `rutear_consulta`) o de la síntesis (system del redactor final).

Router: parte la consulta en cláusulas (por "?", ".", ":", ";" y " y "), asigna cada cláusula a
los dominios cuyas palabras clave aparecen y reparte las cláusulas sin dominio (el contexto: "me
cancelaron el OA2250") a todos los dominios encontrados. Copia a cada tarea los códigos que
necesita. Es un clasificador por reglas: acierta en lo obvio y se equivoca como se equivocan las
reglas (una palabra de otro dominio alcanza para sumar un worker de más). El router con LLM se
mide con la API real.
"""
from __future__ import annotations

import re
import unicodedata

CLAVES = {
    "equipaje": ["valija", "maleta", "equipaje", "de mano", "bodega", "mascota", "sobrepeso", "articulo personal",
                 "indemniz", "rueda"],
    "cambios": ["cambi", "reprogram", "horario", "como viene", " sale ", "sale hoy", "conexion", "no show",
                "opciones", "de la reserva", "datos de"],
    "reembolsos": ["reembols", "devuelv", "devolucion", "plata", "compensa", "voucher", "comer", "comida", "hotel",
                   "acredit", "asistencia", "arrepent", "paga"],
}
_AEROLINEA = ["vuelo", "valija", "equipaje", "reserva", "pasaje", "tarifa", "orbitair", "aeropuerto", "maleta"]
_contador = 0


def _norm(t: str) -> str:
    t = unicodedata.normalize("NFKD", t.lower())
    return " " + "".join(c for c in t if not unicodedata.combining(c)) + " "


def _codigos(texto: str) -> dict[str, list[str]]:
    t = texto.upper()
    valijas = re.findall(r"\bOA-\d{6}\b", t) + re.findall(r"\b[A-Z]{3}-\d{5}\b", t)
    vuelos = re.findall(r"\bOA\s?\d{4}\b", t)
    reservas = [r for r in re.findall(r"\b[A-Z0-9]{6}\b", texto)
                if re.search(r"\d", r) and re.search(r"[A-Z]", r) and not re.fullmatch(r"[A-Z]{2}\d{4}", r)]
    return {"valijas": valijas, "vuelos": vuelos, "reservas": reservas}


def _clausulas(consulta: str) -> list[str]:
    partes = re.split(r"[?.:;¿]+|\s+[yY]\s+", consulta)
    return [p.strip(" ,!¡") for p in partes if len(p.strip(" ,!¡")) > 2]


def rutear(consulta: str) -> list[dict]:
    asignadas: dict[str, list[str]] = {}
    contexto: list[str] = []
    for c in _clausulas(consulta):
        n = _norm(c)
        doms = [d for d, claves in CLAVES.items() if any(k in n for k in claves)]
        if not doms and _codigos(c)["valijas"]:
            doms = ["equipaje"]
        if not doms:
            contexto.append(c)
        for d in doms:
            asignadas.setdefault(d, []).append(c)
    if not asignadas:
        cod = _codigos(consulta)
        if cod["vuelos"] or cod["reservas"] or any(w in _norm(consulta) for w in _AEROLINEA):
            asignadas["cambios"] = []
        else:
            return [{"dominio": "otros", "tarea": consulta}]
    intenciones = []
    cod = _codigos(consulta)
    for d, cls in asignadas.items():
        tarea = ". ".join(contexto + cls) or consulta
        propios = _codigos(tarea)
        n = _norm(tarea)
        faltan = []
        if not any(propios.values()):          # la parte no trae códigos: copiar los que necesita
            if d == "equipaje" and "valija" in n:
                faltan = cod["valijas"]
            elif d != "equipaje" and "vuelo" in n:
                faltan = cod["vuelos"] or cod["reservas"]
            elif d != "equipaje" and "reserva" in n:
                faltan = cod["reservas"]
        intenciones.append({"dominio": d, "tarea": tarea + (f" ({', '.join(faltan)})" if faltan else "")})
    return intenciones


def llamada_router(consulta: str) -> tuple[str, list[dict]]:
    global _contador
    _contador += 1
    return "", [{"id": f"call_router_{_contador:04d}", "nombre": "rutear_consulta",
                 "argumentos": {"intenciones": rutear(consulta)}}]


def sintetizar(contenido: str) -> str:
    """Une las respuestas de los especialistas (sin repetir oraciones). No reescribe: no razona."""
    bloques = re.findall(r"Respuesta del especialista en \w+ \(su parte: .*?\):\n(.*?)(?=\n\nRespuesta del especialista|\Z)",
                         contenido, flags=re.S)
    oraciones: list[str] = []
    for b in bloques:
        for o in re.split(r"(?<=[.!?])\s+(?=[A-ZÁÉÍÓÚÑ¿¡])", b.strip()):
            if o and o not in oraciones:
                oraciones.append(o)
    return " ".join(oraciones)
