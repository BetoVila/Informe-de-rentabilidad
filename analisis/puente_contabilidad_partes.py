import gzip, json, subprocess, re, os, csv, io
from collections import defaultdict

W = r'C:\ProgramData\RazoRentabilidad\work'
run = [d for d in sorted(os.listdir(W)) if re.match(r'^\d{8}-\d{6}-', d) and os.path.exists(os.path.join(W, d, 'current.json.gz'))][-1]
data = json.loads(gzip.open(os.path.join(W, run, 'current.json.gz')).read())
D1, D2 = '2026-01-01', '2026-08-31'

def q(sql):
    out = subprocess.run(['docker', 'exec', 'odoo15-local-db', 'psql', '-U', 'odoo', '-d', 'vilpor_local', '-At', '-F', '|', '-c', sql], capture_output=True, text=True, encoding='utf-8').stdout
    return [l.split('|') for l in out.strip().splitlines() if l]

# contabilidad por sociedad y grupo de cuentas (6xx gasto, 7xx ingreso), ordinarios, D1..D2
led = defaultdict(lambda: defaultdict(float))
for c, g, v in q("select company_id, left(cuenta_codigo,3), sum(debe-haber) from razo_cxconta_apunte where fecha between '%s' and '%s' and clase='ordinario' group by 1,2" % (D1, D2)):
    led[int(c)][g] = float(v)
def L(c, *prefixes):
    return sum(v for g, v in led[c].items() if g.startswith(prefixes) )
# ingresos y gastos totales
for c, name in ((1, 'Razo'), (2, 'Agetrans')):
    ing = -sum(v for g, v in led[c].items() if g.startswith('7'))
    gas = sum(v for g, v in led[c].items() if g.startswith('6'))
    print('%-9s contabilidad %s..%s: ingresos %.0f | gastos %.0f | resultado %.0f (%.1f%%)' % (name, D1, D2, ing, gas, ing - gas, (ing - gas) * 100 / ing))

# partes por titular
owners = {'TRANSPORTES RAZO, S.L.': 1, 'AGETRANS BERGANTIÑOS, S.L.': 2}
fields = ['fuel', 'adblue', 'driver', 'overtime', 'amort', 'maintenance', 'insurance', 'expensesCompany', 'expensesDriver', 'expensesVehicle', 'structure']
P = defaultdict(lambda: defaultdict(float)); n = defaultdict(int)
for p in data['parts']:
    if D1 <= p['date'] <= D2:
        c = owners.get(p['owner'], 0)
        n[c] += 1
        for f in fields: P[c][f] += p[f]
print()
print('partes Access 2026-01..08 por titular: %s' % {k: n[k] for k in n})
for c, name in ((1, 'Razo'), (2, 'Agetrans'), (0, 'otros/sin titular')):
    tot = sum(P[c].values())
    print('%-9s partes: %s | total %.0f' % (name, ', '.join('%s %.0f' % (f, P[c][f]) for f in fields if P[c][f]), tot))

print()
print('%-38s %12s %12s' % ('PUENTE (Razo)', 'contabilidad', 'partes'))
r = 1
rows = [
 ('Combustible (628.0)', L(r, '6280'), P[r]['fuel']),
 ('Personal 640+641+642+649 (sueldos y SS)', L(r, '640', '641', '642', '649'), P[r]['driver'] + P[r]['overtime']),
 ('Dietas 62900801-4 (personal)', 0, P[r]['expensesDriver']),
 ('Amortizacion 681', L(r, '681'), P[r]['amort']),
 ('Seguros 625', L(r, '625'), P[r]['insurance']),
 ('Reparaciones 622 + repuestos/neumaticos', L(r, '622'), P[r]['maintenance']),
 ('Peajes/otros vehiculo', 0, P[r]['expensesVehicle']),
 ('Gastos empresa', 0, P[r]['expensesCompany']),
 ('Estructura % (imputada)', 0, P[r]['structure']),
 ('AdBlue', 0, P[r]['adblue']),
]
for name, a, b in rows: print('%-38s %12.0f %12.0f' % (name, a, b))
print('%-38s %12.0f %12.0f' % ('TOTAL GASTOS', L(r, '6'), sum(P[r].values())))
print()
print('Agetrans: gastos contab %.0f | partes %.0f | de ellos 607 (subcontratacion) %.0f | 678 extraord. %.0f | 628 combustible %.0f | 640+642 personal %.0f' % (L(2, '6'), sum(P[2].values()), L(2, '607'), L(2, '678'), L(2, '628'), L(2, '640', '642')))
print('Razo: 607 subcontr. %.0f | 602 compras (aridos y repuestos) %.0f | 622 reparaciones %.0f' % (L(1, '607'), L(1, '602'), L(1, '622')))
