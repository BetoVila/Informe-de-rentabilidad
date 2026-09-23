# -*- coding: utf-8 -*-
"""Descargador de HISTORICO de Movertis (Wialon) para la triangulacion de km/duracion. SOLO LECTURA.

Baja, por unidad y dia de 2026: km (del sensor de kilometraje), la TRAZA de posiciones adelgazada (t, lat, lon,
velocidad) y las marcas de tiempo (primer/ultimo mensaje) para poder segmentar por ventanas horarias de albaran.

Reglas de oro:
- La clave sale del entorno WIALON_TOKEN y NUNCA se imprime.
- UNA SOLA sesion: token/login -> ... -> core/logout SIEMPRE en finally. No se lanza en bucle ni de madrugada, y no
  se choca con el ERP (que abre sesion cada ~2 y ~30 min): esto es una pasada corta y puntual.
- No se inventa nada: si un dia no trae mensajes, km=None y se dice; el dia sin traza no se rellena con ceros.

Modos:
  --prueba                 1 unidad (--unidad o la primera), 1 dia reciente (--dia o ayer). Confirma que responde.
  --retencion              1 unidad, una bateria de dias de sonda; usa SOLO el 'count' de load_interval (ligero) para
                           ver hasta que fecha Wialon retiene mensajes (interesa may-ago 2026). No descarga mensajes.
  --desde D --hasta D      bajada real por unidad+dia (traza+km). Con --solo se limita a unas unidades. ESCALAR solo
                           tras confirmar prueba+retencion; parar y reportar antes de bajar la flota entera de todo el ano.
"""
import argparse, datetime, hashlib, json, math, os, re, sys, time, urllib.parse, urllib.request

BASE = "https://hst-api.wialon.com/wialon/ajax.html"
PASO = 60  # segundos entre posiciones que se guardan (adelgazado de la traza)

# CONDUCTOR Y ACTIVIDAD (21/09/2026, Roberto): la telematica dice quien lleva el camion y que hace (conduccion / otros
# trabajos / disponibilidad / descanso). Se registran los CAMBIOS de cada parametro de conductor/tacografo a resolucion
# COMPLETA (no adelgazada), con su hora. PRIVACIDAD: la tarjeta del tacografo lleva el DNI dentro: los identificadores
# se guardan SOLO como hash opaco (sal propia); los estados (codigos pequenos) se guardan tal cual.
RE_COND = re.compile(r"(tco|tacho|drv|driver|ibutton|rfid|card)", re.I)
# Contadores que cambian en casi cada mensaje (distancias del tacografo y minutos en la actividad): se EXCLUYEN de los
# eventos para no inflar la traza; el km ya sale de can_mileage y la duracion de cada actividad sale de sus cambios.
RE_EXCL = re.compile(r"(odo|distance|_tm\d*$)", re.I)
# La tarjeta de conductor LLEVA EL DNI/NIE DENTRO (patron L########L######). Para enlazar con chofer.dbf (NUMTAC
# vacio en ~94%, NIF relleno en ~90%) se extrae EN MEMORIA el DNI/NIE embebido y se guarda SOLO su hash ('nif_h').
RE_TARJETA = re.compile(r"(driver\d?_id|drv\d?_id)", re.I)
RE_DOC = re.compile(r"(\d{8}[A-Z]|[XYZ]\d{7}[A-Z])")
VERSION_CONDUCTOR = 2
# Verificado en mensajes reales (0063NBM 18/09/2026): tco_driver1_id / tacho_drv1_id = tarjeta del conductor 1;
# tco_activity_type1 = actividad del conductor 1 (velocidad media: 3 -> 32,7 km/h conduccion; 2 -> 0,7 otros
# trabajos; 0 -> 0,1 descanso; 1 = disponibilidad segun el estandar FMS). *2 = conductor 2.
RE_ID = re.compile(r"(id\b|_id|driver|ibutton|rfid|card|name|nombre|dni|nif)", re.I)
SAL = os.environ.get("RAZO_HASH_SALT") or "vilpor-conductor-v1"


def opaco(v):
    return "h:" + hashlib.sha256((SAL + "|" + str(v).strip().upper()).encode("utf-8")).hexdigest()[:16]


def valor_conductor(k, v):
    """Campo con pinta de IDENTIFICADOR (id, driver, card, rfid, ibutton, nombre, dni, nif) -> hash opaco (salvo 0-15,
    que son banderas). Estados y tiempos numericos -> tal cual. Nunca se escribe un identificador en claro."""
    es_id = bool(RE_ID.search(k))
    try:
        f = float(v)
        if not es_id:
            return int(f) if f.is_integer() else f
        if f.is_integer() and 0 <= f <= 15:
            return int(f)
        return opaco(v)
    except (TypeError, ValueError):
        pass
    if v in (None, ""):
        return v
    return opaco(v) if es_id else str(v)[:40]


def guardar_json(path, obj):
    """Escritura atomica: si el proceso se corta, el fichero anterior sigue entero."""
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False)
    os.replace(tmp, path)


def clean_plate(v):
    k = re.sub(r"[^0-9A-Z]", "", (v or "").upper())
    return "" if k in {"", "0", "000000"} else k


def llamar(svc, params, sid=None, reintentos=3, espera=4):
    datos = {"svc": svc, "params": json.dumps(params or {})}
    if sid:
        datos["sid"] = sid
    cuerpo = urllib.parse.urlencode(datos).encode("utf-8")
    ultimo = ""
    for intento in range(reintentos):
        try:
            with urllib.request.urlopen(urllib.request.Request(BASE, data=cuerpo), timeout=120) as r:
                obj = json.loads(r.read().decode("utf-8", "replace"))
            if isinstance(obj, dict) and "error" in obj and obj["error"] != 0:
                # 1 = sesion no valida/caducada; 5 = ejecucion; 4 = parametros. No se reintenta el 1 (mejor reportar).
                ultimo = "error Wialon %s" % obj["error"]
                if obj["error"] in (1, 7):
                    raise RuntimeError(ultimo)
            else:
                return obj
        except Exception as e:  # noqa: BLE001
            ultimo = str(e)
        time.sleep(espera)
    raise RuntimeError("Movertis no contesta a '%s': %s" % (svc, ultimo))


def entrar(token):
    r = llamar("token/login", {"token": token})
    sid = (r or {}).get("eid")
    if not sid:
        raise RuntimeError("Movertis no devolvio sesion (WIALON_TOKEN invalido o caducado)")
    # datos de cuenta utiles: nombre y, si viene, el periodo de historico
    return sid, (r or {}).get("user", {}).get("nm", "")


def salir(sid):
    if not sid:
        return
    try:
        llamar("core/logout", {}, sid=sid, reintentos=1)
    except Exception as e:  # noqa: BLE001
        print("AVISO: no se pudo cerrar la sesion (%s). El trabajo ya esta hecho." % e, file=sys.stderr)


def unidades(sid):
    r = llamar("core/search_items", {
        "spec": {"itemsType": "avl_unit", "propName": "sys_name", "propValueMask": "*", "sortType": "sys_name"},
        "force": 1, "flags": 1 | 0x1000, "from": 0, "to": 0}, sid=sid)
    return (r or {}).get("items") or []


def formula_de(expr):
    """De 'can_mileage*const0.005' saca (param, factor, desplazamiento)."""
    e = (expr or "").lower().replace("const", "")
    import re
    mp = re.search(r"([a-z_][a-z0-9_]*)", e)
    if not mp:
        return None, 1.0, 0.0
    param = mp.group(1)
    mf = re.search(r"\*\s*([0-9.]+)", e)
    factor = float(mf.group(1)) if mf else 1.0
    mo = re.search(r"([+-])\s*([0-9.]+)\s*$", e)
    off = (float(mo.group(2)) * (-1 if mo.group(1) == "-" else 1)) if mo else 0.0
    return param, factor, off


KM_PREF = ("mileage", "absolute mileage", "relative mileage", "odometer", "absolute odometer")


def sensores(unidad):
    """(km_param, km_factor, fuel_param, fuel_factor). km preferido 'mileage'>'odometer'; fuel = contador ACUMULADO
    de litros consumidos ('absolute fuel consumption' o parametro tipo fuel_consumed/used/absolute). Instantaneo/nivel NO."""
    sens = list((unidad.get("sens") or {}).values())
    km = fuel = None
    for s in sens:
        tipo = str((s or {}).get("t") or "").strip().lower()
        param, factor, _ = formula_de(str((s or {}).get("p") or ""))
        if not param:
            continue
        if tipo in KM_PREF:
            r = KM_PREF.index(tipo)
            if km is None or r < km[0]:
                km = (r, param, factor)
        # combustible acumulado: evita nivel / instantaneo / caudal
        if "fuel" in tipo and any(x in tipo for x in ("absolute", "consum", "counted", "used")) \
                and not any(x in tipo for x in ("level", "instant", "rate", "impulse")):
            if fuel is None:
                fuel = (param, factor)
    if km is None:
        for s in sens:
            param, factor, _ = formula_de(str((s or {}).get("p") or ""))
            if param and ("mileage" in param or "odom" in param):
                km = (0, param, factor); break
    if fuel is None:
        for s in sens:
            param, factor, _ = formula_de(str((s or {}).get("p") or ""))
            pl = (param or "").lower()
            if "fuel" in pl and any(x in pl for x in ("consum", "used", "absol", "total")):
                fuel = (param, factor); break
    return (km[1] if km else None, km[2] if km else None,
            fuel[0] if fuel else None, fuel[1] if fuel else None)


def ventana(dia, zona):
    import datetime as dt
    d0 = dt.datetime.combine(dia, dt.time.min)
    d1 = dt.datetime.combine(dia, dt.time.max)
    if hasattr(zona, "localize"):
        d0, d1 = zona.localize(d0), zona.localize(d1)
    else:
        d0, d1 = d0.replace(tzinfo=zona), d1.replace(tzinfo=zona)
    return int(d0.timestamp()), int(d1.timestamp())


class _Madrid(datetime.tzinfo):
    """Europe/Madrid sin tzdata ni pytz (el Python del runtime no los trae): CET +1 / CEST +2 con la regla UE
    (ultimo domingo de marzo 02:00 local -> ultimo domingo de octubre 03:00 local)."""
    @staticmethod
    def _ultimo_domingo(y, m):
        d = datetime.date(y, m, 31)
        return d - datetime.timedelta(days=(d.weekday() + 1) % 7)

    def _verano(self, dt):
        if dt is None:
            return False
        ini = datetime.datetime.combine(self._ultimo_domingo(dt.year, 3), datetime.time(2))
        fin = datetime.datetime.combine(self._ultimo_domingo(dt.year, 10), datetime.time(3))
        return ini <= dt.replace(tzinfo=None) < fin

    def utcoffset(self, dt):
        return datetime.timedelta(hours=2 if self._verano(dt) else 1)

    def dst(self, dt):
        return datetime.timedelta(hours=1 if self._verano(dt) else 0)

    def tzname(self, dt):
        return "CEST" if self._verano(dt) else "CET"


def zona_casa(nombre="Europe/Madrid"):
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(nombre)
    except Exception:  # noqa: BLE001
        try:
            import pytz
            return pytz.timezone(nombre)
        except Exception:  # noqa: BLE001
            return _Madrid()


def contar_dia(sid, unit_id, t0, t1):
    """Solo el numero de mensajes del intervalo (ligero: no descarga los mensajes)."""
    r = llamar("messages/load_interval", {"itemId": unit_id, "timeFrom": t0, "timeTo": t1,
                                          "flags": 0, "flagsMask": 0, "loadCount": 0}, sid=sid)
    n = (r or {}).get("count", 0)
    try:
        llamar("messages/unload", {}, sid=sid, reintentos=1)
    except Exception:  # noqa: BLE001
        pass
    return n


def mensajes_dia(sid, unit_id, t0, t1):
    llamar("messages/load_interval", {"itemId": unit_id, "timeFrom": t0, "timeTo": t1,
                                      "flags": 0, "flagsMask": 0, "loadCount": 0xFFFFFFFF, "calcSensors": 0}, sid=sid)
    try:
        r = llamar("messages/get_messages", {"indexFrom": 0, "indexTo": 0xFFFFFFFF}, sid=sid)
    finally:
        try:
            llamar("messages/unload", {}, sid=sid, reintentos=1)
        except Exception:  # noqa: BLE001
            pass
    if isinstance(r, dict):
        r = r.get("messages") or []
    return r or []


def _num(v):
    try:
        x = float(v)
        return x if math.isfinite(x) else None
    except (TypeError, ValueError):
        return None


def _total_positivo(pares):
    """Suma de deltas positivos de una serie (t, valor) acumulada. Robusto a un reset o lecturas a cero."""
    vals = [(t, v) for t, v in pares if v is not None and v > 0]
    if len(vals) < 2:
        return None
    vals.sort()
    tot = 0.0
    for i in range(1, len(vals)):
        d = vals[i][1] - vals[i - 1][1]
        if d > 0:
            tot += d
    return tot


def _haversine(a, b):
    """km entre dos (lat,lon)."""
    from math import radians, sin, cos, asin, sqrt
    la1, lo1, la2, lo2 = map(radians, (a[0], a[1], b[0], b[1]))
    h = sin((la2 - la1) / 2) ** 2 + cos(la1) * cos(la2) * sin((lo2 - lo1) / 2) ** 2
    return 2 * 6371.0088 * asin(sqrt(h))


def _km_gps(conpos, umbral_km=0.02):
    """Distancia recorrida integrando el track (ignora saltos < umbral = ruido de GPS parado)."""
    if len(conpos) < 2:
        return None
    tot = 0.0
    prev = None
    for x in conpos:
        p = (x["lat"], x["lon"])
        if prev is not None:
            d = _haversine(prev, p)
            if d >= umbral_km and d <= 20:  # 20 km entre dos mensajes = salto imposible, se ignora
                tot += d
        prev = p
    return round(tot, 2)


def procesar(sid, u, dia, zona, salida_dir, guardar_traza=True):
    """Baja el dia de una unidad: km y LITROS del dia (delta de contadores) + traza con los contadores
    ACUMULADOS de km y litros en cada punto, para que la triangulacion saque km/litros por segmento por diferencia."""
    t0, t1 = ventana(dia, zona)
    kmp, kmf, flp, flf = sensores(u)
    msgs = mensajes_dia(sid, u["id"], t0, t1)
    puntos = []  # ordenados por t: {t, lat, lon, s, kmc(acum km real), litc(acum litros real)}
    for m in msgs:
        t = _num(m.get("t"))
        if not t or t <= 0:
            continue
        t = int(t)
        p = m.get("p") if isinstance(m.get("p"), dict) else {}
        pos = m.get("pos") if isinstance(m.get("pos"), dict) else m
        lat = _num(pos.get("y")); lon = _num(pos.get("x")); s = _num(pos.get("s"))
        if lat is not None and (not (-90 <= lat <= 90) or not (-180 <= lon <= 180) or (lat == 0 and lon == 0)):
            lat = lon = None
        kmc = _num(p.get(kmp)) if kmp else None
        litc = _num(p.get(flp)) if flp else None
        puntos.append({"t": t, "lat": lat, "lon": lon, "s": (max(0.0, s) if s is not None else None),
                       "kmc": (kmc * (kmf or 1.0)) if kmc is not None else None,
                       "litc": (litc * (flf or 1.0)) if litc is not None else None})
    puntos.sort(key=lambda x: x["t"])
    # eventos de conductor/actividad a resolucion completa: solo los CAMBIOS de valor, con su hora
    eventos, ultimo, nombres = [], {}, set()
    for m in sorted(msgs, key=lambda m: _num(m.get("t")) or 0):
        p = m.get("p") if isinstance(m.get("p"), dict) else {}
        t = _num(m.get("t"))
        if not t:
            continue
        for k, v in p.items():
            if not RE_COND.search(k) or RE_EXCL.search(k):
                continue
            nombres.add(k)
            val = valor_conductor(k, v)
            if ultimo.get(k, "__nada__") != val:
                ev = {"t": int(t), "k": k, "v": val}
                if isinstance(val, str) and val.startswith("h:") and RE_TARJETA.search(k):
                    mm = RE_DOC.search(str(v).upper())
                    if mm:
                        ev["nif_h"] = opaco(mm.group(0))
                eventos.append(ev)
                ultimo[k] = val
    km_can = _total_positivo([(x["t"], x["kmc"]) for x in puntos])
    lit = _total_positivo([(x["t"], x["litc"]) for x in puntos])
    # traza adelgazada (solo puntos con posicion valida), conservando los contadores acumulados
    conpos = [x for x in puntos if x["lat"] is not None]
    km_gps = _km_gps(conpos)
    # km del dia: manda el cuentakilometros CAN si hay; si no, la integracion del track GPS.
    km = km_can if (km_can is not None and km_can > 0) else km_gps
    traza = []
    ult = None
    for i, x in enumerate(conpos):
        if i in (0, len(conpos) - 1) or ult is None or (x["t"] - ult) >= PASO:
            traza.append({"t": x["t"], "lat": round(x["lat"], 5), "lon": round(x["lon"], 5),
                          "s": round(x["s"], 1) if x["s"] is not None else None,
                          "kmc": round(x["kmc"], 3) if x["kmc"] is not None else None,
                          "litc": round(x["litc"], 3) if x["litc"] is not None else None})
            ult = x["t"]
    movi = 0
    prev = None
    for x in conpos:
        if prev is not None and (x["s"] or 0) > 2 and (x["t"] - prev) <= 900:
            movi += (x["t"] - prev)
        prev = x["t"]
    reg = {"unidad": u.get("nm", ""), "unit_id": u["id"], "dia": dia.isoformat(), "mensajes": len(msgs),
           "km": round(km, 2) if km is not None else None,
           "km_can": round(km_can, 2) if km_can is not None else None, "km_gps": km_gps,
           "km_fuente": "can_mileage" if (km_can is not None and km_can > 0) else ("gps" if km_gps else None),
           "litros": round(lit, 2) if (lit is not None and lit > 0) else None, "litros_crudo": True,
           "sensor_km": kmp, "sensor_fuel": flp,
           "tiene_fuel": bool(flp) and (lit is not None and lit > 0),
           "t_ini": conpos[0]["t"] if conpos else None, "t_fin": conpos[-1]["t"] if conpos else None,
           "segundos_movimiento": movi, "puntos_traza": len(traza),
           "params_conductor": sorted(nombres), "eventos_conductor": len(eventos),
           "ids_conductor_dia": len({e["v"] for e in eventos if isinstance(e["v"], str) and e["v"].startswith("h:")}),
           "version_conductor": VERSION_CONDUCTOR}
    if guardar_traza and salida_dir:
        os.makedirs(salida_dir, exist_ok=True)
        with open(os.path.join(salida_dir, "traza_%s_%s.json" % (u.get("nm", "u"), dia.isoformat())), "w", encoding="utf-8") as f:
            json.dump({**reg, "version_conductor": VERSION_CONDUCTOR, "traza": traza, "conductor_eventos": eventos}, f,
                      ensure_ascii=False)
    return reg


def diagnostico_conductores(sid, items, quien, dia, zona):
    """Que parametros de conductor/tacografo traen los mensajes REALES de una unidad un dia, sus valores (ids en hash),
    la velocidad media por estado (para verificar p.ej. 3 = conduccion), los sensores de conductor definidos, los
    recursos con conductores y las asignaciones conductor<->unidad de la semana. Solo recuentos: nunca nombres/tarjetas."""
    import collections
    u = elegir_unidad(items, quien)
    t0, t1 = ventana(dia, zona)
    msgs = mensajes_dia(sid, u["id"], t0, t1)
    claves = collections.Counter()
    valores = collections.defaultdict(collections.Counter)
    vel = collections.defaultdict(list)
    for m in msgs:
        p = m.get("p") if isinstance(m.get("p"), dict) else {}
        pos = m.get("pos") if isinstance(m.get("pos"), dict) else m
        s = _num(pos.get("s")) or 0.0
        for k, v in p.items():
            if not RE_COND.search(k):
                continue
            claves[k] += 1
            vv = valor_conductor(k, v)
            etq = (vv[:8] + "..") if isinstance(vv, str) and vv.startswith("h:") else vv
            valores[k][str(etq)] += 1
            if isinstance(vv, int) and vv <= 15:
                vel[(k, vv)].append(s)
    params = {k: {"mensajes": n, "pct": round(100.0 * n / max(1, len(msgs)), 1), "distintos": len(valores[k]),
                  "top": valores[k].most_common(6)} for k, n in claves.most_common()}
    vel_media = {"%s=%s" % kv: {"n": len(l), "vel_media": round(sum(l) / len(l), 1)} for kv, l in sorted(vel.items()) if l}
    sens = [{"n": s.get("n"), "t": s.get("t"), "p": s.get("p")} for s in (u.get("sens") or {}).values()
            if str(s.get("t") or "").lower() == "driver" or RE_COND.search(str(s.get("p") or ""))]
    recursos = []
    try:
        r = llamar("core/search_items", {"spec": {"itemsType": "avl_resource", "propName": "sys_name", "propValueMask": "*",
                                                   "sortType": "sys_name"}, "force": 1, "flags": 0x1 | 0x4000 | 0x8000,
                                          "from": 0, "to": 0}, sid=sid)
        for it in (r or {}).get("items") or []:
            drv = it.get("drvrs") or {}
            recursos.append({"resource_id": it.get("id"), "conductores": len(drv),
                             "campos_de_conductor": sorted({kk for d in drv.values() for kk in (d or {}).keys()}),
                             "con_codigo": sum(1 for d in drv.values() if (d or {}).get("c")),
                             "claves_recurso": sorted(it.keys())[:25]})
    except Exception as e:  # noqa: BLE001
        recursos.append({"error": str(e)[:150]})
    asign = None
    for rr in recursos:
        if rr.get("conductores"):
            try:
                b = llamar("resource/get_driver_bindings", {"resourceId": rr["resource_id"], "unitId": u["id"], "driverId": 0,
                                                            "timeFrom": t0 - 6 * 86400, "timeTo": t1}, sid=sid)
                if isinstance(b, dict):
                    asign = {"tipo": "dict", "conductores_con_asignaciones": len(b),
                             "asignaciones": sum(len(v) for v in b.values() if isinstance(v, list)),
                             "muestra": [{"t": x.get("t"), "u": x.get("u")} for v in list(b.values())[:1] for x in (v or [])[:4]]}
                else:
                    asign = {"tipo": type(b).__name__, "n": len(b or [])}
            except Exception as e:  # noqa: BLE001
                asign = {"error": str(e)[:150]}
            break
    return {"unidad": u.get("nm"), "dia": dia.isoformat(), "mensajes": len(msgs), "params_en_mensajes": params,
            "velocidad_media_por_estado": vel_media, "sensores_conductor": sens, "recursos": recursos,
            "asignaciones_7dias": asign}


def elegir_unidad(items, quien):
    if not quien:
        return items[0]
    q = clean_plate(quien)
    for u in items:
        if clean_plate(u.get("nm", "")) == q:
            return u
    ql = quien.strip().lower()
    for u in items:
        if ql in str(u.get("nm", "")).lower():
            return u
    return items[0]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--modo", choices=["prueba", "retencion", "bajada", "pares", "conductores"], default="prueba")
    ap.add_argument("--unidad", default="")
    ap.add_argument("--dia", default="")
    ap.add_argument("--desde", default="")
    ap.add_argument("--hasta", default="")
    ap.add_argument("--solo", default="", help="subcadenas de nombre separadas por comas (limita unidades en bajada)")
    ap.add_argument("--pares", default="", help="JSON con {'pares':[{'mat','dia'},...]} a bajar (modo pares)")
    ap.add_argument("--pausa", type=float, default=4.0, help="segundos de espera entre peticiones (poco a poco)")
    ap.add_argument("--max-fallos", type=int, default=6, dest="max_fallos", help="fallos consecutivos antes de PARAR")
    ap.add_argument("--salida", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "wialon_hist"))
    a = ap.parse_args()
    token = os.environ.get("WIALON_TOKEN") or ""
    if not token:
        print("ERROR: falta WIALON_TOKEN en el entorno (no se teclea; se pone con setx).", file=sys.stderr)
        return 2
    zona = zona_casa()
    hoy = datetime.datetime.now(datetime.timezone.utc).astimezone(zona).date()
    sid = None
    try:
        sid, cuenta = entrar(token)
        items = unidades(sid)
        info = {"unidades_total": len(items), "cuenta": bool(cuenta)}
        if a.modo == "prueba":
            u = elegir_unidad(items, a.unidad)
            dia = datetime.date.fromisoformat(a.dia) if a.dia else (hoy - datetime.timedelta(days=1))
            reg = procesar(sid, u, dia, zona, a.salida)
            print(json.dumps({**info, "prueba": reg}, ensure_ascii=False))
        elif a.modo == "retencion":
            u = elegir_unidad(items, a.unidad)
            dias = a.dia.split(",") if a.dia else [
                (hoy - datetime.timedelta(days=1)).isoformat(),
                "2026-09-01", "2026-08-10", "2026-07-15", "2026-06-15", "2026-05-15",
                "2026-04-15", "2026-03-15", "2026-02-15", "2026-01-15",
                "2025-12-01", "2025-10-15", "2025-08-25", "2025-06-15"]
            res = []
            for ds in dias:
                d = datetime.date.fromisoformat(ds)
                t0, t1 = ventana(d, zona)
                n = contar_dia(sid, u["id"], t0, t1)
                res.append({"dia": ds, "mensajes": n})
                time.sleep(0.3)
            print(json.dumps({**info, "unidad": u.get("nm", ""), "retencion": res}, ensure_ascii=False))
        elif a.modo == "conductores":
            dia = datetime.date.fromisoformat(a.dia) if a.dia else (hoy - datetime.timedelta(days=3))
            print(json.dumps({**info, "conductores": diagnostico_conductores(sid, items, a.unidad, dia, zona)},
                             ensure_ascii=False, indent=1))
        elif a.modo == "pares":
            if not a.pares:
                print("ERROR: modo pares necesita --pares <json>", file=sys.stderr); return 2
            datos = json.load(open(a.pares, encoding="utf-8"))
            pares = datos["pares"] if isinstance(datos, dict) else datos
            porplaca = {}
            for u in items:
                p = clean_plate(u.get("nm", ""))
                if p:
                    porplaca[p] = u
            os.makedirs(a.salida, exist_ok=True)
            ckpt = os.path.join(a.salida, "_checkpoint.json")
            done = set()
            if os.path.isfile(ckpt):
                try:
                    done = set(json.load(open(ckpt, encoding="utf-8")))
                except Exception:  # noqa: BLE001
                    done = set()
            # el resumen tambien cuenta como hecho (por si un corte dejo el checkpoint a medias)
            rj = os.path.join(a.salida, "_resumen.jsonl")
            if os.path.isfile(rj):
                for linea in open(rj, encoding="utf-8"):
                    try:
                        x = json.loads(linea)
                    except ValueError:
                        continue
                    if x.get("unit_id") or x.get("estado") == "sin_unidad_wialon":
                        done.add(clean_plate(x.get("mat") or x.get("unidad")) + "|" + str(x.get("dia")))
            jsonl = open(os.path.join(a.salida, "_resumen.jsonl"), "a", encoding="utf-8")
            hechos = fallidos = saltados = sin_unidad = 0
            consec = 0
            parado = False
            for par in pares:
                plate = clean_plate(par.get("mat")); dia = par.get("dia")
                if not plate or not dia:
                    continue
                kkey = plate + "|" + dia
                if kkey in done:
                    saltados += 1; continue
                u = porplaca.get(plate)
                if not u:
                    sin_unidad += 1
                    jsonl.write(json.dumps({"mat": plate, "dia": dia, "estado": "sin_unidad_wialon"}, ensure_ascii=False) + "\n"); jsonl.flush()
                    done.add(kkey); guardar_json(ckpt, sorted(done))
                    continue
                ok = False
                for intento in range(1, 6):
                    try:
                        reg = procesar(sid, u, datetime.date.fromisoformat(dia), zona, a.salida)
                        reg["mat"] = plate
                        jsonl.write(json.dumps(reg, ensure_ascii=False) + "\n"); jsonl.flush()
                        hechos += 1; consec = 0; ok = True
                        break
                    except Exception:  # noqa: BLE001
                        if intento >= 3:  # sesion caida: recuperar UNA vez, sin pelear
                            try:
                                salir(sid); sid, _ = entrar(token)
                            except Exception:  # noqa: BLE001
                                pass
                        time.sleep(min(90, 5 * (2 ** (intento - 1))))
                if not ok:
                    fallidos += 1; consec += 1
                    jsonl.write(json.dumps({"mat": plate, "dia": dia, "estado": "fallo"}, ensure_ascii=False) + "\n"); jsonl.flush()
                    if consec >= a.max_fallos:
                        parado = True
                        break
                done.add(kkey)
                guardar_json(ckpt, sorted(done))
                if (hechos + fallidos) % 20 == 0:
                    json.dump({"hechos": hechos, "fallidos": fallidos, "saltados": saltados, "sin_unidad": sin_unidad,
                               "pendientes": len(pares) - len(done), "ts": datetime.datetime.now().isoformat(timespec="seconds")},
                              open(os.path.join(a.salida, "_estado.json"), "w", encoding="utf-8"), ensure_ascii=False)
                time.sleep(a.pausa)
            jsonl.close()
            json.dump({"hechos": hechos, "fallidos": fallidos, "saltados": saltados, "sin_unidad": sin_unidad,
                       "pendientes": len(pares) - len(done), "parado_por_fallos": parado,
                       "ts": datetime.datetime.now().isoformat(timespec="seconds")},
                      open(os.path.join(a.salida, "_estado.json"), "w", encoding="utf-8"), ensure_ascii=False)
            print(json.dumps({**info, "pares_total": len(pares), "hechos": hechos, "fallidos": fallidos,
                              "saltados": saltados, "sin_unidad": sin_unidad, "parado_por_fallos": parado}, ensure_ascii=False))
        else:  # bajada
            if not a.desde or not a.hasta:
                print("ERROR: bajada necesita --desde y --hasta", file=sys.stderr)
                return 2
            d0 = datetime.date.fromisoformat(a.desde)
            d1 = datetime.date.fromisoformat(a.hasta)
            filtros = [s.strip().lower() for s in a.solo.split(",") if s.strip()]
            sel = [u for u in items if not filtros or any(s in str(u.get("nm", "")).lower() for s in filtros)]
            resumen = []
            d = d0
            while d <= d1:
                for u in sel:
                    reg = procesar(sid, u, d, zona, a.salida)
                    resumen.append(reg)
                    time.sleep(0.2)
                d += datetime.timedelta(days=1)
            with open(os.path.join(a.salida, "_resumen.json"), "w", encoding="utf-8") as f:
                json.dump({**info, "desde": a.desde, "hasta": a.hasta, "unidades": len(sel), "filas": resumen}, f, ensure_ascii=False)
            print(json.dumps({**info, "bajada": {"unidades": len(sel), "dias": (d1 - d0).days + 1, "filas": len(resumen),
                                                 "con_km": sum(1 for r in resumen if r["km"] is not None)}}, ensure_ascii=False))
        return 0
    finally:
        salir(sid)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # noqa: BLE001
        print("ERROR: %s" % e, file=sys.stderr)
        sys.exit(1)
