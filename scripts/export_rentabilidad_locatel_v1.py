# -*- coding: utf-8 -*-
"""Km y consumo reales medidos por Locatel (CANbus), para el informe de rentabilidad. SOLO LECTURA, SIN CLAVES.

Igual que con Movertis: NO se llama a la web de Locatel desde aqui. El ERP tiene su propio agente que baja las emisiones de
Locatel y las deja en `razo_locatel_emision` (km, litros, CO2, con `factor_medido` del CANbus y `estimado` cuando no lo hay).
Aqui solo se lee esa tabla. Un dato, un sitio.

Hoy esa tabla puede estar VACIA en la copia local del ERP (el agente corre en produccion y todavia no ha traido las
emisiones a `vilpor_local`, igual que el historico de km). En ese caso NO se inventa nada: se sale con `disponible:false` y su
motivo, el informe lo dice y sigue. En cuanto las emisiones lleguen a la copia local, esta misma lectura las usa sin tocar nada.
"""
import argparse, csv, datetime, io, json, os, shutil, subprocess, sys


def consulta(docker, contenedor, base, usuario, sql, tiempo=180):
    orden = [docker, 'exec', contenedor, 'psql', '-U', usuario, '-d', base, '-v', 'ON_ERROR_STOP=1', '-c',
             'COPY (%s) TO STDOUT WITH (FORMAT csv, HEADER true)' % sql]
    r = subprocess.run(orden, capture_output=True, timeout=tiempo)
    if r.returncode != 0:
        raise RuntimeError('psql fallo (%s): %s' % (r.returncode, r.stderr.decode('utf-8', 'replace').strip()[:400]))
    return list(csv.DictReader(io.StringIO(r.stdout.decode('utf-8'))))


def num(v):
    return round(float(v), 2) if v not in (None, '') else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--output', required=True)
    ap.add_argument('--from-date', default='2025-01-01')
    ap.add_argument('--to-date', default='')
    ap.add_argument('--contenedor', default=os.environ.get('RAZO_DB_CONTENEDOR') or 'odoo15-local-db')
    ap.add_argument('--base', default=os.environ.get('RAZO_DB_BASE') or 'vilpor_local')
    ap.add_argument('--usuario', default=os.environ.get('RAZO_DB_USUARIO') or 'odoo')
    a = ap.parse_args()
    hasta = a.to_date or (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
    docker = shutil.which('docker')
    if not docker:
        raise RuntimeError('No se encuentra docker en el PATH')
    # Emisiones que solapan con el periodo. Cada fila es un tramo (fecha_desde..fecha_hasta) por matricula.
    filas = consulta(docker, a.contenedor, a.base, a.usuario,
        "SELECT matricula AS p, fecha_desde AS d1, fecha_hasta AS d2, km, litros AS l, co2e_kg AS co2, "
        "estimado AS est, combustible AS comb FROM razo_locatel_emision WHERE matricula IS NOT NULL "
        "AND fecha_hasta >= '%s' AND fecha_desde <= '%s' ORDER BY fecha_desde, matricula" % (a.from_date, hasta))
    leido = datetime.datetime.now().isoformat(timespec='seconds')
    if not filas:
        # No es un error: la tabla existe pero el ERP aun no ha traido las emisiones a la copia local.
        out = {'metadata': {'disponible': False, 'fuente': 'Locatel (razo_locatel_emision del ERP)', 'leido': leido,
                            'motivo': 'El ERP todavia no ha traido las emisiones de Locatel a la copia local (0 registros).'}}
        with open(a.output, 'w', encoding='utf-8') as f:
            json.dump(out, f, ensure_ascii=False)
        print(json.dumps({'disponible': False, 'registros': 0, 'motivo': out['metadata']['motivo']}, ensure_ascii=False))
        return
    rows = []
    for r in filas:
        if r['km'] in (None, '') or float(r['km']) <= 0:
            continue
        rows.append({'p': r['p'], 'from': r['d1'], 'to': r['d2'], 'km': round(float(r['km']), 2),
                     'litres': num(r['l']), 'co2e': num(r['co2']), 'estimado': r['est'] == 't', 'fuel': r['comb'] or None})
    if not rows:
        out = {'metadata': {'disponible': False, 'fuente': 'Locatel (razo_locatel_emision del ERP)', 'leido': leido,
                            'motivo': 'Locatel devuelve registros sin km utiles en el periodo.'}}
        with open(a.output, 'w', encoding='utf-8') as f:
            json.dump(out, f, ensure_ascii=False)
        print(json.dumps({'disponible': False, 'registros': len(filas)}, ensure_ascii=False))
        return
    desde = min(r['from'] for r in rows)
    hasta_real = max(r['to'] for r in rows)
    out = {'metadata': {'disponible': True, 'fuente': 'Locatel (razo_locatel_emision del ERP)', 'desde': desde, 'hasta': hasta_real,
                        'registros': len(rows), 'estimados': sum(1 for r in rows if r['estimado']),
                        'unidades': len({r['p'] for r in rows}), 'leido': leido}, 'rows': rows}
    with open(a.output, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False)
    print(json.dumps(out['metadata'], ensure_ascii=False))


if __name__ == '__main__':
    try:
        main()
    except Exception as e:  # noqa: BLE001
        print('ERROR: %s' % e, file=sys.stderr)
        sys.exit(1)
