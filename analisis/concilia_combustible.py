# -*- coding: utf-8 -*-
"""Cruce Solred (tarjeta) contra el combustible que declaran los partes de
Access, por mes y por matricula. Solo agregados."""
import collections
import glob
import json
import os
import re

BASE = r"C:\Users\Roberto\AppData\Local\Temp\claude\C--Users-Roberto-Downloads-Nueva-carpeta\28602b99-e589-45df-aa45-17dc43911990\scratchpad\rentabilidad-extract"
acc = json.load(open(sorted(glob.glob(os.path.join(BASE, "work", "*", "rentabilidad_access_v3.json")))[-1], encoding="utf-8"))
sol = json.load(open(os.path.join(BASE, "solred_test.json"), encoding="utf-8"))


def pk(p):
    return re.sub(r"[^0-9A-Z]", "", str(p or "").upper())


maq = {str(m["id"]): pk(m.get("matricula")) for m in acc["machines"]}
A = collections.defaultdict(lambda: collections.defaultdict(float))   # (mes, matricula) -> campos
for p in acc["parts"]:
    mes = p["Fecha"][:7]
    if not ("2026-05" <= mes <= "2026-08"):
        continue
    k = (mes, maq.get(str(p["IdMaquina"]), "?"))
    A[k]["gas_l"] += float(p.get("GasoilLitros") or 0)
    A[k]["gas_eur"] += float(p.get("GasoilImporte") or 0)
    A[k]["adb_l"] += float(p.get("AdBlueLitros") or 0)
    A[k]["adb_eur"] += float(p.get("AdBlueImporte") or 0)

S = collections.defaultdict(lambda: collections.defaultdict(float))
sin_mat = collections.defaultdict(float)
for r in sol["rows"]:
    mes = r["fecha"][:7]
    if not ("2026-05" <= mes <= "2026-08"):
        continue
    if not r["vehiculo"]:
        sin_mat[(mes, r["familia"])] += r["neto"]
        continue
    k = (mes, pk(r["vehiculo"]))
    if r["familia"] == "gasoleo":
        S[k]["gas_l"] += r["litros"]
        S[k]["gas_eur"] += r["neto"]
    else:
        S[k]["adb_l"] += r["litros"]
        S[k]["adb_eur"] += r["neto"]

print("%-8s | %-34s | %-34s | %7s" % ("mes", "ACCESS gasoleo (litros / eur)", "SOLRED gasoleo (litros / eur)", "S/A eur"))
for mes in ("2026-05", "2026-06", "2026-07", "2026-08"):
    al = sum(v["gas_l"] for (m, _), v in A.items() if m == mes)
    ae = sum(v["gas_eur"] for (m, _), v in A.items() if m == mes)
    sl = sum(v["gas_l"] for (m, _), v in S.items() if m == mes)
    se = sum(v["gas_eur"] for (m, _), v in S.items() if m == mes)
    print("%-8s | %14.1f / %14.2f | %14.1f / %14.2f | %6.1f%%" % (mes, al, ae, sl, se, 100.0 * se / ae if ae else 0))

print("\nAdBlue: mes | ACCESS eur | SOLRED eur")
for mes in ("2026-05", "2026-06", "2026-07", "2026-08"):
    print(mes, "%12.2f" % sum(v["adb_eur"] for (m, _), v in A.items() if m == mes), "%12.2f" % sum(v["adb_eur"] for (m, _), v in S.items() if m == mes))

# cobertura por matricula-mes (gasoleo)
ambos = solo_a = solo_s = 0
dif_rel = []
for k in set(A) | set(S):
    a = A[k]["gas_l"] if k in A else 0
    s = S[k]["gas_l"] if k in S else 0
    if a > 0 and s > 0:
        ambos += 1
        dif_rel.append((s - a) / a)
    elif a > 0:
        solo_a += 1
    elif s > 0:
        solo_s += 1
print("\nmatricula-mes con gasoleo: en los dos=%d | solo en partes=%d | solo en Solred=%d" % (ambos, solo_a, solo_s))
if dif_rel:
    dif_rel.sort()
    n = len(dif_rel)
    print("diferencia relativa Solred vs partes (litros) en los %d comunes: p10=%.0f%%  mediana=%.0f%%  p90=%.0f%%" % (
        n, 100 * dif_rel[int(n * .1)], 100 * dif_rel[n // 2], 100 * dif_rel[int(n * .9)]))
print("\nSolred sin matricula reconocible (neto por mes/familia):", {k: round(v, 2) for k, v in sin_mat.items()})
# litros de gasoleo en partes por origen: hay partes con estacion de servicio propia?
n_est = collections.Counter(str(p.get("IdGasoilEstacionServicio")) for p in acc["parts"] if "2026-05" <= p["Fecha"][:7] <= "2026-08" and float(p.get("GasoilLitros") or 0) > 0)
print("\npartes con gasoil (may-ago 2026) por IdGasoilEstacionServicio (top):", n_est.most_common(8))
