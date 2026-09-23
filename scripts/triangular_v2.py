# -*- coding: utf-8 -*-
"""Triangulado v2: viaje real <-> traza del localizador + tacografo, con HORA DE INICIO Y FIN, conductor y desglose de horas
por viaje. Aridos (banera) en esta pasada; largas distancias / nacional (varios dias) en la siguiente (salen igual, marcadas).

Extiende triangular_v1 SIN forkear el metodo (importa sus funciones). Razona sobre TODOS los datos: posiciones, paradas,
tacografo (actividad y tarjeta, dentro de la traza de Wialon) y los albaranes de GesRuta.
  1. COSE los dias consecutivos de cada camion en un flujo continuo (los ficheros diarios son dias naturales de Madrid y
     encajan sin hueco): el corte a medianoche era un artefacto del fichero.
  2. JORNADAS por DESCANSO LARGO (> 8 h parado, regla de Roberto; uno menor NO separa) o hueco de datos, NUNCA por
     medianoche; fechadas por su primer movimiento.
  3. CICLOS por GEOGRAFIA: cada parada (>= 3 min) se clasifica en el mapa contra los lugares de carga y descarga de los
     albaranes del dia; una maquina de estados carga -> descarga corta los ciclos. Una parada puede ser descarga de un viaje y
     carga del siguiente (planta); dos cargas seguidas sin descarga = descarga no vista (parada corta), se cierra y se marca.
     Sin geografia util ese dia: particion por el HUB (la parada que se repite) y orden de GesRuta.
  4. ASIGNACION: los albaranes se agrupan por (origen, destino); dentro de cada grupo el ORDEN de GesRuta es cronologico
     (deduccion sobre datos reales: entre canteras NO lo es, va por series de nº de ticket), asi que cada grupo casa con sus
     ciclos en orden temporal. Lo que queda (sin geografia) se alinea por programacion dinamica monotona (orden manda,
     geografia confirma o corrige, nunca fuerza una pareja contradictoria).
  5. Cada viaje sale SIEMPRE (norma: no se ocultan viajes): medido (con t_ini/t_fin y confianza), dia (reparto de los
     ciclos sobrantes), sin_ciclo (mas albaranes que ciclos: SIN DATO, nunca 0), sin_traza (motivo), o cantera_repetida
     (error de grabacion, regla de Roberto: la carga es el albaran de CANTERA, que reinicia numeracion cada ano).
  6. TACOGRAFO por viaje: minutos de conduccion / otros trabajos / disponibilidad / descanso dentro de cada viaje, de los
     cambios de actividad del tacografo que trae la traza (si no hay, por el movimiento); y el conductor (tarjeta, en hash)
     que llevaba el camion, enlazado al codigo de chofer de GesRuta cuando se conoce.
  7. Jornada nocturna PRESTADA: los ciclos de madrugada de la jornada de la vispera que sobraron valen para los albaranes
     de hoy. Nunca se cuenta un ciclo dos veces.
Salida = esquema v1 + aditivos (ver meta). Hora de Madrid sin tzdata ni pytz (regla UE). SOLO LECTURA. Nunca inventa.
"""
import argparse, bisect, collections, datetime as dt, glob, gzip, json, os, statistics, sys

D = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, D)
import triangular_v1 as v1  # noqa: E402

V_PARADO, V_MOVIL = v1.V_PARADO, v1.V_MOVIL
DWELL_S = 180                              # parada = >= 3 min (las descargas de aridos duran 5-10 min; alguna menos de 5)
KM_MIN_CICLO, MIN_MIN_CICLO = 1.0, 8.0     # ciclo valido (hub): >= 1 km y >= 8 min; si no, se funde con el anterior
HUB_EPS_KM = 0.35                          # paradas a < 350 m son el mismo sitio
LARGA_KM = 200.0                           # origen-destino a >= 200 km = larga distancia (pasada de nacional)
MAX_JORNADA_H = 24.0                       # jornada mas larga: no es de aridos, sus viajes van a la pasada de nacional
GAP, MATCH, MISMATCH = -0.6, 1.0, -1.5     # alineamiento: saltar; geografia que confirma; que contradice
VENTANA_DIAS = 7                           # un albaran puede agrupar tickets de varios dias: se buscan a ±7 dias en la traza
ACT = {3: "conduccion", 2: "otros", 1: "disponible", 0: "descanso"}


# ---------------------------------------------------------------- hora de Madrid sin tzdata
def _ultimo_domingo(y, m):
    d = dt.date(y, m, 31)
    return d - dt.timedelta(days=(d.weekday() + 1) % 7)


def madrid_offset(t):
    y = dt.datetime.fromtimestamp(t, dt.timezone.utc).year
    ini = dt.datetime.combine(_ultimo_domingo(y, 3), dt.time(1), tzinfo=dt.timezone.utc).timestamp()
    fin = dt.datetime.combine(_ultimo_domingo(y, 10), dt.time(1), tzinfo=dt.timezone.utc).timestamp()
    return 7200 if ini <= t < fin else 3600


def local(t):
    return dt.datetime.fromtimestamp(t + madrid_offset(t), dt.timezone.utc).replace(tzinfo=None)


def iso_min(t):
    return local(t).strftime("%Y-%m-%dT%H:%M") if t is not None else None


def fecha_de(t):
    return local(t).strftime("%Y-%m-%d")


# ---------------------------------------------------------------- trazas (+ tacografo) por dia y cosidas por camion
def cargar_trazas(dirs):
    """(matricula, dia) -> {fuente, pts[], act[(t,v)], drv[(t,hash)]}. Wialon y Locatel del mismo dia: manda Wialon."""
    tr = {}
    for fuente, carpeta in dirs:
        for ruta in sorted(glob.glob(os.path.join(carpeta, "traza_*.json"))):
            try:
                x = json.load(open(ruta, encoding="utf-8"))
            except (ValueError, OSError):
                continue
            mat = v1.clean(x.get("mat") or x.get("unidad"))
            dia = x.get("dia")
            pts = []
            for q in x.get("traza") or []:
                if q.get("lat") is None or q.get("t") is None:
                    continue
                pts.append({"t": int(q["t"]), "lat": q["lat"], "lon": q["lon"], "s": q.get("s") or 0.0,
                            "kmc": q.get("kmc"), "litc": q.get("litc"), "rec": q.get("rec"),
                            "parada_min": q.get("parada_min"), "f": fuente})
            pts.sort(key=lambda q: q["t"])
            if not mat or not dia or len(pts) < 3:
                continue
            if fuente == "locatel" and (mat, dia) in tr and tr[(mat, dia)]["fuente"] == "wialon":
                continue
            act, drv = [], []
            for e in x.get("conductor_eventos") or []:
                if e.get("k") == "tco_activity_type1" and isinstance(e.get("v"), (int, float)):
                    act.append((int(e["t"]), int(e["v"])))
                elif e.get("k") == "tco_driver1_id" and isinstance(e.get("v"), str) and e["v"].startswith("h:"):
                    drv.append((int(e["t"]), e["v"]))
            tr[(mat, dia)] = {"fuente": fuente, "pts": pts, "act": act, "drv": drv}
    return tr


def coser(trazas):
    flujo, acts, drvs = collections.defaultdict(list), collections.defaultdict(list), collections.defaultdict(list)
    for (mat, dia), v in trazas.items():
        flujo[mat].extend(v["pts"]); acts[mat].extend(v["act"]); drvs[mat].extend(v["drv"])
    for mat in flujo:
        flujo[mat].sort(key=lambda q: q["t"]); acts[mat].sort(); drvs[mat].sort()
    return flujo, acts, drvs


def es_mov(q):
    if q["f"] == "locatel":
        return (q.get("parada_min") or 0) * 60 < DWELL_S or (q["s"] or 0) > V_MOVIL
    return (q["s"] or 0) > V_MOVIL


def paradas_flujo(pts):
    out, i, n = [], 0, len(pts)
    while i < n:
        q = pts[i]
        if q["f"] == "locatel":
            if (q.get("parada_min") or 0) * 60 >= DWELL_S:
                out.append({"t_in": q["t"], "t_out": q["t"] + int(q["parada_min"] * 60), "lat": q["lat"], "lon": q["lon"]})
            i += 1
            continue
        if (q["s"] or 0) <= V_PARADO:
            j = i
            while j + 1 < n and pts[j + 1]["f"] != "locatel" and (pts[j + 1]["s"] or 0) <= V_PARADO:
                j += 1
            if pts[j]["t"] - pts[i]["t"] >= DWELL_S:
                seg = pts[i:j + 1]
                out.append({"t_in": pts[i]["t"], "t_out": pts[j]["t"],
                            "lat": statistics.median(x["lat"] for x in seg), "lon": statistics.median(x["lon"] for x in seg)})
            i = j + 1
        else:
            i += 1
    return out


def jornadas_de(pts, paradas, rest_s):
    cortes = [(p["t_in"], p["t_out"]) for p in paradas if p["t_out"] - p["t_in"] >= rest_s]
    for a, b in zip(pts, pts[1:]):
        if b["t"] - a["t"] >= rest_s:
            cortes.append((a["t"], b["t"]))
    cortes.sort()
    ts = [q["t"] for q in pts]
    mov = [q["t"] for q in pts if es_mov(q)]
    if not mov:
        return []
    jor, ci, ini, ult, c0 = [], 0, None, None, ts[0]
    for t in mov:
        while ci < len(cortes) and cortes[ci][1] <= t:
            if ini is not None and cortes[ci][0] > ini:
                jor.append({"ini": ini, "fin": ult, "c0": c0, "c1": cortes[ci][0]})
                ini = None
            c0 = cortes[ci][1]
            ci += 1
        if ini is None:
            ini = t
        ult = t
    if ini is not None:
        jor.append({"ini": ini, "fin": ult, "c0": c0, "c1": ts[-1]})
    for j in jor:
        j["fecha"] = fecha_de(j["ini"])
        j["nocturna"] = fecha_de(j["ini"]) != fecha_de(j["fin"])
        j["paradas"] = [p for p in paradas if p["t_out"] > j["ini"] and p["t_in"] < j["fin"] and p["t_out"] - p["t_in"] < rest_s]
        j["horas"] = round((j["fin"] - j["ini"]) / 3600.0, 2)
        i0, i1 = bisect.bisect_left(ts, j["c0"]), bisect.bisect_right(ts, j["c1"])
        j["pts"] = pts[i0:i1]
        j["ciclos"], j["sobrantes"], j["asignados"], j["modo"] = None, [], 0, None
    return jor


# ---------------------------------------------------------------- tacografo: minutos por actividad y conductor en un tramo
def _integrar(serie, d0, d1):
    """serie = [(t, valor)] ordenada (valor vigente desde t). Devuelve {valor: segundos} dentro de [d0, d1]."""
    out = collections.Counter()
    if not serie:
        return out
    i = bisect.bisect_right([s[0] for s in serie], d0) - 1
    t, v = (serie[i] if i >= 0 else (None, None))
    cur_t = d0
    k = i + 1
    while cur_t < d1:
        nxt = serie[k][0] if k < len(serie) else d1
        fin = min(nxt, d1)
        if v is not None and fin > cur_t:
            out[v] += fin - cur_t
        cur_t = fin
        if k < len(serie):
            t, v = serie[k]; k += 1
        else:
            break
    return out


def tacografo_tramo(acts, drvs, d0, d1):
    segs = _integrar(acts, d0, d1)
    cubierto = sum(segs.values())
    dur = max(1, d1 - d0)
    res = {"min_conduccion": None, "min_otros": None, "min_disponible": None, "min_descanso": None, "tacografo": False, "conductor": None}
    if cubierto >= 0.5 * dur:
        for v, nombre in ACT.items():
            res["min_" + nombre] = round(segs.get(v, 0) / 60.0, 1)
        res["tacografo"] = True
    d = _integrar(drvs, d0, d1)
    if d:
        h, s = max(d.items(), key=lambda kv: kv[1])
        if s >= 0.5 * dur:
            res["conductor"] = h
    return res


# ---------------------------------------------------------------- medir un tramo
def medir(j, fuente, t0, t1, tablas, d0, d1, acts, drvs):
    m = v1.medir({"fuente": fuente, "pts": j["pts"]}, t0, t1, tablas, d0, d1)
    cond, prev = 0.0, None
    for q in j["pts"]:
        if q["t"] < d0:
            prev = q; continue
        if q["t"] > d1:
            break
        if prev is not None and prev["t"] >= d0 and es_mov(q) and (q["t"] - prev["t"]) <= 900:
            cond += q["t"] - prev["t"]
        prev = q
    tc = tacografo_tramo(acts, drvs, d0, d1)
    m["min_conduccion_traza"] = round(cond / 60.0, 1)
    if tc["tacografo"]:
        m.update({k: tc[k] for k in ("min_conduccion", "min_otros", "min_disponible", "min_descanso")})
        m["min_fuente"] = "tacografo"
    else:
        m.update({"min_conduccion": m["min_conduccion_traza"], "min_otros": None, "min_disponible": None, "min_descanso": None, "min_fuente": "traza"})
    m["min_espera"] = round(max(0.0, (m["duracion_min"] or 0) - (m["min_conduccion"] or 0)), 1)
    m["conductor_hash"] = tc["conductor"]
    return m


# ---------------------------------------------------------------- geografia: clasificar paradas y cortar ciclos
def cerca_cod(stop, cod, coords, casa):
    if not cod or not stop:
        return 0.0
    c = coords.get((casa, cod))
    if not c or v1.RADIO_MATCH.get(c["fuente"], 1) is None:
        return 0.0
    return MATCH if v1.cerca(stop, c, c["fuente"], c.get("radio_m")) else MISMATCH


KM_MISMA_CARGA = 3.0    # dos paradas en el mismo origen con menos de 3 km recorridos entre ellas = la misma carga (espera en cantera)


def fundir_pequenos(ciclos, j, fuente, tablas, km_min=KM_MIN_CICLO, min_min=MIN_MIN_CICLO):
    """Un ciclo que no recorre km_min ni dura min_min no es un viaje: se funde con el anterior (o el siguiente si es el primero).
    km_min es RELATIVO al viaje mas corto del dia (un trayecto cantera->planta de 0,4 km hace ciclos de 0,8 km)."""
    i = 0
    while i < len(ciclos) and len(ciclos) > 1:
        c = ciclos[i]
        m = v1.medir({"fuente": fuente, "pts": j["pts"]}, c["t0"], c["t1"], tablas, c["t0"], c["t1"])
        if (m["km"] or 0) >= km_min and (m["duracion_min"] or 0) >= min_min:
            i += 1
            continue
        if i > 0:
            p = ciclos[i - 1]
            p["t1"] = c["t1"]
            if c.get("descarga"):
                p["descarga"], p["d"], p["falta"] = c["descarga"], c["d"], c["falta"]
            del ciclos[i]
        else:
            n = ciclos[1]
            n["t0"] = c["t0"]
            if not n.get("carga") and c.get("carga"):
                n["carga"], n["o"] = c["carga"], c["o"]
            del ciclos[0]
    return ciclos


def ciclos_geo(j, viajes, coords, casa, fuente, tablas):
    """Maquina de estados carga -> descarga sobre las paradas clasificadas en el mapa. Devuelve ciclos con (o, d) o [] si el
    dia no tiene geografia util. Convencion v1: un ciclo va del fin del anterior a la SALIDA de su descarga; el ultimo, al fin.
    - Dos paradas en el mismo origen con < KM_MISMA_CARGA recorridos entre ellas = la misma carga (espera en la cantera).
    - Si no hay parada de descarga (volcar una banera dura 2-3 min), la descarga es el PASO de la traza por el destino (el
      punto mas cercano dentro de su radio): 'descarga_por_paso'. Si tampoco pasa, 'descarga_no_vista' (se cierra al cargar)."""
    O = {t["o"] for t in viajes if t["o"]}
    Dd = {t["d"] for t in viajes if t["d"]}
    pares = {(t["o"], t["d"]) for t in viajes}
    pts = j["pts"]
    ts = [q["t"] for q in pts]
    # VISITAS a las zonas del dia por GEOCERCA sobre los puntos de la traza (sin exigir parada: en un porte de 3 km ni la carga
    # ni la descarga llegan a 3 min). Visita = puntos consecutivos dentro de la zona; vale si tiene >= 2 puntos o el camion
    # frena (< 10 km/h) dentro. Un punto suelto a velocidad de carretera no es una visita (paso por delante).
    zonas = []
    for cod in O | Dd:
        c = coords.get((casa, cod))
        if c and v1.RADIO_MATCH.get(c["fuente"], 1) is not None:
            zonas.append((cod, c))
    visitas, cur = [], None
    for q in pts:
        dentro = [(v1.hav((q["lat"], q["lon"]), (c["lat"], c["lon"])), cod) for cod, c in zonas if v1.cerca(q, c, c["fuente"], c.get("radio_m"))]
        cod = None
        if dentro:
            cod = min(dentro)[1]        # zonas solapadas (planta a 1 km de la cantera): manda la mas cercana
        if cur and cod == cur["cod"]:
            cur["t_out"] = q["t"]; cur["n"] += 1; cur["lat"] += q["lat"]; cur["lon"] += q["lon"]; cur["vmin"] = min(cur["vmin"], q["s"] or 0)
            continue
        if cur:
            visitas.append(cur); cur = None
        if cod:
            cur = {"cod": cod, "t_in": q["t"], "t_out": q["t"], "n": 1, "lat": q["lat"], "lon": q["lon"], "vmin": q["s"] or 0}
    if cur:
        visitas.append(cur)
    # arranque: si la jornada empieza descargando el viaje de AYER (carga hoy, descarga manana), sus viajes arrancan despues
    desde = j.get("arranque") or j["ini"]
    cl = []
    for v in visitas:
        if v["n"] < 2 and v["vmin"] > 10:
            continue
        if v["t_out"] <= desde:
            continue
        s = {"t_in": max(v["t_in"], desde), "t_out": v["t_out"], "lat": v["lat"] / v["n"], "lon": v["lon"] / v["n"], "zona": v["cod"]}
        cl.append((s, [v["cod"]] if v["cod"] in O else [], [v["cod"]] if v["cod"] in Dd else []))
    if not cl:
        return []
    # distancia ida+vuelta de cada par (o, d) del dia: los umbrales son RELATIVOS a ella (hay trayectos de 0,4 km)
    iv = {}
    for (o, d) in pares:
        co, cd = coords.get((casa, o)), coords.get((casa, d))
        if co and cd:
            iv[(o, d)] = 2 * v1.hav((co["lat"], co["lon"]), (cd["lat"], cd["lon"]))
    iv_min = min(iv.values()) if iv else None
    km_min_ciclo = max(0.3, min(KM_MIN_CICLO, 0.5 * iv_min)) if iv_min is not None else KM_MIN_CICLO
    min_min_ciclo = MIN_MIN_CICLO if (iv_min is None or iv_min >= 4) else 6.0

    def umbral_misma_carga(o):
        ds = [v for (oo, d), v in iv.items() if oo == o]
        return min(KM_MISMA_CARGA, max(0.4, 0.6 * min(ds))) if ds else KM_MISMA_CARGA

    def km_entre(t0, t1):
        return v1.km_gps(pts[bisect.bisect_left(ts, t0):bisect.bisect_right(ts, t1)])

    def paso_por_destino(o, t0, t1):
        best = None
        i0, i1 = bisect.bisect_left(ts, t0), bisect.bisect_right(ts, t1)
        for d in [d for (oo, d) in pares if oo == o and d]:
            c = coords.get((casa, d))
            if not c or v1.RADIO_MATCH.get(c["fuente"], 1) is None:
                continue
            for q in pts[i0:i1]:
                if v1.cerca(q, c, c["fuente"], c.get("radio_m")):
                    dist = v1.hav((q["lat"], q["lon"]), (c["lat"], c["lon"]))
                    if best is None or dist < best[0]:
                        best = (dist, q, d)
        return best

    def paso_por_origen(d_codes, t0, t1):
        """La carga fue rapida (menos que el umbral de parada): el punto de la traza mas cercano a un ORIGEN compatible con
        alguna de estas descargas, entre t0 y t1, si entra en su radio."""
        best = None
        i0, i1 = bisect.bisect_left(ts, t0), bisect.bisect_right(ts, t1)
        for (o, d) in pares:
            if d not in d_codes or not o:
                continue
            c = coords.get((casa, o))
            if not c or v1.RADIO_MATCH.get(c["fuente"], 1) is None:
                continue
            for q in pts[i0:i1]:
                if v1.cerca(q, c, c["fuente"], c.get("radio_m")):
                    dist = v1.hav((q["lat"], q["lon"]), (c["lat"], c["lon"]))
                    if best is None or dist < best[0]:
                        best = (dist, q, o)
        return best

    ciclos, loaded, prev_fin = [], None, desde

    def cerrar(t1, descarga, d, falta):
        ciclos.append({"t0": prev_fin, "t1": t1, "carga": loaded["s"], "descarga": descarga, "o": loaded["o"], "d": d, "falta": falta})

    def cerrar_sin_parada(t_limite):
        nonlocal prev_fin
        p = paso_por_destino(loaded["o"], loaded["s"]["t_out"], t_limite)
        if p:
            q, d = p[1], p[2]
            ds = {"t_in": q["t"], "t_out": q["t"], "lat": q["lat"], "lon": q["lon"], "paso": True}
            cerrar(q["t"], ds, d, "descarga_por_paso")
            prev_fin = q["t"]
        else:
            cerrar(t_limite, None, None, "descarga_no_vista")
            prev_fin = t_limite

    dual = None     # parada de doble papel (descarga en la planta que tambien es origen): SOLO es carga si la siguiente parada
    #                 clasificada es una descarga compatible; si el camion vuelve a cargar a otro sitio, no hubo tal carga y el
    #                 retorno en vacio va al viaje siguiente (convencion v1)
    for s, oc, dc in cl:
        oo = [o for o in oc if any(p[0] == o for p in pares)]
        if loaded is None and dual is not None:
            dd = [d for d in dc if (dual["o"], d) in pares]
            if dd:
                loaded = dual
                cerrar(s["t_out"], s, dd[0], None)
                prev_fin, loaded = s["t_out"], None
                dual = {"s": s, "o": oo[0]} if oo else None
                continue
            if oo:
                dual = None                                     # cargo en otro sitio: la doble carga no existio
            else:
                continue                                        # parada intermedia: la doble carga sigue en el aire
        if loaded is not None:
            dd = [d for d in dc if (loaded["o"], d) in pares]
            if dd:
                cerrar(s["t_out"], s, dd[0], None)
                prev_fin, loaded = s["t_out"], None
                dual = {"s": s, "o": oo[0]} if oo else None
                continue
            if oo:
                if loaded["o"] in oo and km_entre(loaded["s"]["t_out"], s["t_in"]) < umbral_misma_carga(loaded["o"]):
                    continue                                    # misma carga: espera o movimiento dentro de la cantera
                cerrar_sin_parada(s["t_in"])                    # otra carga: la descarga fue rapida (paso) o no se vio
                loaded = {"s": s, "o": oo[0]}
            # parada intermedia (espera): sigue cargado
        elif oo:
            loaded = {"s": s, "o": oo[0]}
        elif dc:
            # descarga vista SIN carga vista: la carga fue rapida (una pala llena una banera en 2-3 min). Si la traza paso por
            # un origen compatible desde el fin del ciclo anterior, ese paso es la carga: 'carga_por_paso'
            p = paso_por_origen(dc, prev_fin, s["t_in"])
            if p:
                q, o = p[1], p[2]
                loaded = {"s": {"t_in": q["t"], "t_out": q["t"], "lat": q["lat"], "lon": q["lon"], "paso": True}, "o": o}
                cerrar(s["t_out"], s, [d for d in dc if (o, d) in pares][0], "carga_por_paso")
                prev_fin, loaded = s["t_out"], None
    if loaded is not None:
        cerrar_sin_parada(j["fin"])
        ciclos[-1]["t1"] = j["fin"]
        if ciclos[-1]["falta"] == "descarga_no_vista":
            ciclos[-1]["falta"] = "descarga_no_vista_fin_jornada"
    elif ciclos:
        ciclos[-1]["t1"] = j["fin"]
    ciclos = dividir_por_alternancias(ciclos, pts, ts, coords, casa)
    return fundir_pequenos(ciclos, j, fuente, tablas, km_min_ciclo, min_min_ciclo)


def dividir_por_alternancias(ciclos, pts, ts, coords, casa):
    """Un porte de 3 km con carga y descarga de menos de un minuto puede no dejar ni un punto de la traza dentro de la zona
    entre dos muestras, y dos viajes quedan en un ciclo de doble duracion. Dentro de cada ciclo (o, d) se cuentan las
    ALTERNANCIAS origen -> destino -> origen -> destino con un radio algo mayor (>= 600 m) y criterio de visita (2 puntos o
    frenada); si hay k >= 2 descargas encadenadas, el ciclo se parte en k (marcados 'dividido_por_alternancias')."""
    out = []
    for c in ciclos:
        o, d = c.get("o"), c.get("d")
        co, cd = coords.get((casa, o)) if o else None, coords.get((casa, d)) if d else None
        if not (co and cd) or v1.RADIO_MATCH.get(co["fuente"], 1) is None or v1.RADIO_MATCH.get(cd["fuente"], 1) is None:
            out.append(c); continue
        i0, i1 = bisect.bisect_left(ts, c["t0"]), bisect.bisect_right(ts, c["t1"])
        seg = pts[i0:i1]
        if len(seg) < 6:
            out.append(c); continue
        def radio(cc):
            r = v1.RADIO_MATCH.get(cc["fuente"], 3.0)
            if cc["fuente"] == "gps_aprendida":
                r = min(1.0, max(0.3, 2.0 * (cc.get("radio_m") or 150) / 1000.0))
            return max(0.6, r)
        ro, rd = radio(co), radio(cd)
        # secuencia de zonas por punto (o / d / None), colapsando repeticiones; una visita vale con 2 puntos o frenada
        hits, cur = [], None
        for q in seg:
            zo = v1.hav((q["lat"], q["lon"]), (co["lat"], co["lon"])) <= ro
            zd = v1.hav((q["lat"], q["lon"]), (cd["lat"], cd["lon"])) <= rd
            z = "d" if zd and not zo else ("o" if zo and not zd else (cur["z"] if (cur and (zo or zd)) else None))
            if cur and z == cur["z"]:
                cur["t_out"] = q["t"]; cur["n"] += 1; cur["vmin"] = min(cur["vmin"], q["s"] or 0); continue
            if cur and (cur["n"] >= 2 or cur["vmin"] <= 15):
                hits.append(cur)
            cur = {"z": z, "t_in": q["t"], "t_out": q["t"], "n": 1, "vmin": q["s"] or 0} if z else None
        if cur and (cur["n"] >= 2 or cur["vmin"] <= 15):
            hits.append(cur)
        # descargas que siguen a una carga: cada una cierra un viaje. El ciclo arranca VACIO (empieza tras la descarga
        # anterior, o al inicio de la jornada): una pasada por el destino antes de cargar no es una descarga.
        cortes, visto_o = [], False
        for h in hits:
            if h["z"] == "o":
                visto_o = True
            elif h["z"] == "d" and visto_o:
                cortes.append(h["t_out"]); visto_o = False
        # entre dos descargas tiene que haber una ida y vuelta de verdad (>= 70 % de la distancia o-d ida y vuelta)
        iv = 2 * v1.hav((co["lat"], co["lon"]), (cd["lat"], cd["lon"]))
        dep = [cortes[0]] if cortes else []
        for tc in cortes[1:]:
            i0, i1 = bisect.bisect_left(ts, dep[-1]), bisect.bisect_right(ts, tc)
            if v1.km_gps(pts[i0:i1]) >= 0.7 * iv:
                dep.append(tc)
        cortes = dep
        if len(cortes) < 2:
            out.append(c); continue
        t0 = c["t0"]
        for k, tc in enumerate(cortes[:-1]):
            out.append({"t0": t0, "t1": tc, "carga": c["carga"] if k == 0 else None, "descarga": {"t_in": tc, "t_out": tc, "lat": cd["lat"], "lon": cd["lon"], "paso": True}, "o": o, "d": d, "falta": "dividido_por_alternancias"})
            t0 = tc
        out.append({"t0": t0, "t1": c["t1"], "carga": None, "descarga": c["descarga"], "o": o, "d": d, "falta": c.get("falta") or "dividido_por_alternancias"})
    return out


def sitios_jornada(j, codigos, coords, casa):
    grupos = v1.agrupar([{"lat": s["lat"], "lon": s["lon"], "s": s} for s in j["paradas"]], HUB_EPS_KM)
    out = []
    for g in grupos:
        vis = sorted((x["s"] for x in g["m"]), key=lambda s: s["t_in"])
        cods = [cod for cod in codigos if cerca_cod({"lat": g["lat"], "lon": g["lon"]}, cod, coords, casa) > 0]
        out.append({"lat": g["lat"], "lon": g["lon"], "visitas": vis, "codigos": cods})
    return out


def elegir_hub(sitios, viajes):
    cand = [s for s in sitios if len(s["visitas"]) >= 2]
    if not cand:
        return None, None
    origs = collections.Counter(t["o"] for t in viajes if t["o"])
    dests = collections.Counter(t["d"] for t in viajes if t["d"])
    cand.sort(key=lambda s: (max(sum(origs[c] for c in s["codigos"]), sum(dests[c] for c in s["codigos"])), len(s["visitas"])), reverse=True)
    hub = cand[0]
    so, sd = sum(origs[c] for c in hub["codigos"]), sum(dests[c] for c in hub["codigos"])
    modo = "destino" if sd > so else ("origen" if so > sd else ("destino" if len(dests) < len(origs) else "origen"))
    return hub, modo


def particionar_hub(j, hub, modo, fuente, tablas, acts, drvs):
    """Ciclos sin solapes por las visitas al hub (sin geografia de codigos). Los que no llegan a viaje se funden con el anterior."""
    if not hub:
        ps = j["paradas"]
        return [{"t0": j["ini"], "t1": j["fin"], "carga": ps[0] if ps else None, "descarga": ps[-1] if len(ps) > 1 else None, "o": None, "d": None, "falta": None}]
    vis = hub["visitas"]
    ids_hub = {id(s) for s in vis}
    otras = [s for s in j["paradas"] if id(s) not in ids_hub]
    cortes = ([j["ini"]] + [s["t_out"] for s in vis[:-1]] + [j["fin"]]) if modo == "destino" else ([j["ini"]] + [s["t_in"] for s in vis[1:]] + [j["fin"]])
    ciclos = []
    for k, (a, b) in enumerate(zip(cortes, cortes[1:])):
        if b <= a:
            continue
        v = vis[k] if k < len(vis) else None
        dentro = [s for s in otras if s["t_out"] > a and s["t_in"] < b]
        larga = max(dentro, key=lambda s: s["t_out"] - s["t_in"]) if dentro else None
        ciclos.append({"t0": a, "t1": b, "carga": larga if modo == "destino" else v, "descarga": v if modo == "destino" else larga, "o": None, "d": None, "falta": None})
    i = 0
    while i < len(ciclos) and len(ciclos) > 1:
        c = ciclos[i]
        m = v1.medir({"fuente": fuente, "pts": j["pts"]}, c["t0"], c["t1"], tablas, c["t0"], c["t1"])
        if (m["km"] or 0) >= KM_MIN_CICLO and (m["duracion_min"] or 0) >= MIN_MIN_CICLO:
            i += 1
            continue
        if i > 0:
            p = ciclos[i - 1]; p["t1"] = c["t1"]; p["descarga"] = c["descarga"] or p["descarga"]; del ciclos[i]
        else:
            n = ciclos[1]; n["t0"] = c["t0"]; n["carga"] = c["carga"] or n["carga"]; del ciclos[0]
    return ciclos


# ---------------------------------------------------------------- alineamiento monotono (respaldo sin geografia completa)
def _dp(S):
    """Alineamiento monotono por programacion dinamica sobre la matriz de puntuacion S[i][k]. Devuelve {i: k}."""
    n, m = len(S), (len(S[0]) if S else 0)
    dp = [[0.0] * (m + 1) for _ in range(n + 1)]
    bt = [[None] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        dp[i][0], bt[i][0] = i * GAP, "u"
    for k in range(1, m + 1):
        dp[0][k], bt[0][k] = k * GAP, "l"
    for i in range(1, n + 1):
        for k in range(1, m + 1):
            best, b = dp[i - 1][k - 1] + S[i - 1][k - 1], "d"
            if dp[i - 1][k] + GAP > best:
                best, b = dp[i - 1][k] + GAP, "u"
            if dp[i][k - 1] + GAP > best:
                best, b = dp[i][k - 1] + GAP, "l"
            dp[i][k], bt[i][k] = best, b
    asig, i, k = {}, n, m
    while i > 0 or k > 0:
        b = bt[i][k]
        if b == "d":
            asig[i - 1] = k - 1; i -= 1; k -= 1
        elif b == "u":
            i -= 1
        else:
            k -= 1
    return asig


def alinear(viajes, ciclos, coords, casa):
    S = [[cerca_cod(ciclos[k]["carga"], viajes[i]["o"], coords, casa) + cerca_cod(ciclos[k]["descarga"], viajes[i]["d"], coords, casa)
          for k in range(len(ciclos))] for i in range(len(viajes))]
    return _dp(S), S


# ---------------------------------------------------------------- triangular los viajes de un dia
def sin_dato(metodo, motivo, j=None):
    return {"metodo": metodo, "motivo": motivo, "km": None, "duracion_min": None, "litros": None, "litros_calibrados": None,
            "km_fuente": None, "repartido": None, "medido": False, "confianza": None, "t_ini": None, "t_fin": None,
            "min_conduccion": None, "min_espera": None, "min_otros": None, "min_disponible": None, "min_descanso": None,
            "min_fuente": None, "conductor_hash": None, "jornada": j, "orden_ciclo": None, "geo_score": None}


SUMABLES = ("km", "litros", "litros_calibrados", "duracion_min", "min_conduccion", "min_conduccion_traza", "min_espera", "min_otros", "min_disponible", "min_descanso")


def medir_ciclo(j, c, k, nc, fuente, tablas, acts, drvs, prestada=False):
    if c.get("partes"):
        # viaje que carga hoy y descarga manana: dos tramos en dos jornadas; el descanso entre medias NO es del viaje
        m = None
        for (jp, c0, c1, d0, d1) in c["partes"]:
            mp = medir(jp, fuente, c0, c1, tablas, d0, d1, acts, drvs)
            if m is None:
                m = mp
                continue
            for kk in SUMABLES:
                if mp.get(kk) is not None:
                    m[kk] = round((m.get(kk) or 0) + mp[kk], 2)
            if mp.get("conductor_hash") and not m.get("conductor_hash"):
                m["conductor_hash"] = mp["conductor_hash"]
    else:
        c0 = max(j["c0"], j.get("arranque") or 0) if (not prestada and k == 0) else c["t0"]
        c1 = j["c1"] if (not prestada and k == nc - 1) else c["t1"]
        m = medir(j, fuente, c0, c1, tablas, c["t0"], c["t1"], acts, drvs)
    m.update({"repartido": False, "medido": True, "t_ini": c["t0"], "t_fin": c["t1"], "jornada": j, "orden_ciclo": k + 1,
              "motivo": c.get("falta"), "prestada": prestada})
    return m


def asignar_geo(viajes, pendientes, ciclos, j, fuente, tablas, acts, drvs, res, prestada=False):
    """Por ORIGEN: los albaranes de una cantera van en orden cronologico (deduccion sobre datos reales), asi que se alinean
    monotonamente con los ciclos cargados en ese origen, en orden temporal; el destino solo puntua (confirma, no fuerza)."""
    usados = set()
    grupos = collections.OrderedDict()
    for i in pendientes:
        grupos.setdefault(viajes[i]["o"], []).append(i)
    for o, lst in grupos.items():
        lst = [i for i in lst if res[i] is None]
        ks = [k for k, c in enumerate(ciclos) if k not in usados and c["o"] == o]
        if not lst or not ks:
            continue
        def sc(i, k):
            d, td = ciclos[k]["d"], viajes[i]["d"]
            return 0.0 if (d is None or not td) else (MATCH if d == td else MISMATCH)
        S = [[sc(i, k) for k in ks] for i in lst]
        for li, kk in _dp(S).items():
            i, k = lst[li], ks[kk]
            m = medir_ciclo(j, ciclos[k], k, len(ciclos), fuente, tablas, acts, drvs, prestada)
            s = S[li][kk]
            m.update({"metodo": "geo", "confianza": "alta" if s > 0 else ("media" if s == 0 else "baja"), "geo_score": MATCH + s})
            res[i] = m; usados.add(k); ciclos[k]["viaje"] = viajes[i]
    quedan = [i for i in pendientes if res[i] is None]
    return quedan, [k for k in range(len(ciclos)) if k not in usados]


def asignar_dp(viajes, pendientes, ciclos, idx_libres, j, fuente, tablas, acts, drvs, res, coords, casa, prestada=False):
    if not pendientes or not idx_libres:
        return list(pendientes), list(idx_libres)
    cand = [viajes[i] for i in pendientes]
    libres = [ciclos[k] for k in idx_libres]
    asig, S = alinear(cand, libres, coords, casa)
    usados = set()
    for li, kk in asig.items():
        i, k = pendientes[li], idx_libres[kk]
        m = medir_ciclo(j, ciclos[k], k, len(ciclos), fuente, tablas, acts, drvs, prestada)
        sc = S[li][kk]
        m.update({"metodo": "geo" if sc >= 2 * MATCH else "orden", "confianza": "alta" if sc >= 2 * MATCH else ("media" if sc >= 0 else "baja"), "geo_score": sc})
        res[i] = m; usados.add(k); ciclos[k]["viaje"] = viajes[i]
    return [i for i in pendientes if res[i] is None], [k for k in idx_libres if k not in usados]


def reparto(tramos, fuente, tablas, acts, drvs, k, motivo, j):
    tot = collections.Counter(); hay = {"lit": False, "litc": False, "taco": False}
    for (a, b, jj) in tramos:
        m = medir(jj, fuente, a, b, tablas, a, b, acts, drvs)
        tot["km"] += m["km"] or 0; tot["dur"] += m["duracion_min"] or 0; tot["cond"] += m["min_conduccion"] or 0
        for kk in ("min_otros", "min_disponible", "min_descanso"):
            if m[kk] is not None:
                tot[kk] += m[kk]; hay["taco"] = True
        if m["litros"] is not None:
            tot["lit"] += m["litros"]; hay["lit"] = True
        if m["litros_calibrados"] is not None:
            tot["litc"] += m["litros_calibrados"]; hay["litc"] = True
    dur, cond = tot["dur"] / k, tot["cond"] / k
    return {"km": round(tot["km"] / k, 2), "km_fuente": "can_mileage" if fuente == "wialon" else "locatel_recorrido",
            "litros": round(tot["lit"] / k, 2) if hay["lit"] else None, "litros_calibrados": round(tot["litc"] / k, 2) if hay["litc"] else None,
            "duracion_min": round(dur, 1), "min_conduccion": round(cond, 1), "min_espera": round(max(0.0, dur - cond), 1),
            "min_otros": round(tot["min_otros"] / k, 1) if hay["taco"] else None, "min_disponible": round(tot["min_disponible"] / k, 1) if hay["taco"] else None,
            "min_descanso": round(tot["min_descanso"] / k, 1) if hay["taco"] else None, "min_fuente": "tacografo" if hay["taco"] else "traza",
            "conductor_hash": None, "metodo": "dia", "repartido": True, "medido": False, "confianza": "baja", "motivo": motivo,
            "t_ini": None, "t_fin": None, "jornada": j, "orden_ciclo": None, "geo_score": None}


def triangular_dia(viajes, jornadas, prestados, fuente, coords, tablas, acts, drvs, diag, permitir_ciclos=True, viajes_sig=None):
    """viajes_sig = albaranes del dia SIGUIENTE del mismo camion: en una jornada nocturna sus cargas de madrugada estan en esta
    traza, asi que sus lugares tambien cortan ciclos (que quedan sobrantes hoy y se prestan manana)."""
    n = len(viajes)
    res = [None] * n
    pendientes = list(range(n))
    casa = viajes[0]["c"]
    if permitir_ciclos:
        if prestados:
            jp = prestados[0][1]
            cic = [c for c, _ in prestados]
            pendientes, libres = asignar_geo(viajes, pendientes, cic, jp, fuente, tablas, acts, drvs, res, prestada=True)
            pendientes, libres = asignar_dp(viajes, pendientes, cic, libres, jp, fuente, tablas, acts, drvs, res, coords, casa, prestada=True)
            diag["ciclos_prestados_usados"] += len(cic) - len(libres)
            jp["sobrantes"] = [c for k, c in enumerate(cic) if k in libres] + [c for c in jp["sobrantes"] if c not in cic]
        codigos = {c for t in viajes for c in (t["o"], t["d"]) if c}
        for j in jornadas:
            if j["ciclos"] is None:
                base = viajes + (list(viajes_sig) if (j["nocturna"] and viajes_sig) else [])
                cic = ciclos_geo(j, base, coords, casa, fuente, tablas)
                if cic:
                    j["modo"] = "geo"
                else:
                    hub, modo = elegir_hub(sitios_jornada(j, codigos, coords, casa), viajes)
                    cic = particionar_hub(j, hub, modo, fuente, tablas, acts, drvs)
                    j["modo"] = "hub_" + (modo or "unico")
                j["ciclos"] = cic
            pendientes, libres = asignar_geo(viajes, pendientes, j["ciclos"], j, fuente, tablas, acts, drvs, res)
            pendientes, libres = asignar_dp(viajes, pendientes, j["ciclos"], libres, j, fuente, tablas, acts, drvs, res, coords, casa)
            j["sobrantes"] = [j["ciclos"][k] for k in libres]
            j["asignados"] = len(j["ciclos"]) - len(libres)
    if pendientes:
        if not permitir_ciclos:
            tramos = [(j["c0"], j["c1"], j) for j in jornadas]
            motivo = "larga_distancia_pendiente_pasada_2"
        else:
            # solo los sobrantes cargados HOY; los de madrugada de una nocturna son de los albaranes de manana (se prestan)
            hoy = viajes[0]["dia"]
            def es_de_hoy(c):
                return fecha_de((c.get("carga") or {}).get("t_in", c["t0"])) == hoy
            tramos = [(c["t0"], c["t1"], j) for j in jornadas for c in j["sobrantes"] if es_de_hoy(c)]
            motivo = "sin_ciclo_propio_reparto_de_sobrantes"
        if tramos:
            r = reparto(tramos, fuente, tablas, acts, drvs, len(pendientes), motivo, tramos[0][2])
            for i in pendientes:
                res[i] = dict(r)
            if permitir_ciclos:
                diag["viajes_repartidos_de_sobrantes"] += len(pendientes)
                for j in jornadas:
                    j["sobrantes"] = [c for c in j["sobrantes"] if not es_de_hoy(c)]
        elif jornadas:
            for i in pendientes:
                res[i] = sin_dato("sin_ciclo", "mas_albaranes_que_ciclos_en_la_traza", jornadas[0])
            diag["viajes_sin_ciclo"] += len(pendientes)
        else:
            for i in pendientes:
                res[i] = sin_dato("sin_traza", "sin_jornada_ese_dia")
    for j in jornadas:
        diag["ciclos_sobrantes"] += len(j["sobrantes"])
        j["min_sobrantes"] = round(sum((c["t1"] - c["t0"]) / 60.0 for c in j["sobrantes"]), 0)
        diag["min_sobrantes"] += j["min_sobrantes"]
    return res


def primer_paso_destino(jn, t, viajes_hoy, coords):
    """Carga ayer, descarga hoy: en la jornada jn, la primera visita (2 puntos o frenada, radio >= 600 m) al DESTINO del viaje t
    ANTES de la primera visita a un origen de los viajes de hoy. Devuelve la hora de salida de esa visita, o None."""
    casa = t["c"]
    cd = coords.get((casa, t["d"])) if t.get("d") else None
    if not cd or v1.RADIO_MATCH.get(cd["fuente"], 1) is None:
        return None
    origs = []
    for x in viajes_hoy:
        c = coords.get((casa, x["o"])) if x.get("o") else None
        if c and v1.RADIO_MATCH.get(c["fuente"], 1) is not None:
            origs.append(c)

    def radio(cc):
        r = v1.RADIO_MATCH.get(cc["fuente"], 3.0)
        if cc["fuente"] == "gps_aprendida":
            r = min(1.0, max(0.3, 2.0 * (cc.get("radio_m") or 150) / 1000.0))
        return max(0.6, r)
    rd = radio(cd)
    cur, n_o = None, 0
    for q in jn["pts"]:
        if q["t"] < jn["ini"]:
            continue
        en_d = v1.hav((q["lat"], q["lon"]), (cd["lat"], cd["lon"])) <= rd
        en_o = any(v1.hav((q["lat"], q["lon"]), (c["lat"], c["lon"])) <= radio(c) for c in origs)
        if en_o and not en_d:
            n_o += 1
            if n_o >= 2 or (q["s"] or 0) <= 15:
                break                       # ya esta cargando el primer viaje de hoy: no hubo descarga pendiente antes
        else:
            n_o = 0
        if en_d:
            if cur is None:
                cur = {"t_in": q["t"], "t_out": q["t"], "n": 1, "vmin": q["s"] or 0}
            else:
                cur["t_out"] = q["t"]; cur["n"] += 1; cur["vmin"] = min(cur["vmin"], q["s"] or 0)
        elif cur is not None:
            if cur["n"] >= 2 or cur["vmin"] <= 15:
                return cur["t_out"]
            cur = None
    if cur is not None and (cur["n"] >= 2 or cur["vmin"] <= 15):
        return cur["t_out"]
    return None


# ---------------------------------------------------------------- ancla de GesRuta (tarifas)
def cargar_ancla(ruta):
    out = collections.defaultdict(list)
    if not ruta or not os.path.isfile(ruta):
        return out
    try:
        opener = gzip.open if ruta.endswith(".gz") else open
        with opener(ruta, "rt", encoding="utf-8") as f:
            cargas = json.load(f).get("cargas") or []
    except (OSError, ValueError) as e:
        print("Aviso: ancla ilegible (%s); se sigue sin ella" % e, file=sys.stderr)
        return out
    filas, ident = [], collections.defaultdict(set)
    for x in cargas:
        if x.get("naturaleza") not in (None, "viaje"):
            continue
        casa = v1.casa_norm(x.get("empresa"))
        fecha = str(x.get("fecha") or "")[:10]
        cant = str(x.get("cantera") or "").strip()
        k_id = (casa, (x.get("origen") or "").strip().upper(), cant, fecha[:4])
        ident[k_id].add((str(x.get("viaje")), str(x.get("albara"))))     # albaranes DISTINTOS con el mismo ticket = error
        filas.append((casa, str(x.get("viaje")), cant, k_id,
                      {"tipo": x.get("tipo"), "albara": x.get("albara"), "linea": x.get("linea"), "cliente": x.get("cliente"),
                       "cantidad": x.get("cantidad"), "unidad": x.get("unidad"), "fecha": fecha, "origen": x.get("origen"), "chofer": x.get("chofer")}))
    for casa, viaje, cant, k_id, reg in filas:
        reg["repetida"] = bool(cant) and len(ident[k_id]) > 1   # dos lineas del MISMO albaran son la misma carga (dos conceptos)
        out[(casa, viaje, cant)].append(reg)
    return out


# ---------------------------------------------------------------- principal
def main():
    global DWELL_S
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--demanda", required=True)
    ap.add_argument("--wialon", action="append", default=[])
    ap.add_argument("--locatel", action="append", default=[])
    ap.add_argument("--sensores", default="")
    ap.add_argument("--geocode", default="")
    ap.add_argument("--plates", default="")
    ap.add_argument("--ancla", default="", help="viajes-ancla-razo.json(.gz) de tarifas")
    ap.add_argument("--conductores", default="", help="conductores_hash_codigo.json: hash de tarjeta -> codigo de chofer GesRuta")
    ap.add_argument("--rest-h", type=float, default=8.0, dest="rest_h", help="descanso (h) que separa jornadas: > 8 h (Roberto)")
    ap.add_argument("--dwell-min", type=float, default=3.0, dest="dwell_min", help="minutos parado para contar como parada")
    ap.add_argument("--sin-aprender", action="store_true")
    ap.add_argument("--salida", required=True)
    ap.add_argument("--diag", default="")
    a = ap.parse_args()
    rest_s = int(a.rest_h * 3600)
    DWELL_S = int(a.dwell_min * 60)
    v1.DWELL_S = DWELL_S

    dem = json.load(open(a.demanda, encoding="utf-8"))["viajes"]
    for t in dem:
        t["mat"] = v1.clean(t["mat"]); t["c"] = v1.casa_norm(t["c"])
    sens = json.load(open(a.sensores, encoding="utf-8")) if a.sensores and os.path.isfile(a.sensores) else {}
    plates = set()
    if a.plates and os.path.isfile(a.plates):
        plates = {v1.clean(l) for l in open(a.plates, encoding="utf-8-sig") if v1.clean(l)}
    ancla = cargar_ancla(a.ancla)
    enlace = {}
    if a.conductores and os.path.isfile(a.conductores):
        try:
            enlace = json.load(open(a.conductores, encoding="utf-8"))
        except (OSError, ValueError):
            enlace = {}

    ges = v1.coords_gesruta()
    geo = {}
    if a.geocode and os.path.isfile(a.geocode):
        for k, x in json.load(open(a.geocode, encoding="utf-8")).items():
            if isinstance(x, dict) and x.get("lat") is not None and x.get("lon") is not None:
                casa, _, cod = k.partition("|")
                geo[(v1.casa_norm(casa), cod.strip())] = {"lat": float(x["lat"]), "lon": float(x["lon"]), "fuente": v1.fuente_de(x), "nombre": x.get("nombre")}
    ref = v1.mejor(ges, geo)
    trazas = cargar_trazas([("locatel", d) for d in a.locatel] + [("wialon", d) for d in a.wialon])
    paradas_dia = {k: v1.paradas(v["pts"], v["fuente"]) for k, v in trazas.items()}
    internas_dia = {}
    for k, v in trazas.items():
        j0, j1 = v1.jornada(v["pts"])
        internas_dia[k] = v1.internas(paradas_dia[k], j0, j1) if j0 else []
    apr, disc = ({}, []) if a.sin_aprender else v1.aprender(dem, trazas, internas_dia, ref)
    coords = v1.mejor(ref, apr)
    discrepantes = {(x["casa"], x["codigo"]) for x in disc}

    flujo, acts, drvs = coser(trazas)
    fuente_mat = {}
    for (mat, dia), v in trazas.items():
        fuente_mat.setdefault(mat, collections.Counter())[v["fuente"]] += 1
    jornadas_mat = {mat: jornadas_de(pts, paradas_flujo(pts), rest_s) for mat, pts in flujo.items()}
    por_fecha = collections.defaultdict(list)
    for mat, js in jornadas_mat.items():
        for j in js:
            por_fecha[(mat, j["fecha"])].append(j)

    def dist_od(t):
        co, cd = coords.get((t["c"], t["o"])), coords.get((t["c"], t["d"]))
        return v1.hav((co["lat"], co["lon"]), (cd["lat"], cd["lon"])) if co and cd else None
    por_dia = collections.defaultdict(list)
    for idx, t in enumerate(dem):
        cg = ancla.get((t["c"], t["v"], t["cant"])) or []
        t["tipo"] = cg[0]["tipo"] if cg else None
        t["cargas"] = cg
        d = dist_od(t)
        t["dist_od"] = round(d, 1) if d is not None else None
        t["larga"] = t["tipo"] == "nacional" or (d is not None and d >= LARGA_KM)
        por_dia[(t["mat"], t["dia"])].append(idx)
    salida = [None] * len(dem)
    pos_dem = {id(t): i for i, t in enumerate(dem)}
    diag = collections.Counter()
    dias_diag = []
    for (m, d) in sorted(por_dia, key=lambda k: (k[1], k[0])):
        idxs = por_dia[(m, d)]
        idxs.sort(key=lambda i: (v1.natkey(dem[i]["v"]), v1.natkey(dem[i]["cant"])))
        fuente = (fuente_mat.get(m) or collections.Counter()).most_common(1)
        fuente = fuente[0][0] if fuente else None
        if m not in flujo:
            # camion AJENO (vehicu.PROPIO=False: subcontratado, su coste va por IMPPRO) -> nunca tendra traza nuestra; rotularlo asi
            ajeno = any(dem[i].get("propio") is False for i in idxs)
            motivo = "sin_matricula" if not m else ("pendiente_bajada" if m in plates else ("camion_ajeno" if ajeno else "sin_telemetria_o_pendiente_locatel"))
            for i in idxs:
                salida[i] = sin_dato("sin_traza", motivo)
            continue
        jor = por_fecha.get((m, d), [])
        # CARGA HOY, DESCARGA MANANA (aridos, regla de Roberto): si la jornada ANTERIOR del camion acabo cargada (descarga no
        # vista al fin de jornada) y la primera de hoy pasa por ese destino ANTES de cargar nada, es el MISMO viaje: se le suma
        # el tramo de hoy (sin el descanso), se marca 'pernocta_cargado' y los viajes de hoy arrancan tras esa descarga.
        if jor:
            js = jornadas_mat[m]
            jn = jor[0]
            k0 = next((ix for ix, x in enumerate(js) if x is jn), None)
            prev = js[k0 - 1] if k0 else None
            if prev and prev.get("ciclos") and (jn["ini"] - prev["fin"]) <= 40 * 3600:
                c = prev["ciclos"][-1]
                t = c.get("viaje")
                if t is not None and c.get("falta") == "descarga_no_vista_fin_jornada" and not c.get("partes") and not jn.get("arranque"):
                    td = primer_paso_destino(jn, t, [dem[i] for i in idxs], coords)
                    if td:
                        cd = coords.get((t["c"], t["d"]))
                        kl = len(prev["ciclos"]) - 1
                        c["partes"] = [(prev, prev["c0"] if kl == 0 else c["t0"], prev["c1"], c["t0"], prev["fin"]), (jn, jn["c0"], td, jn["ini"], td)]
                        c["t1"], c["d"], c["falta"] = td, t["d"], "pernocta_cargado"
                        c["descarga"] = {"t_in": td, "t_out": td, "lat": cd["lat"], "lon": cd["lon"], "paso": True}
                        jn["arranque"] = td
                        fuente_p = (fuente_mat.get(m) or collections.Counter()).most_common(1)
                        fuente_p = fuente_p[0][0] if fuente_p else None
                        mm = medir_ciclo(prev, c, kl, kl + 1, fuente_p, sens.get(m), acts.get(m, []), drvs.get(m, []))
                        old = salida[pos_dem[id(t)]] or {}
                        mm.update({"metodo": old.get("metodo") or "geo", "confianza": "alta", "geo_score": (old.get("geo_score") or 0) + MATCH,
                                   "motivo": "pernocta_cargado", "medido": True, "repartido": False})
                        salida[pos_dem[id(t)]] = mm
                        diag["pernocta_cargado"] += 1
        if not jor:
            # ¿hay traza del camion en esas fechas? Si no la hay a ±VENTANA_DIAS (p. ej. 2025, sin bajada), es 'sin traza en esas
            # fechas', no 'sin jornada ese dia' (que sugiere que el camion paro). Rotular bien lo que no se sabe.
            d_ = dt.date.fromisoformat(d)
            if not any((m, (d_ + dt.timedelta(days=k)).isoformat()) in trazas for k in range(-VENTANA_DIAS, VENTANA_DIAS + 1)):
                for i in idxs:
                    salida[i] = sin_dato("sin_traza", "sin_traza_en_esas_fechas")
                continue
        dprev = (dt.date.fromisoformat(d) - dt.timedelta(days=1)).isoformat()
        # el ciclo pertenece al dia de su CARGA (el albaran se hace al cargar), no al de su inicio (que puede ser la vuelta de ayer)
        prestados = [(c, j) for j in por_fecha.get((m, dprev), []) if j["nocturna"] and fecha_de(j["fin"]) == d
                     for c in j["sobrantes"] if fecha_de((c.get("carga") or {}).get("t_in", c["t0"])) == d]
        for j in jor:
            if j["horas"] > MAX_JORNADA_H:
                diag["jornadas_largas"] += 1
        larga_dia = any(j["horas"] > MAX_JORNADA_H for j in jor)
        i_rep = [i for i in idxs if any(c.get("repetida") for c in dem[i]["cargas"])]
        i_larga = [i for i in idxs if i not in i_rep and (dem[i]["larga"] or larga_dia)]
        i_arid = [i for i in idxs if i not in i_rep and i not in i_larga]
        res = {}
        for i in i_rep:
            res[i] = sin_dato("cantera_repetida", "mismo_numero_de_cantera_en_varias_lineas_del_ano", jor[0] if jor else None)
        if i_arid:
            dnext = (dt.date.fromisoformat(d) + dt.timedelta(days=1)).isoformat()
            sig = [dem[i] for i in por_dia.get((m, dnext), []) if not dem[i]["larga"]]
            r = triangular_dia([dem[i] for i in i_arid], jor, prestados, fuente, coords, sens.get(m), acts.get(m, []), drvs.get(m, []), diag, viajes_sig=sig)
            res.update(dict(zip(i_arid, r)))
        if i_larga:
            r = triangular_dia([dem[i] for i in i_larga], jor, [], fuente, coords, sens.get(m), acts.get(m, []), drvs.get(m, []), diag, permitir_ciclos=False)
            for x in r:
                x["pendiente_pasada_nacional"] = True
            res.update(dict(zip(i_larga, r)))
        for i in idxs:
            salida[i] = res[i]
        if a.diag:
            dias_diag.append({"matricula": m, "fecha": d, "viajes": len(idxs), "larga": len(i_larga), "repetidas": len(i_rep), "prestados": len(prestados),
                              "jornadas": [{"ini": iso_min(j["ini"]), "fin": iso_min(j["fin"]), "horas": j["horas"], "nocturna": j["nocturna"],
                                            "paradas": len(j["paradas"]), "modo": j["modo"], "ciclos": len(j["ciclos"] or []),
                                            "asignados": j["asignados"], "sobrantes": len(j["sobrantes"]), "min_sobrantes": j.get("min_sobrantes", 0)} for j in jor],
                              "medidos": sum(1 for i in idxs if salida[i].get("medido"))})

    # ---- SEGUNDA PASADA por camion: albaranes que agrupan VARIOS DIAS. GesRuta no guarda la fecha por ticket (la linea no
    # tiene fecha ni vehiculo; el albaran lleva FECHA/FECHAACORD y puede agrupar entregas de una semana), asi que un ticket
    # sin ciclo en "su" dia se busca en los ciclos SOBRANTES del mismo camion en los dias cercanos, por origen y en orden de
    # nº de ticket (los numeros de cantera son cronologicos). La fecha real pasa a ser la de la traza. Marcado y visible.
    recuperados = 0
    for m in flujo:
        idx_sc = [i for i in range(len(dem)) if dem[i]["mat"] == m and salida[i] and salida[i]["metodo"] == "sin_ciclo" and not dem[i]["larga"]]
        if not idx_sc:
            continue
        sob = sorted(((c, j) for j in jornadas_mat[m] for c in j["sobrantes"]), key=lambda cj: cj[0]["t0"])
        if not sob:
            continue
        fuente_m = ((fuente_mat.get(m) or collections.Counter()).most_common(1) or [("wialon", 0)])[0][0]
        por_o = collections.defaultdict(list)
        for i in idx_sc:
            por_o[dem[i]["o"]].append(i)
        for o, lst in por_o.items():
            lst.sort(key=lambda i: v1.natkey(dem[i]["cant"]))
            ks = [k for k, (c, j) in enumerate(sob) if c.get("o") == o and not c.get("usado")]
            if not ks:
                continue
            def sc(i, k):
                c = sob[k][0]
                dd = abs((dt.date.fromisoformat(fecha_de(c["t0"])) - dt.date.fromisoformat(dem[i]["dia"])).days)
                if dd > VENTANA_DIAS:
                    return -9.0
                d, td = c.get("d"), dem[i]["d"]
                return (0.0 if (d is None or not td) else (MATCH if d == td else MISMATCH)) - 0.05 * dd
            S = [[sc(i, k) for k in ks] for i in lst]
            for li, kk in _dp(S).items():
                if S[li][kk] <= -9.0:
                    continue
                i, k = lst[li], ks[kk]
                c, j = sob[k]
                pos = next((ix for ix, x in enumerate(j["ciclos"] or []) if x is c), 0)
                mm = medir_ciclo(j, c, pos, len(j["ciclos"] or [c]), fuente_m, sens.get(m), acts.get(m, []), drvs.get(m, []))
                mm.update({"metodo": "geo", "confianza": "media", "geo_score": MATCH + S[li][kk], "motivo": "fecha_del_albaran_corregida_por_traza"})
                salida[i] = mm
                c["usado"] = True
                j["sobrantes"] = [x for x in j["sobrantes"] if x is not c]
                recuperados += 1
    diag["recuperados_entre_dias"] = recuperados
    diag["ciclos_sobrantes"] = sum(len(j["sobrantes"]) for js in jornadas_mat.values() for j in js)
    diag["min_sobrantes"] = sum((c["t1"] - c["t0"]) / 60.0 for js in jornadas_mat.values() for j in js for c in j["sobrantes"])

    viajes_out = []
    for t, r in zip(dem, salida):
        co, cd = coords.get((t["c"], t["o"])), coords.get((t["c"], t["d"]))
        j = r.get("jornada")
        cargas = t.get("cargas") or []
        medido = bool(r.get("medido"))
        ch = r.get("conductor_hash")
        chofer_ges = (cargas[0].get("chofer") or "").strip() or None if cargas else None
        lk = enlace.get(ch) or [] if ch else []
        if isinstance(lk, dict):
            lk = [lk]
        chofer_taco = next((str(e.get("codigo_gesruta")).strip() for e in lk if isinstance(e, dict) and e.get("casa") == t["c"] and e.get("codigo_gesruta")), None) \
            or next((str(e.get("codigo_gesruta")).strip() for e in lk if isinstance(e, dict) and e.get("codigo_gesruta")), None)
        viajes_out.append({
            "empresa": t["c"], "viaje": t["v"], "cantera": t["cant"], "matricula": t["mat"],
            "fecha": fecha_de(r["t_ini"]) if medido and r.get("t_ini") else t["dia"], "fecha_gesruta": t["dia"],
            "origen": t["o"], "destino": t["d"], "tipo": t.get("tipo"), "larga_distancia": bool(t.get("larga")), "dist_od_km": t.get("dist_od"),
            "km": r.get("km"), "duracion_min": r.get("duracion_min"), "litros": r.get("litros"), "litros_calibrados": r.get("litros_calibrados"),
            "metodo": r.get("metodo"), "medido": medido, "fuente": (j["pts"][0]["f"] if j and j.get("pts") else None),
            "km_fuente": r.get("km_fuente"), "repartido": r.get("repartido"), "confianza": r.get("confianza"), "motivo": r.get("motivo"),
            "t_ini": iso_min(r.get("t_ini")), "t_fin": iso_min(r.get("t_fin")), "orden_dia": None, "ciclo": r.get("orden_ciclo"), "geo_score": r.get("geo_score"),
            "jornada_ini": iso_min(j["ini"]) if j else None, "jornada_fin": iso_min(j["fin"]) if j else None,
            "jornada_nocturna": bool(j and j.get("nocturna")), "jornada_prestada": bool(r.get("prestada")),
            "min_conduccion": r.get("min_conduccion"), "min_espera": r.get("min_espera"), "min_otros": r.get("min_otros"),
            "min_disponible": r.get("min_disponible"), "min_descanso": r.get("min_descanso"), "min_fuente": r.get("min_fuente"),
            "conductor_hash": ch, "chofer_tacografo": chofer_taco, "chofer_gesruta": chofer_ges,
            "chofer_coincide": (None if not (chofer_taco and chofer_ges) else chofer_taco.lstrip("0") == chofer_ges.lstrip("0")),
            "viajes_dia": len(por_dia[(t["mat"], t["dia"])]),
            "albara": cargas[0]["albara"] if len(cargas) == 1 else None, "linea": cargas[0]["linea"] if len(cargas) == 1 else None,
            "cliente": cargas[0]["cliente"] if cargas else None, "n_cargas_clave": len(cargas) if cargas else None,
            "pendiente_pasada_nacional": bool(r.get("pendiente_pasada_nacional")),
            "coord_origen": co["fuente"] if co else None, "coord_destino": cd["fuente"] if cd else None,
            "coord_revisar": ((t["c"], t["o"]) in discrepantes) or ((t["c"], t["d"]) in discrepantes)})
    for (m, d), idxs in por_dia.items():
        for pos, i in enumerate(idxs):
            viajes_out[i]["orden_dia"] = pos + 1

    tot = len(viajes_out)
    met = collections.Counter(x["metodo"] for x in viajes_out)
    arid = [x for x in viajes_out if not x["larga_distancia"]]
    larg = [x for x in viajes_out if x["larga_distancia"]]
    nmed = sum(1 for x in viajes_out if x["medido"])
    resumen = {"viajes": tot, "aridos": len(arid), "larga_distancia_pendiente_pasada_2": len(larg),
               "por_metodo": {k: {"viajes": n, "pct": round(100.0 * n / tot, 1)} for k, n in met.most_common()},
               "medido_por_viaje": {"viajes": nmed, "pct": round(100.0 * nmed / tot, 1),
                                    "aridos_pct": round(100.0 * sum(1 for x in arid if x["medido"]) / max(1, len(arid)), 1)},
               "confianza_medidos": dict(collections.Counter(x["confianza"] for x in viajes_out if x["medido"])),
               "descarga_no_vista": sum(1 for x in viajes_out if x["medido"] and (x["motivo"] or "").startswith("descarga_no_vista")),
               "con_hora_inicio_fin": sum(1 for x in viajes_out if x["t_ini"]),
               "horas_del_tacografo": sum(1 for x in viajes_out if x["min_fuente"] == "tacografo"),
               "con_conductor_tacografo": sum(1 for x in viajes_out if x["conductor_hash"]),
               "chofer_coincide_gesruta": dict(collections.Counter(str(x["chofer_coincide"]) for x in viajes_out if x["chofer_coincide"] is not None)),
               "viajes_en_jornada_nocturna": sum(1 for x in viajes_out if x["jornada_nocturna"]),
               "viajes_con_ciclo_prestado": sum(1 for x in viajes_out if x["jornada_prestada"]),
               "viajes_con_fecha_real_distinta_gesruta": sum(1 for x in viajes_out if x["fecha"] != x["fecha_gesruta"]),
               "sin_traza_por_motivo": dict(collections.Counter(x["motivo"] for x in viajes_out if x["metodo"] == "sin_traza")),
               "jornadas": {"total": sum(len(js) for js in jornadas_mat.values()),
                            "nocturnas": sum(1 for js in jornadas_mat.values() for j in js if j["nocturna"]),
                            "largas_gt_%dh" % int(MAX_JORNADA_H): diag["jornadas_largas"],
                            "modo": dict(collections.Counter(j["modo"] for js in jornadas_mat.values() for j in js if j["modo"]))},
               "ciclos_sobrantes_sin_viaje": diag["ciclos_sobrantes"], "horas_sobrantes_sin_viaje": round(diag["min_sobrantes"] / 60.0, 1),
               "descarga_por_paso": sum(1 for x in viajes_out if x["motivo"] == "descarga_por_paso"),
               "carga_por_paso": sum(1 for x in viajes_out if x["motivo"] == "carga_por_paso"),
               "pernocta_cargado_carga_hoy_descarga_manana": sum(1 for x in viajes_out if x["motivo"] == "pernocta_cargado"),
               "descarga_no_vista_fin_jornada": sum(1 for x in viajes_out if x["motivo"] == "descarga_no_vista_fin_jornada"),
               "ciclos_prestados_usados": diag["ciclos_prestados_usados"],
               "viajes_repartidos_de_sobrantes": diag["viajes_repartidos_de_sobrantes"], "viajes_sin_ciclo": met.get("sin_ciclo", 0),
               "tickets_recuperados_en_otro_dia": diag["recuperados_entre_dias"],
               "cantera_repetida_error_grabacion": met.get("cantera_repetida", 0),
               "trazas_disponibles": {"wialon": sum(1 for v in trazas.values() if v["fuente"] == "wialon"),
                                      "locatel": sum(1 for v in trazas.values() if v["fuente"] == "locatel"), "camiones": len(flujo),
                                      "dias_con_tacografo": sum(1 for v in trazas.values() if v["act"])},
               "coords": {"gesruta_maestro": len(ges), "geocode": len(geo), "aprendidas": len(apr), "discrepancias_gt5km": sum(1 for x in disc if x["tipo"] == "discrepancia")},
               "parametros": {"rest_h": a.rest_h, "dwell_min": a.dwell_min, "hub_eps_km": HUB_EPS_KM, "km_min_ciclo": KM_MIN_CICLO,
                              "min_min_ciclo": MIN_MIN_CICLO, "larga_km": LARGA_KM, "max_jornada_h": MAX_JORNADA_H,
                              "alineamiento": {"gap": GAP, "match": MATCH, "mismatch": MISMATCH}}}
    meta = {"version": 2, "generado": dt.datetime.now().strftime("%Y-%m-%dT%H:%M"), "clave": "(empresa, viaje, cantera)",
            "hora": "t_ini/t_fin/jornada_* en hora de Madrid (CET/CEST), sin zona",
            "metodos": "geo = ciclo cortado por la geografia (carga y descarga en el mapa) / orden = ciclo por secuencia de GesRuta: ambos MEDIDOS con t_ini/t_fin; dia = repartido de ciclos sobrantes; sin_ciclo = mas albaranes que ciclos (SIN DATO, no 0); sin_traza; cantera_repetida (error de grabacion)",
            "jornada": "flujo continuo por camion; corte por descanso > rest_h o hueco de datos, NUNCA por medianoche; fechada por su primer movimiento",
            "ciclo": "del fin del ciclo anterior a la salida de la descarga (v1); el ultimo hasta el fin de la jornada; primero/ultimo con el ralenti de borde",
            "asignacion": "por grupos (origen, destino) en orden de GesRuta (cronologico dentro de cada cantera, no entre canteras); respaldo: alineamiento monotono por programacion dinamica",
            "tacografo": "min_conduccion/otros/disponible/descanso de los cambios de actividad del tacografo dentro de la traza (min_fuente=tacografo); si no cubre el viaje, conduccion por movimiento (traza). conductor_hash = tarjeta (hash) que llevaba el camion; chofer_tacografo = su codigo GesRuta si esta enlazado",
            "larga_distancia": "origen-destino >= 200 km, tipo nacional del ancla, o jornada > 24 h: salen como dia (repartido) con pendiente_pasada_nacional=true",
            "litros": "crudo = reduccion monotona del contador; calibrados = tabla del sensor (ERP) + reduccion monotona"}
    json.dump({"meta": meta, "resumen": resumen, "viajes": viajes_out}, open(a.salida, "w", encoding="utf-8"), ensure_ascii=False)
    if a.diag:
        json.dump({"meta": meta, "resumen": resumen, "dias": dias_diag}, open(a.diag, "w", encoding="utf-8"), ensure_ascii=False)
    print(json.dumps(resumen, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
