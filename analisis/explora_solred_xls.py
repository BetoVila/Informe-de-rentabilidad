# -*- coding: utf-8 -*-
"""Que trae Operaciones202608.xls (guardado en 'Otros'). Solo estructura y agregados."""
import collections
import glob
import os
import re

import xlrd

BASE = r"Z:\A CARBURANTES\2 GUARDADO"
print("Contenido de 'Otros' y '3 NO LO ENTIENDO':")
for d in (os.path.join(BASE, "Otros"), r"Z:\A CARBURANTES\3 NO LO ENTIENDO"):
    for r, _, fs in os.walk(d):
        for f in fs:
            print("  ", os.path.join(r, f)[len("Z:\\A CARBURANTES\\"):], os.path.getsize(os.path.join(r, f)))

ruta = os.path.join(BASE, "Otros", "2026", "Operaciones202608.xls")
wb = xlrd.open_workbook(ruta)
print("\nHOJAS:", wb.sheet_names())
for n in wb.sheet_names():
    h = wb.sheet_by_name(n)
    print("\n== hoja %r: %d filas x %d columnas" % (n, h.nrows, h.ncols))
    for i in range(min(6, h.nrows)):
        print("  %2d | %s" % (i, " | ".join(str(v).strip()[:16] for v in h.row_values(i)[:16])))
    # buscar la fila de cabecera y contar valores de columnas con pocos distintos
    cab = next((i for i in range(min(15, h.nrows)) if sum(1 for v in h.row_values(i) if isinstance(v, str) and v.strip()) >= 6), 0)
    heads = [str(v).strip() for v in h.row_values(cab)]
    print("  cabecera detectada en fila %d: %s" % (cab, heads))
    filas = [h.row_values(i) for i in range(cab + 1, h.nrows)]
    for j, nombre in enumerate(heads):
        vals = [f[j] for f in filas if j < len(f) and f[j] not in ("", None)]
        distintos = collections.Counter(str(v).strip() for v in vals)
        if 1 < len(distintos) <= 14:
            print("   col %-2d %-22s %d valores, distintos: %s" % (j, nombre[:22], len(vals), dict(distintos.most_common(8))))
    # matriculas y titular no se pueden resolver aqui: se cuentan matriculas distintas
    pl = set()
    for f in filas:
        for v in f:
            if isinstance(v, str):
                m = re.search(r"(\d{4})[- ]?([A-Z]{3})\b", v.upper())
                if m:
                    pl.add(m.group(1) + m.group(2))
    print("  matriculas distintas detectadas:", len(pl))
    open(os.path.join(os.path.dirname(__file__), "solred_xls_matriculas.txt"), "w").write("\n".join(sorted(pl)))
