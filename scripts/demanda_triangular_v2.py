# -*- coding: utf-8 -*-
"""Demanda de la triangulacion: los viajes REALES de aridos/nacional (linea con Alb. cantera = CAMPO1; no hormigon) de GesRuta,
con su dia (DESDEF), matricula (viaje.MATRI1), origen y destino. SOLO LECTURA. Misma definicion que la demanda v1 (comparable).
Salida: {desde, hasta, viajes:[{c, v, cant, mat, dia, o, d, m3, t, imp, horm}]} + pares (matricula, dia) a bajar del localizador."""
import argparse, collections, json, os, re, sys
D = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, D)
from dbf_gesruta import abrir  # noqa: E402


def clean_plate(v):
    k = re.sub(r"[^0-9A-Z]", "", (v or "").upper())
    return "" if k in {"", "0", "000000"} else k


def leer_sociedad(base, empresa, desde, hasta, viajes):
    vj = abrir(base, "viaje.dbf"); matr = {}
    for r in vj.registros():
        v = vj.get(r, "CODIGO")
        if v is not None:
            matr[str(v)] = clean_plate(vj.get(r, "MATRI1"))
    vj.cerrar()
    alb = abrir(base, "albara.dbf"); cab = {}
    for r in alb.registros():
        v, n = alb.get(r, "VIAJE"), alb.get(r, "NUMERO")
        if v is None or n is None:
            continue
        d = alb.get(r, "DESDEF") or alb.get(r, "FECHA")
        if d and hasattr(d, "year") and desde <= d.isoformat() <= hasta:
            cab[(str(v), str(n))] = d.isoformat()
    alb.cerrar()
    ln = abrir(base, "lineas.dbf")
    seen = {}
    for r in ln.registros():
        c1 = ln.get(r, "CAMPO1")
        if not (c1 and str(c1).strip()):
            continue
        v, a = str(ln.get(r, "VIAJE")), str(ln.get(r, "ALBARA"))
        dia = cab.get((v, a))
        if not dia:
            continue
        cant = str(c1).strip()
        key = (v, cant)
        um = (ln.get(r, "UNIMED") or "").strip().upper()
        cod = (ln.get(r, "CODCON") or "").strip()
        horm = um == "M3" or cod[:1] == "K"
        t = seen.get(key)
        if t is None:
            t = seen[key] = {"c": empresa, "v": v, "cant": cant, "mat": matr.get(v, ""), "dia": dia,
                             "o": (ln.get(r, "ORIGEN") or "").strip(), "d": (ln.get(r, "DESTINO") or "").strip(),
                             "m3": 0.0, "t": 0.0, "imp": 0.0, "horm": False}
        cr = ln.get(r, "CANTIDREAL") or ln.get(r, "CANTID") or 0
        if um == "M3":
            t["m3"] += cr; t["horm"] = True
        elif um in ("TN", "TM", "T", "TON"):
            t["t"] += cr
        if horm:
            t["horm"] = True
        t["imp"] += ln.get(r, "IMPORT") or 0
    ln.cerrar()
    for t in seen.values():
        if not t["horm"]:
            viajes.append(t)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=r"\\SERVIDOR\Programas\Gesruta")
    ap.add_argument("--from-date", dest="desde", required=True)
    ap.add_argument("--to-date", dest="hasta", required=True)
    ap.add_argument("--plates", default="", help="movertis_plates.txt: matriculas descargables por Wialon")
    ap.add_argument("--salida", required=True)
    ap.add_argument("--pares", default="", help="salida opcional: pares (matricula, dia) a bajar del localizador")
    a = ap.parse_args()
    plates = set()
    if a.plates and os.path.isfile(a.plates):
        plates = {clean_plate(l) for l in open(a.plates, encoding="utf-8-sig") if clean_plate(l)}
    viajes = []
    for carpeta, empresa in (("EMPTR21", "Razo"), ("EMPAG21", "Agetrans")):
        base = os.path.join(a.root, carpeta)
        if os.path.isdir(base):
            leer_sociedad(base, empresa, a.desde, a.hasta, viajes)
        else:
            print("Aviso: no esta %s" % base, file=sys.stderr)
    json.dump({"desde": a.desde, "hasta": a.hasta, "viajes": viajes}, open(a.salida, "w", encoding="utf-8"), ensure_ascii=False)
    pares = collections.Counter((t["mat"], t["dia"]) for t in viajes if t["mat"])
    if a.pares:
        lista = sorted([{"mat": k[0], "dia": k[1], "viajes": n} for k, n in pares.items() if k[0] in plates or not plates], key=lambda x: (x["dia"], x["mat"]))
        json.dump({"pares": lista, "total": len(lista)}, open(a.pares, "w", encoding="utf-8"), ensure_ascii=False)
    print(json.dumps({"viajes_aridos_nacional": len(viajes), "sin_matricula": sum(1 for t in viajes if not t["mat"]),
                      "pares_matricula_dia": len(pares), "pares_movertis": sum(1 for k in pares if k[0] in plates),
                      "por_casa": dict(collections.Counter(t["c"] for t in viajes))}, ensure_ascii=False))


if __name__ == "__main__":
    main()
