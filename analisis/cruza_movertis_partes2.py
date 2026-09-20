import gzip, json, subprocess, re, os, csv, io, statistics
from collections import defaultdict

W = r'C:\ProgramData\RazoRentabilidad\work'
run = [d for d in sorted(os.listdir(W)) if re.match(r'^\d{8}-\d{6}-', d) and os.path.exists(os.path.join(W, d, 'current.json.gz'))][-1]
data = json.loads(gzip.open(os.path.join(W, run, 'current.json.gz')).read())
norm = lambda s: re.sub(r'[^A-Z0-9]', '', (s or '').upper())
P = data['parts']

print('=== 1. CALIDAD DE LOS PARTES DE ACCESS (todo el historico, %d partes) ===' % len(P))
def bad(name, pred, val):
    xs = [p for p in P if pred(p)]
    print('%-46s %6d partes | suma %s' % (name, len(xs), '{:,.0f}'.format(sum(val(p) for p in xs))))
bad('km > 1.500 en un solo parte (imposible)', lambda p: p['km'] > 1500, lambda p: p['km'])
bad('km negativos', lambda p: p['km'] < 0, lambda p: p['km'])
bad('litros > 1.500 en un parte', lambda p: p['litres'] > 1500, lambda p: p['litres'])
bad('horas > 24 en un parte', lambda p: p['hours'] > 24, lambda p: p['hours'])
tot_km = sum(p['km'] for p in P); ok_km = sum(p['km'] for p in P if 0 <= p['km'] <= 1500)
print('km totales en partes: {:,.0f} | sin los imposibles: {:,.0f} | inflado por basura: {:,.0f}'.format(tot_km, ok_km, tot_km - ok_km))
# consumo aparente global con y sin basura
lit = sum(p['litres'] for p in P)
print('consumo aparente global (litros/km*100): con basura %.2f | sin basura %.2f' % (lit * 100 / tot_km, sum(p['litres'] for p in P if 0 <= p['km'] <= 1500) * 100 / ok_km))
for f in ['expensesCompany', 'expensesDriver', 'expensesVehicle']:
    xs = sorted(P, key=lambda p: -p[f])[:3]
    print('mayores %-16s: %s | total %.0f' % (f, ', '.join('%s %s %.0f' % (p['plate'], p['date'], p[f]) for p in xs), sum(p[f] for p in P)))

print()
print('=== 2. MISMOS DIAS: Movertis (GPS/CAN) frente al parte de Access, 20/08-17/09/2026 ===')
sql = """copy (select e.matricula, d.fecha, d.km, d.litros from razo_movertis_dia d join razo_movertis_enlace e on e.id=d.enlace_id where d.fecha between '2026-08-20' and '2026-09-17' and not d.descartada and d.km is not null) to stdout with csv"""
out = subprocess.run(['docker', 'exec', 'odoo15-local-db', 'psql', '-U', 'odoo', '-d', 'vilpor_local', '-c', sql], capture_output=True, text=True, encoding='utf-8').stdout
mov = {}
for row in csv.reader(io.StringIO(out)):
    if row:
        mov[(norm(row[0]), row[1])] = (float(row[2]), float(row[3]) if row[3] else None)
acc = defaultdict(lambda: [0.0, 0.0, 0])
for p in P:
    if '2026-08-20' <= p['date'] <= '2026-09-17':
        a = acc[(norm(p['plate']), p['date'])]; a[0] += p['km']; a[1] += p['litres']; a[2] += 1
ratios = []; sumM = sumA = 0; garbage = 0; noKm = 0; comp = 0
for k, (km, lit_m) in mov.items():
    if k in acc:
        comp += 1
        if km < 30: continue           # camion casi parado: la razon no dice nada
        a = acc[k]
        if a[0] > 1500: garbage += 1; continue
        if a[0] == 0: noKm += 1
        ratios.append(a[0] / km); sumM += km; sumA += a[0]
print('dias-camion con las dos fuentes: %d | con km imposibles en Access: %d | con km=0 en Access aunque Movertis dice que circuló: %d' % (comp, garbage, noKm))
if ratios:
    ratios.sort()
    q = lambda f: ratios[int(f * (len(ratios) - 1))]
    within = sum(1 for r in ratios if 0.85 <= r <= 1.15) * 100 / len(ratios)
    print('n=%d | ratio km Access/Movertis: p10 %.2f  mediana %.2f  p90 %.2f | dentro de +-15%%: %.0f%% | suma Access %.0f vs Movertis %.0f (%.2f)' % (len(ratios), q(.1), q(.5), q(.9), within, sumA, sumM, sumA / sumM))
# dias con Movertis>30km sin ningun parte de Access
sinparte = [(k, v[0]) for k, v in mov.items() if v[0] >= 30 and k not in acc]
print('dias-camion con Movertis >=30 km y SIN parte de Access: %d de %d (%.0f%%) | %.0f km sin parte' % (len(sinparte), sum(1 for v in mov.values() if v[0] >= 30), len(sinparte) * 100 / max(1, sum(1 for v in mov.values() if v[0] >= 30)), sum(x[1] for x in sinparte)))

print()
print('=== 3. KM DE MOVERTIS EN DIAS SIN PARTE, POR MATRICULA (top) ===')
byplate = defaultdict(lambda: [0, 0.0, 0, 0.0])   # dias sin parte, km sin parte, dias con parte, km con parte
for (pl, d), (km, lit_m) in mov.items():
    if km < 30: continue
    if (pl, d) in acc: byplate[pl][2] += 1; byplate[pl][3] += km
    else: byplate[pl][0] += 1; byplate[pl][1] += km
anyPart = {pl for (pl, d) in acc}
rows = sorted(byplate.items(), key=lambda kv: -kv[1][1])
print('%-9s %8s %10s %8s %10s  %s' % ('placa', 'dSinPart', 'kmSinPart', 'dConPart', 'kmConPart', 'tiene partes en la ventana'))
for pl, v in rows[:14]:
    print('%-9s %8d %10.0f %8d %10.0f  %s' % (pl, v[0], v[1], v[2], v[3], 'si' if pl in anyPart else 'NINGUNO'))
never = [(pl, v) for pl, v in byplate.items() if pl not in anyPart]
print('placas activas en Movertis (>=30 km algun dia) SIN ningun parte en la ventana: %d de %d | %.0f km' % (len(never), len(byplate), sum(v[1] for _, v in never)))
