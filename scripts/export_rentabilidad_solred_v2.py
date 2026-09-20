# -*- coding: utf-8 -*-
"""Gasto REAL de la tarjeta Solred: gasoleo, AdBlue, peajes y resto, por matricula y mes.

Fuente: los 'Operaciones AAAAMM.txt' de ancho fijo que Roberto baja de Mi Solred y deja en
Analizador Carburantes (programa hermano). Formato y columnas verificados alli (flota.py) y aqui:
  * LITROS con UN decimal (279-284); el Excel de Mi Solred trae dos, pero el importe correcto es el del texto.
  * BRUTO (288-299) - DESCUENTO (340-347) = NETO (347-358) en el 100 % de las lineas.
  * El NETO lleva IVA: en 1.413 parejas parte-Access <-> linea Solred, neto/1,21 = importe del parte, al centimo.
    Por eso se guarda tambien 'base' = neto/(1+IVA) (IVA editable, 21 % por defecto).

QUE CUENTA CUBRE: un fichero por cuenta de Mi Solred. El que hay es el de TRANSPORTES RAZO (NIF B15226095): trae
el 92 % de los litros de Razo y solo el 8 % de los de Agetrans. Este lector NO lo esconde: el informe compara lo que
trae con lo que declaran los partes por sociedad y avisa de la que falta.

SOLO LECTURA. Si la carpeta no existe la fuente queda 'no disponible' y el informe sigue con el resto.
"""
import argparse
import collections
import datetime as dt
import glob
import json
import os
import re

COL = {"operacion": (205, 212), "vehiculo": (175, 190), "fecha": (212, 220), "hora": (220, 224), "producto": (269, 279),
       "litros": (279, 284), "bruto": (288, 299), "descuento": (340, 347), "neto": (347, 358)}
MATRICULA = re.compile(r"(\d{4}[A-Z]{3})$")


def tipo(prod):
    if prod.startswith("DIE"):
        return "gasoleo"
    if prod.startswith("EFI"):
        return "gasolina"
    if prod in ("ADB+GRN", "ADBLUE"):
        return "adblue"
    if prod in ("AUTOPISTAS", "VIA T"):
        return "peaje"
    return "otros"


def placa(v):
    m = MATRICULA.search((v or "").strip().replace("-", "").replace(" ", "").upper())
    return m.group(1) if m else None


def _n(s):
    s = s.strip()
    return int(s) if s.isdigit() else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--roots", nargs="+", required=True, help=r"Carpetas con Operaciones AAAAMM.txt (Analizador Carburantes\datos\repostajes)")
    ap.add_argument("--output", required=True)
    ap.add_argument("--from-date", default="2025-01-01")
    ap.add_argument("--to-date", default=(dt.date.today() - dt.timedelta(days=1)).isoformat())
    ap.add_argument("--iva", type=float, default=0.21)
    a = ap.parse_args()
    meta = {"desde": a.from_date, "hasta": a.to_date, "read_at": dt.datetime.now().astimezone().isoformat(), "disponible": False,
            "iva": a.iva, "ficheros": [], "maxFecha": None, "lineas": 0, "repetidas": 0, "descuadres": 0, "sinMatricula": 0}
    rutas = []
    for r in a.roots:
        rutas += sorted(glob.glob(os.path.join(r, "Operaciones*.txt")))
    if not rutas:
        meta["aviso"] = "No hay ficheros Operaciones*.txt en " + "; ".join(a.roots)
        json.dump({"metadata": meta, "rows": []}, open(a.output, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
        print(json.dumps({"disponible": False, "aviso": meta["aviso"]}, ensure_ascii=False))
        return 0
    agg = collections.defaultdict(lambda: {"n": 0, "litros": 0.0, "neto": 0.0, "base": 0.0})
    vistas = set()
    for ruta in rutas:
        st = os.stat(ruta)
        info = {"fichero": os.path.basename(ruta), "modificado": dt.datetime.fromtimestamp(st.st_mtime).isoformat(timespec="minutes"), "lineas": 0}
        for linea in open(ruta, encoding="latin-1"):
            linea = linea.rstrip("\n")
            if len(linea) < 372:
                continue
            g = {k: linea[x:y] for k, (x, y) in COL.items()}
            f = g["fecha"].strip()
            if not (len(f) == 8 and f.isdigit()):
                continue
            iso = "%s-%s-%s" % (f[:4], f[4:6], f[6:])
            info["lineas"] += 1
            if meta["maxFecha"] is None or iso > meta["maxFecha"]:
                meta["maxFecha"] = iso
            if not (a.from_date <= iso <= a.to_date):
                continue
            prod = g["producto"].strip()
            clave = (g["operacion"].strip(), f, g["hora"], g["litros"], g["bruto"], prod)
            if clave in vistas:
                meta["repetidas"] += 1
                continue
            vistas.add(clave)
            bruto, dto, neto = _n(g["bruto"]) / 100.0, _n(g["descuento"]) / 100.0, _n(g["neto"]) / 100.0
            if abs(bruto - dto - neto) > 0.02:
                meta["descuadres"] += 1
            pl = placa(g["vehiculo"])
            if pl is None:
                meta["sinMatricula"] += 1
            x = agg[(iso[:7], pl, tipo(prod))]
            x["n"] += 1
            x["litros"] += _n(g["litros"]) / 10.0
            x["neto"] += neto
            x["base"] += neto / (1.0 + a.iva)
            meta["lineas"] += 1
        meta["ficheros"].append(info)
    rows = [{"month": m, "plate": p, "kind": k, "n": v["n"], "litros": round(v["litros"], 1), "neto": round(v["neto"], 2), "base": round(v["base"], 2)}
            for (m, p, k), v in sorted(agg.items(), key=lambda kv: (kv[0][0], kv[0][2], kv[0][1] or ""))]
    meta["disponible"] = True
    json.dump({"metadata": meta, "rows": rows}, open(a.output, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    print(json.dumps({"disponible": True, "ficheros": len(rutas), "lineas": meta["lineas"], "filas": len(rows), "maxFecha": meta["maxFecha"],
                      "descuadres": meta["descuadres"], "sinMatricula": meta["sinMatricula"], "repetidas": meta["repetidas"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
