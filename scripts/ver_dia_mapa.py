# -*- coding: utf-8 -*-
"""Un dia de un camion en el mapa: traza real, viajes NUMERADOS y coloreados (del triangulado v2), paradas con lugar y duracion,
linea de tiempo del dia y lista de esperas. Para VER la realidad y comprobar el cruce. Pinchar un viaje (tabla, linea de tiempo,
leyenda o traza) lo resalta y atenua el resto; #v=<nº del dia> lo preselecciona (enlace «ver dia» del informe).
HTML autonomo (Leaflet de cdnjs + mapa base Esri sin clave; funciona abierto como archivo local, tambien desde \\SERVIDOR).
Uso: un dia:   ver_dia_mapa.py --v2 triangulado_v2.json --diag diag.json --wialon <dir> --matricula 5790FSH --fecha 2026-01-07 --salida dia.html
     todos:    ver_dia_mapa.py --v2 ... --wialon <dir> --todos --salida-dir <carpeta>   (un fichero dias/<MATRICULA>_<fecha>.html
               por cada dia con viajes medidos; compacto: 1 punto cada 2 min y sin repetir puntos parados)
Nombres de lugar: maestro GLOBAL de GesRuta (puntos + puntcd, Razo y Agetrans) y, con --geocode, los nombres geocodificados.
Las paradas se rotulan con el lugar conocido mas cercano (a menos de 700 m); si no hay, «lugar no conocido».
La carga y la descarga se rotulan por lo que VE EL GPS: el lugar del albaran solo si la parada cae dentro de su radio; si no,
el lugar conocido mas cercano y a cuantos km queda lo que dice el albaran. Si el albaran repite el lugar de carga como
destino (hormigon: la obra no tiene codigo) no se compara con el destino: se da el sitio del GPS y su distancia a la carga.
Sin señal: 30 min o mas sin posicion (parado, Wialon da una cada 1-5 min y Locatel cada 5-16) no es una parada; las
paradas de triangular_v2 que lo cruzan se parten y el hueco sale aparte. Las paradas que siguen tras el dia se recortan.
Export de trazas (--export-trazas <fichero .jsonl.gz>, con --todos): una linea JSON por viaje MEDIDO con su clave
(empresa, viaje, cantera), tiempos, posiciones de carga y descarga, km/litros/minutos y el recorrido real simplificado
(«ciclo» entero y tramo «cargado» de la salida de carga a la llegada a descarga), para las apps que dibujan rutas (tarifas,
ERP) sin tener que leer estos HTML. Sin --salida-dir solo escribe el export."""
import argparse, bisect, calendar, collections, gzip, json, math, os, statistics, sys, datetime as dt
D = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, D)
import triangular_v2 as t2  # noqa: E402
try:
    from export_rentabilidad_gesruta_actividad_v1 import cargar_lugares_global  # noqa: E402
except Exception:  # sin el modulo del export (instalacion parcial) se sigue con los codigos
    cargar_lugares_global = None

PALETA = ["#2563eb", "#d97706", "#059669", "#dc2626", "#7c3aed", "#0891b2", "#be185d", "#65a30d", "#ea580c", "#4f46e5", "#0d9488", "#b91c1c", "#a21caf", "#1d4ed8", "#ca8a04"]
DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"]
RADIO_LUGAR_KM = 0.7
# 30 min sin posicion = SIN SEÑAL, no parada: un camion parado da posicion cada 1-5 min en Wialon (p99 5,6 min, enero 2026)
# y cada 5-16 min en Locatel (contando la parada que trae en un punto); huecos de 30 min o mas: 0,15 % y 0,01 %.
HUECO_S = 1800
SALTO_KM = t2.HUB_EPS_KM                    # dos puntos parados a mas de 350 m no son la misma parada
# «Como se lee esta pagina» (plegable). Cargado/vacio/resto segun triangular_v2.medir_ciclo (+ la vuelta de la obra en hormigon).
AYUDA = [
    "Carga y descarga: la hora y el sitio son los que ve el GPS. Se pone el nombre del albarán solo si la parada cae en su sitio; si no, el lugar conocido más cercano y a cuántos km queda lo que dice el albarán.",
    "En hormigón el albarán suele poner la planta también como destino, porque la obra no tiene código: el sitio de la descarga es el que ve el GPS, y «a N km en línea recta de la carga» es la distancia entre los dos puntos, no los km recorridos.",
    "Km: los del contador del camión en todo el viaje. Cargado = de salir de la carga a llegar a la descarga. En vacío = de empezar el viaje a llegar a cargar (en hormigón, también la vuelta de la obra). Lo que no es ni lo uno ni lo otro sale aparte como «sin clasificar»: por ejemplo, moverse dentro de la planta, la cantera o la obra, o la vuelta a la base tras el último viaje.",
    "Sin señal (rayado): el localizador no dio posición durante 30 min o más. No se sabe si el camión estaba parado; si vuelve a aparecer en otro sitio, se dice a cuántos km. Una parada que sigue después del día se corta a las 24:00 y se dice hasta cuándo siguió.",
    "Confianza media o baja: el ciclo se asignó a ese albarán con dudas (por ejemplo, hay más albaranes que ciclos); su carga y su descarga son candidatas.",
    "El primer viaje del día arranca al primer movimiento (incluye la ida desde la base); el último llega al fin de la jornada (incluye la vuelta). Los viajes «repartidos» no tienen hora: su km y minutos son un reparto de los ciclos sobrantes del día.",
]

PLANTILLA = r"""<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>@@TITLE@@</title>
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.css"><script src="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.js"></script>
<style>:root{--ink:#12233b;--mut:#5b6b7f;--line:#e2e9f2;--soft:#eef3fa}body{margin:0;font:14px system-ui,Segoe UI,sans-serif;color:var(--ink);background:#f6f8fb}
.wrap{padding:12px 16px 30px;max-width:1500px;margin:0 auto}h1{font-size:19px;margin:0 0 4px}h2{font-size:15px;margin:18px 0 6px;color:#233246}.sub{color:var(--mut);margin:0 0 10px;line-height:1.5}
.chips{display:flex;gap:8px;flex-wrap:wrap;margin:6px 0 10px}.chip{background:#fff;border:1px solid var(--line);border-radius:9px;padding:6px 12px;display:grid;line-height:1.25}.chip small{font-size:10.5px;color:var(--mut);text-transform:uppercase;letter-spacing:.04em}.chip b{font-size:15px}
.tlwrap{background:#fff;border:1px solid var(--line);border-radius:10px;padding:6px 10px 2px;margin-bottom:8px}#tl{width:100%;height:104px;display:block}.tlcap{font-size:11.5px;color:var(--mut);margin:0 0 6px;display:flex;gap:14px;flex-wrap:wrap}
.leg{display:flex;gap:6px;flex-wrap:wrap;margin:6px 0 8px}.lg{border:1px solid var(--line);background:#fff;border-radius:20px;padding:3px 10px 3px 6px;font:12.5px inherit;cursor:pointer;color:var(--ink)}.lg b{display:inline-block;width:12px;height:12px;border-radius:50%;vertical-align:-1px;margin-right:5px}.lg.sel{background:var(--ink);color:#fff;border-color:var(--ink)}.lg.dim{opacity:.45}
#map{height:60vh;min-height:420px;border:1px solid var(--line);border-radius:10px}
.leg2{display:flex;gap:14px;flex-wrap:wrap;font-size:12px;color:var(--mut);margin:8px 0;align-items:center}.leg2 b{display:inline-block;width:12px;height:12px;border-radius:50%;vertical-align:-1px;margin-right:4px}
#todos{margin-left:auto;border:1px solid var(--line);background:#fff;border-radius:8px;padding:5px 10px;font:12.5px inherit;cursor:pointer}
.tw{overflow-x:auto;background:#fff;border:1px solid var(--line);border-radius:10px}table{width:100%;border-collapse:collapse;font-size:12.8px}
th,td{padding:6px 9px;border-bottom:1px solid #eef2f7;text-align:left;white-space:nowrap;border-right:1px solid #f1f4f8}th{background:var(--soft);font-size:10.5px;text-transform:uppercase;color:var(--mut);letter-spacing:.03em}
td.num,th.num{text-align:right;font-variant-numeric:tabular-nums}tr[data-n]{cursor:pointer}tr.sel td{background:#e7f0ff}tr.dim{opacity:.4}td.aviso{color:var(--mut);font-size:12px;white-space:normal;max-width:360px}
.rol{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:6px;vertical-align:-1px}
.nm{width:22px;height:22px;border-radius:50%;color:#fff;font:700 11px/20px system-ui,sans-serif;text-align:center;border:2px solid #fff;box-shadow:0 0 0 1px #12233b;box-sizing:border-box}.nm.sq{border-radius:4px}
.blk{cursor:pointer}.blk.dim{opacity:.3}.blk.sel rect{stroke:#12233b;stroke-width:2}
td.lug{white-space:normal;min-width:150px;max-width:280px}td small{display:block;color:var(--mut);font-size:11.5px;line-height:1.3;white-space:normal}
tr.hueco td{background:repeating-linear-gradient(135deg,#f6f8fb 0 6px,#eef2f7 6px 12px);color:var(--mut)}
.ayuda{margin:0 0 10px;font-size:12.5px;color:var(--mut);max-width:1100px}.ayuda summary{cursor:pointer;color:#233246;font-weight:600}.ayuda ul{margin:6px 0 0;padding-left:18px;line-height:1.5}
@media print{#map{height:70vh}#todos{display:none}}</style></head><body><div class="wrap">
<h1>@@TITLE@@</h1><p class="sub">@@SUB@@</p>
<details class="ayuda"><summary>Cómo se lee esta página</summary><ul>@@AYUDA@@</ul></details>
<div class="chips" id="chips"></div>
<div class="tlwrap"><svg id="tl"></svg><p class="tlcap"><span>Línea de tiempo del día (hora de Madrid): arriba cada viaje con su número; debajo las paradas (verde cargando, azul descargando, naranja espera dentro de un viaje, gris fuera de viaje; rayado = sin señal del localizador); la barra fina es la jornada. Pincha un viaje para resaltarlo.</span></p></div>
<div class="leg" id="leg"></div>
<div id="map"></div>
<div class="leg2"><span><b style="background:#16a34a"></b>parada cargando</span><span><b style="background:#2563eb"></b>parada descargando</span><span><b style="background:#d97706"></b>espera dentro de un viaje</span><span><b style="background:#9ca3af"></b>parada fuera de viaje · traza gris = sin viaje asignado</span><span>Círculo numerado = dónde carga cada viaje; cuadrado = dónde descarga. El tamaño de la parada es su duración.</span><button id="todos" hidden>Ver todos los viajes</button></div>
<h2>Viajes del día</h2>
<div class="tw"><table><thead><tr><th>Nº</th><th>Albarán cantera</th><th>Según el albarán</th><th>Carga que ve el GPS</th><th>Descarga que ve el GPS</th><th>Inicio → fin del viaje</th><th class="num">Km</th><th class="num">Cargado / vacío</th><th class="num">Litros</th><th class="num">Min</th><th class="num">Conduc.</th><th class="num">Espera</th><th>Chofer</th><th>Método / conf.</th><th>Aviso</th></tr></thead><tbody id="tvb"></tbody></table></div>
<h2>Paradas y esperas del día</h2>
<div class="tw"><table><thead><tr><th>Hora</th><th class="num">Min</th><th>Lugar (GPS)</th><th>Viaje</th><th>Qué hacía</th></tr></thead><tbody id="tpb"></tbody></table></div>
</div><script>
const META=@@META@@,V=@@V@@,L0=@@L@@,P=@@P@@,J=@@J@@,H=@@H@@;
const ROL={carga:'#16a34a',descarga:'#2563eb',espera:'#d97706',fuera:'#9ca3af'},ROLTXT={carga:'cargando',descarga:'descargando',espera:'espera dentro del viaje',fuera:'fuera de viaje'};
const $=id=>document.getElementById(id);
const hm=s=>s==null?'':new Date(s*1000).toLocaleTimeString('es-ES',{hour:'2-digit',minute:'2-digit',timeZone:'Europe/Madrid'});
const f=(v,n=0)=>v==null?'':Number(v).toLocaleString('es-ES',{minimumFractionDigits:n,maximumFractionDigits:n});
$('chips').innerHTML=[['Albaranes',META.n],['Viajes medidos',META.med],['Km del día (medidos)',f(META.km,1)],['Litros (medidos)',f(META.lit,1)],['Jornada',META.jor]].map(([k,v])=>`<span class="chip"><small>${k}</small><b>${v}</b></span>`).join('');
const map=L.map('map');L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}',{maxZoom:19,attribution:'© Esri · © OpenStreetMap'}).addTo(map);
const lines=[],stops=[],marks=[],b=[];
for(const [c,n,pts] of L0){const pl=L.polyline(pts,{color:c,weight:4,opacity:.85}).addTo(map);pl.n=n;lines.push(pl);if(n)pl.on('click',()=>sel(n));for(const p of pts)b.push(p);}
for(const p of P){const [lat,lon,ti,to,txt,min,col,n,lugar,rol]=p;const r=Math.max(6,Math.min(17,5+Math.sqrt(min)*1.7));const m=L.circleMarker([lat,lon],{radius:r,color:'#12233b',weight:1,fillColor:ROL[rol]||col,fillOpacity:.9}).addTo(map);m.bindTooltip(`${txt} · ${min} min · ${lugar||'lugar no conocido'}${n?' · viaje '+n+' ('+ROLTXT[rol]+')':' · fuera de viaje'}`);m.n=n;stops.push(m);}
for(const v of V){if(!v.n)continue;const pc=v.posc||v.pos0;if(pc){const m=L.marker(pc,{icon:L.divIcon({className:'',html:`<div class="nm" style="background:${v.col}">${v.n}</div>`,iconSize:[22,22],iconAnchor:[11,11]}),zIndexOffset:1000}).addTo(map).bindTooltip(`Viaje ${v.n}: carga en ${cSitio(v)}`).on('click',()=>sel(v.n));m.n=v.n;marks.push(m);}
 if(v.posd){const m=L.marker(v.posd,{icon:L.divIcon({className:'',html:`<div class="nm sq" style="background:${v.col}">${v.n}</div>`,iconSize:[22,22],iconAnchor:[11,11]}),zIndexOffset:1000}).addTo(map).bindTooltip(`Viaje ${v.n}: descarga en ${dSitio(v)}`).on('click',()=>sel(v.n));m.n=v.n;marks.push(m);}}
function encuadrar(){if(b.length)map.fitBounds(b,{padding:[20,20]});}
encuadrar();
// abierta sin tamaño (pestaña oculta, vista previa) Leaflet se queda en el zoom maximo: se encuadra cuando el mapa lo tenga
if(!$('map').clientWidth&&window.ResizeObserver){const ro=new ResizeObserver(()=>{if($('map').clientWidth){map.invalidateSize();encuadrar();ro.disconnect();}});ro.observe($('map'));}
// Carga y descarga: el sitio que VE EL GPS (el del albaran solo si la parada cae en su radio: cok/dok)
function cSitio(v){return v.cl||(v.tc?'lugar no conocido':'carga no vista');}
function dSitio(v){return v.dl||(v.td?'lugar no conocido':'descarga no vista');}
$('leg').innerHTML=V.filter(v=>v.n).map(v=>`<button class="lg" data-n="${v.n}"><b style="background:${v.col}"></b>${v.n} · ${cSitio(v)} → ${dSitio(v)}${v.mas1?' (+1)':''}</button>`).join('');
function timeline(){const svg=$('tl');const W=Math.max(600,svg.clientWidth||1000);svg.setAttribute('viewBox',`0 0 ${W} 104`);
 const med=V.filter(v=>v.ini_s);const ini=[...J.map(j=>j[0]),...med.map(v=>v.ini_s),...P.map(p=>p[2])],fin=[...J.map(j=>j[1]),...med.map(v=>v.fin_s),...P.map(p=>p[3])];
 if(!ini.length){svg.innerHTML='';return;}
 const t0=Math.min(...ini)-900,t1=Math.max(...fin)+900;const X=t=>W*(t-t0)/(t1-t0),Xc=t=>X(Math.min(Math.max(t,t0),t1));
 let s='<defs><pattern id="rayas" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><rect width="3" height="6" fill="#c3ccd8"/></pattern></defs>';
 for(let t=t0-(t0%3600);t<=t1;t+=3600){const x=X(t);if(x<0)continue;s+=`<line x1="${x}" x2="${x}" y1="6" y2="94" stroke="#e2e9f2"/><text x="${x+2}" y="102" font-size="9.5" fill="#5b6b7f">${hm(t)}</text>`;}
 for(const j of J)s+=`<rect x="${Xc(j[0])}" y="84" width="${Math.max(1,Xc(j[1])-Xc(j[0]))}" height="6" fill="#c7d7f0" rx="2"><title>jornada ${hm(j[0])} → ${hm(j[1])} (${j[3]} h${j[2]?', nocturna':''})</title></rect>`;
 for(const v of med){const x=Xc(v.ini_s),w=Math.max(2,Xc(v.fin_s)-x);s+=`<g class="blk" data-n="${v.n}"><rect x="${x}" y="12" width="${w}" height="32" fill="${v.col}" rx="3"/>${w>16?`<text x="${x+w/2}" y="33" text-anchor="middle" font-size="12.5" font-weight="700" fill="#fff">${v.n}</text>`:''}<title>Viaje ${v.n}: ${cSitio(v)} → ${dSitio(v)} · ${hm(v.ini_s)} → ${hm(v.fin_s)}${v.km!=null?' · '+f(v.km,1)+' km recorridos':''}</title></g>`;}
 for(const p of P){const x=Xc(p[2]),w=Math.max(1.5,Xc(p[3])-x);s+=`<rect x="${x}" y="52" width="${w}" height="20" fill="${ROL[p[9]]}" rx="2"><title>${p[4]} · ${p[5]} min · ${p[8]||'lugar no conocido'}</title></rect>`;}
 for(const h of H){const x=Xc(h[0]),w=Math.max(2,Xc(h[1])-x);s+=`<rect x="${x}" y="52" width="${w}" height="20" fill="url(#rayas)" stroke="#9ca3af" stroke-width=".6"><title>${h[2]} · sin señal del localizador (${h[3]})</title></rect>`;}
 svg.innerHTML=s;svg.querySelectorAll('.blk').forEach(g=>g.addEventListener('click',()=>sel(+g.dataset.n)));if(cur)marcar();}
function tablas(){$('tvb').innerHTML=V.map(v=>{
  const alb=`${v.on} → ${v.dn}${v.mismo?'<small>el albarán repite el lugar de carga: no dice dónde se descarga</small>':''}`;
  const car=v.tc?`${hm(v.tc)} → ${hm(v.tcf)}<small>${cSitio(v)}${v.ckm!=null?' · a '+f(v.ckm,1)+' km del lugar del albarán':''}</small>`:'';
  const des=v.td?`${hm(v.td)}${v.tdf?' → '+hm(v.tdf):''}<small>${dSitio(v)}${v.dc!=null?' · a '+f(v.dc,1)+' km en línea recta de la carga':''}${v.dkm!=null?' · a '+f(v.dkm,1)+' km del destino del albarán':''}${v.n&&v.conf&&v.conf!=='alta'?' · candidata (confianza '+v.conf+')':''}</small>`:'';
  const cv=v.kmc!=null?f(v.kmc,1)+' / '+f(v.kmv,1)+(v.sc!=null?(v.sc>0?'<small>sin clasificar '+f(v.sc,1)+'</small>':'<small>cargado + vacío superan el total en '+f(-v.sc,1)+'</small>'):''):'';
  return `<tr data-n="${v.n||''}" style="border-left:6px solid ${v.n?v.col:'#9ca3af'}"><td>${v.n||'—'}</td><td>${v.alb}</td><td class="lug">${alb}</td><td class="lug">${car}</td><td class="lug">${des}</td><td>${v.ini_s?hm(v.ini_s)+' → '+hm(v.fin_s)+(v.mas1?' (+1)':''):(v.met==='dia'?'repartido (sin hora)':'')}</td><td class="num">${f(v.km,1)}</td><td class="num">${cv}</td><td class="num">${f(v.lit,1)}</td><td class="num">${f(v.min)}</td><td class="num">${f(v.cond)}</td><td class="num">${f(v.esp)}</td><td>${v.chofer||''}</td><td>${v.met||''}${v.conf?' / '+v.conf:''}</td><td class="aviso">${v.aviso||''}</td></tr>`;}).join('');
 const filas=P.map(p=>({t:p[2],h:`<tr data-n="${p[7]||''}"><td>${p[4]}</td><td class="num">${p[5]}</td><td>${p[8]||'<i>lugar no conocido</i>'}</td><td>${p[7]?'<b style="color:'+p[6]+'">viaje '+p[7]+'</b>':'—'}</td><td><span class="rol" style="background:${ROL[p[9]]}"></span>${ROLTXT[p[9]]}</td></tr>`}))
  .concat(H.map(h=>({t:h[0],h:`<tr class="hueco"><td>${h[2]}</td><td class="num">—</td><td>${h[4]}</td><td>—</td><td>sin señal del localizador (${h[3]}): no se sabe si estuvo parado</td></tr>`})))
  .sort((a,c)=>a.t-c.t);
 $('tpb').innerHTML=filas.map(x=>x.h).join('');
 document.querySelectorAll('#tvb tr,#tpb tr,.lg').forEach(el=>el.addEventListener('click',()=>{const n=+el.dataset.n;if(n)sel(n);}));}
let cur=0;
function marcar(){document.querySelectorAll('[data-n]').forEach(el=>{const n=+el.dataset.n;el.classList.toggle('sel',Boolean(cur)&&n===cur);el.classList.toggle('dim',Boolean(cur)&&n!==cur);});}
function sel(n){cur=(!n||n===cur)?0:n;
 lines.forEach(pl=>pl.setStyle({opacity:cur?(pl.n===cur?1:.15):.85,weight:cur&&pl.n===cur?6:4}));
 stops.forEach(m=>m.setStyle({fillOpacity:cur?(m.n===cur?.95:.12):.9,opacity:cur?(m.n===cur?1:.15):1}));
 marks.forEach(m=>m.setOpacity(cur?(m.n===cur?1:.25):1));
 marcar();$('todos').hidden=!cur;
 if(cur){const pts=[];for(const pl of lines)if(pl.n===cur)pts.push(...pl.getLatLngs());if(pts.length)map.fitBounds(pts,{padding:[30,30]});}else encuadrar();}
$('todos').onclick=()=>sel(0);
tablas();timeline();window.addEventListener('resize',timeline);
const h=location.hash.match(/v=(\d+)/);if(h){const v=V.find(x=>x.od===+h[1]&&x.n);if(v)sel(v.n);}
</script></body></html>"""


def ep(iso):
    """'YYYY-MM-DDTHH:MM' en hora de Madrid -> epoch (UTC)."""
    if not iso:
        return None
    d = dt.datetime.strptime(iso[:16], "%Y-%m-%dT%H:%M")
    u = calendar.timegm(d.timetuple())
    return u - t2.madrid_offset(u - 3600)


def fecha_larga(fecha):
    d = dt.date.fromisoformat(fecha)
    return "%s %d de %s de %d" % (DIAS[d.weekday()], d.day, MESES[d.month - 1], d.year)


class Lugares:
    """Nombres de lugar por codigo (maestro GesRuta + geocode) e indice espacial para rotular paradas."""
    def __init__(self, nombres, coords):
        self.nombres = nombres or {}
        self.coords = coords or {}                                   # (casa, codigo) -> {lat, lon, fuente, ...}
        self.grid = collections.defaultdict(list)
        for (casa, cod), c in (coords or {}).items():
            self.grid[(int(c["lat"] * 100), int(c["lon"] * 100))].append((c["lat"], c["lon"], cod, (c.get("nombre") or "")))
            if c.get("nombre") and cod not in self.nombres:
                self.nombres[cod] = {"nom": c["nombre"], "loc": "", "pro": ""}

    def nombre(self, cod):
        x = self.nombres.get(cod) if cod else None
        if not x:
            return cod or "—"
        nom = (x.get("nom") or "").strip() or cod
        loc = (x.get("loc") or "").strip()
        return nom + (" (%s)" % loc if loc and loc.upper() not in nom.upper() else "")

    def cerca(self, lat, lon):
        """Lugar conocido mas cercano: a menos de RADIO_LUGAR_KM su nombre; hasta 2 km 'cerca de ...' (canteras y obras son
        grandes y la coordenada del maestro es un punto); mas lejos, None (lugar no conocido)."""
        gi, gj = int(lat * 100), int(lon * 100)
        mejor = None
        for di in (-2, -1, 0, 1, 2):
            for dj in (-2, -1, 0, 1, 2):
                for (la, lo, cod, nom) in self.grid.get((gi + di, gj + dj), ()):
                    d = t2.v1.hav((lat, lon), (la, lo))
                    if d <= 2.0 and (mejor is None or d < mejor[0]):
                        mejor = (d, cod)
        if not mejor:
            return None
        return self.nombre(mejor[1]) if mejor[0] <= RADIO_LUGAR_KM else "cerca de " + self.nombre(mejor[1])

    def sitio(self, pos, casa, cod):
        """Donde esta la carga o la descarga que ve el GPS: (nombre, confirmado, km al lugar del albaran).
        confirmado = la parada cae dentro del radio del lugar del albaran (el mismo radio con que triangula triangular_v1:
        1 km el maestro, 5 km un centro de pueblo) y el nombre es el del albaran. Si no, el lugar conocido mas cercano segun
        el GPS (o None) y a cuantos km queda el del albaran (None si no tiene coordenada o no se pasa codigo)."""
        c = self.coords.get((casa, cod)) if cod else None
        dist = None
        if c is not None:
            dist = round(t2.v1.hav(pos, (c["lat"], c["lon"])), 2)
            if t2.v1.cerca({"lat": pos[0], "lon": pos[1]}, c, c["fuente"], c.get("radio_m")):
                return self.nombre(cod), True, dist
        return self.cerca(pos[0], pos[1]), False, dist


def partir_parada(p, pts, ts):
    """Una parada de triangular_v2 partida por los huecos SIN SEÑAL (>= HUECO_S sin posicion) y por los saltos de sitio
    (> SALTO_KM) que haya dentro: triangular_v2 junta puntos parados aunque entre ellos pasen dias sin señal (1895CNR el
    09/01/2026: «17:22 -> 16/01 08:47, 9.565 min» y situada en Bertoa, cuando el ultimo punto del 9 esta en Sabon a las
    19:39 y el siguiente aparece el 16 a 17,5 km). Devuelve [(t_in, t_out, lat, lon)]: la parada tal cual si no hay cortes;
    si los hay, los trozos de DWELL_S o mas con la mediana de sus puntos. Las paradas de Locatel (un punto) van tal cual."""
    i0, i1 = bisect.bisect_left(ts, p["t_in"]), bisect.bisect_right(ts, p["t_out"])
    grupo = [q for q in pts[i0:i1] if q.get("f") != "locatel"]
    if len(grupo) < 2:
        return [(p["t_in"], p["t_out"], p["lat"], p["lon"])]
    trozos, cur = [], [grupo[0]]
    for a_, b_ in zip(grupo, grupo[1:]):
        if b_["t"] - a_["t"] >= HUECO_S or t2.v1.hav((a_["lat"], a_["lon"]), (b_["lat"], b_["lon"])) > SALTO_KM:
            trozos.append(cur)
            cur = [b_]
        else:
            cur.append(b_)
    trozos.append(cur)
    if len(trozos) == 1:
        return [(p["t_in"], p["t_out"], p["lat"], p["lon"])]
    return [(g[0]["t"], g[-1]["t"], statistics.median(q["lat"] for q in g), statistics.median(q["lon"] for q in g))
            for g in trozos if g[-1]["t"] - g[0]["t"] >= t2.DWELL_S]


def huecos_sin_senal(pts, desde, hasta):
    """Tramos sin posicion de HUECO_S o mas que EMPIEZAN en [desde, hasta): [(t0, t1, punto_antes, punto_despues)]. Un punto
    de Locatel con parada_min cubre su parada (Locatel la trae en un solo punto)."""
    out = []
    for a_, b_ in zip(pts, pts[1:]):
        if not (desde <= a_["t"] < hasta):
            continue
        cubre = a_["t"] + int((a_.get("parada_min") or 0) * 60) if a_.get("f") == "locatel" else a_["t"]
        if b_["t"] - cubre >= HUECO_S:
            out.append((cubre, b_["t"], a_, b_))
    return out


def dia_hora(t, fecha):
    """'HH:MM' si t es de ese dia (hora de Madrid); si no, 'dd/mm HH:MM'."""
    s = t2.iso_min(t)
    return s[11:] if s[:10] == fecha else "%s/%s %s" % (s[8:10], s[5:7], s[11:])


def duracion_txt(seg):
    if seg >= 86400:
        return ("%.1f días" % (seg / 86400.0)).replace(".", ",")
    if seg >= 3600:
        return "%d h %02d min" % (seg // 3600, (seg % 3600) // 60)
    return "%d min" % (seg // 60)


def km_txt(km):
    return ("%.1f" % km).replace(".", ",")


def preparar_flujo(pts_mat, rest_s):
    """Indice, paradas y jornadas del camion; se reutilizan para todos sus dias."""
    par = t2.paradas_flujo(pts_mat)
    return {'ts': [q['t'] for q in pts_mat], 'paradas': par,
            'jornadas': t2.jornadas_de(pts_mat, par, rest_s)}


def render_dia(mat, fecha, viajes, pts_mat, dg_dia, rest_s, paso_s, lug=None, contexto=None):
    """HTML de un dia. pts_mat = flujo continuo del camion. Devuelve (html, n_medidos) o None si no hay traza."""
    lug = lug or Lugares({}, {})
    viajes = [x for x in viajes if not x.get("espejo_de")]           # el espejo intercompania no se repite
    viajes = sorted(viajes, key=lambda x: (x["t_ini"] or "z", x.get("orden_dia") or 0))
    if not pts_mat:
        return None
    contexto = contexto if contexto is not None else preparar_flujo(pts_mat, rest_s)
    par = contexto['paradas']
    jor_all = contexto['jornadas']
    jor = [j for j in jor_all if j["fecha"] == fecha or (j["nocturna"] and t2.fecha_de(j["fin"]) == fecha)]
    if jor:
        w0, w1 = min(j["c0"] for j in jor), max(j["c1"] for j in jor)
    else:
        d0 = dt.date.fromisoformat(fecha)
        w0 = int(dt.datetime.combine(d0, dt.time.min).timestamp()) - 7200; w1 = w0 + 86400 + 7200
    med = [x for x in viajes if x["t_ini"] and x["t_fin"]]
    for x in med:                                                    # los largos cruzan dias: la ventana los abarca enteros
        w0, w1 = min(w0, ep(x["t_ini"]) - 600), max(w1, ep(x["t_fin"]) + 600)
    seg = pts_mat[bisect.bisect_left(contexto['ts'], w0):bisect.bisect_right(contexto['ts'], w1)]
    if not seg:
        return None
    ts = [q["t"] for q in seg]

    def pos_at(t):
        if t is None:
            return None
        k = min(max(bisect.bisect_left(ts, t), 0), len(seg) - 1)
        return [round(seg[k]["lat"], 5), round(seg[k]["lon"], 5)]
    V, ciclos, lado = [], [], {}
    n = 0
    for x in viajes:
        medido = bool(x["t_ini"] and x["t_fin"])
        if medido:
            n += 1
        col = PALETA[(n - 1) % len(PALETA)] if medido else "#9ca3af"
        ini_s, fin_s = (ep(x["t_ini"]), ep(x["t_fin"])) if medido else (None, None)
        tc, tcf, td, tdf = ep(x.get("t_carga")), ep(x.get("t_carga_fin")), ep(x.get("t_descarga")), ep(x.get("t_descarga_fin"))
        if medido:
            ciclos.append((ini_s, fin_s, col, n))
        casa = t2.v1.casa_norm(x.get("empresa"))
        # el albaran que repite el lugar de carga como destino (hormigon: la obra no tiene codigo) NO dice donde se descarga
        mismo = bool(x["origen"]) and x["origen"] == x["destino"]
        if medido:
            lado[n] = (casa, x["origen"], None if mismo else x["destino"])
        posc, posd = (pos_at(tc) if tc else None), (pos_at(td) if td else None)
        cs = lug.sitio(posc, casa, x["origen"]) if posc else (None, False, None)
        ds = lug.sitio(posd, casa, None if mismo else x["destino"]) if posd else (None, False, None)
        resto = None                                                  # km que no son ni cargado ni vacio: a la vista
        if x["km"] is not None and x.get("km_cargado") is not None and x.get("km_vacio") is not None:
            resto = round(x["km"] - x["km_cargado"] - x["km_vacio"], 2)
            if abs(resto) < 0.05:
                resto = None
        V.append({"n": n if medido else None, "od": x.get("orden_dia"), "col": col, "alb": x["cantera"], "o": x["origen"], "d": x["destino"],
                  "on": lug.nombre(x["origen"]), "dn": lug.nombre(x["destino"]), "ini_s": ini_s, "fin_s": fin_s, "tc": tc, "tcf": tcf, "td": td, "tdf": tdf,
                  "km": x["km"], "kmc": x.get("km_cargado"), "kmv": x.get("km_vacio"), "lit": x.get("litros_calibrados") if x.get("litros_calibrados") is not None else x.get("litros"),
                  "min": None if x["duracion_min"] is None else int(x["duracion_min"]), "cond": None if x.get("min_conduccion") is None else int(x["min_conduccion"]),
                  "esp": None if x.get("min_espera") is None else int(x["min_espera"]), "chofer": x.get("chofer_tacografo") or "", "met": x["metodo"], "conf": x["confianza"] or "",
                  "aviso": x["motivo"] or "", "mas1": bool(medido and x["t_fin"][:10] != x["t_ini"][:10]),
                  "mismo": mismo, "cl": cs[0], "ckm": None if cs[1] else cs[2], "dl": ds[0], "dkm": None if ds[1] else ds[2],
                  "dc": round(t2.v1.hav(posc, posd), 2) if (posc and posd) else None, "sc": resto,
                  "pos0": pos_at(ini_s), "posc": posc, "posd": posd})

    def viaje_de(t):
        for a_, b_, c, k in ciclos:
            if a_ <= t <= b_:
                return c, k
        return "#9ca3af", 0
    # polilineas por viaje, adelgazadas: 1 punto cada paso_s y sin repetir puntos parados (misma posicion redondeada)
    lineas, cur, curk, ult_t, ult_p = [], [], None, None, None
    for q in seg:
        p = [round(q["lat"], 4), round(q["lon"], 4)]
        ck = viaje_de(q["t"])
        if ck != curk and cur:
            lineas.append((curk[0], curk[1], cur)); cur = [cur[-1]]
            ult_t = None
        curk = ck
        if ult_t is not None and (q["t"] - ult_t) < paso_s and p == ult_p:
            continue
        cur.append(p); ult_t, ult_p = q["t"], p
    if cur and curk:
        lineas.append((curk[0], curk[1], cur))
    # paradas: viaje al que pertenecen, que hacia (carga / descarga / espera / fuera) y el sitio que VE EL GPS; partidas por los
    # huecos sin señal y recortadas al dia (hasta las 24:00, o al fin de la jornada o del viaje si acaban despues): lo que
    # sigue despues se dice, no se suma
    fin_dia = ep((dt.date.fromisoformat(fecha) + dt.timedelta(days=1)).isoformat() + "T00:00")
    f1 = max(w1, fin_dia)
    P = []
    vmed = [v for v in V if v["n"]]
    for p0 in par:
        if p0["t_out"] < w0 or p0["t_in"] > f1:
            continue
        for (ti, to, la, lo) in partir_parada(p0, pts_mat, contexto['ts']):
            if not (w0 <= ti <= f1):
                continue
            tov = min(to, f1)
            col, k, rol, lugar = "#9ca3af", 0, "fuera", None
            for v in vmed:
                if v["ini_s"] <= ti <= v["fin_s"] or v["ini_s"] <= to <= v["fin_s"]:
                    col, k = v["col"], v["n"]
                    casa, o_, d_ = lado[v["n"]]
                    if v["tc"] and ti <= (v["tcf"] or v["tc"]) and to >= v["tc"]:
                        rol, lugar = "carga", lug.sitio([la, lo], casa, o_)[0]
                    elif v["td"] and ti <= (v["tdf"] or v["td"]) + 60 and to >= v["td"]:
                        rol, lugar = "descarga", lug.sitio([la, lo], casa, d_)[0]
                    else:
                        rol = "espera"
                    break
            txt = dia_hora(ti, fecha) + "–" + ("24:00" if (to > f1 and f1 == fin_dia) else dia_hora(tov, fecha))
            if to > f1:
                txt += " (sigue hasta el %s)" % dia_hora(to, "")
            P.append([round(la, 5), round(lo, 5), ti, tov, txt, int((tov - ti) // 60), col, k, lugar or lug.cerca(la, lo), rol])
    # huecos sin señal que empiezan en el dia (el que acaba otro dia tambien: se toma el primer punto de despues)
    k0, k1 = bisect.bisect_left(contexto['ts'], w0), bisect.bisect_right(contexto['ts'], f1)
    H = []
    for (h0, h1, a_, b_) in huecos_sin_senal(pts_mat[k0:min(k1 + 1, len(pts_mat))], w0, f1):
        salto = t2.v1.hav((a_["lat"], a_["lon"]), (b_["lat"], b_["lon"]))
        if salto > SALTO_KM:
            donde = lug.cerca(b_["lat"], b_["lon"])
            rea = "vuelve a dar posición a %s km, %s" % (km_txt(salto), (donde if donde and donde.startswith("cerca de") else ("en " + donde) if donde else "en un lugar no conocido"))
        else:
            rea = "vuelve a dar posición en el mismo sitio"
        H.append([h0, h1, "%s → %s" % (dia_hora(h0, fecha), dia_hora(h1, fecha)), duracion_txt(h1 - h0), rea])
    J = [[j["ini"], j["fin"], bool(j["nocturna"]), j["horas"]] for j in jor]
    dg = {j_["ini"]: j_ for j_ in (dg_dia or [])}
    jtxt = "; ".join("%s → %s (%.1f h%s%s)" % (t2.iso_min(j["ini"])[11:], t2.iso_min(j["fin"])[11:], j["horas"], ", nocturna" if j["nocturna"] else "",
                     (", %s, %d ciclos, %d asignados" % (dg[t2.iso_min(j["ini"])]["modo"], dg[t2.iso_min(j["ini"])]["ciclos"], dg[t2.iso_min(j["ini"])]["asignados"])) if t2.iso_min(j["ini"]) in dg else "") for j in jor) or "sin jornada"
    meta = {"mat": mat, "fecha": fecha, "n": len(viajes), "med": len(vmed), "km": round(sum(v["km"] or 0 for v in vmed), 1), "lit": round(sum(v["lit"] or 0 for v in vmed), 1), "jor": jtxt}
    titulo = "%s · %s · %d albaranes de GesRuta" % (mat, fecha_larga(fecha), len(viajes))
    sub = ("Traza real del localizador. Cada color es un viaje medido del triangulado (de su hora de inicio a la de fin); gris = sin viaje asignado. "
           "Jornada(s): %s. Hora de Madrid.") % jtxt
    html = (PLANTILLA.replace("@@TITLE@@", titulo).replace("@@SUB@@", sub)
            .replace("@@AYUDA@@", "".join("<li>%s</li>" % s_ for s_ in AYUDA))
            .replace("@@META@@", json.dumps(meta, ensure_ascii=False, separators=(",", ":")))
            .replace("@@V@@", json.dumps(V, ensure_ascii=False, separators=(",", ":")))
            .replace("@@L@@", json.dumps(lineas, separators=(",", ":")))
            .replace("@@P@@", json.dumps(P, ensure_ascii=False, separators=(",", ":")))
            .replace("@@J@@", json.dumps(J, separators=(",", ":")))
            .replace("@@H@@", json.dumps(H, ensure_ascii=False, separators=(",", ":"))))
    return html, len(vmed)


def simplificar(pts, tol_m=12.0):
    """Douglas-Peucker sobre [[lat, lon], ...] en metros (proyeccion local): quita los puntos que se desvian menos de tol_m de
    la recta entre sus vecinos conservados. Conserva los extremos. Una carretera sigue dibujada; los puntos redundantes, fuera."""
    n = len(pts)
    if n <= 2:
        return pts
    lat0 = math.radians(sum(p[0] for p in pts) / n)
    kx, ky = 111320.0 * math.cos(lat0), 110540.0
    xy = [(p[1] * kx, p[0] * ky) for p in pts]
    keep = [False] * n; keep[0] = keep[-1] = True
    pila = [(0, n - 1)]
    while pila:
        i, j = pila.pop()
        if j <= i + 1:
            continue
        x1, y1 = xy[i]; x2, y2 = xy[j]; dx, dy = x2 - x1, y2 - y1; l2 = dx * dx + dy * dy
        peor, k_ = -1.0, -1
        for k in range(i + 1, j):
            x0, y0 = xy[k]
            if l2 == 0:
                d = math.hypot(x0 - x1, y0 - y1)
            else:
                t = max(0.0, min(1.0, ((x0 - x1) * dx + (y0 - y1) * dy) / l2))
                d = math.hypot(x0 - (x1 + t * dx), y0 - (y1 + t * dy))
            if d > peor:
                peor, k_ = d, k
        if peor > tol_m:
            keep[k_] = True; pila.append((i, k_)); pila.append((k_, j))
    return [pts[k] for k in range(n) if keep[k]]


def trazas_de_viajes(mat, viajes, pts_mat, ts, tol_m=12.0):
    """Una fila por viaje MEDIDO (con hora de inicio y fin) del dia: clave, tiempos, posiciones de carga y descarga, medidas y
    el recorrido real simplificado (ciclo entero y tramo cargado). pts_mat ordenado por t; ts = sus tiempos (para bisect)."""
    out = []
    for x in viajes:
        if not (x.get("t_ini") and x.get("t_fin")):
            continue
        a_, b_ = ep(x["t_ini"]), ep(x["t_fin"])
        ciclo = pts_mat[bisect.bisect_left(ts, a_):bisect.bisect_right(ts, b_)]
        if len(ciclo) < 2:
            continue

        def pos(t):
            if t is None:
                return None
            k = min(max(bisect.bisect_left(ts, t), 0), len(pts_mat) - 1)
            return [round(pts_mat[k]["lat"], 5), round(pts_mat[k]["lon"], 5)]
        tc, tcf, td = ep(x.get("t_carga")), ep(x.get("t_carga_fin")), ep(x.get("t_descarga"))
        s0 = tcf or tc
        car = [q for q in ciclo if s0 <= q["t"] <= td] if (s0 and td and td > s0) else []
        tdf = ep(x.get("t_descarga_fin")) or td       # la VUELTA EN VACÍO: de salir de la descarga al fin del viaje
        vac = [q for q in ciclo if q["t"] >= tdf] if tdf else []
        lit = x.get("litros_calibrados") if x.get("litros_calibrados") is not None else x.get("litros")
        out.append({"empresa": x.get("empresa"), "viaje": x.get("viaje"), "cantera": x.get("cantera"), "mat": mat, "fecha": x.get("fecha"),
                    "orden_dia": x.get("orden_dia"), "tipo": x.get("tipo"), "espejo_de": x.get("espejo_de"), "origen": x.get("origen"), "destino": x.get("destino"),
                    "t_ini": x.get("t_ini"), "t_fin": x.get("t_fin"), "t_carga": x.get("t_carga"), "t_carga_fin": x.get("t_carga_fin"),
                    "t_descarga": x.get("t_descarga"), "t_descarga_fin": x.get("t_descarga_fin"), "posc": pos(tc), "posd": pos(td),
                    "km": x.get("km"), "km_cargado": x.get("km_cargado"), "km_vacio": x.get("km_vacio"), "litros": lit,
                    "min": x.get("duracion_min"), "min_conduccion": x.get("min_conduccion"), "min_espera": x.get("min_espera"),
                    "metodo": x.get("metodo"), "confianza": x.get("confianza"),
                    "cargado": simplificar([[round(q["lat"], 5), round(q["lon"], 5)] for q in car], tol_m) or None,
                    "vacio": simplificar([[round(q["lat"], 5), round(q["lon"], 5)] for q in vac], tol_m) or None,
                    "ciclo": simplificar([[round(q["lat"], 5), round(q["lon"], 5)] for q in ciclo], tol_m)})
    return out


def cargar_lugares(geocode):
    """Nombres (maestro GesRuta global + geocode) y coordenadas (GesRuta + geocode) para rotular; nunca escribe en el origen."""
    nombres = {}
    if cargar_lugares_global is not None:
        try:
            nombres = cargar_lugares_global(t2.v1.GESRUTA)
        except Exception as e:  # noqa: BLE001
            print("Aviso: sin maestro de lugares de GesRuta (%s); se usan los codigos" % e, file=sys.stderr)
    geo = {}
    if geocode and os.path.isfile(geocode):
        try:
            for k, x in json.load(open(geocode, encoding="utf-8")).items():
                if isinstance(x, dict) and x.get("lat") is not None and x.get("lon") is not None:
                    casa, _, cod = k.partition("|")
                    geo[(t2.v1.casa_norm(casa), cod.strip())] = {"lat": float(x["lat"]), "lon": float(x["lon"]), "fuente": t2.v1.fuente_de(x), "nombre": x.get("nombre")}
        except (OSError, ValueError) as e:
            print("Aviso: geocode ilegible (%s)" % e, file=sys.stderr)
    try:
        ges = t2.v1.coords_gesruta()
    except Exception as e:  # noqa: BLE001
        print("Aviso: sin coordenadas de GesRuta (%s)" % e, file=sys.stderr)
        ges = {}
    return Lugares(nombres, t2.v1.mejor(ges, geo))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--v2", required=True); ap.add_argument("--diag", default="")
    ap.add_argument("--wialon", action="append", default=[]); ap.add_argument("--locatel", action="append", default=[])
    ap.add_argument("--geocode", default="", help="coords_lugares_por_casa.json (nombres y coordenadas geocodificadas)")
    ap.add_argument("--matricula", default=""); ap.add_argument("--fecha", default=""); ap.add_argument("--salida", default="")
    ap.add_argument("--todos", action="store_true"); ap.add_argument("--salida-dir", dest="salida_dir", default="")
    ap.add_argument("--rest-h", type=float, default=8.0); ap.add_argument("--dwell-min", type=float, default=3.0)
    ap.add_argument("--paso-s", type=int, default=120, dest="paso_s", help="segundos entre puntos dibujados (compacto)")
    ap.add_argument("--export-trazas", dest="export_trazas", default="", help="con --todos: .jsonl.gz con el recorrido real de cada viaje medido")
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
    lug = cargar_lugares(a.geocode)
    if a.todos:
        if not a.salida_dir and not a.export_trazas:
            print("--todos necesita --salida-dir o --export-trazas"); sys.exit(2)
        if a.salida_dir:
            os.makedirs(a.salida_dir, exist_ok=True)
        trazas = t2.cargar_trazas(dirs)
        flujo, _, _ = t2.coser(trazas)
        n = 0; kb = 0
        exp = [] if a.export_trazas else None
        ts_mat, ts, contexto = None, None, None
        for (mat, fecha), viajes in sorted(por_dia.items()):
            if not any(x["t_ini"] for x in viajes) or mat not in flujo:
                continue
            if ts_mat != mat:
                ts_mat = mat
                contexto = preparar_flujo(flujo[mat], rest_s)
                ts = contexto['ts']
            if exp is not None:
                exp.extend(trazas_de_viajes(mat, viajes, flujo[mat], ts))
            if not a.salida_dir:
                continue
            r = render_dia(mat, fecha, viajes, flujo[mat], dg.get((mat, fecha)), rest_s, a.paso_s, lug, contexto)
            if not r:
                continue
            ruta = os.path.join(a.salida_dir, "%s_%s.html" % (mat, fecha))
            temporal = ruta + '.' + str(os.getpid()) + '.tmp'
            with open(temporal, "w", encoding="utf-8") as salida:
                salida.write(r[0])
            os.replace(temporal, ruta)
            n += 1; kb += os.path.getsize(ruta) / 1024.0
        res = {"dias": n, "MB": round(kb / 1024.0, 1), "carpeta": a.salida_dir}
        if exp is not None:
            tmp = a.export_trazas + ".tmp"
            with gzip.open(tmp, "wt", encoding="utf-8") as f:
                for rec in exp:
                    f.write(json.dumps(rec, ensure_ascii=False, separators=(",", ":")) + "\n")
            os.replace(tmp, a.export_trazas)
            res.update({"trazas_viajes": len(exp), "trazas_MB": round(os.path.getsize(a.export_trazas) / 1048576.0, 1),
                        "con_tramo_cargado": sum(1 for r_ in exp if r_["cargado"])})
        print(json.dumps(res))
        return
    mat = t2.v1.clean(a.matricula)
    d0 = dt.date.fromisoformat(a.fecha)
    dias = {(d0 + dt.timedelta(days=k)).isoformat() for k in (-2, -1, 0, 1, 2)}
    tr = {k: v for k, v in t2.cargar_trazas(dirs).items() if k[0] == mat and k[1] in dias}
    flujo, _, _ = t2.coser(tr)
    r = render_dia(mat, a.fecha, por_dia.get((mat, a.fecha), []), flujo.get(mat, []), dg.get((mat, a.fecha)), rest_s, a.paso_s, lug)
    if not r:
        print("sin traza"); return
    open(a.salida, "w", encoding="utf-8").write(r[0])
    print("ok", a.salida, "| viajes:", len(por_dia.get((mat, a.fecha), [])), "| medidos:", r[1])


if __name__ == "__main__":
    main()
