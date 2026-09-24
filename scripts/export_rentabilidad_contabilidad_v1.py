# -*- coding: utf-8 -*-
"""Contabilidad real (CxConta) para el informe de rentabilidad. SOLO LECTURA.

La contabilidad de las dos sociedades ya la trae el ERP a su base (espejo `razo_cxconta_apunte`, importado cada noche
desde CxConta). Aqui no se vuelve a leer CxConta: se le pregunta al ERP por los totales de gastos (grupo 6) e ingresos
(grupo 7) por sociedad, mes y cuenta. Es una consulta SELECT agregada: no baja apuntes sueltos, ni terceros, ni importes
de una factura.

Sin claves: se llama a `docker exec <contenedor> psql` como el resto de tareas de la casa. Si Docker o la base no estan
disponibles, sale con error y el informe sigue sin esta fuente (nunca se rellena con ceros).
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
    # Solo apuntes ordinarios: los de cierre y apertura mueven las mismas cuentas sin ser gasto ni ingreso del mes.
    apuntes = consulta(docker, a.contenedor, a.base, a.usuario,
        "SELECT company_id, to_char(fecha,'YYYY-MM') AS mes, cuenta_codigo AS cuenta, round(sum(debe)::numeric,2) AS debe, "
        "round(sum(haber)::numeric,2) AS haber, count(*) AS n FROM razo_cxconta_apunte WHERE clase='ordinario' "
        "AND fecha >= '%s' AND fecha <= '%s' AND (cuenta_codigo LIKE '6%%' OR cuenta_codigo LIKE '7%%') GROUP BY 1,2,3 ORDER BY 1,2,3"
        % (a.from_date, hasta))
    nombres = consulta(docker, a.contenedor, a.base, a.usuario,
        "SELECT DISTINCT ON (code) code, name FROM account_account WHERE code LIKE '6%' OR code LIKE '7%' ORDER BY code, company_id")
    # El detalle conserva la identidad de cada apunte. Sirve para cotejar documentos de otras apps,
    # nunca para volver a sumarlos sobre los totales anteriores.
    detalle = consulta(docker, a.contenedor, a.base, a.usuario,
        "SELECT a.cxconta_key AS id,a.company_id,a.fecha,a.ejercicio,a.libro,a.asiento,a.linea,"
        "a.cuenta_codigo AS cuenta,coalesce(c.name,'') AS cuenta_nombre,a.documento,a.concepto,"
        "a.debe,a.haber,(a.debe-a.haber) AS importe FROM razo_cxconta_apunte a "
        "LEFT JOIN razo_cxconta_cuenta c ON c.id=a.cuenta_id WHERE a.clase='ordinario' "
        "AND a.fecha>='%s' AND a.fecha<='%s' AND a.cuenta_codigo LIKE '6%%' ORDER BY a.company_id,a.fecha,a.asiento,a.linea"
        % (a.from_date,hasta))
    meta = consulta(docker, a.contenedor, a.base, a.usuario,
        "SELECT company_id, max(fecha) AS max_fecha, count(*) AS n FROM razo_cxconta_apunte WHERE clase='ordinario' "
        "AND fecha <= '%s' GROUP BY 1 ORDER BY 1" % hasta)
    # Intragrupo (facturacion consolidada): un asiento es intragrupo si toca una cuenta de EMPRESAS DEL GRUPO del PGC.
    # Clientes grupo 433-436 -> las patas 7xx del asiento son ingreso intragrupo; proveedores grupo 403-406 -> las 6xx
    # son gasto intragrupo. No se usa el tercero (el apunte no lo trae) ni se cablea ninguna cuenta concreta. La 552
    # (cuenta corriente con el grupo) es tesoreria, no P&L, y no entra. Medido, verificado contra los albaranes de GesRuta.
    intra_ing = consulta(docker, a.contenedor, a.base, a.usuario,
        "WITH grp AS (SELECT DISTINCT company_id,ejercicio,libro,asiento FROM razo_cxconta_apunte WHERE clase='ordinario' "
        "AND fecha>='%s' AND fecha<='%s' AND (cuenta_codigo LIKE '433%%' OR cuenta_codigo LIKE '434%%' OR cuenta_codigo LIKE '435%%' OR cuenta_codigo LIKE '436%%')) "
        "SELECT a.company_id, to_char(a.fecha,'YYYY-MM') AS mes, round(sum(CASE WHEN a.cuenta_codigo LIKE '7%%' THEN a.haber-a.debe ELSE 0 END)::numeric,2) AS importe "
        "FROM razo_cxconta_apunte a JOIN grp ON grp.company_id=a.company_id AND grp.ejercicio=a.ejercicio AND grp.libro=a.libro AND grp.asiento=a.asiento "
        "WHERE a.clase='ordinario' GROUP BY 1,2 ORDER BY 1,2" % (a.from_date, hasta))
    intra_gas = consulta(docker, a.contenedor, a.base, a.usuario,
        "WITH grp AS (SELECT DISTINCT company_id,ejercicio,libro,asiento FROM razo_cxconta_apunte WHERE clase='ordinario' "
        "AND fecha>='%s' AND fecha<='%s' AND (cuenta_codigo LIKE '403%%' OR cuenta_codigo LIKE '404%%' OR cuenta_codigo LIKE '405%%' OR cuenta_codigo LIKE '406%%')) "
        "SELECT a.company_id, to_char(a.fecha,'YYYY-MM') AS mes, round(sum(CASE WHEN a.cuenta_codigo LIKE '6%%' THEN a.debe-a.haber ELSE 0 END)::numeric,2) AS importe "
        "FROM razo_cxconta_apunte a JOIN grp ON grp.company_id=a.company_id AND grp.ejercicio=a.ejercicio AND grp.libro=a.libro AND grp.asiento=a.asiento "
        "WHERE a.clase='ordinario' GROUP BY 1,2 ORDER BY 1,2" % (a.from_date, hasta))
    if not apuntes:
        raise RuntimeError('La contabilidad no devuelve ningun apunte de gasto ni de ingreso en el periodo')
    rows = [{'company': int(r['company_id']), 'month': r['mes'], 'cuenta': r['cuenta'], 'debe': float(r['debe']),
             'haber': float(r['haber']), 'n': int(r['n'])} for r in apuntes]
    intra = {}
    for r in intra_ing:
        k = (int(r['company_id']), r['mes']); intra.setdefault(k, {'ingreso': 0.0, 'gasto': 0.0})['ingreso'] = float(r['importe'] or 0)
    for r in intra_gas:
        k = (int(r['company_id']), r['mes']); intra.setdefault(k, {'ingreso': 0.0, 'gasto': 0.0})['gasto'] = float(r['importe'] or 0)
    intragrupo_rows = [{'company': k[0], 'month': k[1], 'ingreso': round(v['ingreso'], 2), 'gasto': round(v['gasto'], 2)}
                       for k, v in sorted(intra.items())]
    out = {'metadata': {'disponible': True, 'fuente': 'CxConta (espejo razo_cxconta_apunte del ERP)', 'desde': a.from_date,
                        'hasta': hasta, 'apuntesAgregados': len(rows),
                        'maxFechaPorSociedad': {m['company_id']: m['max_fecha'] for m in meta},
                        'leido': datetime.datetime.now().isoformat(timespec='seconds')},
           'accounts': {r['code']: r['name'] for r in nombres}, 'rows': rows,
           'detalleGastos': [{**r,'company_id':int(r['company_id']), 'importe':float(r['importe']),
                              'debe':float(r['debe']), 'haber':float(r['haber'])} for r in detalle],
           'intragrupo': {'metodo': 'Asientos que tocan cuentas de empresas del grupo (clientes 433-436 -> ingreso 7xx; proveedores 403-406 -> gasto 6xx)',
                          'rows': intragrupo_rows}}
    with open(a.output, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False)
    print(json.dumps({'disponible': True, 'filas': len(rows), 'cuentas': len(out['accounts']),
                      'meses': sorted({r['month'] for r in rows})[-3:], 'maxFecha': out['metadata']['maxFechaPorSociedad'],
                      'intragrupoIngreso': round(sum(r['ingreso'] for r in intragrupo_rows), 2),
                      'intragrupoGasto': round(sum(r['gasto'] for r in intragrupo_rows), 2)},
                     ensure_ascii=False))


if __name__ == '__main__':
    try:
        main()
    except Exception as e:  # noqa: BLE001
        print('ERROR: %s' % e, file=sys.stderr)
        sys.exit(1)
