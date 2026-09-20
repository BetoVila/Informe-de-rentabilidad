# -*- coding: utf-8 -*-
"""Genera Conciliacion.dc.html y Personal.dc.html a partir de Main.dc.html
(mismo masthead, filtros y estilos) + datos_conciliacion.json (REALES y
agregados). Personal usa filas FICTICIAS: nada de personas reales en la
maqueta. Parchea tambien las pestanas de Main y Vehiculos."""
import json
import os
import re

B = r"C:\Users\Roberto\AppData\Local\Temp\claude\C--Users-Roberto-Downloads-Nueva-carpeta\28602b99-e589-45df-aa45-17dc43911990\scratchpad"
P = os.path.join(B, "rentabilidad-mockup", "project")
D = json.load(open(os.path.join(B, "datos_conciliacion.json"), encoding="utf-8"))
MES = {"01": "Ene", "02": "Feb", "03": "Mar", "04": "Abr", "05": "May", "06": "Jun", "07": "Jul", "08": "Ago", "09": "Sep", "10": "Oct", "11": "Nov", "12": "Dic"}


def n(v, d=0):
    s = "{:,.{d}f}".format(v, d=d)
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def eur(v):
    return n(v) + " €"


def mes(m):
    return "%s %s" % (MES[m[5:7]], m[:4])


def pill_pct(p):
    if p is None:
        return '<span class="pill">—</span>'
    cls = "ok" if 95 <= p <= 105 else ("warn" if 85 <= p < 95 or 105 < p <= 112 else "bad")
    return '<span class="pill %s">%s %%</span>' % (cls, n(p, 1))


LOCK = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-2px;margin-left:5px"><rect x="4" y="11" width="16" height="10" rx="2"/><path d="M8 11V8a4 4 0 0 1 8 0v3"/></svg>'


def tabs(sel):
    def t(k, label, href=None):
        if k == sel:
            return '<button class="selected" aria-current="page">%s</button>' % label
        if href:
            return '<a href="%s">%s</a>' % (href, label)
        return "<button>%s</button>" % label
    return ('<nav class="tabs" aria-label="Vistas">' + t("res", "Resumen", "Main.dc.html") + t("veh", "Vehículos", "Vehiculos.dc.html")
            + t("cli", "Clientes") + t("fac", "Facturas") + t("par", "Partes y costes")
            + t("con", "Conciliación", "Conciliacion.dc.html") + t("per", "Personal" + LOCK, "Personal.dc.html")
            + t("met", "Criterios y fuentes") + "</nav>")


def titlebar(tag):
    return ('<div class="titlebar"><div><p class="eyebrow">ANÁLISIS DE LA OPERACIÓN · SERVIDOR</p><h1>Rentabilidad</h1></div>'
            '<div style="display:flex;gap:10px;align-items:center"><span class="tag">%s</span>'
            '<a class="textbtn" href="#">Estado de actualización ↗</a><button class="textbtn">Recargar informe</button></div></div>' % tag)


EXTRA_CSS = """
.ph{display:flex;justify-content:space-between;align-items:flex-start;gap:12px;flex-wrap:wrap}
.pill{display:inline-block;padding:3px 10px;border-radius:20px;font-size:11.5px;font-weight:700;background:#eef2f8;color:#455b77;white-space:nowrap}
.pill.ok{background:#dcf3ec;color:#0b6b5f}.pill.warn{background:#fff0d6;color:#8a5608}.pill.bad{background:#fde4e7;color:#a12a3a}.pill.off{background:#eef2f8;color:#6b7c90;border:1px dashed #b8c4d3}
.verdict{border:1px solid #d3dceb;border-left:4px solid #2C5FD6;background:#f4f8ff;border-radius:10px;padding:13px 16px;font-size:13.5px;color:#22344d;margin:0 0 16px;line-height:1.55}
.verdict.warn{border-left-color:#A9660A;background:#fdf8ec;color:#5f430f}
.panel h3{margin:22px 0 10px;font-size:14px;color:#0A192F}
.split{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-top:6px}
.stat{border:1px solid #dde4ec;border-radius:12px;padding:14px 16px}
.stat .label{font-size:12px;color:#5A6B7C;display:block}.stat .value{font-size:22px;font-weight:700;color:#0A192F;display:block;margin-top:4px}.stat small{font-size:11.5px;color:#5A6B7C}
.ph2{display:grid;grid-template-columns:150px 1fr auto auto;align-items:center;gap:12px;font-size:13px;margin:12px 0}
.note{font-size:12px;color:#5A6B7C;margin-top:10px;line-height:1.5}
.lockbox{max-width:460px;margin:34px auto;text-align:center;padding:30px 28px;background:#fff;border:1px solid #dde4ec;border-radius:16px}
.lockbox .ico{width:54px;height:54px;border-radius:14px;background:#eef2f8;display:grid;place-items:center;margin:0 auto 14px;color:#0A192F}
.lockbox h2{margin:0 0 6px;font-size:19px;color:#0A192F}.lockbox p{color:#5A6B7C;font-size:13.5px;margin:0 0 16px;line-height:1.55}
.lockbox input{width:100%;padding:11px 12px;border:1px solid #cbd6e4;border-radius:9px;font-size:14px;margin-bottom:10px}
.lockbox button.go{width:100%;padding:11px;background:#0A192F;color:#fff;border:0;border-radius:9px;font-size:14px;font-weight:600}
.ribbon{display:inline-block;background:#fdf1d8;color:#7a5209;border:1px solid #ecd9a8;font-size:12px;font-weight:700;padding:4px 10px;border-radius:8px;margin-bottom:12px}
.chips2{display:flex;gap:6px;flex-wrap:wrap;margin:0 0 14px}
.chips2 button{font-size:12px;padding:5px 11px}.chips2 button.selected{background:#0A192F;color:#fff;border-color:#0A192F}
"""


def bar(p, txt):
    w = max(2, min(100, p))
    col = "#0E9488" if 95 <= p <= 105 else ("#A9660A" if p >= 85 else "#C1394B")
    return '<div class="bartrack"><div class="barfill" style="width:%s%%;background:%s"></div></div>' % (w, col)


# ---------------------------------------------------------------- CONCILIACION
per = D["personal"]
acum_n = sum(r["nomina"] for r in per)
acum_i = sum(r["imputado"] for r in per)
acum = 100 * acum_i / acum_n
ult = per[-1]
filas_p = "".join(
    '<tr><td>%s</td><td class="num">%s</td><td class="num">%s</td><td class="num">%s</td><td class="num">%s</td></tr>' % (
        mes(r["mes"]), eur(r["nomina"]), eur(r["imputado"]), pill_pct(r["pct"]), ("+" if r["sin_imputar"] < 0 else "") + eur(-r["sin_imputar"] if r["sin_imputar"] < 0 else r["sin_imputar"]))
    for r in per)
tipos = "".join('<div class="ph2"><span>%s</span>%s<span class="barnum">%s</span>%s</div>' % (
    t["tipo"], bar(t["pct"], ""), eur(t["nomina"]), pill_pct(t["pct"])) for t in D["por_tipo"])
g = D["gasto"]
filas_g = "".join(
    '<tr><td>%s%s</td><td class="num">%s</td><td class="num">%s</td><td class="num">%s</td><td class="num"><b>%s</b></td><td class="num">%s</td></tr>' % (
        mes(r["mes"]), ' <small style="color:#8a97a8">· surtidor hasta el 6</small>' if r["mes"] == "2026-08" else "",
        n(r["partes_l"]), n(r["solred_l"]), n(r["gespro_l"]), n(r["sin_respaldo_l"]), pill_pct(r["pct_cubierto"]))
    for r in g)
media_sin = sum(r["sin_respaldo_l"] for r in g) / len(g)
est = D["estructura"]

main_con = titlebar("Conciliación · Ene–Ago 2026") + tabs("con") + """
<section class="panel" style="margin-bottom:16px">
  <div class="ph"><h2>Personal · nómina real frente a lo que imputan los partes</h2><span class="pill warn">Baja cada mes desde abril</span></div>
  <p class="sub">Conductores de Razo y Agetrans juntos. Nómina = coste de empresa exacto de la gestoría (devengos + Seguridad Social + dietas). Imputado = conductor ordinario + extra + gastos de empleado de los partes de Access.</p>
  <div class="verdict warn">Acumulado de enero a agosto, los partes imputan el <b>%(acum)s %%</b> de la nómina de conductores. Mes a mes oscila entre el 85 %% y el 115 %%, y desde abril baja cada mes (101 %% → 85 %%): en agosto quedan <b>%(sin)s</b> de coste de conductores sin imputar a ningún parte.</div>
  <div class="tablewrap"><table>
    <thead><tr><th>Mes</th><th style="text-align:right">Nómina conductores</th><th style="text-align:right">Imputado en partes</th><th style="text-align:right">%% imputado</th><th style="text-align:right">Sin imputar</th></tr></thead>
    <tbody>%(filas_p)s</tbody></table></div>
  <h3>Por tipo de trabajo · %(ult)s</h3>%(tipos)s
  <p class="note">Hormigonera = sección 1 de Razo · bañera = sección 3 de Razo · nacional = sección 2 de Razo + sección 1 de Agetrans (probable, por confirmar con los contratos de Access).</p>
  <div class="split">
    <div class="stat"><span class="label">Estructura que añaden los partes (12 %%) · %(ult)s</span><span class="value">%(estr)s</span><small>Suma de «coste estructura» de todos los partes del mes</small></div>
    <div class="stat"><span class="label">Nómina de administración + taller · %(ult)s</span><span class="value">%(admin)s</span><small>Razo (secciones 4 y 5) · Agetrans sección 3 aparte: %(ag3)s</small></div>
  </div>
</section>

<section class="panel" style="margin-bottom:16px">
  <div class="ph"><h2>Combustible · litros que declaran los partes frente a lo que hay detrás</h2><span class="pill warn">~%(pctmedio)s %% sin respaldo</span></div>
  <p class="sub">Gasóleo, litros. Solred = extracto real de la tarjeta. Surtidor = depósito propio de la nave (GesproWin). Donde una matrícula sale en partes y en Solred, los litros coinciden (mediana 0 %%).</p>
  <div class="verdict warn">Cada mes hay unos <b>%(media)s litros</b> en los partes que no están ni en la tarjeta ni en el surtidor: otra tarjeta, pago en efectivo… o litros declarados de más. Se enseñan como dato de control, sin corregirlos. Además, la base del surtidor <b>se corta el 6 de agosto</b>: la copia nocturna no está llegando.</div>
  <div class="tablewrap"><table>
    <thead><tr><th>Mes</th><th style="text-align:right">Litros en partes</th><th style="text-align:right">Solred (tarjeta)</th><th style="text-align:right">Surtidor de la nave</th><th style="text-align:right">Sin respaldo</th><th style="text-align:right">Cubierto</th></tr></thead>
    <tbody>%(filas_g)s</tbody></table></div>
</section>

<section class="panel" style="margin-bottom:16px">
  <div class="ph"><h2>Kilómetros · qué fuentes hay y cuál está viva</h2><span class="pill bad">GesRuta sin km desde mayo</span></div>
  <p class="sub">El informe usa los km de los partes de Access. Estas son las fuentes independientes con las que se pueden contrastar.</p>
  <div class="tablewrap"><table>
    <thead><tr><th>Fuente</th><th>Qué aporta</th><th>Cobertura</th><th>Estado</th></tr></thead>
    <tbody>
      <tr><td>Partes de Access</td><td>km por vehículo y día (declarados)</td><td>Todo el periodo</td><td><span class="pill ok">Conectada</span></td></tr>
      <tr><td>GesRuta · kilome</td><td>Odómetro encadenado por viaje</td><td>Hasta abril de 2026; desde mayo 0 filas</td><td><span class="pill bad">Cortada</span></td></tr>
      <tr><td>Surtidor de la nave</td><td>Km en cada repostaje del depósito</td><td>Hasta el 6 de agosto de 2026</td><td><span class="pill warn">Parada</span></td></tr>
      <tr><td>Locatel</td><td>Km GPS por trayecto · litros y CO₂ por CANbus</td><td>13 vehículos · rango de fechas libre</td><td><span class="pill warn">Probada · falta automatizar</span></td></tr>
      <tr><td>Movertis</td><td>Odómetro exacto por viaje</td><td>Aprox. el último año</td><td><span class="pill off">Falta acceso</span></td></tr>
    </tbody></table></div>
</section>

<section class="panel">
  <div class="ph"><h2>Sin duplicados · versiones de un mismo mes</h2><span class="pill ok">1 caso resuelto</span></div>
  <p class="sub">Cuando un mismo mes de nómina aparece en más de un fichero, se usa el más reciente y las demás versiones quedan anotadas aquí.</p>
  <div class="tablewrap"><table>
    <thead><tr><th>Empresa · mes</th><th>Fichero usado</th><th>Otra versión</th><th style="text-align:right">Diferencia</th></tr></thead>
    <tbody><tr><td>Razo · Feb 2025</td><td>Carpeta de febrero · 16/04/2025 · 146.223,17 €</td><td>Carpeta de enero (mal archivada) · 10/03/2025 · 146.750,54 €</td><td class="num">−527,37 €</td></tr></tbody></table></div>
</section>
<footer>Maqueta con cifras reales agregadas (sin nombres ni sueldos individuales). Personal: nómina de la gestoría y partes de Access; combustible: Solred, GesproWin y partes; datos hasta el 18/09/2026.</footer>
""" % {"acum": n(acum, 1), "sin": eur(ult["sin_imputar"]), "filas_p": filas_p, "ult": mes(ult["mes"]), "tipos": tipos,
       "estr": eur(est["estructura_access"]), "admin": eur(est["admin_taller_razo"]), "ag3": eur(est["agetrans_s3"]),
       "media": n(round(media_sin, -2)), "filas_g": filas_g, "pctmedio": n(100 - sum(r["pct_cubierto"] for r in g) / len(g), 0)}

# ---------------------------------------------------------------- PERSONAL (ficticio)
demo = [("Conductor 1", "Conductor hormigonera", "Razo", 3412.50, 2648.10, 764.40, 198.20, 168.0),
        ("Conductor 2", "Conductor hormigonera", "Razo", 3287.15, 2531.00, 756.15, 176.00, 171.5),
        ("Conductor 3", "Conductor nacional", "Razo", 3690.80, 2902.35, 788.45, 512.40, 164.0),
        ("Conductor 4", "Conductor nacional", "Agetrans", 3544.20, 2760.90, 783.30, 498.60, 160.5),
        ("Conductor 5", "Conductor bañera", "Razo", 3201.95, 2470.55, 731.40, 121.30, 169.0),
        ("Conductor 6", "Conductor bañera", "Razo", 3315.60, 2566.20, 749.40, 133.90, 172.0),
        ("Mecánico 1", "Taller", "Razo", 2508.30, 1961.75, 546.55, 0.0, 0.0),
        ("Administrativo 1", "Administración", "Razo", 2887.40, 2321.60, 565.80, 0.0, 0.0)]
filas_d = ""
for nom_, tr, emp, c, dv, ss, di, h in demo:
    real_h = (c / h) if h else None
    acc_h = round(real_h * 0.93, 2) if real_h else None
    filas_d += ('<tr><td>%s</td><td>%s</td><td>%s</td><td class="num">%s</td><td class="num">%s</td><td class="num">%s</td><td class="num">%s</td><td class="num">%s</td><td class="num">%s</td><td class="num">%s</td></tr>' % (
        nom_, tr, emp, eur(c).replace(" €", ",00 €") if False else n(c, 2) + " €", n(dv, 2) + " €", n(ss, 2) + " €", n(di, 2) + " €",
        n(h, 1) if h else "—", (n(real_h, 2) + " €") if real_h else "—", (n(acc_h, 2) + " €") if acc_h else "—"))

main_per = titlebar("Personal · Ago 2026") + tabs("per") + """
<sc-if value="{{ locked }}" hint-placeholder-val="{{ true }}">
  <div class="lockbox">
    <div class="ico"><svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="4" y="11" width="16" height="10" rx="2"/><path d="M8 11V8a4 4 0 0 1 8 0v3"/></svg></div>
    <h2>Coste por empleado</h2>
    <p>Este apartado muestra el sueldo y el coste de cada persona. Cualquiera con acceso a la carpeta puede abrir el informe, así que se protege con una clave. El resto del informe se ve igual sin ella.</p>
    <label for="clave" style="position:absolute;left:-9999px">Clave</label>
    <input id="clave" type="password" placeholder="Clave del apartado de personal" autocomplete="off">
    <button class="go" onClick="{{ unlock }}">Desbloquear (demo)</button>
    <p class="note" style="margin-top:12px">La clave la eliges tú al instalar el informe en SERVIDOR. Sin clave, este apartado no se llega a descifrar: los sueldos no están en el fichero en claro.</p>
  </div>
</sc-if>
<sc-if value="{{ unlocked }}" hint-placeholder-val="{{ false }}">
  <section class="panel">
    <div class="ph"><div><h2>Coste por empleado y mes</h2><p class="sub">Coste de empresa exacto de la nómina de la gestoría, por persona, con su tipo de trabajo. Horas y €/hora salen de los partes de Access.</p></div>
      <button class="textbtn" onClick="{{ lock }}">Bloquear</button></div>
    <span class="ribbon">EJEMPLO CON DATOS FICTICIOS · en el informe real salen los nombres y sueldos de la nómina</span>
    <div class="chips2"><button class="selected">Todos</button><button>Conductor hormigonera</button><button>Conductor nacional</button><button>Conductor bañera</button><button>Taller</button><button>Administración</button></div>
    <div class="tablewrap"><table>
      <thead><tr><th>Persona</th><th>Trabajo que realiza</th><th>Empresa</th><th style="text-align:right">Coste empresa</th><th style="text-align:right">Devengos</th><th style="text-align:right">Seg. Social</th><th style="text-align:right">Dietas</th><th style="text-align:right">Horas en partes</th><th style="text-align:right">€/hora real</th><th style="text-align:right">€/hora en Access</th></tr></thead>
      <tbody>""" + filas_d + """</tbody></table></div>
    <p class="note">«€/hora real» = coste de empresa del mes ÷ horas de sus partes. «€/hora en Access» es la tarifa del contrato que usan los partes hoy: la diferencia dice qué tarifas hay que corregir. Bajas, vacaciones y personas sin partes aparecen igual, con horas en blanco.</p>
  </section>
</sc-if>
<footer>Maqueta · datos ficticios en esta pantalla. La nómina real nunca se publica en claro.</footer>
"""

# ---------------------------------------------------------------- ensamblado
main_txt = open(os.path.join(P, "Main.dc.html"), encoding="utf-8").read()
ini = main_txt.index("<main>")
fin = main_txt.index("</main>") + len("</main>")
cabeza, cola = main_txt[:ini], main_txt[fin:]
cabeza = cabeza.replace("<title>Rentabilidad · Resumen</title>", "<title>%s</title>")
cabeza = re.sub(r'<button class="\{\{companyAllClass\}\}"[^\n]*\n\s*<button class="\{\{companyRazoClass\}\}"[^\n]*\n\s*<button class="\{\{companyAgetransClass\}\}"[^\n]*\n',
                '<button class="selected">Ambas</button><button>Razo</button><button>Agetrans</button>\n', cabeza)
cabeza = cabeza.replace("</style>", EXTRA_CSS + "</style>", 1)
# tabs de las pantallas existentes: enlazar Conciliacion y Personal
for fichero in ("Main.dc.html", "Vehiculos.dc.html"):
    txt = open(os.path.join(P, fichero), encoding="utf-8").read()
    if "Personal.dc.html" not in txt:
        txt = txt.replace("<button>Conciliación</button>", '<a href="Conciliacion.dc.html">Conciliación</a>\n      <a href="Personal.dc.html">Personal' + LOCK + '</a>')
        open(os.path.join(P, fichero), "w", encoding="utf-8").write(txt)

script_con = """<script type="text/x-dc" data-dc-script data-props='{"$preview":{"width":1440,"height":2300}}'>
class Component extends DCLogic {
  renderVals(){ return {}; }
}
</script>"""
script_per = """<script type="text/x-dc" data-dc-script data-props='{"$preview":{"width":1440,"height":1100}}'>
class Component extends DCLogic {
  constructor(props){ super(props); this.state = { unlocked: false }; }
  renderVals(){
    return { unlocked: this.state.unlocked, locked: !this.state.unlocked,
      unlock: () => this.setState({ unlocked: true }), lock: () => this.setState({ unlocked: false }) };
  }
}
</script>
</body>
</html>"""
script_con += "\n</body>\n</html>"
open(os.path.join(P, "Conciliacion.dc.html"), "w", encoding="utf-8").write(cabeza.replace("<title>%s</title>", "<title>Rentabilidad · Conciliación</title>") + "<main>" + main_con + "</main>\n</div>\n</div>\n\n</x-dc>\n" + script_con)
open(os.path.join(P, "Personal.dc.html"), "w", encoding="utf-8").write(cabeza.replace("<title>%s</title>", "<title>Rentabilidad · Personal</title>") + "<main>" + main_per + "</main>\n</div>\n</div>\n\n</x-dc>\n" + script_per)

# canvas.json
cj = json.load(open(os.path.join(P, "canvas.json"), encoding="utf-8"))
cj["boards"]["Conciliacion.dc.html"] = {"x": 3200, "y": 0, "w": 1440, "h": 2300, "title": "Conciliación", "expand": "fill", "is_interactive": True}
cj["boards"]["Personal.dc.html"] = {"x": 4800, "y": 0, "w": 1440, "h": 1100, "title": "Personal (protegido)", "expand": "fill", "is_interactive": True}
for k in ("Conciliacion.dc.html", "Personal.dc.html"):
    if k not in cj["order"]:
        cj["order"].append(k)
json.dump(cj, open(os.path.join(P, "canvas.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print("OK: generados Conciliacion.dc.html, Personal.dc.html; pestanas parcheadas; canvas.json actualizado")
