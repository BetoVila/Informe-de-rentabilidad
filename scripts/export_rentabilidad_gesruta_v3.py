# -*- coding: utf-8 -*-
"""Lectura reproducible de GesRuta; conserva fecha de linea y de factura e IVA."""
import sys, os, json, datetime as dt, argparse
from collections import Counter, defaultdict
from dbf_gesruta import abrir
from helpers import txt,num,iso,invoice_plate
parser=argparse.ArgumentParser()
parser.add_argument('--root',required=True)
parser.add_argument('--output',required=True)
parser.add_argument('--from-date',default='2025-01-01')
parser.add_argument('--to-date',default=(dt.date.today()-dt.timedelta(days=1)).isoformat())
args=parser.parse_args()
START, END = args.from_date,args.to_date
result = {'metadata':{'desde':START,'hasta':END,'read_at':dt.datetime.now().astimezone().isoformat()},'lines':[],'headers':[],'checks':[],'files':[]}

def key(serie,number):
    return txt(serie)+'-'+str(int(num(number)))

for company,folder in [('Razo','EMPTR21'),('Agetrans','EMPAG21')]:
    base = os.path.join(args.root,folder)
    stamps={}
    def read(table,fields):
        with abrir(base,table) as db:
            stamps[db.ruta] = os.stat(db.ruta).st_mtime_ns
            for rec in db.registros():
                yield {field:db.get(rec,field) for field in fields}
    clients={txt(r['CODIGO']):txt(r['NOMBRE']) for r in read('mascli.dbf',['CODIGO','NOMBRE'])}
    albs={}
    for r in read('albara.dbf',['VIAJE','NUMERO','CARGA','REFERE','FECHA','DESDEF','HASTAF']):
        albs[(txt(r['VIAJE']).zfill(8),txt(r['NUMERO']).zfill(2))]={'load':txt(r['CARGA']),'reference':txt(r['REFERE']),'serviceDate':iso(r['DESDEF']) or iso(r['FECHA'])}
    headers={}; duplicate_headers=[]
    fields=['SERIE','NUMERO','FECFAC','CLIENT','ANULADA','IMPFAC','IMPSUPLIDO','IMPBONIF']+[f'{p}{i}' for p in ['BASE','CUOTA','IMPRET','IMPDTOPIE'] for i in range(1,5)]
    for r in read('facturas.dbf',fields):
        k=key(r['SERIE'],r['NUMERO'])
        if not num(r['NUMERO']): continue
        h={'id':company+'|'+k,'company':company,'invoice':k,'invoiceDate':iso(r['FECFAC']),'clientId':company+'|'+txt(r['CLIENT']),'client':clients.get(txt(r['CLIENT']),'Sin cliente'), 'cancelled':bool(r['ANULADA']),'base':sum(num(r[f'BASE{i}']) for i in range(1,5)), 'vat':sum(num(r[f'CUOTA{i}']) for i in range(1,5)),'gross':num(r['IMPFAC']),'retention':sum(num(r[f'IMPRET{i}']) for i in range(1,5)), 'supplied':num(r['IMPSUPLIDO']),'discount':sum(num(r[f'IMPDTOPIE{i}']) for i in range(1,5)), 'bonus':num(r['IMPBONIF'])}
        if k in headers and START <= h['invoiceDate'] <= END: duplicate_headers.append(k)
        headers[k]=h
    invoice_sums=defaultdict(float); selected_headers=set(); lines=[]; missing=0
    line_keys=Counter()
    fields=['NUMERO','SERIE','NUMFAC','FECHA','CONCEPTO','MATRICULA','IMPORTE','IVA','SUPLIDO','CODART','CUECON','CANTIDAD','PRECIO','ALB_VIAJE','ALB_NUMERO','TIPOLINEA']
    for row_number,r in enumerate(read('linfaclib.dbf',fields)):
        k=key(r['SERIE'],r['NUMFAC']); h=headers.get(k)
        line_date=iso(r['FECHA']) or (h['invoiceDate'] if h else '')
        invoice_date=h['invoiceDate'] if h else ''
        if h and not h['cancelled']:
            invoice_sums[k] += 0 if r['SUPLIDO'] else num(r['IMPORTE'])
        if not (START<=line_date<=END or START<=invoice_date<=END): continue
        if h and h['cancelled']: continue
        plate,display=invoice_plate(r)
        trip=txt(r['ALB_VIAJE']); trip=trip.zfill(8) if trip else ''
        alb=txt(r['ALB_NUMERO']); alb=alb.zfill(2) if alb else ''
        a=albs.get((trip,alb),{})
        line_key=company+'|'+k+'|'+str(int(num(r['NUMERO'])))
        line_keys[line_key]+=1
        lines.append({'id':company+'|row|'+str(row_number),'sourceLine':int(num(r['NUMERO'])),'company':company,'invoice':k,'invoiceId':company+'|'+k,'invoiceDate':invoice_date,'lineDate':line_date,'serviceDate':a.get('serviceDate',''),'clientId':h['clientId'] if h else company+'|missing','client':h['client'] if h else 'Sin cabecera','plate':plate,'plateLabel':display,'plateSource':'Campo de factura' if txt(r['MATRICULA']) else ('Texto del concepto' if plate else 'Sin matricula'),'trip':trip,'delivery':alb,'load':a.get('load',''),'reference':a.get('reference',''),'concept':txt(r['CONCEPTO']),'article':txt(r['CODART']),'account':txt(r['CUECON']),'quantity':num(r['CANTIDAD']),'price':num(r['PRECIO']),'amount':num(r['IMPORTE']),'revenue':0 if r['SUPLIDO'] else num(r['IMPORTE']),'supplied':bool(r['SUPLIDO']),'vatRate':num(r['IVA']),'kind':'Linea GesRuta','orphan':h is None})
        if h: selected_headers.add(k)
        else: missing+=1
    for k,h in headers.items():
        if not h['cancelled'] and START<=h['invoiceDate']<=END: selected_headers.add(k)
    for k in sorted(selected_headers):
        h=headers[k]; h['lineBase']=round(invoice_sums[k],3); h['gap']=round(h['base']-invoice_sums[k],3)
        result['headers'].append(h)
        # La diferencia queda identificada, sin inventar una matricula o un viaje.
        if abs(h['gap'])>=0.005 and START<=h['invoiceDate']<=END:
            lines.append({'id':h['id']+'|adjustment','sourceLine':None,'company':company,'invoice':h['invoice'],'invoiceId':h['id'],'invoiceDate':h['invoiceDate'],'lineDate':h['invoiceDate'],'serviceDate':'','clientId':h['clientId'],'client':h['client'],'plate':'','plateLabel':'SIN VEHICULO','plateSource':'Ajuste de cabecera','trip':'','delivery':'','load':'','reference':'','concept':'Diferencia base cabecera / lineas (revisar)','article':'','account':'','quantity':0,'price':0,'amount':h['gap'],'revenue':h['gap'],'supplied':False,'vatRate':None,'kind':'Ajuste de cabecera','orphan':False})
    for p,stamp in stamps.items():
        if os.stat(p).st_mtime_ns != stamp: raise RuntimeError('El origen cambio durante la lectura: '+p)
        result['files'].append({'path':p,'modified':dt.datetime.fromtimestamp(stamp/1e9).astimezone().isoformat()})
    result['checks'].append({'company':company,'duplicateHeaderKeys':duplicate_headers,'duplicateLineKeys':sum(v-1 for v in line_keys.values() if v>1),'orphanLines':missing})
    result['lines']+=lines
out=args.output
with open(out,'w',encoding='utf-8') as f: json.dump(result,f,ensure_ascii=False,separators=(',',':'))
print(json.dumps({'lines':len(result['lines']),'headers':len(result['headers']),'checks':result['checks'],'output':out},ensure_ascii=False))
