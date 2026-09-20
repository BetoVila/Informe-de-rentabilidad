# -*- coding: utf-8 -*-
"""Exploracion de ESTRUCTURA de un RESUMEN de nomina (no se vuelcan sueldos
con nombre: las celdas de texto se recortan)."""
import sys
import openpyxl

ruta = sys.argv[1]
wb = openpyxl.load_workbook(ruta, read_only=True, data_only=True)
print("HOJAS:", wb.sheetnames)
for nombre in wb.sheetnames:
    ws = wb[nombre]
    print("\n=== hoja %r  max_row=%s max_col=%s" % (nombre, ws.max_row, ws.max_column))
    filas = list(ws.iter_rows(values_only=True))
    print("filas leidas:", len(filas))

    def corta(v):
        if v is None:
            return "."
        if isinstance(v, str):
            return v.strip()[:14]
        if isinstance(v, float):
            return "%.2f" % v
        return str(v)[:14]

    print("--- bloque superior izquierdo (14 filas x 7 columnas) ---")
    for i, fila in enumerate(filas[:14]):
        print("%3d | %s" % (i, " | ".join(corta(v) for v in fila[:7])))
    # columna A y B completas: etiquetas de conceptos/secciones (no personales)
    print("--- columnas A y B (etiquetas), primeras 70 filas con texto ---")
    n = 0
    for i, fila in enumerate(filas):
        a = fila[0] if len(fila) > 0 else None
        b = fila[1] if len(fila) > 1 else None
        if isinstance(a, str) and a.strip() or isinstance(b, str) and b.strip():
            print("%3d | A=%-28s | B=%s" % (i, (a or "").strip()[:28], (b if isinstance(b, str) else "")[:28]))
            n += 1
            if n >= 70:
                break
