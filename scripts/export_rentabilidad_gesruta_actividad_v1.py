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
import argparse, csv, datetime, json, os, re, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dbf_gesruta import abrir


# ---- CSV editable de provincias/localidades por punto (lo rellena Roberto; nosotros lo respetamos y lo mantenemos) ----
CAB_LUGARES = ["Codigo", "Punto", "Viajes", "Falta", "Provincia", "Localidad"]


def cargar_override(path):
    """Devuelve (override, previos). override={cod:{prov,loc}} con lo que Roberto haya escrito (provincia, localidad o las dos);
    previos = todas las filas guardadas."""
    override, previos = {}, {}
    if not path or not os.path.isfile(path):
        return override, previos
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f, delimiter=";"):
            cod = (row.get("Codigo") or "").strip()
            if not cod:
                continue
            prov = norm_prov(row.get("Provincia") or "")
            loc = norm_loc(row.get("Localidad"))
            previos[cod] = {"punto": (row.get("Punto") or "").strip(), "prov": prov, "loc": loc}
            if prov or loc:
                override[cod] = {"prov": prov, "loc": loc}
    return override, previos


def escribir_override(path, pend, previos):
    """Reescribe el CSV preservando lo que Roberto ya escribio; refresca 'Viajes' y 'Falta' y anade los puntos nuevos a los que
    les falta la provincia o la localidad."""
    codigos = set(pend) | set(previos)
    filas = []
    for cod in codigos:
        p = previos.get(cod, {})
        u = pend.get(cod)
        # Se mantiene lo que Roberto ya escribió y lo que sigue pendiente (aparece en pend).
        # Lo que ya resolvió el maestro y él no había tocado, se cae de la lista.
        if not (p.get("prov") or p.get("loc")) and u is None:
            continue
        filas.append({"Codigo": cod, "Punto": (u or {}).get("punto") or p.get("punto") or cod,
                      "Viajes": (u or {}).get("viajes", 0), "Falta": (u or {}).get("falta", ""),
                      "Provincia": p.get("prov", ""), "Localidad": p.get("loc", "")})
    # Primero lo que Roberto aún no ha tocado, de más tráfico a menos: así ataca lo que más pesa.
    filas.sort(key=lambda r: (1 if (r["Provincia"] or r["Localidad"]) else 0, -r["Viajes"], r["Punto"]))
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CAB_LUGARES, delimiter=";")
        w.writeheader()
        w.writerows(filas)
    os.replace(tmp, path)
    return len(filas), sum(1 for r in filas if not (r["Provincia"] or r["Localidad"]))


def limpio_km(v):
    try:
        k = float(v)
        return k if 0 < k <= 300 else 0.0
    except (TypeError, ValueError):
        return 0.0


def norm_mat(m):
    # Matricula comparable (para cruzar con la tabla de horas del localizador): solo letras y numeros, en mayuscula.
    return re.sub(r"[^0-9A-Z]", "", (m or "").upper())


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


def limpio_txt(s):
    # Texto de lugar comparable: mayusculas y espacios simples.
    return " ".join((s or "").upper().split())


def norm_loc(s):
    # Localidad = el PUEBLO (no la planta ni la cantera), normalizado.
    p = limpio_txt(s).strip(" .,;-")
    if p in ("LA CORUNA", "LA CORUÑA", "A CORUNA", "CORUNA", "CORUÑA"):
        return "A CORUÑA"
    if p in ("SANTIAGO", "SANTIAGO COMPOSTELA"):
        return "SANTIAGO DE COMPOSTELA"
    return p


def _leer_lugares_base(base, lugar):
    # Vuelca puntos.dbf + puntcd.dbf de UNA sociedad en el dict compartido 'lugar' (clave=codigo; se rellenan huecos).
    for tabla in ("puntos.dbf", "puntcd.dbf"):
        try:
            t = abrir(base, tabla)
        except IOError:
            continue
        tiene_prov = "PROVINCIA" in t.nombres()
        for r in t.registros():
            c = (t.get(r, "CODIGO") or "").strip()
            if not c:
                continue
            pro = prov_desde(t.get(r, "PROVINCIA") if tiene_prov else "", t.get(r, "PROVIN") if "PROVIN" in t.nombres() else "", t.get(r, "CP"))
            if not pro:
                pro = norm_prov(t.get(r, "PROVIN") or "") if "PROVIN" in t.nombres() else ""
            loc = norm_loc(t.get(r, "LOCALI"))
            nom = limpio_txt(t.get(r, "NOMBRE"))
            prev = lugar.get(c)
            if prev is None:
                lugar[c] = {"pro": pro, "loc": loc, "nom": nom}
            else:  # completar lo que faltaba (misma clave en las dos sociedades = mismo lugar, dato unico global)
                if not prev["pro"] and pro:
                    prev["pro"] = pro
                if not prev["loc"] and loc:
                    prev["loc"] = loc
                if not prev["nom"] and nom:
                    prev["nom"] = nom
        t.cerrar()


def cargar_lugares_global(root, gps=None):
    # Maestro de lugares GLOBAL: Razo + Agetrans JUNTOS, por codigo (Roberto 22/09: las localizaciones son globales,
    # dato unico del grupo). Tres niveles: provincia, LOCALIDAD (pueblo, LOCALI) y PUNTO (planta/cantera/obra, NOMBRE).
    lugar = {}
    for carpeta in ("EMPTR21", "EMPAG21"):
        base = os.path.join(root, carpeta)
        if os.path.isdir(base):
            _leer_lugares_base(base, lugar)
    # Capa GPS GLOBAL: municipio REAL de las paradas de la flota (Wialon/Locatel + OpenStreetMap), por CODIGO (sin empresa).
    # Rellena el pueblo/provincia que el maestro dejo vacios; no pisa un LOCALI escrito a mano. El CSV de Roberto manda.
    if gps:
        for c, x in lugar.items():
            g = gps.get(c)
            if not g:
                continue
            if not x["loc"] and g.get("localidad"):
                x["loc"] = norm_loc(g["localidad"])
            if not x["pro"] and g.get("provincia"):
                x["pro"] = norm_prov(g["provincia"])
    # Puntos sin pueblo en el maestro, cuyo NOMBRE ya dice el pueblo: «CARBALLO», «CORUÑA», o «… (FERROL)».
    # Solo se usa un pueblo que ya existe como LOCALI en el propio maestro (no se inventa ninguno).
    pueblos = {x["loc"] for x in lugar.values() if x["loc"]}
    for x in lugar.values():
        if x["loc"] or not x["nom"]:
            continue
        cand = norm_loc(x["nom"])
        if cand in pueblos:
            x["loc"] = cand
            continue
        m = re.search(r"\(([^()]+)\)\s*$", x["nom"])
        if m:
            p = norm_loc(m.group(1))
            if p in pueblos:
                x["loc"] = p
            else:
                largos = [q for q in pueblos if q.startswith(p + " ")]
                if len(largos) == 1:          # «SANTIAGO» -> «SANTIAGO DE COMPOSTELA» solo si no hay duda
                    x["loc"] = largos[0]
    return lugar


def clasificar_unidad(um, cod, con):
    """Que unidad mueve una linea de viaje real: 'm3' (hormigon), 't' (arido/material) o '' (no medible en esas dos).
    UNIMED suele ir VACIO, asi que se decide tambien por el codigo de concepto (CODCON) y por el texto del concepto.
    Medido sobre 2026: sin esto se perdian ~230.000 t (toneladas de material, servidas, portes) por venir sin unidad."""
    um = (um or "").strip().upper()
    cod = (cod or "").strip().upper()
    con = (con or "").strip().upper()
    # 1) Unidad explicita cuando la hay
    if um in ("M3", "M³", "MC", "MCU"):
        return "m3"
    if um in ("TN", "TM", "T", "TON", "TM.", "TN.", "TNM"):
        return "t"
    if um in ("MM", "ML", "M", "H", "HR", "HRS", "UD", "U", "%", "KM", "€", "EUR"):
        return ""  # metros, horas, unidades, incrementos: ni m3 ni toneladas
    # 2) Por codigo de concepto (los que en 2026 vienen sin UNIMED)
    if cod[:1] == "K" or cod[:2] == "MK" or cod in ("MCU", "M25", "M16", "916"):
        return "m3"
    if cod in ("TNL", "TMS", "908", "930", "933", "966", "904", "907"):
        return "t"
    # 3) Por el texto del concepto (el m3 se mira antes que el porte para no confundir hormigon con arido)
    if "M3" in con or "M³" in con or "CUBICO" in con or "CÚBICO" in con:
        return "m3"
    if "TONELADA" in con:
        return "t"
    if con.startswith("PORTE DE MATERIAL"):
        return "t"
    return ""  # PORTES NACIONALES (P), OBRA UTE ARZUA, incrementos... unidad sin verificar: no se suma


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


def leer_sociedad(base, empresa, desde, hasta, override, pend, lugar, impro_excl):
    # maestro de clientes: codigo -> nombre (mascli.dbf)
    clientes = {}
    mc = abrir(base, "mascli.dbf")
    for r in mc.registros():
        cod = (mc.get(r, "CODIGO") or "").strip()
        if cod:
            clientes[cod] = (mc.get(r, "NOMBRE") or "").strip()
    mc.cerrar()
    # fecha de servicio + cliente + FACTURADO (el albaran lleva su nº de factura, serie y fecha) por (viaje, albaran).
    # El INGRESO se ancla a lo FACTURADO (albaran con NUMFAC): cuadra con la facturacion de GesRuta y la contabilidad.
    # Un albaran sin NUMFAC es trabajo ENTREGADO PENDIENTE DE FACTURAR (del año en curso): no se cuenta todavia.
    alb = abrir(base, "albara.dbf")
    cab = {}
    for r in alb.registros():
        v, n = alb.get(r, "VIAJE"), alb.get(r, "NUMERO")
        if v is None or n is None:
            continue
        cod = (alb.get(r, "CLIENT") or "").strip()
        cab[(str(v), str(n))] = {"fecha": alb.get(r, "DESDEF") or alb.get(r, "FECHA"),
                                 "cliente": clientes.get(cod, cod),
                                 "facturado": bool(str(alb.get(r, "NUMFAC") or "").strip()),
                                 "delega": str(alb.get(r, "DELEGACLIE") or "").strip()}
    alb.cerrar()
    # matricula por viaje
    vj = abrir(base, "viaje.dbf")
    matr = {}
    for r in vj.registros():
        v = vj.get(r, "CODIGO")          # la clave del viaje en viaje.dbf es CODIGO (no VIAJE)
        if v is not None:
            matr[str(v)] = {"mat": (vj.get(r, "MATRI1") or "").strip(), "cho": (vj.get(r, "CHOFER1") or "").strip()}
    vj.cerrar()
    # lugares: dict GLOBAL (Razo+Agetrans) ya construido en main y pasado aqui (dato unico de localizacion)

    def rprov(code):  # el CSV de Roberto manda; si no, el maestro de lugares
        ov = override.get(code)
        return (ov and ov.get("prov")) or lugar.get(code, {}).get("pro", "")

    def rloc(code):
        ov = override.get(code)
        return (ov and ov.get("loc")) or lugar.get(code, {}).get("loc", "")

    def rnom(code):  # el PUNTO concreto (planta, cantera, obra): su nombre en el maestro, o su código
        return lugar.get(code, {}).get("nom", "") or (code or "")

    def apuntar_pendiente(code):  # punto usado sin provincia o sin localidad -> a la lista para que Roberto lo complete
        if not code:
            return
        sin_p, sin_l = not rprov(code), not rloc(code)
        if sin_p or sin_l:
            p = pend.setdefault(code, {"punto": "", "viajes": 0, "falta": ""})
            p["viajes"] += 1
            if not p["punto"]:
                p["punto"] = lugar.get(code, {}).get("nom", "") or code
            p["falta"] = "provincia y localidad" if (sin_p and sin_l) else ("provincia" if sin_p else "localidad")

    # lineas: agregacion por (viaje, cantera) = viaje real
    ln = abrir(base, "lineas.dbf")
    trips = {}
    for r in ln.registros():
        v, a = str(ln.get(r, "VIAJE")), str(ln.get(r, "ALBARA"))
        c = cab.get((v, a))
        d = c["fecha"] if c else None
        if not d or not (d.year >= int(desde[:4]) and d.isoformat() >= desde and d.isoformat() <= hasta):
            continue
        if not c.get("facturado"):      # albaran aun sin facturar: no se cuenta (el ingreso se ancla a lo FACTURADO)
            continue
        c1 = ln.get(r, "CAMPO1")
        tiene_cantera = bool(c1 and str(c1).strip())
        # Viaje REAL: con «Alb. cantera» (arido/hormigon) por (viaje, cantera). Los NACIONALES subcontratados no llevan
        # cantera; su viaje = el ALBARAN, y su coste real es lo que se paga al subcontratista (IMPPRO). Sin capturarlos
        # se dejaba fuera casi todo su ingreso pero se les colgaba el coste -> margenes absurdos (Roberto 22/09).
        cant = str(c1).strip() if tiene_cantera else ""
        key = (v, cant) if tiene_cantera else (v, "@" + a)
        unidad = clasificar_unidad(ln.get(r, "UNIMED"), ln.get(r, "CODCON"), ln.get(r, "CONCEP"))
        t = trips.get(key)
        if t is None:
            o, dest = (ln.get(r, "ORIGEN") or "").strip(), (ln.get(r, "DESTINO") or "").strip()
            apuntar_pendiente(o); apuntar_pendiente(dest)
            t = trips[key] = {"c": empresa, "v": v, "cant": cant, "mat": matr.get(v, {}).get("mat", ""), "cho": matr.get(v, {}).get("cho", ""), "mes": d.isoformat()[:7], "dia": d.isoformat(),
                              "cli": c["cliente"] if c else "", "o": o, "d": dest,
                              "op": rprov(o), "ol": rloc(o), "on": rnom(o),
                              "dp": rprov(dest), "dl": rloc(dest), "dn": rnom(dest),
                              "km": 0.0, "m3": 0.0, "t": 0.0, "imp": 0.0, "impro": 0.0, "horm": False, "nac": not tiene_cantera}
        imp_val = ln.get(r, "IMPORT") or 0
        impro_val = ln.get(r, "IMPPRO") or 0     # coste REAL del subcontratista por linea (cuadra con la cuenta 607); viaje con impro>0 = subcontratado
        if impro_val > 15000 and impro_val > imp_val * 8:   # coste de subcontrata IMPOSIBLE en una linea (error de tecleo en GesRuta, p. ej. 170.108 en un porte de 430): no sumar, anotar
            impro_excl.append({"empresa": empresa, "viaje": v, "albaran": a, "impro": round(impro_val), "importe": round(imp_val), "cliente": (c["cliente"] if c else "")})
            impro_val = 0
        t["imp"] += imp_val
        t["impro"] += impro_val
        cr = ln.get(r, "CANTIDREAL") or ln.get(r, "CANTID") or 0
        if unidad == "m3":
            t["m3"] += cr; t["horm"] = True
            t["km"] += limpio_km(ln.get(r, "CAMPO2"))   # «Km. Viaje» solo tiene sentido en hormigon; el arido se triangula
        elif unidad == "t":
            t["t"] += cr
    ln.cerrar()
    # Nacionales sin cantera: solo se quedan los SUBCONTRATADOS (impro>0), que traen su coste real. Los de coste propio
    # sin cantera (no triangulan, sin km/horas fiables) se dejan fuera por ahora, para no inventarles un coste.
    return [t for t in trips.values() if t.get("cant") or t.get("impro", 0) > 0]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True, help="Carpeta Gesruta (con EMPTR21 y EMPAG21)")
    ap.add_argument("--output", required=True)
    ap.add_argument("--from-date", default="2025-01-01")
    ap.add_argument("--to-date", default="")
    ap.add_argument("--lugares", default="", help="CSV editable donde Roberto escribe provincia/localidad de los puntos")
    ap.add_argument("--gps", default="", help="JSON con el municipio real de cada punto segun las paradas GPS de la flota")
    ap.add_argument("--triangulado", default="", help="triangulado_v1.json: km/litros/duracion reales por viaje (bases de reparto del coste)")
    ap.add_argument("--horas", default="", help="horas_vehiculo_mes.json: minutos MEDIDOS por matricula|mes (para dar horas reales al hormigon)")
    a = ap.parse_args()
    hasta = a.to_date or (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
    override, previos = cargar_override(a.lugares)
    gps = {}
    if a.gps and os.path.isfile(a.gps):
        try:
            gps = json.load(open(a.gps, encoding="utf-8"))
        except (OSError, ValueError) as e:
            print("Aviso: no se pudo leer --gps %s: %s" % (a.gps, e), file=sys.stderr)
    lugar = cargar_lugares_global(a.root, gps)   # maestro de lugares GLOBAL (Razo+Agetrans), una sola vez
    # triangulacion: km/litros/duracion reales por (empresa,viaje,cantera) -> bases de reparto del coste
    tri, Lp100, tri_resumen = {}, 40.0, None
    if a.triangulado and os.path.isfile(a.triangulado):
        try:
            td = json.load(open(a.triangulado, encoding="utf-8"))
            trows = td if isinstance(td, list) else (td.get("rows") or td.get("viajes") or next((x for x in td.values() if isinstance(x, list)), []))
            if isinstance(td, dict) and td.get("resumen"):
                rs, mt = td["resumen"], td.get("meta") or {}
                tri_resumen = {"version": mt.get("version"), "generado": mt.get("generado"), "viajes": rs.get("viajes"),
                               "medido": (rs.get("medido_por_viaje") or {}).get("viajes"), "pct": (rs.get("medido_por_viaje") or {}).get("pct"),
                               "aridos_pct": (rs.get("medido_por_viaje") or {}).get("aridos_pct"),
                               "alta": (rs.get("confianza_medidos") or {}).get("alta"), "media": (rs.get("confianza_medidos") or {}).get("media"),
                               "taco": rs.get("horas_del_tacografo"), "chofer_ok": (rs.get("chofer_coincide_gesruta") or {}).get("True"),
                               "chofer_no": (rs.get("chofer_coincide_gesruta") or {}).get("False"),
                               "nocturnas": (rs.get("jornadas") or {}).get("nocturnas"), "sin_ciclo": rs.get("viajes_sin_ciclo"),
                               "sobrantes_h": rs.get("horas_sobrantes_sin_viaje"), "largas": rs.get("larga_distancia_pendiente_pasada_2"),
                               "repetidas": rs.get("cantera_repetida_error_grabacion"), "sin_traza": sum((rs.get("sin_traza_por_motivo") or {}).values())}
            kmt = litt = 0.0
            for r in trows:
                tri[(r.get("empresa"), str(r.get("viaje")), str(r.get("cantera")))] = r
                kmt += r.get("km") or 0
                litt += r.get("litros_calibrados") or r.get("litros") or 0
            if kmt:
                Lp100 = round(litt / kmt * 100, 2)   # consumo medio real de la flota (para el hormigon sin litros)
        except (OSError, ValueError) as e:
            print("Aviso: no se pudo leer --triangulado %s: %s" % (a.triangulado, e), file=sys.stderr)
    horas = {}
    if a.horas and os.path.isfile(a.horas):
        try:
            horas = json.load(open(a.horas, encoding="utf-8"))
        except (OSError, ValueError) as e:
            print("Aviso: no se pudo leer --horas %s: %s" % (a.horas, e), file=sys.stderr)
    pend = {}
    rows = []
    margen = []
    impro_excl = []
    for carpeta, empresa in (("EMPTR21", "Razo"), ("EMPAG21", "Agetrans")):
        base = os.path.join(a.root, carpeta)
        if not os.path.isdir(base):
            print("Aviso: no esta %s" % base, file=sys.stderr)
            continue
        rows.extend(leer_sociedad(base, empresa, a.from_date, hasta, override, pend, lugar, impro_excl))
        margen.extend(leer_margen(base, empresa, a.from_date, hasta))
    # Pegar a cada viaje su km/litros/horas REALES (bases de reparto). Aridos/nacional: de la triangulacion. Hormigon:
    # km nativo (CAMPO2) y HORAS REALES del localizador (jornadas por matricula/mes, repartidas por km entre los viajes de
    # hormigon de ese vehiculo) cuando las hay; si no, estimadas. La fuente queda en 'trm'.
    hormKm = {}
    if horas:
        for t in rows:
            if not tri.get((t["c"], t["v"], t["cant"])) and t["km"] > 0:
                k = (norm_mat(t["mat"]), t["mes"])
                hormKm[k] = hormKm.get(k, 0.0) + t["km"]
    for t in rows:
        tr = tri.get((t["c"], t["v"], t["cant"]))
        if tr and tr.get("fecha"):
            t["dia"] = tr["fecha"]          # fecha REAL de servicio (traza GPS) donde la hay; si no, la del albarán
        if tr and (tr.get("km") or 0) > 0:
            t["kmr"] = round(tr.get("km") or 0, 1)
            t["lit"] = round(tr.get("litros_calibrados") or tr.get("litros") or (t["kmr"] * Lp100 / 100), 1)
            dur = tr.get("duracion_min")
            t["dur"] = round(dur, 0) if dur else (round(40 + t["kmr"] / 22.0 * 60, 0) if t["kmr"] else None)
            t["trm"] = "repartido" if tr.get("repartido") else "medido"
        if tr and tr.get("t_ini"):
            # triangulado v2: hora real de inicio/fin, orden del dia, desglose de minutos (tacografo o traza), metodo,
            # confianza, chofer que llevaba el camion (tacografo) y jornada nocturna. TODO VISIBLE en el informe.
            t["tini"] = tr.get("t_ini"); t["tfin"] = tr.get("t_fin"); t["ord"] = tr.get("orden_dia")
            t["mcon"] = tr.get("min_conduccion"); t["mesp"] = tr.get("min_espera"); t["motr"] = tr.get("min_otros")
            t["met"] = tr.get("metodo"); t["conf"] = tr.get("confianza"); t["chot"] = tr.get("chofer_tacografo")
            t["noct"] = bool(tr.get("jornada_nocturna")); t["med"] = bool(tr.get("medido")); t["mfu"] = tr.get("min_fuente")
        elif tr:
            t["ord"] = tr.get("orden_dia"); t["met"] = tr.get("metodo"); t["conf"] = tr.get("confianza"); t["med"] = False
        else:
            t["kmr"] = round(t["km"], 1)                                  # hormigon: km nativo (Km. Viaje)
            t["lit"] = round(t["kmr"] * Lp100 / 100, 1) if t["kmr"] else 0.0
            hm = horas.get(norm_mat(t["mat"]) + "|" + t["mes"]) if horas else None
            tk = hormKm.get((norm_mat(t["mat"]), t["mes"]), 0.0)
            if hm and tk > 0 and t["km"] > 0:
                t["dur"] = round(hm * t["km"] / tk, 0)                    # horas MEDIDAS del vehiculo, repartidas por km
                t["trm"] = "repartido"
            else:
                t["dur"] = round(40 + t["kmr"] / 22.0 * 60, 0) if t["kmr"] else None
                t["trm"] = "hormigon" if t["horm"] else "sin"
        t["imp"] = round(t["imp"], 2); t["km"] = round(t["km"], 1); t["m3"] = round(t["m3"], 2); t["t"] = round(t["t"], 2)
    # Coordenadas por NOMBRE de punto (planta/cantera/obra), para el MAPA: el informe agrega los viajes del periodo
    # elegido por su punto de origen/destino y une aqui la coordenada del localizador (paradas GPS de la flota).
    coords = {}
    for cod, g in gps.items():
        if not isinstance(g, dict) or g.get("lat") in (None, "") or g.get("lon") in (None, ""):
            continue
        nom = (lugar.get(cod, {}).get("nom") or cod)
        if nom and nom not in coords:
            coords[nom] = [round(g["lat"], 5), round(g["lon"], 5), g.get("localidad") or "", g.get("provincia") or ""]
    out = {"metadata": {"disponible": True, "fuente": "GesRuta operativo (lineas de albaran: cantera=arido/hormigon, o nacional subcontratado por albaran; coste subcontrata=IMPPRO; inggas)",
                        "desde": a.from_date, "hasta": hasta, "viajes": len(rows),
                        "improExcluidos": impro_excl, "coords": coords, "triangulado": tri_resumen,
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
