# -*- coding: utf-8 -*-
import collections
import json
import re

B = r"C:\Users\Roberto\AppData\Local\Temp\claude\C--Users-Roberto-Downloads-Nueva-carpeta\28602b99-e589-45df-aa45-17dc43911990\scratchpad\rentabilidad-extract"
d = json.load(open(B + r"\nomina_test.json", encoding="utf-8"))
m = d["metadata"]
print("metadata:", {k: (v if k != "periodos" else {c: (p[0], p[-1], len(p)) for c, p in v.items()}) for k, v in m.items()})
esperados = ["2025-%02d" % i for i in range(1, 13)] + ["2026-%02d" % i for i in range(1, 9)]
for c, ps in m["periodos"].items():
    print(c, "faltan:", [p for p in esperados if p not in ps])
print("\nversiones duplicadas:")
for v in d["versions"]:
    print("  ", v["company"], v["period"], "difieren=", v["difieren"], "| usada:", v["usada"][-60:])
    for x in v["versiones"]:
        print("       ", x)
print("\nerrores de lectura:", d["errors"])
print("\nfilas 2026-08:")
for r in d["rows"]:
    if r["period"] == "2026-08":
        print("  ", r)
print("\nfilas plegadas (privacidad):", [(r["company"], r["period"], r["section"], r["people"], r["plegado"]) for r in d["rows"] if r["plegado"]][:8], "... total", sum(1 for r in d["rows"] if r["plegado"]))
minp = min((r["people"] for r in d["rows"] if r["people"] is not None), default=None)
print("minimo de personas en cualquier fila agregada:", minp)
# sin nombres: las unicas cadenas de las filas son empresa y periodo
claves = set()
for r in d["rows"]:
    claves |= set(r.keys())
print("claves de las filas agregadas:", sorted(claves))
# identidad por empresa-mes: suma de secciones = coste esperado (comparamos con detalle)
det = json.load(open(B + r"\nomina_detalle_test.json", encoding="utf-8"))
suma_det = collections.defaultdict(float)
for p in det["rows"]:
    suma_det[(p["company"], p["period"])] += p["cost"]
suma_agg = collections.defaultdict(float)
for r in d["rows"]:
    suma_agg[(r["company"], r["period"])] += r["cost"]
mal = [(k, round(suma_agg[k], 2), round(suma_det[k], 2)) for k in suma_agg if abs(suma_agg[k] - suma_det[k]) > 0.1]
print("\nagregado vs detalle por persona (empresa-mes) que NO cuadran:", mal[:5], "de", len(suma_agg))
print("personas por mes (Razo/Agetrans) ultimos 3:", [(k[0], k[1], sum(1 for p in det['rows'] if (p['company'], p['period']) == k)) for k in sorted(suma_agg)[-6:]])
