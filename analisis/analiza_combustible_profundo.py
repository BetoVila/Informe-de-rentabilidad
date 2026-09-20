# -*- coding: utf-8 -*-
"""Por que los partes declaran mas litros que Solred + surtidor.
1) productos de Solred que se estaban descartando; 2) a que estacion
imputan los partes cada litro; 3) exportaciones de texto del surtidor.
Solo agregados."""
import collections
import glob
import os
import re

import pyodbc

SOL = r"P:\Analizador Carburantes\datos\repostajes"
COL = {"operacion": (205, 212), "vehiculo": (175, 190), "fecha": (212, 220), "hora": (220, 224), "estacion": (224, 244),
       "producto": (269, 279), "litros": (279, 284), "bruto": (288, 299), "descuento": (340, 347), "neto": (347, 358)}


def _n(s):
    s = s.strip()
    return int(s) if s.isdigit() else 0


print("=" * 20, "1) PRODUCTOS en los ficheros de Solred (todas las lineas, sin filtrar)")
prod = collections.defaultdict(lambda: [0, 0.0, 0.0])
lineas = cortas = 0
for ruta in sorted(glob.glob(os.path.join(SOL, "*.txt"))):
    for linea in open(ruta, encoding="latin-1"):
        linea = linea.rstrip("\n")
        lineas += 1
        if len(linea) < 372:
            cortas += 1
            continue
        g = {k: linea[a:b] for k, (a, b) in COL.items()}
        p = g["producto"].strip()
        prod[p][0] += 1
        prod[p][1] += _n(g["litros"]) / 10.0
        prod[p][2] += _n(g["neto"]) / 100.0
print("lineas leidas:", lineas, "| demasiado cortas (descartadas):", cortas)
print("%-14s %7s %12s %12s" % ("producto", "lineas", "litros", "neto EUR"))
for p, (n, l, e) in sorted(prod.items(), key=lambda kv: -kv[1][2])[:25]:
    print("%-14s %7d %12.1f %12.2f" % (p, n, l, e))

print("\n" + "=" * 20, "2) ESTACIONES a las que imputan los partes (Access, tabla EstacionServicio)")
cn = pyodbc.connect("DRIVER={Microsoft Access Driver (*.mdb, *.accdb)};DBQ=P:\\PartesTrabajo\\Partes 7.0.accdb", readonly=True)
c = cn.cursor()
c.execute("SELECT * FROM EstacionServicio")
cols = [d[0] for d in c.description]
filas = c.fetchall()
print("columnas:", cols, "| filas:", len(filas))
nombres = {}
for r in filas:
    d = dict(zip(cols, r))
    nombres[str(d.get(cols[0]))] = " | ".join(str(d[k]) for k in cols[1:4] if d.get(k) is not None)
c.execute("SELECT Format(Fecha,'yyyy-mm'), IdGasoilEstacionServicio, Count(*), Sum(GasoilLitros), Sum(GasoilImporte) FROM PartesTrabajo "
          "WHERE Fecha >= #05/01/2026# AND Fecha < #09/01/2026# AND GasoilLitros > 0 GROUP BY Format(Fecha,'yyyy-mm'), IdGasoilEstacionServicio")
por_mes = collections.defaultdict(list)
for mes, est, n, l, e in c.fetchall():
    por_mes[mes].append((float(l or 0), n, str(est), float(e or 0)))
for mes in sorted(por_mes):
    tot = sum(x[0] for x in por_mes[mes])
    print("\n%s: %.0f litros en partes con gasoil" % (mes, tot))
    for l, n, est, e in sorted(por_mes[mes], reverse=True)[:9]:
        print("   estacion %-5s %-46s %9.0f L (%4.1f%%) %5d partes  %.2f EUR/L" % (est, nombres.get(est, "?")[:46], l, 100 * l / tot, n, e / l if l else 0))
cn.close()

print("\n" + "=" * 20, "3) EXPORTACIONES DE TEXTO del surtidor (Z:\\Z Datos Gasoil): litros por mes 2026")
mens = collections.defaultdict(float)
n_ops = collections.defaultdict(int)
for ruta in glob.glob(r"Z:\Z Datos Gasoil\*.txt"):
    for linea in open(ruta, encoding="latin-1"):
        p = linea.strip().split(";")
        if len(p) >= 7 and re.match(r"^\d{8}$", p[2]):
            try:
                mens[p[2][:6]] += float(p[6])
                n_ops[p[2][:6]] += 1
            except ValueError:
                pass
for m in sorted(mens):
    if m >= "202601":
        print("   %s  %9.1f L  %4d servicios" % (m, mens[m], n_ops[m]))
