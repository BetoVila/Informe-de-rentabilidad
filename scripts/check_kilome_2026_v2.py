# -*- coding: utf-8 -*-
"""Segunda pasada, con los campos reales (VEHICU, LECINIC/LECFINC = el
odometro encadenado de la cabeza tractora; LECINIV/LECFINV = el del
remolque). Solo lectura."""
import collections
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dbf_gesruta import abrir  # noqa: E402

for empresa, carpeta in [("Razo", r"P:\Gesruta\EMPTR21"), ("Agetrans", r"P:\Gesruta\EMPAG21")]:
    print("=" * 12, empresa, "=" * 12)
    with abrir(carpeta, "kilome.dbf") as db:
        por_mes = collections.Counter()
        con_odom_cargado_por_mes = collections.Counter()
        vehiculos_por_anio = collections.defaultdict(set)
        for rec in db.registros():
            f = db.fila(rec, ["FECHA", "VEHICU", "LECINIC", "LECFINC", "LECINIV", "LECFINV", "KMCARGA", "KMVACIO"])
            fecha = f["FECHA"]
            if not fecha:
                continue
            clave_mes = "%04d-%02d" % (fecha.year, fecha.month)
            por_mes[clave_mes] += 1
            if f["LECINIC"] not in (None, 0) and f["LECFINC"] not in (None, 0):
                con_odom_cargado_por_mes[clave_mes] += 1
            if f["VEHICU"]:
                vehiculos_por_anio[fecha.year].add(f["VEHICU"].strip())
        print("\nfilas y cobertura de odometro (LECINIC/LECFINC) por mes, 2025-2026:")
        print("%-8s %8s %8s %6s" % ("mes", "filas", "con_odom", "pct"))
        for mes in sorted(k for k in por_mes if k >= "2025-01"):
            filas = por_mes[mes]
            con = con_odom_cargado_por_mes[mes]
            print("%-8s %8d %8d %5.1f%%" % (mes, filas, con, 100.0 * con / filas if filas else 0))
        print("\nvehiculos distintos por anio (VEHICU, todas las filas, tractora+remolque mezclados):")
        for anio in sorted(vehiculos_por_anio):
            if anio >= 2023:
                print(" ", anio, len(vehiculos_por_anio[anio]))
