# -*- coding: utf-8 -*-
"""Horas REALES de trabajo de las hormigoneras, por (matricula, mes), MEDIDAS desde la TRAZA GPS de Wialon.

Correccion de Roberto (22/09/2026): las horas NO salen del canal de tacografo (tco_activity) porque no todas las
hormigoneras meten la tarjeta; salen del HISTORICO DE POSICIONES (lat/lon/velocidad/tiempo), que SI dejan todas.
Mismo criterio que la triangulacion de aridos (ver triangular_v1.py: jornada()+paradas()+internas()), agregado por
(vehiculo, dia) y sumado a mes:
  - CONDUCCION      = tiempo con velocidad > V_MOVIL, dentro de la jornada del dia.
  - OTROS TRABAJOS  = paradas CORTAS dentro de la jornada (< --umbral-larga-min; carga/descarga/espera): cuentan.
  - DESCANSO        = paradas LARGAS dentro de la jornada (>= --umbral-larga-min) + todo lo de fuera de la jornada:
                       NO cuentan.
  trabajo_dia_min = (fin_jornada - inicio_jornada) - suma(paradas largas internas)

REUTILIZA (no reinventa) la sesion Wialon de descargar_movertis_historico_v1.py (login/logout/llamar/unidades/
mensajes_dia/ventana/zona_casa) y el algoritmo de triangular_v1.py (jornada/paradas/internas/km_gps). SOLO LECTURA.
UNA SOLA SESION: login una vez, trabajo poco a poco con pausa entre peticiones, core/logout SIEMPRE en finally. Si
el login no da sesion, aborta (no se reintenta en bucle). NADA programado. Privacidad: solo se leen t/lat/lon/
velocidad de cada mensaje; nunca se tocan campos de conductor/tarjeta/DNI (ni se importa esa parte del modulo).

Fetch por (vehiculo, MES) -- no por dia -- para no disparar el numero de peticiones (28 veh. x ~9 meses = ~250, en
vez de 28 x ~265 dias = ~7500). Los mensajes de cada mes se parten LOCALMENTE por dia natural (Europe/Madrid) antes
de aplicar jornada/paradas/internas, asi que el resultado por dia es identico a pedirlo dia a dia (una parada nocturna
o de fin de semana, aunque cruce la medianoche, siempre queda FUERA de la jornada de cualquiera de los dos dias que
toca, porque la jornada se define por el primer/ultimo punto en movimiento de ESE dia).

No se inventa nada (mismo principio que descargar_movertis_historico_v1.py): si un (matricula, mes) no trae NINGUN
mensaje de Wialon, no se escribe esa clave en la salida (ausencia = sin dato), en vez de escribir un cero.

Salida:  cache/horas_hormigon_v1.json   {"MATRICULA|YYYY-MM": minutos_trabajo}
Bonus:   cache/km_hormigon_v1.json      {"MATRICULA|YYYY-MM": km_gps}            (si --con-km, activado por defecto)
Detalle: scripts/_horas_hormigon_estado/_resumen.jsonl  (una linea por vehiculo+mes, con el desglose y por dia)
"""
import argparse, collections, datetime, json, os, sys, time

_SCRIPTS = os.path.dirname(os.path.abspath(__file__))
_CACHE = os.path.normpath(os.path.join(_SCRIPTS, "..", "cache"))  # <root>\cache, junto al resto de caches del localizador
sys.path.insert(0, _SCRIPTS)  # importa las dependencias (sesion Wialon + triangulacion) del mismo scripts\
import descargar_movertis_historico_v1 as dm  # noqa: E402  (login/logout/llamar/unidades/mensajes_dia/ventana)
import triangular_v1 as tri  # noqa: E402  (jornada/paradas/internas/km_gps -- mismo criterio que la triangulacion)

MATRICULAS_HORMIGON = [
    "0987FXD", "3337JNC", "1533NFJ", "2516KSN", "7720HGK", "6578FSP", "0063NBM", "2504MCL",
    "4696FYN", "7047MSF", "8942MGT", "2864FNK", "6234FCX", "6864DLY", "1245CRJ", "0065NBM",
    "1895CNR", "8716KBD", "7371MJL", "8977GBY", "9470KCX", "0972FWN", "6081FHD", "8803NKR",
    "1865NNH", "5690NPW", "8026KDV", "1868NNH",
]


def meses_entre(desde, hasta):
    """'2026-01'..'2026-09' -> [(2026,1),...,(2026,9)]"""
    y0, m0 = (int(x) for x in desde.split("-"))
    y1, m1 = (int(x) for x in hasta.split("-"))
    out = []
    y, m = y0, m0
    while (y, m) <= (y1, m1):
        out.append((y, m))
        m += 1
        if m > 12:
            m = 1
            y += 1
    return out


def ventana_mes(anio, mes, zona, hoy=None):
    d0 = datetime.date(anio, mes, 1)
    d1 = (datetime.date(anio, 12, 31) if mes == 12 else datetime.date(anio, mes + 1, 1) - datetime.timedelta(days=1))
    if hoy and d1 > hoy:
        d1 = hoy
    if d1 < d0:
        return None
    t0, _ = dm.ventana(d0, zona)
    _, t1 = dm.ventana(d1, zona)
    return t0, t1


def puntos_de(msgs):
    """Mensajes Wialon crudos -> puntos {t,lat,lon,s} ordenados por tiempo; descarta posiciones invalidas. Nunca
    toca el diccionario 'p' (ahi viven los campos de conductor/tarjeta/tacografo): solo 't' y 'pos'."""
    pts = []
    for m in msgs:
        t = dm._num(m.get("t"))
        if not t or t <= 0:
            continue
        pos = m.get("pos") if isinstance(m.get("pos"), dict) else m
        lat, lon, s = dm._num(pos.get("y")), dm._num(pos.get("x")), dm._num(pos.get("s"))
        if lat is None or lon is None or not (-90 <= lat <= 90) or not (-180 <= lon <= 180) or (lat == 0 and lon == 0):
            continue
        pts.append({"t": int(t), "lat": lat, "lon": lon, "s": max(0.0, s) if s is not None else 0.0})
    pts.sort(key=lambda x: x["t"])
    return pts


def partir_por_dia(pts, zona):
    out = collections.defaultdict(list)
    for p in pts:
        d = datetime.datetime.fromtimestamp(p["t"], tz=datetime.timezone.utc).astimezone(zona).date()
        out[d.isoformat()].append(p)
    return out


def horas_dia(pts_dia, umbral_larga_s):
    """(trabajo,conduccion,otros,descanso_largo interno) de UN dia, con jornada/paradas/internas de triangular_v1."""
    j0, j1 = tri.jornada(pts_dia)
    if j0 is None or j1 is None or j1 <= j0:
        return {"trabajo_min": 0.0, "conduccion_min": 0.0, "otros_min": 0.0, "descanso_largo_min": 0.0,
                "puntos": len(pts_dia)}
    ps = tri.paradas(pts_dia, "wialon")
    inn = tri.internas(ps, j0, j1)
    span_min = (j1 - j0) / 60.0
    larga = sum((p["t_out"] - p["t_in"]) / 60.0 for p in inn if (p["t_out"] - p["t_in"]) >= umbral_larga_s)
    corta = sum((p["t_out"] - p["t_in"]) / 60.0 for p in inn if (p["t_out"] - p["t_in"]) < umbral_larga_s)
    trabajo = max(0.0, span_min - larga)
    conduccion = max(0.0, trabajo - corta)
    return {"trabajo_min": trabajo, "conduccion_min": conduccion, "otros_min": corta, "descanso_largo_min": larga,
            "puntos": len(pts_dia)}


def procesar_mes(sid, u, anio, mes, zona, hoy, umbral_larga_s, con_km):
    win = ventana_mes(anio, mes, zona, hoy)
    if not win:
        return None
    t0, t1 = win
    msgs = dm.mensajes_dia(sid, u["id"], t0, t1)  # generica: sirve para cualquier ventana, no solo un dia
    pts = puntos_de(msgs)
    por_dia = partir_por_dia(pts, zona)
    trabajo = conduccion = otros = descanso = km = 0.0
    dias_con_movimiento = 0
    dias_detalle = {}
    for dia, pts_dia in sorted(por_dia.items()):
        pts_dia.sort(key=lambda x: x["t"])
        r = horas_dia(pts_dia, umbral_larga_s)
        if r["trabajo_min"] > 0:
            dias_con_movimiento += 1
        trabajo += r["trabajo_min"]; conduccion += r["conduccion_min"]
        otros += r["otros_min"]; descanso += r["descanso_largo_min"]
        if con_km and r["trabajo_min"] > 0:
            km += tri.km_gps(pts_dia)
        dias_detalle[dia] = {"trabajo_min": round(r["trabajo_min"]), "puntos": r["puntos"]}
    return {"mensajes": len(msgs), "puntos": len(pts), "dias_con_puntos": len(por_dia),
            "dias_con_movimiento": dias_con_movimiento, "trabajo_min": round(trabajo, 1),
            "conduccion_min": round(conduccion, 1), "otros_min": round(otros, 1),
            "descanso_largo_min": round(descanso, 1), "km_gps": round(km, 1) if con_km else None,
            "dias_detalle": dias_detalle}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--desde", default="2026-01")
    ap.add_argument("--hasta", default="", help="YYYY-MM; vacio = mes actual")
    ap.add_argument("--solo", default="", help="matriculas separadas por coma para limitar (pruebas)")
    ap.add_argument("--umbral-larga-min", type=int, default=60, dest="umbral_larga_min")
    ap.add_argument("--pausa", type=float, default=5.0)
    ap.add_argument("--con-km", action="store_true", default=True, dest="con_km")
    ap.add_argument("--sin-km", action="store_false", dest="con_km")
    ap.add_argument("--max-fallos", type=int, default=6, dest="max_fallos")
    ap.add_argument("--estado-dir", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "_horas_hormigon_estado"))
    ap.add_argument("--salida", default=os.path.join(_CACHE, "horas_hormigon_v1.json"))
    ap.add_argument("--salida-km", default=os.path.join(_CACHE, "km_hormigon_v1.json"), dest="salida_km")
    a = ap.parse_args()

    token = os.environ.get("WIALON_TOKEN") or ""
    if not token:
        print("ERROR: falta WIALON_TOKEN en el entorno (no se teclea).", file=sys.stderr)
        return 2

    zona = dm.zona_casa()
    hoy = datetime.datetime.now(datetime.timezone.utc).astimezone(zona).date()
    hasta = a.hasta or ("%04d-%02d" % (hoy.year, hoy.month))
    umbral_s = a.umbral_larga_min * 60
    os.makedirs(a.estado_dir, exist_ok=True)

    objetivo = [dm.clean_plate(p) for p in (a.solo.split(",") if a.solo else MATRICULAS_HORMIGON) if p.strip()]

    ckpt_path = os.path.join(a.estado_dir, "_checkpoint.json")
    done = set()
    if os.path.isfile(ckpt_path):
        try:
            done = set(json.load(open(ckpt_path, encoding="utf-8")))
        except Exception:  # noqa: BLE001
            done = set()
    resumen_path = os.path.join(a.estado_dir, "_resumen.jsonl")
    acumulado, acumulado_km = {}, {}
    if os.path.isfile(resumen_path):
        for linea in open(resumen_path, encoding="utf-8"):
            try:
                x = json.loads(linea)
            except ValueError:
                continue
            if x.get("estado") == "ok" and x.get("mensajes", 0) > 0:
                k = "%s|%04d-%02d" % (x["mat"], x["anio"], x["mes"])
                acumulado[k] = x["trabajo_min"]
                if x.get("km_gps") is not None:
                    acumulado_km[k] = x["km_gps"]

    sid = None
    no_encontradas, encontradas = [], {}
    hechos = fallidos = saltados = 0
    parado = False
    pares = []
    try:
        sid, cuenta = dm.entrar(token)
        items = dm.unidades(sid)
        porplaca = {}
        for u in items:
            p = dm.clean_plate(u.get("nm", ""))
            if p:
                porplaca[p] = u
        encontradas = {p: porplaca[p] for p in objetivo if p in porplaca}
        no_encontradas = [p for p in objetivo if p not in porplaca]

        meses = meses_entre(a.desde, hasta)
        pares = [(p, y, m) for p in objetivo if p in encontradas for (y, m) in meses]
        jsonl = open(resumen_path, "a", encoding="utf-8")
        consec = 0
        for (p, y, m) in pares:
            kkey = "%s|%04d-%02d" % (p, y, m)
            if kkey in done:
                saltados += 1
                continue
            u = encontradas[p]
            ok = False
            for intento in range(1, 4):
                try:
                    r = procesar_mes(sid, u, y, m, zona, hoy, umbral_s, a.con_km)
                    fila = {"mat": p, "anio": y, "mes": m, "estado": "ok", **(r or {"mensajes": 0, "trabajo_min": 0.0})}
                    jsonl.write(json.dumps(fila, ensure_ascii=False) + "\n"); jsonl.flush()
                    if r and r.get("mensajes", 0) > 0:
                        acumulado[kkey] = r["trabajo_min"]
                        if a.con_km and r.get("km_gps") is not None:
                            acumulado_km[kkey] = r["km_gps"]
                    print("[%s] %s %04d-%02d -> msgs=%s trabajo_min=%s km=%s" % (
                        datetime.datetime.now().strftime("%H:%M:%S"), p, y, m,
                        (r or {}).get("mensajes"), (r or {}).get("trabajo_min"), (r or {}).get("km_gps")),
                        file=sys.stderr)
                    hechos += 1; consec = 0; ok = True
                    break
                except Exception as e:  # noqa: BLE001
                    print("  aviso intento %d %s|%04d-%02d: %s" % (intento, p, y, m, e), file=sys.stderr)
                    if intento == 2:  # 2 fallos seguidos: puede que la sesion haya caido, reentrar UNA vez
                        try:
                            dm.salir(sid); sid, _ = dm.entrar(token)
                        except Exception:  # noqa: BLE001
                            pass
                    if intento < 3:
                        time.sleep(5 * intento)
            if not ok:
                fallidos += 1; consec += 1
                jsonl.write(json.dumps({"mat": p, "anio": y, "mes": m, "estado": "fallo"}, ensure_ascii=False) + "\n"); jsonl.flush()
                if consec >= a.max_fallos:
                    parado = True
                    break
            done.add(kkey)
            dm.guardar_json(ckpt_path, sorted(done))
            if (hechos + fallidos) % 5 == 0:
                dm.guardar_json(a.salida, {k: round(v) for k, v in acumulado.items()})
                if a.con_km:
                    dm.guardar_json(a.salida_km, {k: v for k, v in acumulado_km.items() if v is not None})
            time.sleep(a.pausa)
        jsonl.close()
        dm.guardar_json(a.salida, {k: round(v) for k, v in acumulado.items()})
        if a.con_km:
            dm.guardar_json(a.salida_km, {k: v for k, v in acumulado_km.items() if v is not None})

        salida_final = {k: round(v) for k, v in acumulado.items()}
        resumen = {
            "unidades_wialon_total": len(items), "objetivo": len(objetivo),
            "encontradas": sorted(encontradas.keys()), "no_encontradas": sorted(no_encontradas),
            "meses": ["%04d-%02d" % (y, m) for (y, m) in meses],
            "pares_total": len(pares), "hechos": hechos, "fallidos": fallidos, "saltados": saltados,
            "parado_por_fallos": parado, "claves_en_salida": len(salida_final),
            "minutos_totales": round(sum(salida_final.values())),
            "horas_totales": round(sum(salida_final.values()) / 60.0, 1),
        }
        print(json.dumps(resumen, ensure_ascii=False, indent=1))
        return 0
    finally:
        dm.salir(sid)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # noqa: BLE001
        print("ERROR: %s" % e, file=sys.stderr)
        sys.exit(1)
