# -*- coding: utf-8 -*-
"""Donde esta el hueco de litros: cada parte con gasoil contra las lineas de
Solred de la misma matricula (+-3 dias, litros +-3%). Despues, AdBlue y
peajes. Solo agregados."""
import collections
import datetime as dt
import glob
import json
import os
import re
import unicodedata

import pyodbc

B = r"C:\Users\Roberto\AppData\Local\Temp\claude\C--Users-Roberto-Downloads-Nueva-carpeta\28602b99-e589-45df-aa45-17dc43911990\scratchpad\rentabilidad-extract"
SOL = r"P:\Analizador Carburantes\datos\repostajes"
COL = {"operacion": (205, 212), "vehiculo": (175, 190), "fecha": (212, 220), "estacion": (224, 244), "localidad": (246, 262),
       "producto": (269, 279), "litros": (279, 284), "bruto": (288, 299), "descuento": (340, 347), "neto": (347, 358)}
DESDE, HASTA = "2026-05-01", "2026-08-31"


def pk(s):
    return re.sub(r"[^0-9A-Z]", "", str(s or "").upper())


def limpio(s):
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().upper()
    return re.sub(r"\s+", " ", re.sub(r"[^A-Z0-9 ]", " ", s)).strip()


def _n(s):
    s = s.strip()
    return int(s) if s.isdigit() else 0


def plate_de(v):
    m = re.search(r"(\d{4}[A-Z]{3})$", (v or "").strip().replace("-", "").replace(" ", "").upper())
    return m.group(1) if m else None


# ---- Solred: todas las lineas de gasoleo/adblue/peajes del periodo
sol, tot = [], collections.defaultdict(lambda: collections.defaultdict(float))
vistas = set()
for ruta in sorted(glob.glob(os.path.join(SOL, "*.txt"))):
    for linea in open(ruta, encoding="latin-1"):
        linea = linea.rstrip("\n")
        if len(linea) < 372:
            continue
        g = {k: linea[a:b] for k, (a, b) in COL.items()}
        f = g["fecha"].strip()
        if not (len(f) == 8 and f.isdigit()):
            continue
        iso = "%s-%s-%s" % (f[:4], f[4:6], f[6:])
        if not (DESDE <= iso <= HASTA):
            continue
        clave = (g["operacion"].strip(), f, g["litros"], g["bruto"], g["producto"])
        if clave in vistas:
            continue
        vistas.add(clave)
        p = g["producto"].strip()
        r = {"fecha": iso, "placa": plate_de(g["vehiculo"]), "litros": _n(g["litros"]) / 10.0, "neto": _n(g["neto"]) / 100.0,
             "bruto": _n(g["bruto"]) / 100.0, "estacion": g["estacion"].strip(), "loc": limpio(g["localidad"]), "prod": p}
        if p.startswith("DIE"):
            r["fam"] = "gasoleo"
            sol.append(r)
        elif p in ("ADB+GRN", "ADBLUE"):
            tot[(iso[:7], "adblue")]["neto"] += r["neto"]
            tot[(iso[:7], "adblue")]["litros"] += r["litros"]
        elif p in ("AUTOPISTAS", "VIA T"):
            tot[(iso[:7], "peaje")]["neto"] += r["neto"]
            tot[(iso[:7], "peaje")]["n"] += 1

# ---- Access: partes con gasoil (+ estacion y localidad)
acc = json.load(open(sorted(glob.glob(os.path.join(B, "work", "*", "rentabilidad_access_v3.json")))[-1], encoding="utf-8"))
maq = {str(m["id"]): pk(m.get("matricula")) for m in acc["machines"]}
cn = pyodbc.connect("DRIVER={Microsoft Access Driver (*.mdb, *.accdb)};DBQ=P:\\PartesTrabajo\\Partes 7.0.accdb", readonly=True)
c = cn.cursor()
c.execute("SELECT IdEstacionServicio, NombreEstacion, LocalidadEstacion FROM EstacionServicio")
est = {str(a): (limpio(b), limpio(l)) for a, b, l in c.fetchall()}
c.execute("SELECT IdParteTrabajo, IdGasoilEstacionServicio FROM PartesTrabajo WHERE Fecha >= #05/01/2026# AND Fecha < #09/01/2026#")
id_est = {str(i): str(e) for i, e in c.fetchall()}
cn.close()
partes = []
ad = collections.defaultdict(lambda: collections.defaultdict(float))
gv = collections.defaultdict(float)
for p in acc["parts"]:
    iso = p["Fecha"][:10]
    if not (DESDE <= iso <= HASTA):
        continue
    ad[iso[:7]]["litros"] += float(p.get("AdBlueLitros") or 0)
    ad[iso[:7]]["eur"] += float(p.get("AdBlueImporte") or 0)
    gv[iso[:7]] += float(p.get("GastosVehiculo") or 0)
    l = float(p.get("GasoilLitros") or 0)
    if l > 0:
        e = id_est.get(str(p["IdParteTrabajo"]), "?")
        nom, loc = est.get(e, ("?", "?"))
        partes.append({"id": p["IdParteTrabajo"], "fecha": iso, "placa": maq.get(str(p["IdMaquina"])), "litros": l, "eur": float(p.get("GasoilImporte") or 0),
                       "est": e, "nom": nom, "loc": loc})

# ---- emparejar parte <-> linea de Solred (misma matricula, +-3 dias, litros +-3%)
por_placa = collections.defaultdict(list)
for i, r in enumerate(sol):
    if r["placa"]:
        por_placa[r["placa"]].append(i)
usadas = set()
emparejados = []
sin_par = []
for p in sorted(partes, key=lambda x: x["fecha"]):
    mejor, mejor_d = None, 99
    d0 = dt.date.fromisoformat(p["fecha"])
    for i in por_placa.get(p["placa"], []):
        if i in usadas:
            continue
        r = sol[i]
        dd = abs((dt.date.fromisoformat(r["fecha"]) - d0).days)
        if dd <= 3 and abs(r["litros"] - p["litros"]) <= max(2.0, 0.03 * p["litros"]) and dd < mejor_d:
            mejor, mejor_d = i, dd
    if mejor is not None:
        usadas.add(mejor)
        emparejados.append((p, sol[mejor], mejor_d))
    else:
        sin_par.append(p)
lp = sum(p["litros"] for p in partes)
le = sum(p["litros"] for p, _, _ in emparejados)
print("partes con gasoil (may-ago 2026): %d, %.0f L" % (len(partes), lp))
print("  emparejados con una linea de Solred (misma matricula, +-3 dias, litros +-3%%): %d partes, %.0f L (%.1f%%)" % (len(emparejados), le, 100 * le / lp))
print("  desfase de dias de los emparejados:", dict(collections.Counter(d for _, _, d in emparejados)))
print("  SIN pareja: %d partes, %.0f L (%.1f%%)" % (len(sin_par), lp - le, 100 * (lp - le) / lp))
sol_sin = [r for i, r in enumerate(sol) if i not in usadas]
print("  lineas de Solred sin parte: %d lineas, %.0f L (de %.0f L totales de Solred)" % (len(sol_sin), sum(r["litros"] for r in sol_sin), sum(r["litros"] for r in sol)))

# ---- de los partes sin pareja: por estacion, y si Solred tiene ALGUNA operacion en esa localidad
locs_solred = collections.defaultdict(float)
for r in sol:
    locs_solred[r["loc"]] += r["litros"]
por_est = collections.defaultdict(lambda: [0, 0.0, set()])
for p in sin_par:
    x = por_est[(p["est"], p["nom"], p["loc"])]
    x[0] += 1
    x[1] += p["litros"]
    x[2].add(p["placa"])
print("\nPARTES SIN PAREJA por estacion (top 14) y litros que Solred registra en esa localidad en todo el periodo:")
print("%-6s %-26s %-18s %6s %9s %8s  %s" % ("id", "estacion (Access)", "localidad", "partes", "litros", "matric.", "Solred en esa localidad"))
for (e, nom, loc), (n, l, pl) in sorted(por_est.items(), key=lambda kv: -kv[1][1])[:14]:
    en_sol = sum(v for k, v in locs_solred.items() if loc and (loc[:8] in k or k[:8] in loc))
    print("%-6s %-26s %-18s %6d %9.0f %8d  %9.0f L" % (e, nom[:26], loc[:18], n, l, len(pl), en_sol))
print("\nPor categoria de matricula no se calcula aqui; ver matriculas distintas sin pareja:", len({p['placa'] for p in sin_par}))

# ---- litros del mismo dia duplicados en partes (misma matricula, misma fecha, mismos litros)
rep = collections.Counter((p["placa"], p["fecha"], round(p["litros"], 1)) for p in partes)
dup = [(k, v) for k, v in rep.items() if v > 1]
print("\nPartes con MISMA matricula+fecha+litros repetidos (posible doble conteo): %d casos, %.0f L de mas" % (len(dup), sum(k[2] * (v - 1) for k, v in dup)))

# ---- AdBlue
print("\nADBLUE por mes  (Access declarado | Solred)  [Solred con IVA; sin IVA entre parentesis]")
for m in sorted({m for m, _ in tot if _ == "adblue"}):
    s = tot[(m, "adblue")]
    print("  %s  Access %8.2f EUR %7.1f L | Solred %8.2f EUR (%8.2f) %7.1f L" % (m, ad[m]["eur"], ad[m]["litros"], s["neto"], s["neto"] / 1.21, s["litros"]))
# ---- Peajes
# ---- IVA: en las parejas exactas, importe del parte frente a Solred con y sin IVA
rat_civa = sorted(r["neto"] / p["eur"] for p, r, _ in emparejados if p["eur"] > 0)
rat_siva = sorted(r["neto"] / 1.21 / p["eur"] for p, r, _ in emparejados if p["eur"] > 0)
rat_bruto = sorted(r["bruto"] / 1.21 / p["eur"] for p, r, _ in emparejados if p["eur"] > 0)
q = lambda v, f: v[int(len(v) * f)]
print("\nIVA - %d parejas: importe SolredNeto / importeParte -> p10=%.3f mediana=%.3f p90=%.3f | (Solred neto/1,21)/parte -> p10=%.3f mediana=%.3f p90=%.3f | (Solred BRUTO/1,21)/parte -> mediana=%.3f" % (
    len(rat_civa), q(rat_civa, .1), q(rat_civa, .5), q(rat_civa, .9), q(rat_siva, .1), q(rat_siva, .5), q(rat_siva, .9), q(rat_bruto, .5)))

# ---- los partes sin pareja: matriculas que NUNCA salen en Solred?
cat = {str(c_["id"]): c_["nombre"] for c_ in acc["categories"]}
emp = {str(c_["id"]): c_["nombre"] for c_ in acc["companies"]}
info = {pk(m.get("matricula")): (cat.get(str(m.get("categoria"))), emp.get(str(m.get("titular")))) for m in acc["machines"]}
placas_solred = {r["placa"] for r in sol if r["placa"]}
placas_partes = {p["placa"] for p in partes}
print("\nMATRICULAS con gasoil: en partes=%d | en Solred=%d | en las dos=%d | solo en partes=%d" % (
    len(placas_partes), len(placas_solred), len(placas_partes & placas_solred), len(placas_partes - placas_solred)))
en = sum(p["litros"] for p in sin_par if p["placa"] in placas_solred)
fuera = sum(p["litros"] for p in sin_par if p["placa"] not in placas_solred)
print("litros de partes SIN pareja: matricula que SI sale en Solred=%.0f | matricula que NUNCA sale en Solred=%.0f" % (en, fuera))
nave = sum(p["litros"] for p in sin_par if p["est"] == "56")
print("   (de ellos, estacion NAVE = surtidor propio: %.0f L)" % nave)
por_tit = collections.defaultdict(float)
por_cat = collections.defaultdict(float)
for p in sin_par:
    if p["est"] == "56":
        continue
    cat_, tit = info.get(p["placa"], ("?", "?"))
    por_tit[tit] += p["litros"]
    por_cat[cat_] += p["litros"]
print("sin pareja y SIN contar la nave, por titular del vehiculo:", {k: round(v) for k, v in por_tit.items()})
print("sin pareja y SIN contar la nave, por categoria:", {k: round(v) for k, v in sorted(por_cat.items(), key=lambda kv: -kv[1])})
tot_tit = collections.defaultdict(float)
for p in partes:
    cat_, tit = info.get(p["placa"], ("?", "?"))
    tot_tit[tit] += p["litros"]
print("litros declarados en partes por titular:", {k: round(v) for k, v in tot_tit.items()})
sol_tit = collections.defaultdict(float)
for r in sol:
    if r["placa"]:
        sol_tit[info.get(r["placa"], ("?", "?"))[1]] += r["litros"]
print("litros de Solred por titular del vehiculo:", {k: round(v) for k, v in sol_tit.items()})

# ---- peajes por matricula-mes
tp = collections.defaultdict(float)
for ruta in sorted(glob.glob(os.path.join(SOL, "*.txt"))):
    for linea in open(ruta, encoding="latin-1"):
        linea = linea.rstrip("\n")
        if len(linea) < 372:
            continue
        g = {k: linea[a:b] for k, (a, b) in COL.items()}
        if g["producto"].strip() in ("AUTOPISTAS", "VIA T") and DESDE <= "%s-%s-%s" % (g["fecha"][:4], g["fecha"][4:6], g["fecha"][6:8]) <= HASTA:
            pl = plate_de(g["vehiculo"])
            if pl:
                tp[("%s-%s" % (g["fecha"][:4], g["fecha"][4:6]), pl)] += _n(g["neto"]) / 100.0 / 1.21
gvp = collections.defaultdict(float)
for p in acc["parts"]:
    iso = p["Fecha"][:10]
    if DESDE <= iso <= HASTA:
        gvp[(iso[:7], maq.get(str(p["IdMaquina"])))] += float(p.get("GastosVehiculo") or 0)
claves = [k for k in tp if tp[k] > 5]
ge = sum(1 for k in claves if gvp.get(k, 0) >= tp[k] * 0.95)
print("\nPEAJES por matricula-mes: %d con peaje en Solred; en %d el GastosVehiculo del parte es >= al peaje (sin IVA); GastosVehiculo total de esas matriculas-mes=%.0f vs peaje=%.0f" % (
    len(claves), ge, sum(gvp.get(k, 0) for k in claves), sum(tp[k] for k in claves)))
print("\nPEAJES por mes (Solred: AUTOPISTAS + VIA T, con IVA) | Access GastosVehiculo (todo tipo de gasto de vehiculo)")
for m in sorted({m for m, f in tot if f == "peaje"}):
    s = tot[(m, "peaje")]
    print("  %s  Solred %8.2f EUR en %4d lineas (%8.2f sin IVA) | Access GastosVehiculo %9.2f" % (m, s["neto"], s["n"], s["neto"] / 1.21, gv[m]))
