# -*- coding: utf-8 -*-
"""Nomina real (por seccion) frente al coste de conductor que imputan los
partes de Access (por categoria de vehiculo). Solo agregados."""
import collections
import glob
import json
import os

B = r"C:\Users\Roberto\AppData\Local\Temp\claude\C--Users-Roberto-Downloads-Nueva-carpeta\28602b99-e589-45df-aa45-17dc43911990\scratchpad\rentabilidad-extract"
acc = json.load(open(sorted(glob.glob(os.path.join(B, "work", "*", "rentabilidad_access_v3.json")))[-1], encoding="utf-8"))
nom = json.load(open(os.path.join(B, "nomina_test.json"), encoding="utf-8"))
cat = {str(c["id"]): c["nombre"] for c in acc["categories"]}
maq = {str(m["id"]): (cat.get(str(m.get("categoria"))), m.get("titular")) for m in acc["machines"]}
emp = {str(c["id"]): c["nombre"] for c in acc["companies"]}

por = collections.defaultdict(lambda: collections.defaultdict(float))
for p in acc["parts"]:
    mes = p["Fecha"][:7]
    if not ("2026-03" <= mes <= "2026-08"):
        continue
    c, _ = maq.get(str(p["IdMaquina"]), ("?", None))
    d = por[(mes, c)]
    d["cond"] += float(p.get("CosteParteChoferHorasOrdinarias") or 0) + float(p.get("CosteParteChoferHorasExtra") or 0)
    d["horas"] += float(p.get("HorasTrabajo") or 0)
    d["gastos_emp"] += float(p.get("GastosEmpleado") or 0)
    d["partes"] += 1

print("COSTE DE CONDUCTOR IMPUTADO EN PARTES por categoria de vehiculo (todas las titulares), meses recientes")
cats = sorted({c for (_, c) in por}, key=lambda x: str(x))
print("%-8s | " % "mes" + " | ".join("%-15s" % str(c)[:15] for c in cats))
for mes in ("2026-03", "2026-04", "2026-05", "2026-06", "2026-07", "2026-08"):
    print("%-8s | " % mes + " | ".join("%15.0f" % por[(mes, c)]["cond"] for c in cats))

print("\nGASTOS EMPLEADO (Access) por mes vs DIETAS en nomina (todas las secciones, ambas empresas)")
for mes in ("2026-03", "2026-04", "2026-05", "2026-06", "2026-07", "2026-08"):
    ge = sum(por[(mes, c)]["gastos_emp"] for c in cats)
    dietas = sum(r["dietas"] for r in nom["rows"] if r["period"] == mes)
    extras = sum(r["extras"] for r in nom["rows"] if r["period"] == mes)
    print("%-8s Access GastosEmpleado=%10.0f | nomina dietas=%10.0f | nomina H.EXTRAS=%9.0f" % (mes, ge, dietas, extras))

print("\nNOMINA REAL por seccion (Razo), y conductores totales ambas empresas")
for mes in ("2026-03", "2026-04", "2026-05", "2026-06", "2026-07", "2026-08"):
    razo = {r["section"]: r["cost"] for r in nom["rows"] if r["company"] == "Razo" and r["period"] == mes}
    age = {r["section"]: r["cost"] for r in nom["rows"] if r["company"] == "Agetrans" and r["period"] == mes}
    cond_real = razo.get(1, 0) + razo.get(2, 0) + razo.get(3, 0) + age.get(1, 0)
    cond_acc = sum(por[(mes, c)]["cond"] for c in cats)
    print("%-8s Razo H=%8.0f N=%8.0f B=%8.0f Adm=%8.0f Tall=%8.0f | Agetrans s1=%8.0f s3=%8.0f | CONDUCTORES real=%9.0f imputado=%9.0f -> %5.1f%% (factor x%.3f)" % (
        mes, razo.get(1, 0), razo.get(2, 0), razo.get(3, 0), razo.get(4, 0), razo.get(5, 0), age.get(1, 0), age.get(3, 0),
        cond_real, cond_acc, 100 * cond_acc / cond_real if cond_real else 0, cond_real / cond_acc if cond_acc else 0))

# por tipo (Razo secciones 1,2,3 contra categorias de vehiculo relacionadas)
print("\nPOR TIPO, agosto 2026 (Razo): nomina vs imputado en las categorias afines")
mes = "2026-08"
razo = {r["section"]: r["cost"] for r in nom["rows"] if r["company"] == "Razo" and r["period"] == mes}
afines = {1: ("HORMIGONERA", "REMOLQUE - HORMIGONERA"), 2: ("TRACTORA NACIONAL", "REMOLQUE PLATAFORMA-NACIONAL", "10 PLATAFORMA LONA", "PLATAFORMA ABIERTA"), 3: ("TRACTORA BAÑERA", "REMOLQUE-BAÑERA")}
for s, cs in afines.items():
    imp = sum(por[(mes, c)]["cond"] for c in cs)
    print("  seccion %d (%s): nomina=%9.0f  imputado en %s=%9.0f -> %5.1f%%" % (s, {1: "hormigonera", 2: "nacional", 3: "banera"}[s], razo.get(s, 0), cs, imp, 100 * imp / razo[s] if razo.get(s) else 0))
otras = sum(por[(mes, c)]["cond"] for c in cats if c not in sum(afines.values(), ()))
print("  imputado en otras categorias (turismos, varios, gruas...):", round(otras))
