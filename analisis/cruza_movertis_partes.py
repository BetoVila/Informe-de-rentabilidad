import gzip, json, subprocess, re, sys, glob, os, csv, io
from collections import defaultdict

W = r'C:\ProgramData\RazoRentabilidad\work'
run = [d for d in sorted(os.listdir(W)) if re.match(r'^\d{8}-\d{6}-', d) and os.path.exists(os.path.join(W, d, 'current.json.gz'))][-1]
data = json.loads(gzip.open(os.path.join(W, run, 'current.json.gz')).read())
norm = lambda s: re.sub(r'[^A-Z0-9]', '', (s or '').upper())

sql = """copy (select e.matricula, d.fecha, d.km, d.litros, d.descartada, coalesce(d.sin_cuentakilometros,false) from razo_movertis_dia d join razo_movertis_enlace e on e.id=d.enlace_id where d.fecha between '2026-08-20' and '2026-09-17') to stdout with csv"""
out = subprocess.run(['docker','exec','odoo15-local-db','psql','-U','odoo','-d','vilpor_local','-c',sql],capture_output=True,text=True,encoding='utf-8').stdout
mov = defaultdict(dict)   # plate -> date -> (km, litros, descartada)
for row in csv.reader(io.StringIO(out)):
    if not row: continue
    plate, fecha, km, lit, desc, sinck = row
    mov[norm(plate)][fecha] = (float(km) if km else None, float(lit) if lit else None, desc == 't')

parts = [p for p in data['parts'] if '2026-08-20' <= p['date'] <= '2026-09-17']
acc = defaultdict(lambda: defaultdict(lambda: [0.0, 0.0, 0.0, 0]))  # plate -> date -> km, litres, fuel EUR, n
for p in parts:
    a = acc[norm(p['plate'])][p['date']]
    a[0] += p['km']; a[1] += p['litres']; a[2] += p['fuel']; a[3] += 1

print('run', run, '| partes en ventana', len(parts), '| placas Access', len(acc), '| placas Movertis', len(mov))
print()
print('%-9s %5s %5s | %9s %9s %6s | %8s %8s %6s' % ('placa','dMov','dAcc','kmMov','kmAcc','ratio','litMov','litAcc','L/100M'))
tot = defaultdict(float)
rows = []
for plate, days in mov.items():
    good = {d: v for d, v in days.items() if not v[2] and v[0] is not None}
    if not good: continue
    both = [d for d in good if d in acc.get(plate, {})]
    kmM = sum(good[d][0] for d in good)
    litM = sum((good[d][1] or 0) for d in good)
    kmA = sum(acc[plate][d][0] for d in acc.get(plate, {}) if d in good)
    litA = sum(acc[plate][d][1] for d in acc.get(plate, {}) if d in good)
    rows.append((kmM, plate, len(good), len(both), kmM, kmA, litM, litA))
rows.sort(reverse=True)
for _, plate, dm, da, kmM, kmA, litM, litA in rows[:28]:
    print('%-9s %5d %5d | %9.0f %9.0f %6s | %8.0f %8.0f %6s' % (plate, dm, da, kmM, kmA, ('%.2f' % (kmA / kmM)) if kmM else '-', litM, litA, ('%.1f' % (litM * 100 / kmM)) if kmM else '-'))
    tot['kmM'] += kmM; tot['kmA'] += kmA; tot['litM'] += litM; tot['litA'] += litA
print()
print('SUMA (28 mayores): kmMov %.0f | kmAccess(mismos dias) %.0f | ratio %.2f | litros Mov %.0f | litros Access %.0f' % (tot['kmM'], tot['kmA'], tot['kmA'] / tot['kmM'], tot['litM'], tot['litA']))
allM = sum(r[4] for r in rows); allA = sum(r[5] for r in rows)
print('TODAS: %d placas con dias validos | kmMov %.0f | kmAccess mismos dias %.0f | ratio %.2f' % (len(rows), allM, allA, allA / allM if allM else 0))
# Access km en dias en que Movertis NO tiene dato valido (para ver hueco)
noM = sum(acc[p][d][0] for p in acc for d in acc[p] if not (p in mov and d in mov[p] and not mov[p][d][2] and mov[p][d][0] is not None))
print('km Access en dias/placas SIN dato valido de Movertis: %.0f' % noM)
