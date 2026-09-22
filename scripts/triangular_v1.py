# -*- coding: utf-8 -*-
"""Triangulacion viaje <-> traza del localizador (Wialon y Locatel) -> km, duracion y litros por VIAJE REAL de
aridos/nacional. SOLO LECTURA sobre todas las fuentes. Nunca inventa: cada viaje lleva su metodo.

Niveles por viaje (siempre explicito en 'metodo'):
  geo    : todos los viajes del dia casan por geografia (parada cerca del origen y luego parada cerca del destino, en
           orden) -> ciclos medidos sobre la traza.
  orden  : sin geografia completa: el lugar de carga del dia se reconoce en la propia traza (paradas que se repiten
           tantas veces como viajes) y los ciclos se asignan a los viajes por su secuencia en GesRuta (viaje, cantera).
  dia    : suelo seguro: km/duracion/litros MEDIDOS del dia, repartidos a partes iguales entre los viajes de ese
           camion ese dia ('repartido': true si hay mas de uno; con un solo viaje el dia entero es suyo).
  sin_traza : no hay traza de ese camion ese dia (subcontrata sin telemetria, o pendiente de bajar). Sin dato.

Ciclo = desde el fin del ciclo anterior (o inicio de jornada) hasta la salida de la parada de descarga; el ultimo
ciclo llega al fin de jornada (incluye la vuelta). Asi la suma de los viajes del dia = la jornada medida.

Coordenadas de lugares (mejor disponible): gps_aprendida (paradas propias) > gesruta (maestro) > nominatim_exacto >
nominatim_localidad > manual. Aprende la coordenada REAL de cada lugar frecuente agrupando las paradas de nuestros
camiones en los dias que GesRuta dice que fueron alli (con contraste frente a los dias que no fueron, para no confundir
la base con la planta). Salidas: coords_aprendidas_v1.json (+ _por_casa) y coords_discrepancias_v1.json (>5 km).

Consumo: tabla de calibracion del sensor (la del ERP, sensores_erp.json) + reduccion MONOTONA del contador (la del
ERP: 0063NBM 18/09 = 56,5 L, no 64,0 que salia sumando el jitter de 0,5 L).
"""
import argparse, collections, glob, json, math, os, re, statistics, sys

D = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(os.path.dirname(D), "rentabilidad-extract", "scripts")
sys.path.insert(0, SCRIPTS)
GESRUTA = r"\\SERVIDOR\Programas\Gesruta"
GEOCODE_DIR = os.path.join(os.path.dirname(D), "geocode")
CASAS = {"EMPTR21": "Razo", "EMPAG21": "Agetrans"}
RANGO = {"gps_aprendida": 0, "gesruta": 1, "nominatim_exacto": 2, "nominatim_localidad": 3, "manual": 4, "dudoso": 5}
# 'dudoso' NO se usa para emparejar (demasiado incierto): solo como punto de partida amplio para aprender.
RADIO_MATCH = {"gesruta": 1.0, "nominatim_exacto": 1.0, "nominatim_localidad": 5.0, "manual": 3.0, "dudoso": None}
RADIO_APRENDER = {"gesruta": 3.0, "nominatim_exacto": 5.0, "nominatim_localidad": 12.0, "manual": 8.0, "dudoso": 25.0}
DWELL_S = 300          # parada = >= 5 min parado
V_PARADO = 3.0         # km/h
V_MOVIL = 5.0


def clean(v):
    return re.sub(r"[^0-9A-Z]", "", (v or "").upper())


def hav(a, b):
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * 6371.0088 * math.asin(math.sqrt(h))


def casa_norm(s):
    s = (s or "").strip().lower()
    if s.startswith("emptr") or s.startswith("raz") or s == "r":
        return "Razo"
    if s.startswith("empag") or s.startswith("aget") or s == "a":
        return "Agetrans"
    return s or "Razo"


# ---------------------------------------------------------------- coordenadas de referencia
def coords_gesruta():
    from dbf_gesruta import abrir
    out = {}
    for carpeta, casa in CASAS.items():
        for tabla in ("puntos.dbf", "puntcd.dbf"):
            try:
                db = abrir(os.path.join(GESRUTA, carpeta), tabla)
            except IOError:
                continue
            for r in db.registros():
                c = (db.get(r, "CODIGO") or "").strip()
                la, lo = db.get(r, "LATITUD"), db.get(r, "LONGITUD")
                if c and la and lo and abs(la) > 0.01 and abs(lo) > 0.01 and (casa, c) not in out:
                    out[(casa, c)] = {"lat": float(la), "lon": float(lo), "fuente": "gesruta"}
            db.cerrar()
    return out


def fuente_de(v):
    conf = str(v.get("confianza") or "").lower()
    f = str(v.get("fuente") or "").lower()
    if f == "gesruta" or conf == "gesruta":
        return "gesruta"
    if f == "manual" or conf == "manual":
        return "manual"
    if conf == "exacto":
        return "nominatim_exacto"
    if conf == "dudoso":
        return "dudoso"
    return "nominatim_localidad"


def coords_geocode():
    """SOLO coords_lugares_por_casa.json, por (empresa, codigo). El plano NO: 11 codigos significan lugares distintos en
    Razo y en Agetrans. Si el fichero no existe, devuelve {} y la triangulacion sigue con lo que hay."""
    out = {}
    pc = os.path.join(GEOCODE_DIR, "coords_lugares_por_casa.json")
    try:
        if os.path.isfile(pc):
            for k, v in json.load(open(pc, encoding="utf-8")).items():
                if not isinstance(v, dict) or v.get("lat") is None or v.get("lon") is None:
                    continue
                casa, _, cod = k.partition("|")
                out[(casa_norm(casa), cod.strip())] = {"lat": float(v["lat"]), "lon": float(v["lon"]), "fuente": fuente_de(v),
                                                       "nombre": v.get("nombre")}
    except (ValueError, OSError) as e:
        print("Aviso: geocode ilegible (%s); se sigue sin el" % e, file=sys.stderr)
    return out


def mejor(*dicts_por_clave):
    """Combina fuentes quedandose, por clave, con la de mejor rango."""
    out = {}
    for d in dicts_por_clave:
        for k, v in d.items():
            if k not in out or RANGO[v["fuente"]] < RANGO[out[k]["fuente"]]:
                out[k] = v
    return out


# ---------------------------------------------------------------- trazas
def cargar_trazas():
    """(matricula, dia) -> {fuente, pts[], km_dia_fuente}. Si hay Wialon y Locatel del mismo dia, manda Wialon (litros)."""
    tr = {}
    for fuente, patron in (("locatel", os.path.join(D, "locatel_hist", "traza_*.json")),
                           ("wialon", os.path.join(D, "wialon_hist", "traza_*.json")),
                           ("wialon", os.path.join(D, "wialon_hist_pase2", "traza_*.json"))):  # la 2a pasada pisa a la 1a
        for ruta in glob.glob(patron):
            try:
                x = json.load(open(ruta, encoding="utf-8"))
            except (ValueError, OSError):
                continue
            p = clean(x.get("mat") or x.get("unidad"))
            dia = x.get("dia")
            pts = []
            for q in x.get("traza") or []:
                if q.get("lat") is None or q.get("t") is None:
                    continue
                pts.append({"t": int(q["t"]), "lat": q["lat"], "lon": q["lon"], "s": q.get("s") or 0.0,
                            "kmc": q.get("kmc"), "litc": q.get("litc"), "rec": q.get("rec"),
                            "parada_min": q.get("parada_min"), "pob": q.get("pob")})
            pts.sort(key=lambda q: q["t"])
            if not p or not dia or len(pts) < 3:
                continue
            if fuente == "wialon" and not any(q["kmc"] is not None or q["litc"] is not None for q in pts) and (p, dia) in tr:
                continue  # traza vieja de prueba sin contadores: no pisa a otra
            tr[(p, dia)] = {"fuente": fuente, "pts": pts, "km_fuente_dia": x.get("km_fuente")}
    return tr


def paradas(pts, fuente):
    out = []
    if fuente == "locatel":
        for i, q in enumerate(pts):
            if (q.get("parada_min") or 0) >= DWELL_S / 60:
                out.append({"t_in": q["t"], "t_out": q["t"] + int(q["parada_min"] * 60), "lat": q["lat"], "lon": q["lon"], "i": i, "j": i})
        return out
    i, n = 0, len(pts)
    while i < n:
        if (pts[i]["s"] or 0) <= V_PARADO:
            j = i
            while j + 1 < n and (pts[j + 1]["s"] or 0) <= V_PARADO:
                j += 1
            if pts[j]["t"] - pts[i]["t"] >= DWELL_S:
                seg = pts[i:j + 1]
                out.append({"t_in": pts[i]["t"], "t_out": pts[j]["t"],
                            "lat": statistics.median(q["lat"] for q in seg), "lon": statistics.median(q["lon"] for q in seg),
                            "i": i, "j": j})
            i = j + 1
        else:
            i += 1
    return out


def jornada(pts):
    mov = [q["t"] for q in pts if (q["s"] or 0) > V_MOVIL]
    if not mov:
        return None, None
    return mov[0], mov[-1]


def internas(ps, j0, j1):
    """Paradas dentro de la jornada (fuera la de la noche/base al principio y al final)."""
    return [p for p in ps if j0 is not None and p["t_out"] > j0 and p["t_in"] < j1]


# ---------------------------------------------------------------- contadores (km / litros)
def aplicar_tabla(v, tabla):
    if v is None:
        return None
    segs = [s for s in (tabla or [{"x": 10.0, "a": 1.0, "b": 0.0}]) if v >= s["x"]]
    if not segs:
        return None
    s = max(segs, key=lambda s: s["x"])
    if s["a"] == 0:           # centinela del ERP (x*0-348201): lectura basura
        return None
    return s["a"] * v + s["b"]


def reducir(serie, ritmo_max):
    """Contador acumulado -> consumido. Monotono como el ERP: ignora retrocesos pequenos (jitter), rebasa en un reset
    o en un salto imposible (ritmo_max unidades/minuto)."""
    buena = tb = None
    tot = 0.0
    for t, v in serie:
        if v is None:
            continue
        if buena is None:
            buena, tb = v, t; continue
        d = v - buena
        tope = max(5.0, ritmo_max * max(1.0, (t - tb) / 60.0))
        if d >= 0:
            if d <= tope:
                tot += d
            buena, tb = v, t
        elif -d > tope:
            buena, tb = v, t
    return tot


def km_gps(pts):
    tot = 0.0
    for a, b in zip(pts, pts[1:]):
        d = hav((a["lat"], a["lon"]), (b["lat"], b["lon"]))
        if 0.02 <= d <= 20:
            tot += d
    return tot


def medir(tr, t0, t1, tablas, d0=None, d1=None):
    """km, litros (crudo monotono), litros_calibrados entre t0 y t1 (contadores) y minutos entre d0 y d1 (jornada)."""
    pts = [q for q in tr["pts"] if t0 <= q["t"] <= t1]
    d0 = t0 if d0 is None else max(t0, d0)
    d1 = t1 if d1 is None else min(t1, d1)
    dur = round(max(0, d1 - d0) / 60.0, 1)
    if tr["fuente"] == "locatel":
        km = sum((q.get("rec") or 0) for q in pts[1:])
        return {"km": round(km, 2), "km_fuente": "locatel_recorrido", "litros": None, "litros_calibrados": None, "duracion_min": dur}
    tk, tf = (tablas or {}).get("tabla_km"), (tablas or {}).get("tabla_fuel")
    ks = [(q["t"], aplicar_tabla(q["kmc"], tk)) for q in pts if q["kmc"] is not None]
    km = reducir(ks, 2.5) if len(ks) >= 2 else None
    fuente_km = "can_mileage"
    if not km:
        km, fuente_km = km_gps(pts), "gps"
    lr = [(q["t"], q["litc"]) for q in pts if q["litc"] is not None and q["litc"] > 0]
    lc = [(q["t"], aplicar_tabla(q["litc"], tf)) for q in pts if q["litc"] is not None]
    lit = reducir(lr, 2.0) if len(lr) >= 2 else None
    litc = reducir(lc, 2.0) if len([v for _, v in lc if v is not None]) >= 2 else None
    return {"km": round(km, 2) if km is not None else None, "km_fuente": fuente_km,
            "litros": round(lit, 2) if lit else None, "litros_calibrados": round(litc, 2) if litc else None,
            "duracion_min": dur}


# ---------------------------------------------------------------- aprender coordenadas de las paradas
def agrupar(puntos, eps_km=0.25):
    """Agrupamiento voraz por cercania (centroide = media incremental); al final, centroide = mediana de miembros."""
    grupos = []
    for p in puntos:
        for g in grupos:
            if hav((g["lat"], g["lon"]), (p["lat"], p["lon"])) <= eps_km:
                g["m"].append(p); g["sl"] += p["lat"]; g["so"] += p["lon"]
                g["lat"] = g["sl"] / len(g["m"]); g["lon"] = g["so"] / len(g["m"])
                break
        else:
            grupos.append({"lat": p["lat"], "lon": p["lon"], "m": [p], "sl": p["lat"], "so": p["lon"]})
    for g in grupos:
        g["lat"] = statistics.median(x["lat"] for x in g["m"]); g["lon"] = statistics.median(x["lon"] for x in g["m"])
    return grupos


def aprender(dem, trazas, paradas_de, ref, min_viajes=5, min_dias=3, min_viajes_sin_ref=30):
    """Coordenada REAL de cada lugar frecuente = el grupo de paradas propias que se repite en los dias que GesRuta dice
    que el camion fue alli y NO se repite en los dias que no fue (contraste: asi la base/cochera no gana)."""
    por_lugar = collections.defaultdict(set)   # (casa, cod) -> {(mat, dia)} con viaje alli
    n_viajes = collections.Counter()
    for t in dem:
        for cod in (t["o"], t["d"]):
            if cod:
                por_lugar[(t["c"], cod)].add((t["mat"], t["dia"]))
                n_viajes[(t["c"], cod)] += 1
    dias_por_mat = collections.defaultdict(set)
    for (m, d) in trazas:
        dias_por_mat[m].add(d)
    def intentar(rel, visitas, p0):
        """Con referencia: paradas dentro de su radio. Sin referencia (o si la referencia no lleva a nada): todas las
        paradas de esos dias, con umbrales mas estrictos. Devuelve el mejor grupo o None."""
        r0 = RADIO_APRENDER[p0["fuente"]] if p0 else None
        cand = []
        for k in rel:
            for s in paradas_de[k]:
                if r0 is None or hav((s["lat"], s["lon"]), (p0["lat"], p0["lon"])) <= r0:
                    cand.append({"lat": s["lat"], "lon": s["lon"], "k": k})
        if not cand:
            return None
        mats = {m for m, _ in rel}
        nrel = [(m, d) for m in mats for d in dias_por_mat[m] if (m, d) not in visitas]
        grupos = agrupar(cand)
        for g in grupos:
            g["dias"] = {x["k"] for x in g["m"]}
        grupos = sorted((g for g in grupos if len(g["dias"]) >= (min_dias if p0 else 4)), key=lambda g: -len(g["dias"]))[:8]
        mejor_g, mejor_score = None, -9
        for g in grupos:
            f_rel = len(g["dias"]) / float(len(rel))
            f_no = 0.0
            if nrel:
                con = sum(1 for k in nrel if any(hav((s["lat"], s["lon"]), (g["lat"], g["lon"])) <= 0.3 for s in paradas_de[k]))
                f_no = con / float(len(nrel))
            g["f_rel"], g["f_no"] = f_rel, f_no
            score = f_rel - f_no
            if f_rel >= (0.3 if p0 else 0.5) and score > mejor_score:
                mejor_g, mejor_score = g, score
        if not mejor_g or mejor_score < (0.2 if p0 else 0.4):
            return None
        return mejor_g

    aprendidas, revisar = {}, []
    for lugar, visitas in por_lugar.items():
        p0 = ref.get(lugar)
        if n_viajes[lugar] < (min_viajes if p0 else min_viajes_sin_ref):
            continue
        rel = [k for k in visitas if k in trazas]
        if len(rel) < (min_dias if p0 else 4):
            continue
        mejor_g = intentar(rel, visitas, p0) if p0 else None
        via = "con_referencia"
        if mejor_g is None and n_viajes[lugar] >= min_viajes_sin_ref and len(rel) >= 4:
            mejor_g = intentar(rel, visitas, None)     # la referencia no llevo a nada (p.ej. 'exacto' equivocado)
            via = "sin_referencia"
        if mejor_g is None:
            continue
        dist = sorted(hav((x["lat"], x["lon"]), (mejor_g["lat"], mejor_g["lon"])) * 1000 for x in mejor_g["m"])
        radio = dist[int(0.9 * (len(dist) - 1))] if dist else 0
        reg = {"lat": round(mejor_g["lat"], 6), "lon": round(mejor_g["lon"], 6), "fuente": "gps_aprendida",
               "dias": len(mejor_g["dias"]), "camiones": len({m for m, _ in mejor_g["dias"]}), "radio_m": int(radio),
               "paradas": len(mejor_g["m"]), "casa": lugar[0], "usos_demanda_2026": n_viajes[lugar],
               "frac_dias_con_visita": round(mejor_g["f_rel"], 2), "frac_dias_sin_visita": round(mejor_g["f_no"], 2),
               "referencia": p0["fuente"] if p0 else None,
               "dist_referencia_km": round(hav((mejor_g["lat"], mejor_g["lon"]), (p0["lat"], p0["lon"])), 2) if p0 else None}
        # PLAUSIBILIDAD del reintento sin referencia: en un viaje NACIONAL la fecha de GesRuta suele ser el dia de CARGA
        # (en Galicia), y el contraste "aprenderia" la carga como si fuera el destino (MECO o CABANILLAS a 500 km).
        # Solo se usa si queda cerca de la referencia (<=150 km) y con evidencia fuerte; si no, manda la referencia.
        fuerte = reg["dias"] >= 5 and reg["camiones"] >= 2 and reg["frac_dias_sin_visita"] <= 0.25
        usada = True
        if via == "sin_referencia" and p0 and (reg["dist_referencia_km"] > 150 or not fuerte):
            usada = False
        reg["via"], reg["usada"] = via, usada
        if usada:
            aprendidas[lugar] = reg
        if not p0:
            revisar.append({"tipo": "sin_referencia", "casa": lugar[0], "codigo": lugar[1], "aprendida": [reg["lat"], reg["lon"]],
                            "dias": reg["dias"], "camiones": reg["camiones"], "radio_m": reg["radio_m"], "usada": usada,
                            "nota": "aprendida solo por contraste de paradas (no habia coordenada de partida): confirmar"})
        elif reg["dist_referencia_km"] > 5:
            revisar.append({"tipo": "discrepancia", "casa": lugar[0], "codigo": lugar[1], "nombre": p0.get("nombre"),
                            "aprendida": [reg["lat"], reg["lon"]], "referencia": [p0["lat"], p0["lon"]],
                            "fuente_referencia": p0["fuente"], "distancia_km": reg["dist_referencia_km"],
                            "dias": reg["dias"], "camiones": reg["camiones"], "via": via, "usada": usada,
                            "nota": ("se usa la aprendida (plausible y con evidencia fuerte): confirmar" if usada else
                                     "NO se usa: implausible (probable dia de carga de un viaje nacional); manda la referencia")})
    return aprendidas, revisar


# ---------------------------------------------------------------- triangular un dia
def natkey(s):
    """Orden natural: '263/227' < '263/245'; '1395256263' < '1395256277' (numerico, no alfabetico)."""
    return [int(p) if p.isdigit() else p for p in re.split(r"(\d+)", str(s or ""))]


def cerca(s, c, fuente, radio_m=None):
    r = RADIO_MATCH.get(fuente, 3.0)
    if fuente == "gps_aprendida":
        r = min(1.0, max(0.3, 2.0 * (radio_m or 150) / 1000.0))
    if r is None:
        return False
    return hav((s["lat"], s["lon"]), (c["lat"], c["lon"])) <= r


def triangular_dia(viajes, tr, ps, coords, tablas):
    j0, j1 = jornada(tr["pts"])
    n = len(viajes)
    if j0 is None:
        return [{"metodo": "dia", "motivo": "camion_parado", "km": 0.0, "duracion_min": 0.0, "litros": None,
                 "litros_calibrados": None, "km_fuente": None, "repartido": n > 1} for _ in viajes]
    inn = internas(ps, j0, j1)
    orden = sorted(range(n), key=lambda i: (natkey(viajes[i]["v"]), natkey(viajes[i]["cant"])))
    dia0, dia1 = tr["pts"][0]["t"], tr["pts"][-1]["t"]   # contadores del primer/ultimo ciclo: dia entero (ralenti)

    def med(pos, ini, fin):
        c0 = dia0 if pos == 0 else ini
        c1 = dia1 if pos == n - 1 else fin
        return medir(tr, c0, c1, tablas, ini, fin)
    # --- geo: emparejamiento CRONOLOGICO por tipo (origen->destino). Se recorren las paradas en el tiempo: parada cerca
    #     de un origen con viajes pendientes = carga; la siguiente parada cerca de un destino compatible = descarga de
    #     ese viaje (el de cantera mas baja de ese tipo). No depende de que GesRuta numere en orden cronologico.
    casa = viajes[0]["c"]

    def cc(cod):
        return coords.get((casa, cod))

    pend = collections.defaultdict(list)
    for i in orden:
        pend[(viajes[i]["o"], viajes[i]["d"])].append(i)
    if all(cc(o) and cc(d) and RADIO_MATCH.get(cc(o)["fuente"], 1) is not None and RADIO_MATCH.get(cc(d)["fuente"], 1) is not None
           for (o, d) in pend):
        descargas = {}           # indice de viaje -> parada de descarga
        cargado = None
        for s in inn:
            if cargado is not None:
                dsts = [d for (o, d), l in pend.items() if o == cargado and l and cerca(s, cc(d), cc(d)["fuente"], cc(d).get("radio_m"))]
                if dsts:
                    i = pend[(cargado, dsts[0])].pop(0)
                    descargas[i] = s
                    cargado = None
                    continue
            origs = [o for (o, d), l in pend.items() if l and cerca(s, cc(o), cc(o)["fuente"], cc(o).get("radio_m"))]
            if origs:
                cargado = origs[0]
        if len(descargas) == n:
            crono = sorted(descargas, key=lambda i: descargas[i]["t_out"])
            res = [None] * n
            ini = j0
            for pos, i in enumerate(crono):
                fin = j1 if pos == n - 1 else descargas[i]["t_out"]
                if fin <= ini:
                    res = None; break
                m = med(pos, ini, fin); ini = fin
                m.update({"metodo": "geo", "repartido": False, "confianza": "alta"})
                res[i] = m
            if res:
                return res
    # --- orden: solo si los viajes del dia comparten ORIGEN (se corta al llegar a cargar) o DESTINO (se corta al salir
    #     de descargar); ese lugar tiene que aparecer en la traza tantas veces como viajes; cada ciclo se valida.
    if n > 1 and inn:
        origenes = {viajes[i]["o"] for i in range(n)}
        destinos = {viajes[i]["d"] for i in range(n)}
        modo = "origen" if len(origenes) == 1 else ("destino" if len(destinos) == 1 else None)
        if modo:
            cod = next(iter(origenes)) if modo == "origen" else next(iter(destinos))
            ref = coords.get((viajes[0]["c"], cod))
            grupos = agrupar([{"lat": s["lat"], "lon": s["lon"], "s": s} for s in inn], 0.4)
            cand = [g for g in grupos if len(g["m"]) in (n, n + 1)]
            if ref:
                cand.sort(key=lambda g: hav((g["lat"], g["lon"]), (ref["lat"], ref["lon"])))
            else:  # la carga es lo primero del dia; la descarga, lo que se repite mas tarde
                cand.sort(key=lambda g: min(x["s"]["t_in"] for x in g["m"]), reverse=(modo == "destino"))
            for g in cand[:2]:
                visitas = sorted((x["s"] for x in g["m"]), key=lambda s: s["t_in"])[:n]
                if modo == "origen":
                    cortes = [j0] + [s["t_in"] for s in visitas[1:]] + [j1]
                else:
                    cortes = [j0] + [s["t_out"] for s in visitas[:-1]] + [j1]
                if any(b <= a for a, b in zip(cortes, cortes[1:])):
                    continue
                res, valido = [None] * n, True
                for pos, i in enumerate(orden):
                    m = med(pos, cortes[pos], cortes[pos + 1])
                    if (m["km"] or 0) < 1.0 or (m["duracion_min"] or 0) < 8:
                        valido = False; break
                    m.update({"metodo": "orden", "repartido": False, "confianza": "media", "ancla": modo})
                    res[i] = m
                if valido:
                    return res
    # --- dia: suelo seguro
    tot = medir(tr, dia0, dia1, tablas, j0, j1)
    res = []
    for _ in viajes:
        m = {k: (round(v / n, 2) if isinstance(v, (int, float)) and v is not None else v) for k, v in tot.items()}
        m.update({"metodo": "dia", "repartido": n > 1, "confianza": "alta" if n == 1 else "baja"})
        res.append(m)
    return res


# ---------------------------------------------------------------- principal
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--salida", default=os.path.join(D, "triangulado_v1.json"))
    ap.add_argument("--sin-aprender", action="store_true")
    a = ap.parse_args()
    dem = json.load(open(os.path.join(D, "demanda_triangular.json"), encoding="utf-8"))["viajes"]
    for t in dem:
        t["mat"] = clean(t["mat"])
    sens = {}
    if os.path.isfile(os.path.join(D, "sensores_erp.json")):
        sens = json.load(open(os.path.join(D, "sensores_erp.json"), encoding="utf-8"))
    ges = coords_gesruta()
    geo = coords_geocode()
    ref = mejor(ges, geo)
    trazas = cargar_trazas()
    paradas_de = {k: paradas(v["pts"], v["fuente"]) for k, v in trazas.items()}
    # paradas internas para aprender (fuera noche/base)
    internas_de = {}
    for k, v in trazas.items():
        j0, j1 = jornada(v["pts"])
        internas_de[k] = internas(paradas_de[k], j0, j1) if j0 else []
    apr, disc = ({}, []) if a.sin_aprender else aprender(dem, trazas, internas_de, ref)
    coords = mejor(ref, apr)

    # salidas de coordenadas aprendidas (plano por codigo con prioridad Razo, y por casa)
    plano = {}
    for (casa, cod), v in sorted(apr.items(), key=lambda kv: 0 if kv[0][0] == "Razo" else 1):
        plano.setdefault(cod, v)
    json.dump(plano, open(os.path.join(D, "coords_aprendidas_v1.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    json.dump({"%s|%s" % k: v for k, v in apr.items()}, open(os.path.join(D, "coords_aprendidas_por_casa_v1.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    json.dump(disc, open(os.path.join(D, "coords_discrepancias_v1.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    discrepantes = {(x["casa"], x["codigo"]) for x in disc}

    por_dia = collections.defaultdict(list)
    for idx, t in enumerate(dem):
        por_dia[(t["mat"], t["dia"])].append(idx)
    salida = [None] * len(dem)
    movertis = {clean(l) for l in open(os.path.join(D, "movertis_plates.txt"), encoding="utf-8-sig") if clean(l)}
    for (m, d), idxs in por_dia.items():
        viajes = [dem[i] for i in idxs]
        tr = trazas.get((m, d))
        if not tr:
            motivo = "sin_matricula" if not m else ("pendiente_bajada" if m in movertis else "sin_telemetria_o_pendiente_locatel")
            for i in idxs:
                salida[i] = {"metodo": "sin_traza", "motivo": motivo, "km": None, "duracion_min": None, "litros": None,
                             "litros_calibrados": None, "km_fuente": None, "fuente": None, "repartido": None}
            continue
        res = triangular_dia(viajes, tr, paradas_de[(m, d)], coords, sens.get(m))
        for i, r in zip(idxs, res):
            r["fuente"] = tr["fuente"]
            salida[i] = r
    viajes_out = []
    for t, r in zip(dem, salida):
        co, cd = coords.get((t["c"], t["o"])), coords.get((t["c"], t["d"]))
        viajes_out.append({"empresa": t["c"], "viaje": t["v"], "cantera": t["cant"], "matricula": t["mat"], "fecha": t["dia"],
                           "origen": t["o"], "destino": t["d"],
                           "km": r.get("km"), "duracion_min": r.get("duracion_min"), "litros": r.get("litros"),
                           "litros_calibrados": r.get("litros_calibrados"), "metodo": r.get("metodo"),
                           "fuente": r.get("fuente"), "km_fuente": r.get("km_fuente"), "repartido": r.get("repartido"),
                           "confianza": r.get("confianza"), "motivo": r.get("motivo"),
                           "viajes_dia": len(por_dia[(t["mat"], t["dia"])]),
                           "coord_origen": co["fuente"] if co else None, "coord_destino": cd["fuente"] if cd else None,
                           "coord_revisar": ((t["c"], t["o"]) in discrepantes) or ((t["c"], t["d"]) in discrepantes)})
    tot = len(viajes_out)
    met = collections.Counter(v["metodo"] for v in viajes_out)
    fue = collections.Counter(v["fuente"] for v in viajes_out)
    mot = collections.Counter(v["motivo"] for v in viajes_out if v["metodo"] == "sin_traza")
    con_lit = sum(1 for v in viajes_out if v["litros_calibrados"])
    resumen = {"viajes_aridos_nacional": tot,
               "por_metodo": {k: {"viajes": n, "pct": round(100.0 * n / tot, 1)} for k, n in met.most_common()},
               "por_fuente": {str(k): n for k, n in fue.most_common()},
               "sin_traza_por_motivo": dict(mot),
               "con_km_medido_o_repartido": sum(1 for v in viajes_out if v["km"] is not None),
               "con_litros_calibrados": con_lit,
               "repartidos_dia_multiviaje": sum(1 for v in viajes_out if v["metodo"] == "dia" and v["repartido"]),
               "trazas_disponibles": {"wialon": sum(1 for v in trazas.values() if v["fuente"] == "wialon"),
                                      "locatel": sum(1 for v in trazas.values() if v["fuente"] == "locatel")},
               "coords": {"gesruta_maestro": len(ges), "geocode": len(geo), "aprendidas": len(apr),
                          "discrepancias_gt5km": sum(1 for x in disc if x["tipo"] == "discrepancia"),
                          "discrepancias_usadas": sum(1 for x in disc if x["tipo"] == "discrepancia" and x.get("usada")),
                          "discrepancias_rechazadas": sum(1 for x in disc if x["tipo"] == "discrepancia" and not x.get("usada")),
                          "aprendidas_sin_referencia": sum(1 for x in disc if x["tipo"] == "sin_referencia")},
               "viajes_por_fuente_coord": {
                   "origen": dict(collections.Counter(v["coord_origen"] for v in viajes_out)),
                   "destino": dict(collections.Counter(v["coord_destino"] for v in viajes_out))}}
    json.dump({"meta": {"metodos": "geo > orden > dia; sin_traza explicito", "ciclo": "fin ciclo anterior -> salida de la descarga; ultimo hasta fin de jornada",
                        "litros": "crudo = reduccion monotona del contador; calibrados = tabla del sensor (ERP) + reduccion monotona"},
               "resumen": resumen, "viajes": viajes_out},
              open(a.salida, "w", encoding="utf-8"), ensure_ascii=False)
    print(json.dumps(resumen, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
