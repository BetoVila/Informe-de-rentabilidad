# -*- coding: utf-8 -*-
"""Cobertura de la base del surtidor (GesproWin) y cuadre con los partes.
Solo agregados. Lee una COPIA en scratchpad, nunca el original en uso."""
import collections
import glob
import json
import os
import re
import shutil
import sys

import pyodbc

ORIGEN = r"P:\Analizador Carburantes\datos\gespro\GesproWinBD.mdb"
BASE = r"C:\Users\Roberto\AppData\Local\Temp\claude\C--Users-Roberto-Downloads-Nueva-carpeta\28602b99-e589-45df-aa45-17dc43911990\scratchpad"
copia = os.path.join(BASE, "GesproWinBD_copia.mdb")
shutil.copy2(ORIGEN, copia)
print("copia:", os.path.getsize(copia), "bytes; original modificado:", os.path.getmtime(ORIGEN))

drv = [d for d in pyodbc.drivers() if "Access" in d and "mdb" in d]
print("drivers Access:", drv)
cn = pyodbc.connect("DRIVER={%s};DBQ=%s" % (drv[0], copia), readonly=True)
c = cn.cursor()
tablas = [r.table_name for r in c.tables(tableType="TABLE")]
print("tablas:", tablas)
c.execute("SELECT * FROM Serveis WHERE 1=0")
print("campos de Serveis:", [d[0] for d in c.description])
c.execute("SELECT MIN(DataGlobal), MAX(DataGlobal), COUNT(*), SUM(Quantitat) FROM Serveis")
print("min/max fecha, n, litros:", c.fetchone())

por_mes = collections.defaultdict(lambda: [0, 0.0, 0, 0])   # n, litros, con_km, sin_matricula
c.execute("SELECT DataGlobal, Matricula, Quilometres, Quantitat, NomCarburant FROM Serveis")
productos = collections.Counter()
plate_mes = collections.defaultdict(float)
for fe, mat, km, lit, prod in c.fetchall():
    if not fe or not lit:
        continue
    m = fe.strftime("%Y-%m")
    v = por_mes[m]
    v[0] += 1
    v[1] += float(lit)
    if km and str(km).strip().isdigit() and int(str(km).strip()) > 0:
        v[2] += 1
    if not re.match(r"^\d{4}[A-Z]{3}$", (mat or "").strip().upper().replace("-", "").replace(" ", "")):
        v[3] += 1
    productos[(prod or "").strip()] += 1
    plate_mes[(m, re.sub(r"[^0-9A-Z]", "", (mat or "").upper()))] += float(lit)
print("\nproductos:", productos.most_common(6))
print("\n%-8s %7s %12s %8s %10s" % ("mes", "servs", "litros", "con_km", "sin_matr"))
for m in sorted(por_mes):
    if m >= "2025-01":
        n, l, k, s = por_mes[m]
        print("%-8s %7d %12.1f %8d %10d" % (m, n, l, k, s))

# cuadre con partes de Access (litros por matricula-mes) may-ago 2026
acc = json.load(open(sorted(glob.glob(os.path.join(BASE, "rentabilidad-extract", "work", "*", "rentabilidad_access_v3.json")))[-1], encoding="utf-8"))
maq = {str(m["id"]): re.sub(r"[^0-9A-Z]", "", str(m.get("matricula") or "").upper()) for m in acc["machines"]}
A = collections.defaultdict(float)
for p in acc["parts"]:
    mes = p["Fecha"][:7]
    if "2026-05" <= mes <= "2026-08":
        A[(mes, maq.get(str(p["IdMaquina"]), "?"))] += float(p.get("GasoilLitros") or 0)
sol = json.load(open(os.path.join(BASE, "rentabilidad-extract", "solred_test.json"), encoding="utf-8"))
S = collections.defaultdict(float)
for r in sol["rows"]:
    if r["familia"] == "gasoleo" and r["vehiculo"] and "2026-05" <= r["fecha"][:7] <= "2026-08":
        S[(r["fecha"][:7], re.sub(r"[^0-9A-Z]", "", r["vehiculo"]))] += r["litros"]
print("\nCUADRE litros diesel  (partes de Access) vs (Solred + surtidor Gespro)")
print("%-8s %12s %12s %12s %10s" % ("mes", "partes", "Solred", "Gespro", "(S+G)/P"))
for mes in ("2026-05", "2026-06", "2026-07", "2026-08"):
    a = sum(v for (m, _), v in A.items() if m == mes)
    s = sum(v for (m, _), v in S.items() if m == mes)
    g = sum(v for (m, _), v in plate_mes.items() if m == mes)
    print("%-8s %12.1f %12.1f %12.1f %9.1f%%" % (mes, a, s, g, 100.0 * (s + g) / a if a else 0))
cn.close()
os.remove(copia)
