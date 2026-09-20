# -*- coding: utf-8 -*-
"""Km y litros por camion y dia medidos por Movertis, para el informe de rentabilidad. SOLO LECTURA, SIN CLAVES.

Movertis (Wialon) admite una sola sesion a la vez y el ERP ya la usa cada pocos minutos. Por eso aqui NO se abre ninguna
sesion en Movertis: se lee lo que el propio ERP ya ha bajado y validado (`razo_movertis_dia`, con el puente unidad <->
matricula `razo_movertis_enlace`). Un dato, un sitio: la cuenta de los kilometros (formula del sensor, dias cortados con la
hora de Madrid, lecturas tiradas) vive en el ERP y no se repite.

Se descartan los dias que el ERP marca como no fiables (`descartada`): sin lectura del cuentakilometros, sin formula del
sensor o con un valor imposible. Nunca se rellena un dia sin dato con un cero.
"""
import argparse, csv, datetime, io, json, os, shutil, subprocess, sys


def consulta(docker, contenedor, base, usuario, sql, tiempo=180):
    orden = [docker, 'exec', contenedor, 'psql', '-U', usuario, '-d', base, '-v', 'ON_ERROR_STOP=1', '-c',
             'COPY (%s) TO STDOUT WITH (FORMAT csv, HEADER true)' % sql]
    r = subprocess.run(orden, capture_output=True, timeout=tiempo)
    if r.returncode != 0:
        raise RuntimeError('psql fallo (%s): %s' % (r.returncode, r.stderr.decode('utf-8', 'replace').strip()[:400]))
    return list(csv.DictReader(io.StringIO(r.stdout.decode('utf-8'))))


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
    filas = consulta(docker, a.contenedor, a.base, a.usuario,
        "SELECT e.matricula AS p, d.fecha AS d, d.km AS km, d.litros AS l, d.descartada AS x FROM razo_movertis_dia d "
        "JOIN razo_movertis_enlace e ON e.id = d.enlace_id WHERE d.fecha >= '%s' AND d.fecha <= '%s' AND e.matricula IS NOT NULL "
        "ORDER BY d.fecha, e.matricula" % (a.from_date, hasta))
    if not filas:
        raise RuntimeError('El ERP no tiene ningun dia de Movertis en el periodo')
    validas, descartadas, sin_matricula = [], 0, 0
    for r in filas:
        if r['x'] == 't' or r['km'] == '':
            descartadas += 1
            continue
        validas.append({'p': r['p'], 'd': r['d'], 'km': round(float(r['km']), 2), 'l': round(float(r['l']), 2) if r['l'] != '' else None})
    if not validas:
        raise RuntimeError('Ningun dia de Movertis es fiable en el periodo')
    fechas = sorted({r['d'] for r in validas})
    out = {'metadata': {'disponible': True, 'fuente': 'Movertis (razo_movertis_dia del ERP)', 'desde': fechas[0], 'hasta': fechas[-1],
                        'diasCamion': len(filas), 'diasFiables': len(validas), 'diasDescartados': descartadas,
                        'unidades': len({r['p'] for r in validas}), 'leido': datetime.datetime.now().isoformat(timespec='seconds')},
           'rows': validas}
    with open(a.output, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False)
    print(json.dumps(out['metadata'], ensure_ascii=False))


if __name__ == '__main__':
    try:
        main()
    except Exception as e:  # noqa: BLE001
        print('ERROR: %s' % e, file=sys.stderr)
        sys.exit(1)
