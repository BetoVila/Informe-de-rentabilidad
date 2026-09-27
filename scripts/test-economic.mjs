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
const conEvidencia=c=>({...c,evidencia_real:{granularidad:'viaje',conciliada:true,lineas:Object.entries(c.coste).filter(([,importe])=>Math.abs(importe)>=0.005).map(([componente,importe],i)=>({componente,importe,fuente:'factura Solred',documento_sha256:'a'.repeat(64),linea:'L'+i}))}});
const r=reconcileActivity(activity,[invoice('Razo',120),invoice('Agetrans',20),invoice('Razo',50,'')],[cost('Razo',0),cost('Agetrans',100)]);
assert.equal(r.control.facturado,190);assert.equal(r.control.sinViaje,50);
assert.equal(r.rows[0].costeCanonico.componentes.material,0);
assert.equal(r.rows[1].costeCanonico.componentes.material,100);
assert.equal(r.rows[2].costeCanonico,null);assert.equal(r.rows[2].imp,50);
assert.equal(r.rows[0].economia[0].invoiceDate,'2026-02-01');
const real=reconcileActivity(activity,[invoice('Razo',120)],[conEvidencia(cost('Razo',0))]);
assert.equal(real.rows[0].costeCanonico.realConfirmado,true,'R solo con evidencia conciliada directamente al viaje');
assert.equal(real.rows[0].costeCanonico.componentes.gasoil,10);
const withoutEvidence=reconcileActivity(activity,[invoice('Razo',120)],[cost('Razo',0)]);
assert.equal(withoutEvidence.rows[0].costeCanonico.realConfirmado,false,'desglose completo sin factura directa sigue siendo E');
const badEvidence=conEvidencia(cost('Razo',0));badEvidence.evidencia_real.lineas[0].importe=9;
assert.equal(reconcileActivity(activity,[invoice('Razo',120)],[badEvidence]).rows[0].costeCanonico.realConfirmado,false,'importe que no concilia sigue siendo E');
const badHash=conEvidencia(cost('Razo',0));badHash.evidencia_real.lineas[0].documento_sha256='sin-huella';
assert.equal(reconcileActivity(activity,[invoice('Razo',120)],[badHash]).rows[0].costeCanonico.realConfirmado,false,'evidencia sin huella de documento sigue siendo E');
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
const splitReal=reconcileActivity(shared,[invoice('Razo',120)],[conEvidencia(cost('Razo',10))]);
assert.ok(splitReal.rows.every(r=>r.costeCanonico.realConfirmado===false),'reparto entre dos filas no se marca R');
const partly=reconcileActivity({rows:[{...activity.rows[0],cant:'',albaranes:['1','2']}]},[invoice('Razo',120)],[{...cost('Razo',10),cantera:'A1'}]);
assert.equal(partly.rows[0].costeCanonico.completo,false);
assert.equal(partly.rows[0].costeCanonico.componentes.material,10);
assert.equal(r.control.enlace,'albaran','sin r.facturas (extracciones anteriores) se enlaza como antes');

// ---- Enlace EXACTO carga -> factura por la cabecera del albaran (r.facturas = [[«empresa|serie-numero», venta]]).
const near=(a,b,m)=>assert.ok(Math.abs(a-b)<1e-6,m+': '+a+' != '+b);
const carga=(c,v,cant,dia,facturas,extra)=>({c,v,cant,albaranes:['01'],imp:facturas.reduce((s,[,x])=>s+x,0),cli:'Cliente',mes:dia.slice(0,7),dia,facturas,...extra});
const linea=(company,f,revenue,account,delivery,trip)=>({id:company+'|'+f+'|'+account+'|'+revenue,company,invoiceId:company+'|'+f,invoice:f,trip:trip||'00000001',delivery:delivery||'01',
 client:'Cliente',clientId:company+'|1',invoiceDate:'2026-01-31',lineDate:'2026-01-26',revenue,account,load:'HOR',concept:'Servicio',category:'Cat'});
// Caso real 26446 (Razo, enero 2026): la factura 26-1 agrupa por tarifa y su «albaran» 03 no identifica la carga.
const hormigon={rows:[carga('Razo','00026446','21799','2026-01-09',[['Razo|26-1',112.4]]),carga('Razo','00026446','21828','2026-01-09',[['Razo|26-1',80]]),
 carga('Razo','00026446','21840','2026-01-09',[['Razo|26-1',59.75]]),carga('Razo','00026448','30001','2026-01-20',[['Razo|26-1',80]])]};
const f26=[linea('Razo','26-1',112.4,'7050031001','03'),linea('Razo','26-1',219.75,'7050031001','18'),linea('Razo','26-1',0,'7050031002','03')];
const h=reconcileActivity(hormigon,f26,[]);
assert.equal(h.control.enlace,'factura');
assert.deepEqual(h.rows.slice(0,4).map(x=>Math.round(x.imp*100)/100),[112.4,80,59.75,80],'cada carga lleva su venta, no un reparto del albaran de la linea');
assert.ok(h.rows.slice(0,4).every(x=>x.enlaceIngreso==='factura'&&Math.abs(x.importeAlbaran-x.imp)<1e-9));
assert.equal(h.rows.length,4,'la factura cuadra con sus cargas: sin fila aparte');
assert.equal(h.control.facturasCuadran,1);assert.deepEqual(h.facturas['Razo|26-1'],[4,332.15,332.15]);
assert.equal(h.rows[0].economia[0].invoice,'Razo|26-1');assert.equal(h.rows[0].economia[0].invoiceDate,'2026-01-31');
assert.equal(h.rows[0].economia[0].lineDate,'2026-01-09','la fecha de linea de la carga es la de su albaran');
// Prebetong 26-24: una linea de 25.362,65 € es el mes de muchos viajes; no cae en la unica carga de su albaran.
const pre={rows:[carga('Razo','00026748','A1','2026-01-30',[['Razo|26-24',432.12]]),carga('Razo','00026750','A2','2026-01-12',[['Razo|26-24',400]]),
 carga('Razo','00026751','A3','2026-01-13',[['Razo|26-24',567.88]])]};
const p=reconcileActivity(pre,[linea('Razo','26-24',1400,'7050020000','02','00026748')],[]);
assert.deepEqual(p.rows.map(x=>Math.round(x.imp*100)/100),[432.12,400,567.88]);
// Factura con MAS que sus cargas (minimos, complementos): la diferencia va aparte y no se reparte.
const mas=reconcileActivity(hormigon,[...f26,linea('Razo','26-1',35.85,'7050031002','03')],[]);
assert.deepEqual(mas.rows.slice(0,4).map(x=>Math.round(x.imp*100)/100),[112.4,80,59.75,80]);
const aj=mas.rows.find(x=>x.ajusteFactura);near(aj.imp,35.85,'fila de ajuste');assert.equal(aj.enlaceIngreso,'ajuste_factura');assert.equal(aj.soloFactura,true);
assert.ok(mas.rows.slice(0,4).every(x=>x.enlaceIngreso==='factura_con_diferencia'));
assert.equal(mas.control.facturasConDiferencia,1);near(mas.control.ajustes,35.85,'ajustes');
// Cuentas de la factura: cada cuenta suma lo mismo que sus lineas (los filtros por servicio siguen cuadrando).
const porCuenta=a=>mas.rows.flatMap(x=>x.economia).filter(l=>l.account===a).reduce((s,l)=>s+l.revenue,0);
near(porCuenta('7050031001'),332.15,'cuenta 7050031001');near(porCuenta('7050031002'),35.85,'cuenta 7050031002');
// Factura sin cargas (manual, rectificativa, abono): cada linea en su fila, como siempre.
const sin=reconcileActivity(hormigon,[...f26,linea('Razo','RH-2',-50,'7050020000'),linea('Razo','26-99',50,'7050020000')],[]);
assert.equal(sin.rows.filter(x=>x.enlaceIngreso==='factura_sin_cargas').length,2);near(sin.control.sinCargas,0,'rectificada y re-facturada');
// Carga cuya factura cae fuera del periodo leido: su venta se ve, el ingreso no se cuenta.
const fuera=reconcileActivity({rows:[...hormigon.rows,carga('Razo','00026500','40001','2025-12-30',[['Razo|25-400',90]])]},f26,[]);
const fx=fuera.rows[4];assert.equal(fx.imp,0);assert.equal(fx.importeAlbaran,90);assert.equal(fx.enlaceIngreso,'sin_factura_leida');near(fuera.control.sinFacturaLeida,90,'sin factura leida');
// Una carga en dos facturas lleva en cada una su parte; sociedades aisladas por el prefijo de la factura.
const dos=reconcileActivity({rows:[carga('Razo','00026600','50001','2026-01-10',[['Razo|26-1',30],['Razo|26-2',20]]),
 carga('Agetrans','00026600','50001','2026-01-10',[['Agetrans|26-1',70]])]},[linea('Razo','26-1',30,'7050020000'),linea('Razo','26-2',20,'7050020000'),linea('Agetrans','26-1',70,'7050020000')],[]);
assert.deepEqual(dos.rows.map(x=>x.imp),[50,70]);
// El coste por carga sigue repartiendose por la venta del albaran (no por el ingreso enlazado).
const cc=reconcileActivity({rows:[carga('Razo','1','7','2026-01-15',[['Razo|26-1',75]]),carga('Razo','1','7','2026-01-15',[['Razo|26-1',25]])]},[linea('Razo','26-1',100,'7050031001')],[cost('Razo',10)]);
assert.deepEqual(cc.rows.map(x=>x.costeCanonico.componentes.gasoil),[7.5,2.5]);
console.log('OK conciliacion: sociedades aisladas, facturas sin viaje, fechas, abonos, rechazo del coste antiguo, R solo con evidencia por viaje y enlace exacto carga -> factura (26-1, 26-24, minimos aparte, rectificativas, fuera de periodo, dos facturas).');
