import fs from 'node:fs/promises';
import {createHash} from 'node:crypto';
import {gzipSync} from 'node:zlib';
import path from 'node:path';
// Une las fuentes en un solo conjunto de datos. Access + GesRuta mandan (si fallan, no hay informe); las demas
// (Solred, surtidor, nomina) son OPCIONALES: si faltan, el informe lo dice y sigue con lo que hay.
const root=process.argv[2];
if(!root)throw new Error('Indique el directorio privado de esta extracción');
const readText=(f)=>fs.readFile(path.join(root,f),'utf8');
const optional=async(f)=>{try{return JSON.parse(await readText(f));}catch(e){if(e.code==='ENOENT')return null;throw e;}};
const aText=await readText('rentabilidad_access_v3.json'),gText=await readText('rentabilidad_gesruta_v3.json');
const a=JSON.parse(aText),g=JSON.parse(gText);
const solred=await optional('solred_v2.json'),gespro=await optional('gespro_v1.json'),nomina=await optional('nomina_v1.json');
const nominaDetalle=await optional('nomina_detalle.json'),personal=await optional('personal_v1.json'),contab=await optional('contabilidad_v1.json'),movertis=await optional('movertis_v1.json'),locatelSrc=await optional('locatel_v1.json'),actividadSrc=await optional('actividad_v1.json'),solredVeh=await optional('solred_vehiculos_v1.json');
const cuentasCfg=JSON.parse(await fs.readFile(new URL('../config/cuentas-contables.json',import.meta.url),'utf8'));
const cfg=JSON.parse(await fs.readFile(new URL('../config/secciones-nomina.json',import.meta.url),'utf8'));
const index=(rows)=>new Map(rows.map(r=>[String(r.id),r]));
const machines=index(a.machines),categories=index(a.categories),companies=index(a.companies),clients=index(a.clients),plants=index(a.plants);
const stationNames=new Map((a.stations||[]).map(s=>[String(s.id),String(s.nombre||'').trim()]));
const plateKey=(p)=>String(p||'').toUpperCase().replace(/[^A-Z0-9]/g,'');
const costFields=[['fuel','Gasóleo','GasoilImporte'],['adblue','AdBlue','AdBlueImporte'],['driver','Conductor · ordinarias','CosteParteChoferHorasOrdinarias'],['overtime','Conductor · extras','CosteParteChoferHorasExtra'],['amort','Amortización','CosteParteCamionAmortizacion'],['maintenance','Mantenimiento','CosteParteCamionMantenimiento'],['insurance','Seguro','CosteParteCamionSeguro'],['expensesCompany','Gastos empresa','GastosEmpresa'],['expensesDriver','Gastos empleado','GastosEmpleado'],['expensesVehicle','Gastos vehículo','GastosVehiculo']];
// Un camión no hace más de ~1.500 km en un parte. Access trae partes con millones de km (cuentakilómetros tecleado en
// el campo de recorridos): esos km NO se cuentan (el importe del parte sí) y se anotan en metadata.quality.
const KM_MAX_PARTE=1500;
const parts=a.parts.map(r=>{
 const machine=machines.get(String(r.IdMaquina)),plate=plateKey(machine?.matricula),values=Object.fromEntries(costFields.map(([k,,field])=>[k,Number(r[field])||0]));
 const kmRaw=Number(r.KmRecorridos)||0,kmOk=kmRaw>=0&&kmRaw<=KM_MAX_PARTE?kmRaw:0;
 const direct=Number(r.TotalCostesDirectos)||0,structure=Number(r.CosteEstructura)||0,componentDirect=Object.values(values).reduce((s,v)=>s+v,0),rate=Number(r['Estructura%'])||0;
 return {id:String(r.IdParteTrabajo),machineId:r.IdMaquina,date:r.Fecha.slice(0,10),plate,plateLabel:machine?.matricula||'Sin matrícula',category:categories.get(String(machine?.categoria))?.nombre||'Sin categoría Access',owner:companies.get(String(machine?.titular))?.nombre||'Sin titular',partClient:clients.get(String(r.IdCliente))?.nombre||'Sin cliente en parte',plant:plants.get(String(r['IdCliente/Planta']))?.nombre||'',station:String(r.IdGasoilEstacionServicio||''),direct,structure,rate,stored:direct+structure,componentDirect,recalculated:componentDirect*(1+rate),residual:direct-componentDirect,...values,km:kmOk,kmExcluded:kmRaw-kmOk,hours:Number(r.HorasTrabajo)||0,litres:Number(r.GasoilLitros)||0,adblueLitres:Number(r.AdBlueLitros)||0,accessRevenue:Number(r.FacturacionDiariaTotal)||0,trips:Number(r.Viajes)||0,m3:Number(r.MetrosCubicos)||0,tonnes:Number(r.Toneladas)||0,loaded:Number(r.KmCargado)||0,empty:Number(r.KmVacio)||0};
});
const machinesByPlate=new Map(a.machines.map(r=>[plateKey(r.matricula),r]));
// Tipo de servicio de la línea por su CUENTA contable (CUECON): portes nacionales, áridos por toneladas, hormigón por m³…
// El texto libre del concepto (2.000 variantes distintas) se conserva en conceptText, pero no sirve para segmentar.
const tipoServicio=(code)=>{let best='Sin cuenta contable',len=-1;for(const c of cuentasCfg.conceptosFacturacion||[])for(const p of c.prefijos)if(String(code||'').startsWith(p)&&p.length>len){best=c.label;len=p.length;}return best;};
const lines=g.lines.map(r=>({...r,load:r.load||'Sin carga',conceptText:r.concept||'Sin concepto',concept:r.kind==='Linea GesRuta'?tipoServicio(r.account):'Ajuste de cabecera',category:categories.get(String(machinesByPlate.get(r.plate)?.categoria))?.nombre||'Sin ficha Access'}));
if(a.metadata.desde!==g.metadata.desde||a.metadata.hasta!==g.metadata.hasta)throw new Error('Periodos distintos entre fuentes');
const to=g.metadata.hasta,month=(d)=>d.slice(0,7);
const ownerOfPlate=new Map();for(const p of parts)if(p.plate&&!ownerOfPlate.has(p.plate))ownerOfPlate.set(p.plate,p.owner);
const round=(v,n=2)=>Math.round(v*10**n)/10**n;

// ---- combustible: Solred (tarjeta) y surtidor de la nave (deposito propio)
const fuel={solred:null,surtidor:null};
if(solred?.metadata?.disponible){
 fuel.solred={meta:{desde:solred.metadata.desde,hasta:solred.metadata.hasta,maxFecha:solred.metadata.maxFecha,iva:solred.metadata.iva,ficheros:solred.metadata.ficheros,lineas:solred.metadata.lineas,sinMatricula:solred.metadata.sinMatricula,descuadres:solred.metadata.descuadres},rows:solred.rows.map(r=>({...r,owner:r.plate?ownerOfPlate.get(r.plate)||'Sin ficha':'Sin matrícula'}))};
 if(solred.metadata.descuadres>Math.max(2,solred.metadata.lineas*0.005))throw new Error('Solred: el mapa de columnas ya no cuadra (bruto − descuento ≠ neto en '+solred.metadata.descuadres+' líneas)');
}
if(gespro?.metadata?.disponible){
 const m=new Map();
 for(const r of gespro.rows){const k=month(r.fecha)+'|'+(r.placa||'');if(!m.has(k))m.set(k,{month:month(r.fecha),plate:r.placa||null,n:0,litros:0,kmN:0});const x=m.get(k);x.n++;x.litros+=r.litros;if(r.km)x.kmN++;}
 const maxs=[gespro.metadata.fuentes.base.maxFecha,gespro.metadata.fuentes.texto.maxFecha].filter(Boolean).sort();
 fuel.surtidor={meta:{fuentes:gespro.metadata.fuentes,maxFecha:maxs[maxs.length-1]||null},rows:[...m.values()].map(x=>({...x,litros:round(x.litros,1),owner:x.plate?ownerOfPlate.get(x.plate)||'Sin ficha':'Sin matrícula'}))};
}
// ---- estaciones: solo las que salen en partes con gasoil
const usedStations=new Set(parts.filter(p=>p.litres>0&&p.station).map(p=>p.station));
const stations=Object.fromEntries([...usedStations].map(id=>[id,stationNames.get(id)||('Estación '+id)]));
// Palabra completa: «NAVE» no es «BENAVENTE».
const naveIds=Object.entries(stations).filter(([,n])=>cfg.stationNave.some(x=>new RegExp('(^|[^A-ZÁÉÍÓÚÑ])'+x+'([^A-ZÁÉÍÓÚÑ]|$)','i').test(n))).map(([id])=>id);

// ---- nomina (agregados por seccion; SIN nombres)
let payroll=null;
if(nomina?.metadata?.disponible){
 const seen=new Set();
 for(const r of nomina.rows){const k=[r.company,r.period,r.section].join('|');if(seen.has(k))throw new Error('Nómina: sección repetida '+k);seen.add(k);if(r.people!=null&&r.people<3)throw new Error('Nómina: un grupo de menos de 3 personas sin plegar ('+k+')');}
 payroll={meta:{periodos:nomina.metadata.periodos,ficheros:nomina.metadata.ficheros,elegidos:nomina.metadata.elegidos,minPersonasGrupo:nomina.metadata.minPersonasGrupo,erroresLectura:nomina.metadata.erroresLectura,sinDetalle:nomina.metadata.sinDetalle},rows:nomina.rows,versions:nomina.versions,sections:cfg.sections,typeLabels:cfg.typeLabels,categoryType:cfg.categoryType};
}

// ---- contabilidad real (CxConta vía el ERP): gastos (grupo 6) e ingresos (grupo 7) por sociedad, mes y cuenta
let ledger=null;
if(contab?.metadata?.disponible){
 const catOf=(code,list)=>{let best='otros',len=-1;for(const c of list)for(const p of c.prefijos)if(code.startsWith(p)&&p.length>len){best=c.id;len=p.length;}return best;};
 const rows=[];
 for(const r of contab.rows){
  const gasto=r.cuenta.startsWith('6'),amount=round(gasto?r.debe-r.haber:r.haber-r.debe,2);
  if(!amount)continue;
  rows.push({company:r.company,month:r.month,cuenta:r.cuenta,kind:gasto?'g':'i',cat:catOf(r.cuenta,gasto?cuentasCfg.gastos:cuentasCfg.ingresos),amount});
 }
 // Mes cerrado: la contabilidad se asienta cuando llegan las facturas; un mes con menos de la mitad de los ingresos de
 // servicios de los tres anteriores todavía no está cerrado y no se compara.
 const incomeOf=(company,month)=>rows.filter(r=>r.company===company&&r.month===month&&r.kind==='i'&&['servicios','ventas'].includes(r.cat)).reduce((s,r)=>s+r.amount,0);
 const months=[...new Set(rows.map(r=>r.month))].sort();
 let lastClosed=null;
 for(const m of months){
  const i=months.indexOf(m);if(i<3)continue;
  const ok=[1,2].every(c=>{const prev=[1,2,3].map(k=>incomeOf(c,months[i-k])).reduce((s,v)=>s+v,0)/3;return prev<=0||incomeOf(c,m)>=0.5*prev;});
  if(ok)lastClosed=m;
 }
 const used=new Set(rows.map(r=>r.cuenta));
 // Intragrupo (facturación consolidada): ingreso/gasto entre Razo y Agetrans, medido en el libro por cuenta de grupo.
 const intragrupo=(contab.intragrupo?.rows||[]).map(r=>({company:r.company,month:r.month,ingreso:round(r.ingreso||0,2),gasto:round(r.gasto||0,2)}));
 ledger={meta:{fuente:contab.metadata.fuente,desde:contab.metadata.desde,hasta:contab.metadata.hasta,leido:contab.metadata.leido,maxFechaPorSociedad:contab.metadata.maxFechaPorSociedad,lastClosed,intragrupoMetodo:contab.intragrupo?.metodo||''},accounts:Object.fromEntries([...used].map(c=>[c,contab.accounts[c]||''])),categories:{gastos:cuentasCfg.gastos.map(c=>({id:c.id,label:c.label})),ingresos:cuentasCfg.ingresos.map(c=>({id:c.id,label:c.label}))},puente:cuentasCfg.puente,sociedades:cuentasCfg.sociedades,titularASociedad:cuentasCfg.titularASociedad,intragrupo,rows};
}

// ---- telemática: km y litros medidos por el propio camión, por matrícula y día. Tres fuentes, un solo conjunto:
//  1) el ERP (Movertis, razo_movertis_dia: solo días fiables) manda cuando existe el día;
//  2) el HISTÓRICO bajado de Wialon en este PC (historicos\wialon_hist\_resumen.jsonl, desde ago-2025) rellena los días que
//     el ERP no tiene (el ERP empezó a bajar en ago-2026), con la misma regla de fiabilidad: contador leído y km posibles;
//  3) los km por día de Locatel que trae el ERP (sin litros). Un día sin lectura no cuenta como cero.
const KM_MAX_DIA=1500,LITROS_MAX_DIA=900;
let telemetry=null;
{
 const rows=new Map(),src={erp:null,historico:null,locatel:null};
 const put=(plate,date,km,litres,s)=>{if(!plate||!date||rows.has(plate+'|'+date))return false;rows.set(plate+'|'+date,{plate,date,km,litres,src:s});return true;};
 const span=(list)=>list.length?{desde:list.reduce((a,r)=>r.date<a?r.date:a,list[0].date),hasta:list.reduce((a,r)=>r.date>a?r.date:a,list[0].date),dias:list.length,unidades:new Set(list.map(r=>r.plate)).size}:null;
 let clases={};
 if(movertis?.metadata?.disponible){
  const erp=movertis.rows.map(r=>({plate:plateKey(r.p),date:r.d,km:r.km,litres:r.l})).filter(r=>r.plate);
  for(const r of erp)put(r.plate,r.date,r.km,r.litres,'erp');
  clases=Object.fromEntries(Object.entries(movertis.clases||{}).map(([m,c])=>[plateKey(m),c]).filter(([k])=>k));
  src.erp={...span(erp),diasCamion:movertis.metadata.diasCamion,diasFiables:movertis.metadata.diasFiables,diasDescartados:movertis.metadata.diasDescartados,leido:movertis.metadata.leido};
 }
 const histDir=process.argv[3]||path.resolve(root,'..','..','historicos');
 const histFile=path.join(histDir,'wialon_hist','_resumen.jsonl');
 try{
  const text=await fs.readFile(histFile,'utf8');
  const ok=[],vistos=new Set();let descartados=0,lineas=0;
  for(const line of text.split('\n')){
   if(!line.trim())continue;lineas++;let r;try{r=JSON.parse(line);}catch(e){descartados++;continue;}
   const plate=plateKey(r.mat||String(r.unidad||'').replace(/-/g,'')),date=r.dia;
   if(!plate||!date||vistos.has(plate+'|'+date)){continue;}vistos.add(plate+'|'+date);
   const km=Number(r.km);
   if(!r.km_fuente||!Number.isFinite(km)||km<0||km>KM_MAX_DIA){descartados++;continue;}   // sin contador o km imposibles en un día: no es dato
   const lit=r.tiene_fuel&&Number.isFinite(Number(r.litros))&&Number(r.litros)>0&&Number(r.litros)<=LITROS_MAX_DIA?round(Number(r.litros),2):null;
   ok.push({plate,date,km:round(km,2),litres:lit});
  }
  let nuevos=0;for(const r of ok)if(put(r.plate,r.date,r.km,r.litres,'historico'))nuevos++;
  src.historico={...span(ok),lineas,descartados,nuevosSobreErp:nuevos,fichero:histFile};
 }catch(e){if(e.code!=='ENOENT')throw e;}
 if(locatelSrc?.metadata?.disponible){
  // solo tramos de UN día (from = to): son los km del día de esa matrícula
  const loc=(locatelSrc.rows||[]).filter(r=>r.from&&r.from===r.to).map(r=>({plate:plateKey(r.p),date:r.from,km:Number(r.km)})).filter(r=>r.plate&&Number.isFinite(r.km)&&r.km>=0&&r.km<=KM_MAX_DIA);
  let n=0;for(const r of loc)if(put(r.plate,r.date,round(Number(r.km),2),null,'locatel'))n++;
  src.locatel=loc.length?{...span(loc),nuevos:n}:null;
 }
 const all=[...rows.values()].sort((x,y)=>x.date<y.date?-1:x.date>y.date?1:x.plate.localeCompare(y.plate));
 if(all.length){
  const sp=span(all),porFuente={};for(const r of all)porFuente[r.src]=(porFuente[r.src]||0)+1;
  telemetry={meta:{fuente:'Localizador: ERP (Movertis) + histórico bajado (Wialon) + Locatel (ERP)',desde:sp.desde,hasta:sp.hasta,diasCamion:all.length,diasFiables:all.length,diasDescartados:(src.erp?.diasDescartados||0)+(src.historico?.descartados||0),unidades:sp.unidades,leido:src.erp?.leido||new Date().toISOString(),fuentes:src,porFuente},clases,rows:all};
 }
}

// ---- Locatel (CANbus, vía el ERP): km y consumo reales por matrícula y tramo. Hoy la copia local puede no tener aún estas
// emisiones (el agente del ERP corre en producción); en ese caso queda null y el informe lo dice, sin inventar dato.
let locatel=null;
if(locatelSrc?.metadata?.disponible){
 const rows=locatelSrc.rows.map(r=>({plate:plateKey(r.p),from:r.from,to:r.to,km:r.km,litres:r.litres,co2e:r.co2e,estimado:r.estimado,fuel:r.fuel})).filter(r=>r.plate&&r.km>0);
 if(rows.length)locatel={meta:{fuente:locatelSrc.metadata.fuente,desde:locatelSrc.metadata.desde,hasta:locatelSrc.metadata.hasta,registros:rows.length,estimados:rows.filter(r=>r.estimado).length,unidades:new Set(rows.map(r=>r.plate)).size,leido:locatelSrc.metadata.leido},rows};
}

// ---- estado de cada fuente (lo que ve Roberto arriba)
const lastPeriod=payroll?Object.values(payroll.meta.periodos).map(p=>p[p.length-1]).sort().pop():null;
const litresBy=(pred)=>parts.filter(p=>pred(p)&&p.litres>0&&(!naveIds.includes(p.station))).reduce((s,p)=>s+p.litres,0);
const coverage={};
if(fuel.solred){
 const from=fuel.solred.meta.desde>'2025-01-01'?fuel.solred.meta.desde:'2026-05-01';
 const months=new Set(fuel.solred.rows.filter(r=>r.kind==='gasoleo').map(r=>r.month));
 for(const owner of new Set(parts.map(p=>p.owner))){
  const declared=parts.filter(p=>p.owner===owner&&months.has(month(p.date))&&p.litres>0&&!naveIds.includes(p.station)).reduce((s,p)=>s+p.litres,0);
  const card=fuel.solred.rows.filter(r=>r.kind==='gasoleo'&&r.owner===owner).reduce((s,r)=>s+r.litros,0);
  if(declared>1000)coverage[owner]=round(card/declared,3);
 }
}
// ---- resumen por matrícula de Solred (informe «Vehículos» de Mi Solred): para las sociedades sin ficheros mensuales
const coverageResumen=new Set();
fuel.solredVehiculos=null;
if(solredVeh?.metadata?.disponible){
 fuel.solredVehiculos=solredVeh.informes.map(inf=>{
  const rows=inf.filas.map(f=>({plate:plateKey(f.plate),importe:f.importe,litros:f.litros,operaciones:f.operaciones,descuento:f.descuento}));
  const votes=new Map();for(const r of rows){const o=ownerOfPlate.get(r.plate)||'Sin ficha';votes.set(o,(votes.get(o)||0)+r.litros);}
  const owner=[...votes.entries()].sort((a,b)=>b[1]-a[1])[0]?.[0]||'Sin ficha',plates=new Set(rows.map(r=>r.plate));
  const declared=parts.filter(p=>plates.has(p.plate)&&p.date>=inf.desde&&p.date<=inf.hasta&&p.litres>0&&!naveIds.includes(p.station)).reduce((s,p)=>s+p.litres,0);
  const litros=rows.reduce((s,r)=>s+r.litros,0);
  return {fichero:inf.fichero,nif:inf.nif,desde:inf.desde,hasta:inf.hasta,owner,rows,litros:round(litros,1),importe:round(rows.reduce((s,r)=>s+r.importe,0),2),declared:round(declared,1),coverage:declared>1000?round(litros/declared,3):null};
 });
 // un informe da la cobertura de una sociedad SOLO si esa sociedad no tiene ficheros mensuales suficientes
 for(const inf of fuel.solredVehiculos)if(inf.coverage!=null&&!(coverage[inf.owner]>=0.6)){coverage[inf.owner]=inf.coverage;coverageResumen.add(inf.owner);}
}
const solredWeak=Object.entries(coverage).filter(([,c])=>c<0.6).map(([o])=>o);
const sources=[
 {id:'gesruta',name:'GesRuta',state:'ok',to:to,note:'Facturas y albaranes de Razo y Agetrans.'},
 {id:'access',name:'Access',state:'ok',to:to,note:'Partes diarios por vehículo y conductor.'},
 {id:'solred',name:'Solred',state:!fuel.solred?'sin':(solredWeak.length||coverageResumen.size)?'parcial':'ok',to:fuel.solred?.meta.maxFecha||null,note:!fuel.solred?'Sin ficheros de Solred.':solredWeak.length?'Falta la cuenta de '+solredWeak.join(' y ')+': el fichero solo cubre una parte de sus litros ('+Object.entries(coverage).map(([o,c])=>o.replace(/,? S\.L\.?/i,'')+' '+Math.round(c*100)+' %').join(', ')+').':coverageResumen.size?'Ficheros mensuales solo de una sociedad. '+[...coverageResumen].map(o=>o.replace(/,? S\.L\.?/i,'')).join(' y ')+' llega como resumen por matrícula (informe «Vehículos» de Solred), sin detalle por mes: faltan sus ficheros de operaciones en texto.':'Tarjeta de combustible.'},
 {id:'surtidor',name:'Surtidor nave',state:!fuel.surtidor?'sin':(fuel.surtidor.meta.fuentes.base.maxFecha&&fuel.surtidor.meta.fuentes.base.maxFecha<to.slice(0,8)+'00'?'parcial':'ok'),to:fuel.surtidor?.meta.maxFecha||null,note:!fuel.surtidor?'Sin datos del surtidor.':'GesproWin: la base llega hasta el '+fuel.surtidor.meta.fuentes.base.maxFecha+'; se completa con las exportaciones de texto.'},
 {id:'nomina',name:'Nómina',state:payroll?'ok':'sin',to:lastPeriod,note:payroll?'Resumen mensual de la gestoría; el último mes llega ~10 días después de cerrar.':'Sin resúmenes de nómina.'},
 {id:'contabilidad',name:'Contabilidad',state:ledger?'ok':'sin',to:ledger?.meta.lastClosed||null,note:ledger?'Gastos e ingresos reales de CxConta (traspasados al ERP cada noche). Cerrada hasta '+ledger.meta.lastClosed+'; el mes en curso no se compara.':'Sin contabilidad: el gasto que se ve es solo el de los partes de Access, que no es el real.'},
 {id:'movertis',name:'Movertis',state:telemetry?(telemetry.meta.fuentes.historico?'ok':'parcial'):'pendiente',to:telemetry?.meta.hasta||null,note:telemetry?'Km y litros medidos por el camión, del '+telemetry.meta.desde+' al '+telemetry.meta.hasta+': '+(telemetry.meta.fuentes.erp?'ERP (Movertis) desde '+telemetry.meta.fuentes.erp.desde:'')+(telemetry.meta.fuentes.historico?'; histórico bajado de Wialon desde '+telemetry.meta.fuentes.historico.desde+' ('+telemetry.meta.fuentes.historico.dias+' días-camión)':'; sin histórico anterior al ERP')+'. '+telemetry.meta.diasDescartados+' días-camión sin lectura fiable no se cuentan.':'Kilómetros y consumo medidos por el camión: sin lectura en esta pasada.'},
 {id:'locatel',name:'Locatel',state:locatel?'ok':(locatelSrc?.metadata?'sin':'pendiente'),to:locatel?.meta.hasta||null,note:locatel?('Km y consumo (CANbus) medidos por el camión, leídos del ERP (que los baja de Locatel): '+locatel.meta.registros+' tramos de '+locatel.meta.unidades+' vehículos.'):(locatelSrc?.metadata?'Conectado al ERP, pero sus emisiones de Locatel aún no están en la copia local del ERP (0 registros). En cuanto lleguen, se usan sin tocar nada.':'Kilómetros y consumo (CANbus) por GPS: falta el acceso automático.')}
];

// ---- Actividad operativa (GesRuta): un viaje real = albarán de cantera; km/m³/t/importe por viaje. El nombre del cliente
// ya viene resuelto por el maestro (mascli). Los textos se internan en diccionarios (cliente/matrícula/provincia/localidad)
// y cada viaje es una fila POSICIONAL de índices, para no inflar el HTML con 65k filas de texto repetido.
// Fila: [empresa, mes, cliente, matrícula, provOrigen, provDestino, locOrigen, locDestino, km, m³, t, importe, hormigón,
//        puntoOrigen, puntoDestino]   (localidad = pueblo; punto = planta/cantera/obra concreta)
let actividad=null;
if(actividadSrc?.metadata?.disponible){
 const co=['Razo','Agetrans'];
 const mo=[],moIx=new Map();
 const cli=['(sin asignar)'],cliIx=new Map([['(sin asignar)',0]]);
 const mat=[''],matIx=new Map([['',0]]);
 const prov=['(sin provincia)'],provIx=new Map([['',0]]);
 const loc=['(sin localidad)'],locIx=new Map([['',0]]);
 const pt=['(sin punto)'],ptIx=new Map([['',0]]);
 const dia=[''],diaIx=new Map([['',0]]);   // fecha completa del viaje (día), para la tabla y el agrupamiento
 const met=[''],metIx=new Map([['',0]]),conf=[''],confIx=new Map([['',0]]),chot=[''],chotIx=new Map([['',0]]);   // triangulado v2
 const mot=[''],motIx=new Map([['',0]]),tipo=[''],tipoIx=new Map([['',0]]),kmf=[''],kmfIx=new Map([['',0]]),mfu=[''],mfuIx=new Map([['',0]]);   // detalle completo
 const hm=s=>s?String(s).slice(11,16):'',nn=v=>v==null?null:v;
 const intern=(arr,ix,val)=>{let i=ix.get(val);if(i===undefined){i=arr.length;arr.push(val);ix.set(val,i);}return i;};
 const TRM={medido:0,repartido:1,hormigon:2,sin:3};   // fiabilidad del km/coste del viaje (triangulado / estimado)
 const rows=actividadSrc.rows.map(r=>{
  const c=r.c==='Agetrans'?1:0;
  let mi=moIx.get(r.mes);if(mi===undefined){mi=mo.length;mo.push(r.mes);moIx.set(r.mes,mi);}
  const ci=intern(cli,cliIx,(r.cli&&String(r.cli).trim())||'(sin asignar)');
  const mti=intern(mat,matIx,(r.mat&&String(r.mat).trim())||'');
  const oi=intern(prov,provIx,r.op||''),di=intern(prov,provIx,r.dp||'');
  const li=intern(loc,locIx,r.ol||''),ld=intern(loc,locIx,r.dl||'');
  const po=intern(pt,ptIx,r.on||''),pd=intern(pt,ptIx,r.dn||'');
  const dd=intern(dia,diaIx,r.dia||'');
  // 21..31: triangulado v2 (hora real inicio/fin, nº del día, min conducción/espera/otros, método, confianza, chofer tacógrafo, nocturno, medido)
  // 32..33: km cargado / km en vacio del viaje (contador CAN; null si no se vieron la carga y la descarga)
  const v2=[r.tini||'',r.tfin||'',r.ord||0,r.mcon==null?null:r.mcon,r.mesp==null?null:r.mesp,r.motr==null?null:r.motr,
   intern(met,metIx,r.met||''),intern(conf,confIx,r.conf||''),intern(chot,chotIx,r.chot?String(r.chot):''),r.noct?1:0,r.med?1:0,
   r.kmc==null?null:r.kmc,r.kmv==null?null:r.kmv,
   // 34: paradas y esperas del viaje (>= 5 min): [hh:mm, minutos, lugar (interno en pt), que hacia (0 carga, 1 descarga, 2 espera, 3 fuera)]
   (r.par||[]).map(p=>[p[0],p[1],intern(pt,ptIx,p[2]||''),({carga:0,descarga:1,espera:2,fuera:3})[p[3]]??3]),
   // 35..63: TODO el detalle del viaje (al pinchar): hitos carga/descarga (hh:mm), min disponible/descanso/sin dato, fuente de los
   // minutos, coherente, transcurridos, litros cargado/vacio, dist o-d, min en obra, viajes del dia, motivo, fecha del albaran,
   // chofer del albaran, coincide, tipo, largo, espejo, jornada ini/fin, fuente del km, litros contador/calibrados, viaje, cantera
   hm(r.tca),hm(r.tcf),hm(r.tde),hm(r.tdf),nn(r.mdis),nn(r.mdes),nn(r.msd),intern(mfu,mfuIx,r.mfu||''),r.mcoh==null?null:(r.mcoh?1:0),nn(r.mtr),
   nn(r.litc),nn(r.litv),nn(r.dod),nn(r.obm),r.vdia||null,intern(mot,motIx,r.mot||''),intern(dia,diaIx,r.fg||''),intern(chot,chotIx,r.chg?String(r.chg):''),
   r.chok==null?null:(r.chok?1:0),intern(tipo,tipoIx,r.tipo||''),r.larga?1:0,r.esp?1:0,hm(r.jini),hm(r.jfin),intern(kmf,kmfIx,r.kmf||''),nn(r.litraw),nn(r.litcal),
   String(r.v||''),String(r.cant||'')];
  return [c,mi,ci,mti,oi,di,li,ld,r.km||0,r.m3||0,r.t||0,r.imp||0,r.horm?1:0,po,pd,r.kmr||0,r.lit||0,r.dur||0,TRM[r.trm]??3,r.impro||0,dd].concat(v2);
 });
 // Margen operativo de GesRuta (inggas): P&L por mes×cliente. Antes del coste real de flota/personal/indirectos.
 let margen=null;
 if(Array.isArray(actividadSrc.margen)&&actividadSrc.margen.length){
  margen={rows:actividadSrc.margen.map(a=>({c:a.c==='Agetrans'?1:0,m:a.m,cli:(a.cli&&String(a.cli).trim())||'(sin cliente)',
   i:a.ing||0,ma:a.materiales||0,s:a.subcontratacion||0,g:a.gasoil||0,p:a.peajes||0,ad:a.adblue||0}))};
 }
 actividad={meta:{fuente:actividadSrc.metadata.fuente,desde:actividadSrc.metadata.desde,hasta:actividadSrc.metadata.hasta,viajes:rows.length,leido:actividadSrc.metadata.leido},co,mo,cli,mat,prov,loc,pt,dia,met,conf,chot,mot,tipo,kmf,mfu,tri:actividadSrc.metadata.triangulado||null,coords:actividadSrc.metadata.coords||{},rows,margen};
}
const data={version:4,metadata:{generatedAt:new Date().toISOString(),accessReadAt:a.metadata.read_at,gesrutaReadAt:g.metadata.read_at,from:g.metadata.desde,to:g.metadata.hasta,defaultFrom:g.metadata.hasta.slice(0,4)+'-01-01',defaultTo:g.metadata.hasta,snapshot:true,accessModified:a.metadata.modified,queries:[a.metadata.query],sourceHashes:{access:createHash('sha256').update(aText).digest('hex'),gesruta:createHash('sha256').update(gText).digest('hex')},sources,fuelIva:cfg.ivaCombustible,solredCoverage:coverage,solredResumen:[...coverageResumen],naveStations:naveIds,quality:{kmMaxParte:KM_MAX_PARTE,partesKmImposible:parts.filter(p=>p.kmExcluded>0).length,kmExcluidos:round(parts.reduce((s,p)=>s+p.kmExcluded,0),0),peorParte:parts.filter(p=>p.kmExcluded>0).sort((x,y)=>y.kmExcluded-x.kmExcluded).slice(0,5).map(p=>({id:p.id,date:p.date,plate:p.plateLabel,km:p.kmExcluded}))}},costFields:[...costFields.map(([k,label])=>[k,label]),['structure','Estructura'],['residual','Diferencia guardado / desglose']],parts,lines,headers:g.headers,sourceControls:{access:a.controls[0],gesruta:g.checks},sourceFiles:g.files,stations,fuel,payroll,ledger,telemetry,locatel,actividad,definitions:[
 'Contabilidad: gastos (grupo 6) e ingresos (grupo 7) reales de CxConta por sociedad, mes y cuenta, sin asientos de cierre ni apertura. El resultado contable es la referencia de rentabilidad; el coste de los partes de Access solo recoge una parte del gasto real (ver el puente en Conciliación). Un mes se compara solo cuando está cerrado; el mes en curso queda fuera.',
 'Ingresos sin IVA: líneas de GesRuta, excluidos suplidos, más diferencias explícitas con la base de cabecera. Las facturas anuladas y filas borradas no se incluyen.',
 'Fecha de factura: FECFAC. Fecha de línea: FECHA de linfaclib, con FECFAC como respaldo si no consta. La fecha del parte gobierna siempre los costes.',
 'Coste declarado en Access: TotalCostesDirectos + CosteEstructura del parte; lo rellena quien registra el parte y no es un dato contable. Recalculado: suma de diez conceptos de coste multiplicada por (1 + Estructura%). Con nómina real: como el recalculado, pero el conductor (ordinarias + extras + gastos de empleado) se ajusta cada mes y tipo de trabajo a la nómina real de la gestoría; la estructura mantiene el % de Access. Nada de esto modifica Access.',
 'El coste total por matrícula procede de Access. La atribución a empresa facturadora, cliente, carga y concepto es ESTIMADA por ingreso positivo del mismo mes y matrícula, según fecha de línea. Los abonos no generan pesos negativos. El reparto se fija antes de filtrar y no usa cuotas anuales.',
 'Los costes sin ingreso positivo enlazable en el mes quedan Sin asignar. Ambas incluye estos costes; seleccionar una empresa los excluye y muestra su importe aparte. Titular del vehículo no equivale a empresa facturadora.',
 'Saldo observado = ingresos seleccionados − coste seleccionado; no representa rentabilidad completa cuando hay ingresos sin coste, coste sin asignar, subcontratación sin costes u otras fuentes pendientes.',
 'Cobertura mensual = ingreso con una matrícula y algún parte en el mismo mes del criterio de fecha seleccionado / ingreso total. Es una medida de enlace, no prueba de que estén todos los gastos.',
 'Viajes GesRuta = referencias VIAJE distintas por empresa; albaranes = empresa + VIAJE + ALB_NUMERO. Viajes Access = contador declarado en los partes. No se suman entre fuentes.',
 'Consumo declarado = litros declarados en los partes / km declarados × 100. NO es consumo real: los partes traen km imposibles (no se cuentan los de más de '+KM_MAX_PARTE+' km en un solo parte) y faltan en muchos días en que el camión circula. El consumo real sale de los litros de la tarjeta Solred y del surtidor y de los km del localizador (Movertis, Locatel); ver Conciliación. Las horas de Access pueden ser aproximadas.',
 'Combustible: los litros y el importe de los partes se cruzan con la tarjeta Solred (importe con IVA; sin IVA = importe / 1,21, que coincide con el del parte al céntimo) y con el surtidor de la nave (solo litros). Solred llega por cuenta: si falta la de una sociedad, se avisa en lugar de darlo por bueno.',
 'Nómina: coste de empresa exacto de la gestoría (devengos + Seguridad Social + dietas), por mes y sección. La sección es el trabajo que realiza cada persona. Los grupos de menos de 3 personas se pliegan en otro para que un total no sea el sueldo de nadie. Si un mes aparece en varios ficheros se usa el más reciente y se anota la diferencia.',
 'Movertis y Locatel: kilómetros y litros medidos por el propio camión, por matrícula y día. Manda el ERP (Movertis, solo días fiables); los días que el ERP no tiene se toman del histórico bajado de Wialon en este PC (desde agosto de 2025, con la misma regla: contador leído y como máximo '+KM_MAX_DIA+' km al día) y de los km diarios de Locatel del ERP. Un día sin lectura no cuenta como cero. Un día-camión está «activo» si circula 30 km o más; «sin parte» si en ese día no hay ningún parte de Access de esa matrícula.',
 'Vehículos y Clientes: mismo motor que «Margen por viaje». Cada viaje real (albarán) lleva su ingreso facturado y el coste REAL de la contabilidad repartido por sus bases medidas (litros → combustible, horas → personal, km → flota, ingreso → indirectos; subcontratado = factura real del subcontratista). El material (compra de áridos) se atribuye por cliente y se descuenta del ingreso para dar el ingreso de transporte y servicios. Sin contabilidad cerrada en el periodo no hay coste real y se dice.',
 'Tipo de servicio: cada línea de factura de GesRuta se clasifica por su cuenta contable (portes nacionales, áridos por toneladas, hormigón por m³, venta de productos…), no por el texto libre del concepto.'
]};

// ---- capa PRIVADA de personal (con nombres): solo se escribe en la carpeta de trabajo; build.mjs la cifra
const norm=(s)=>String(s||'').normalize('NFD').replace(/[̀-ͯ]/g,'').toUpperCase();
const tok=(s)=>new Set(norm(s).replace(/[^A-Z ]/g,' ').split(/\s+/).filter(t=>t.length>1&&!['DE','DEL','LA','LAS','LOS','Y'].includes(t)));
const overlap=(x,y)=>{let n=0;for(const t of x)if(y.has(t))n++;return n;};
let privateLayer=null;
if(nominaDetalle&&personal){
 const emps=personal.employees.map(e=>({...e,t:tok(e.nombre)}));
 const empHours=new Map(),partEmp=new Map(personal.parts.map(p=>[String(p.id),p.emp]));
 for(const p of parts){const e=partEmp.get(p.id);if(!e)continue;const k=e+'|'+month(p.date);const x=empHours.get(k)||{hours:0,partes:0,km:0,rev:0};x.hours+=p.hours;x.km+=p.km;x.rev+=p.accessRevenue;x.partes++;empHours.set(k,x);}
 const match=(name)=>{
  const t=tok(name);let best=null,sc=0,second=0;
  for(const e of emps){const o=overlap(t,e.t);if(!o)continue;const s=o/Math.min(t.size,e.t.size)*(o>=3||o===Math.min(t.size,e.t.size)?1:0.5)+o/(t.size+e.t.size-o)*0.25;if(s>sc){second=sc;sc=s;best=e;}else if(s>second)second=s;}
  return best&&sc>=0.85&&sc-second>=0.1?best:null;
 };
 const byPerson=new Map();let casadas=0,total=0;
 for(const r of nominaDetalle.rows){
  if(r.period<data.metadata.from.slice(0,7))continue;
  const e=match(r.nombre);total++;if(e)casadas++;
  const key=e?('a'+e.id):('n'+norm(r.nombre)+'|'+r.company);
  if(!byPerson.has(key))byPerson.set(key,{key,name:r.nombre,company:r.company,accessId:e?.id??null,tipo:e?Object.entries(e.tipo).filter(([,v])=>v).map(([k])=>k):[],costeHoraOrd:e?.costeHoraOrd??null,sueldoPactado:e?.sueldoPactado??null,rows:[]});
  const h=e?empHours.get(e.id+'|'+r.period):null;
  byPerson.get(key).rows.push({period:r.period,company:r.company,section:r.seccion,cost:r.cost,devengos:r.devengos,ss:r.ss,dietas:r.dietas,extras:r.extras,hours:h?round(h.hours,1):null,km:h?round(h.km,0):null,revenue:h?round(h.rev,2):null,partes:h?.partes??null});
 }
 privateLayer={generatedAt:new Date().toISOString(),people:[...byPerson.values()],match:{casadas,total},sectionLabels:cfg.sections,typeLabels:cfg.typeLabels};
}
// Recorridos reales (GPS) de cada camión en sus últimos 30 días con traza, para el mapa de su ficha (Roberto 24/09: «no tienes
// mapas»). Salen del trazas_viajes.jsonl.gz de esta lectura (ver_dia_mapa.py). Opcional: sin él, la ficha va sin mapa.
// Cada recorrido: [fecha, nº del día, origen, destino, carga[lat,lon], descarga[lat,lon], cargado, vacío]; los caminos van
// en enteros de 1e-4 grados (~11 m) y en diferencias (el primer punto entero; los demás, el salto desde el anterior).
try{
 const {createGunzip}=await import('node:zlib'),{createReadStream}=await import('node:fs'),readline=await import('node:readline');
 const f=path.join(root,'trazas_viajes.jsonl.gz');await fs.access(f);
 const pk=s=>String(s||'').toUpperCase().replace(/[^A-Z0-9]/g,''),enc=ps=>{if(!Array.isArray(ps)||ps.length<2)return null;const o=[];let la=0,lo=0;for(const [a,b] of ps){const A=Math.round(a*1e4),B=Math.round(b*1e4);o.push(A-la,B-lo);la=A;lo=B;}return o;};
 const q=p=>Array.isArray(p)?[Math.round(p[0]*1e4)/1e4,Math.round(p[1]*1e4)/1e4]:null;
 let lug={};try{lug=JSON.parse(await fs.readFile(path.join(process.argv[3]||'','coords_lugares_por_casa.json'),'utf8'));}catch(e){}
 const nom=(emp,cod)=>{const c=String(cod||'');const x=lug[String(emp||'').toLowerCase()+'|'+c];return (x&&x.nombre)||c;};
 const todos=new Map(),ultimo=new Map();
 const rl=readline.createInterface({input:createReadStream(f).pipe(createGunzip()),crlfDelay:Infinity});
 for await(const line of rl){if(!line)continue;const x=JSON.parse(line);if(x.espejo_de||!x.mat||!x.fecha)continue;const k=pk(x.mat);if(!(x.cargado||x.vacio))continue;(todos.get(k)||todos.set(k,[]).get(k)).push(x);if(!ultimo.has(k)||x.fecha>ultimo.get(k))ultimo.set(k,x.fecha);}
 const menos=(d,n)=>{const t=new Date(d+'T12:00:00Z');t.setUTCDate(t.getUTCDate()-n);return t.toISOString().slice(0,10);};
 const rec={};let n=0;
 for(const [k,xs] of todos){const desde=menos(ultimo.get(k),30);rec[k]=xs.filter(x=>x.fecha>=desde).sort((a,b)=>(a.fecha+String(a.orden_dia||0).padStart(3,'0')).localeCompare(b.fecha+String(b.orden_dia||0).padStart(3,'0'))).map(x=>[x.fecha,x.orden_dia||null,nom(x.empresa,x.origen),nom(x.empresa,x.destino),q(x.posc),q(x.posd),enc(x.cargado),enc(x.vacio)]);n+=rec[k].length;}
 data.recorridos={dias:30,camiones:Object.keys(rec).length,viajes:n,porMatricula:rec};
}catch(e){if(e.code!=='ENOENT')console.error('Aviso: recorridos no incluidos ('+e.message+')');}
await fs.writeFile(path.join(root,'current.json.gz'),gzipSync(JSON.stringify(data),{level:9}));
if(privateLayer)await fs.writeFile(path.join(root,'personal_private.json'),JSON.stringify(privateLayer));
console.log(JSON.stringify({ledger:ledger?{rows:ledger.rows.length,lastClosed:ledger.meta.lastClosed}:null,quality:data.metadata.quality.partesKmImposible+' partes con km imposibles ('+data.metadata.quality.kmExcluidos+' km)',parts:parts.length,lines:lines.length,headers:g.headers.length,unmappedParts:parts.filter(p=>!p.plate).length,solred:!!fuel.solred,surtidor:!!fuel.surtidor,payrollRows:payroll?.rows.length||0,stations:usedStations.size,naveIds,coverage,private:privateLayer?{personas:privateLayer.people.length,casadas:privateLayer.match.casadas,total:privateLayer.match.total}:null}));
