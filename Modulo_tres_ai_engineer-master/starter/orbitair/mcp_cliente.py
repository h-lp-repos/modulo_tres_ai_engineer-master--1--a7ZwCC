"""C4 · El agente como CLIENTE MCP: descubre las herramientas del server y las usa con el triage de C1.

EJERCICIO 2 · Completar `spec_openai()` y `ClienteMCP.llamar()`.

El host (nuestro agente) lanza el server como proceso (stdio), le pasa la SESIÓN por el entorno
(qué pasajero, qué rol) y conversa con él por el protocolo:

    host ── initialize ─────────────────────────► server   (versión del protocolo, capacidades)
    host ── tools/list ─────────────────────────► server   → nombre, descripción, inputSchema, annotations
    host ── tools/call {name, arguments} ───────► server   → content (+ isError)
    host ── resources/read {uri} · prompts/get ─► server

El modelo no habla MCP: sigue recibiendo especificaciones de herramientas en formato OpenAI. El
cliente TRADUCE: tools/list → specs para el modelo (`spec_openai`), y tool_call del modelo →
tools/call al server → observación. Los errores del server vuelven tipados ([entrada],
[transitorio], [permisos], [sistema]) y se convierten en las excepciones de C1: el triage
(reintentar / informar al modelo / abortar) funciona igual que con las herramientas locales.

El SDK de MCP es asíncrono y los nodos del grafo son síncronos: `ClienteMCP` mantiene la sesión
abierta en un hilo con su propio event loop y expone métodos síncronos (ya resuelto).
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import threading
import time
from concurrent.futures import Future
from dataclasses import dataclass
from functools import partial
from pathlib import Path

from mcp import Client
from mcp.client.stdio import StdioServerParameters

from .errores import ErrorDeEntrada, ErrorDelSistema, ErrorDePermisos, ErrorTransitorio, ResultadoTool, ejecutar_con_triage
from .grafo import ConfigAgente
from .llm import MOCK, ToolCall
from .tools import specs
from .workers import DOMINIOS, AgenteWorker

PAQUETE = Path(__file__).resolve().parents[1]           # src/ (o starter/): desde ahí corre `-m orbitair.mcp_server`


@dataclass
class HerramientaMCP:
    nombre: str
    descripcion: str
    schema: dict
    solo_lectura: bool | None          # annotations.readOnlyHint: una PISTA del server, no una garantía
    salida: dict | None = None         # outputSchema: si la tool devuelve datos estructurados


# ---------------------------------------------------------------------------
# EJERCICIO 2 · De la tool MCP a la especificación que ve el modelo
# ---------------------------------------------------------------------------
def spec_openai(h: HerramientaMCP) -> dict:
    """{"type": "function", "function": {"name", "description", "parameters"}} con el inputSchema del server
    como `parameters`. Es la misma forma que `_spec` de tools.py (C1): el modelo no se entera del cambio."""
    # TODO (Ejercicio 2): return {"type": "function", "function": {"name": ..., "description": ..., "parameters": ...}}
    raise NotImplementedError("Ejercicio 2: de la tool MCP a la spec del modelo")


class ClienteMCP:
    """Una sesión MCP con el server de OrbitAir, para UN pasajero y UN rol. Métodos síncronos."""

    def __init__(self, pasajero_id: str, rol: str = "consulta", fallas: dict | None = None,
                 timeout_s: float = 20.0, modulo: str = "orbitair.mcp_server", con_sesion: bool = True):
        """`modulo`: qué server lanzar. `con_sesion=False` (C4 · Ej. 5): el server NO recibe el pasajero ni el rol;
        sólo lo mínimo para correr (un server de terceros no tiene por qué saber quién es el pasajero)."""
        self.pasajero_id, self.rol, self.timeout_s, self.modulo = pasajero_id, rol, timeout_s, modulo
        env = {k: v for k, v in os.environ.items() if not k.startswith("ORBITAIR_")}
        env["PYTHONIOENCODING"] = "utf-8"
        if con_sesion:
            env.update({"ORBITAIR_PASAJERO_ID": pasajero_id, "ORBITAIR_ROL": rol, "ORBITAIR_MOCK": "1" if MOCK else "0"})
        if fallas:
            env["ORBITAIR_FALLAS"] = json.dumps(fallas)
        self.parametros = StdioServerParameters(command=sys.executable, args=["-m", modulo], cwd=str(PAQUETE), env=env)
        self._pedidos: asyncio.Queue | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        listo: Future = Future()
        self._hilo = threading.Thread(target=lambda: asyncio.run(self._sesion(listo)), daemon=True)
        t0 = time.perf_counter()
        self._hilo.start()
        listo.result(timeout=timeout_s)            # propaga el error si el server no arrancó
        self.conexion_s = time.perf_counter() - t0
        self.herramientas = self._listar_herramientas()
        self.llamadas: list[tuple[str, float]] = []    # (herramienta, segundos) de cada tools/call

    # -- el puente async ↔ sync (ya resuelto) -------------------------------
    async def _sesion(self, listo: Future) -> None:
        try:
            async with Client(self.parametros) as cliente:
                self._loop, self._pedidos = asyncio.get_running_loop(), asyncio.Queue()
                listo.set_result(True)
                while (pedido := await self._pedidos.get()) is not None:
                    metodo, args, futuro = pedido
                    try:
                        futuro.set_result(await getattr(cliente, metodo)(*args))
                    except Exception as e:  # noqa: BLE001 — se re-lanza en el hilo que llamó
                        futuro.set_exception(e)
        except Exception as e:  # noqa: BLE001
            if not listo.done():
                listo.set_exception(ErrorDelSistema(f"el server MCP no arrancó o cortó la conexión "
                                                    f"({type(e).__name__}; el motivo está en su stderr)"))

    def _rpc(self, metodo: str, *args):
        if self._loop is None or not self._hilo.is_alive():
            raise ErrorDelSistema("la sesión MCP está cerrada")
        futuro: Future = Future()
        self._loop.call_soon_threadsafe(self._pedidos.put_nowait, (metodo, args, futuro))
        try:
            return futuro.result(timeout=self.timeout_s)
        except TimeoutError:
            raise ErrorTransitorio(f"el server MCP no respondió {metodo} en {self.timeout_s:.0f} s") from None

    def cerrar(self) -> None:
        if self._loop and self._hilo.is_alive():
            self._loop.call_soon_threadsafe(self._pedidos.put_nowait, None)
            self._hilo.join(timeout=10)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.cerrar()

    # -- primitivas ----------------------------------------------------------
    def _listar_herramientas(self) -> dict[str, HerramientaMCP]:
        r = self._rpc("list_tools")
        return {t.name: HerramientaMCP(t.name, " ".join((t.description or "").split()), t.input_schema,
                                       t.annotations.read_only_hint if t.annotations else None, t.output_schema)
                for t in r.tools}

    def specs(self, nombres: list[str] | None = None) -> list[dict]:
        return [spec_openai(h) for n, h in self.herramientas.items() if nombres is None or n in nombres]

    def recursos(self) -> list[str]:
        estaticos = [r.uri for r in self._rpc("list_resources").resources]
        plantillas = [t.uri_template for t in self._rpc("list_resource_templates").resource_templates]
        return [*map(str, estaticos), *plantillas]

    def leer_recurso(self, uri: str) -> str:
        return "".join(c.text for c in self._rpc("read_resource", uri).contents if hasattr(c, "text"))

    def prompts(self) -> list[str]:
        return [p.name for p in self._rpc("list_prompts").prompts]

    def prompt(self, nombre: str, argumentos: dict) -> list[dict]:
        r = self._rpc("get_prompt", nombre, argumentos)
        return [{"role": m.role, "content": m.content.text} for m in r.messages]

    # -----------------------------------------------------------------------
    # EJERCICIO 2 · tools/call y los errores tipados del server
    # -----------------------------------------------------------------------
    def llamar(self, nombre: str, argumentos: dict) -> dict:
        """Llama a la tool en el server y devuelve la observación (dict). Si el resultado viene con `is_error`,
        lanza la excepción de C1 que corresponde, para que el triage decida.
        Si salió bien: `r.structured_content` (los datos, si la tool tiene outputSchema); si no viene, el JSON del
        texto. `content` es para el modelo; `structured_content`, para el código.


        - texto con "[transitorio]" → ErrorTransitorio (se reintenta)
        - "[entrada]", o un error de validación del schema ("validation error"), o "Unknown tool" → ErrorDeEntrada
          (vuelve al modelo)
        - "[permisos]" → ErrorDePermisos (corta y deriva)
        - cualquier otra cosa ("[sistema]", un crash del server) → ErrorDelSistema (fail closed)
        El texto del resultado está en `r.content` (bloques con `.text`).
        Registrar en `self.llamadas` (nombre, segundos) cada llamada.
        """
        # TODO (Ejercicio 2):
        # t0 = time.perf_counter(); r = self._rpc("call_tool", nombre, argumentos)
        # self.llamadas.append((nombre, time.perf_counter() - t0))
        # texto = "".join(c.text for c in r.content if hasattr(c, "text"))
        # sin error → r.structured_content si no es None; si no, json.loads(texto) if texto else {}
        # con error → detalle = re.sub(r"^Error executing tool \w+: ", "", texto) y lanzar según la tabla del docstring
        raise NotImplementedError("Ejercicio 2: tools/call y los errores tipados")


# ---------------------------------------------------------------------------
# El worker que usa las herramientas del server (ya resuelto)
# ---------------------------------------------------------------------------
class AgenteConMCP(AgenteWorker):
    """Un worker de C3 cuyas herramientas de datos vienen del server MCP. `buscar_politica` sigue local (el
    retrieval del M2 es del host: el server publica los documentos como resources, no un buscador)."""

    def __init__(self, pasajero_id: str, nombre: str = "", cliente: ClienteMCP | None = None, **kwargs):
        if cliente is None or cliente.pasajero_id != pasajero_id:
            # Fail closed: la sesión MCP es de UN pasajero. Usarla para otro sería saltear los permisos.
            raise ErrorDePermisos("la sesión MCP no corresponde al pasajero de la conversación")
        super().__init__(pasajero_id, nombre, **kwargs)
        self.cliente = cliente
        remotas = [n for n in self.herramientas if n in cliente.herramientas]
        self.tools = cliente.specs(remotas) + specs([n for n in self.herramientas if n not in cliente.herramientas])

    def ejecutar(self, tc: ToolCall, dormir=time.sleep) -> ResultadoTool:
        if tc.nombre in self.cliente.herramientas:
            return ejecutar_con_triage(lambda: self.cliente.llamar(tc.nombre, tc.argumentos), dormir=dormir)
        return super().ejecutar(tc, dormir)            # buscar_politica: el retrieval local del M2


def config_worker_mcp(dominio: str, cliente: ClienteMCP) -> ConfigAgente:
    """El worker de `dominio` sobre MCP. Mínimo privilegio en DOS capas: las herramientas del dominio (C3) que
    además el server le da a esta sesión según su rol (C4) + buscar_politica (local)."""
    d = DOMINIOS[dominio]
    herramientas = [h for h in (*d.herramientas, *d.acciones) if h in cliente.herramientas]
    return ConfigAgente(herramientas=[*herramientas, "buscar_politica"],
                        fabrica=partial(AgenteConMCP, dominio=dominio, cliente=cliente))


# ---------------------------------------------------------------------------
# Un host con varios servers (C4 · Ejercicio 5, ya resuelto)
# ---------------------------------------------------------------------------
_SOSPECHOSO = [r"<\s*important", r"ignor[aá]", r"antes de responder", r"no (le )?(menciones|digas)",
               r"\bsiempre\b", r"api[_ ]?key", r"\.env\b", r"contraseña|password"]


def revisar_herramienta(h: HerramientaMCP, otras: set[str]) -> list[str]:
    """Alertas sobre la descripción de una tool ANTES de mostrársela al modelo: menciona otras herramientas,
    trae instrucciones imperativas o etiquetas ocultas, o es sospechosamente larga. Es una red, no una
    garantía: la defensa real es no conectar servers que no se revisaron y no darles más permisos de los que
    necesitan."""
    texto = f"{h.descripcion} {json.dumps(h.schema, ensure_ascii=False)}"
    alertas = [f"menciona la herramienta '{o}'" for o in sorted(otras) if o != h.nombre and o in texto]
    alertas += [f"patrón sospechoso: /{p}/" for p in _SOSPECHOSO if re.search(p, texto, re.I)]
    if len(h.descripcion) > 600:
        alertas.append(f"descripción de {len(h.descripcion)} caracteres")
    return alertas


def combinar_herramientas(clientes: dict[str, ClienteMCP], permitidas: dict[str, set[str]] | None = None,
                          prefijo: bool = True) -> dict[str, tuple[ClienteMCP, HerramientaMCP]]:
    """Junta las tools de varios servers. `prefijo=True`: nombre `<server>__<tool>` (sin colisiones).
    `permitidas`: allowlist por server; una tool que no está, no llega al modelo."""
    todas: dict[str, tuple[ClienteMCP, HerramientaMCP]] = {}
    for servidor, cliente in clientes.items():
        for nombre, h in cliente.herramientas.items():
            if permitidas is not None and nombre not in permitidas.get(servidor, set()):
                continue
            todas[f"{servidor}__{nombre}" if prefijo else nombre] = (cliente, h)
    return todas
