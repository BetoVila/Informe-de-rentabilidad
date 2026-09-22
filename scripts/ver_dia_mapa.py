# -*- coding: utf-8 -*-
"""Un dia de un camion en el mapa: traza real, paradas con hora y duracion, ciclos del triangulado v2 (coloreados) y la lista
de albaranes de GesRuta con su hora de inicio/fin, metodo y confianza. Para VER la realidad y comprobar el cruce.
HTML autonomo (Leaflet de cdnjs + mapa base Esri sin clave; funciona abierto como archivo local, tambien desde \\SERVIDOR).
Uso: un dia:   ver_dia_mapa.py --v2 triangulado_v2.json --diag diag.json --wialon <dir> --matricula 5790FSH --fecha 2026-01-07 --salida dia.html
     todos:    ver_dia_mapa.py --v2 ... --wialon <dir> --todos --salida-dir <carpeta>   (un fichero dias/<MATRICULA>_<fecha>.html
               por cada dia con viajes medidos; compacto: 1 punto cada 2 min y sin repetir puntos parados)"""
import argparse, collections, json, os, sys, datetime as dt
D = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, D)
import triangular_v2 as t2  # noqa: E402

PALETA = ["#2563eb", "#d97706", "#059669", "#dc2626", "#7c3aed", "#0891b2", "#be185d", "#65a30d", "#ea580c", "#4f46e5", "#0d9488", "#b91c1c", "#a21caf", "#1d4ed8", "#ca8a04"]
PLANTILLA = """<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>%(mat)s · %(fecha)s</title>
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.css"><script src="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.js"></script>
<style>:root{--ink:#12233b;--mut:#5b6b7f;--line:#e2e9f2}body{margin:0;font:14px system-ui,Segoe UI,sans-serif;color:var(--ink);background:#f6f8fb}
.wrap{padding:12px 16px;max-width:1400px;margin:0 auto}h1{font-size:18px;margin:0 0 4px}.sub{color:var(--mut);margin:0 0 10px}
#map{height:62vh;min-height:420px;border:1px solid var(--line);border-radius:10px}table{width:100%%;border-collapse:collapse;margin-top:12px;font-size:13px;background:#fff}
th,td{padding:5px 8px;border-bottom:1px solid #eef2f7;text-align:left;white-space:nowrap}th{background:#eef3fa;font-size:11px;text-transform:uppercase;color:var(--mut)}
.leg{display:flex;gap:14px;flex-wrap:wrap;font-size:12px;color:var(--mut);margin:8px 0}.leg b{display:inline-block;width:14px;height:14px;border-radius:3px;vertical-align:middle;margin-right:4px}
.tw{overflow-x:auto}@media print{#map{height:70vh}}</style></head><body><div class="wrap">
<h1>%(mat)s · %(fecha)s · %(n)d albaranes de GesRuta</h1><p class="sub">Jornada(s): %(jor)s. Traza real del localizador; cada color = un viaje medido (de su hora de inicio a la de fin); gris = sin viaje asignado. Círculos = paradas (≥ %(dw)d min): pincha para ver hora y minutos.</p>
<div id="map"></div>
<div class="leg"><span><b style="background:#9ca3af"></b>sin viaje asignado</span><span>Hora de Madrid. El primer viaje del día arranca al primer movimiento (incluye la ida desde la base); el último llega al fin de la jornada (incluye la vuelta).</span></div>
<div class="tw"><table><thead><tr><th>#</th><th>Alb. cantera</th><th>Origen → destino</th><th>Inicio</th><th>Fin</th><th>km</th><th>min</th><th>Cond.</th><th>Espera</th><th>Chofer</th><th>Método</th><th>Confianza</th><th>Aviso</th></tr></thead><tbody>%(filas)s</tbody></table></div>
</div><script>
const L0=%(lineas)s,P=%(paradas)s;const map=L.map('map');
L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}',{maxZoom:19,attribution:'© Esri · © OpenStreetMap'}).addTo(map);
const b=[];for(const [c,pts] of L0){L.polyline(pts,{color:c,weight:4,opacity:.85}).addTo(map);for(const p of pts)b.push(p);}
for(const p of P){L.circleMarker([p[0],p[1]],{radius:7,color:'#12233b',weight:1,fillColor:p[4],fillOpacity:.9}).addTo(map).bindTooltip(p[2]+' · '+p[3]+' min');}
if(b.length)map.fitBounds(b,{padding:[20,20]});
</script></body></html>"""


def render_dia(mat, fecha, viajes, pts_mat, dg_dia, rest_s, paso_s):
    """HTML de un dia. pts_mat = flujo continuo del camion. Devuelve (html, n_medidos) o None si no hay traza."""
    viajes = sorted(viajes, key=lambda x: (x["t_ini"] or "z", x["orden_dia"]))
    par = t2.paradas_flujo(pts_mat)
    jor_all = t2.jornadas_de(pts_mat, par, rest_s)
    jor = [j for j in jor_all if j["fecha"] == fecha or (j["nocturna"] and t2.fecha_de(j["fin"]) == fecha)]
    if not pts_mat:
        return None
    if jor:
        w0, w1 = min(j["c0"] for j in jor), max(j["c1"] for j in jor)
    else:
        d0 = dt.date.fromisoformat(fecha)
        w0 = int(dt.datetime.combine(d0, dt.time.min).timestamp()) - 7200; w1 = w0 + 86400 + 7200
    seg = [q for q in pts_mat if w0 <= q["t"] <= w1]
    if not seg:
        return None
    ciclos = []
    for i, x in enumerate(viajes):
        if x["t_ini"] and x["t_fin"]:
            ciclos.append((x["t_ini"], x["t_fin"], PALETA[i % len(PALETA)]))

    def color_de(t):
        s = t2.iso_min(t)
        for a_, b_, c in ciclos:
            if a_ <= s <= b_:
                return c
        return "#9ca3af"
    # polilineas por color, adelgazadas: 1 punto cada paso_s y sin repetir puntos parados (misma posicion redondeada)
    lineas, cur, curc, ult_t, ult_p = [], [], None, None, None
    for q in seg:
        p = [round(q["lat"], 4), round(q["lon"], 4)]
        c = color_de(q["t"])
        if c != curc and cur:
            lineas.append((curc, cur)); cur = [cur[-1]]
            ult_t = None
        curc = c
        if ult_t is not None and (q["t"] - ult_t) < paso_s and p == ult_p:
            continue
        if ult_t is not None and (q["t"] - ult_t) < paso_s and len(cur) > 1 and p == ult_p:
            continue
        cur.append(p); ult_t, ult_p = q["t"], p
    if cur:
        lineas.append((curc, cur))
    paradas = [[round(p["lat"], 4), round(p["lon"], 4), t2.iso_min(p["t_in"])[11:] + "–" + t2.iso_min(p["t_out"])[11:], (p["t_out"] - p["t_in"]) // 60, color_de(p["t_in"])]
               for p in par if w0 <= p["t_in"] <= w1]
    filas = "".join("<tr style=\"border-left:6px solid %s\"><td>%s</td><td>%s</td><td>%s → %s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>" % (
        (PALETA[i % len(PALETA)] if x["t_ini"] else "#9ca3af"), x["orden_dia"], x["cantera"], x["origen"], x["destino"], (x["t_ini"] or "")[11:], (x["t_fin"] or "")[11:] + ((" (+1)" if x["t_fin"] and x["t_ini"] and x["t_fin"][:10] != x["t_ini"][:10] else "")),
        "" if x["km"] is None else x["km"], "" if x["duracion_min"] is None else int(x["duracion_min"]), "" if x.get("min_conduccion") is None else int(x["min_conduccion"]),
        "" if x.get("min_espera") is None else int(x["min_espera"]), x.get("chofer_tacografo") or "", x["metodo"], x["confianza"] or "", (x["motivo"] or "")) for i, x in enumerate(viajes))
    dg = {j_["ini"]: j_ for j_ in (dg_dia or [])}
    jtxt = "; ".join("%s → %s (%.1f h%s%s)" % (t2.iso_min(j["ini"])[11:], t2.iso_min(j["fin"])[11:], j["horas"], ", nocturna" if j["nocturna"] else "",
                     (", %s, %d ciclos, %d asignados" % (dg[t2.iso_min(j["ini"])]["modo"], dg[t2.iso_min(j["ini"])]["ciclos"], dg[t2.iso_min(j["ini"])]["asignados"])) if t2.iso_min(j["ini"]) in dg else "") for j in jor) or "sin jornada"
    html = PLANTILLA % {"mat": mat, "fecha": fecha, "n": len(viajes), "jor": jtxt, "dw": int(t2.DWELL_S / 60), "filas": filas,
                        "lineas": json.dumps(lineas, separators=(",", ":")), "paradas": json.dumps(paradas, ensure_ascii=False, separators=(",", ":"))}
    return html, sum(1 for x in viajes if x["t_ini"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--v2", required=True); ap.add_argument("--diag", default="")
    ap.add_argument("--wialon", action="append", default=[]); ap.add_argument("--locatel", action="append", default=[])
    ap.add_argument("--matricula", default=""); ap.add_argument("--fecha", default=""); ap.add_argument("--salida", default="")
    ap.add_argument("--todos", action="store_true"); ap.add_argument("--salida-dir", dest="salida_dir", default="")
    ap.add_argument("--rest-h", type=float, default=8.0); ap.add_argument("--dwell-min", type=float, default=3.0)
    ap.add_argument("--paso-s", type=int, default=120, dest="paso_s", help="segundos entre puntos dibujados (compacto)")
    a = ap.parse_args()
    t2.DWELL_S = int(a.dwell_min * 60)
    rest_s = int(a.rest_h * 3600)
    v2 = json.load(open(a.v2, encoding="utf-8"))
    dg = {}
    if a.diag and os.path.isfile(a.diag):
        for d_ in json.load(open(a.diag, encoding="utf-8")).get("dias") or []:
            dg[(d_["matricula"], d_["fecha"])] = d_["jornadas"]
    # agrupado por la FECHA REAL del viaje (la de la traza; = la de GesRuta salvo tickets recuperados en otro dia): es la que
    # enseña el informe y la que nombra el fichero dias\<MATRICULA>_<fecha>.html
    por_dia = collections.defaultdict(list)
    for x in v2["viajes"]:
        por_dia[(x["matricula"], x["fecha"])].append(x)
    dirs = [("locatel", d) for d in a.locatel] + [("wialon", d) for d in a.wialon]
    if a.todos:
        if not a.salida_dir:
            print("--todos necesita --salida-dir"); sys.exit(2)
        os.makedirs(a.salida_dir, exist_ok=True)
        trazas = t2.cargar_trazas(dirs)
        flujo, _, _ = t2.coser(trazas)
        n = 0; kb = 0
        for (mat, fecha), viajes in sorted(por_dia.items()):
            if not any(x["t_ini"] for x in viajes) or mat not in flujo:
                continue
            r = render_dia(mat, fecha, viajes, flujo[mat], dg.get((mat, fecha)), rest_s, a.paso_s)
            if not r:
                continue
            ruta = os.path.join(a.salida_dir, "%s_%s.html" % (mat, fecha))
            open(ruta, "w", encoding="utf-8").write(r[0]); n += 1; kb += os.path.getsize(ruta) / 1024.0
        print(json.dumps({"dias": n, "MB": round(kb / 1024.0, 1), "carpeta": a.salida_dir}))
        return
    mat = t2.v1.clean(a.matricula)
    d0 = dt.date.fromisoformat(a.fecha)
    dias = {(d0 + dt.timedelta(days=k)).isoformat() for k in (-1, 0, 1)}
    tr = {k: v for k, v in t2.cargar_trazas(dirs).items() if k[0] == mat and k[1] in dias}
    flujo, _, _ = t2.coser(tr)
    r = render_dia(mat, a.fecha, por_dia.get((mat, a.fecha), []), flujo.get(mat, []), dg.get((mat, a.fecha)), rest_s, a.paso_s)
    if not r:
        print("sin traza"); return
    open(a.salida, "w", encoding="utf-8").write(r[0])
    print("ok", a.salida, "| viajes:", len(por_dia.get((mat, a.fecha), [])), "| medidos:", r[1])


if __name__ == "__main__":
    main()
