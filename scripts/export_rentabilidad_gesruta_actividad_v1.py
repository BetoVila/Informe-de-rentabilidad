# -*- coding: utf-8 -*-
"""Actividad operativa de GesRuta para el informe de rentabilidad. SOLO LECTURA.

El VIAJE de GesRuta es un CONTENEDOR (agrupa varias entregas de un camion/chofer y fija el cliente y la fecha). El VIAJE
REAL es cada linea de albaran con valor en «Alb. cantera» (campo CAMPO1); su km, sobre todo en hormigon, es «Km. Viaje»
(campo CAMPO2). Aqui se cuentan asi: una fila por (viaje, cantera), con sus m3/toneladas, km, importe, matricula y
origen/destino->provincia. Verificado con las capturas de Roberto (viajes 00029968 hormigon, 00029471 aridos).

Lee por sociedad (EMPTR21 Razo, EMPAG21 Agetrans): lineas (lineas de albaran), albara (fecha de servicio y cliente),
viaje (matricula y chofer), puntos + puntcd (maestros de lugares: provincia/localidad/CP), mascli (nombre de cliente).
NUNCA escribe en los sistemas de origen. Si se le pasa --lugares, MANTIENE un CSV editable (fuera del origen) donde
Roberto escribe la provincia/localidad de los puntos que GesRuta nunca geolocalizo; ese CSV manda sobre puntcd.
"""
import argparse, csv, datetime, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dbf_gesruta import abrir


# ---- CSV editable de provincias/localidades por punto (lo rellena Roberto; nosotros lo respetamos y lo mantenemos) ----
CAB_LUGARES = ["Codigo", "Punto", "Viajes", "Provincia", "Localidad"]


def cargar_override(path):
    """Devuelve (override, previos). override={cod:{prov,loc}} solo con Provincia escrita; previos=todas las filas guardadas."""
    override, previos = {}, {}
    if not path or not os.path.isfile(path):
        return override, previos
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f, delimiter=";"):
            cod = (row.get("Codigo") or "").strip()
            if not cod:
                continue
            prov = norm_prov(row.get("Provincia") or "")
            loc = (row.get("Localidad") or "").strip()
            previos[cod] = {"punto": (row.get("Punto") or "").strip(), "prov": prov, "loc": loc}
            if prov:
                override[cod] = {"prov": prov, "loc": loc}
    return override, previos


def escribir_override(path, pend, previos):
    """Reescribe el CSV preservando lo que Roberto ya escribio; refresca 'Viajes' y anade los puntos nuevos sin provincia."""
    codigos = set(pend) | set(previos)
    filas = []
    for cod in codigos:
        p = previos.get(cod, {})
        u = pend.get(cod)
        # Se mantiene lo que Roberto ya escribió (tiene provincia) y lo que sigue pendiente (aparece en pend).
        # Lo que ya resolvió el maestro y él no había tocado, se cae de la lista.
        if not p.get("prov") and u is None:
            continue
        filas.append({"Codigo": cod, "Punto": (u or {}).get("punto") or p.get("punto") or cod,
                      "Viajes": (u or {}).get("viajes", 0), "Provincia": p.get("prov", ""), "Localidad": p.get("loc", "")})
    # Primero los pendientes (sin provincia) de mas trafico, para que Roberto ataque lo que mas pesa.
    filas.sort(key=lambda r: (1 if r["Provincia"] else 0, -r["Viajes"], r["Punto"]))
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CAB_LUGARES, delimiter=";")
        w.writeheader()
        w.writerows(filas)
    os.replace(tmp, path)
    return len(filas), sum(1 for r in filas if not r["Provincia"])


def limpio_km(v):
    try:
        k = float(v)
        return k if 0 < k <= 300 else 0.0
    except (TypeError, ValueError):
        return 0.0


def norm_prov(s):
    # Provincia como NOMBRE; se unifican variantes obvias del mismo territorio.
    p = (s or "").strip().upper()
    if not p:
        return ""
    if p in ("LA CORUNA", "LA CORUÑA", "A CORUNA", "CORUNA", "CORUÑA", "LA CORUÑA."):
        return "A CORUÑA"
    if p in ("ORENSE",):
        return "OURENSE"
    return p


# Códigos oficiales de provincia (INE, 2 dígitos) -> nombre canónico. También es el prefijo del código postal.
INE = {"01": "ARABA/ÁLAVA", "02": "ALBACETE", "03": "ALICANTE", "04": "ALMERÍA", "05": "ÁVILA", "06": "BADAJOZ",
       "07": "BALEARES", "08": "BARCELONA", "09": "BURGOS", "10": "CÁCERES", "11": "CÁDIZ", "12": "CASTELLÓN",
       "13": "CIUDAD REAL", "14": "CÓRDOBA", "15": "A CORUÑA", "16": "CUENCA", "17": "GIRONA", "18": "GRANADA",
       "19": "GUADALAJARA", "20": "GIPUZKOA", "21": "HUELVA", "22": "HUESCA", "23": "JAÉN", "24": "LEÓN",
       "25": "LLEIDA", "26": "LA RIOJA", "27": "LUGO", "28": "MADRID", "29": "MÁLAGA", "30": "MURCIA",
       "31": "NAVARRA", "32": "OURENSE", "33": "ASTURIAS", "34": "PALENCIA", "35": "LAS PALMAS", "36": "PONTEVEDRA",
       "37": "SALAMANCA", "38": "SANTA CRUZ DE TENERIFE", "39": "CANTABRIA", "40": "SEGOVIA", "41": "SEVILLA",
       "42": "SORIA", "43": "TARRAGONA", "44": "TERUEL", "45": "TOLEDO", "46": "VALENCIA", "47": "VALLADOLID",
       "48": "BIZKAIA", "49": "ZAMORA", "50": "ZARAGOZA", "51": "CEUTA", "52": "MELILLA"}
# Códigos de matrícula antiguos (una/dos letras) -> código INE.
LETRAS = {"C": "15", "LU": "27", "OR": "32", "OU": "32", "PO": "36", "M": "28", "TO": "45", "LE": "24", "V": "46",
          "B": "08", "Z": "50", "VA": "47", "BI": "48", "SS": "20", "O": "33", "S": "39", "BU": "09", "P": "34",
          "ZA": "49", "SA": "37", "AV": "05", "SG": "40", "SO": "42", "GU": "19", "CU": "16", "CR": "13", "AB": "02",
          "MU": "30", "A": "03", "CS": "12", "GI": "17", "GE": "17", "T": "43", "L": "25", "HU": "22", "TE": "44",
          "NA": "31", "VI": "01", "LO": "26", "CC": "10", "BA": "06", "SE": "41", "H": "21", "CA": "11", "CO": "14",
          "J": "23", "GR": "18", "MA": "29", "AL": "04", "PM": "07", "IB": "07", "GC": "35", "TF": "38", "CE": "51",
          "ML": "52"}


def prov_desde(pa, pv, cp):
    # Provincia a partir del nombre (PROVINCIA), el CP (prefijo INE) o el código (PROVIN, numérico o de matrícula).
    pa = (pa or "").strip()
    if pa:
        return norm_prov(pa)
    cp = (cp or "").strip()
    if len(cp) >= 2 and cp[:2] in INE:
        return INE[cp[:2]]
    pv = (pv or "").strip().upper()
    if pv in INE:
        return INE[pv]
    if pv in LETRAS:
        return INE[LETRAS[pv]]
    if pv in ("PT", "P-", "POR"):
        return "PORTUGAL"
    return ""


def cargar_lugares(base):
    # Maestro de lugares combinado: puntos.dbf (rico: provincia/CP/código) manda; puntcd.dbf rellena huecos.
    lugar = {}
    try:
        pt = abrir(base, "puntos.dbf")
        for r in pt.registros():
            c = (pt.get(r, "CODIGO") or "").strip()
            if not c:
                continue
            nom = (pt.get(r, "NOMBRE") or "").strip()
            pro = prov_desde(pt.get(r, "PROVINCIA"), pt.get(r, "PROVIN"), pt.get(r, "CP"))
            loc = (pt.get(r, "LOCALI") or "").strip()
            lugar[c] = {"pro": pro, "loc": loc or nom, "nom": nom}
        pt.cerrar()
    except IOError:
        pass
    pc = abrir(base, "puntcd.dbf")
    for r in pc.registros():
        c = (pc.get(r, "CODIGO") or "").strip()
        if not c:
            continue
        nom = (pc.get(r, "NOMBRE") or "").strip()
        pro = prov_desde(pc.get(r, "PROVINCIA") if "PROVINCIA" in pc.nombres() else "", "", pc.get(r, "CP")) or norm_prov(pc.get(r, "PROVIN") or "")
        loc = (pc.get(r, "LOCALI") or "").strip()
        prev = lugar.get(c)
        if prev is None:
            lugar[c] = {"pro": pro, "loc": loc or nom, "nom": nom}
        else:
            # completar lo que puntos no trajo
            if not prev["pro"] and pro:
                prev["pro"] = pro
            if (not prev["loc"] or prev["loc"] == prev["nom"]) and loc:
                prev["loc"] = loc
    pc.cerrar()
    return lugar


def cat_gasto(con):
    # Categoria de un gasto de inggas por su CONCEPTO (unica senal fiable; CODCUENTA/PROTRAN van vacios).
    c = (con or "").strip().upper()
    if c == "GASOIL":
        return "gasoil"
    if c == "ADBLUE":
        return "adblue"
    if c.startswith("AUTOPISTA") or "PEAJE" in c:
        return "peajes"
    if c.startswith("PORTE") or "TONELADAS SERVIDAS" in c:
        return "subcontratacion"
    return "materiales"  # aridos y demas compras directas al proveedor


def leer_margen(base, empresa, desde, hasta):
    # P&L operativo por viaje desde inggas.dbf: ingreso (TIPO I) y gasto (TIPO G) por concepto, agregado por (mes, cliente).
    # Es el margen que ve GesRuta, ANTES del coste real de flota (diesel Solred+Access), personal (nomina) e indirectos.
    clientes = {}
    mc = abrir(base, "mascli.dbf")
    for r in mc.registros():
        cod = (mc.get(r, "CODIGO") or "").strip()
        if cod:
            clientes[cod] = (mc.get(r, "NOMBRE") or "").strip()
    mc.cerrar()
    vcli = {}
    alb = abrir(base, "albara.dbf")
    for r in alb.registros():
        v = alb.get(r, "VIAJE")
        if v is None:
            continue
        vcli.setdefault(str(v), clientes.get((alb.get(r, "CLIENT") or "").strip(), ""))
    alb.cerrar()
    ig = abrir(base, "inggas.dbf")
    agg = {}  # (mes, cli) -> dict de importes
    for r in ig.registros():
        f = ig.get(r, "FECHA")
        if not f or f.isoformat() < desde or f.isoformat() > hasta:
            continue
        tp = (ig.get(r, "TIPO") or "").strip().upper()
        cli = vcli.get(str(ig.get(r, "VIAJE")), "") or "(sin cliente)"
        key = (f.isoformat()[:7], cli)
        a = agg.get(key)
        if a is None:
            a = agg[key] = {"c": empresa, "m": key[0], "cli": cli, "ing": 0.0,
                            "materiales": 0.0, "subcontratacion": 0.0, "gasoil": 0.0, "peajes": 0.0, "adblue": 0.0}
        if tp == "I":
            a["ing"] += ig.get(r, "IMPORTEH") or 0
        elif tp == "G":
            a[cat_gasto(ig.get(r, "CONCEPTO"))] += ig.get(r, "IMPORTED") or 0
    ig.cerrar()
    for a in agg.values():
        for k in ("ing", "materiales", "subcontratacion", "gasoil", "peajes", "adblue"):
            a[k] = round(a[k], 2)
    return list(agg.values())


def leer_sociedad(base, empresa, desde, hasta, override, pend):
    # maestro de clientes: codigo -> nombre (mascli.dbf)
    clientes = {}
    mc = abrir(base, "mascli.dbf")
    for r in mc.registros():
        cod = (mc.get(r, "CODIGO") or "").strip()
        if cod:
            clientes[cod] = (mc.get(r, "NOMBRE") or "").strip()
    mc.cerrar()
    # fecha de servicio + cliente por (viaje, albaran)
    alb = abrir(base, "albara.dbf")
    cab = {}
    for r in alb.registros():
        v, n = alb.get(r, "VIAJE"), alb.get(r, "NUMERO")
        if v is None or n is None:
            continue
        cod = (alb.get(r, "CLIENT") or "").strip()
        cab[(str(v), str(n))] = {"fecha": alb.get(r, "DESDEF") or alb.get(r, "FECHA"),
                                 "cliente": clientes.get(cod, cod)}
    alb.cerrar()
    # matricula por viaje
    vj = abrir(base, "viaje.dbf")
    matr = {}
    for r in vj.registros():
        v = vj.get(r, "CODIGO")          # la clave del viaje en viaje.dbf es CODIGO (no VIAJE)
        if v is not None:
            matr[str(v)] = {"mat": (vj.get(r, "MATRI1") or "").strip(), "cho": (vj.get(r, "CHOFER1") or "").strip()}
    vj.cerrar()
    # lugares: codigo -> provincia, localidad (maestro combinado puntos + puntcd)
    lugar = cargar_lugares(base)

    def rprov(code):  # el CSV de Roberto manda; si no, el maestro de lugares
        ov = override.get(code)
        return (ov and ov.get("prov")) or lugar.get(code, {}).get("pro", "")

    def rloc(code):
        ov = override.get(code)
        return (ov and ov.get("loc")) or lugar.get(code, {}).get("loc", "")

    def apuntar_pendiente(code):  # punto usado sin provincia -> a la lista para que Roberto la escriba
        if code and not rprov(code):
            p = pend.setdefault(code, {"punto": "", "viajes": 0})
            p["viajes"] += 1
            if not p["punto"]:
                p["punto"] = lugar.get(code, {}).get("nom", "") or code

    # lineas: agregacion por (viaje, cantera) = viaje real
    ln = abrir(base, "lineas.dbf")
    trips = {}
    for r in ln.registros():
        c1 = ln.get(r, "CAMPO1")
        if not (c1 and str(c1).strip()):
            continue
        v, a = str(ln.get(r, "VIAJE")), str(ln.get(r, "ALBARA"))
        c = cab.get((v, a))
        d = c["fecha"] if c else None
        if not d or not (d.year >= int(desde[:4]) and d.isoformat() >= desde and d.isoformat() <= hasta):
            continue
        cant = str(c1).strip()
        key = (v, cant)
        um = (ln.get(r, "UNIMED") or "").strip().upper()
        cod = (ln.get(r, "CODCON") or "").strip()
        horm = um == "M3" or cod[:1] == "K"
        t = trips.get(key)
        if t is None:
            o, dest = (ln.get(r, "ORIGEN") or "").strip(), (ln.get(r, "DESTINO") or "").strip()
            apuntar_pendiente(o); apuntar_pendiente(dest)
            t = trips[key] = {"c": empresa, "v": v, "cant": cant, "mat": matr.get(v, {}).get("mat", ""), "cho": matr.get(v, {}).get("cho", ""), "mes": d.isoformat()[:7],
                              "cli": c["cliente"] if c else "", "o": o, "d": dest,
                              "op": rprov(o), "ol": rloc(o),
                              "dp": rprov(dest), "dl": rloc(dest),
                              "km": 0.0, "m3": 0.0, "t": 0.0, "imp": 0.0, "horm": False}
        t["imp"] += ln.get(r, "IMPORT") or 0
        cr = ln.get(r, "CANTIDREAL") or ln.get(r, "CANTID") or 0
        if um == "M3":
            t["m3"] += cr; t["horm"] = True
        elif um in ("TN", "TM", "T", "TON"):
            t["t"] += cr
        if horm:
            t["km"] += limpio_km(ln.get(r, "CAMPO2")); t["horm"] = True
    ln.cerrar()
    return list(trips.values())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True, help="Carpeta Gesruta (con EMPTR21 y EMPAG21)")
    ap.add_argument("--output", required=True)
    ap.add_argument("--from-date", default="2025-01-01")
    ap.add_argument("--to-date", default="")
    ap.add_argument("--lugares", default="", help="CSV editable donde Roberto escribe provincia/localidad de los puntos")
    a = ap.parse_args()
    hasta = a.to_date or (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
    override, previos = cargar_override(a.lugares)
    pend = {}
    rows = []
    margen = []
    for carpeta, empresa in (("EMPTR21", "Razo"), ("EMPAG21", "Agetrans")):
        base = os.path.join(a.root, carpeta)
        if not os.path.isdir(base):
            print("Aviso: no esta %s" % base, file=sys.stderr)
            continue
        rows.extend(leer_sociedad(base, empresa, a.from_date, hasta, override, pend))
        margen.extend(leer_margen(base, empresa, a.from_date, hasta))
    for t in rows:
        t["imp"] = round(t["imp"], 2); t["km"] = round(t["km"], 1); t["m3"] = round(t["m3"], 2); t["t"] = round(t["t"], 2)
    out = {"metadata": {"disponible": True, "fuente": "GesRuta operativo (lineas de albaran con cantera + inggas)",
                        "desde": a.from_date, "hasta": hasta, "viajes": len(rows),
                        "leido": datetime.datetime.now().isoformat(timespec="seconds")}, "rows": rows, "margen": margen}
    with open(a.output, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False)
    lug = {"total": 0, "pendientes": 0}
    if a.lugares:
        try:
            total, pendientes = escribir_override(a.lugares, pend, previos)
            lug = {"total": total, "pendientes": pendientes, "escritos": len(override)}
        except OSError as e:
            print("Aviso: no se pudo mantener %s: %s" % (a.lugares, e), file=sys.stderr)
    porEmp = {}
    for t in rows:
        x = porEmp.setdefault(t["c"], {"v": 0, "km": 0.0, "m3": 0.0, "t": 0.0, "imp": 0.0})
        x["v"] += 1; x["km"] += t["km"]; x["m3"] += t["m3"]; x["t"] += t["t"]; x["imp"] += t["imp"]
    mrg = {}
    for a in margen:
        x = mrg.setdefault(a["c"], {"ing": 0.0, "gasto": 0.0})
        x["ing"] += a["ing"]; x["gasto"] += a["materiales"] + a["subcontratacion"] + a["gasoil"] + a["peajes"] + a["adblue"]
    print(json.dumps({"disponible": True, "viajes": len(rows), "lugares": lug,
                      "porEmpresa": {k: {kk: round(vv) for kk, vv in v.items()} for k, v in porEmp.items()},
                      "margen": {k: {"ing": round(v["ing"]), "gasto": round(v["gasto"]), "op": round(v["ing"] - v["gasto"])} for k, v in mrg.items()}}, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # noqa: BLE001
        print("ERROR: %s" % e, file=sys.stderr)
        sys.exit(1)
