# -*- coding: utf-8 -*-
"""Demanda de la triangulacion: los viajes REALES de aridos/nacional (linea con Alb. cantera = CAMPO1; no hormigon) de GesRuta,
con su dia (DESDEF), matricula (viaje.MATRI1), origen y destino. SOLO LECTURA. Misma definicion que la demanda v1 (comparable).
Salida: {desde, hasta, viajes:[{c, v, cant, mat, dia, o, d, m3, t, imp, horm}]} + pares (matricula, dia) a bajar del localizador."""
import argparse, collections, json, os, re, sys
D = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, D)
from dbf_gesruta import abrir  # noqa: E402

# Portes de largo recorrido facturados (no áridos ni hormigón): nacional / regional / internacional / especial / grupaje.
# ~29 % de estas líneas NO llevan Alb. cantera (CAMPO1 vacío) y hasta ahora se descartaban enteras. Se identifican por el
# CONCEPTO. Con --con-nacional se capturan también las que no tienen cantera, con clave (empresa, viaje, "A"+albarán).
NACIONAL = re.compile(r"PORTES? (NACIONAL|REGIONAL|INTERNACIONAL)|TRANSPORTE ESPECIAL|GRUPAJE|^PORTE DESDE")


def clean_plate(v):
    k = re.sub(r"[^0-9A-Z]", "", (v or "").upper())
    return "" if k in {"", "0", "000000"} else k


def unidad_porte(um, cod, con, q, imp):
    """Unidad de un porte, igual criterio que el analizador de tarifas: UNIMED/CODCON/CONCEPTO y, si no bastan, la
    heurística por la cantidad (Razo factura el nacional por KM = la cantidad ≈ km del viaje a ~0,75 €/km; Agetrans por
    VIAJE plano, cantidad 1 y 400-550 €; ambas con un bloque por TONELADA de báscula). Devuelve 't'|'m3'|'km'|'h'|'viaje'|''."""
    u = (um or "").strip().upper(); c = (con or "").strip().upper()
    if u in ("KM", "KMS") or "€/KM" in c or "KILOMETR" in c:
        return "km"
    if u in ("H", "HR", "HRS", "HORA", "HORAS") or "/H" in c or "HORA" in c:
        return "h"
    if u == "M3" or "METROS CUB" in c or "METRO CUB" in c:
        return "m3"
    if u in ("TN", "TM", "T", "TON", "TONELADA", "TONELADAS"):
        return "t"
    ratio = (imp / q) if q else 0
    if abs((q or 0) - 1.0) < 1e-6 or ratio >= 20:       # cantidad 1, o precio unitario alto -> es una tarifa por VIAJE
        return "viaje"
    if (q or 0) >= 20 and 0.2 <= ratio <= 5.0:           # cantidad grande y 0,2-5 €/ud -> la cantidad es el KM facturado
        return "km"
    if 6 <= (q or 0) <= 45 and ratio >= 5:               # 6-45 t de báscula
        return "t"
    return ""


def flota_grupo(base):
    """vehicu.dbf de una casa: matriculas SIN proveedor (PROVEE vacio) = flota del grupo. OJO: PROPIO no vale (5790FSH es de
    Razo y lleva PROPIO=False: sera propiedad vs renting); y en la ficha de Agetrans los camiones de Razo llevan PROVEE=P00099,
    por eso la flota del grupo es la UNION de las dos casas. Los camiones ajenos (subcontratados) o no estan en vehicu o
    llevan proveedor: nunca tendran traza nuestra."""
    grupo = set()
    try:
        db = abrir(base, "vehicu.dbf")
    except Exception:  # noqa: BLE001
        return grupo
    for r in db.registros():
        m = clean_plate(db.get(r, "MATRIC"))
        pv = db.get(r, "PROVEE")
        pv = pv.strip() if isinstance(pv, str) else pv
        if m and pv in (None, "", 0):
            grupo.add(m)
    db.cerrar()
    return grupo


def leer_sociedad(base, empresa, desde, hasta, viajes, grupo=None, dueno=None, con_hormigon=False, con_nacional=False):
    dueno = dueno or {}
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
        v, a = str(ln.get(r, "VIAJE")), str(ln.get(r, "ALBARA"))
        dia = cab.get((v, a))
        if not dia:
            continue
        c1 = ln.get(r, "CAMPO1"); c1 = str(c1).strip() if c1 is not None else ""
        con = " ".join((ln.get(r, "CONCEP") or "").upper().split())
        nac = bool(NACIONAL.search(con))
        if c1:                                   # línea con Alb. cantera: áridos / hormigón / nacional-con-cantera (como siempre)
            cant, es_nac_sin_cant = c1, False
        elif con_nacional and nac:               # porte nacional SIN cantera (antes se descartaba): clave sintética "A"+albarán
            cant, es_nac_sin_cant = "A" + a, True
        else:
            continue
        key = (v, cant)
        um = (ln.get(r, "UNIMED") or "").strip().upper()
        cod = (ln.get(r, "CODCON") or "").strip()
        horm = um == "M3" or cod[:1] == "K"
        cr = ln.get(r, "CANTIDREAL") or ln.get(r, "CANTID") or 0
        imp = ln.get(r, "IMPORT") or 0
        u = unidad_porte(um, cod, con, cr, imp)
        t = seen.get(key)
        if t is None:
            mat = matr.get(v, "")
            t = seen[key] = {"c": empresa, "v": v, "cant": cant, "mat": mat, "dia": dia,
                             "o": (ln.get(r, "ORIGEN") or "").strip(), "d": (ln.get(r, "DESTINO") or "").strip(),
                             "m3": 0.0, "t": 0.0, "imp": 0.0, "horm": False,
                             "km_fact": 0.0, "unidad": "", "nac": False, "sin_cantera": es_nac_sin_cant,
                             "propio": ((mat in grupo) if (grupo is not None and mat) else None),
                             "dueno": dueno.get(mat)}
        if um == "M3":
            t["m3"] += cr; t["horm"] = True
        elif um in ("TN", "TM", "T", "TON") or u == "t":
            t["t"] += cr
        if u == "km":
            t["km_fact"] += cr                   # km FACTURADO (la cantidad de la línea de porte por km, ~0,75 €/km en Razo)
        if u and not t["unidad"]:
            t["unidad"] = u
        if nac:
            t["nac"] = True
        if horm:
            t["horm"] = True
        t["imp"] += imp
    ln.cerrar()
    for t in seen.values():
        if not t["km_fact"]:
            t["km_fact"] = None
        if con_hormigon or not t["horm"]:      # hormigon (m3 / concepto K): solo si se pide; va por su propia pasada del motor
            viajes.append(t)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=r"\\SERVIDOR\Programas\Gesruta")
    ap.add_argument("--from-date", dest="desde", required=True)
    ap.add_argument("--to-date", dest="hasta", required=True)
    ap.add_argument("--plates", default="", help="movertis_plates.txt: matriculas descargables por Wialon")
    ap.add_argument("--salida", required=True)
    ap.add_argument("--pares", default="", help="salida opcional: pares (matricula, dia) a bajar del localizador")
    ap.add_argument("--con-hormigon", dest="con_hormigon", action="store_true", help="incluir tambien las cargas de hormigon (viaje por viaje)")
    ap.add_argument("--con-nacional", dest="con_nacional", action="store_true", help="incluir los portes nacional/regional/internacional SIN Alb. cantera (clave 'A'+albaran); trae km_fact y unidad")
    a = ap.parse_args()
    plates = set()
    if a.plates and os.path.isfile(a.plates):
        plates = {clean_plate(l) for l in open(a.plates, encoding="utf-8-sig") if clean_plate(l)}
    viajes = []
    casas = [(carpeta, empresa) for carpeta, empresa in (("EMPTR21", "Razo"), ("EMPAG21", "Agetrans")) if os.path.isdir(os.path.join(a.root, carpeta))]
    # dueno del camion = la casa que lo tiene en su ficha SIN proveedor (si las dos, Razo, que es quien tiene la flota de
    # tractoras y le hace los portes a Agetrans). Sirve para elegir que linea de un ESPEJO intercompania lleva la medida.
    grupo, dueno = set(), {}
    for carpeta, empresa in casas:
        g = flota_grupo(os.path.join(a.root, carpeta))
        grupo |= g
        for m in g:
            if m not in dueno or empresa == "Razo":
                dueno[m] = empresa
    for carpeta, empresa in casas:
        leer_sociedad(os.path.join(a.root, carpeta), empresa, a.desde, a.hasta, viajes, grupo, dueno, a.con_hormigon, a.con_nacional)
    if len(casas) < 2:
        print("Aviso: falta alguna casa en %s" % a.root, file=sys.stderr)
    json.dump({"desde": a.desde, "hasta": a.hasta, "viajes": viajes}, open(a.salida, "w", encoding="utf-8"), ensure_ascii=False)
    pares = collections.Counter((t["mat"], t["dia"]) for t in viajes if t["mat"])
    if a.pares:
        lista = sorted([{"mat": k[0], "dia": k[1], "viajes": n} for k, n in pares.items() if k[0] in plates or not plates], key=lambda x: (x["dia"], x["mat"]))
        json.dump({"pares": lista, "total": len(lista)}, open(a.pares, "w", encoding="utf-8"), ensure_ascii=False)
    nac = [t for t in viajes if t.get("nac")]
    print(json.dumps({"viajes_aridos_nacional": sum(1 for t in viajes if not t["horm"]), "viajes_hormigon": sum(1 for t in viajes if t["horm"]), "sin_matricula": sum(1 for t in viajes if not t["mat"]),
                      "pares_matricula_dia": len(pares), "pares_movertis": sum(1 for k in pares if k[0] in plates),
                      "portes_nacionales": len(nac), "nacional_sin_cantera": sum(1 for t in nac if t.get("sin_cantera")),
                      "nacional_con_km_facturado": sum(1 for t in nac if t.get("km_fact")),
                      "por_casa": dict(collections.Counter(t["c"] for t in viajes))}, ensure_ascii=False))


if __name__ == "__main__":
    main()
