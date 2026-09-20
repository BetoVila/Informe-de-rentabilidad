import fs from 'node:fs/promises';
import path from 'node:path';
import assert from 'node:assert/strict';
import {gunzipSync,gzipSync} from 'node:zlib';
import {createHash} from 'node:crypto';
import {createModel,sum,inRange} from '../src/model.mjs';
import {criptoCifrar,criptoDescifrar} from '../src/cripto.mjs';
const [input,output,mode='pending',at='03:00']=process.argv.slice(2);
if(!input||!output)throw new Error('Indique datos de entrada y carpeta de salida');
const data=JSON.parse(gunzipSync(await fs.readFile(input)));
const close=(a,b,label)=>assert.ok(Number.isFinite(a)&&Number.isFinite(b)&&Math.abs(a-b)<.006,label+': '+a+' / '+b);
assert.ok(data.parts.length&&data.headers.length,'No se publica una extracción vacía');
assert.equal(new Set(data.parts.map(p=>p.id)).size,data.parts.length,'Partes duplicados');
assert.equal(new Set(data.lines.map(p=>p.id)).size,data.lines.length,'Líneas duplicadas');
assert.ok(data.sourceControls.gesruta.every(c=>!c.duplicateHeaderKeys.length&&!c.duplicateLineKeys&&!c.orphanLines),'Claves o cabeceras de GesRuta incoherentes');
// Los km imposibles (>1.500 en un parte) se excluyen de los totales pero siguen en el control contra la base de Access.
for(const [key,field] of [['direct','directo'],['structure','estructura'],['km','km']])close(sum(data.parts,key)+(key==='km'?sum(data.parts,'kmExcluded'):0),data.sourceControls.access[field],'Control SQL '+key);
assert.equal(data.parts.length,data.sourceControls.access.partes,'Recuento SQL independiente');
const model=createModel(data),period={from:data.metadata.from,to:data.metadata.to,dateBasis:'invoice',costMode:'stored'};
const full=model.run(period);
close(full.totals.revenue,sum(data.headers.filter(h=>inRange(h.invoiceDate,period.from,period.to)),'base'),'Bases de factura');
close(full.totals.cost,sum(data.parts,'stored'),'Total Access incl. no asignado');
close(full.totals.km,sum(data.parts,'km'),'Kilómetros sin duplicar');
for(const dimension of ['plate','client','company','load','concept','month']){
 const groups=model.group(full,period,dimension).groups;
 for(const key of ['revenue','cost','km'])close(sum(groups,key),full.totals[key],dimension+' '+key);
}
// Los tres modos de coste: el total es la suma de los partes y todo desglose cuadra con él.
for(const [mode,field] of [['stored','stored'],['recalculated','recalculated'],['real','real']]){
 const r=model.run({...period,costMode:mode});
 close(r.totals.cost,sum(data.parts,field),'Coste total '+mode);
 for(const dimension of ['plate','month','company'])close(sum(model.group(r,{...period,costMode:mode},dimension).groups,'cost'),r.totals.cost,'Coste '+mode+' por '+dimension);
 close(sum(Object.entries(r.totals.breakdown).map(([k,v])=>({v})),'v'),r.totals.cost,'Desglose del coste '+mode);
}
// Nómina real: el conductor de los partes de cada mes y tipo de trabajo suma exactamente la nómina de la gestoría.
if(data.payroll){
 let checked=0;
 for(const [key,imputedAmount] of model.imputed){const pool=model.pool.get(key);if(!(pool>0)||!(imputedAmount>0))continue;close(imputedAmount*model.factor.get(key),pool,'Nómina real '+key);checked++;}
 assert.ok(checked>0,'Nómina real: ningún mes cuadrado');
 // Hay correcciones negativas legítimas en Access (unos euros): solo se exige que el importe sea un número.
 assert.ok(data.parts.every(p=>Number.isFinite(p.real)&&Number.isFinite(p.realFactor)&&p.realFactor>0),'Coste con nómina real inválido');
}
// Contabilidad: cada resumen cuadra con sus partes y el puente cierra con el total.
if(data.ledger){
 const f={from:data.metadata.from,to:data.metadata.to,companies:[]},lv=model.ledgerView(f),br=model.bridge(f);
 assert.ok(lv.months.length,'Contabilidad sin ningún mes cerrado');
 close(sum(lv.byMonth,'income'),lv.income,'Contabilidad ingresos por mes');close(sum(lv.byMonth,'expenses'),lv.expenses,'Contabilidad gastos por mes');
 close(sum(lv.expenseCategories,'amount'),lv.expenses,'Contabilidad gastos por categoría');close(sum(lv.incomeCategories,'amount'),lv.income,'Contabilidad ingresos por categoría');
 close(sum(lv.byCompany,'expenses'),lv.expenses,'Contabilidad gastos por sociedad');
 close(br.totalLedger,lv.expenses,'Puente: la contabilidad del puente es todo el gasto');
 for(const company of ['Razo','Agetrans'])close(model.ledgerView({...f,companies:[company]}).expenses,lv.byCompany.find(c=>c.key===company).expenses,'Contabilidad '+company);
 // Facturación consolidada: eliminar el intragrupo Razo↔Agetrans debe cuadrar en todas las agregaciones.
 assert.ok(lv.intragrupo&&lv.intragrupo.income>0,'Intragrupo: no se ha medido ingreso entre las empresas');
 const lc=model.ledgerView({...f,consolidado:true});
 close(lc.income,lv.income-lv.intragrupo.income,'Consolidado: ingresos = suma − ingreso intragrupo');
 close(lc.expenses,lv.expenses-lv.intragrupo.expense,'Consolidado: gastos = suma − gasto intragrupo');
 close(lc.result,lv.result-(lv.intragrupo.income-lv.intragrupo.expense),'Consolidado: resultado = suma − neto intragrupo');
 close(sum(lc.incomeCategories,'amount'),lc.income,'Consolidado: ingresos por categoría');
 close(sum(lc.expenseCategories,'amount'),lc.expenses,'Consolidado: gastos por categoría');
 close(sum(lc.byMonth,'income'),lc.income,'Consolidado: ingresos por mes');close(sum(lc.byMonth,'expenses'),lc.expenses,'Consolidado: gastos por mes');
 close(sum(lc.byCompany,'expenses'),lc.expenses,'Consolidado: gastos por sociedad');
}
for(const company of ['Razo','Agetrans']){
 const expected=model.group(full,period,'company').groups.find(g=>g.key===company);
 if(expected)close(model.run({...period,companies:[company]}).totals.cost,expected.cost,'Filtro empresa '+company);
}
const sourceList=data.metadata.sources||[];
const readSources=sourceList.filter(s=>s.state==='ok'||s.state==='parcial').map(s=>s.name),missingSources=sourceList.filter(s=>s.state!=='ok'&&s.state!=='parcial').map(s=>s.name);
data.metadata.refresh={mode,at,host:process.env.COMPUTERNAME||'SERVIDOR',sources:readSources};
data.definitions=data.definitions.filter(t=>!t.startsWith('Movertis y Locatel:'));
data.definitions.push('Fuentes de esta lectura: '+(readSources.join(', ')||'ninguna')+(missingSources.length?'. Sin lectura automática todavía: '+missingSources.join(', ')+'.':'.')+' El informe conserva el último corte válido si hay un fallo; consulte Estado de actualización. Los gastos y el consumo que traen los partes de Access son DECLARADOS por quien los rellena, no reales: lo real es la tarjeta Solred, el surtidor de la nave, la nómina de la gestoría y, para kilómetros y consumo, los localizadores (Movertis y Locatel).');
const read=p=>fs.readFile(new URL('../src/'+p,import.meta.url),'utf8');
const [template,css,modelText,calendar,cripto,app]=await Promise.all(['dashboard.html','dashboard.css','model.mjs','calendar.mjs','cripto.mjs','app.mjs'].map(read));
const packed=gzipSync(JSON.stringify(data),{level:9}).toString('base64');
// Capa PRIVADA de personal (nombres y costes por persona): solo viaja CIFRADA con la clave que elige Roberto. Sin clave, o sin
// capa privada en esta lectura, el apartado no existe en el informe. El fichero en claro nunca se publica.
let personalBlob='',personalInfo=null;
{
 const clave=process.env.RENTABILIDAD_CLAVE_PERSONAL||'';let text=null;
 try{text=await fs.readFile(path.join(path.dirname(input),'personal_private.json'),'utf8');}catch(e){if(e.code!=='ENOENT')throw e;}
 if(text&&clave){
  personalBlob=await criptoCifrar(text,clave);
  assert.equal(await criptoDescifrar(personalBlob,clave),text,'El apartado de personal no descifra con su clave');
  const p=JSON.parse(text);personalInfo={cifrado:true,personas:p.people.length,casadas:p.match.casadas,total:p.match.total};
 }
}
const script=[modelText,calendar,cripto].map(s=>s.replace(/^export /gm,'')).join('\n')+'\n'+app.replace('__PACKED_DATA__',()=>packed).replace('__PACKED_PERSONAL__',()=>personalBlob);
const html=template.replace('/*__STYLE__*/',()=>css).replace('/*__MODEL__*/',()=>script).replace('/*__APP__*/','');
assert.ok(!html.includes('__PACKED_DATA__')&&!html.includes('__PACKED_PERSONAL__'));
await fs.mkdir(output,{recursive:true});
await fs.writeFile(path.join(output,'informe.html'),html);
const receipt={ok:true,validatedAt:new Date().toISOString(),readAt:data.metadata.generatedAt,from:period.from,to:period.to,sha256:createHash('sha256').update(html).digest('hex'),parts:data.parts.length,lines:data.lines.length,sourceHashes:data.metadata.sourceHashes,sourcesText:readSources.join(' + '),personal:personalInfo,ledger:data.ledger?{lastClosed:data.ledger.meta.lastClosed,rows:data.ledger.rows.length}:null,mode,at,totals:full.totals,internalDifferences:data.parts.filter(p=>Math.abs(p.residual)>.01).length};
await fs.writeFile(path.join(output,'verification.json'),JSON.stringify(receipt,null,2));
console.log(JSON.stringify({ok:true,parts:receipt.parts,lines:receipt.lines,sha256:receipt.sha256,mode}));
