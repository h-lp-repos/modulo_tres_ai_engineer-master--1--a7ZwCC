"""Genera los CSV de operaciones de OrbitAir (vuelos, reservas, valijas, reembolsos).

Ya se corrió: los CSV de esta carpeta están versionados. Este script queda para
reproducirlos o ampliarlos (`python data/ops/generar_ops.py`). Es determinista
(semilla fija): siempre genera los mismos datos.

Dos capas:
- ESCENARIOS: registros escritos a mano, que usan los ejercicios de M3 (los vuelos,
  valijas y reservas que aparecen en los datasets de consultas). No se tocan sin
  revisar las guías.
- RELLENO: registros aleatorios con la misma forma, para que la base tenga el
  volumen del track (~60 vuelos, ~200 valijas, reembolsos en distintos estados) y
  las consultas no sean triviales.

La "fecha de operación" de la base es 2026-10-01: "hoy", para el agente.
"""
import csv
import random
from datetime import datetime, timedelta
from pathlib import Path

AQUI = Path(__file__).resolve().parent
HOY = datetime(2026, 10, 1)
rng = random.Random(20261001)

# Aeropuertos de POL-TC-01 §8.1 y distancias aproximadas (km) de las rutas que opera OrbitAir.
RUTAS = {
    ("AEP", "COR"): 650, ("AEP", "MDZ"): 980, ("AEP", "BRC"): 1330, ("AEP", "MVD"): 210,
    ("AEP", "SCL"): 1140, ("AEP", "ASU"): 1040, ("AEP", "LIM"): 3150, ("EZE", "GRU"): 1700,
    ("EZE", "GIG"): 1980, ("EZE", "BOG"): 4660, ("EZE", "SCL"): 1140, ("EZE", "LIM"): 3150,
    ("SCL", "LIM"): 2460, ("LIM", "CUZ"): 580, ("LIM", "BOG"): 1880, ("BOG", "MDE"): 215,
    ("GRU", "GIG"): 360, ("COR", "SCL"): 870, ("MDZ", "SCL"): 190, ("ASU", "GRU"): 1110,
}
CAUSAS_DEMORA = ["operativa", "operativa", "tecnica", "meteorologica", "control_transito_aereo"]
NOMBRES = ["Martina", "Joaquín", "Valentina", "Santiago", "Camila", "Mateo", "Sofía", "Benjamín",
           "Florencia", "Tomás", "Isabella", "Nicolás", "Renata", "Lucas", "Antonella", "Diego"]
APELLIDOS = ["González", "Rodríguez", "Pérez", "Silva", "Rojas", "Gómez", "Díaz", "Torres",
             "Vargas", "Castro", "Romero", "Morales", "Herrera", "Medina", "Ruiz", "Ortiz"]

# ---------------------------------------------------------------------------
# ESCENARIOS (a mano). Los usan data/c1_consultas_agente.jsonl y data/c2_*.
# ---------------------------------------------------------------------------
PASAJEROS = [
    # id, nombre, ciudad de residencia, socio OrbitAir Plus
    ("P-1001", "Lucía Fernández", "Buenos Aires", "si"),
    ("P-1002", "Andrés Quispe", "Lima", "no"),
    ("P-2002", "Carolina Méndez", "Santiago", "si"),
]

VUELOS = [
    # codigo, fecha, origen, destino, salida programada, estado, demora_min, causa, aviso_cancelacion
    ("OA1203", "2026-10-01", "AEP", "LIM", "12:30", "demorado", 95, "operativa", ""),
    ("OA0417", "2026-10-01", "EZE", "BOG", "08:10", "demorado", 260, "tecnica", ""),
    ("OA2250", "2026-10-01", "AEP", "SCL", "16:45", "cancelado", 0, "meteorologica", "2026-09-30"),
    ("OA0761", "2026-09-30", "EZE", "GRU", "06:20", "aterrizado", 150, "operativa", ""),
    ("OA1388", "2026-10-01", "SCL", "LIM", "10:05", "cancelado", 0, "operativa", "2026-09-28"),
    ("OA0905", "2026-10-02", "LIM", "CUZ", "07:40", "programado", 0, "", ""),
    ("OA0530", "2026-09-29", "AEP", "LIM", "21:15", "aterrizado", 0, "", ""),
    ("OA0218", "2026-10-01", "AEP", "COR", "09:00", "en_vuelo", 10, "operativa", ""),
]

RESERVAS = [
    # codigo, pasajero_id, vuelos (|), familia, clase, monto_usd, medio_pago
    ("M4TR88", "P-1001", "OA1388", "CL", "K", 412.0, "tarjeta_credito"),
    ("H2LQ7Z", "P-1001", "OA1203|OA0905", "LT", "Q", 286.5, "tarjeta_debito"),
    ("K7PQ2M", "P-2002", "OA2250", "FX", "Y", 690.0, "tarjeta_credito"),
    ("B8NN4C", "P-1002", "OA0530", "CL", "M", 355.0, "transferencia"),
    ("T5RW2D", "P-1001", "OA2250", "LT", "V", 198.0, "tarjeta_credito"),
]

VALIJAS = [
    # codigo, pasajero_id, vuelo, fecha, estado, ubicacion, pir, actualizado
    ("OA-582331", "P-1001", "OA1203", "2026-10-01", "en_transito", "AEP - cargada en bodega del OA1203", "",
     "2026-10-01 11:52"),
    ("OA-771045", "P-1002", "OA0530", "2026-09-29", "en_busqueda", "sin ubicar - búsqueda en red de escalas",
     "LIM-48213", "2026-09-30 18:20"),
    ("OA-310877", "P-1001", "OA0761", "2026-09-30", "entregada", "GRU - entregada en domicilio declarado", "GRU-20551",
     "2026-10-01 09:15"),
    ("OA-640212", "P-1001", "OA0761", "2026-09-30", "demorada", "EZE - localizada, sale en el próximo vuelo a GRU",
     "GRU-20552", "2026-10-01 07:40"),
]

REEMBOLSOS = [
    # id, reserva, pasajero_id, motivo, monto_usd, estado, creado, actualizado
    ("RE-10421", "B8NN4C", "P-1002", "arrepentimiento_24h", 355.0, "acreditado", "2026-08-02", "2026-08-30"),
    ("RE-10588", "H2LQ7Z", "P-1001", "servicio_adicional_no_prestado", 25.0, "en_revision", "2026-09-27",
     "2026-09-29"),
]


def hora(h: str, mas_min: int = 0) -> str:
    return (datetime.strptime(h, "%H:%M") + timedelta(minutes=mas_min)).strftime("%H:%M")


def relleno_vuelos(n: int) -> list[tuple]:
    usados = {v[0] for v in VUELOS}
    filas = []
    while len(filas) < n:
        codigo = f"OA{rng.randint(100, 2999):04d}"
        if codigo in usados:
            continue
        usados.add(codigo)
        o, d = rng.choice(list(RUTAS))
        if rng.random() < 0.5:
            o, d = d, o
        fecha = (HOY + timedelta(days=rng.choice([-2, -1, -1, 0, 0, 0, 1, 1, 2]))).strftime("%Y-%m-%d")
        salida = f"{rng.randint(5, 22):02d}:{rng.choice(['00', '15', '30', '45'])}"
        if fecha < HOY.strftime("%Y-%m-%d"):
            estado = "aterrizado" if rng.random() < 0.93 else "cancelado"
        elif fecha > HOY.strftime("%Y-%m-%d"):
            estado = "programado" if rng.random() < 0.95 else "cancelado"
        else:
            estado = rng.choice(["programado", "programado", "embarcando", "en_vuelo", "aterrizado", "demorado"])
        demora = rng.choice([0, 0, 0, 15, 25, 40, 70, 130]) if estado in ("aterrizado", "en_vuelo", "embarcando") else 0
        if estado == "demorado":
            demora = rng.choice([45, 80, 135, 190, 320])
        causa = rng.choice(CAUSAS_DEMORA) if (demora or estado == "cancelado") else ""
        aviso = (HOY - timedelta(days=rng.choice([1, 3, 20]))).strftime("%Y-%m-%d") if estado == "cancelado" else ""
        filas.append((codigo, fecha, o, d, salida, estado, demora, causa, aviso))
    return filas


def relleno_pasajeros(n: int) -> list[tuple]:
    filas = []
    for i in range(n):
        filas.append((f"P-{3000 + i}", f"{rng.choice(NOMBRES)} {rng.choice(APELLIDOS)}",
                      rng.choice(["Buenos Aires", "Santiago", "Lima", "Bogotá", "São Paulo", "Montevideo", "Córdoba"]),
                      rng.choice(["si", "no", "no"])))
    return filas


def codigo_reserva(usados: set) -> str:
    letras = "ABCDEFGHJKLMNPQRSTUVWXYZ"
    while True:
        c = "".join(rng.choice(letras + "23456789") for _ in range(6))
        if c not in usados and any(ch.isdigit() for ch in c) and any(ch.isalpha() for ch in c):
            usados.add(c)
            return c


def main():
    vuelos = VUELOS + relleno_vuelos(60 - len(VUELOS))
    pasajeros = PASAJEROS + relleno_pasajeros(117)
    usados = {r[0] for r in RESERVAS}
    reservas = list(RESERVAS)
    familias = {"LT": "OQV", "CL": "KLM", "FX": "YB"}
    for p in pasajeros[len(PASAJEROS):]:
        v = rng.choice(vuelos[len(VUELOS):])
        fam = rng.choice(["LT", "LT", "CL", "CL", "FX"])
        reservas.append((codigo_reserva(usados), p[0], v[0], fam, rng.choice(familias[fam]),
                         round(rng.uniform(90, 720), 2),
                         rng.choice(["tarjeta_credito", "tarjeta_credito", "tarjeta_debito", "transferencia", "millas"])))

    vuelo_por_codigo = {v[0]: v for v in vuelos}
    valijas = list(VALIJAS)
    tags = {v[0] for v in valijas}
    estados_valija = ["entregada"] * 10 + ["en_transito"] * 3 + ["demorada", "en_busqueda", "perdida", "danada_reportada"]
    while len(valijas) < 200:
        r = rng.choice(reservas[len(RESERVAS):])
        if r[3] == "LT" and rng.random() < 0.7:      # Lite no incluye valija facturada
            continue
        tag = f"OA-{rng.randint(100000, 999999)}"
        if tag in tags:
            continue
        tags.add(tag)
        v = vuelo_por_codigo[r[2].split("|")[0]]
        if v[1] > HOY.strftime("%Y-%m-%d") or v[5] == "programado":    # todavía no se despachó
            continue
        estado = rng.choice(estados_valija) if v[5] in ("aterrizado",) else "en_transito" if v[5] != "cancelado" \
            else "devuelta_al_pasajero"
        pir = f"{v[3]}-{rng.randint(10000, 99999)}" if estado in ("demorada", "en_busqueda", "perdida",
                                                                   "danada_reportada") else ""
        ubic = {"entregada": f"{v[3]} - retirada en cinta", "en_transito": f"{v[2]} - en bodega del {v[0]}",
                "demorada": f"{v[2]} - localizada, sale en el próximo vuelo", "en_busqueda": "sin ubicar",
                "perdida": "no localizada en 21 días", "danada_reportada": f"{v[3]} - reporte de daño",
                "devuelta_al_pasajero": f"{v[2]} - devuelta en mostrador"}[estado]
        valijas.append((tag, r[1], v[0], v[1], estado, ubic, pir, f"{v[1]} {rng.randint(6, 23):02d}:{rng.randint(0, 59):02d}"))

    reembolsos = list(REEMBOLSOS)
    motivos = ["arrepentimiento_24h", "cancelacion_involuntaria", "voluntario_flex", "demora_mas_5h",
               "servicio_adicional_no_prestado"]
    estados_re = ["solicitado", "en_revision", "en_revision", "aprobado", "acreditado", "acreditado", "rechazado"]
    for i, r in enumerate(rng.sample(reservas[len(RESERVAS):], 38)):
        creado = HOY - timedelta(days=rng.randint(1, 70))
        reembolsos.append((f"RE-{10600 + i}", r[0], r[1], rng.choice(motivos), r[5], rng.choice(estados_re),
                           creado.strftime("%Y-%m-%d"),
                           (creado + timedelta(days=rng.randint(0, 20))).strftime("%Y-%m-%d")))

    tablas = {
        "pasajeros": (["id", "nombre", "ciudad_residencia", "socio_plus"], pasajeros),
        "vuelos": (["codigo", "fecha", "origen", "destino", "salida_programada", "salida_estimada", "estado",
                    "demora_min", "causa", "aviso_cancelacion", "distancia_km"],
                   [(c, f, o, d, s, hora(s, dm) if e not in ("cancelado",) else "", e, dm, ca, av,
                     RUTAS.get((o, d)) or RUTAS[(d, o)]) for c, f, o, d, s, e, dm, ca, av in vuelos]),
        "reservas": (["codigo", "pasajero_id", "vuelos", "familia", "clase", "monto_usd", "medio_pago"], reservas),
        "valijas": (["codigo", "pasajero_id", "vuelo", "fecha", "estado", "ubicacion", "pir", "actualizado"], valijas),
        "reembolsos": (["id", "reserva", "pasajero_id", "motivo", "monto_usd", "estado", "creado", "actualizado"],
                       reembolsos),
    }
    for nombre, (cols, filas) in tablas.items():
        with open(AQUI / f"{nombre}.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(cols)
            w.writerows(filas)
        print(f"{nombre}.csv: {len(filas)} filas")


if __name__ == "__main__":
    main()
