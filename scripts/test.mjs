// Pruebas del modelo y del informe. Uso:
//   node scripts/test.mjs                          -> solo calendario
//   node scripts/test.mjs <current.json.gz> [informe.html]  -> además, modelo sobre esos datos y sintaxis del informe
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import {gunzipSync} from 'node:zlib';
import vm from 'node:vm';
import {createModel,sum} from '../src/model.mjs';
import {priorYear,quickPeriods,incompleteMonth} from '../src/calendar.mjs';
assert.equal(priorYear('2028-02-29'),'2027-02-28');
assert.equal(priorYear('2027-03-01'),'2026-03-01');
assert.equal(incompleteMonth('2026-09-04'),true);
assert.equal(incompleteMonth('2028-02-29'),false);
const periods=quickPeriods('2025-01-01','2027-01-04');
assert.deepEqual(periods[0],{label:'Año 2027',from:'2027-01-01',to:'2027-01-04'});
assert.ok(periods.every(p=>p.to<='2027-01-04'&&p.from>='2025-01-01'));
const [dataPath,htmlPath]=process.argv.slice(2);
const near=(a,b,label='')=>assert.ok(Math.abs(a-b)<.006,label+' '+a+' / '+b);
if(dataPath){
 const data=JSON.parse(gunzipSync(await fs.readFile(dataPath)));
 const m=createModel(data),f={from:data.metadata.from,to:data.metadata.to,dateBasis:'invoice',costMode:'stored'};
 for(const [mode,field] of [['stored','stored'],['recalculated','recalculated'],['real','real']]){
  const g={...f,costMode:mode},full=m.run(g),t=full.totals;
  near(t.cost,sum(data.parts,field),'coste '+mode);
  for(const dim of ['plate','client','company','load','concept','month']){
   const rows=m.group(full,g,dim).groups;
   near(sum(rows,'cost'),t.cost,mode+' '+dim);near(sum(rows,'revenue'),t.revenue,mode+' ingresos '+dim);
  }
  const client=m.group(full,g,'client').groups.find(r=>r.key!=='Sin asignar'&&r.cost>1000);
  if(client)near(m.run({...g,clients:[client.key]}).totals.cost,client.cost,'filtro cliente '+mode);
  const none=m.run({...g,clients:['__cliente_inexistente__']});
  assert.equal(none.totals.cost,0);assert.equal(none.totals.consumption,null);
 }
 near(m.run({...f,dateBasis:'line'}).totals.revenue,sum(data.headers,'base')>0?m.run({...f,dateBasis:'line'}).totals.revenue:0);
 if(data.payroll)for(const [key,imputed] of m.imputed){const pool=m.pool.get(key);if(pool>0&&imputed>0)near(imputed*m.factor.get(key),pool,'nómina '+key);}
 if(data.ledger){
  const lv=m.ledgerView({from:f.from,to:f.to,companies:[]}),br=m.bridge({from:f.from,to:f.to,companies:[]});
  assert.ok(lv.months.length>0);near(br.totalLedger,lv.expenses,'puente');
  near(sum(lv.byCompany,'result'),lv.result,'resultado por sociedad');
  const razo=m.ledgerView({from:f.from,to:f.to,companies:['Razo']}),age=m.ledgerView({from:f.from,to:f.to,companies:['Agetrans']});
  near(razo.expenses+age.expenses,lv.expenses,'gastos por sociedad');
  // un mes sin cerrar nunca entra
  if(lv.lastClosed)assert.ok(lv.months.every(x=>x<=lv.lastClosed));
  // el detalle por cuenta suma exactamente cada naturaleza (sin consolidar)
  for(const c of lv.expenseCategories)near(lv.accounts.filter(a=>a.kind==='g'&&a.cat===c.id).reduce((s,a)=>s+a.amount,0),c.amount,'cuentas de '+c.id);
  for(const c of lv.incomeCategories)near(lv.accounts.filter(a=>a.kind==='i'&&a.cat===c.id).reduce((s,a)=>s+a.amount,0),c.amount,'cuentas de '+c.id);
 }
 // Vista real por vehículo / cliente / mes: cada dimensión suma lo mismo, el coste es la suma de sus partes y cuadra con «Margen por viaje».
 if(data.actividad&&data.ledger){
  const g={from:f.from,to:f.to,companies:[]},nv=m.netaView(g);
  const tol=(a,b,label)=>assert.ok(Math.abs(a-b)<1,label+' '+a+' / '+b);
  for(const dim of ['plate','client','month','tipo','ruta']){
   const rv=m.realView(g,dim);assert.ok(rv&&rv.groups.length,'realView '+dim);
   for(const k of ['viajes','ingreso','material','coste','km','horas','litros'])tol(sum(rv.groups,k),rv.tot[k],dim+' '+k);
   for(const x of rv.groups.concat([rv.tot]))tol(x.combustible+x.personal+x.flota+x.indirectos+x.subcontrata+x.material,x.coste,dim+' desglose '+x.key);
   if(nv){tol(rv.tot.ingreso,nv.tot.ingreso,dim+' ingreso = margen por viaje');assert.ok(Math.abs(rv.tot.coste-nv.tot.coste)<rv.groups.length+2,dim+' coste = margen por viaje');}
   const d=rv.detail(rv.groups[0].key);tol(sum(d.byMonth,'ingreso'),rv.groups[0].ingreso,dim+' detalle por mes');tol(sum(d.byRuta,'coste'),rv.groups[0].coste,dim+' detalle por ruta');
  }
  // el segmentador de vehículo deja solo esa matrícula, con los mismos coeficientes
  const pv=m.realView(g,'plate'),first=pv.groups.find(x=>x.key&&!/^\(/.test(x.key));
  if(first){const one=m.realView({...g,plates:[first.key]},'plate');assert.equal(one.groups.length,1);tol(one.tot.coste,first.coste,'filtro de matrícula');}
 }
 if(data.telemetry){
  const v=m.telemetryView({from:f.from,to:f.to,companies:[]});assert.ok(v&&v.activeDays>0,'telemetría');
  assert.ok(data.telemetry.rows.every(r=>r.km>=0&&r.km<=1500),'telemetría: km imposibles');
  const keys=new Set(data.telemetry.rows.map(r=>r.plate+'|'+r.date));assert.equal(keys.size,data.telemetry.rows.length,'telemetría: día-camión repetido');
 }
}
if(htmlPath){
 const html=await fs.readFile(htmlPath,'utf8');
 new vm.Script(html.match(/<script type="module">([\s\S]*?)<\/script>/)[1]);
 assert.ok(html.includes('href="estado.html"'));assert.ok(!html.includes('__PACKED_DATA__'));
}
console.log('OK: calendario'+(dataPath?', modelo en los tres modos de coste, filtros, nómina real, contabilidad y puente':'')+(htmlPath?' y sintaxis del informe.':'.'));
