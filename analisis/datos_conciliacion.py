# -*- coding: utf-8 -*-
"""Agregados REALES (sin personas) para la maqueta de Conciliacion.
Salida: datos_conciliacion.json"""
import collections
import glob
import json
import os
import re

B = r"C:\Users\Roberto\AppData\Local\Temp\claude\C--Users-Roberto-Downloads-Nueva-carpeta\28602b99-e589-45df-aa45-17dc43911990\scratchpad"
X = os.path.join(B, "rentabilidad-extract")
acc = json.load(open(sorted(glob.glob(os.path.join(X, "work", "*", "rentabilidad_access_v3.json")))[-1], encoding="utf-8"))
nom = json.load(open(os.path.join(X, "nomina_test.json"), encoding="utf-8"))
sol = json.load(open(os.path.join(X, "solred_test.json"), encoding="utf-8"))
cat = {str(c["id"]): c["nombre"] for c in acc["categories"]}
maq = {str(m["id"]): (cat.get(str(m.get("categoria"))), re.sub(r"[^0-9A-Z]", "", str(m.get("matricula") or "").upper())) for m in acc["machines"]}

TIPO = {"HORMIGONERA": "hormigonera", "TRACTORA BAÑERA": "banera", "TRACTORA NACIONAL": "nacional"}
acc_m = collections.defaultdict(lambda: collections.defaultdict(float))
est = collections.defaultdict(float)
gas = collections.defaultdict(lambda: collections.defaultdict(float))
for p in acc["parts"]:
    mes = p["Fecha"][:7]
    c, pl = maq.get(str(p["IdMaquina"]), (None, "?"))
    t = TIPO.get(c)
    cond = float(p.get("CosteParteChoferHorasOrdinarias") or 0) + float(p.get("CosteParteChoferHorasExtra") or 0)
    ge = float(p.get("GastosEmpleado") or 0)
    acc_m[mes]["cond"] += cond
    acc_m[mes]["gastos_emp"] += ge
    if t:
        acc_m[(mes, t)]["cond"] += cond
        acc_m[(mes, t)]["gastos_emp"] += ge
    est[mes] += float(p.get("CosteEstructura") or 0)
    if "2026-05" <= mes <= "2026-08":
        gas[mes]["l"] += float(p.get("GasoilLitros") or 0)
        gas[mes]["e"] += float(p.get("GasoilImporte") or 0)

# nomina por mes: conductores = Razo 1,2,3 + Agetrans 1 ; por tipo: hormigonera=Razo1, nacional=Razo2+Agetrans1, banera=Razo3
def nomina(mes, empresa, secs):
    return sum(r["cost"] for r in nom["rows"] if r["period"] == mes and r["company"] == empresa and r["section"] in secs)


meses = sorted({r["period"] for r in nom["rows"]})
personal = []
for mes in meses:
    real = nomina(mes, "Razo", (1, 2, 3)) + nomina(mes, "Agetrans", (1,))
    imp = acc_m[mes]["cond"] + acc_m[mes]["gastos_emp"]
    personal.append({"mes": mes, "nomina": round(real), "imputado": round(imp), "pct": round(100 * imp / real, 1) if real else None,
                     "sin_imputar": round(real - imp)})
ult = meses[-1]
por_tipo = []
for t, nombre, real in (("hormigonera", "Conductor hormigonera", nomina(ult, "Razo", (1,))),
                        ("banera", "Conductor bañera", nomina(ult, "Razo", (3,))),
                        ("nacional", "Conductor nacional", nomina(ult, "Razo", (2,)) + nomina(ult, "Agetrans", (1,)))):
    imp = acc_m[(ult, t)]["cond"] + acc_m[(ult, t)]["gastos_emp"]
    por_tipo.append({"tipo": nombre, "nomina": round(real), "imputado": round(imp), "pct": round(100 * imp / real, 1)})

gasto = []
S = collections.defaultdict(lambda: collections.defaultdict(float))
for r in sol["rows"]:
    if r["familia"] == "gasoleo" and "2026-05" <= r["fecha"][:7] <= "2026-08":
        S[r["fecha"][:7]]["l"] += r["litros"]
        S[r["fecha"][:7]]["e"] += r["neto"]
GESPRO = {"2026-05": 7471.1, "2026-06": 6753.8, "2026-07": 11965.0, "2026-08": 5761.2}     # medido en explora_gespro.py
for mes in ("2026-05", "2026-06", "2026-07", "2026-08"):
    a, s, g = gas[mes]["l"], S[mes]["l"], GESPRO[mes]
    gasto.append({"mes": mes, "partes_l": round(a), "solred_l": round(s), "gespro_l": round(g), "sin_respaldo_l": round(a - s - g),
                  "pct_cubierto": round(100 * (s + g) / a, 1), "partes_eur": round(gas[mes]["e"]), "solred_eur": round(S[mes]["e"])})

estructura = {"mes": ult, "estructura_access": round(est[ult]),
              "admin_taller_razo": round(nomina(ult, "Razo", (4, 5))), "agetrans_s3": round(nomina(ult, "Agetrans", (3,)))}
json.dump({"personal": personal, "por_tipo": por_tipo, "gasto": gasto, "estructura": estructura, "ult": ult},
          open(os.path.join(B, "datos_conciliacion.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(json.dumps({"personal": personal[-8:], "por_tipo": por_tipo, "gasto": gasto, "estructura": estructura}, ensure_ascii=False, indent=1))
