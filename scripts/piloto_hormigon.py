# -*- coding: utf-8 -*-
"""PRUEBA PILOTO: hormigon POR VIAJE desde la traza GPS (Roberto: «analiza la ultima semana de agosto, todo por GPS, 2026 y 2025»).
Ciclo = planta -> obra -> planta. Planta = geocerca (coordenada conocida o aprendida); la obra NO suele tener coordenada en
GesRuta: se localiza como la PARADA MAS LARGA fuera de la planta dentro del ciclo. Regla de Roberto: en hormigon nunca se
carga hoy y se descarga manana (salvo nocturno cruzando la medianoche, que el corte por descanso ya respeta).
Reutiliza triangular_v2 (jornadas, visitas por geocerca, maquina carga->descarga, asignacion por orden, medicion + tacografo).
Entrada: el ancla de tarifas (tipo=hormigonera) para los albaranes; las trazas de historicos\wialon_hist.
Salida: JSON con el esquema del v2 (para ver_dia_mapa.py --todos) + resumen por ano/hormigonera/dia + tabla de texto."""
import argparse, collections, datetime as dt, gzip, json, os, sys
D = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, D)
import triangular_v2 as t2  # noqa: E402
v1 = t2.v1


def cargas_hormigon(ruta, desde, hasta):
    opener = gzip.open if ruta.endswith(".gz") else open
    with opener(ruta, "rt", encoding="utf-8") as f:
        cargas = json.load(f).get("cargas") or []
    out = []
    for x in cargas:
        if x.get("tipo") != "hormigonera" or x.get("naturaleza") not in (None, "viaje"):
            continue
        fecha = str(x.get("fecha") or "")[:10]
        if not (desde <= fecha <= hasta):
            continue
        out.append({"c": v1.casa_norm(x.get("empresa")), "v": str(x.get("viaje")), "cant": str(x.get("cantera") or x.get("albara") or ""),
                    "albara": x.get("albara"), "linea": x.get("linea"), "mat": v1.clean(x.get("matricula")), "dia": fecha,
                    "o": (x.get("origen") or "").strip(), "d": (x.get("destino") or "").strip(), "cliente": x.get("cliente"),
                    "m3": x.get("cantidad"), "chofer": x.get("chofer")})
    return out


def obra_del_ciclo(j, c, planta):
    """La parada mas larga fuera de la planta dentro del ciclo = la obra (con su tiempo en obra)."""
    mejor = None
    for s in j["paradas"]:
        if s["t_out"] <= c["t0"] or s["t_in"] >= c["t1"]:
            continue
        if planta and v1.hav((s["lat"], s["lon"]), (planta["lat"], planta["lon"])) <= 0.6:
            continue
        dur = s["t_out"] - s["t_in"]
        if mejor is None or dur > mejor[0]:
            mejor = (dur, s)
    return mejor


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ancla", required=True); ap.add_argument("--wialon", action="append", default=[])
    ap.add_argument("--geocode", default=""); ap.add_argument("--aprendidas", default="", help="coords_aprendidas_por_casa_v1.json")
    ap.add_argument("--sensores", default=""); ap.add_argument("--conductores", default="")
    ap.add_argument("--semanas", default="2026-08-24:2026-08-31,2025-08-24:2025-08-31")
    ap.add_argument("--salida", required=True); ap.add_argument("--rest-h", type=float, default=8.0); ap.add_argument("--dwell-min", type=float, default=3.0)
    a = ap.parse_args()
    t2.DWELL_S = int(a.dwell_min * 60); v1.DWELL_S = t2.DWELL_S
    rest_s = int(a.rest_h * 3600)
    semanas = [tuple(s.split(":")) for s in a.semanas.split(",")]
    dem = []
    for d0, d1 in semanas:
        dem.extend(cargas_hormigon(a.ancla, d0, d1))
    sens = json.load(open(a.sensores, encoding="utf-8")) if a.sensores and os.path.isfile(a.sensores) else {}
    enlace = json.load(open(a.conductores, encoding="utf-8")) if a.conductores and os.path.isfile(a.conductores) else {}
    # coordenadas: GesRuta + geocode + aprendidas (la planta suele estar aprendida por las paradas de las hormigoneras)
    ges = v1.coords_gesruta()
    geo = {}
    if a.geocode and os.path.isfile(a.geocode):
        for k, x in json.load(open(a.geocode, encoding="utf-8")).items():
            if isinstance(x, dict) and x.get("lat") is not None:
                casa, _, cod = k.partition("|")
                geo[(v1.casa_norm(casa), cod.strip())] = {"lat": float(x["lat"]), "lon": float(x["lon"]), "fuente": v1.fuente_de(x)}
    apr = {}
    if a.aprendidas and os.path.isfile(a.aprendidas):
        for k, x in json.load(open(a.aprendidas, encoding="utf-8")).items():
            casa, _, cod = k.partition("|")
            apr[(v1.casa_norm(casa), cod.strip())] = {"lat": x["lat"], "lon": x["lon"], "fuente": "gps_aprendida", "radio_m": x.get("radio_m")}
    coords = v1.mejor(ges, geo, apr)
    # trazas de las hormigoneras en las semanas (+-1 dia)
    mats = {t["mat"] for t in dem if t["mat"]}
    dias = set()
    for d0, d1 in semanas:
        a0, a1 = dt.date.fromisoformat(d0) - dt.timedelta(days=1), dt.date.fromisoformat(d1) + dt.timedelta(days=1)
        for k in range((a1 - a0).days + 1):
            dias.add((a0 + dt.timedelta(days=k)).isoformat())
    trazas = {k: v for k, v in t2.cargar_trazas([("wialon", d) for d in a.wialon]).items() if k[0] in mats and k[1] in dias}
    flujo, acts, drvs = t2.coser(trazas)
    jornadas_mat = {m: t2.jornadas_de(pts, t2.paradas_flujo(pts), rest_s) for m, pts in flujo.items()}
    por_dia = collections.defaultdict(list)
    for i, t in enumerate(dem):
        por_dia[(t["mat"], t["dia"])].append(i)
    salida = [None] * len(dem)
    filas_dia = []
    for (m, d) in sorted(por_dia):
        idxs = sorted(por_dia[(m, d)], key=lambda i: (v1.natkey(dem[i]["v"]), v1.natkey(dem[i]["albara"]), v1.natkey(dem[i]["linea"])))
        viajes = [dem[i] for i in idxs]
        jor = [j for j in jornadas_mat.get(m, []) if j["fecha"] == d]
        if m not in flujo or not jor:
            motivo = "sin_traza" if m not in flujo else "sin_jornada_ese_dia"
            for i in idxs:
                salida[i] = t2.sin_dato("sin_traza", motivo)
            filas_dia.append({"mat": m, "dia": d, "albaranes": len(idxs), "ciclos": 0, "casados": 0, "nota": motivo})
            continue
        casa = viajes[0]["c"]
        res = [None] * len(viajes)
        pend = list(range(len(viajes)))
        ciclos_total = 0
        for j in jor:
            cic = t2.ciclos_geo(j, viajes, coords, casa, "wialon", sens.get(m))
            modo = "geo"
            if not cic:
                hub, hm = t2.elegir_hub(t2.sitios_jornada(j, {c for t in viajes for c in (t["o"], t["d"]) if c}, coords, casa), viajes)
                cic = t2.particionar_hub(j, hub, hm, "wialon", sens.get(m), acts.get(m, []), drvs.get(m, []))
                modo = "hub_" + (hm or "unico")
            j["ciclos"], j["modo"] = cic, modo
            ciclos_total += len(cic)
            pend, libres = t2.asignar_geo(viajes, pend, cic, j, "wialon", sens.get(m), acts.get(m, []), drvs.get(m, []), res)
            pend, libres = t2.asignar_dp(viajes, pend, cic, libres, j, "wialon", sens.get(m), acts.get(m, []), drvs.get(m, []), res, coords, casa)
            j["sobrantes"] = [cic[k] for k in libres]
            # obra de cada ciclo (parada mas larga fuera de la planta)
            planta = coords.get((casa, viajes[0]["o"]))
            for c in cic:
                ob = obra_del_ciclo(j, c, planta)
                c["obra"] = {"lat": round(ob[1]["lat"], 5), "lon": round(ob[1]["lon"], 5), "min": round(ob[0] / 60.0, 0), "t_in": t2.iso_min(ob[1]["t_in"])} if ob else None
        for k in pend:
            res[k] = t2.sin_dato("sin_ciclo", "mas_albaranes_que_ciclos_en_la_traza", jor[0])
        for i, r in zip(idxs, res):
            salida[i] = r
        filas_dia.append({"mat": m, "dia": d, "albaranes": len(idxs), "ciclos": ciclos_total, "casados": sum(1 for r in res if r.get("medido")),
                          "sobrantes": sum(len(j["sobrantes"]) for j in jor), "jornada": "%s→%s %.1fh %s" % (t2.iso_min(jor[0]["ini"])[11:], t2.iso_min(jor[-1]["fin"])[11:], sum(j["horas"] for j in jor), jor[0]["modo"])})
    # salida con el esquema del v2 (para los mapas) + obra
    out = []
    for t, r in zip(dem, salida):
        j = r.get("jornada")
        c = None
        if r.get("medido") and j and j.get("ciclos"):
            c = next((x for x in j["ciclos"] if x["t0"] == r["t_ini"]), None)
        ch = r.get("conductor_hash")
        lk = enlace.get(ch) or []
        chofer_t = next((str(e.get("codigo_gesruta")) for e in (lk if isinstance(lk, list) else [lk]) if isinstance(e, dict) and e.get("casa") == t["c"]), None)
        out.append({"empresa": t["c"], "viaje": t["v"], "cantera": t["cant"], "albara": t["albara"], "linea": t["linea"], "matricula": t["mat"],
                    "fecha": t2.fecha_de(r["t_ini"]) if r.get("t_ini") else t["dia"], "fecha_gesruta": t["dia"], "origen": t["o"], "destino": t["d"],
                    "cliente": t["cliente"], "m3": t["m3"], "tipo": "hormigonera",
                    "km": r.get("km"), "duracion_min": r.get("duracion_min"), "litros": r.get("litros"), "litros_calibrados": r.get("litros_calibrados"),
                    "metodo": r.get("metodo"), "medido": bool(r.get("medido")), "confianza": r.get("confianza"), "motivo": r.get("motivo"),
                    "t_ini": t2.iso_min(r.get("t_ini")), "t_fin": t2.iso_min(r.get("t_fin")), "orden_dia": None, "ciclo": r.get("orden_ciclo"),
                    "min_conduccion": r.get("min_conduccion"), "min_espera": r.get("min_espera"), "min_otros": r.get("min_otros"), "min_fuente": r.get("min_fuente"),
                    "chofer_tacografo": chofer_t, "chofer_gesruta": (t.get("chofer") or "").strip() or None,
                    "obra": (c or {}).get("obra"), "jornada_nocturna": bool(j and j.get("nocturna")), "jornada_prestada": False,
                    "larga_distancia": False, "dist_od_km": None, "coord_origen": (coords.get((t["c"], t["o"])) or {}).get("fuente"),
                    "coord_destino": (coords.get((t["c"], t["d"])) or {}).get("fuente")})
    for (m, d), idxs in por_dia.items():
        for pos, i in enumerate(sorted(idxs, key=lambda i: (v1.natkey(dem[i]["v"]), v1.natkey(dem[i]["albara"]), v1.natkey(dem[i]["linea"])))):
            out[i]["orden_dia"] = pos + 1
    # resumen por ano
    res_anos = {}
    for d0, d1 in semanas:
        sel = [x for x in out if d0 <= x["fecha_gesruta"] <= d1]
        med = [x for x in sel if x["medido"]]
        kms = sorted(x["km"] for x in med if x["km"] is not None); dur = sorted(x["duracion_min"] for x in med if x["duracion_min"])
        res_anos[d0[:4]] = {"albaranes": len(sel), "hormigoneras": len({x["matricula"] for x in sel}),
                            "con_traza": sum(1 for x in sel if x["metodo"] != "sin_traza"), "medidos": len(med),
                            "pct_medidos_con_traza": round(100.0 * len(med) / max(1, sum(1 for x in sel if x["metodo"] != "sin_traza")), 1),
                            "sin_ciclo": sum(1 for x in sel if x["metodo"] == "sin_ciclo"), "sin_traza": sum(1 for x in sel if x["metodo"] == "sin_traza"),
                            "con_obra_localizada": sum(1 for x in med if x.get("obra")),
                            "km_p50": kms[len(kms) // 2] if kms else None, "dur_p50": dur[len(dur) // 2] if dur else None,
                            "chofer_coincide": sum(1 for x in med if x["chofer_tacografo"] and x["chofer_gesruta"] and x["chofer_tacografo"].lstrip("0") == x["chofer_gesruta"].lstrip("0")),
                            "con_chofer": sum(1 for x in med if x["chofer_tacografo"] and x["chofer_gesruta"])}
    json.dump({"meta": {"que": "piloto hormigon por viaje (planta=hub, obra=parada larga fuera)", "semanas": semanas, "generado": dt.datetime.now().strftime("%Y-%m-%dT%H:%M")},
               "resumen": res_anos, "dias": filas_dia, "viajes": out}, open(a.salida, "w", encoding="utf-8"), ensure_ascii=False)
    print(json.dumps(res_anos, ensure_ascii=False, indent=1))
    print("== por hormigonera y dia (albaranes / ciclos / casados / sobrantes) ==")
    for f in filas_dia:
        print(" %s %s  alb %2d  cic %2s  casados %2s  sobr %s  %s" % (f["mat"], f["dia"], f["albaranes"], f.get("ciclos", "-"), f.get("casados", "-"), f.get("sobrantes", "-"), f.get("jornada") or f.get("nota")))


if __name__ == "__main__":
    main()
