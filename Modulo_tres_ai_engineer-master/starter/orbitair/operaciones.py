"""La base de operaciones de OrbitAir: vuelos, reservas, valijas y reembolsos (SQLite mock).

Ya resuelto. Es el "sistema externo" que consultan las herramientas del agente
(orbitair/tools.py). En C4 estas mismas funciones quedan detrás de un server MCP.

- Los datos salen de data/ops/*.csv (generados por data/ops/generar_ops.py: ~60
  vuelos, ~120 reservas, 200 valijas, 40 reembolsos en distintos estados). La base
  SQLite se arma desde los CSV la primera vez, en results/orbitair_ops.db.
- "Hoy" es 2026-10-01 para el agente (`HOY`).
- Cada consulta valida sus argumentos y el PERMISO: el pasajero de la sesión sólo
  ve sus reservas y sus valijas. Esa regla vive acá, en el código, no en el prompt.
- `inyectar_fallas()` simula un sistema inestable (timeouts, caída) para el
  Ejercicio 4 de C1: los errores se ven igual que los de un sistema real.
"""
from __future__ import annotations

import csv
import re
import sqlite3
from collections import defaultdict
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from typing import Iterator

from .errores import ErrorDeEntrada, ErrorDelSistema, ErrorDePermisos, ErrorTransitorio

ROOT = Path(__file__).resolve().parents[2]
CSV_DIR = ROOT / "data" / "ops"
DB_PATH = ROOT / "results" / "orbitair_ops.db"
HOY = "2026-10-01"

TABLAS = ["pasajeros", "vuelos", "reservas", "valijas", "reembolsos"]
_NUMERICAS = {"demora_min": int, "distancia_km": int, "monto_usd": float}

MOTIVOS_REEMBOLSO = ["cancelacion_involuntaria", "demora_mas_5h", "arrepentimiento_24h", "voluntario_flex",
                     "servicio_adicional_no_prestado"]


# ---------------------------------------------------------------------------
# Base
# ---------------------------------------------------------------------------
def reiniciar_db() -> None:
    """Rearma la base desde los CSV (borra lo que hayan escrito los ejercicios, ej. reembolsos iniciados)."""
    DB_PATH.parent.mkdir(exist_ok=True)
    if DB_PATH.exists():
        DB_PATH.unlink()
    con = sqlite3.connect(DB_PATH)
    for tabla in TABLAS:
        with open(CSV_DIR / f"{tabla}.csv", encoding="utf-8") as f:
            filas = list(csv.DictReader(f))
        cols = list(filas[0])
        tipos = ", ".join(f"{c} {'REAL' if c == 'monto_usd' else 'INTEGER' if c in _NUMERICAS else 'TEXT'}"
                          for c in cols)
        con.execute(f"CREATE TABLE {tabla} ({tipos})")
        con.executemany(f"INSERT INTO {tabla} VALUES ({', '.join('?' * len(cols))})",
                        [[_NUMERICAS.get(c, str)(fila[c]) if fila[c] != "" or c not in _NUMERICAS else None
                          for c in cols] for fila in filas])
    con.commit()
    con.close()


@contextmanager
def _conectar() -> Iterator[sqlite3.Connection]:
    """Una conexión por operación (commit al salir y SIEMPRE cerrada: en Windows un archivo abierto no se borra)."""
    _quizas_fallar("db")
    if not DB_PATH.exists():
        reiniciar_db()
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    try:
        yield con
        con.commit()
    finally:
        con.close()


def _uno(sql: str, params: tuple) -> dict | None:
    with _conectar() as con:
        fila = con.execute(sql, params).fetchone()
    return dict(fila) if fila else None


def _todos(sql: str, params: tuple) -> list[dict]:
    with _conectar() as con:
        return [dict(f) for f in con.execute(sql, params).fetchall()]


# ---------------------------------------------------------------------------
# Inyección de fallas (C1 · Ejercicio 4)
# ---------------------------------------------------------------------------
_FALLAS: dict[str, list[str]] = defaultdict(list)


def inyectar_fallas(operacion: str, fallas: list[str]) -> None:
    """Las próximas llamadas a `operacion` fallan en orden: "timeout" (transitorio) o "caida" (duro).
    `operacion`: "consultar_vuelo", "rastrear_valija", "consultar_reserva", "iniciar_reembolso" o "db"."""
    _FALLAS[operacion] = list(fallas)


def limpiar_fallas() -> None:
    _FALLAS.clear()


def _quizas_fallar(operacion: str) -> None:
    if not _FALLAS.get(operacion):
        return
    falla = _FALLAS[operacion].pop(0)
    sistema = "la base de operaciones" if operacion == "db" else f"el sistema de {operacion.split('_')[-1]}s"
    if falla == "timeout":
        raise ErrorTransitorio(f"timeout: {sistema} no respondió en 3 s")
    raise ErrorDelSistema(f"{sistema} está fuera de servicio")


# ---------------------------------------------------------------------------
# Normalización y validación de códigos
# ---------------------------------------------------------------------------
def normalizar_vuelo(codigo: str) -> str:
    """'oa 1203', 'OA-1203', 'OA1203' → 'OA1203'. Otra aerolínea o formato roto → ErrorDeEntrada."""
    c = re.sub(r"[\s\-]", "", str(codigo or "")).upper()
    m = re.fullmatch(r"OA(\d{3,4})", c)
    if m:
        return f"OA{int(m[1]):04d}"
    if re.fullmatch(r"[A-Z0-9]{2}\d{2,4}", c):
        raise ErrorDeEntrada(f"'{codigo}' no es un vuelo de OrbitAir: los vuelos de OrbitAir son 'OA' + 4 dígitos "
                             f"(ej. OA1203). Puede ser un vuelo de otra aerolínea.")
    raise ErrorDeEntrada(f"'{codigo}' no es un código de vuelo válido: el formato es 'OA' + 4 dígitos (ej. OA1203).")


def normalizar_valija(codigo: str) -> tuple[str, str]:
    """Etiqueta 'OA-582331' / 'OA582331' → ("codigo", 'OA-582331'); PIR 'LIM-48213' → ("pir", 'LIM-48213')."""
    c = re.sub(r"\s", "", str(codigo or "")).upper()
    if m := re.fullmatch(r"OA-?(\d{6})", c):
        return "codigo", f"OA-{m[1]}"
    if m := re.fullmatch(r"([A-Z]{3})-?(\d{5})", c):
        return "pir", f"{m[1]}-{m[2]}"
    raise ErrorDeEntrada(f"'{codigo}' no es una etiqueta de valija ('OA-' + 6 dígitos, ej. OA-582331) "
                         f"ni un número de reporte PIR (aeropuerto + 5 dígitos, ej. LIM-48213).")


def normalizar_reserva(codigo: str) -> str:
    c = re.sub(r"\s", "", str(codigo or "")).upper()
    if not re.fullmatch(r"[A-Z0-9]{6}", c):
        raise ErrorDeEntrada(f"'{codigo}' no es un código de reserva válido (6 letras y números, ej. M4TR88).")
    return c


def _validar_fecha(fecha: str | None) -> str | None:
    if fecha in (None, ""):
        return None
    try:
        return date.fromisoformat(str(fecha)).isoformat()
    except ValueError:
        raise ErrorDeEntrada(f"'{fecha}' no es una fecha válida: usar AAAA-MM-DD (ej. {HOY}).") from None


# ---------------------------------------------------------------------------
# Consultas (lo que exponen las herramientas)
# ---------------------------------------------------------------------------
def consultar_vuelo(codigo_vuelo: str, fecha: str | None = None) -> dict:
    """Estado de un vuelo. No requiere permiso: es información pública."""
    _quizas_fallar("consultar_vuelo")
    codigo, fecha = normalizar_vuelo(codigo_vuelo), _validar_fecha(fecha)
    sql, params = "SELECT * FROM vuelos WHERE codigo = ?", (codigo,)
    if fecha:
        sql, params = sql + " AND fecha = ?", (codigo, fecha)
    v = _uno(sql, params)
    if not v:
        return {"encontrado": False, "codigo_vuelo": codigo, "fecha": fecha,
                "detalle": f"No hay un vuelo {codigo}{' el ' + fecha if fecha else ''} en la programación de OrbitAir."}
    return {"encontrado": True, **{k: v[k] for k in ("codigo", "fecha", "origen", "destino", "salida_programada",
                                                      "salida_estimada", "estado", "demora_min", "causa",
                                                      "aviso_cancelacion", "distancia_km")},
            "consultado_el": HOY}


def rastrear_valija(codigo: str, pasajero_id: str) -> dict:
    """Estado de una valija por etiqueta o por PIR. Sólo las del pasajero de la sesión."""
    _quizas_fallar("rastrear_valija")
    campo, valor = normalizar_valija(codigo)
    v = _uno(f"SELECT * FROM valijas WHERE {campo} = ?", (valor,))
    if not v:
        return {"encontrada": False, campo: valor, "detalle": f"No hay ninguna valija registrada con {campo} {valor}."}
    if v["pasajero_id"] != pasajero_id:
        raise ErrorDePermisos(f"la valija {valor} no pertenece al pasajero {pasajero_id}")
    return {"encontrada": True, **{k: v[k] for k in ("codigo", "vuelo", "fecha", "estado", "ubicacion", "pir",
                                                      "actualizado")},
            "estado_final": v["estado"] in ("entregada", "perdida", "devuelta_al_pasajero")}


def consultar_reserva(codigo_reserva: str, pasajero_id: str) -> dict:
    """Reserva con sus vuelos y sus reembolsos. Sólo las del pasajero de la sesión."""
    _quizas_fallar("consultar_reserva")
    codigo = normalizar_reserva(codigo_reserva)
    r = _uno("SELECT * FROM reservas WHERE codigo = ?", (codigo,))
    if not r:
        return {"encontrada": False, "codigo_reserva": codigo, "detalle": f"No existe la reserva {codigo}."}
    if r["pasajero_id"] != pasajero_id:
        raise ErrorDePermisos(f"la reserva {codigo} no pertenece al pasajero {pasajero_id}")
    vuelos = [_uno("SELECT codigo, fecha, origen, destino, estado FROM vuelos WHERE codigo = ?", (c,))
              for c in r["vuelos"].split("|")]
    reembolsos = _todos("SELECT id, motivo, monto_usd, estado, creado, actualizado FROM reembolsos WHERE reserva = ?",
                        (codigo,))
    return {"encontrada": True, "codigo": codigo, "familia": r["familia"], "clase": r["clase"],
            "monto_usd": r["monto_usd"], "medio_pago": r["medio_pago"], "vuelos": [v for v in vuelos if v],
            "reembolsos": reembolsos}


def iniciar_reembolso(codigo_reserva: str, motivo: str, pasajero_id: str, monto_usd: float | None = None) -> dict:
    """ESCRIBE en la base: crea una solicitud de reembolso en estado "solicitado".

    Es la primera herramienta con efectos (C2 · human-in-the-loop): una vez ejecutada,
    el reembolso existe. Valida permiso, motivo y que no haya otro reembolso en curso.
    """
    _quizas_fallar("iniciar_reembolso")
    codigo = normalizar_reserva(codigo_reserva)
    if motivo not in MOTIVOS_REEMBOLSO:
        raise ErrorDeEntrada(f"motivo '{motivo}' inválido. Valores posibles: {', '.join(MOTIVOS_REEMBOLSO)}.")
    r = _uno("SELECT * FROM reservas WHERE codigo = ?", (codigo,))
    if not r:
        raise ErrorDeEntrada(f"No existe la reserva {codigo}.")
    if r["pasajero_id"] != pasajero_id:
        raise ErrorDePermisos(f"la reserva {codigo} no pertenece al pasajero {pasajero_id}")
    en_curso = _uno("SELECT id, estado FROM reembolsos WHERE reserva = ? AND estado IN "
                    "('solicitado', 'en_revision', 'aprobado')", (codigo,))
    if en_curso:
        return {"creado": False, "detalle": f"Ya hay un reembolso en curso para {codigo}: {en_curso['id']} "
                                            f"({en_curso['estado']})."}
    monto = float(monto_usd) if monto_usd not in (None, "") else r["monto_usd"]
    if not 0 < monto <= r["monto_usd"]:
        raise ErrorDeEntrada(f"monto USD {monto} fuera de rango: debe ser mayor a 0 y hasta USD {r['monto_usd']} "
                             f"(lo pagado por la reserva).")
    with _conectar() as con:
        n = con.execute("SELECT COUNT(*) FROM reembolsos").fetchone()[0]
        id_ = f"RE-{11000 + n}"
        con.execute("INSERT INTO reembolsos VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (id_, codigo, pasajero_id, motivo, monto, "solicitado", HOY, HOY))
    return {"creado": True, "id": id_, "reserva": codigo, "motivo": motivo, "monto_usd": monto,
            "estado": "solicitado", "medio_pago": r["medio_pago"]}


def pasajero(pasajero_id: str) -> dict | None:
    return _uno("SELECT * FROM pasajeros WHERE id = ?", (pasajero_id,))
