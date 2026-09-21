# -*- coding: utf-8 -*-
"""Actividad operativa de GesRuta para el informe de rentabilidad. SOLO LECTURA.

El VIAJE de GesRuta es un CONTENEDOR (agrupa varias entregas de un camion/chofer y fija el cliente y la fecha). El VIAJE
REAL es cada linea de albaran con valor en «Alb. cantera» (campo CAMPO1); su km, sobre todo en hormigon, es «Km. Viaje»
(campo CAMPO2). Aqui se cuentan asi: una fila por (viaje, cantera), con sus m3/toneladas, km, importe, matricula y
origen/destino->provincia. Verificado con las capturas de Roberto (viajes 00029968 hormigon, 00029471 aridos).

Lee cinco tablas por sociedad (EMPTR21 Razo, EMPAG21 Agetrans): lineas (lineas de albaran), albara (fecha de servicio y
cliente), viaje (matricula y chofer), puntcd (maestro de lugares: provincia/localidad). Nunca escribe.
"""
import argparse, datetime, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dbf_gesruta import abrir


def limpio_km(v):
    try:
        k = float(v)
        return k if 0 < k <= 300 else 0.0
    except (TypeError, ValueError):
        return 0.0


def norm_prov(s):
    # Provincia como NOMBRE en puntcd; se unifican variantes obvias del mismo territorio.
    p = (s or "").strip().upper()
    if not p:
        return ""
    if p in ("LA CORUNA", "LA CORUÑA", "A CORUNA", "CORUNA", "CORUÑA", "LA CORUÑA."):
        return "A CORUÑA"
    if p in ("ORENSE",):
        return "OURENSE"
    return p


def leer_sociedad(base, empresa, desde, hasta):
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
    # lugares: codigo -> provincia, localidad
    lugar = {}
    pc = abrir(base, "puntcd.dbf")
    for r in pc.registros():
        c = (pc.get(r, "CODIGO") or "").strip()
        if c:
            loc = (pc.get(r, "LOCALI") or "").strip()
            nom = (pc.get(r, "NOMBRE") or "").strip()
            # Cuando el punto no trae localidad (canteras/plantas del histórico), su nombre es la mejor etiqueta.
            lugar[c] = {"pro": norm_prov(pc.get(r, "PROVIN") or ""), "loc": loc or nom, "nom": nom}
    pc.cerrar()
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
            t = trips[key] = {"c": empresa, "v": v, "cant": cant, "mat": matr.get(v, {}).get("mat", ""), "cho": matr.get(v, {}).get("cho", ""), "mes": d.isoformat()[:7],
                              "cli": c["cliente"] if c else "", "o": o, "d": dest,
                              "op": norm_prov(lugar.get(o, {}).get("pro", "")), "ol": lugar.get(o, {}).get("loc", "").strip(),
                              "dp": norm_prov(lugar.get(dest, {}).get("pro", "")), "dl": lugar.get(dest, {}).get("loc", "").strip(),
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
    a = ap.parse_args()
    hasta = a.to_date or (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
    rows = []
    for carpeta, empresa in (("EMPTR21", "Razo"), ("EMPAG21", "Agetrans")):
        base = os.path.join(a.root, carpeta)
        if not os.path.isdir(base):
            print("Aviso: no esta %s" % base, file=sys.stderr)
            continue
        rows.extend(leer_sociedad(base, empresa, a.from_date, hasta))
    for t in rows:
        t["imp"] = round(t["imp"], 2); t["km"] = round(t["km"], 1); t["m3"] = round(t["m3"], 2); t["t"] = round(t["t"], 2)
    out = {"metadata": {"disponible": True, "fuente": "GesRuta operativo (lineas de albaran con cantera + inggas)",
                        "desde": a.from_date, "hasta": hasta, "viajes": len(rows),
                        "leido": datetime.datetime.now().isoformat(timespec="seconds")}, "rows": rows}
    with open(a.output, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False)
    porEmp = {}
    for t in rows:
        x = porEmp.setdefault(t["c"], {"v": 0, "km": 0.0, "m3": 0.0, "t": 0.0, "imp": 0.0})
        x["v"] += 1; x["km"] += t["km"]; x["m3"] += t["m3"]; x["t"] += t["t"]; x["imp"] += t["imp"]
    print(json.dumps({"disponible": True, "viajes": len(rows), "porEmpresa": {k: {kk: round(vv) for kk, vv in v.items()} for k, v in porEmp.items()}}, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # noqa: BLE001
        print("ERROR: %s" % e, file=sys.stderr)
        sys.exit(1)
