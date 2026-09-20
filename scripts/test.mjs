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
 }
}
if(htmlPath){
 const html=await fs.readFile(htmlPath,'utf8');
 new vm.Script(html.match(/<script type="module">([\s\S]*?)<\/script>/)[1]);
 assert.ok(html.includes('href="estado.html"'));assert.ok(!html.includes('__PACKED_DATA__'));
}
console.log('OK: calendario'+(dataPath?', modelo en los tres modos de coste, filtros, nómina real, contabilidad y puente':'')+(htmlPath?' y sintaxis del informe.':'.'));
