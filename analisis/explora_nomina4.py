# -*- coding: utf-8 -*-
"""Por que 'suma de secciones' no cuadra con el total en algunos meses."""
import sys
import openpyxl

for ruta in sys.argv[1:]:
    wb = openpyxl.load_workbook(ruta, read_only=True, data_only=True)
    filas = [list(f) for f in wb["Totales"].iter_rows(values_only=True)]
    ini = next(i for i, f in enumerate(filas) if f and isinstance(f[0], str) and f[0].strip().upper().startswith("TOTALES SECCIONES"))
    cab = next(i for i in range(ini, ini + 6) if any(isinstance(v, (int, float)) for v in filas[i][2:]))
    print("\n###", ruta.split("\\")[-2], "|", ruta.split("\\")[-1])
    print("fila cabecera (indice %d), TODAS las celdas:" % cab)
    print("   ", [v for v in filas[cab]])
    for et in ("TOTAL DEVENGOS", "TOTAL COSTE S.S.", "TOTAL"):
        f = next(f for f in filas[cab + 1:] if f and isinstance(f[0], str) and f[0].strip() == et)
        vals = [v for v in f[1:]]
        num = [v for v in vals if isinstance(v, (int, float))]
        print("   %-18s celdas=%s" % (et, [None if v is None else round(v, 2) if isinstance(v, (int, float)) else v for v in vals]))
        if len(num) > 1:
            print("       total=%.2f  suma(resto)=%.2f  diferencia=%.2f" % (num[0], sum(num[1:]), sum(num[1:]) - num[0]))
