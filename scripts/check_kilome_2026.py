# -*- coding: utf-8 -*-
"""Comprobacion puntual, no parte del paquete: cuanta cobertura real tiene
kilome.dbf por ano, y en particular 2026. Solo lectura."""
import collections
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dbf_gesruta import abrir  # noqa: E402
from helpers import txt, num, iso  # noqa: E402

for empresa, carpeta in [("Razo", r"P:\Gesruta\EMPTR21"), ("Agetrans", r"P:\Gesruta\EMPAG21")]:
    print("=" * 10, empresa, carpeta, "=" * 10)
    try:
        with abrir(carpeta, "kilome.dbf") as db:
            print("campos:", db.nombres())
            print("registros en cabecera:", db.numrec)
            por_anio = collections.Counter()
            con_km_por_anio = collections.Counter()
            vehiculos_2026 = set()
            muestra_2026 = []
            total = 0
            for rec in db.registros():
                total += 1
                fila = db.fila(rec)
                # buscamos el campo de fecha, sea cual sea su nombre real
                fecha = None
                for nombre_campo in fila:
                    if "FEC" in nombre_campo.upper():
                        v = fila[nombre_campo]
                        if v:
                            fecha = v
                            break
                if fecha is None:
                    continue
                anio = fecha.year if hasattr(fecha, "year") else None
                if anio is None:
                    continue
                por_anio[anio] += 1
                km_val = None
                for nombre_campo in fila:
                    if "KM" in nombre_campo.upper() or "KILOM" in nombre_campo.upper():
                        v = fila[nombre_campo]
                        if v not in (None, 0, 0.0):
                            km_val = v
                            break
                if km_val is not None:
                    con_km_por_anio[anio] += 1
                if anio == 2026:
                    mat = fila.get("MATRICULA") or fila.get("VEHICULO") or ""
                    if mat:
                        vehiculos_2026.add(txt(mat))
                    if len(muestra_2026) < 8:
                        muestra_2026.append(fila)
            print("total registros leidos:", total)
            print("registros por anio:", dict(sorted(por_anio.items())))
            print("CON km valido por anio:", dict(sorted(con_km_por_anio.items())))
            print("vehiculos distintos en 2026:", len(vehiculos_2026))
            print("muestra filas 2026 (hasta 8):")
            for f in muestra_2026:
                print("  ", f)
    except IOError as e:
        print("NO ENCONTRADO:", e)
    print()
