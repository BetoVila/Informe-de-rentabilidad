# -*- coding: utf-8 -*-
"""Estructura y agregados del extracto real de Access (sin nombres de personas)."""
import collections
import glob
import json
import os
import sys

WORK = r"C:\Users\Roberto\AppData\Local\Temp\claude\C--Users-Roberto-Downloads-Nueva-carpeta\28602b99-e589-45df-aa45-17dc43911990\scratchpad\rentabilidad-extract\work"
ruta = sorted(glob.glob(os.path.join(WORK, "*", "rentabilidad_access_v3.json")))[-1]
d = json.load(open(ruta, encoding="utf-8"))
print("metadata:", {k: d["metadata"][k] for k in ("desde", "hasta", "modified")})
print("controls:", d["controls"])
p0 = d["parts"][0]
print("\nCAMPOS de un parte (%d):" % len(p0))
print(sorted(p0.keys()))
print("\nempresas (tabla Empresas):", d["companies"])
print("\ncategorias:", [(c["id"], c["nombre"]) for c in d["categories"]])
# maquinas: titular
tit = collections.Counter(str(m.get("titular")) for m in d["machines"])
print("\nmaquinas por titular (id):", dict(tit))

# suma por mes de los componentes de coste del conductor, por titular del vehiculo
maq = {str(m["id"]): m for m in d["machines"]}
emp = {str(c["id"]): c["nombre"] for c in d["companies"]}
por = collections.defaultdict(lambda: collections.defaultdict(float))
for p in d["parts"]:
    mes = p["Fecha"][:7]
    m = maq.get(str(p["IdMaquina"]))
    titular = emp.get(str(m.get("titular"))) if m else "sin maquina"
    for campo in ("CosteParteChoferHorasOrdinarias", "CosteParteChoferHorasExtra", "TotalCostesDirectos", "CosteEstructura", "HorasTrabajo"):
        por[(mes, titular)][campo] += float(p.get(campo) or 0)
    por[(mes, titular)]["partes"] += 1
print("\nCONDUCTOR (ord+extra) por mes y TITULAR del vehiculo, 2025-01..2026-09")
print("%-8s %-28s %7s %13s %13s %13s %11s" % ("mes", "titular", "partes", "cond_ord", "cond_extra", "directos", "horas"))
for (mes, tit), v in sorted(por.items()):
    if mes >= "2026-01":
        print("%-8s %-28s %7d %13.2f %13.2f %13.2f %11.1f" % (mes, (tit or "")[:28], v["partes"], v["CosteParteChoferHorasOrdinarias"],
              v["CosteParteChoferHorasExtra"], v["TotalCostesDirectos"], v["HorasTrabajo"]))
