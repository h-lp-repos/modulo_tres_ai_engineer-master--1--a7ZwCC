"""El "modelo" del modo mock (ORBITAIR_MOCK=1): un guion determinista con la interfaz de tool calling.

Ya resuelto, no tocar. NO es un LLM: es un conjunto de reglas que lee los mismos
mensajes y herramientas que recibiría gpt-4.1-mini y devuelve lo mismo que la API
(texto y/o tool_calls). Sirve para ensayar el loop, las stopping rules, el triage,
la memoria y el grafo sin API key y con resultados reproducibles.

Qué imita (a propósito):
- Planifica: extrae códigos de vuelo, valija, PIR y reserva de la consulta y llama a
  las herramientas de datos (en paralelo, como hace la API) y después a la política.
- Usa la memoria: si la consulta dice "mi valija" sin código, lo busca en los turnos
  anteriores y en el system prompt (memoria de largo plazo).
- Obedece al prompt ingenuo de C1 · Ej. 3: si la valija no tiene estado final y el
  system dice "volvé a consultar hasta tenerlo", vuelve a consultar. Siempre.
- Si recibe un timeout como observación (agente sin triage), reintenta la llamada.
- Cuando el harness corta el loop (mensaje "[Control del sistema]"), responde con lo
  que tiene.
- C3: si le llega la herramienta del router (`rutear_consulta`) o el system de la síntesis,
  responde con orbitair/mock_orquestador.py. Si es un worker, lee sólo SU parte de la
  consulta (lo que viene después de "Tu parte (...):").

Qué no hace: razonar. Las respuestas son plantillas armadas con las observaciones
(estado del vuelo, oración de la política que más palabras comparte con la consulta).
Los hallazgos sobre la CALIDAD del agente se ven con la API real.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from . import mock_orquestador
from .bm25 import tokenizar
from .historial import Obs, observaciones

MARCA_INGENUA = "volvé a consultar hasta tenerlo"
MARCA_TAREA = "[Orquestador]"               # C3: así le llega la tarea a un worker
MARCA_SINTESIS = "Sos el redactor final"     # C3: el system de la síntesis
CONTROL = "[Control del sistema]"
_contador = 0

CAUSAS = {"operativa": "operativa", "tecnica": "técnica", "meteorologica": "meteorológica",
          "control_transito_aereo": "control de tránsito aéreo"}
ESTADOS_VALIJA = {"en_transito": "en tránsito", "en_busqueda": "en búsqueda", "demorada": "demorada",
                  "entregada": "entregada", "perdida": "perdida", "danada_reportada": "con reporte de daño",
                  "devuelta_al_pasajero": "devuelta al pasajero"}


def _norm(t: str) -> str:
    t = unicodedata.normalize("NFKD", t.lower())
    return "".join(c for c in t if not unicodedata.combining(c))


@dataclass
class Entidades:
    vuelos: list[str] = field(default_factory=list)
    valijas: list[str] = field(default_factory=list)
    reservas: list[str] = field(default_factory=list)


def entidades(texto: str) -> Entidades:
    t = texto.upper()
    valijas = re.findall(r"\bOA-?\d{6}\b", t) + re.findall(r"\b[A-Z]{3}-\d{5}\b", t)
    vuelos = [f"{a}{b}" for a, b in re.findall(r"\b([A-Z]{2})[\s-]?(\d{3,4})\b", t)]
    reservas = [r for r in re.findall(r"\b[A-Z0-9]{6}\b", texto)
                if re.search(r"\d", r) and re.search(r"[A-Z]", r) and not re.fullmatch(r"[A-Z]{2}\d{4}", r)]
    return Entidades(list(dict.fromkeys(vuelos)), list(dict.fromkeys(valijas)), list(dict.fromkeys(reservas)))


# ---------------------------------------------------------------------------
# Intenciones (palabras clave)
# ---------------------------------------------------------------------------
_POLITICA = ["corresponde", "compens", "me dan", "me tienen que dar", "puedo", "que hago", "cuanto", "cuanta",
             "derecho", "devuelv", "paga", "politica", "comer", "comida", "hotel", "llevar", "permit", "algo",
             "cubr", "cobr", "tarda", "opcion", "conviene", "indemniz", "acredit", "asistencia"]
_REEMBOLSO = ["quiero el reembolso", "quiero que me devuelvan", "pedir el reembolso", "iniciar el reembolso",
              "solicitar el reembolso", "quiero reembolso", "inicien el reembolso", "hacer el reembolso"]
_DOMINIO = ["vuelo", "valija", "equipaje", "reserva", "pasaje", "tarifa", "reembolso", "demora", "cancel",
            "orbitair", "conexion", "compensacion", "asiento", "millas", "embarque", "aeropuerto", "maleta"]


def _tiene(texto: str, claves: list[str]) -> bool:
    n = _norm(texto)
    return any(c in n for c in claves)


# ---------------------------------------------------------------------------
# Decisión
# ---------------------------------------------------------------------------
def decidir(mensajes: list[dict], tools: list[dict]) -> tuple[str, list[dict]]:
    sistema = mensajes[0]["content"] if mensajes and mensajes[0]["role"] == "system" else ""
    disponibles = {t["function"]["name"] for t in tools}
    iu = max(i for i, m in enumerate(mensajes)
             if m["role"] == "user" and not str(m["content"]).startswith(CONTROL))
    consulta = mensajes[iu]["content"]
    if "rutear_consulta" in disponibles:                       # C3: el router del orquestador
        return mock_orquestador.llamada_router(consulta)
    if sistema.startswith(MARCA_SINTESIS):                     # C3: la síntesis de las respuestas
        return mock_orquestador.sintetizar(consulta), []
    if consulta.startswith(MARCA_TAREA):                       # C3: un worker lee sólo su parte
        consulta = consulta.split("\nTu parte (", 1)[-1].split("): ", 1)[-1]
    turno = observaciones(mensajes[iu + 1:])
    previas = observaciones(mensajes[1:iu])
    ent = entidades(consulta)
    faltante = _resolver_referencias(consulta, ent, previas, sistema)
    contexto = [o for o in previas if _referida(o, consulta) and o.nombre != "buscar_politica"] + turno

    if not tools:                                   # cierre forzado: sólo puede responder
        return redactar(consulta, contexto, faltante), []

    # Obedece al prompt ingenuo: estado no final → volver a consultar (la causa del loop colgado de C1 · Ej. 3).
    if turno and turno[-1].nombre == "rastrear_valija" and turno[-1].contenido.get("encontrada") \
            and not turno[-1].contenido.get("estado_final") and MARCA_INGENUA in sistema:
        o = turno[-1]
        return "El estado todavía no es definitivo: vuelvo a consultar la valija.", [_llamada(o.nombre, o.args)]
    # Sin triage, un timeout le llega como observación: el "modelo" reintenta (gastando un paso de LLM).
    if turno and turno[-1].error and "timeout" in turno[-1].error:
        o = turno[-1]
        return "El sistema no respondió; vuelvo a intentar la consulta.", [_llamada(o.nombre, o.args)]
    if any(o.contenido.get("tipo") == "entrada" for o in turno):
        return redactar(consulta, contexto, faltante), []          # no insiste con un dato mal escrito

    hechas = {o.firma for o in turno}
    datos = [("consultar_vuelo", {"codigo_vuelo": v}) for v in ent.vuelos] + \
            [("rastrear_valija", {"codigo": t}) for t in ent.valijas] + \
            [("consultar_reserva", {"codigo_reserva": r}) for r in ent.reservas]
    for o in turno:                                 # la reserva lleva a sus vuelos con problemas
        if o.nombre == "consultar_reserva" and o.contenido.get("encontrada") and \
                (_tiene(consulta, _POLITICA) or _tiene(consulta, _REEMBOLSO)):
            datos += [("consultar_vuelo", {"codigo_vuelo": v["codigo"]}) for v in o.contenido["vuelos"]
                      if v["estado"] in ("cancelado", "demorado")]
    pendientes = [(n, a) for n, a in datos if n in disponibles and Obs(n, a, {}).firma not in hechas]
    if pendientes:
        return _pensamiento(pendientes), [_llamada(n, a) for n, a in pendientes]

    if faltante:
        return redactar(consulta, contexto, faltante), []
    if "buscar_politica" in disponibles and (_tiene(consulta, _POLITICA) or _tiene(consulta, _REEMBOLSO)):
        args = {"consulta": consulta_politica(consulta, contexto)}
        if Obs("buscar_politica", args, {}).firma not in hechas:
            return "Busco en la política de OrbitAir qué corresponde en este caso.", [
                _llamada("buscar_politica", args)]

    if "iniciar_reembolso" in disponibles and _tiene(consulta, _REEMBOLSO) and \
            not any(o.nombre == "iniciar_reembolso" for o in turno):
        for o in turno:
            if o.nombre == "consultar_reserva" and o.contenido.get("encontrada") and any(
                    v.contenido.get("estado") == "cancelado" for v in turno if v.nombre == "consultar_vuelo"):
                if not any(r["estado"] in ("solicitado", "en_revision", "aprobado") for r in o.contenido["reembolsos"]):
                    return ("El vuelo fue cancelado por OrbitAir: corresponde el reembolso involuntario. "
                            "Inicio la solicitud."), [_llamada("iniciar_reembolso", {
                                "codigo_reserva": o.contenido["codigo"], "motivo": "cancelacion_involuntaria"})]
    return redactar(consulta, contexto, faltante), []


def _llamada(nombre: str, args: dict) -> dict:
    global _contador
    _contador += 1
    return {"id": f"call_mock_{_contador:04d}", "nombre": nombre, "argumentos": dict(args)}


def _pensamiento(pendientes: list[tuple[str, dict]]) -> str:
    partes = {"consultar_vuelo": "el estado del vuelo {codigo_vuelo}", "rastrear_valija": "la valija {codigo}",
              "consultar_reserva": "la reserva {codigo_reserva}"}
    return "Voy a consultar " + " y ".join(partes[n].format(**a) for n, a in pendientes) + "."


def _referida(o: Obs, consulta: str) -> bool:
    """¿Una observación de un turno anterior es relevante para esta consulta? (referencias tipo "esa demora")."""
    n = _norm(consulta)
    return (o.nombre == "consultar_vuelo" and any(w in n for w in ("vuelo", "demora", "cancel"))) or \
        (o.nombre == "rastrear_valija" and any(w in n for w in ("valija", "equipaje", "maleta"))) or \
        (o.nombre == "consultar_reserva" and "reserva" in n)


def _resolver_referencias(consulta: str, ent: Entidades, previas: list[Obs], sistema: str) -> str | None:
    """Completa `ent` con lo que la consulta menciona sin código. Devuelve qué dato falta, si falta alguno."""
    n = _norm(consulta)
    pide_valija = bool(re.search(r"\b(mi|la|esa|de la)\s+(valija|maleta)\b", n)) and not ent.valijas
    pide_vuelo = any(w in n for w in ("mi vuelo", "ese vuelo", "esa demora", "el vuelo")) and not (
        ent.vuelos or ent.reservas)
    if pide_valija:
        en_turnos = [o.args["codigo"] for o in previas if o.nombre == "rastrear_valija"]
        if not en_turnos:
            memoria = entidades(sistema.split("Memoria", 1)[-1]).valijas if "Memoria" in sistema else []
            if memoria:
                ent.valijas.append(memoria[0])       # de otra sesión: hay que volver a consultar
            else:
                return "valija"
    if pide_vuelo:
        if not any(o.nombre == "consultar_vuelo" for o in previas):
            memoria = entidades(sistema.split("Memoria", 1)[-1]).vuelos if "Memoria" in sistema else []
            if memoria:
                ent.vuelos.append(memoria[0])
            else:
                return "vuelo"
    return None


def consulta_politica(consulta: str, obs: list[Obs]) -> str:
    """Lo que buscaría un modelo después de ver los datos: la consulta en palabras de la política."""
    n = _norm(consulta)
    if re.search(r"\d+\s*horas", n):                 # el pasajero ya dijo de qué demora habla
        return consulta
    # C3: lo que un modelo escribiría "en palabras de la política" para preguntas sin datos de vuelo
    familia = next((f for f in ("lite", "clasica", "flex") if f in n), None)
    if familia and "cambiar" in n and not any(o.nombre == "consultar_vuelo" for o in obs):
        return f"cambio de fecha tarifa {familia}: cuántos USD por tramo"
    if familia and ("reembolso" in n or "devuelv" in n):
        return f"reembolso voluntario condiciones por familia tarifaria {familia}"
    if "reclamar" in n and any(w in n for w in ("rompi", "rueda", "dano", "danad", "rot")):
        return "plazo en días para reclamar el daño del equipaje"
    for o in obs:
        if o.nombre != "consultar_vuelo" or not o.contenido.get("encontrado"):
            continue
        v = o.contenido
        if _tiene(consulta, _REEMBOLSO):
            return "reembolso involuntario cancelación del vuelo qué se devuelve"
        if "conexion" in n:
            return "conexión perdida vuelo de otra aerolínea reserva separada demora"
        if v["estado"] == "cancelado":
            if v["causa"] in ("meteorologica", "control_transito_aereo"):
                return "cancelación por causas extraordinarias meteorológicas compensación económica"
            return "compensación cancelación con poca anticipación"
        if v["demora_min"] >= 300:
            return "demora de 5 horas o más reembolso"
        if v["demora_min"] >= 240:
            return "asistencia demora 4 horas o más comida completa"
        if v["demora_min"]:
            return "asistencia según el tiempo de espera 2 horas o más refrigerio"
    return consulta


# ---------------------------------------------------------------------------
# Redacción (plantillas)
# ---------------------------------------------------------------------------
def _oraciones(texto: str) -> list[str]:
    salida = []
    lineas = [l.strip() for l in texto.splitlines()]
    for i, l in enumerate(lineas):
        if not l or set(l) <= set("|-: "):
            continue
        if l.startswith("|") and i + 1 < len(lineas) and set(lineas[i + 1]) <= set("|-: ") and lineas[i + 1]:
            continue                                   # encabezado de tabla
        if l.startswith("|"):
            celdas = [c.strip() for c in l.strip("|").split("|")]
            salida.append(f"{celdas[0]}: {', '.join(celdas[1:])}")
            continue
        salida += [p.strip(" -*") for p in re.split(r"(?<=[.:])\s+(?=[A-ZÁÉÍÓÚÑ¿])", l) if len(p.strip(" -*")) > 20]
    return salida


def _mejor_oracion(consulta: str, fragmentos: list[dict]) -> tuple[str, str] | None:
    terminos = set(tokenizar(consulta))
    mejor = None
    for f in fragmentos:
        for o in _oraciones(f["texto"]):
            if o.endswith(":"):                       # introduce una lista: sola no dice nada
                continue
            puntaje = len(terminos & set(tokenizar(o)))
            if puntaje and (mejor is None or puntaje > mejor[0]):
                mejor = (puntaje, o, f["id"])
    return (mejor[1], mejor[2]) if mejor else None


def _frase_vuelo(v: dict) -> str:
    base = f"El vuelo {v['codigo']} ({v['origen']} → {v['destino']}) del {v['fecha']}"
    causa = CAUSAS.get(v["causa"], v["causa"])
    if v["estado"] == "cancelado":
        return f"{base} está cancelado (causa informada: {causa})."
    if v["estado"] == "demorado":
        return (f"{base} está demorado {v['demora_min']} minutos: salida estimada {v['salida_estimada']} "
                f"(programada {v['salida_programada']}). Causa informada: {causa}.")
    extra = f", con {v['demora_min']} minutos de demora" if v["demora_min"] else ""
    estados = {"aterrizado": "aterrizó", "en_vuelo": "está en vuelo", "programado": "está programado",
               "embarcando": "está embarcando"}
    return f"{base} {estados.get(v['estado'], v['estado'])}{extra} (salida programada {v['salida_programada']})."


def _frase(o: Obs) -> str | None:
    c = o.contenido
    if o.error:
        if c.get("tipo") == "entrada":
            return f"{c['error']} ¿Me confirmás el dato?"
        if "timeout" in c["error"] or ":" not in c["error"]:
            return "No pude consultar el sistema en este momento."
        return f"No pude completar la consulta: {c['error'].split(': ', 1)[1]}."     # agente sin triage: lo cuenta todo
    if c.get("rechazado"):
        return c.get("detalle", "La operación no fue aprobada.")
    if o.nombre == "consultar_vuelo":
        return _frase_vuelo(c) if c.get("encontrado") else (
            f"No encuentro el vuelo {c['codigo_vuelo']} en la programación de OrbitAir. ¿Me confirmás el número?")
    if o.nombre == "rastrear_valija":
        if not c.get("encontrada"):
            return f"{c['detalle']} ¿Me confirmás el código?"
        estado = ESTADOS_VALIJA.get(c["estado"], c["estado"])
        pir = f" (reporte PIR {c['pir']})" if c["pir"] else ""
        sigue = "" if c["estado_final"] else " Todavía no es un estado final: te avisamos cuando haya novedades."
        return (f"Tu valija {c['codigo']} del vuelo {c['vuelo']} está {estado}{pir}: {c['ubicacion']}. "
                f"Última actualización: {c['actualizado']}.{sigue}")
    if o.nombre == "consultar_reserva":
        if not c.get("encontrada"):
            return f"{c['detalle']} ¿Me confirmás el código?"
        vuelos = ", ".join(f"{v['codigo']} {v['origen']}→{v['destino']} del {v['fecha']} ({v['estado']})"
                           for v in c["vuelos"])
        res = "; ".join(f"{r['id']} por USD {r['monto_usd']:.2f}: {r['estado']}" for r in c["reembolsos"])
        return (f"La reserva {c['codigo']} (familia {c['familia']}, clase {c['clase']}) incluye: {vuelos}."
                + (f" Reembolsos: {res}." if res else ""))
    if o.nombre == "iniciar_reembolso":
        if c.get("creado"):
            return (f"Inicié la solicitud de reembolso {c['id']} por USD {c['monto_usd']:.2f} para la reserva "
                    f"{c['reserva']}; estado: {c['estado']}.")
        return c.get("detalle")
    return None


def redactar(consulta: str, obs: list[Obs], faltante: str | None = None) -> str:
    n = _norm(consulta)
    if faltante == "valija":
        return "¿Me pasás la etiqueta de la valija (OA- + 6 dígitos) o el número de reporte PIR, así la busco?"
    if faltante == "vuelo":
        return "¿De qué vuelo me hablás? Pasame el código (OA + 4 dígitos) y lo consulto."
    partes = [f for o in obs if o.nombre != "buscar_politica" and (f := _frase(o))]
    pol = [o for o in obs if o.nombre == "buscar_politica" and not o.error]
    if pol and not any(o.contenido.get("tipo") == "entrada" for o in obs):
        mejor = _mejor_oracion(pol[-1].args["consulta"], pol[-1].contenido.get("fragmentos", []))
        demora = next((o.contenido["demora_min"] for o in obs if o.nombre == "consultar_vuelo"
                       and o.contenido.get("encontrado") and o.contenido["estado"] == "demorado"), 0)
        if mejor and 0 < demora < 120 and "asistencia" in pol[-1].args["consulta"]:
            partes.append(f"Con {demora} minutos de demora todavía no corresponde asistencia: empieza a partir "
                          f"de las 2 horas de espera.")
        if mejor:
            partes.append(f"Según la política: {mejor[0].rstrip('.')}. [{mejor[1]}]")
    if partes:
        return " ".join(dict.fromkeys(partes))
    if not _tiene(consulta, _DOMINIO):
        if re.fullmatch(r"\W*(hola|buen(os|as)? (dia|tardes|noches))\W*.*", n) and len(n) < 40:
            return "¡Hola! Soy el asistente de OrbitAir. ¿En qué te puedo ayudar con tu vuelo, tu equipaje o tu reserva?"
        return ("Solo puedo ayudarte con consultas sobre vuelos, equipaje, reservas y políticas de OrbitAir. "
                "¿Tenés alguna consulta sobre tu viaje?")
    return "No encontré información para responder eso. ¿Me das más detalles (código de vuelo, valija o reserva)?"
