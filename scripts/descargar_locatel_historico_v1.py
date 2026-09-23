# -*- coding: utf-8 -*-
"""Descargador de HISTORICO GPS de Locatel por el LOGIN DE USUARIO (lo autorizo Roberto). SOLO LECTURA.

Camino (el mismo que hace su web): POST /login.asp (usuario/password) -> GET /historicos_gps_in.asp (formulario con
la lista de vehiculos) -> POST /historicos_gps_out.asp?imprimir=1 con vehiculo_id + fh_ini/fh_fin + chk_coordenadas=1
-> tabla con fecha, hora, estado, velocidad, recorrido, latitud, longitud, poblacion, provincia por posicion.

Se REUTILIZA el cliente probado del ERP (importador/extraer_locatel.py): galleta en memoria, vista de impresion, lectura
de tablas y la guardia de la "trampa de la pestana" (si Locatel sirve otra pagina, el bloque lo dice y aqui NO se usa).

Reglas: credenciales del entorno (LOCATEL_USUARIO / LOCATEL_CLAVE), NUNCA impresas; corre en el PC de Roberto (el
contenedor no tiene sus certificados); pausa entre peticiones (educado); resumible por (matricula, dia); para si rechaza.

Modos: vehiculos | prueba --matricula --dia | retencion --matricula [--dia d1,d2..] | pares --pares <json>
"""
import argparse, datetime, json, math, os, re, sys, time

IMPORTADOR = r"C:\ODOO15-LOCAL\addons\razo_transporte\importador"
sys.path.insert(0, IMPORTADOR)
import extraer_locatel as L  # noqa: E402

D = os.path.dirname(os.path.abspath(__file__))


def clean(v):
    return re.sub(r"[^0-9A-Z]", "", (v or "").upper())


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


def zona_casa():
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo("Europe/Madrid")
    except Exception:  # noqa: BLE001
        try:
            import pytz
            return pytz.timezone("Europe/Madrid")
        except Exception:  # noqa: BLE001
            return _Madrid()


def num(s):
    """'43,3232' / '-8,5' / '45 km/h' / '1.234,5' -> float. None si no hay numero."""
    if s is None:
        return None
    if isinstance(s, (int, float)):
        return float(s)
    t = str(s).strip()
    m = re.search(r"-?[\d.,]+", t)
    if not m:
        return None
    t = m.group(0)
    if "," in t and "." in t:
        t = t.replace(".", "").replace(",", ".") if t.rfind(",") > t.rfind(".") else t.replace(",", "")
    elif "," in t:
        t = t.replace(",", ".")
    try:
        x = float(t)
        return x if math.isfinite(x) else None
    except ValueError:
        return None


def epoch(fecha, hora, zona):
    f = str(fecha or "").strip()
    h = str(hora or "").strip()
    m = re.search(r"(\d{1,2})/(\d{1,2})/(\d{2,4})", f)
    if not m:
        return None
    d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
    y = y + 2000 if y < 100 else y
    mh = re.search(r"(\d{1,2}):(\d{2})(?::(\d{2}))?", h or f)
    hh, mm, ss = (int(mh.group(1)), int(mh.group(2)), int(mh.group(3) or 0)) if mh else (0, 0, 0)
    dt = datetime.datetime(y, mo, d, hh, mm, ss)
    dt = zona.localize(dt) if hasattr(zona, "localize") else dt.replace(tzinfo=zona)
    return int(dt.timestamp())


def hav(a, b):
    from math import radians, sin, cos, asin, sqrt
    la1, lo1, la2, lo2 = map(radians, (a[0], a[1], b[0], b[1]))
    h = sin((la2 - la1) / 2) ** 2 + cos(la1) * cos(la2) * sin((lo2 - lo1) / 2) ** 2
    return 2 * 6371.0088 * asin(sqrt(h))


def minutos(estado):
    """'41 min.' / '1 h. 5 min.' / '2 h.' -> minutos de parada. None si la fila no es parada."""
    e = (estado or "").lower()
    if not e.strip():
        return None
    h = re.search(r"(\d+)\s*h", e)
    m = re.search(r"(\d+)\s*min", e)
    if not h and not m:
        return None
    return (int(h.group(1)) * 60 if h else 0) + (int(m.group(1)) if m else 0)


def puntos_de(filas, zona, dia=None):
    """Filas del historico (modo Resumido: una por tramo o parada) -> puntos ordenados del DIA pedido.
    La fecha dd/mm/aaaa se busca en las columnas crudas: la columna 'Fecha' que casa el lector es el rotulo largo."""
    t0 = t1 = None
    if dia is not None:
        t0 = epoch(dia.strftime("%d/%m/%Y"), "00:00:00", zona)
        t1 = epoch(dia.strftime("%d/%m/%Y"), "23:59:59", zona)
    pts = {}
    for f in filas or []:
        fecha = None
        for c in (f.get("_columnas") or []) + [f.get("fecha") or ""]:
            if re.fullmatch(r"\s*\d{1,2}/\d{1,2}/\d{2,4}\s*", str(c)):
                fecha = str(c).strip(); break
        t = epoch(fecha, f.get("hora"), zona) if fecha else None
        lat, lon = num(f.get("latitud")), num(f.get("longitud"))
        if t is None or lat is None or lon is None:
            continue
        if t0 is not None and not (t0 <= t <= t1):
            continue
        if not (-90 <= lat <= 90) or not (-180 <= lon <= 180) or (lat == 0 and lon == 0):
            continue
        pts[t] = {"t": t, "lat": round(lat, 6), "lon": round(lon, 6), "s": num(f.get("velocidad")),
                  "rec": num(f.get("recorrido")), "parada_min": minutos(f.get("estado")),
                  "pob": (f.get("poblacion") or "").strip(), "via": (f.get("zona") or "").strip(),
                  "prov": (f.get("provincia") or "").strip()}
    return [pts[k] for k in sorted(pts)]


def km_gps(pts, umbral=0.02):
    tot, prev = 0.0, None
    for p in pts:
        q = (p["lat"], p["lon"])
        if prev is not None:
            d = hav(prev, q)
            if umbral <= d <= 20:
                tot += d
        prev = q
    return round(tot, 2)


def km_recorrido(pts):
    """Si 'recorrido' es un contador que crece, su delta; si es por tramo, su suma. Se devuelven las dos lecturas."""
    vals = [p["rec"] for p in pts if p.get("rec") is not None]
    if len(vals) < 2:
        return None, None
    creciente = sum(1 for i in range(1, len(vals)) if vals[i] >= vals[i - 1]) >= 0.9 * (len(vals) - 1)
    delta = round(vals[-1] - vals[0], 2) if creciente else None
    return delta, round(sum(v for v in vals if v > 0), 2)


class Sesion(object):
    def __init__(self, espera):
        self.web = L.Locatel(os.environ.get("RAZO_LOCATEL_URL") or L.URL_BASE_RESPALDO, 3, espera)
        self.formulario = None

    def entrar(self):
        u, c = os.environ.get("LOCATEL_USUARIO") or "", os.environ.get("LOCATEL_CLAVE") or ""
        if not u or not c:
            raise RuntimeError("faltan LOCATEL_USUARIO / LOCATEL_CLAVE en el entorno")
        self.web.entrar(u, c)
        self.formulario = self.web.pedir("/historicos_gps_in.asp", parametros={})

    def vehiculos(self):
        return L.vehiculos_del_formulario_historico(self.formulario)

    def dia(self, vid, dia, modalidad="resumido"):
        datos = L.datos_del_formulario_historico(self.formulario, vid, dia, dia)
        # fh_ini/fh_fin son FECHA+HORA en su formulario: con solo la fecha el intervalo queda 00:00 -> 00:00 (vacio).
        datos["fh_ini"] = dia.strftime("%d/%m/%Y") + " 00:00"
        datos["fh_fin"] = dia.strftime("%d/%m/%Y") + " 23:59:59"
        datos["chk_paradas"] = "1"
        if modalidad == "extendido":
            for atr, cont in L._SELECT.findall(self.formulario):
                if L._atributos_de(atr).get("name") == "modalidad_historico":
                    for o in L._OPTION.findall(cont):
                        if "extend" in L._texto_html(o[1]).lower():
                            datos["modalidad_historico"] = L._atributos_de(o[0]).get("value") or ""
        return self.web.bloque("historicos_gps", datos=datos)

    def salir(self):
        try:
            self.web.salir()
        except Exception:  # noqa: BLE001
            pass


def procesar(ses, vid, plate, dia, zona, salida, modalidad="resumido"):
    b = ses.dia(vid, dia, modalidad)
    servida = b.get("pagina_servida")
    pts = puntos_de(b.get("filas"), zona, dia)
    rd, rs = km_recorrido(pts)
    mov = [p for p in pts if (p.get("s") or 0) > 3]
    paradas = [p for p in pts if p.get("parada_min")]
    reg = {"mat": plate, "vehiculo_id": str(vid), "dia": dia.isoformat(), "pagina_servida": servida,
           "modalidad": modalidad, "filas": len(b.get("filas") or []), "puntos": len(pts),
           "km": rs, "km_fuente": "locatel_recorrido", "km_gps": km_gps(pts),
           "paradas": len(paradas), "min_parado": sum(p["parada_min"] for p in paradas),
           "t_ini": pts[0]["t"] if pts else None, "t_fin": pts[-1]["t"] if pts else None,
           "t_primer_mov": mov[0]["t"] if mov else None, "t_ultimo_mov": mov[-1]["t"] if mov else None,
           "litros": None, "tiene_fuel": False}
    if servida not in (None, "", "historicos_gps"):
        reg["aviso"] = "Locatel sirvio otra pagina (%s): NO se usa este dia" % servida
        return reg
    os.makedirs(salida, exist_ok=True)
    with open(os.path.join(salida, "traza_%s_%s.json" % (plate, dia.isoformat())), "w", encoding="utf-8") as f:
        json.dump({**reg, "fuente": "locatel", "traza": pts}, f, ensure_ascii=False)
    return reg


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--modo", choices=["vehiculos", "prueba", "retencion", "pares"], default="vehiculos")
    ap.add_argument("--matricula", default="")
    ap.add_argument("--dia", default="")
    ap.add_argument("--pares", default="")
    ap.add_argument("--espera", type=float, default=4.0, help="segundos minimos entre peticiones a Locatel")
    ap.add_argument("--max-fallos", type=int, default=5, dest="max_fallos")
    ap.add_argument("--modalidad", choices=["resumido", "extendido"], default="resumido")
    ap.add_argument("--salida", default=os.path.join(D, "locatel_hist"))
    a = ap.parse_args()
    zona = zona_casa()
    ses = Sesion(a.espera)
    try:
        ses.entrar()
        veh = ses.vehiculos()
        porplaca = {}
        for vid, rot in veh:
            p = clean(rot)
            m = re.search(r"\d{4}[A-Z]{3}", p)
            porplaca[m.group(0) if m else p] = (vid, rot)
        if a.modo == "vehiculos":
            dem = json.load(open(os.path.join(D, "pares_no_movertis.json"), encoding="utf-8"))["pares"]
            demp = {}
            for x in dem:
                demp[clean(x["mat"])] = demp.get(clean(x["mat"]), 0) + x["viajes"]
            en = {p: n for p, n in demp.items() if p in porplaca}
            json.dump({"vehiculos": [{"vehiculo_id": v, "rotulo": r} for v, r in veh]},
                      open(os.path.join(D, "locatel_vehiculos.json"), "w", encoding="utf-8"), ensure_ascii=False)
            print(json.dumps({"vehiculos_locatel": len(veh), "matriculas_demanda_no_movertis": len(demp),
                              "de_ellas_en_locatel": len(en), "viajes_cubribles": sum(en.values()),
                              "viajes_no_movertis_total": sum(demp.values()),
                              "muestra_rotulos": [r for _, r in veh[:8]]}, ensure_ascii=False))
        elif a.modo == "prueba":
            p = clean(a.matricula)
            if p not in porplaca:
                print(json.dumps({"error": "matricula no esta en Locatel", "mat": p}, ensure_ascii=False)); return 2
            reg = procesar(ses, porplaca[p][0], p, datetime.date.fromisoformat(a.dia), zona, a.salida, a.modalidad)
            print(json.dumps(reg, ensure_ascii=False))
        elif a.modo == "retencion":
            p = clean(a.matricula)
            dias = a.dia.split(",") if a.dia else ["2026-09-15", "2026-06-15", "2026-03-16", "2026-01-12", "2025-10-15"]
            res = []
            for ds in dias:
                d = datetime.date.fromisoformat(ds)
                b = ses.dia(porplaca[p][0], d, a.modalidad)
                pts = puntos_de(b.get("filas"), zona, d)
                res.append({"dia": ds, "filas": len(b.get("filas") or []), "puntos_del_dia": len(pts),
                            "km": km_recorrido(pts)[1], "servida": b.get("pagina_servida")})
            print(json.dumps({"mat": p, "retencion": res}, ensure_ascii=False))
        else:  # pares
            pares = json.load(open(a.pares, encoding="utf-8"))["pares"]
            os.makedirs(a.salida, exist_ok=True)
            ckpt = os.path.join(a.salida, "_checkpoint.json")
            done = set(json.load(open(ckpt, encoding="utf-8"))) if os.path.isfile(ckpt) else set()
            jl = open(os.path.join(a.salida, "_resumen.jsonl"), "a", encoding="utf-8")
            hechos = fallidos = no_esta = saltados = consec = 0
            parado = False
            for par in pares:
                p, ds = clean(par["mat"]), par["dia"]
                k = p + "|" + ds
                if k in done:
                    saltados += 1; continue
                if p not in porplaca:
                    no_esta += 1; done.add(k)
                    jl.write(json.dumps({"mat": p, "dia": ds, "estado": "no_esta_en_locatel"}, ensure_ascii=False) + "\n"); jl.flush()
                    json.dump(sorted(done), open(ckpt, "w", encoding="utf-8")); continue
                ok = False
                for intento in range(1, 4):
                    try:
                        reg = procesar(ses, porplaca[p][0], p, datetime.date.fromisoformat(ds), zona, a.salida)
                        jl.write(json.dumps(reg, ensure_ascii=False) + "\n"); jl.flush()
                        hechos += 1; consec = 0; ok = True
                        break
                    except Exception:  # noqa: BLE001
                        time.sleep(min(120, 10 * (2 ** (intento - 1))))
                if not ok:
                    fallidos += 1; consec += 1
                    jl.write(json.dumps({"mat": p, "dia": ds, "estado": "fallo"}, ensure_ascii=False) + "\n"); jl.flush()
                    if consec >= a.max_fallos:
                        parado = True; break
                done.add(k)
                json.dump(sorted(done), open(ckpt, "w", encoding="utf-8"))
                if (hechos + fallidos) % 10 == 0:
                    json.dump({"hechos": hechos, "fallidos": fallidos, "no_esta": no_esta, "saltados": saltados,
                               "pendientes": len(pares) - len(done), "ts": datetime.datetime.now().isoformat(timespec="seconds")},
                              open(os.path.join(a.salida, "_estado.json"), "w", encoding="utf-8"), ensure_ascii=False)
            jl.close()
            est = {"hechos": hechos, "fallidos": fallidos, "no_esta": no_esta, "saltados": saltados,
                   "pendientes": len(pares) - len(done), "parado_por_fallos": parado,
                   "ts": datetime.datetime.now().isoformat(timespec="seconds")}
            json.dump(est, open(os.path.join(a.salida, "_estado.json"), "w", encoding="utf-8"), ensure_ascii=False)
            print(json.dumps(est, ensure_ascii=False))
        return 0
    finally:
        ses.salir()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # noqa: BLE001
        print("ERROR: %s" % e, file=sys.stderr)
        sys.exit(1)
