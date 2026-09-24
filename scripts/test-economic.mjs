import assert from 'node:assert/strict';
import {reconcileActivity,costSnapshot} from './economic-activity.mjs';
const dated=[{version_coste:2,generado:'2026-09-24T05:00:00'}];
assert.equal(costSnapshot(dated,'2026-09-24T03:00:00').rows.length,1);
assert.equal(costSnapshot(dated,'2026-09-25T03:00:00').rows.length,0);
assert.throws(()=>costSnapshot([...dated,{version_coste:2,generado:'2026-09-23T05:00:00'}],'2026-09-24'));
const activity={rows:[{c:'Razo',v:'0001',cant:'7',albaranes:['01'],imp:100,cli:'Cliente',mes:'2026-01',dia:'2026-01-15'},
 {c:'Agetrans',v:'0001',cant:'7',albaranes:['01'],imp:20,cli:'Cliente',mes:'2026-01',dia:'2026-01-15'}]};
const invoice=(company,revenue,trip='1')=>({id:company+revenue,company,trip,delivery:'1',client:'Cliente',clientId:company+'|1',
 invoiceDate:'2026-02-01',lineDate:'2026-01-15',revenue,account:'7050031001'});
const cost=(empresa,material)=>({version_coste:2,empresa,viaje:'1',cantera:'7',albaran:'1',coste:{gasoil:10,conductor:20,material},coste_completo:true,faltantes:[]});
const r=reconcileActivity(activity,[invoice('Razo',120),invoice('Agetrans',20),invoice('Razo',50,'')],[cost('Razo',0),cost('Agetrans',100)]);
assert.equal(r.control.facturado,190);assert.equal(r.control.sinViaje,50);
assert.equal(r.rows[0].costeCanonico.componentes.material,0);
assert.equal(r.rows[1].costeCanonico.componentes.material,100);
assert.equal(r.rows[2].costeCanonico,null);assert.equal(r.rows[2].imp,50);
assert.equal(r.rows[0].economia[0].invoiceDate,'2026-02-01');
const old=reconcileActivity(activity,[invoice('Razo',120)],[{...cost('Razo',0),version_coste:1}]);
assert.equal(old.rows[0].costeCanonico,null);
const abono=reconcileActivity(activity,[invoice('Razo',-20)],[cost('Razo',0)]);
assert.equal(abono.control.facturado,-20);
// Dos filas de actividad que comparten una carga no duplican sus gastos.
const shared={rows:[{...activity.rows[0],imp:75},{...activity.rows[0],imp:25}]};
const split=reconcileActivity(shared,[invoice('Razo',120)],[cost('Razo',10)]);
assert.equal(split.rows.reduce((s,r)=>s+r.costeCanonico.componentes.material,0),10);
assert.equal(split.rows.reduce((s,r)=>s+r.costeCanonico.componentes.gasoil,0),10);
assert.equal(split.rows.reduce((s,r)=>s+r.imp,0),120);
const partly=reconcileActivity({rows:[{...activity.rows[0],cant:'',albaranes:['1','2']}]},[invoice('Razo',120)],[{...cost('Razo',10),cantera:'A1'}]);
assert.equal(partly.rows[0].costeCanonico.completo,false);
assert.equal(partly.rows[0].costeCanonico.componentes.material,10);
console.log('OK conciliacion: sociedades aisladas, facturas sin viaje, fechas, abonos y rechazo del coste antiguo.');
