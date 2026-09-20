# -*- coding: utf-8 -*-
"""Casa el Excel de Mi Solred con el .txt de ancho fijo para la MISMA operacion
y averigua a que columna del Excel corresponde cada campo del texto."""
import collections
import os

import xlrd

XLS = r"Z:\A CARBURANTES\2 GUARDADO\Otros\2026\Operaciones202608.xls"
TXT = r"P:\Analizador Carburantes\datos\repostajes\Operaciones202608.txt"
COL = {"operacion": (205, 212), "vehiculo": (175, 190), "fecha": (212, 220), "producto": (269, 279), "litros": (279, 284),
       "bruto": (288, 299), "descuento": (340, 347), "neto": (347, 358)}


def _n(s):
    s = s.strip()
    return int(s) if s.isdigit() else 0


t = {}
for linea in open(TXT, encoding="latin-1"):
    linea = linea.rstrip("\n")
    if len(linea) < 372:
        continue
    g = {k: linea[a:b] for k, (a, b) in COL.items()}
    t[(g["operacion"].strip(), g["fecha"].strip(), g["producto"].strip())] = {"lit": _n(g["litros"]) / 10, "bruto": _n(g["bruto"]) / 100, "dto": _n(g["descuento"]) / 100, "neto": _n(g["neto"]) / 100, "veh": g["vehiculo"].strip()}
print("lineas txt agosto:", len(t))

wb = xlrd.open_workbook(XLS)
h = wb.sheet_by_index(0)
cab = [str(v).strip() for v in h.row_values(0)]
ix = {n: i for i, n in enumerate(cab)}
casadas = 0
ejemplos = []
coinc = collections.Counter()
for r in range(1, h.nrows):
    f = h.row_values(r)
    op = str(f[ix["NUM_REFER"]]).strip().replace(".0", "")
    fecha = str(f[ix["FEC_OPERAC"]]).strip().replace(".0", "")
    prod = str(f[ix["DES_PRODU"]]).strip()
    for k in ((op, fecha, prod), (op.lstrip("0"), fecha, prod), (op.zfill(7), fecha, prod)):
        if k in t:
            casadas += 1
            x = t[k]
            def num(c):
                try:
                    return float(f[ix[c]])
                except (ValueError, TypeError):
                    return None
            for c in ("IMPORTE", "IMP_TOTAL", "BONIF_TOTAL", "NUM_LITROS"):
                v = num(c)
                if v is None:
                    continue
                for nombre, ref in (("neto", x["neto"]), ("bruto", x["bruto"]), ("dto", x["dto"]), ("litros", x["lit"])):
                    if abs(v - ref) < 0.011:
                        coinc[(c, nombre)] += 1
            if len(ejemplos) < 4 and prod == "DIE E+":
                ejemplos.append({c: f[ix[c]] for c in ("NUM_REFER", "FEC_OPERAC", "MATRICULA", "KILOMETROS", "DES_PRODU", "NUM_LITROS", "IMPORTE", "IMP_TOTAL", "IVA", "PU_LITRO", "PRECIO_LITRO", "DCTO_FIJO", "DCTO_EESS", "DCTO_OPERAC", "RAPPEL", "BONIF_TOTAL")} | {"TXT": x})
            break
print("filas del Excel casadas con el texto por (operacion, fecha, producto):", casadas, "de", h.nrows - 1)
print("coincidencias columna Excel = campo del texto:", dict(coinc))
for e in ejemplos:
    print(e)
