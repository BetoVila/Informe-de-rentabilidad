"""Fuentes de gasto en solo lectura. Conserva el documento; nunca suma sus copias como gastos nuevos."""
import argparse
import datetime as dt
import decimal
import json
import os
import pathlib
import socket
import re
import xmlrpc.client
import sys

# El motor nocturno incluye su propio Python. No depende de paquetes del perfil personal.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / 'vendor' /
                       ('python%d%d' % sys.version_info[:2])))


def json_value(value):
    if isinstance(value, (dt.date, dt.datetime)): return value.isoformat()
    if isinstance(value, decimal.Decimal): return float(value)
    raise TypeError(type(value).__name__)


def atomico(path, value):
    path = pathlib.Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False, default=json_value), encoding='utf-8')
    os.replace(tmp, path)


def leer_seguros(ruta):
    import pyodbc
    conexion = pyodbc.connect(r'DRIVER={Microsoft Access Driver (*.mdb, *.accdb)};DBQ='+ruta+';', readonly=True)
    try:
        cur = conexion.cursor()
        def leer(tabla, campos):
            cur.execute('SELECT '+','.join('['+x+']' for x in campos)+' FROM ['+tabla+']')
            return [dict(zip(campos, row)) for row in cur.fetchall()]
        polizas = leer('Póliza', ['IdPóliza','Nº Poliza','IdCíaSeguros','IdMaquina','IdTomador','fecha_baja'])
        recibos = leer('ReciboSeguro', ['IdRecibo Seguro','IdPoliza','Nº Recibo','Inicio cobertura','Fin cobertura','Importe','FechaRecibo','Devuelto'])
        maquinas = leer('Máquinas', ['IdMáquina','Matrícula','Titular','IdCategoría','FechaCompra','FechaDeVenta','PrecioCompra'])
        cias = leer('CíaSeguros', ['IdCiaSeguros','NombreCiaSeguros'])
        tomadores = leer('TomadorPolizaSeguro', ['IdTomador','ApellidosYNombreTomador','DNI'])
        vinculaciones = leer('PolizaMaquina', ['IdPoliza','IdMaquina','FechaInclusión','FechaExclusion'])
    finally:
        conexion.close()
    pm = {x['IdPóliza']:x for x in polizas}; mm = {x['IdMáquina']:x for x in maquinas}
    cm = {x['IdCiaSeguros']:x['NombreCiaSeguros'] for x in cias}
    empresas = {'B15226095':'Razo','B15938442':'Agetrans'}
    # Vinculos verificados contra el maestro: nunca se deduce la sociedad del propietario actual del camion.
    nombres={'TRANSPORTES RAZO, S.L.':'Razo','AGETRANS BERGANTIÑOS, S.L.':'Agetrans'}
    tm = {x['IdTomador']:empresas.get(re.sub(r'[^A-Z0-9]','',str(x['DNI'] or '').upper()).removeprefix('ES'))
          or nombres.get((x['ApellidosYNombreTomador'] or '').strip().upper(),'Sin sociedad identificada') for x in tomadores}
    rows=[]
    for r in recibos:
        p=pm.get(r['IdPoliza'],{}); mid=p.get('IdMaquina'); maquina=mm.get(mid,{})
        asociaciones=[{'matricula':mm.get(v['IdMaquina'],{}).get('Matrícula'), 'desde':v['FechaInclusión'], 'hasta':v['FechaExclusion']}
                      for v in vinculaciones if v['IdPoliza']==r['IdPoliza']]
        rows.append({'id':'SEGUROS:'+str(r['IdRecibo Seguro']), 'fuente':'Access Seguros / ReciboSeguro', 'tipo':'seguro',
            'empresa':tm.get(p.get('IdTomador'),'Sin sociedad identificada'), 'empresa_fuente':'Tomador de poliza '+str(p.get('IdTomador')),
            'proveedor':cm.get(p.get('IdCíaSeguros')),
            'documento':r['Nº Recibo'], 'poliza':p.get('Nº Poliza'), 'fecha':r['FechaRecibo'],
            'cobertura_desde':r['Inicio cobertura'], 'cobertura_hasta':r['Fin cobertura'], 'importe':r['Importe'],
            'devuelto':bool(r['Devuelto']), 'matricula':maquina.get('Matrícula'), 'vehiculos_cubiertos':asociaciones,
            'criterio':'Recibo documentado; se coteja con contabilidad. No se suma de nuevo al gasto contable.',
            'estado':'devuelto_revisar' if r['Devuelto'] else 'documentado', 'naturaleza_importe':'total_recibo'})
    return {'generado':dt.datetime.now().astimezone().isoformat(), 'fuente':ruta, 'polizas':len(polizas), 'rows':rows}


def leer_gesruta(raiz, desde, hasta):
    from dbf_gesruta import abrir
    rows=[]; controls=[]
    for empresa,carpeta in [('Razo','EMPTR21'),('Agetrans','EMPAG21')]:
        base=os.path.join(raiz,carpeta); stamps={}
        def read(nombre,campos):
            with abrir(base,nombre) as db:
                stamps[db.ruta]=os.stat(db.ruta).st_mtime_ns
                for record in db.registros():yield {c:db.get(record,c) for c in campos}
        proveedores={str(r['CODIGO']).strip():r for r in read('provee.dbf',['CODIGO','NOMBRE','NIF'])}
        viajes={str(r['CODIGO']).strip():str(r['MATRI1'] or '').strip() for r in read('viaje.dbf',['CODIGO','MATRI1'])}
        campos=['ASIENTO','TIPO','FECHA','IMPORTED','IMPORTEH','CONCEPTO','VIAJE','ALBARAN','VEHICU','LITROS','PRECIO',
                'NUMVAL','FACTURA','PROVEE','NUMFACPROV','FC_SERIE','FC_NUMFAC','ENLACONTA']
        for i,r in enumerate(read('inggas.dbf',campos)):
            fecha=r['FECHA'];fecha=fecha.isoformat() if fecha else ''
            if str(r['TIPO'] or '').strip()!='G' or not desde<=fecha<=hasta:continue
            proveedor=proveedores.get(str(r['PROVEE'] or '').strip(),{})
            rows.append({'id':'GESRUTA:'+carpeta+':inggas:'+str(r['ASIENTO'])+':'+str(i), 'empresa':empresa,
                'fecha':fecha,'importe':float(r['IMPORTED'] or 0)-float(r['IMPORTEH'] or 0),'concepto':str(r['CONCEPTO'] or '').strip(),
                'proveedor':proveedor.get('NOMBRE'),'nif_proveedor':proveedor.get('NIF'), 'proveedor_codigo':r['PROVEE'],
                'documento':r['NUMFACPROV'] or r['FACTURA'] or '', 'factura_gesruta':str(r['FC_SERIE'] or '')+'-'+str(r['FC_NUMFAC'] or ''),
                'viaje':r['VIAJE'],'albaran':r['ALBARAN'],'matricula':viajes.get(str(r['VIAJE'] or '').strip()),
                'litros':r['LITROS'],'precio':r['PRECIO'],'vale':r['NUMVAL'], 'enlazado_contabilidad':bool(r['ENLACONTA']),
                'naturaleza_importe':'gasto_operativo_GesRuta','fuente':'GesRuta / inggas.dbf'})
        for ruta,stamp in stamps.items():
            if os.stat(ruta).st_mtime_ns!=stamp:raise RuntimeError('El origen cambio durante la lectura: '+ruta)
        controls.append({'empresa':empresa,'ficheros':len(stamps),'filas':sum(x['empresa']==empresa for x in rows)})
    return {'generado':dt.datetime.now().astimezone().isoformat(),'desde':desde,'hasta':hasta,'fuente':raiz,'control':controls,'rows':rows}


def leer_softic(desde,hasta):
    socket.setdefaulttimeout(60)
    url=os.environ.get('SOFTIC_URL','https://razo.ddb1.softic.es').rstrip('/')
    bd=os.environ.get('SOFTIC_BD'); user=os.environ.get('SOFTIC_USUARIO'); clave=os.environ.get('SOFTIC_CLAVE')
    if not all([bd,user,clave]): raise RuntimeError('Faltan las variables de acceso a Softic')
    common=xmlrpc.client.ServerProxy(url+'/xmlrpc/2/common')
    uid=common.authenticate(bd,user,clave,{})
    if not uid: raise RuntimeError('Softic no autentica')
    obj=xmlrpc.client.ServerProxy(url+'/xmlrpc/2/object')
    context={'active_test':False,'prefetch_fields':False}
    def call(model,method,args,kwargs=None):
        if method not in {'search_read','search_count','fields_get','read'}:raise ValueError('Solo lectura')
        return obj.execute_kw(bd,uid,clave,model,method,args,{'context':context,**(kwargs or {})})
    def read(model,domain,fields):
        # Techo fijo de ID y paginacion por clave: una insercion durante la lectura no desplaza paginas.
        last=call(model,'search_read',[domain, ['id']],{'order':'id desc','limit':1})
        if not last:return []
        bound=domain+[('id','<=',last[0]['id'])]; expected=call(model,'search_count',[bound])
        rows=[]; cursor=0
        while True:
            batch=call(model,'search_read',[bound+[('id','>',cursor)],fields],{'order':'id','limit':500})
            if not batch:break
            rows.extend(batch);cursor=batch[-1]['id']
        if len(rows)!=expected:raise RuntimeError('Cambio de origen durante lectura: '+model)
        return rows
    empresas=read('res.company',[],['name','vat'])
    context['allowed_company_ids']=[x['id'] for x in empresas]
    cuentas=read('account.account',[('code','=like','6%')],['code','name','company_id'])
    rows=read('account.move.line',[('account_id','in',[x['id'] for x in cuentas]),('date','>=',desde),('date','<=',hasta),('parent_state','=','posted')],
        ['move_id','move_name','date','company_id','account_id','name','debit','credit','balance','partner_id','vehicle_id','purchase_line_id','invoice_date','ref','write_date'])
    moves=read('account.move',[('id','in',sorted({x['move_id'][0] for x in rows}))],['name','ref','invoice_date','move_type','state','partner_id','company_id','amount_untaxed','amount_total','write_date']) if rows else []
    vehicles=read('fleet.vehicle',[('id','in',sorted({x['vehicle_id'][0] for x in rows if x['vehicle_id']}))],['license_plate','company_id']) if any(x['vehicle_id'] for x in rows) else []
    return {'generado':dt.datetime.now().astimezone().isoformat(),'desde':desde,'hasta':hasta,'fuente':url,
        'estado':'posted','empresas':empresas,'cuentas':cuentas,'documentos':moves,'vehiculos':vehicles,'rows':rows}


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--fuente',choices=['seguros','softic','gesruta'],required=True)
    ap.add_argument('--output',required=True)
    ap.add_argument('--seguros',default=r'\\servidor\Documentos\SEGUROS\BaseDatosSEGUROS\Seguros.accdb')
    ap.add_argument('--gesruta',default=r'\\servidor\Programas\Gesruta')
    ap.add_argument('--desde',default='2025-01-01');ap.add_argument('--hasta',default=(dt.date.today()-dt.timedelta(days=1)).isoformat())
    a=ap.parse_args()
    if a.fuente=='seguros':out=leer_seguros(a.seguros)
    elif a.fuente=='gesruta':out=leer_gesruta(a.gesruta,a.desde,a.hasta)
    else:out=leer_softic(a.desde,a.hasta)
    atomico(a.output,out)
    print(json.dumps({'fuente':a.fuente,'filas':len(out['rows']),'generado':out['generado']},ensure_ascii=False))


if __name__=='__main__':main()
