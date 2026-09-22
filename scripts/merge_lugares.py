# -*- coding: utf-8 -*-
"""Funde la capa GPS global (fiable: paradas reales) con SOLO los aciertos SEGUROS del gazetteer por nombre
(cuando el municipio geocodificado COINCIDE con el nombre del punto). Los dudosos NO se aplican: van a una lista de repaso.
Salida: cache/lugares_gps.json (lo que lee el extractor via --gps) + lugares_sugerencias.json (para que Roberto ojee)."""
import json, os, sys, unicodedata
HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(os.path.dirname(HERE), "cache")

def sinart(s):
    s = unicodedata.normalize("NFKD", (s or "")).encode("ascii", "ignore").decode().upper()
    for a in ("O ", "A ", "AS ", "OS ", "EL ", "LA ", "LOS ", "LAS "):
        if s.startswith(a):
            s = s[len(a):]
    return " ".join(s.split())

gps = json.load(open(os.path.join(CACHE, "lugares_gps_global.json"), encoding="utf-8"))
nom = json.load(open(os.path.join(CACHE, "lugares_nombre.json"), encoding="utf-8")) if os.path.isfile(os.path.join(CACHE, "lugares_nombre.json")) else {}

merged = dict(gps)
sugerencias, aplicados = {}, 0
for cod, v in nom.items():
    if cod in gps:
        continue
    loc = v.get("localidad") or ""
    q = v.get("consulta") or ""
    nq, nl = sinart(q), sinart(loc)
    seguro = bool(loc) and (nq == nl or nq in nl or nl in nq)
    if seguro:
        merged[cod] = {"localidad": loc, "provincia": v.get("provincia", ""), "fuente": "nombre=municipio (seguro)"}
        aplicados += 1
    else:
        sugerencias[cod] = v

json.dump(merged, open(os.path.join(CACHE, "lugares_gps.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
json.dump(sugerencias, open(os.path.join(CACHE, "lugares_sugerencias.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("GPS global:", len(gps), "| gazetteer seguros aplicados:", aplicados, "| dudosos a repaso:", len(sugerencias))
print("TOTAL en lugares_gps.json (global):", len(merged))
