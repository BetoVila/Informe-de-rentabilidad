# -*- coding: utf-8 -*-
"""Resuelve provincia/localidad de los puntos que quedan SIN geolocalizar, geocodificando su NOMBRE contra OpenStreetMap
(Nominatim, busqueda directa, 1 peticion/seg, sesgo Galicia/Espana). Es MENOS fiable que el GPS de las paradas -> se marca
como derivado del nombre para que Roberto lo repase. Entrada: el CSV de puntos pendientes (Codigo;Punto;Viajes;Falta;...).
Salida: JSON {codigo:{localidad,provincia,fuente,consulta}} para fundir con la capa GPS (el GPS manda; esto rellena huecos).
"""
import argparse, csv, json, os, re, sys, time, urllib.parse, urllib.request
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from export_rentabilidad_gesruta_actividad_v1 import INE, LETRAS, norm_loc, norm_prov  # noqa: E402

UA = "razo-rentabilidad/1.0 (informe interno de Transportes Razo)"
QUITA = re.compile(r"^\s*(PLANTA\s+DE\s+|PLANTA\s+|CANTERA\s+DE\s+|CANTEIRA\s+DE\s+|CANTERA\s+|OBRA\s+DE\s+|OBRA\s+|UTE\s+|PUERTO\s+|PARQUE\s+|POL[IÍ]GONO\s+|POL\.\s*|PREBETONG\s+|HORMIGONES\s+|ARIDOS\s+)", re.I)


def limpia(nom):
    n = " ".join((nom or "").split())
    n = re.sub(r"\([^)]*\)", "", n).strip()          # fuera parentesis
    prev = None
    while prev != n:
        prev = n; n = QUITA.sub("", n).strip()
    return n


def provincia_iso(ad):
    iso = (ad.get("ISO3166-2-lvl6") or "").upper()
    if iso.startswith("ES-"):
        c = iso[3:]
        if c in LETRAS: return INE[LETRAS[c]]
        if c in INE: return INE[c]
    return ""


def geocodifica(q):
    p = urllib.parse.urlencode({"q": q + ", Galicia, España", "format": "jsonv2", "limit": 1,
                                "addressdetails": 1, "countrycodes": "es", "accept-language": "es"})
    req = urllib.request.Request("https://nominatim.openstreetmap.org/search?" + p, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        j = json.loads(r.read().decode("utf-8"))
    return j[0] if j else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pendientes", required=True, help="CSV de puntos pendientes (Codigo;Punto;Viajes;Falta;Provincia;Localidad)")
    ap.add_argument("--salida", required=True)
    ap.add_argument("--gps", default="", help="lugares_gps_global.json (si un codigo ya esta ahi, no se geocodifica)")
    a = ap.parse_args()
    gps = json.load(open(a.gps, encoding="utf-8")) if a.gps and os.path.isfile(a.gps) else {}
    previo = json.load(open(a.salida, encoding="utf-8")) if os.path.isfile(a.salida) else {}
    out, nuevas = dict(previo), 0
    with open(a.pendientes, encoding="utf-8-sig", newline="") as f:
        filas = list(csv.DictReader(f, delimiter=";"))
    for row in filas:
        cod = (row.get("Codigo") or "").strip()
        if not cod or cod in gps or cod in out:
            continue
        nom = (row.get("Punto") or "").strip()
        q = limpia(nom)
        if len(q) < 3:
            continue
        try:
            r = geocodifica(q); nuevas += 1; time.sleep(1.1)
        except Exception as e:  # noqa: BLE001
            print("  sin respuesta %s (%s): %s" % (cod, q, e)); continue
        if not r:
            continue
        ad = r.get("address") or {}
        loc = norm_loc(ad.get("city") or ad.get("town") or ad.get("village") or ad.get("municipality") or "")
        prov = provincia_iso(ad)
        if loc or prov:
            out[cod] = {"localidad": loc, "provincia": prov, "fuente": "nombre+OpenStreetMap (repasar)",
                        "consulta": q, "punto": nom}
    tmp = a.salida + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    os.replace(tmp, a.salida)
    print("resueltos por nombre: %d (consultas nuevas %d)" % (len(out), nuevas))
    for k, v in list(out.items())[:50]:
        print("  %-8s %-28s -> %-24s %s" % (k, (v.get("consulta") or "")[:28], v.get("localidad") or "?", v.get("provincia") or "?"))


if __name__ == "__main__":
    main()
