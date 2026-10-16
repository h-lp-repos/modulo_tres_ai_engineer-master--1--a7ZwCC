"""C3 · Los workers: el agente de C2, especializado por dominio.

EJERCICIO 1 · Completar `AgenteWorker.ejecutar()` y `config_worker()`.

En el patrón orquestador-workers, un WORKER es un agente con un alcance acotado. No hace
falta inventar uno nuevo: es el grafo de C2 (control → agente → herramientas…, con sus
stopping rules, su triage y su aprobación humana) con tres cosas distintas:

1. Un PROMPT de especialista: sabe de un dominio y responde sólo su parte de la consulta.
2. MENOS HERRAMIENTAS: sólo las de su dominio (mínimo privilegio). El worker de equipaje no
   puede iniciar un reembolso aunque el modelo lo intente: la herramienta no existe para él.
3. Su RETRIEVAL FILTRADO: `buscar_politica` busca sólo en el documento de su dominio, con la
   búsqueda híbrida del M2 (orbitair/retrieval.py). Mismo contrato para el modelo.

Los dominios son las categorías del contrato del M1 (equipaje / cambios / reembolsos / otros),
y cada uno tiene su documento de política del M2:

| dominio    | documento | herramientas de datos                                                   |
|------------|-----------|-------------------------------------------------------------------------|
| equipaje   | POL-EQ-01 | rastrear_valija, consultar_reserva (la franquicia depende de la tarifa)  |
| cambios    | POL-TC-01 | consultar_vuelo, consultar_reserva                                      |
| reembolsos | POL-RE-01 | consultar_reserva, consultar_vuelo (+ iniciar_reembolso, con aprobación) |
| otros      | —         | no tiene worker: lo responde el orquestador sin LLM                      |
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from functools import partial

from . import retrieval
from .agente import Agente
from .errores import ErrorDeEntrada, ResultadoTool, ejecutar_con_triage
from .grafo import ConfigAgente
from .llm import ToolCall
from .tools import HERRAMIENTAS_C1


@dataclass(frozen=True)
class Dominio:
    nombre: str
    documento: str                 # código del documento de política (filtro del retrieval)
    herramientas: tuple[str, ...]  # herramientas de datos (sin buscar_politica, que tienen todos)
    acciones: tuple[str, ...]      # herramientas con efectos: sólo si el worker se arma con acciones=True
    descripcion: str               # lo que lee el router para decidir (orbitair/orquestador.py)


DOMINIOS: dict[str, Dominio] = {
    "equipaje": Dominio(
        "equipaje", "POL-EQ-01", ("rastrear_valija", "consultar_reserva"), (),
        "Valijas y equipaje: dónde está una valija, equipaje demorado, perdido o dañado, reclamos PIR, gastos de "
        "primera necesidad, indemnización por pérdida, franquicia (equipaje de mano, facturado, artículo "
        "personal), sobrepeso, exceso, mascotas y equipaje especial."),
    "cambios": Dominio(
        "cambios", "POL-TC-01", ("consultar_vuelo", "consultar_reserva"), (),
        "Vuelos, reservas, tarifas y cambios: estado u horario de un vuelo, datos de una reserva, familias "
        "tarifarias, cambios voluntarios (cargos, diferencia tarifaria), cambios involuntarios y "
        "reprogramaciones, opciones ante una cancelación, conexiones perdidas, no show, cambios de nombre."),
    "reembolsos": Dominio(
        "reembolsos", "POL-RE-01", ("consultar_reserva", "consultar_vuelo"), ("iniciar_reembolso",),
        "Reembolsos y compensaciones: devolución del dinero (voluntario o involuntario), estado de un reembolso, "
        "plazos de acreditación por medio de pago, vouchers, compensación económica por cancelación o "
        "sobreventa, asistencia por demoras (refrigerio, comida, hotel) y reintegro de gastos por demora del vuelo."),
}

SISTEMA_WORKER = """

Sos el especialista en {dominio} del equipo de atención de OrbitAir. Un orquestador te asigna una parte de la
consulta del pasajero: respondé SÓLO esa parte, usando tus herramientas. Otros especialistas responden el resto y
después se combinan las respuestas, así que no te disculpes por lo que no es tuyo ni lo menciones.
Tus políticas son las de {documento}: buscá ahí con buscar_politica y citá el id del fragmento."""


# ---------------------------------------------------------------------------
# El worker
# ---------------------------------------------------------------------------
class AgenteWorker(Agente):
    """El Agente de C1/C2 con el alcance de un dominio. `dominio=None`: generalista (todo el corpus)."""

    def __init__(self, pasajero_id: str, nombre: str = "", dominio: str | None = None, retrieval_modo: str = "hibrida",
                 **kwargs):
        super().__init__(pasajero_id, nombre, **kwargs)
        self.dominio = DOMINIOS[dominio] if dominio else None
        self.documentos = [self.dominio.documento] if self.dominio else None
        self.retrieval_modo = retrieval_modo
        if self.dominio:
            self.sistema += SISTEMA_WORKER.format(dominio=self.dominio.nombre, documento=self.dominio.documento)

    # -----------------------------------------------------------------------
    # EJERCICIO 1 · buscar_politica con el retrieval del M2, filtrado por documento
    # -----------------------------------------------------------------------
    def ejecutar(self, tc: ToolCall, dormir=time.sleep) -> ResultadoTool:
        """Igual que `Agente.ejecutar` (C1), salvo `buscar_politica`, que va a `retrieval.buscar` con
        `documentos=self.documentos` y `modo=self.retrieval_modo`.

        - Validar los argumentos como lo hace `ejecutar_tool`: sólo acepta `consulta` (string, no vacío);
          si no, ErrorDeEntrada (el triage lo devuelve al modelo).
        - Pasar por `ejecutar_con_triage(fn, dormir=dormir)`, como cualquier herramienta.
        - Devolver {"fragmentos": [...]} (el mismo contrato que en C1-C2).
        """
        # TODO:
        # if tc.nombre != "buscar_politica": return super().ejecutar(tc, dormir)
        # def buscar() -> dict:
        #     validar: sólo la clave "consulta", string no vacío (si no → raise ErrorDeEntrada("..."))
        #     return {"fragmentos": retrieval.buscar(consulta, documentos=self.documentos, modo=self.retrieval_modo)}
        # return ejecutar_con_triage(buscar, dormir=dormir)
        raise NotImplementedError("Ejercicio 1: buscar_politica filtrada por documento")


# ---------------------------------------------------------------------------
# EJERCICIO 1 · La configuración de cada worker
# ---------------------------------------------------------------------------
def config_worker(dominio: str | None, acciones: bool = False, retrieval_modo: str = "hibrida") -> ConfigAgente:
    """La ConfigAgente de C2 para el worker de `dominio`.

    - herramientas: las de datos del dominio + "buscar_politica" (+ las `acciones` si acciones=True).
    - fabrica: `partial(AgenteWorker, dominio=dominio, retrieval_modo=retrieval_modo)`.
    `dominio=None` arma el GENERALISTA (C3 · Ej. 4): las 4 herramientas de C1 y el retrieval híbrido sobre todo
    el corpus. Es el agente único de C2 con el mismo retrieval que los workers, para comparar arquitecturas
    sin mezclar otra variable.
    """
    # TODO:
    # dominio None → herramientas = list(HERRAMIENTAS_C1)
    # si no: d = DOMINIOS[dominio]; herramientas = [*d.herramientas, "buscar_politica", *(d.acciones si acciones)]
    # return ConfigAgente(herramientas=herramientas,
    #                     fabrica=partial(AgenteWorker, dominio=dominio, retrieval_modo=retrieval_modo))
    raise NotImplementedError("Ejercicio 1: la configuración del worker")
