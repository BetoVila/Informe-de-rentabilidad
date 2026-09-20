# -*- coding: utf-8 -*-
"""Estructura del 'Listado de personal por funciones' (sin volcar nombres)."""
import collections
import openpyxl

ruta = r"Z:\LABORAL\2026-01-27 Listado de personal por funciones.xlsx"
wb = openpyxl.load_workbook(ruta, read_only=True, data_only=True)
print("HOJAS:", wb.sheetnames)
for nombre in wb.sheetnames:
    ws = wb[nombre]
    filas = [list(f) for f in ws.iter_rows(values_only=True)]
    print("\n=== hoja %r: %d filas x %d cols" % (nombre, len(filas), max((len(f) for f in filas), default=0)))
    for i, f in enumerate(filas[:4]):
        print("%3d | %s" % (i, " | ".join(("." if v is None else str(v).strip()[:10]) for v in f[:10])))
    # columnas con pocos valores distintos = candidatas a 'funcion'/'seccion'
    if len(filas) > 2:
        ncols = max(len(f) for f in filas)
        for j in range(ncols):
            valores = [f[j] for f in filas[1:] if len(f) > j and f[j] not in (None, "")]
            distintos = collections.Counter(str(v).strip() for v in valores)
            if 1 < len(distintos) <= 25 and len(valores) >= 5:
                print("   col %d: %d valores, %d distintos -> %s" % (j, len(valores), len(distintos), dict(distintos.most_common(14))))
