# -*- coding: utf-8 -*-
"""Municipio y provincia REALES de los puntos (plantas, canteras, obras) a partir de las paradas GPS de nuestra flota.

Entrada: coordenadas aprendidas de las paradas de los camiones (Wialon), una por «empresa|codigo», con cuantos dias y camiones
las confirman. Para cada una se pregunta a OpenStreetMap (Nominatim, geocodificacion INVERSA, 1 peticion por segundo) en que
municipio y provincia cae ese punto. Asi la localidad sale de donde paran de verdad los camiones, no del nombre del punto.
Salida: JSON {"Razo|PRE1": {"localidad", "provincia", "lat", "lon", "dias", "camiones", "radio_m", "fuente"}}. Se reutiliza lo
ya preguntado (cache) para no repetir consultas.
"""
import argparse, json, os, sys, time, urllib.parse, urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from export_rentabilidad_gesruta_actividad_v1 import INE, LETRAS, norm_loc  # noqa: E402  (mismos nombres que el informe)

UA = "razo-rentabilidad/1.0 (informe interno de Transportes Razo)"


def provincia_iso(ad):
    # La provincia se toma del CODIGO OFICIAL (ISO 3166-2, p.ej. «ES-C»), no de «county», que en Galicia es la comarca.
    iso = (ad.get("ISO3166-2-lvl6") or "").upper()
    if iso.startswith("ES-"):
        c = iso[3:]
        if c in LETRAS:
            return INE[LETRAS[c]]
        if c in INE:
            return INE[c]
    return ""


def inversa(lat, lon):
    q = urllib.parse.urlencode({"format": "jsonv2", "lat": lat, "lon": lon, "zoom": 10, "addressdetails": 1,
                                "accept-language": "es"})
    req = urllib.request.Request("https://nominatim.openstreetmap.org/reverse?" + q, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--coords", required=True, help="coords_aprendidas_por_casa_v1.json")
    ap.add_argument("--salida", required=True)
    a = ap.parse_args()
    coords = json.load(open(a.coords, encoding="utf-8"))
    previo = json.load(open(a.salida, encoding="utf-8")) if os.path.isfile(a.salida) else {}
    out, nuevas = {}, 0
    for clave, c in coords.items():
        if c.get("usada") is False or c.get("lat") is None:
            continue
        ya = previo.get(clave)
        if ya and abs(ya["lat"] - c["lat"]) < 1e-4 and abs(ya["lon"] - c["lon"]) < 1e-4:
            out[clave] = ya
            continue
        try:
            r = inversa(c["lat"], c["lon"])
            nuevas += 1
            time.sleep(1.1)   # politica de Nominatim: como maximo 1 peticion por segundo
        except Exception as e:  # noqa: BLE001
            print("  sin respuesta para %s: %s" % (clave, e))
            continue
        ad = r.get("address") or {}
        loc = norm_loc(ad.get("city") or ad.get("town") or ad.get("village") or ad.get("municipality") or "")
        prov = provincia_iso(ad)
        out[clave] = {"localidad": loc, "provincia": prov, "lat": c["lat"], "lon": c["lon"],
                      "dias": c.get("dias"), "camiones": c.get("camiones"), "radio_m": c.get("radio_m"),
                      "fuente": "paradas GPS de la flota + OpenStreetMap (geocodificacion inversa)"}
    os.makedirs(os.path.dirname(os.path.abspath(a.salida)), exist_ok=True)
    tmp = a.salida + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    os.replace(tmp, a.salida)
    print("puntos: %d (consultas nuevas: %d)" % (len(out), nuevas))
    for k, v in list(out.items())[:40]:
        print("  %-16s -> %-26s %-14s (%s dias, %s camiones)" % (k, v["localidad"], v["provincia"], v["dias"], v["camiones"]))


if __name__ == "__main__":
    main()
