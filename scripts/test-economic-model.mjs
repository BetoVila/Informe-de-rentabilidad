import fs from 'node:fs';
import assert from 'node:assert/strict';
import {gunzipSync} from 'node:zlib';
import {createModel} from '../src/model.mjs';
const d=JSON.parse(gunzipSync(fs.readFileSync(process.argv[2]))),m=createModel(d);
const f={from:'2026-01-01',to:'2026-08-31',dateBasis:'invoice',companies:[],plates:[],clients:[],loads:[],concepts:[],categories:[]};
const near=(a,b,msg)=>assert.ok(Math.abs(a-b)<.011,`${msg}: ${a} != ${b}`);
const all=m.realView(f,'tipo'),razo=m.realView({...f,companies:['Razo']},'tipo'),age=m.realView({...f,companies:['Agetrans']},'tipo');
near(all.tot.ingreso,m.run(f).totals.revenue,'Ingreso exacto de facturas');
near(all.groups.find(g=>g.key==='hormigonera').ingreso,d.lines.filter(l=>String(l.account).startsWith('705003')&&l.invoiceDate>=f.from&&l.invoiceDate<=f.to).reduce((s,l)=>s+l.revenue,0),'Hormigon coincide con todas sus facturas');
near(all.tot.coste,razo.tot.coste+age.tot.coste,'Coste por sociedad no depende del filtro');
const ambos=m.netaTrips(f).filter(t=>t.emp==='Razo'&&t.tipo==='hormigonera'),solo=m.netaTrips({...f,companies:['Razo']}).filter(t=>t.tipo==='hormigonera');
assert.equal(ambos.length,solo.length);
for(let i=0;i<ambos.length;i++){
 assert.equal(ambos[i].cicloId,solo[i].cicloId);assert.equal(ambos[i].costePendiente,solo[i].costePendiente);
 for(const k of ['ingreso','coste','margen'])assert.equal(ambos[i][k],solo[i][k],k+' invariante por carga');
}
const day={...f,from:'2026-07-15',to:'2026-07-15'};
near(m.realView(day).tot.ingreso,m.run(day).totals.revenue,'Un dia no incluye el mes entero');
for(const field of ['clients','loads','concepts','categories']){
 const col={clients:'clientId',loads:'load',concepts:'concept',categories:'category'}[field];
 const v=d.lines.find(l=>l[col]&&l.invoiceDate>='2026-01-01'&&l.invoiceDate<='2026-08-31')[col];
 const q={...f,[field]:[v]};near(m.realView(q)?.tot.ingreso||0,m.run(q).totals.revenue,'Filtro '+field);
}
for(const g of all.groups)if(g.pendientes){assert.equal(g.margen,null);assert.equal(g.margenTransPct,null);}
console.log(JSON.stringify({ok:true,control:d.actividad.meta.conciliacion,grupos:all.groups.map(g=>({tipo:g.key,ingreso:g.ingreso,costeConocido:g.coste,material:g.material,pendientes:g.pendientes||0,ingresoPendiente:g.ingresoPendiente||0,margen:g.margen}))},null,2));
