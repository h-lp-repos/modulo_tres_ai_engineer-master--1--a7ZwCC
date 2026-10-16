"""C1 · Triage de errores: recuperables vs duros.

EJERCICIO 4 · Completar `clasificar_error()` y `ejecutar_con_triage()`.

Cuando una herramienta falla, el agente tiene tres salidas posibles, y elegir mal
cuesta caro en las tres direcciones:

| Decisión              | Para qué errores                         | Quién se entera                 |
|-----------------------|------------------------------------------|---------------------------------|
| REINTENTAR            | transitorios: timeout, sistema ocupado   | nadie: el harness reintenta     |
| INFORMAR_AL_MODELO    | de entrada: código mal escrito, formato  | el modelo, como observación     |
| ABORTAR               | duros: sin permiso, sistema caído        | el pasajero (derivación humana) |

- Reintentar un error de entrada no sirve (va a fallar igual) y mandarle al modelo un
  timeout lo hace "reintentar" gastando un paso de LLM (tokens) en algo que el
  harness resuelve sin costo.
- Informar al modelo un error duro es peligroso: un "no tenés permiso" que vuelve
  como observación invita al modelo a probar otra cosa (otra tool, otro código) para
  conseguir el dato. El permiso se hace cumplir en el CÓDIGO, no en el prompt.
- Abortar ante un error de entrada deja al pasajero sin respuesta por un typo.

Ante un error desconocido: ABORTAR (fail closed). Mejor derivar a un humano que
improvisar con un estado que no entendemos.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable

REINTENTAR = "reintentar"
INFORMAR_AL_MODELO = "informar_al_modelo"
ABORTAR = "abortar"


class ErrorRecuperable(Exception):
    """El agente puede seguir."""


class ErrorTransitorio(ErrorRecuperable):
    """Timeout, sistema ocupado: la misma llamada, un rato después, probablemente funcione."""


class ErrorDeEntrada(ErrorRecuperable):
    """Argumentos inválidos. Reintentar igual no sirve; el modelo puede corregirlos o preguntarle al pasajero."""


class ErrorDuro(Exception):
    """El agente no debe seguir: hay que cortar y derivar."""


class ErrorDePermisos(ErrorDuro):
    """El dato existe pero no es de este pasajero. Nunca vuelve al modelo con detalles."""


class ErrorDelSistema(ErrorDuro):
    """Sistema caído, o un transitorio que no se recuperó después de los reintentos."""


@dataclass
class Intento:
    numero: int
    error: str | None
    espera_s: float = 0.0


@dataclass
class ResultadoTool:
    ok: bool
    contenido: dict                       # lo que vuelve al modelo como observación
    decision: str | None = None           # None si salió bien al primer intento
    intentos: list[Intento] = field(default_factory=list)
    error_duro: ErrorDuro | Exception | None = None


# ---------------------------------------------------------------------------
# EJERCICIO 4 · Clasificar el error
# ---------------------------------------------------------------------------
def clasificar_error(e: Exception) -> str:
    """REINTENTAR, INFORMAR_AL_MODELO o ABORTAR, según el tipo de error (ver la tabla del docstring)."""
    # TODO: ErrorTransitorio → REINTENTAR · ErrorDeEntrada → INFORMAR_AL_MODELO · cualquier otro → ABORTAR
    raise NotImplementedError("Ejercicio 4: clasificar el error")


# ---------------------------------------------------------------------------
# EJERCICIO 4 · Ejecutar una herramienta con triage
# ---------------------------------------------------------------------------
def ejecutar_con_triage(fn: Callable[[], dict], max_reintentos: int = 2, espera_base_s: float = 0.2,
                        dormir: Callable[[float], None] = time.sleep) -> ResultadoTool:
    """Ejecuta `fn()` (la herramienta ya con sus argumentos) y decide qué hacer si falla.

    - REINTENTAR: hasta `max_reintentos` veces más, con backoff exponencial (0.2 s, 0.4 s...).
      Si se agotan, el transitorio pasa a ser duro (ErrorDelSistema).
    - INFORMAR_AL_MODELO: ok=False y contenido {"error": str(e), "tipo": "entrada"}.
    - ABORTAR: ok=False, contenido {"error": "..."} SIN detalles y `error_duro` = la excepción.
    """
    # TODO (Ejercicio 4): reemplazar la versión provisoria de abajo por el triage del docstring.
    # for n in range(max_reintentos + 1):
    #     try: contenido = fn() → registrar Intento(n + 1, None) → ResultadoTool(True, contenido,
    #          REINTENTAR if n else None, intentos)
    #     except Exception as e:
    #         decision = clasificar_error(e)
    #         - REINTENTAR y n < max_reintentos: Intento(n + 1, error, espera), dormir(espera_base_s * 2 ** n), continue
    #         - INFORMAR_AL_MODELO: ResultadoTool(False, {"error": str(e), "tipo": "entrada"}, decision, intentos)
    #         - ABORTAR, o REINTENTAR sin intentos (→ ErrorDelSistema): ResultadoTool(False, {"error": "No se pudo
    #           completar la operación."}, ABORTAR, intentos, <el error duro>)
    #
    # Provisorio (Ejercicios 1-3): SIN triage, cualquier error vuelve al modelo como texto.
    try:
        return ResultadoTool(True, fn(), None, [Intento(1, None)])
    except Exception as e:  # noqa: BLE001
        return ResultadoTool(False, {"error": f"{type(e).__name__}: {e}"}, INFORMAR_AL_MODELO,
                             [Intento(1, f"{type(e).__name__}: {e}")])
