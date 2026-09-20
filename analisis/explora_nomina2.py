# -*- coding: utf-8 -*-
"""Segunda sonda: de donde sale el 'tipo de trabajo' (seccion) en el RESUMEN
de nomina, y los totales por seccion (agregados, sin nombres)."""
import sys
import openpyxl

ruta = sys.argv[1]
wb = openpyxl.load_workbook(ruta, read_only=True, data_only=True)


def c(v, n=30):
    if v is None:
        return "."
    if isinstance(v, float):
        return "%.2f" % v
    return str(v).strip()[:n]


ws = wb["Totales"]
filas = list(ws.iter_rows(values_only=True))
print("=== Totales: filas 46..54, todas las columnas ===")
for i in range(46, min(56, len(filas))):
    print("%3d | %s" % (i, " | ".join(c(v, 22) for v in filas[i])))
print("\n=== Totales: filas cuya etiqueta es TOTAL / TOTAL DEVENGOS / TOTAL COSTE S.S. (todas las secciones) ===")
for i, f in enumerate(filas):
    a = f[0]
    if isinstance(a, str) and a.strip() in ("TOTAL", "TOTAL DEVENGOS", "TOTAL COSTE S.S.", "COSTE S.S. EMPR."):
        print("%3d | %-20s | %s" % (i, a.strip(), " | ".join(c(v, 12) for v in f[1:])))

ws = wb["Detalle"]
filas = list(ws.iter_rows(values_only=True))
print("\n=== Detalle: filas 3..7 (cols A..E) y 49..57 (cols A..E) ===")
for i in list(range(3, 8)) + list(range(49, 58)):
    print("%3d | %s" % (i, " | ".join(c(v, 34) for v in filas[i][:5])))

# donde aparecen textos 'sección' en toda la hoja
print("\n=== celdas de la hoja Detalle que contienen 'secci' (fila, columna, texto) ===")
for i, f in enumerate(filas):
    for j, v in enumerate(f):
        if isinstance(v, str) and "secci" in v.lower():
            print(i, j, v.strip()[:60])
