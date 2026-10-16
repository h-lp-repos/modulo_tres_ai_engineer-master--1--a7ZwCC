"""C4 · El server MCP de OrbitAir: la base de operaciones detrás del protocolo.

EJERCICIO 1 · Completar `registrar_consultar_vuelo()`, `registrar_politicas()` y `registrar_prompts()`.
EJERCICIO 3 · Completar `herramientas_permitidas()` y `ejecutar_auditado()` (permisos y auditoría).

Hasta C3 las herramientas eran funciones Python que el agente importaba (orbitair/tools.py).
Con MCP (Model Context Protocol) pasan a vivir en un PROCESO APARTE que cualquier host
(nuestro agente, Claude Desktop, un IDE, otro equipo) descubre y usa con el mismo protocolo
(JSON-RPC sobre stdio o HTTP). El server expone tres cosas, cada una controlada por alguien distinto:

| primitiva | qué es                                      | quién decide usarla         | en OrbitAir                       |
|-----------|---------------------------------------------|-----------------------------|-----------------------------------|
| tools     | funciones con efectos o consultas           | el MODELO (tool calling)    | consultar_vuelo, rastrear_valija, |
|           |                                             |                             | consultar_reserva, iniciar_reembolso |
| resources | datos para leer, por URI                    | la APLICACIÓN (el host)     | politica://POL-EQ-01, pasajero://sesion |
| prompts   | plantillas de mensajes con argumentos       | el USUARIO (ej. un comando) | reclamo_equipaje, seguimiento_reembolso |

El SDK (`mcp` 2.x, `MCPServer`) arma el JSON Schema de cada tool a partir de los type hints y
del docstring: la firma de la función ES el contrato que ve el modelo. El tipo de retorno (un TypedDict)
es el outputSchema: el resultado llega como texto para el modelo y como `structured_content` para el código.

Seguridad (Ejercicio 3) — el server no confía en el cliente ni en el modelo:
- El PASAJERO sale de la sesión (variable de entorno que pone el host al lanzar el server; con
  HTTP sería el token OAuth), nunca de un argumento. Igual que en C1, pero ahora del lado del server.
- El ROL de la sesión decide qué tools existen: una tool no permitida no se registra (no se lista
  y no se puede llamar). Mínimo privilegio, como los workers de C3, pero impuesto por el server.
- Inputs validados (schema + normalización de códigos en operaciones.py) y errores traducidos a
  categorías ([entrada], [transitorio], [permisos], [sistema]) para que el triage del cliente siga
  funcionando. Un error de permisos no da detalles; un crash no filtra nada ("Error executing tool").
- Cada llamada queda AUDITADA (results/c4_auditoria.jsonl): quién, qué, con qué y cómo terminó.
- Tope de llamadas por sesión: un agente desbocado no barre la base.

Se lanza como proceso:  python -m orbitair.mcp_server   (desde src/, con las variables de la sesión)
"""
from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Annotated, Callable, Literal, TypedDict

from pydantic import Field

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from . import operaciones
from .corpus import cargar_documentos
from .errores import ErrorDeEntrada, ErrorDePermisos, ErrorTransitorio

RESULTS = Path(__file__).resolve().parents[2] / "results"
AUDITORIA = RESULTS / "c4_auditoria.jsonl"
MAX_LLAMADAS_SESION = 40

TODAS = ["consultar_vuelo", "rastrear_valija", "consultar_reserva", "iniciar_reembolso"]
ROLES = {
    "consulta": "sólo lectura: vuelos, valijas y reservas del pasajero",
    "reembolsos": "lectura + iniciar_reembolso (la aprobación humana la hace el host)",
}
INSTRUCCIONES = ("Sistemas de operaciones de OrbitAir: vuelos, valijas, reservas y reembolsos del pasajero de la "
                 "sesión. Las políticas oficiales están como resources (politica://<código>).")


class Sesion:
    """Lo que el server sabe de quién lo usa. Sale del entorno del proceso, no de los mensajes."""

    def __init__(self, pasajero_id: str, rol: str):
        self.pasajero_id = pasajero_id
        self.rol = rol
        self.llamadas = 0


def sesion_desde_entorno() -> Sesion:
    """Fail closed: sin pasajero válido o con un rol desconocido, el server no arranca."""
    pasajero_id = os.environ.get("ORBITAIR_PASAJERO_ID", "")
    rol = os.environ.get("ORBITAIR_ROL", "consulta")
    if not operaciones.pasajero(pasajero_id):
        raise SystemExit(f"[server MCP] sesión inválida: pasajero '{pasajero_id}' desconocido")
    if rol not in ROLES:
        raise SystemExit(f"[server MCP] rol desconocido: '{rol}'")
    return Sesion(pasajero_id, rol)


# ---------------------------------------------------------------------------
# EJERCICIO 3 · Qué herramientas existen para cada rol
# ---------------------------------------------------------------------------
def herramientas_permitidas(rol: str) -> list[str]:
    """"consulta": las tres de lectura. "reembolsos": las de lectura que usa ese dominio (consultar_vuelo,
    consultar_reserva) + iniciar_reembolso. Cualquier otro rol: ninguna (fail closed)."""
    # TODO (Ejercicio 3): un dict rol → lista de tools; rol desconocido → [] (fail closed).
    # Provisorio hasta el Ejercicio 3: todos los roles ven todas las tools (TODAS).
    return list(TODAS)


# ---------------------------------------------------------------------------
# EJERCICIO 3 · Ejecutar con permisos, traducción de errores y auditoría
# ---------------------------------------------------------------------------
def auditar(sesion: Sesion, herramienta: str, argumentos: dict, resultado: str) -> None:
    RESULTS.mkdir(exist_ok=True)
    with open(AUDITORIA, "a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "pasajero": sesion.pasajero_id,
                            "rol": sesion.rol, "herramienta": herramienta, "argumentos": argumentos,
                            "resultado": resultado}, ensure_ascii=False) + "\n")


def ejecutar_auditado(sesion: Sesion, herramienta: str, argumentos: dict, fn: Callable[[], dict]) -> dict:
    """Corre `fn()` (la operación, ya con el pasajero de la sesión) y deja todo auditado.

    1. Si la herramienta no está en `herramientas_permitidas(sesion.rol)` → auditar "denegada" y
       `ToolError("[permisos] operación no permitida")` (defensa en profundidad: no debería estar registrada).
    2. Si `sesion.llamadas` llegó a MAX_LLAMADAS_SESION → auditar "limite" y `ToolError("[sistema] ...")`;
       si no, sumar 1.
    3. Ejecutar y traducir las excepciones de operaciones.py a ToolError con la categoría entre corchetes:
       ErrorDeEntrada → "[entrada] <mensaje>" · ErrorTransitorio → "[transitorio] <mensaje>"
       ErrorDePermisos → "[permisos] operación no permitida" (SIN el detalle: no confirmar que el dato existe)
       cualquier otra → "[sistema] el sistema no está disponible".
    4. Auditar "ok" o el tipo de error, y devolver el resultado.
    """
    # TODO (Ejercicio 3), en este orden:
    # 1. herramienta no permitida para sesion.rol → auditar(..., "denegada"); raise ToolError("[permisos] ...")
    # 2. sesion.llamadas >= MAX_LLAMADAS_SESION → auditar(..., "limite"); raise ToolError("[sistema] ...")
    #    si no: sesion.llamadas += 1
    # 3. try: resultado = fn()
    #    except ErrorDeEntrada as e:   auditar "entrada";     raise ToolError(f"[entrada] {e}") from None
    #    except ErrorTransitorio as e: auditar "transitorio"; raise ToolError(f"[transitorio] {e}") from None
    #    except ErrorDePermisos:       auditar "permisos";    raise ToolError("[permisos] operación no permitida")
    #    except Exception:             auditar "sistema";     raise ToolError("[sistema] el sistema no está disponible")
    # 4. auditar(..., "ok") y return resultado
    # Provisorio hasta el Ejercicio 3: sin permisos, sin auditoría y sin traducir errores (cualquier error
    # de operaciones.py le llega al cliente como un crash: "Error executing tool <nombre>").
    return fn()


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------
CodigoVuelo = Annotated[str, Field(description="Código del vuelo: 'OA' + 4 dígitos, ej. OA1203.", max_length=20)]


# Salidas TIPADAS: con un TypedDict como tipo de retorno, el SDK publica un outputSchema y cada resultado
# llega al cliente también como `structured_content` (datos para el código), además del texto para el
# modelo. Con `-> dict` no hay salida estructurada. total=False: los campos dependen de si se encontró o no.
class EstadoVuelo(TypedDict, total=False):
    encontrado: bool
    codigo: str
    codigo_vuelo: str
    fecha: str | None
    origen: str
    destino: str
    salida_programada: str
    salida_estimada: str
    estado: str
    demora_min: int | None
    causa: str
    aviso_cancelacion: str
    distancia_km: int | None
    consultado_el: str
    detalle: str


class EstadoValija(TypedDict, total=False):
    encontrada: bool
    codigo: str
    vuelo: str
    fecha: str
    estado: str
    ubicacion: str
    pir: str
    actualizado: str
    estado_final: bool
    detalle: str


class DatosReserva(TypedDict, total=False):
    encontrada: bool
    codigo: str
    codigo_reserva: str
    familia: str
    clase: str
    monto_usd: float
    medio_pago: str
    vuelos: list[dict]
    reembolsos: list[dict]
    detalle: str


class SolicitudReembolso(TypedDict, total=False):
    creado: bool
    id: str
    reserva: str
    motivo: str
    monto_usd: float
    estado: str
    medio_pago: str
    detalle: str


# EJERCICIO 1 · La primera tool
def registrar_consultar_vuelo(server: MCPServer, sesion: Sesion) -> None:
    """Registrar la tool `consultar_vuelo(codigo_vuelo, fecha=None) -> dict` con `@server.tool(...)`.

    - El docstring de la función es la descripción que lee el modelo (la de tools.py en C1).
    - Los type hints son el schema: `codigo_vuelo: CodigoVuelo`, `fecha: str | None = None` (con un Field
      que diga el formato AAAA-MM-DD), y el tipo de retorno `EstadoVuelo` es el outputSchema (salida estructurada).
    - `annotations=ToolAnnotations(readOnlyHint=True)`: sólo lee. Son PISTAS para el host, no garantías.
    - El cuerpo: `ejecutar_auditado(sesion, "consultar_vuelo", {...}, lambda: operaciones.consultar_vuelo(...))`.
    Ojo: `pasajero_id` NO es parámetro (y consultar_vuelo es información pública: no lo necesita).
    """
    # TODO (Ejercicio 1):
    # @server.tool(annotations=ToolAnnotations(readOnlyHint=True))
    # def consultar_vuelo(codigo_vuelo: CodigoVuelo,
    #                     fecha: Annotated[str | None, Field(description="Fecha AAAA-MM-DD...", max_length=10)] = None
    #                     ) -> EstadoVuelo:
    #     """<la descripción para el modelo: qué devuelve y cuándo usarla>"""
    #     return ejecutar_auditado(sesion, "consultar_vuelo", {"codigo_vuelo": codigo_vuelo, "fecha": fecha},
    #                              lambda: operaciones.consultar_vuelo(codigo_vuelo, fecha))
    raise NotImplementedError("Ejercicio 1: la tool consultar_vuelo")


def registrar_herramientas(server: MCPServer, sesion: Sesion) -> list[str]:
    """Registra SÓLO las tools del rol de la sesión (Ejercicio 3). Devuelve sus nombres."""
    permitidas = herramientas_permitidas(sesion.rol)
    pid = sesion.pasajero_id

    if "consultar_vuelo" in permitidas:
        registrar_consultar_vuelo(server, sesion)

    if "rastrear_valija" in permitidas:
        @server.tool(annotations=ToolAnnotations(readOnlyHint=True))
        def rastrear_valija(codigo: Annotated[str, Field(
                description="Etiqueta de la valija ('OA-' + 6 dígitos, ej. OA-582331) o número PIR (aeropuerto + "
                            "5 dígitos, ej. LIM-48213).", max_length=20)]) -> EstadoValija:
            """Estado y ubicación de una valija despachada del pasajero, por su etiqueta o por el número de reporte
            PIR. Devuelve estado (en tránsito, demorada, en búsqueda, entregada, perdida...), ubicación, vuelo y
            última actualización."""
            return ejecutar_auditado(sesion, "rastrear_valija", {"codigo": codigo},
                                     lambda: operaciones.rastrear_valija(codigo, pid))

    if "consultar_reserva" in permitidas:
        @server.tool(annotations=ToolAnnotations(readOnlyHint=True))
        def consultar_reserva(codigo_reserva: Annotated[str, Field(
                description="Código de reserva de 6 caracteres, ej. M4TR88.", max_length=20)]) -> DatosReserva:
            """Datos de una reserva del pasajero: vuelos, familia tarifaria y clase, monto pagado, medio de pago y
            reembolsos asociados con su estado."""
            return ejecutar_auditado(sesion, "consultar_reserva", {"codigo_reserva": codigo_reserva},
                                     lambda: operaciones.consultar_reserva(codigo_reserva, pid))

    if "iniciar_reembolso" in permitidas:
        @server.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False))
        def iniciar_reembolso(
                codigo_reserva: Annotated[str, Field(description="Código de reserva de 6 caracteres.", max_length=20)],
                motivo: Annotated[Literal[tuple(operaciones.MOTIVOS_REEMBOLSO)], Field(
                    description="Motivo del reembolso según la política.")],
                monto_usd: Annotated[float | None, Field(
                    gt=0, le=10000, description="Monto a reembolsar. Omitir: el total pagado.")] = None) -> SolicitudReembolso:
            """Inicia una solicitud de reembolso para una reserva del pasajero. Tiene efectos: crea el trámite. Usarla
            sólo si el pasajero pide el reembolso explícitamente y la política lo permite para su caso."""
            args = {"codigo_reserva": codigo_reserva, "motivo": motivo, "monto_usd": monto_usd}
            return ejecutar_auditado(sesion, "iniciar_reembolso", args,
                                     lambda: operaciones.iniciar_reembolso(codigo_reserva, motivo, pid, monto_usd))
    return permitidas


# ---------------------------------------------------------------------------
# EJERCICIO 1 · Resources: las políticas, por URI
# ---------------------------------------------------------------------------
def registrar_politicas(server: MCPServer, sesion: Sesion) -> None:
    """Dos resources:
    - plantilla `politica://{codigo}` (mime "text/markdown"): el documento completo (`cargar_documentos()`, por
      `doc.codigo`). Código desconocido → `ValueError` con los códigos válidos. No se arma un path con el
      parámetro: se busca en un dict (así "../../.env" no lee nada).
    - estático `pasajero://sesion` (JSON): el pasajero de ESTA sesión (id, nombre, socio Plus). Un resource
      también depende de la sesión.
    """
    # TODO (Ejercicio 1):
    # docs = {d.codigo: d for d in cargar_documentos()}
    # @server.resource("politica://{codigo}", mime_type="text/markdown")
    # def politica(codigo: str) -> str:   docstring; código desconocido → ValueError; si no → docs[codigo].texto
    # @server.resource("pasajero://sesion", mime_type="application/json")
    # def pasajero_de_la_sesion() -> str: json.dumps({"id", "nombre", "socio_plus"}) de operaciones.pasajero(...)
    raise NotImplementedError("Ejercicio 1: los resources")


# ---------------------------------------------------------------------------
# EJERCICIO 1 · Prompts: plantillas que elige el usuario
# ---------------------------------------------------------------------------
def registrar_prompts(server: MCPServer, sesion: Sesion) -> None:
    """Dos prompts (el texto que devuelven es el mensaje `user` que el host le manda al modelo):
    - `reclamo_equipaje(pir)`: pedir el estado de la valija con ese PIR y armar el reclamo según POL-EQ-01
      (gastos de primera necesidad, plazos, documentación).
    - `seguimiento_reembolso(codigo_reserva)`: estado de los reembolsos de la reserva y plazo de acreditación
      según su medio de pago (POL-RE-01 §6).
    """
    # TODO (Ejercicio 1):
    # @server.prompt()
    # def reclamo_equipaje(pir: Annotated[str, Field(description="Número PIR, ej. LIM-48213.")]) -> str:
    #     """<descripción>"""
    #     return f"Mi valija tiene el reporte PIR {pir}. Consultá su estado y, según ... (POL-EQ-01) ..."
    # @server.prompt()
    # def seguimiento_reembolso(codigo_reserva: ...) -> str: ...
    raise NotImplementedError("Ejercicio 1: los prompts")


# ---------------------------------------------------------------------------
# Armar y lanzar
# ---------------------------------------------------------------------------
def crear_server(sesion: Sesion) -> MCPServer:
    server = MCPServer("orbitair-operaciones", instructions=INSTRUCCIONES, version="1.0",
                       log_level="WARNING")
    registrar_herramientas(server, sesion)
    registrar_politicas(server, sesion)
    registrar_prompts(server, sesion)
    return server


def main() -> None:
    # stdout es el canal del protocolo: los logs van a un archivo, nunca a stdout.
    RESULTS.mkdir(exist_ok=True)
    logging.basicConfig(filename=RESULTS / "c4_mcp_server.log", level=logging.INFO, force=True,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if os.environ.get("ORBITAIR_FALLAS"):          # C4 · Ej. 2: fallas inyectadas, como en C1 · Ej. 4
        for operacion, fallas in json.loads(os.environ["ORBITAIR_FALLAS"]).items():
            operaciones.inyectar_fallas(operacion, fallas)
    crear_server(sesion_desde_entorno()).run()      # transporte stdio


if __name__ == "__main__":
    main()
