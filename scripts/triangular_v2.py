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
import argparse, bisect, collections, datetime as dt, glob, gzip, json, math, os, statistics, sys

D = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, D)
import triangular_v1 as v1  # noqa: E402

V_PARADO, V_MOVIL = v1.V_PARADO, v1.V_MOVIL
DWELL_S = 180                              # parada = >= 3 min (las descargas de aridos duran 5-10 min; alguna menos de 5)
KM_MIN_CICLO, MIN_MIN_CICLO = 1.0, 8.0     # ciclo valido (hub): >= 1 km y >= 8 min; si no, se funde con el anterior
HUB_EPS_KM = 0.35                          # paradas a < 350 m son el mismo sitio
HUECO_S = 1800                             # 30 min o mas sin posicion = sin señal, no parada (igual que el mapa del dia)
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
                elif e.get("k") == "tco_driver1_id":
                    # tarjeta en la ranura 1 (hash) o SIN tarjeta (None): hay que ver cuando se saca, no solo cuando se mete
                    v = e.get("v")
                    drv.append((int(e["t"]), v if isinstance(v, str) and v.startswith("h:") else None))
            tr[(mat, dia)] = {"fuente": fuente, "pts": pts, "act": act, "drv": drv}
    return tr


def coser(trazas):
    flujo, acts, drvs = collections.defaultdict(list), collections.defaultdict(list), collections.defaultdict(list)
    for (mat, dia), v in trazas.items():
        flujo[mat].extend(v["pts"]); acts[mat].extend(v["act"]); drvs[mat].extend(v["drv"])
    for mat in flujo:
        flujo[mat].sort(key=lambda q: q["t"]); acts[mat].sort(key=lambda e: e[0]); drvs[mat].sort(key=lambda e: e[0])
    return flujo, acts, drvs


def es_mov(q):
    if q["f"] == "locatel":
        return (q.get("parada_min") or 0) * 60 < DWELL_S or (q["s"] or 0) > V_MOVIL
    return (q["s"] or 0) > V_MOVIL


def paradas_flujo(pts, hueco_s=HUECO_S):
    """Paradas de la traza continua de un camion. Con hueco_s se cortan donde pasan hueco_s o mas sin posicion: sin señal no
    se sabe que hizo el camion (1895CNR 09/01/2026 salia «parado 9.565 min» en un sitio medio entre Sabon y Bertoa por un
    hueco de 6,2 dias). hueco_s=None es para los DESCANSOS que cortan jornadas: un hueco no rompe el descanso (dia sin datos
    con el camion en la nave). No se corta por un salto de sitio SIN hueco: medido el 26/09 en 4,07 M pares de puntos
    parados seguidos, solo 1.084 saltan mas de 350 m y son ruido del GPS (5003MBV oscila 0,4-5 km parado; 5158LHG tiene
    puntos sueltos a mas de 5 km que vuelven al sitio); cortar ahi deshacia paradas y descansos reales."""
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
            while (j + 1 < n and pts[j + 1]["f"] != "locatel" and (pts[j + 1]["s"] or 0) <= V_PARADO
                   and not (hueco_s and pts[j + 1]["t"] - pts[j]["t"] >= hueco_s)):
                j += 1
            if pts[j]["t"] - pts[i]["t"] >= DWELL_S:
                seg = pts[i:j + 1]
                out.append({"t_in": pts[i]["t"], "t_out": pts[j]["t"],
                            "lat": statistics.median(x["lat"] for x in seg), "lon": statistics.median(x["lon"] for x in seg)})
            i = j + 1
        else:
            i += 1
    return out


def jornadas_de(pts, paradas, rest_s, reposos=None):
    """Jornadas = tramos entre descansos de rest_s o mas. Descanso = parada larga aunque tenga huecos sin señal dentro
    (reposos: paradas_flujo(pts, None)) o hueco sin posicion de rest_s o mas. j["paradas"] = las paradas cortas."""
    if reposos is None:
        reposos = paradas_flujo(pts, None)
    cortes = [(p["t_in"], p["t_out"]) for p in reposos if p["t_out"] - p["t_in"] >= rest_s]
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
            # descansos SOLAPADOS (una parada de dias con un hueco sin señal dentro) van por su inicio: el fin del ultimo no
            # es el mayor. Sin max, la jornada arrancaba al acabar el hueco (0063NBM: 24/08/2025 00:04, carga el 25 a las 12:00)
            c0 = max(c0, cortes[ci][1])
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


def tacografo_tramo(acts, drvs, d0, d1, mov_s=0):
    """Desglose del tacografo de la ranura 1 en [d0, d1], SOLO si es fiable: (1) hay tarjeta en la ranura 1 al menos la
    mitad del tramo y (2) la conduccion registrada cubre al menos la mitad del tiempo que el camion se movio segun la traza
    (con tarjeta en la ranura 1 el tacografo pasa solo a conduccion al moverse). Medido 23/09: en 5 camiones (5735JVZ, 4029KXY,
    8111JSB, 8810GKT, 6081FHD) el localizador no recibe el tacografo: sin tarjeta y la actividad congelada en 'descanso' con el
    camion en marcha. Ahi el desglose NO se usa (se usa la traza) y la fila lo dice (min_coherente/motivo_min)."""
    segs = _integrar(acts, d0, d1)
    cubierto = sum(segs.values())
    dur = max(1, d1 - d0)
    res = {"min_conduccion": None, "min_otros": None, "min_disponible": None, "min_descanso": None, "tacografo": False,
           "conductor": None, "coherente": None, "motivo": None}
    d = _integrar(drvs, d0, d1)
    con_tarjeta = sum(d.values())
    if d:
        h, s = max(d.items(), key=lambda kv: kv[1])
        if s >= 0.5 * dur:
            res["conductor"] = h
    if cubierto < 0.5 * dur:
        res["motivo"] = "sin_datos_de_tacografo"
        return res
    if con_tarjeta < 0.5 * dur:
        res.update({"coherente": False, "motivo": "sin_tarjeta_en_ranura_1"})
        return res
    if mov_s >= 300 and segs.get(3, 0) < 0.5 * mov_s:
        res.update({"coherente": False, "motivo": "tacografo_no_refleja_la_conduccion"})
        return res
    for v, nombre in ACT.items():
        res["min_" + nombre] = round(segs.get(v, 0) / 60.0, 1)
    res.update({"tacografo": True, "coherente": True})
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
    tc = tacografo_tramo(acts, drvs, d0, d1, cond)
    m["min_conduccion_traza"] = round(cond / 60.0, 1)
    m["min_coherente"], m["motivo_min"] = tc["coherente"], tc["motivo"]
    if tc["tacografo"]:
        m.update({k: tc[k] for k in ("min_conduccion", "min_otros", "min_disponible", "min_descanso")})
        m["min_fuente"] = "tacografo"
        # desglose del tacografo = PARTICION de la duracion: conduccion + otros + disponible + descanso + sin_dato = duracion
        m["min_sin_dato"] = round(max(0.0, (m["duracion_min"] or 0) - sum(tc[k] or 0 for k in ("min_conduccion", "min_otros", "min_disponible", "min_descanso"))), 1)
    else:
        m.update({"min_conduccion": m["min_conduccion_traza"], "min_otros": None, "min_disponible": None, "min_descanso": None,
                  "min_fuente": "traza", "min_sin_dato": None})
    # min_espera = COMPLEMENTO de la conduccion (todo lo que no es conducir). NO es una categoria mas: no se suma al desglose.
    m["min_espera"] = round(max(0.0, (m["duracion_min"] or 0) - (m["min_conduccion"] or 0)), 1)
    m["conductor_hash"] = tc["conductor"]
    return m


def km_litros(pts, fuente, tablas, a, b):
    """(km, litros) del contador entre a y b (None si el tramo es vacio o no tiene contador)."""
    if a is None or b is None or b <= a:
        return 0.0, 0.0
    x = v1.medir({"fuente": fuente, "pts": pts}, a, b, tablas, a, b)
    return x.get("km"), (x.get("litros_calibrados") if x.get("litros_calibrados") is not None else x.get("litros"))


# ---------------------------------------------------------------- geografia: clasificar paradas y cortar ciclos
def cerca_cod(stop, cod, coords, casa):
    if not cod or not stop:
        return 0.0
    c = coords.get((casa, cod))
    if not c or v1.RADIO_MATCH.get(c["fuente"], 1) is None:
        return 0.0
    return MATCH if v1.cerca(stop, c, c["fuente"], c.get("radio_m")) else MISMATCH


def rotulo_en_lugar(stop, cod, coords, casa, cercano):
    """Rotulo de una parada de carga o descarga: el lugar del albaran SOLO si la parada cae en su radio; si no, el lugar
    conocido mas cercano (cercano(lat, lon), a < 700 m) o None. En hormigon el albaran repite la planta como destino y la
    obra esta a km: la descarga salia «SABO» con el GPS a 14 km."""
    return cod if cerca_cod(stop, cod, coords, casa) == MATCH else cercano(stop["lat"], stop["lon"])


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
            "min_sin_dato": None, "min_fuente": None, "min_coherente": None, "motivo_min": None,
            "conductor_hash": None, "jornada": j, "orden_ciclo": None, "geo_score": None,
            "km_cargado": None, "km_vacio": None, "litros_cargado": None, "litros_vacio": None, "min_transcurridos": None}


SUMABLES = ("km", "litros", "litros_calibrados", "duracion_min", "min_conduccion", "min_conduccion_traza", "min_espera", "min_otros",
            "min_disponible", "min_descanso", "min_sin_dato", "km_cargado", "km_vacio", "litros_cargado", "litros_vacio", "min_transcurridos")


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
        # CARGADO / VACIO (tarifas): vacio = del inicio del ciclo a llegar a cargar; cargado = de salir de la carga a llegar a
        # la descarga. Solo si se conocen las dos visitas; si no, null (no se inventa el reparto).
        ca, de = c.get("carga") or {}, c.get("descarga") or {}
        if ca.get("t_in") is not None and de.get("t_in") is not None and c["t0"] <= ca["t_in"] <= ca.get("t_out", ca["t_in"]) <= de["t_in"] <= c["t1"]:
            kv, lv = km_litros(j["pts"], fuente, tablas, c["t0"], ca["t_in"])
            kc, lc = km_litros(j["pts"], fuente, tablas, ca.get("t_out", ca["t_in"]), de["t_in"])
            m.update({"km_vacio": kv, "km_cargado": kc, "litros_vacio": lv, "litros_cargado": lc})
        # hitos del ciclo (hora real de llegar a cargar, salir cargado y llegar a descargar): los usa la pasada de largo
        # recorrido para conciliar con los ciclos locales y salen al JSON como t_carga / t_carga_fin / t_descarga
        m.update({"t_carga_in": ca.get("t_in"), "t_carga_out": ca.get("t_out", ca.get("t_in")), "t_descarga_in": de.get("t_in"), "t_descarga_out": de.get("t_out", de.get("t_in"))})
    m.setdefault("km_cargado", None); m.setdefault("km_vacio", None); m.setdefault("litros_cargado", None); m.setdefault("litros_vacio", None)
    m.setdefault("t_carga_in", None); m.setdefault("t_carga_out", None); m.setdefault("t_descarga_in", None); m.setdefault("t_descarga_out", None)
    m.setdefault("min_transcurridos", m.get("duracion_min"))
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
            "t_ini": None, "t_fin": None, "jornada": j, "orden_ciclo": None, "geo_score": None,
            "tramos": [(a, b, jj) for (a, b, jj) in tramos], "k_reparto": k}   # para recortarlo si un viaje largo pisa sus tramos


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


# ---------------------------------------------------------------- HORMIGON POR VIAJE (plantas aprendidas de la traza)
def aprender_plantas(dem_h, jornadas_mat):
    """Planta REAL de cada codigo de origen de hormigon, aprendida de la traza. El maestro y el geocode no valen aqui
    (PREBETONG CORUÑA apunta a la cantera a 40 km; PLANTA DE SABON al centro de Arteixo). Regla: en los dias en que todos los
    albaranes de la hormigonera son de UN origen, el grupo de paradas mas visitado del dia (>= 2 visitas: se vuelve a cargar)
    vota por ese codigo; gana el grupo con mas dias (>= 2). Devuelve {(casa, cod): {lat, lon, dias, visitas, radio_m}}."""
    por_dia = collections.defaultdict(list)
    for t in dem_h:
        if t["mat"] and t["o"]:
            por_dia[(t["mat"], t["dia"])].append(t)
    votos = collections.defaultdict(lambda: collections.defaultdict(lambda: [0, 0, 0.0, 0.0]))
    celda = lambda p: (round(p["lat"] / 0.004), round(p["lon"] / 0.005))  # noqa: E731  (~440 x 400 m)
    for (m, d), ts in por_dia.items():
        origs = {(t["c"], t["o"]) for t in ts}
        if len(origs) != 1 or m not in jornadas_mat:
            continue
        key = next(iter(origs))
        jor = [j for j in jornadas_mat[m] if j["fecha"] == d]
        paradas = [p for j in jor for p in j["paradas"] if p["t_out"] - p["t_in"] >= 180]
        if not paradas:
            continue
        cuenta = collections.Counter(celda(p) for p in paradas)
        # donde la hormigonera DUERME o acaba la jornada pesa como 3 visitas, pero solo si tambien para alli de dia (la planta;
        # no la casa del conductor): asi la planta gana aunque ese dia todas las cargas fueran a una misma obra
        for j in jor:
            if j["pts"]:
                for q in (j["pts"][0], j["pts"][-1]):
                    c_ = celda(q)
                    if cuenta.get(c_):
                        cuenta[c_] += 3
        cel, n = cuenta.most_common(1)[0]
        if n < 2:
            continue
        ps = [p for p in paradas if celda(p) == cel]
        v = votos[key][cel]
        v[0] += 1; v[1] += n; v[2] += sum(p["lat"] for p in ps) / len(ps); v[3] += sum(p["lon"] for p in ps) / len(ps)
    plantas = {}
    for key, cels in votos.items():
        cel, v = max(cels.items(), key=lambda kv: (kv[1][0], kv[1][1]))
        if v[0] >= 2:
            plantas[key] = {"lat": v[2] / v[0], "lon": v[3] / v[0], "dias": v[0], "visitas": v[1], "radio_m": 450}
    return plantas


def planta_en(q, plantas):
    return next((k for k, pl in plantas.items() if abs(q["lat"] - pl["lat"]) <= 0.006 and v1.hav((q["lat"], q["lon"]), (pl["lat"], pl["lon"])) * 1000.0 <= pl["radio_m"]), None)


def visitas_por_puntos(j, plantas):
    """Entradas de la TRAZA en una planta aunque no lleguen a parada de 3 min (cargar hormigon puede durar 2 min): puntos
    consecutivos dentro del radio, con >= 3 puntos o frenada (< 10 km/h). Pasar por delante por la carretera no cuenta."""
    out, cur = [], None
    for q in j["pts"]:
        key = planta_en(q, plantas)
        if cur and key == cur["key"]:
            cur["t_out"] = q["t"]; cur["n"] += 1; cur["vmin"] = min(cur["vmin"], q["s"] or 0)
            continue
        if cur:
            out.append(cur); cur = None
        if key:
            cur = {"key": key, "t_in": q["t"], "t_out": q["t"], "n": 1, "vmin": q["s"] or 0, "lat": q["lat"], "lon": q["lon"]}
    if cur:
        out.append(cur)
    return [v for v in out if v["n"] >= 3 or v["vmin"] <= 10]


def visitas_plantas(j, plantas):
    """Visitas de la jornada a cualquier planta aprendida: paradas dentro de su radio (y entradas de la traza sin parada, para
    las cargas rapidas), fundiendo las consecutivas en la misma planta sin parada fuera entre medias (cola y cargadero). Si la
    jornada ARRANCA en una planta (durmio alli) la salida es la carga del primer viaje, y si ACABA en una planta la llegada
    cierra el ultimo: los descansos no son paradas de la jornada, asi que se anaden como visitas de borde. [(t_in, t_out, key, parada)]."""
    out = []
    for s in j["paradas"]:
        out.append((s["t_in"], s["t_out"], planta_en(s, plantas), s))
    out.sort(key=lambda x: x[0])
    vis = []
    for (a, b, key, s) in out:
        if key is None:
            vis.append((a, b, None, s))
        elif vis and vis[-1][2] == key:
            vis[-1] = (vis[-1][0], b, key, vis[-1][3])
        else:
            vis.append((a, b, key, s))
    vis = [v for v in vis if v[2] is not None]
    pts = j["pts"]
    if pts:
        k0 = planta_en(pts[0], plantas)
        if k0 and not (vis and vis[0][0] <= j["ini"] + 60):
            vis.insert(0, (j["c0"], j["ini"], k0, {"lat": pts[0]["lat"], "lon": pts[0]["lon"], "t_in": j["c0"], "t_out": j["ini"]}))
        k1 = planta_en(pts[-1], plantas)
        if k1 and not (vis and vis[-1][1] >= j["fin"] - 60):
            vis.append((j["fin"], j["c1"], k1, {"lat": pts[-1]["lat"], "lon": pts[-1]["lon"], "t_in": j["fin"], "t_out": j["c1"]}))
    return vis


def ciclos_plantas(j, plantas, fuente, tablas):
    """Ciclos de hormigonera: de la LLEGADA a una planta (a cargar) a la llegada a la siguiente planta (vuelta de la obra). Si
    la jornada empieza fuera de planta (viene de casa), el primer tramo se funde con el primer ciclo (como en aridos: el primer
    viaje incluye la ida desde la base). Obra = parada mas larga fuera de plantas DESPUES de salir de la planta. Un ciclo sin
    obra ni recorrido (lavado, espera en planta, cambio de planta) no es un viaje y se funde con el anterior."""
    vis = visitas_plantas(j, plantas)
    if not vis:
        return []
    ini, fin = j.get("arranque") or j["ini"], j["fin"]
    ids_pl = {id(v[3]) for v in vis}
    otras = [s for s in j["paradas"] if id(s) not in ids_pl]
    cortes = []
    if vis[0][0] > ini + 600:
        cortes.append((ini, vis[0][0], None))
    for k, v in enumerate(vis):
        b = vis[k + 1][0] if k + 1 < len(vis) else max(fin, v[1])
        if b - v[0] >= 60:
            cortes.append((v[0], b, v))
    ciclos = []
    for (a, b, v) in cortes:
        dentro = [s for s in otras if s["t_out"] > a and s["t_in"] < b and (v is None or s["t_in"] >= v[1] - 60)]
        obra = max(dentro, key=lambda s: s["t_out"] - s["t_in"]) if dentro else None
        ciclos.append({"t0": a, "t1": b,
                       "carga": ({"t_in": v[0], "t_out": v[1], "lat": v[3]["lat"], "lon": v[3]["lon"]} if v else None),
                       "descarga": ({"t_in": obra["t_in"], "t_out": obra["t_out"], "lat": obra["lat"], "lon": obra["lon"]} if obra else None),
                       "o": v[2][1] if v else None, "d": None, "falta": None if obra else "obra_no_vista", "planta": v[2] if v else None, "obra": obra})
    i = 0
    while i < len(ciclos) and len(ciclos) > 1:
        c = ciclos[i]
        m = v1.medir({"fuente": fuente, "pts": j["pts"]}, c["t0"], c["t1"], tablas, c["t0"], c["t1"])
        if c["obra"] is not None and (m["km"] or 0) >= KM_MIN_CICLO and (m["duracion_min"] or 0) >= MIN_MIN_CICLO:
            i += 1
            continue
        if i > 0:
            p = ciclos[i - 1]; p["t1"] = c["t1"]
            if c["obra"] and (not p["obra"] or (c["obra"]["t_out"] - c["obra"]["t_in"]) > (p["obra"]["t_out"] - p["obra"]["t_in"])):
                p["obra"], p["descarga"], p["falta"] = c["obra"], c["descarga"], None
            del ciclos[i]
        else:
            n = ciclos[1]; n["t0"] = c["t0"]
            if not n["carga"] and c["carga"]:
                n["carga"], n["o"], n["planta"] = c["carga"], c["o"], c["planta"]
            del ciclos[0]
    return ciclos


CAP_HORMIGONERA_M3 = 8.5


def agrupar_por_m3(lst, n_ciclos, viajes, cap=CAP_HORMIGONERA_M3):
    """GRUPAJE en hormigon: cuando hay mas albaranes que ciclos en la planta, varios albaranes van en la MISMA carga (8 m3 + un
    resto de 2 m3, o dos de 4). Se fusionan pares adyacentes (en orden de GesRuta) de menor m3 conjunto, mientras quepan en
    la cuba, hasta que los grupos igualen a los ciclos. Si ya no cabe ninguna fusion, se para (los que sobren, sin ciclo)."""
    grupos = [[i] for i in lst]
    m3 = lambda g: sum(float(viajes[i].get("m3") or 0) for i in g)  # noqa: E731
    while len(grupos) > n_ciclos and len(grupos) > 1:
        mejor = None
        for k in range(len(grupos) - 1):
            s = m3(grupos[k]) + m3(grupos[k + 1])
            if s <= cap and (mejor is None or s < mejor[0]):
                mejor = (s, k)
        if mejor is None:
            break
        k = mejor[1]
        grupos[k:k + 2] = [grupos[k] + grupos[k + 1]]
    return grupos


def triangular_hormigon(viajes, jor, plantas, coords, fuente, tablas, acts, drvs, diag):
    """Hormigon por viaje en UN (camion, dia): ciclos por plantas aprendidas (una jornada puede cargar en dos plantas); cada
    albaran va a un ciclo de SU planta (origen, o una planta a < 3 km: dos codigos para la misma central) en orden de GesRuta
    (cronologico dentro de cada planta, como en aridos); varios albaranes en la misma carga = grupaje por m3 (repartido);
    'hora_carga' (albaran impreso / app del conductor), si viene, es ancla dura (+-30 min sobre la salida de la planta).
    Un albaran con nº de cantera REPETIDO ocupa su turno en el orden (es una carga real) pero no se mide (error de grabacion).
    Si las plantas aprendidas dan menos ciclos que albaranes (planta no aprendida, trabajo nocturno), se prueba el corte por el
    hub del dia (como el piloto) y se usa si da mas ciclos, con confianza baja.
    Ciclos sin albaran = cargas que GesRuta no tiene (quedan como sobrantes, visibles); albaranes sin ciclo = SIN DATO."""
    n = len(viajes)
    res = [None] * n
    casa = viajes[0]["c"]
    ciclos = []
    for j in jor:
        cic = ciclos_plantas(j, plantas, fuente, tablas)
        modo = "plantas" if cic else "sin_planta"
        if len(cic) < n:
            codigos = {c for t in viajes for c in (t["o"], t["d"]) if c}
            hub, hm = elegir_hub(sitios_jornada(j, codigos, coords, casa), viajes)
            cic2 = particionar_hub(j, hub, hm, fuente, tablas, acts, drvs) if hub else []
            if len(cic2) > len(cic):
                for c in cic2:
                    c["planta"], c["obra"] = None, c.get("descarga")
                cic, modo = cic2, "hub_dia"
                diag["hormigon_dias_por_hub"] += 1
        j["ciclos"], j["modo"], j["sobrantes"], j["asignados"] = cic, modo, [], 0
        for k, c in enumerate(cic):
            ciclos.append((j, k, c))
    ciclos.sort(key=lambda x: x[2]["t0"])
    usados = set()

    def medir_c(idx):
        j, k, c = ciclos[idx]
        m = medir_ciclo(j, c, k, len(j["ciclos"]), fuente, tablas, acts, drvs)
        de = c.get("descarga") or {}
        if de.get("t_out") is not None and c["t1"] > de["t_out"]:          # vuelta de la obra a la planta: en vacio
            kv, lv = km_litros(j["pts"], fuente, tablas, de["t_out"], c["t1"])
            if kv is not None:
                m["km_vacio"] = round((m.get("km_vacio") or 0) + kv, 2)
            if lv is not None:
                m["litros_vacio"] = round((m.get("litros_vacio") or 0) + lv, 2)
        ob = c.get("obra")
        m["obra"] = {"lat": round(ob["lat"], 5), "lon": round(ob["lon"], 5), "min": round((ob["t_out"] - ob["t_in"]) / 60.0, 0)} if ob else None
        m["geo_score"] = None
        return m

    def asigna(ids, idx, conf, motivo=None):
        """Un grupo de albaranes (1 o varios: misma carga) a un ciclo. La medida se reparte entre los no repetidos."""
        j, k, c = ciclos[idx]
        usados.add(idx); c["viaje"] = viajes[ids[0]]; j["asignados"] += 1
        vivos = [i for i in ids if not viajes[i].get("_repetida")]
        for i in ids:
            if viajes[i].get("_repetida"):
                res[i] = sin_dato("cantera_repetida", "mismo_numero_de_cantera_en_varias_lineas_del_ano", j)
        if not vivos:
            return
        m = medir_c(idx)
        nv = len(vivos)
        for i in vivos:
            r = dict(m)
            if nv > 1:
                for kk in SUMABLES:
                    if r.get(kk) is not None:
                        r[kk] = round(r[kk] / nv, 2)
                r.update({"repartido": True, "metodo": "geo", "confianza": "media",
                          "motivo": "grupaje_%d_albaranes_misma_carga" % nv + ("; " + motivo if motivo else "")})
                diag["hormigon_grupaje"] += 1
            else:
                r.update({"metodo": "geo", "confianza": conf, "motivo": motivo or c.get("falta")})
            res[i] = r

    def cand_planta(key):
        pk = plantas.get(key)
        return [idx for idx, (j, k, c) in enumerate(ciclos) if idx not in usados and c.get("planta") and
                (c["planta"] == key or (pk and v1.hav((plantas[c["planta"]]["lat"], plantas[c["planta"]]["lon"]), (pk["lat"], pk["lon"])) <= 3.0))]

    # 1) ancla dura: hora de carga (impresa por la planta) en la carga
    for i, t in enumerate(viajes):
        hc = t.get("hora_carga") or ((t.get("cargas") or [{}])[0].get("hora_carga") if t.get("cargas") else None)
        if not hc or len(str(hc)) < 5:
            continue
        try:
            hh, mi = int(str(hc)[:2]), int(str(hc)[3:5])
        except ValueError:
            continue
        mejor = None
        for idx, (j, k, c) in enumerate(ciclos):
            if idx in usados or not c.get("carga"):
                continue
            l_ = local(c["carga"]["t_out"])
            dif = abs((l_.hour * 60 + l_.minute) - (hh * 60 + mi))
            if dif <= 30 and (mejor is None or dif < mejor[0]):
                mejor = (dif, idx)
        if mejor:
            asigna([i], mejor[1], "alta", "hora_carga_impresa")
            diag["hormigon_ancla_hora_carga"] += 1
    # 2) por planta (o planta a < 3 km), en orden de GesRuta dentro de la planta; grupaje por m3 si hay mas albaranes que
    #    ciclos; las repetidas ocupan turno
    por_o = collections.defaultdict(list)
    for i, t in enumerate(viajes):
        if res[i] is None:
            por_o[(t["c"], t["o"])].append(i)
    for key, lst in por_o.items():
        lst.sort(key=lambda i: (v1.natkey(viajes[i]["v"]), v1.natkey(viajes[i]["cant"])))
        cand = cand_planta(key)
        if not cand:
            continue
        grupos = agrupar_por_m3(lst, len(cand), viajes)
        cuadra = len(grupos) == len(cand)
        nota = None if cuadra else "ciclos_y_albaranes_no_cuadran (%d ciclos, %d albaranes)" % (len(cand), len(lst))
        for g, idx in zip(grupos, cand):
            asigna(g, idx, "alta" if cuadra else "media", nota)
    # 3) respaldo: albaranes sin planta aprendida (o sin ciclo en la suya) -> ciclos libres en orden (grupaje por m3), baja
    pend = sorted((i for i in range(n) if res[i] is None), key=lambda i: (v1.natkey(viajes[i]["v"]), v1.natkey(viajes[i]["cant"])))
    libres = [idx for idx in range(len(ciclos)) if idx not in usados]
    if pend and libres:
        for g, idx in zip(agrupar_por_m3(pend, len(libres), viajes), libres):
            asigna(g, idx, "baja", "ciclo_de_otra_planta_o_sin_planta_aprendida")
    for i in range(n):
        if res[i] is None:
            if viajes[i].get("_repetida"):
                res[i] = sin_dato("cantera_repetida", "mismo_numero_de_cantera_en_varias_lineas_del_ano", jor[0] if jor else None)
            else:
                res[i] = sin_dato("sin_ciclo", "mas_albaranes_que_ciclos_en_la_traza", jor[0] if jor else None)
                diag["hormigon_sin_ciclo"] += 1
    for j in jor:
        j["sobrantes"] = [c for c in (j["ciclos"] or []) if "viaje" not in c]
        diag["hormigon_ciclos_sin_albaran"] += len(j["sobrantes"])
        diag["ciclos_sobrantes"] += len(j["sobrantes"])
        j["min_sobrantes"] = round(sum((c["t1"] - c["t0"]) / 60.0 for c in j["sobrantes"]), 0)
        diag["min_sobrantes"] += j["min_sobrantes"]
    return res


# ---------------------------------------------------------------- LARGO RECORRIDO (nacional, >= LARGA_KM)
def zona_larga(cod, coords, casa):
    """Geocerca de un lugar para LARGO recorrido: (lat, lon, radio_km, fuente). A cientos de km la zona de destino es
    inconfundible, asi que con coordenada de localidad (centro del pueblo) se admite un radio amplio: el almacen puede estar
    a varios km; lo que decide es la PARADA real dentro. 'dudoso' se admite con radio amplio y confianza baja."""
    c = coords.get((casa, cod)) if cod else None
    if not c:
        return None
    f = c["fuente"]
    if f == "gps_aprendida":
        r = min(1.5, max(0.6, 2.0 * (c.get("radio_m") or 150) / 1000.0))
    elif f in ("gesruta", "nominatim_exacto"):
        r = 2.0
    elif f == "nominatim_localidad":
        r = 8.0
    elif f == "dudoso":
        r = 10.0
    else:
        r = 4.0
    return (c["lat"], c["lon"], r, f)


def visitas_zona(pts, ts, zona, t0, t1, min_parada_s=600):
    """Visitas de la traza a una geocerca entre t0 y t1: tramos contiguos de puntos dentro del radio que contienen una PARADA
    real (>= min_parada_s parado). Devuelve [{t_in, t_out, parado_s}] en orden. Pasar por delante por la autovia no cuenta."""
    lat, lon, r, _ = zona
    dlat = r / 111.0
    dlon = r / (111.0 * max(0.2, math.cos(math.radians(lat))))
    i0, i1 = bisect.bisect_left(ts, t0), bisect.bisect_right(ts, t1)
    out, cur, prev = [], None, None
    for k in range(i0, i1):
        q = pts[k]
        dentro = abs(q["lat"] - lat) <= dlat and abs(q["lon"] - lon) <= dlon and v1.hav((q["lat"], q["lon"]), (lat, lon)) <= r
        if dentro:
            if cur is None:
                cur = {"t_in": q["t"], "t_out": q["t"], "parado_s": 0}
            else:
                dtm = q["t"] - prev["t"]
                if q["f"] == "locatel":
                    cur["parado_s"] += int((q.get("parada_min") or 0) * 60)
                elif (q["s"] or 0) <= V_PARADO and dtm <= 900:
                    cur["parado_s"] += dtm
                cur["t_out"] = q["t"]
        elif cur is not None:
            if cur["parado_s"] >= min_parada_s:
                out.append(cur)
            cur = None
        prev = q
    if cur is not None and cur["parado_s"] >= min_parada_s:
        out.append(cur)
    return out


def km_prefijo(pts, tablas=None):
    """Km acumulados punto a punto, para medir km entre dos instantes en O(log n). Manda el CONTADOR CAN (reduccion monotona
    como el ERP: ignora retrocesos pequenos, rebasa un reset o un salto imposible); donde no hay contador, el GPS (mismo
    filtro que v1.km_gps). El GPS se queda corto donde la traza tiene huecos; el contador no."""
    tk = (tablas or {}).get("tabla_km")
    acc, buena, tb = [0.0], None, None
    for k in range(1, len(pts)):
        a, b = pts[k - 1], pts[k]
        paso = None
        v = v1.aplicar_tabla(b.get("kmc"), tk) if b.get("kmc") is not None else None
        if v is not None:
            if buena is None:
                buena, tb = v, b["t"]
            else:
                d = v - buena
                tope = max(5.0, 2.5 * max(1.0, (b["t"] - tb) / 60.0))
                if 0 <= d <= tope:
                    paso = d
                    buena, tb = v, b["t"]
                elif d > tope or -d > tope:
                    buena, tb = v, b["t"]          # reset o salto: se rebasa sin sumar
                    paso = 0.0
                else:
                    paso = 0.0                     # jitter hacia atras
        if paso is None:
            g = v1.hav((a["lat"], a["lon"]), (b["lat"], b["lon"]))
            paso = g if 0.02 <= g <= 20 else 0.0
        acc.append(acc[-1] + paso)
    return acc


def linea_txt(x):
    """NUMERO de lineas.dbf como entero en texto ('247008'), venga como '247008.0', 247008.0 o '247008'."""
    if x is None or x == "":
        return None
    try:
        return str(int(float(x)))
    except (TypeError, ValueError):
        return str(x)


def epoch_dia(d, dias=0):
    x = d + dt.timedelta(days=dias)
    return int(dt.datetime(x.year, x.month, x.day, tzinfo=dt.timezone.utc).timestamp())


def triangular_larga(m, idxs, dem, pts, jornadas, coords, fuente, tablas, acts, drvs, ocupados, diag, zonas_conocidas=None, salida=None, repartos=None):
    """Viajes de largo recorrido de UN camion sobre su traza CONTINUA (cargan una tarde, duermen y descargan a 500 km al dia
    siguiente; o cargan el viernes y salen el domingo). Reglas MEDIDAS en la traza real (6301LYJ, lanzadera Santiago-Meco /
    Illescas-Santiago, marzo 2026):
      - la FECHA del albaran nacional es la de CARGA: la estancia del camion en la zona de ORIGEN (visita con parada) tiene que
        cubrir esa fecha (+-1 dia); la carga termina al SALIR de la zona (L.t_out);
      - la DESCARGA es la primera estancia en la zona de DESTINO tras recorrer entre 0,8 y 1,8 veces la distancia (contador CAN),
        en <= distancia/55 + 18 h y sin huecos de traza > 3 h entre medias;
      - el viaje ACABA al terminar la jornada en que llega (descargar y aparcar), al salir de la zona o al empezar a CARGAR el
        siguiente viaje local (zona de destino amplia), lo que antes ocurra: el camion puede quedarse el dia entero en la base
        de destino y eso ya no es de este viaje;
      - el viaje EMPIEZA al acabar el viaje anterior del camion o, si no se conoce, al salir de la ultima parada >= 20 min en un
        lugar conocido (p. ej. la descarga del viaje anterior en Meco), y nunca antes de la jornada en que llega al origen:
        asi el 'vacio' es el reposicionamiento real (Meco -> Illescas, 70 km) y no se come otro viaje cargado.
    km_vacio = [inicio, llegada al origen]; km_cargado = [salida del origen, llegada al destino]; km = [inicio, fin] (contador);
    duracion_min = HORAS DE TRABAJO (lo que cae dentro de jornadas: sin los descansos > 8 h); min_transcurridos = fin - inicio.
    Dos albaranes del MISMO dia y mismo origen-destino sobre el mismo par fisico = grupaje (se reparte, marcado).
    CONCILIACION con los ciclos LOCALES del mismo camion (la maquina del dia corre antes y estira el primer/ultimo ciclo hasta el
    arranque/fin de la jornada, cuando el camion aun venia de descargar a 500 km): nunca dos viajes sobre el mismo minuto de traza.
    El largo manda (carga y descarga vistas en geocerca, km que cuadran con la distancia); el ciclo local que lo pisa se
      - ABSORBE como grupaje si envuelve al largo con el mismo origen (y sin destino o el mismo): dos albaranes, un viaje fisico;
      - RECORTA al tramo fuera del largo y se vuelve a medir ('recortado_por_viaje_largo_del_camion_*', confianza <= media);
      - DESCUENTA del largo si cae entero dentro (entrega intermedia con su propio ciclo);
      - queda SIN CICLO si lo que le sobra no llega a MIN_MIN_CICLO ('tiempo_del_dia_ocupado_por_viaje_largo_del_camion')."""
    res = {}
    if not pts:
        return res
    ts = [q["t"] for q in pts]
    acc = km_prefijo(pts, tablas)

    def km_entre(a, b):
        i, k = bisect.bisect_left(ts, a), bisect.bisect_right(ts, b) - 1
        return acc[k] - acc[i] if k > i else 0.0

    def hueco_max_h(a, b):
        i, k = bisect.bisect_left(ts, a), bisect.bisect_right(ts, b)
        g = max((ts[x + 1] - ts[x] for x in range(i, min(k, len(ts)) - 1)), default=0)
        return g / 3600.0

    def jornada_de(t):
        return next((j for j in jornadas if j["c0"] <= t <= j["c1"]), None)

    # paradas >= 20 min en LUGARES CONOCIDOS del camion (origenes/destinos de sus albaranes): marcan donde acaba un viaje
    paradas_conocidas = []
    if zonas_conocidas:
        for s in paradas_flujo(pts, None):           # fin de viaje: el camion se queda en el sitio aunque apague (hueco)
            if s["t_out"] - s["t_in"] < 1200:
                continue
            for (la, lo, r) in zonas_conocidas:
                if abs(s["lat"] - la) <= r / 111.0 and v1.hav((s["lat"], s["lon"]), (la, lo)) <= r:
                    paradas_conocidas.append(s)
                    break
    fin_conocidas = [s["t_out"] for s in paradas_conocidas]

    # ciclos locales ya medidos del camion: {t0, t1, i (albaran), tc/tco/td (hitos de carga y descarga)}
    ocup = sorted((x for x in ocupados if x.get("t0") is not None and x.get("t1") is not None), key=lambda x: x["t0"])
    ivs = [(x["t0"], x["t1"]) for x in ocup]

    def recortar_local(x, a, b, tipo):
        """El ciclo local x se queda con [a, b] (fuera del largo) y se vuelve a medir sobre la traza continua."""
        i = x["i"]
        r0 = salida[i] if salida is not None else None
        if r0 is None:
            return
        x["t0"], x["t1"] = a, b
        if b - a < MIN_MIN_CICLO * 60:
            res[i] = sin_dato("sin_ciclo", "tiempo_del_dia_ocupado_por_viaje_largo_del_camion", r0.get("jornada"))
            x["absorbido"] = True
            diag["larga_anula_local"] += 1
            return
        a2, b2 = bisect.bisect_left(ts, a - 3600), bisect.bisect_right(ts, b + 3600)
        pj = {"pts": pts[a2:b2]}
        mr = medir(pj, fuente, a, b, tablas, a, b, acts, drvs)
        tc, tco, td, tdo = x.get("tc"), x.get("tco"), x.get("td"), x.get("tdo")
        if tc is not None and td is not None and a <= tc <= (tco or tc) <= td <= b:
            kv, lv = km_litros(pj["pts"], fuente, tablas, a, tc)
            kc, lc = km_litros(pj["pts"], fuente, tablas, tco or tc, td)
            if tdo is not None and tdo > b:
                tdo = None
        else:
            kv = lv = kc = lc = None
            tc = tco = td = tdo = None
        mr.update({"km_vacio": kv, "km_cargado": kc, "litros_vacio": lv, "litros_cargado": lc,
                   "metodo": r0.get("metodo") or "geo", "confianza": "media" if r0.get("confianza") == "alta" else (r0.get("confianza") or "baja"),
                   "medido": True, "repartido": False, "t_ini": a, "t_fin": b, "jornada": r0.get("jornada"), "orden_ciclo": r0.get("orden_ciclo"),
                   "geo_score": r0.get("geo_score"), "prestada": r0.get("prestada"), "t_carga_in": tc, "t_carga_out": tco, "t_descarga_in": td, "t_descarga_out": tdo,
                   "motivo": "recortado_por_viaje_largo_del_camion_" + tipo + ("; " + r0["motivo"] if r0.get("motivo") else "")})
        mr.setdefault("min_transcurridos", mr.get("duracion_min"))
        res[i] = mr
        diag["larga_recorta_local"] += 1

    asig = []                    # [L, U, o, d, t_ini, t_fin, [idx], conf, dia, vacio_desconocido]
    orden = sorted(idxs, key=lambda i: (dem[i]["dia"], v1.natkey(dem[i]["v"]), v1.natkey(dem[i]["cant"])))
    for i in orden:
        t = dem[i]
        casa = t["c"]
        d0 = dt.date.fromisoformat(t["dia"])
        zo, zd = zona_larga(t["o"], coords, casa), zona_larga(t["d"], coords, casa)
        if not zo or not zd:
            res[i] = sin_dato("sin_ciclo", "larga_sin_coordenada_de_" + ("origen" if not zo else "destino"))
            diag["larga_sin_coordenada"] += 1
            continue
        a_fecha, b_fecha = epoch_dia(d0, -1), epoch_dia(d0, 2)          # la estancia en el origen cubre la fecha +-1 dia
        if b_fecha < ts[0] or a_fecha - 5 * 86400 > ts[-1]:
            res[i] = sin_dato("sin_traza", "sin_traza_en_esas_fechas")
            continue
        vo = [L for L in visitas_zona(pts, ts, zo, a_fecha - 2 * 86400, b_fecha + 2 * 86400) if L["t_out"] >= a_fecha and L["t_in"] <= b_fecha]
        dist = t.get("dist_od") or 0.0
        max_s = (dist / 55.0 + 18.0) * 3600
        mejor, grupo = None, None
        for L in vo:
            vd = visitas_zona(pts, ts, zd, L["t_out"], L["t_out"] + max_s)
            for U in vd:
                if U["t_in"] <= L["t_out"]:
                    continue
                k = km_entre(L["t_out"], U["t_in"])
                if k < 0.8 * dist or k > 1.8 * dist + 40:
                    continue
                if hueco_max_h(L["t_out"], U["t_in"]) > 3:
                    continue
                JU = jornada_de(U["t_in"])
                t_fin = min(U["t_out"], JU["fin"]) if JU else U["t_out"]
                # si el camion ya esta CARGANDO el siguiente viaje local antes de salir de la zona (zona amplia), el largo acaba ahi
                nxt = min((x["tc"] for x in ocup if x.get("tc") and U["t_in"] < x["tc"] < t_fin), default=None)
                if nxt is not None:
                    t_fin = nxt
                g = next((x for x in asig if x[0]["t_out"] == L["t_out"] and x[1]["t_in"] == U["t_in"] and x[2] == t["o"] and x[3] == t["d"] and x[8] == t["dia"]), None)
                if g is None and any(not (t_fin <= x[4] or L["t_out"] >= x[5]) for x in asig):
                    continue
                dep = dt.date.fromisoformat(fecha_de(L["t_out"]))
                off = 0 if a_fecha <= L["t_out"] <= b_fecha and dep >= d0 else abs((dep - d0).days)
                score = (off, U["t_in"] - L["t_out"])
                if mejor is None or score < mejor[0]:
                    mejor, grupo = (score, L, U, t_fin), g
                break                               # la PRIMERA llegada valida al destino tras esta salida
        if mejor is None:
            motivo = "larga_sin_carga_vista" if not vo else "larga_sin_descarga_vista"
            res[i] = sin_dato("sin_ciclo", motivo)
            diag["larga_" + motivo] += 1
            continue
        (off, _), L, U, t_fin = mejor
        if grupo is not None:
            grupo[6].append(i)
            continue
        # inicio: fin del viaje anterior del camion, o fin de la ultima parada en un lugar conocido (fuera del origen), y nunca
        # antes de la jornada en que el camion llega al origen
        J = jornada_de(L["t_in"])
        # viajes del camion que acaban antes de SALIR del origen: el camion puede llegar al origen descargando el viaje anterior
        # (su destino es el origen de este), y este no empieza hasta que aquel acaba
        previos = [x1 for x0, x1 in ivs if x1 <= L["t_out"]] + [x[5] for x in asig if x[5] <= L["t_out"]]
        k = bisect.bisect_right(fin_conocidas, L["t_in"]) - 1
        ult_conocida = None
        while k >= 0:
            s = paradas_conocidas[k]
            if not (abs(s["lat"] - zo[0]) <= zo[2] / 111.0 and v1.hav((s["lat"], s["lon"]), (zo[0], zo[1])) <= zo[2]):
                ult_conocida = s["t_out"]
                break
            k -= 1
        cands = [x for x in ([max(previos)] if previos else []) + ([ult_conocida] if ult_conocida else []) + ([J["ini"]] if J else [])]
        t_ini = max(cands) if cands else L["t_in"]
        if any(x0 < L["t_in"] < x1 for x0, x1 in ivs):
            t_ini = max(t_ini, L["t_in"])
            diag["larga_solapa_ciclo_local"] += 1
        t_ini = min(t_ini, L["t_out"])
        vacio_desconocido = False
        if t_ini < L["t_in"]:
            i0, i1 = bisect.bisect_left(ts, t_ini), bisect.bisect_right(ts, L["t_in"])
            for x in range(i1 - 1, i0, -1):
                if ts[x] - ts[x - 1] > 3 * 3600:
                    t_ini = ts[x]
                    break
            # si la traza ARRANCA con el camion ya en marcha (falta el dia anterior), no se sabe de donde venia: el tramo hasta el
            # origen puede ser otro viaje cargado. No se imputa: vacio desconocido y el viaje empieza al llegar al origen.
            p = bisect.bisect_left(ts, t_ini)
            if p < len(ts) and (p == 0 or ts[p] - ts[p - 1] > 3 * 3600) and es_mov(pts[p]):
                t_ini, vacio_desconocido = L["t_in"], True
                diag["larga_vacio_desconocido"] += 1
        conf = "alta" if off == 0 and zo[3] != "dudoso" and zd[3] != "dudoso" else ("baja" if "dudoso" in (zo[3], zd[3]) or off >= 2 else "media")
        asig.append([L, U, t["o"], t["d"], t_ini, t_fin, [i], conf, t["dia"], vacio_desconocido])
    asig.sort(key=lambda x: x[4])
    for (L, U, o, d, t_ini, t_fin, ids, conf, _dia, vacio_desconocido) in asig:
        # ---- CONCILIACION con los ciclos locales que pisan [t_ini, t_fin] (ver docstring); se clasifica con sus limites ACTUALES,
        # porque un ciclo local ya recortado por otro largo del mismo dia no debe volver a contarse
        restar = []
        for x in ocup:
            if x.get("absorbido") or x["t1"] <= t_ini or x["t0"] >= t_fin:
                continue
            tx = dem[x["i"]]
            if x["t0"] <= L["t_out"] and x["t1"] >= U["t_in"]:
                if tx["o"] == o and (not tx["d"] or tx["d"] == d):
                    ids.append(x["i"])
                    x["absorbido"] = True
                    diag["larga_absorbe_local"] += 1            # 2 albaranes del mismo origen sobre el mismo viaje fisico
                    continue
                p1, p2 = (x["t0"], t_ini), (t_fin, x["t1"])
                a_, b_ = max((p1, p2), key=lambda p: ((km_entre(p[0], p[1]) if p[1] > p[0] else -1.0), p[1] - p[0]))
                tipo = "envuelve"
            elif x["t0"] >= t_ini and x["t1"] <= t_fin:
                restar.append(x)
                diag["larga_local_intermedio"] += 1
                continue
            elif x["t0"] < t_fin < x["t1"]:
                a_, b_, tipo = t_fin, x["t1"], "llegada"
            else:
                a_, b_, tipo = x["t0"], t_ini, "salida"
            recortar_local(x, a_, b_, tipo)
        a, b = bisect.bisect_left(ts, t_ini - 3600), bisect.bisect_right(ts, t_fin + 3600)
        pj = {"pts": pts[a:b]}
        mt = medir(pj, fuente, t_ini, t_fin, tablas, t_ini, t_fin, acts, drvs)
        kv, lv = (None, None) if vacio_desconocido else ((0.0, 0.0) if t_ini >= L["t_in"] else km_litros(pj["pts"], fuente, tablas, t_ini, L["t_in"]))
        kc, lc = km_litros(pj["pts"], fuente, tablas, L["t_out"], U["t_in"])
        trabajo = sum(max(0, min(t_fin, j["fin"]) - max(t_ini, j["ini"])) for j in jornadas if j["fin"] > t_ini and j["ini"] < t_fin) / 60.0
        mt.update({"km_vacio": kv, "km_cargado": kc, "litros_vacio": lv, "litros_cargado": lc,
                   "min_transcurridos": round((t_fin - t_ini) / 60.0, 1), "duracion_min": round(trabajo, 1),
                   "min_espera": round(max(0.0, trabajo - (mt.get("min_conduccion") or 0)), 1),
                   "metodo": "geo", "confianza": conf, "medido": True, "repartido": False, "t_ini": t_ini, "t_fin": t_fin,
                   "jornada": jornada_de(L["t_out"]), "orden_ciclo": None, "geo_score": 2 * MATCH,
                   "t_carga_in": L["t_in"], "t_carga_out": L["t_out"], "t_descarga_in": U["t_in"], "t_descarga_out": min(U["t_out"], t_fin),
                   "motivo": "vacio_desconocido_traza_empieza_en_marcha" if vacio_desconocido else None})
        for x in restar:
            rl_ = salida[x["i"]] if salida is not None else None
            if not rl_:
                continue
            for kk in SUMABLES:
                if mt.get(kk) is not None and rl_.get(kk) is not None:
                    mt[kk] = round(max(0.0, mt[kk] - rl_[kk]), 2)
            mt["motivo"] = "descontado_viaje_local_intermedio" + ("; " + mt["motivo"] if mt.get("motivo") else "")
        # ---- viajes REPARTIDOS del mismo camion (sin hora: reparto de ciclos sobrantes del dia) cuyos tramos pisan el largo: se
        # recortan al tiempo fuera del largo y se reparten de nuevo; si no queda tramo util, sin ciclo. Nada se cuenta dos veces.
        if salida is not None and repartos:
            for xi in repartos:
                r0 = salida[xi]
                if not r0 or not r0.get("tramos"):
                    continue
                nuevos, cambiado = [], False
                for (a_, b_, jj) in r0["tramos"]:
                    if b_ <= t_ini or a_ >= t_fin:
                        nuevos.append((a_, b_, jj))
                        continue
                    cambiado = True
                    if a_ < t_ini:
                        nuevos.append((a_, t_ini, jj))
                    if b_ > t_fin:
                        nuevos.append((t_fin, b_, jj))
                if not cambiado:
                    continue
                nuevos = [(a_, b_, jj) for a_, b_, jj in nuevos if b_ - a_ >= 600]
                if not nuevos:
                    rn = sin_dato("sin_ciclo", "tiempo_del_dia_ocupado_por_viaje_largo_del_camion", r0.get("jornada"))
                    diag["larga_anula_reparto"] += 1
                else:
                    rn = reparto(nuevos, fuente, tablas, acts, drvs, r0.get("k_reparto") or 1, str(r0.get("motivo") or "") + "; recortado_por_viaje_largo_del_camion", nuevos[0][2])
                    diag["larga_recorta_reparto"] += 1
                if r0.get("pendiente_pasada_nacional"):
                    rn["pendiente_pasada_nacional"] = True
                res[xi] = rn
                salida[xi] = rn                        # el siguiente largo del camion ya ve los tramos recortados
        n = len(ids)
        for i in ids:
            r = dict(mt)
            if n > 1:
                for kk in SUMABLES:
                    if r.get(kk) is not None:
                        r[kk] = round(r[kk] / n, 2)
                r.update({"repartido": True, "confianza": "media", "motivo": "grupaje_%d_albaranes_mismo_viaje" % n})
                diag["larga_grupaje"] += 1
            res[i] = r
            diag["larga_medidos"] += 1
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
    ap.add_argument("--bajas", default="", help="bajas_flota_erp.json del ERP (matricula, fecha_baja, motivo): albaran posterior a la baja = matricula mal grabada")
    ap.add_argument("--flota", default="", help="flota_erp.json del ERP (matricula, clase, tacografo_tipo, circula): explica los camiones sin tacografo en la traza")
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
    bajas = {}
    if a.bajas and os.path.isfile(a.bajas):
        try:
            for b_ in json.load(open(a.bajas, encoding="utf-8")).get("bajas") or []:
                if b_.get("matricula") and b_.get("fecha_baja"):
                    bajas[v1.clean(b_["matricula"])] = {"fecha_baja": str(b_["fecha_baja"])[:10], "motivo": b_.get("motivo") or ""}
        except (OSError, ValueError) as e:
            print("Aviso: bajas ilegibles (%s)" % e, file=sys.stderr)
    flota = {}
    if a.flota and os.path.isfile(a.flota):
        try:
            for f_ in json.load(open(a.flota, encoding="utf-8")).get("flota") or []:
                if f_.get("matricula"):
                    flota[v1.clean(f_["matricula"])] = {"clase": f_.get("clase") or "", "tacografo_tipo": f_.get("tacografo_tipo") or "", "circula": f_.get("circula") or ""}
        except (OSError, ValueError) as e:
            print("Aviso: flota ilegible (%s)" % e, file=sys.stderr)

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
    # indice espacial de los lugares conocidos: rotula las paradas de espera de cada viaje con el lugar a < 700 m
    grid_lug = collections.defaultdict(list)
    for (casa_, cod_), c_ in coords.items():
        grid_lug[(int(c_["lat"] * 100), int(c_["lon"] * 100))].append((c_["lat"], c_["lon"], cod_))

    def lugar_cerca(lat, lon):
        gi, gj = int(lat * 100), int(lon * 100)
        mejor = None
        for di in (-1, 0, 1):
            for dj in (-1, 0, 1):
                for (la, lo, cod_) in grid_lug.get((gi + di, gj + dj), ()):
                    d_ = v1.hav((lat, lon), (la, lo))
                    if d_ <= 0.7 and (mejor is None or d_ < mejor[0]):
                        mejor = (d_, cod_)
        return mejor[1] if mejor else None

    flujo, acts, drvs = coser(trazas)
    # unidades que solo conoce LOCATEL (tienen alguna traza suya y ninguna de Wialon): lo que les falta es bajar su historico
    plates_locatel = {mat for (mat, dia), v in trazas.items() if v["fuente"] == "locatel"} - {mat for (mat, dia), v in trazas.items() if v["fuente"] == "wialon"}
    fuente_mat = {}
    for (mat, dia), v in trazas.items():
        fuente_mat.setdefault(mat, collections.Counter())[v["fuente"]] += 1
    par_mat = {mat: paradas_flujo(pts) for mat, pts in flujo.items()}          # paradas de cada camion (tambien para las esperas por viaje)
    par_t = {mat: [p["t_in"] for p in pl] for mat, pl in par_mat.items()}
    jornadas_mat = {mat: jornadas_de(pts, par_mat[mat], rest_s, paradas_flujo(pts, None)) for mat, pts in flujo.items()}
    por_fecha = collections.defaultdict(list)
    for mat, js in jornadas_mat.items():
        for j in js:
            por_fecha[(mat, j["fecha"])].append(j)

    def dist_od(t):
        co, cd = coords.get((t["c"], t["o"])), coords.get((t["c"], t["d"]))
        return v1.hav((co["lat"], co["lon"]), (cd["lat"], cd["lon"])) if co and cd else None
    # camion cuya MAYORIA de cargas es hormigon = hormigonera: TODOS sus dias van por la pasada de hormigon (si no, una linea de
    # porte o de mortero del mismo dia iria por la maquina de aridos y cortaria ciclos sobre la misma jornada: doble conteo)
    n_h, n_t = collections.Counter(), collections.Counter()
    for t in dem:
        n_t[t["mat"]] += 1
        if t.get("horm"):
            n_h[t["mat"]] += 1
    es_hormigonera = {m for m in n_t if m and n_h[m] / n_t[m] >= 0.5}
    por_dia = collections.defaultdict(list)
    horm_dia = collections.defaultdict(list)          # hormigon: su propia pasada (plantas aprendidas), no la maquina de aridos
    for idx, t in enumerate(dem):
        cg = ancla.get((t["c"], t["v"], t["cant"])) or []
        t["tipo"] = cg[0]["tipo"] if cg else ("hormigonera" if t.get("horm") else None)
        t["cargas"] = cg
        d = dist_od(t)
        t["dist_od"] = round(d, 1) if d is not None else None
        # LARGO = por DISTANCIA. «nacional» en GesRuta es el tipo de servicio (portes), no la distancia: hay portes de 30 km
        # que caben en una jornada y van por la maquina de ciclos como los aridos.
        es_h = bool(t.get("horm")) or t["mat"] in es_hormigonera
        t["larga"] = (not es_h) and d is not None and d >= LARGA_KM
        (horm_dia if es_h else por_dia)[(t["mat"], t["dia"])].append(idx)
    # ESPEJOS intercompania: el mismo porte fisico sale en Razo y en Agetrans (Agetrans lo vende y se lo subcontrata a Razo):
    # mismo camion, mismo nº de ticket / carta de porte, mismo dia. Se triangula UNA vez, en la linea de la casa duena del
    # camion (la que lo tiene en su ficha sin proveedor; si no se sabe, Razo); la otra hereda la medida marcada 'espejo_de'
    # para que los totales de grupo no la cuenten dos veces.
    espejo_de = {}
    g_esp = collections.defaultdict(list)
    for i, t in enumerate(dem):
        if t["mat"] and t["cant"]:
            g_esp[(t["mat"], t["cant"], t["dia"])].append(i)
    for ids in g_esp.values():
        if len({dem[i]["c"] for i in ids}) < 2:
            continue
        dueno = next((dem[i].get("dueno") for i in ids if dem[i].get("dueno")), None)
        prim = next((i for i in ids if dem[i]["c"] == dueno), None)
        if prim is None:
            prim = next((i for i in ids if dem[i]["c"] == "Razo"), ids[0])
        for i in ids:
            if dem[i]["c"] != dem[prim]["c"]:
                espejo_de[i] = prim
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
                    salida[i] = sin_dato("sin_traza", "sin_traza_en_esas_fechas_locatel" if m in plates_locatel else "sin_traza_en_esas_fechas")
                continue
        dprev = (dt.date.fromisoformat(d) - dt.timedelta(days=1)).isoformat()
        # el ciclo pertenece al dia de su CARGA (el albaran se hace al cargar), no al de su inicio (que puede ser la vuelta de ayer)
        prestados = [(c, j) for j in por_fecha.get((m, dprev), []) if j["nocturna"] and fecha_de(j["fin"]) == d
                     for c in j["sobrantes"] if fecha_de((c.get("carga") or {}).get("t_in", c["t0"])) == d]
        for j in jor:
            if j["horas"] > MAX_JORNADA_H:
                diag["jornadas_largas"] += 1
        i_rep = [i for i in idxs if any(c.get("repetida") for c in dem[i]["cargas"])]
        # los ESPEJOS no compiten por ciclos (heredan la medida de su linea principal) y los LARGOS van por su propia pasada
        i_larga = [i for i in idxs if i not in i_rep and i not in espejo_de and dem[i]["larga"]]
        i_arid = [i for i in idxs if i not in i_rep and i not in espejo_de and not dem[i]["larga"]]
        res = {}
        for i in i_rep:
            res[i] = sin_dato("cantera_repetida", "mismo_numero_de_cantera_en_varias_lineas_del_ano", jor[0] if jor else None)
        if i_arid:
            dnext = (dt.date.fromisoformat(d) + dt.timedelta(days=1)).isoformat()
            sig = [dem[i] for i in por_dia.get((m, dnext), []) if not dem[i]["larga"] and i not in espejo_de]
            r = triangular_dia([dem[i] for i in i_arid], jor, prestados, fuente, coords, sens.get(m), acts.get(m, []), drvs.get(m, []), diag, viajes_sig=sig)
            res.update(dict(zip(i_arid, r)))
        for i, r in res.items():
            salida[i] = r
        if a.diag:
            dias_diag.append({"matricula": m, "fecha": d, "viajes": len(idxs), "larga": len(i_larga), "repetidas": len(i_rep), "prestados": len(prestados),
                              "espejos": sum(1 for i in idxs if i in espejo_de),
                              "jornadas": [{"ini": iso_min(j["ini"]), "fin": iso_min(j["fin"]), "horas": j["horas"], "nocturna": j["nocturna"],
                                            "paradas": len(j["paradas"]), "modo": j["modo"], "ciclos": len(j["ciclos"] or []),
                                            "asignados": j["asignados"], "sobrantes": len(j["sobrantes"]), "min_sobrantes": j.get("min_sobrantes", 0)} for j in jor],
                              "medidos": sum(1 for i in idxs if (salida[i] or {}).get("medido"))})

    # ---- HORMIGON POR VIAJE (Roberto: hormigon tambien por viaje, todo por GPS): plantas APRENDIDAS de la traza (el maestro las
    # tiene mal: PREBETONG CORUÑA apunta a la cantera a 40 km, PLANTA DE SABON al centro de Arteixo), ciclos por planta (una
    # jornada puede cargar en dos plantas), obra = parada mas larga fuera de plantas, asignacion por planta y orden de GesRuta.
    dem_h = [dem[i] for idxs in horm_dia.values() for i in idxs]
    plantas = aprender_plantas(dem_h, jornadas_mat) if dem_h else {}
    for key, pl in plantas.items():
        coords[key] = {"lat": pl["lat"], "lon": pl["lon"], "fuente": "planta_aprendida", "radio_m": pl["radio_m"], "nombre": (ref.get(key) or {}).get("nombre")}
    diag["hormigon_plantas_aprendidas"] = len(plantas)
    for (m, d) in sorted(horm_dia, key=lambda k: (k[1], k[0])):
        idxs = horm_dia[(m, d)]
        idxs.sort(key=lambda i: (v1.natkey(dem[i]["v"]), v1.natkey(dem[i]["cant"])))
        fuente = (fuente_mat.get(m) or collections.Counter()).most_common(1)
        fuente = fuente[0][0] if fuente else None
        if m not in flujo:
            ajeno = any(dem[i].get("propio") is False for i in idxs)
            motivo = "sin_matricula" if not m else ("pendiente_bajada" if m in plates else ("camion_ajeno" if ajeno else "sin_telemetria_o_pendiente_locatel"))
            for i in idxs:
                salida[i] = sin_dato("sin_traza", motivo)
            continue
        jor = por_fecha.get((m, d), [])
        if not jor:
            d_ = dt.date.fromisoformat(d)
            motivo = "sin_jornada_ese_dia" if any((m, (d_ + dt.timedelta(days=k)).isoformat()) in trazas for k in range(-VENTANA_DIAS, VENTANA_DIAS + 1)) else ("sin_traza_en_esas_fechas_locatel" if m in plates_locatel else "sin_traza_en_esas_fechas")
            for i in idxs:
                salida[i] = sin_dato("sin_traza", motivo)
            continue
        i_rep = [i for i in idxs if any(c.get("repetida") for c in dem[i]["cargas"])]
        for i in i_rep:
            dem[i]["_repetida"] = True                # ocupa su turno en el orden (es una carga real) pero no se mide
        i_h = [i for i in idxs if i not in espejo_de]
        if i_h:
            r = triangular_hormigon([dem[i] for i in i_h], jor, plantas, coords, fuente, sens.get(m), acts.get(m, []), drvs.get(m, []), diag)
            for i, x in zip(i_h, r):
                salida[i] = x
        if a.diag:
            dias_diag.append({"matricula": m, "fecha": d, "viajes": len(idxs), "larga": 0, "repetidas": len(i_rep), "prestados": 0, "hormigon": True,
                              "espejos": sum(1 for i in idxs if i in espejo_de),
                              "jornadas": [{"ini": iso_min(j["ini"]), "fin": iso_min(j["fin"]), "horas": j["horas"], "nocturna": j["nocturna"],
                                            "paradas": len(j["paradas"]), "modo": j["modo"], "ciclos": len(j["ciclos"] or []),
                                            "asignados": j["asignados"], "sobrantes": len(j["sobrantes"]), "min_sobrantes": j.get("min_sobrantes", 0)} for j in jor],
                              "medidos": sum(1 for i in idxs if (salida[i] or {}).get("medido"))})

    # ---- SEGUNDA PASADA por camion: albaranes que agrupan VARIOS DIAS. GesRuta no guarda la fecha por ticket (la linea no
    # tiene fecha ni vehiculo; el albaran lleva FECHA/FECHAACORD y puede agrupar entregas de una semana), asi que un ticket
    # sin ciclo en "su" dia se busca en los ciclos SOBRANTES del mismo camion en los dias cercanos, por origen y en orden de
    # nº de ticket (los numeros de cantera son cronologicos). La fecha real pasa a ser la de la traza. Marcado y visible.
    recuperados = 0
    for m in flujo:
        idx_sc = [i for i in range(len(dem)) if dem[i]["mat"] == m and salida[i] and salida[i]["metodo"] == "sin_ciclo" and not dem[i]["larga"] and i not in espejo_de]
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

    # ---- PASADA DE LARGO RECORRIDO (>= LARGA_KM) sobre la traza CONTINUA de cada camion (los viajes cruzan descansos y dias)
    ocupados = collections.defaultdict(list)          # ciclos locales ya medidos: intervalo, albaran e hitos (para conciliar)
    for i, r in enumerate(salida):
        if r and r.get("medido") and r.get("t_ini") is not None and r.get("t_fin") is not None:
            ocupados[dem[i]["mat"]].append({"t0": r["t_ini"], "t1": r["t_fin"], "i": i, "tc": r.get("t_carga_in"), "tco": r.get("t_carga_out"),
                                            "td": r.get("t_descarga_in"), "tdo": r.get("t_descarga_out")})
    larga_mat = collections.defaultdict(list)
    for i, t in enumerate(dem):
        if salida[i] is None and t["larga"] and i not in espejo_de:
            larga_mat[t["mat"]].append(i)
    zonas_mat = collections.defaultdict(set)          # lugares conocidos de cada camion (origenes y destinos de sus albaranes)
    for t in dem:
        if t["mat"] in larga_mat:
            for cod in (t["o"], t["d"]):
                z = zona_larga(cod, coords, t["c"])
                if z:
                    zonas_mat[t["mat"]].add((round(z[0], 4), round(z[1], 4), z[2]))
    rep_mat = collections.defaultdict(list)           # viajes REPARTIDOS del dia (sin hora): sus tramos se recortan si un largo los pisa
    for i, r in enumerate(salida):
        if r and r.get("repartido") and r.get("tramos") and i not in espejo_de:
            rep_mat[dem[i]["mat"]].append(i)
    for m, ids in larga_mat.items():
        if m not in flujo:
            continue
        fuente_m = ((fuente_mat.get(m) or collections.Counter()).most_common(1) or [("wialon", 0)])[0][0]
        rl = triangular_larga(m, ids, dem, flujo[m], jornadas_mat.get(m, []), coords, fuente_m, sens.get(m), acts.get(m, []), drvs.get(m, []), ocupados[m], diag,
                              zonas_conocidas=sorted(zonas_mat[m]), salida=salida, repartos=rep_mat[m])
        for i, r in rl.items():
            salida[i] = r

    # ---- LARGOS SIN CASAR: reparto del dia sobre el tiempo LIBRE del camion (sus jornadas de esa fecha menos lo ya medido),
    # marcado baja/repartido y pendiente_pasada_nacional, como antes de esta pasada: nada empeora para quien ya lo consumia.
    # Se casaran cuando la traza del camion este completa en dias seguidos (el dia de la vuelta tambien).
    ocup2 = collections.defaultdict(list)
    for i, r in enumerate(salida):
        if r and r.get("medido") and r.get("t_ini") is not None and r.get("t_fin") is not None:
            ocup2[dem[i]["mat"]].append((r["t_ini"], r["t_fin"]))
    pend_larga = collections.defaultdict(list)
    for i, r in enumerate(salida):
        if r and r.get("metodo") == "sin_ciclo" and str(r.get("motivo") or "").startswith("larga_") and i not in espejo_de:
            pend_larga[(dem[i]["mat"], dem[i]["dia"])].append(i)
    for (m, d), ids in pend_larga.items():
        oc = sorted(ocup2[m])
        tramos = []
        for j in por_fecha.get((m, d), []):
            a_, b_ = j["ini"], j["fin"]
            for x0, x1 in oc:
                if x1 <= a_ or x0 >= b_:
                    continue
                if x0 > a_:
                    tramos.append((a_, x0, j))
                a_ = max(a_, x1)
            if b_ > a_:
                tramos.append((a_, b_, j))
        tramos = [(a_, b_, j) for a_, b_, j in tramos if b_ - a_ >= 600]
        if not tramos or sum(b_ - a_ for a_, b_, _ in tramos) < 1800:
            continue                                   # sin tiempo libre ese dia: se queda sin dato (sin_ciclo)
        fuente_m = ((fuente_mat.get(m) or collections.Counter()).most_common(1) or [("wialon", 0)])[0][0]
        motivo_orig = collections.Counter(salida[i]["motivo"] for i in ids).most_common(1)[0][0]
        rp = reparto(tramos, fuente_m, sens.get(m), acts.get(m, []), drvs.get(m, []), len(ids), "larga_sin_casar_reparto_del_dia (" + motivo_orig + ")", tramos[0][2])
        for i in ids:
            x = dict(rp)
            x["pendiente_pasada_nacional"] = True
            salida[i] = x
            diag["larga_reparto_del_dia"] += 1

    # ---- ESPEJOS: heredan la medida de su linea principal, marcados (el ERP y los totales de grupo la saltan)
    for i, p in espejo_de.items():
        r = dict(salida[p]) if salida[p] else sin_dato("sin_ciclo", "espejo_sin_linea_principal")
        cp = dem[p]["cargas"]
        r["espejo_de"] = {"empresa": dem[p]["c"], "viaje": dem[p]["v"], "cantera": dem[p]["cant"],
                          "linea": linea_txt(cp[0]["linea"]) if len(cp) == 1 else None}
        if r.get("medido") or r.get("km") is not None:
            r["motivo"] = "espejo_intercompania" + ("; " + r["motivo"] if r.get("motivo") else "")
        salida[i] = r
        diag["espejos"] += 1
    for i in range(len(dem)):
        if salida[i] is None:
            salida[i] = sin_dato("sin_ciclo", "sin_procesar")
            diag["sin_procesar"] += 1

    for k_, v_ in horm_dia.items():                  # el hormigon vuelve al conteo por dia (viajes_dia, orden_dia)
        por_dia[k_].extend(v_)
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
        # una tarjeta puede estar enlazada a VARIOS codigos (la misma persona con dos fichas, o un codigo por casa): coincide si el
        # codigo del albaran es uno de los suyos; como chofer_tacografo se muestra ese y, si no, el primero de su casa
        eqc = lambda a_, b_: str(a_).lstrip("0") == str(b_).lstrip("0")  # noqa: E731
        cods_lk = [str(e.get("codigo_gesruta")).strip() for e in lk if isinstance(e, dict) and e.get("codigo_gesruta")]
        cods_casa = [str(e.get("codigo_gesruta")).strip() for e in lk if isinstance(e, dict) and e.get("casa") == t["c"] and e.get("codigo_gesruta")]
        cand = cods_casa or cods_lk
        chofer_taco = next((c_ for c_ in cand if chofer_ges and eqc(c_, chofer_ges)), None) or (cand[0] if cand else None)
        # paradas y esperas del viaje (>= 5 min) sobre las paradas del flujo del camion: carga / descarga (por los hitos) o
        # espera; lugar = origen/destino del viaje si es su carga/descarga, si no el lugar conocido mas cercano (< 700 m)
        par_v = []
        if medido and r.get("t_ini") is not None and r.get("t_fin") is not None and t["mat"] in par_mat:
            pl_, pt_ = par_mat[t["mat"]], par_t[t["mat"]]
            tc_, tco_, td_, tdo_ = r.get("t_carga_in"), r.get("t_carga_out"), r.get("t_descarga_in"), r.get("t_descarga_out")
            for p_ in pl_[bisect.bisect_left(pt_, r["t_ini"] - 60):]:
                if p_["t_in"] > r["t_fin"]:
                    break
                a_, b_ = max(p_["t_in"], r["t_ini"]), min(p_["t_out"], r["t_fin"])   # solo la parte de la parada DENTRO del viaje
                if b_ - a_ < 300:
                    continue
                if tc_ is not None and p_["t_in"] <= (tco_ or tc_) and p_["t_out"] >= tc_:
                    rol_, lug_ = "carga", rotulo_en_lugar(p_, t["o"], coords, t["c"], lugar_cerca)
                elif td_ is not None and p_["t_in"] <= (tdo_ or td_) + 60 and p_["t_out"] >= td_:
                    rol_, lug_ = "descarga", rotulo_en_lugar(p_, t["d"], coords, t["c"], lugar_cerca)
                else:
                    rol_, lug_ = "espera", lugar_cerca(p_["lat"], p_["lon"])
                par_v.append({"t": iso_min(a_), "min": int((b_ - a_) // 60), "lugar": lug_, "rol": rol_})
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
            "min_disponible": r.get("min_disponible"), "min_descanso": r.get("min_descanso"), "min_sin_dato": r.get("min_sin_dato"),
            "min_fuente": r.get("min_fuente"), "min_coherente": r.get("min_coherente"), "motivo_min": r.get("motivo_min"),
            "min_transcurridos": r.get("min_transcurridos"),
            "km_cargado": r.get("km_cargado"), "km_vacio": r.get("km_vacio"), "litros_cargado": r.get("litros_cargado"), "litros_vacio": r.get("litros_vacio"),
            "conductor_hash": ch, "chofer_tacografo": chofer_taco, "chofer_gesruta": chofer_ges,
            "chofer_coincide": (None if not (chofer_taco and chofer_ges) else any(eqc(c_, chofer_ges) for c_ in cods_lk)),
            "t_carga": iso_min(r.get("t_carga_in")), "t_carga_fin": iso_min(r.get("t_carga_out")),
            "t_descarga": iso_min(r.get("t_descarga_in")), "t_descarga_fin": iso_min(r.get("t_descarga_out")),
            "viajes_dia": len(por_dia[(t["mat"], t["dia"])]),
            "albara": cargas[0]["albara"] if len(cargas) == 1 else None, "linea": linea_txt(cargas[0]["linea"]) if len(cargas) == 1 else None,
            "cliente": cargas[0]["cliente"] if cargas else None, "n_cargas_clave": len(cargas) if cargas else None,
            "espejo_de": r.get("espejo_de"),
            "km_facturado": t.get("km_fact"), "unidad_facturada": t.get("unidad"), "nacional": bool(t.get("nac")), "sin_cantera": bool(t.get("sin_cantera")),
            "pendiente_pasada_nacional": bool(r.get("pendiente_pasada_nacional")),
            "paradas": par_v, "obra": r.get("obra"), "matricula_de_baja": (bajas.get(t["mat"]) or {}).get("fecha_baja"),
            "coord_origen": co["fuente"] if co else None, "coord_destino": cd["fuente"] if cd else None,
            "coord_revisar": ((t["c"], t["o"]) in discrepantes) or ((t["c"], t["d"]) in discrepantes)})
    for (m, d), idxs in por_dia.items():
        for pos, i in enumerate(idxs):
            viajes_out[i]["orden_dia"] = pos + 1

    tot = len(viajes_out)
    met = collections.Counter(x["metodo"] for x in viajes_out)
    arid = [x for x in viajes_out if not x["larga_distancia"] and x["tipo"] != "hormigonera"]
    horm = [x for x in viajes_out if x["tipo"] == "hormigonera"]
    horm_c = [x for x in horm if x["metodo"] != "sin_traza" and not x["espejo_de"]]
    larg = [x for x in viajes_out if x["larga_distancia"]]
    nmed = sum(1 for x in viajes_out if x["medido"])
    larg_c = [x for x in larg if x["metodo"] != "sin_traza" and not x["espejo_de"]]
    resumen = {"viajes": tot, "aridos": len(arid),
               "larga_distancia": {"total": len(larg), "con_traza": len(larg_c), "medidos": sum(1 for x in larg_c if x["medido"]),
                                   "pct_medidos_con_traza": round(100.0 * sum(1 for x in larg_c if x["medido"]) / max(1, len(larg_c)), 1),
                                   "sin_ciclo_por_motivo": dict(collections.Counter(x["motivo"] for x in larg_c if x["metodo"] == "sin_ciclo")),
                                   "grupaje": diag["larga_grupaje"], "solapa_ciclo_local": diag["larga_solapa_ciclo_local"],
                                   "reparto_del_dia_sin_casar": diag["larga_reparto_del_dia"], "vacio_desconocido": diag["larga_vacio_desconocido"],
                                   "conciliacion_con_ciclos_locales": {"absorbidos_como_grupaje": diag["larga_absorbe_local"], "recortados": diag["larga_recorta_local"],
                                                                        "anulados_sin_tiempo": diag["larga_anula_local"], "intermedios_descontados": diag["larga_local_intermedio"],
                                                                        "repartos_recortados": diag["larga_recorta_reparto"], "repartos_anulados": diag["larga_anula_reparto"]},
                                   "km_cargado": round(sum(x["km_cargado"] or 0 for x in larg_c if x["medido"]), 0),
                                   "km_vacio": round(sum(x["km_vacio"] or 0 for x in larg_c if x["medido"]), 0)},
               "hormigon": {"albaranes": len(horm), "con_traza": len(horm_c), "medidos": sum(1 for x in horm_c if x["medido"]),
                            "pct_medidos_con_traza": round(100.0 * sum(1 for x in horm_c if x["medido"]) / max(1, len(horm_c)), 1),
                            "sin_ciclo": sum(1 for x in horm_c if x["metodo"] == "sin_ciclo"), "con_obra": sum(1 for x in horm_c if x.get("obra")),
                            "ciclos_sin_albaran": diag["hormigon_ciclos_sin_albaran"], "ancla_hora_carga": diag["hormigon_ancla_hora_carga"],
                            "dias_por_hub": diag["hormigon_dias_por_hub"], "confianza": dict(collections.Counter(x["confianza"] for x in horm_c if x["medido"])),
                            "plantas_aprendidas": {"%s|%s" % k: {"lat": round(v["lat"], 5), "lon": round(v["lon"], 5), "dias": v["dias"], "visitas": v["visitas"], "nombre": (ref.get(k) or {}).get("nombre")} for k, v in sorted(plantas.items())}},
               "espejos_intercompania": diag["espejos"], "sin_procesar": diag["sin_procesar"],
               "tacografo_descartado": dict(collections.Counter(x["motivo_min"] for x in viajes_out if x["min_coherente"] is False)),
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
            "tacografo": "min_conduccion/otros/disponible/descanso = actividad de la RANURA 1 del tacografo que viene en la traza, sobre la ventana t_ini..t_fin; solo se usa (min_fuente=tacografo, min_coherente=true) si hay tarjeta en la ranura 1 al menos la mitad del viaje y la conduccion registrada cubre al menos la mitad del movimiento de la traza; si no, min_coherente=false con motivo_min (sin_tarjeta_en_ranura_1 | tacografo_no_refleja_la_conduccion) y la conduccion sale del movimiento (min_fuente=traza). conductor_hash = tarjeta (hash) de la ranura 1; chofer_tacografo = su codigo GesRuta si esta enlazado",
            "minutos": "con min_fuente=tacografo: conduccion + otros + disponible + descanso + sin_dato = min_transcurridos (t_fin - t_ini). duracion_min = HORAS DE TRABAJO (= min_transcurridos en aridos; en largo recorrido, sin los descansos > rest_h entre jornadas). min_espera = duracion_min - conduccion (trabajo sin conducir): es el COMPLEMENTO, no una categoria mas; no se suma al desglose",
            "cargado_vacio": "km_vacio = del inicio del viaje a llegar a cargar; km_cargado = de salir de la carga a llegar a la descarga (contador CAN); null si no se ven las dos visitas",
            "larga_distancia": "origen-destino >= 200 km (por DISTANCIA; 'nacional' es el tipo de servicio, no la distancia). Se casan sobre la traza CONTINUA del camion (cruzan descansos y dias): la fecha del albaran es la de CARGA; carga = estancia con parada en la zona de origen que cubre esa fecha (+-1 dia); descarga = primera estancia con parada en la de destino tras recorrer 0,8-1,8 veces la distancia (contador CAN), en <= dist/55 + 18 h y sin huecos de traza > 3 h. Inicio = fin del viaje anterior del camion / ultima parada >= 20 min en un lugar conocido / inicio de la jornada en que llega al origen (lo mas tarde); fin = fin de la jornada en que llega, salida de la zona o inicio de la carga del siguiente viaje local (lo primero). Conciliacion con los ciclos locales del mismo camion: el largo manda; el local que lo pisa se absorbe como grupaje (mismo origen), se recorta y se vuelve a medir (motivo recortado_por_viaje_largo_del_camion_*), se descuenta si cae dentro, o queda sin_ciclo. Grupaje = repartido. pendiente_pasada_nacional = largo sin casar repartido por el dia (se casara cuando la traza este completa)",
            "espejos": "el mismo porte en Razo y en Agetrans (mismo camion, mismo ticket, mismo dia): se mide una vez en la casa duena del camion y la otra linea lo hereda con espejo_de = {empresa, viaje, cantera, linea} de la principal; los totales de grupo deben saltar las filas con espejo_de",
            "linea": "linea = NUMERO de lineas.dbf del sistema anterior como entero en texto; (empresa, linea) es unico",
            "hitos": "t_carga = llegada a cargar, t_carga_fin = salida cargado, t_descarga = llegada a descargar, t_descarga_fin = salida de la descarga (hora de Madrid; null si no se ve la visita); minutos de carga/descarga = diferencias. En largo recorrido son las estancias en las zonas de origen y destino",
            "chofer": "chofer_coincide = el codigo de chofer del albaran (GesRuta) es uno de los enlazados a la tarjeta de la ranura 1 (una tarjeta puede tener varios codigos: dos fichas de la misma persona o un codigo por casa); chofer_tacografo = el codigo enlazado que coincide o, si no, el primero de su casa",
            "paradas": "paradas = [{t (hora de Madrid), min, lugar, rol}]: paradas >= 5 min del camion dentro de [t_ini, t_fin] (una parada se corta con 30 min sin posicion o un salto de mas de 350 m); rol = carga | descarga (por los hitos t_carga/t_descarga; lugar = origen/destino del viaje SOLO si la parada cae en su radio, si no el lugar conocido a < 700 m o null) | espera (tiempo parado fuera de la carga y la descarga; lugar = codigo del lugar conocido a < 700 m o null)",
            "hormigon": "tipo hormigonera: ciclos por PLANTAS APRENDIDAS de la traza (grupo de paradas mas visitado en los dias de un solo origen; el maestro/geocode no valen), de la llegada a la planta a la llegada a la siguiente; obra = parada mas larga fuera de plantas (campo obra {lat, lon, min}); asignacion por planta en orden de GesRuta (cronologico dentro de cada planta), hora_carga impresa como ancla dura si viene en la carga; ciclos sin albaran = cargas que GesRuta no tiene (resumen.hormigon.ciclos_sin_albaran); km_vacio = ida a cargar + vuelta de la obra",
            "litros": "crudo = reduccion monotona del contador; calibrados = tabla del sensor (ERP) + reduccion monotona"}
    # ---- HALLAZGOS: lo que el cruce descubre y sirve para ACTUAR (pestaña Hallazgos del informe). Todo medido, nada estimado.
    hall = {}

    def fuente_de_m(m):
        return ((fuente_mat.get(m) or collections.Counter()).most_common(1) or [("wialon", 0)])[0][0]
    csa = []
    # no son "cargas sin albaran": los largos sin casar (su ciclo espera a la traza contigua) ni los dias con cantera repetida
    # (el albaran existe, es su numero el que esta mal); tampoco ciclos de mas de 150 km (largo recorrido)
    dias_fuera = {(x["matricula"], x["fecha_gesruta"]) for x in viajes_out if x["pendiente_pasada_nacional"] or x["metodo"] == "cantera_repetida"}
    for m, js in jornadas_mat.items():
        for j in js:
            for c in (j.get("sobrantes") or []):
                if c["t1"] - c["t0"] < 600 or (m, fecha_de(c["t0"])) in dias_fuera:
                    continue
                mm = v1.medir({"fuente": fuente_de_m(m), "pts": j["pts"]}, c["t0"], c["t1"], sens.get(m), c["t0"], c["t1"])
                if (mm.get("km") or 0) < KM_MIN_CICLO or (mm.get("km") or 0) > 150:
                    continue
                ob = c.get("obra") or c.get("descarga") or {}
                pl = c.get("planta")
                csa.append({"matricula": m, "fecha": fecha_de(c["t0"]), "t_ini": iso_min(c["t0"]), "t_fin": iso_min(c["t1"]), "min": int((c["t1"] - c["t0"]) // 60),
                            "km": mm.get("km"), "origen": c.get("o") or (pl[1] if pl else None),
                            "destino": c.get("d") or (lugar_cerca(ob["lat"], ob["lon"]) if ob.get("lat") is not None else None),
                            "min_obra": int((ob["t_out"] - ob["t_in"]) // 60) if ob.get("t_in") is not None and ob.get("t_out") is not None else None,
                            "tipo": "hormigonera" if m in es_hormigonera else "aridos/nacional"})
    hall["cargas_sin_albaran"] = sorted(csa, key=lambda x: (x["fecha"], x["matricula"], x["t_ini"]))
    hall["albaranes_sin_ciclo"] = [{"empresa": x["empresa"], "viaje": x["viaje"], "cantera": x["cantera"], "matricula": x["matricula"], "fecha": x["fecha_gesruta"],
                                    "origen": x["origen"], "destino": x["destino"], "cliente": x["cliente"], "tipo": x["tipo"], "motivo": x["motivo"]}
                                   for x in viajes_out if x["metodo"] == "sin_ciclo" and not x["espejo_de"]]
    rep = collections.defaultdict(list)
    for x in viajes_out:
        if x["metodo"] == "cantera_repetida" and not x["espejo_de"]:
            rep[(x["empresa"], x["origen"], x["cantera"], x["fecha_gesruta"][:4])].append(x)
    hall["canteras_repetidas"] = [{"empresa": k[0], "origen": k[1], "cantera": k[2], "anio": k[3], "lineas": len(v_), "viajes": sorted({x["viaje"] for x in v_}),
                                   "matriculas": sorted({x["matricula"] for x in v_ if x["matricula"]}), "fechas": sorted({x["fecha_gesruta"] for x in v_}),
                                   "clientes": sorted({x["cliente"] or "" for x in v_})} for k, v_ in sorted(rep.items())]
    tac = collections.defaultdict(collections.Counter)
    for x in viajes_out:
        if x["medido"] and not x["espejo_de"] and x["matricula"]:
            tac[x["matricula"]]["viajes_medidos"] += 1
            if x["min_coherente"] is False:
                tac[x["matricula"]][x["motivo_min"] or "descartado"] += 1
            elif x["min_fuente"] == "tacografo":
                tac[x["matricula"]]["con_tacografo"] += 1
    hall["tacografo_por_camion"] = [{"matricula": m, "viajes_medidos": c_["viajes_medidos"], "con_tacografo": c_["con_tacografo"],
                                     "sin_tarjeta_en_ranura_1": c_["sin_tarjeta_en_ranura_1"], "tacografo_no_refleja_la_conduccion": c_["tacografo_no_refleja_la_conduccion"],
                                     "pct_descartado": round(100.0 * (c_["sin_tarjeta_en_ranura_1"] + c_["tacografo_no_refleja_la_conduccion"]) / c_["viajes_medidos"], 1),
                                     "tacografo_tipo": (flota.get(m) or {}).get("tacografo_tipo") or "", "clase": (flota.get(m) or {}).get("clase") or ""}
                                    for m, c_ in sorted(tac.items(), key=lambda kv: -(kv[1]["sin_tarjeta_en_ranura_1"] + kv[1]["tacografo_no_refleja_la_conduccion"])) if c_["viajes_medidos"] >= 10]
    cho = collections.defaultdict(lambda: {"n": 0, "matriculas": set(), "desde": None, "hasta": None})
    for x in viajes_out:
        if x["chofer_coincide"] is False and not x["espejo_de"]:
            e = cho[(x["empresa"], x["chofer_tacografo"], x["chofer_gesruta"])]
            e["n"] += 1; e["matriculas"].add(x["matricula"])
            e["desde"] = min(e["desde"] or x["fecha_gesruta"], x["fecha_gesruta"]); e["hasta"] = max(e["hasta"] or x["fecha_gesruta"], x["fecha_gesruta"])
    hall["chofer_discrepante"] = [{"empresa": k[0], "chofer_tacografo": k[1], "chofer_gesruta": k[2], "viajes": e["n"], "matriculas": sorted(e["matriculas"]), "desde": e["desde"], "hasta": e["hasta"]}
                                  for k, e in sorted(cho.items(), key=lambda kv: -kv[1]["n"])]
    coh = collections.defaultdict(collections.Counter)
    for x in viajes_out:
        if x["metodo"] != "sin_traza" and not x["espejo_de"] and not x["larga_distancia"] and x["tipo"] != "nacional" and x["matricula"]:
            c_ = coh[x["matricula"]]; c_["viajes"] += 1; c_["tipo_" + (x["tipo"] or "?")] += 1
            if x["medido"] and x["metodo"] == "geo" and x["confianza"] in ("alta", "media") and not (x["motivo"] or "").startswith("ciclo_de_otra_planta"):
                c_["ok"] += 1
            if x["metodo"] == "sin_ciclo":
                c_["sin_ciclo"] += 1
            if (x["motivo"] or "").startswith("ciclo_de_otra_planta"):
                c_["otra_planta"] += 1
    hall["coherencia_por_unidad"] = [{"matricula": m, "tipo": max((k_[5:] for k_ in c_ if k_.startswith("tipo_")), key=lambda k_: c_["tipo_" + k_]),
                                      "viajes_con_traza": c_["viajes"], "pct_geografia_albaran": round(100.0 * c_["ok"] / c_["viajes"], 1),
                                      "sin_ciclo": c_["sin_ciclo"], "otra_planta": c_["otra_planta"], "clase": (flota.get(m) or {}).get("clase") or ""}
                                     for m, c_ in sorted(coh.items(), key=lambda kv: kv[1]["ok"] / kv[1]["viajes"]) if c_["viajes"] >= 30]
    # Roberto (23/09): una magnitud que resume muchos viajes es un ABANICO: media Y mediana, p90 y desviacion tipica, no un dato unico.
    def _est(xs):
        v = sorted(xs); n_ = len(v)
        if not n_:
            return None, None, None
        med = v[n_ // 2] if n_ % 2 else (v[n_ // 2 - 1] + v[n_ // 2]) / 2.0
        p90 = v[min(n_ - 1, int(round(0.9 * (n_ - 1))))]
        mu = sum(v) / n_; sd = (sum((z - mu) ** 2 for z in v) / (n_ - 1)) ** 0.5 if n_ > 1 else 0.0
        return round(med, 1), round(p90, 1), round(sd, 1)
    par_l = collections.defaultdict(lambda: {"n": 0, "min": 0, "mats": set(), "l": []})
    for x in viajes_out:
        if x["espejo_de"]:
            continue
        for p in (x.get("paradas") or []):
            e = par_l[(p["rol"], p["lugar"] or "")]; e["n"] += 1; e["min"] += p["min"] or 0; e["mats"].add(x["matricula"]); e["l"].append(p["min"] or 0)
    def _row_par(k, e):
        med, p90, sd = _est(e["l"])
        return {"rol": k[0], "lugar": k[1] or None, "paradas": e["n"], "minutos": e["min"], "media_min": round(e["min"] / e["n"], 1),
                "mediana_min": med, "p90_min": p90, "desv_min": sd, "camiones": len(e["mats"])}
    hall["paradas_por_lugar"] = [_row_par(k, e) for k, e in sorted(par_l.items(), key=lambda kv: -kv[1]["min"]) if e["n"] >= 5][:200]
    esp_c = collections.defaultdict(lambda: {"n": 0, "esp": 0.0, "cond": 0.0, "le": [], "lc": []})
    for x in viajes_out:
        if x["medido"] and not x["espejo_de"] and x["cliente"] and x["min_espera"] is not None:
            e = esp_c[x["cliente"]]; e["n"] += 1; e["esp"] += x["min_espera"] or 0; e["cond"] += x["min_conduccion"] or 0
            e["le"].append(x["min_espera"] or 0); e["lc"].append(x["min_conduccion"] or 0)
    def _row_esp(c_, e):
        med, p90, sd = _est(e["le"]); medc, _p, _s = _est(e["lc"])
        return {"cliente": c_, "viajes_medidos": e["n"], "min_espera_total": round(e["esp"]), "min_espera_medio": round(e["esp"] / e["n"], 1),
                "min_espera_mediana": med, "min_espera_p90": p90, "min_espera_desv": sd,
                "min_conduccion_medio": round(e["cond"] / e["n"], 1), "min_conduccion_mediana": medc}
    hall["espera_por_cliente"] = [_row_esp(c_, e) for c_, e in sorted(esp_c.items(), key=lambda kv: -kv[1]["esp"]) if e["n"] >= 10]
    st = collections.defaultdict(lambda: {"n": 0, "casas": set(), "motivo": None, "desde": None, "hasta": None})
    for x in viajes_out:
        if x["metodo"] == "sin_traza" and x["motivo"] in ("camion_ajeno", "sin_telemetria_o_pendiente_locatel", "pendiente_bajada", "sin_matricula", "sin_traza_en_esas_fechas_locatel"):
            e = st[x["matricula"] or "(sin matricula)"]; e["n"] += 1; e["casas"].add(x["empresa"]); e["motivo"] = x["motivo"]
            e["desde"] = min(e["desde"] or x["fecha_gesruta"], x["fecha_gesruta"]); e["hasta"] = max(e["hasta"] or x["fecha_gesruta"], x["fecha_gesruta"])
    hall["sin_localizador"] = [{"matricula": m, "viajes": e["n"], "motivo": e["motivo"], "empresas": sorted(e["casas"]), "desde": e["desde"], "hasta": e["hasta"]}
                               for m, e in sorted(st.items(), key=lambda kv: -kv[1]["n"])]
    hall["fecha_corregida"] = [{"empresa": x["empresa"], "viaje": x["viaje"], "cantera": x["cantera"], "matricula": x["matricula"], "fecha_gesruta": x["fecha_gesruta"], "fecha_real": x["fecha"]}
                               for x in viajes_out if x["medido"] and x["fecha"] != x["fecha_gesruta"] and not x["espejo_de"]]
    lp = collections.Counter(x["matricula"] for x in viajes_out if x["pendiente_pasada_nacional"] and not x["espejo_de"])
    hall["largos_pendientes_de_traza"] = [{"matricula": m, "viajes": n_} for m, n_ in lp.most_common()]

    def tras_baja(x):
        b_ = bajas.get(x["matricula"] or "")
        if not b_:
            return False
        margen = 60 if "no consta" in (b_.get("motivo") or "").lower() else 7   # fecha estimada (ultimo trabajo del ERP) vs exacta
        return x["fecha_gesruta"] > (dt.date.fromisoformat(b_["fecha_baja"]) + dt.timedelta(days=margen)).isoformat()
    hall["albaranes_matricula_baja"] = [{"empresa": x["empresa"], "viaje": x["viaje"], "cantera": x["cantera"], "matricula": x["matricula"], "fecha": x["fecha_gesruta"],
                                         "fecha_baja": bajas[x["matricula"]]["fecha_baja"], "motivo_baja": bajas[x["matricula"]]["motivo"], "cliente": x["cliente"],
                                         "origen": x["origen"], "destino": x["destino"]} for x in viajes_out if not x["espejo_de"] and tras_baja(x)]
    hall["plantas_aprendidas"] = resumen["hormigon"]["plantas_aprendidas"]
    hall["resumen"] = {"cargas_sin_albaran": len(hall["cargas_sin_albaran"]), "albaranes_sin_ciclo": len(hall["albaranes_sin_ciclo"]), "canteras_repetidas": len(hall["canteras_repetidas"]),
                       "camiones_tacografo_descartado": sum(1 for r_ in hall["tacografo_por_camion"] if r_["pct_descartado"] >= 50),
                       "chofer_discrepante_viajes": sum(r_["viajes"] for r_ in hall["chofer_discrepante"]),
                       "unidades_incoherentes": sum(1 for r_ in hall["coherencia_por_unidad"] if r_["pct_geografia_albaran"] < 60),
                       "sin_localizador_viajes": sum(r_["viajes"] for r_ in hall["sin_localizador"]), "fecha_corregida": len(hall["fecha_corregida"]),
                       "largos_pendientes": sum(lp.values()), "plantas_aprendidas": len(hall["plantas_aprendidas"]),
                       "albaranes_matricula_baja": len(hall["albaranes_matricula_baja"]), "bajas_conocidas": len(bajas)}
    meta["hallazgos"] = ("cargas_sin_albaran = ciclos reales del camion (>= 10 min y >= 1 km) sin albaran ese dia (posibles cargas sin facturar o grabadas otro dia); "
                         "albaranes_sin_ciclo = albaranes que la traza no explica; canteras_repetidas = mismo nº de cantera en varias lineas (empresa, origen, año); "
                         "tacografo_por_camion = viajes medidos cuyo tacografo se descarto (localizador que no lo lee); chofer_discrepante = tarjeta con codigo distinto al del albaran; "
                         "coherencia_por_unidad = % de viajes cortos cuyo ciclo se corta por la geografia del albaran (< 60 % = revisar el localizador); "
                         "paradas_por_lugar = paradas >= 5 min por lo que hacia y lugar (codigo); espera_por_cliente = minutos parado por viaje medido; "
                         "sin_localizador = camiones con albaranes y sin traza; fecha_corregida = ticket con fecha real distinta a la del albaran; largos_pendientes = largos sin traza contigua; albaranes_matricula_baja = albaranes fechados mas de 7 dias despues de la baja de la matricula en el ERP (bajas_flota_erp.json): matricula mal grabada, el viaje lo hizo otro camion")
    json.dump({"meta": meta, "resumen": resumen, "hallazgos": hall, "viajes": viajes_out}, open(a.salida, "w", encoding="utf-8"), ensure_ascii=False)
    if a.diag:
        json.dump({"meta": meta, "resumen": resumen, "dias": dias_diag}, open(a.diag, "w", encoding="utf-8"), ensure_ascii=False)
    print(json.dumps(resumen, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
