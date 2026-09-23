// Una sola lógica para tarjetas, gráficos, tablas, filtros y comprobaciones.
export const UNASSIGNED = 'Sin asignar';
export const sum = (rows, field) => rows.reduce((n,r)=>n+(Number(r[field])||0),0);
export const divide = (a,b) => b > 0 ? a/b : null;
export const inRange = (d,from,to) => Boolean(d) && d>=from && d<=to;
export const includes = (values,v) => !values?.length || values.includes(v||UNASSIGNED);
export function createModel(data) {
  const weights = new Map();
  // El reparto es mensual, fijo y explícitamente estimado. Los filtros nunca
  // trasladan a un cliente costes que correspondían a los demás.
  for (const line of data.lines) {
    if (!line.plate || line.revenue<=0 || line.kind!=='Linea GesRuta') continue;
    const key = line.lineDate.slice(0,7)+'|'+line.plate;
    if (!weights.has(key)) weights.set(key,new Map());
    const group=JSON.stringify([line.company,line.clientId,line.load,line.concept]);
    const map=weights.get(key);
    if(!map.has(group)) map.set(group,{company:line.company,clientId:line.clientId,client:line.client,load:line.load,concept:line.concept,weight:0});
    map.get(group).weight+=line.revenue;
  }
  for(const [key,map] of weights) {
    const rows=[...map.values()],total=sum(rows,'weight');
    weights.set(key,rows.map(r=>({...r,share:r.weight/total})));
  }
  // Modo «con nómina real»: el conductor de los partes (ordinarias + extras + gastos de empleado = dietas) se ajusta
  // cada mes y tipo de trabajo a la nómina real de la gestoría. El factor se fija ANTES de filtrar, con todos los
  // partes, igual que el reparto de costes: filtrar nunca lo cambia. Sin nómina de ese mes, factor 1 (nunca cero).
  const payroll=data.payroll,sections=payroll?.sections||{},typeOfCategory=payroll?.categoryType||{};
  const pool=new Map(),imputed=new Map(),factor=new Map();
  const driverBlock=(p)=>p.driver+p.overtime+p.expensesDriver;
  for(const r of payroll?.rows||[]){const s=sections[r.company]?.[String(r.section)];if(s?.driver){const k=r.period+'|'+s.type;pool.set(k,(pool.get(k)||0)+r.cost);}}
  for(const p of data.parts){const t=typeOfCategory[p.category];if(t){const k=p.date.slice(0,7)+'|'+t;imputed.set(k,(imputed.get(k)||0)+driverBlock(p));}}
  for(const [k,imp] of imputed){const pl=pool.get(k);factor.set(k,pl>0&&imp>0?pl/imp:1);}
  for(const p of data.parts){const t=typeOfCategory[p.category],f=t?(factor.get(p.date.slice(0,7)+'|'+t)??1):1,blk=driverBlock(p);p.realFactor=f;p.real=(p.componentDirect-blk+blk*f)*(1+p.rate);}
  const payrollMonths=new Set(Object.values(payroll?.meta?.periodos||{}).flat());
  function match(r,f,scope=true) {
    return includes(f.plates,r.plate) && includes(f.categories,r.category)
      && (!scope || (includes(f.companies,r.company)&&includes(f.clients,r.clientId)&&includes(f.loads,r.load)&&includes(f.concepts,r.concept)));
  }
  function select(f) {
    const dateField=f.dateBasis==='line'?'lineDate':'invoiceDate';
    const lines=data.lines.filter(r=>inRange(r[dateField],f.from,f.to)&&match(r,f));
    const physicalParts=data.parts.filter(r=>inRange(r.date,f.from,f.to)&&match(r,f,false));
    const costs=[];
    for(const part of physicalParts) {
      const options=weights.get(part.date.slice(0,7)+'|'+part.plate)||[{company:UNASSIGNED,clientId:UNASSIGNED,client:UNASSIGNED,load:UNASSIGNED,concept:UNASSIGNED,share:1}];
      for(const dest of options) {
        const row={...part,...dest};
        // Ambas incluye el coste pendiente; una sociedad concreta no se lo apropia.
        if(!match(row,f))continue;
        costs.push(row);
      }
    }
    return {lines,costs,physicalParts,dateField};
  }
  function aggregate(lines,costs,dateField,costMode='stored') {
    let revenue=0,matchedRevenue=0,rawCost=0,calcCost=0,realCost=0,km=0,hours=0,litres=0,partEquivalents=0,accessRevenue=0,tripsAccess=0,m3=0,tonnes=0,loaded=0,empty=0;
    const invoices=new Set(),trips=new Set(),deliveries=new Set(),parts=new Set(),plates=new Set();
    const breakdown=Object.fromEntries(data.costFields.map(([k])=>[k,0]));
    const coveredMonths=new Set(costs.map(r=>r.date.slice(0,7)+'|'+r.plate));
    for(const r of lines) {
      revenue+=r.revenue;
      if(r.plate&&coveredMonths.has(r[dateField].slice(0,7)+'|'+r.plate))matchedRevenue+=r.revenue;
      invoices.add(r.invoiceId);if(r.plate)plates.add(r.plate);
      if(r.trip){trips.add(r.company+'|'+r.trip);deliveries.add(r.company+'|'+r.trip+'|'+r.delivery);}
    }
    for(const r of costs) {
      const s=r.share;rawCost+=r.stored*s;calcCost+=r.recalculated*s;realCost+=r.real*s;km+=r.km*s;hours+=r.hours*s;litres+=r.litres*s;
      accessRevenue+=r.accessRevenue*s;tripsAccess+=r.trips*s;m3+=r.m3*s;tonnes+=r.tonnes*s;loaded+=r.loaded*s;empty+=r.empty*s;
      partEquivalents+=s;parts.add(r.id);if(r.plate)plates.add(r.plate);
      const f=costMode==='real'?r.realFactor:1,blk=driverBlock(r);
      for(const [k] of data.costFields){
        if(k==='structure')breakdown[k]+=(costMode==='stored'?r.structure:(r.componentDirect-blk+blk*f)*r.rate)*s;
        else if(k==='residual')breakdown[k]+=(costMode==='stored'?r.residual:0)*s;
        else breakdown[k]+=(['driver','overtime','expensesDriver'].includes(k)?(r[k]||0)*f:(r[k]||0))*s;
      }
    }
    const cost=costMode==='real'?realCost:costMode==='recalculated'?calcCost:rawCost;
    const coverage=divide(matchedRevenue,revenue);
    return {revenue,matchedRevenue,uncoveredRevenue:revenue-matchedRevenue,cost,rawCost,calcCost,realCost,costDifference:calcCost-rawCost,
      balance:revenue-cost,comparableMargin:matchedRevenue-cost,coverage,marginPct:divide(revenue-cost,revenue),km,hours,litres,m3,tonnes,loaded,empty,
      invoices:invoices.size,trips:trips.size,deliveries:deliveries.size,parts:parts.size,partEquivalents,tripsAccess,plates:plates.size,accessRevenue,
      consumption:divide(litres*100,km),costKm:divide(cost,km),costHour:divide(cost,hours),revenueKm:divide(revenue,km),emptyPct:divide(empty,loaded+empty),
      // Ratios de rentabilidad: por € gastado, por km y por hora (sobre el coste y las horas/km que tenga esta lectura).
      revenuePerCost:divide(revenue,cost),profitPerCost:divide(revenue-cost,cost),profitKm:divide(revenue-cost,km),revenueHour:divide(revenue,hours),profitHour:divide(revenue-cost,hours),breakdown};
  }
  function group(selected,f,dimension='plate') {
    const {lines,costs,dateField}=selected;
    const totals=aggregate(lines,costs,dateField,f.costMode);
    const maps=new Map();
    const rowKey=(r,isCost)=>dimension==='month'?(isCost?r.date:r[dateField]).slice(0,7):dimension==='client'?r.clientId:dimension==='company'?r.company:dimension==='load'?r.load:dimension==='concept'?r.concept:r.plate||'Sin matrícula';
    for(const [rs,isCost] of [[lines,false],[costs,true]])for(const r of rs){
      const key=rowKey(r,isCost)||UNASSIGNED;
      if(!maps.has(key))maps.set(key,{key,label:dimension==='client'?r.client:dimension==='plate'?(r.plateLabel||key):key,lines:[],costs:[]});
      maps.get(key)[isCost?'costs':'lines'].push(r);
    }
    const groups=[...maps.values()].map(g=>({key:g.key,label:g.label,...aggregate(g.lines,g.costs,dateField,f.costMode)}));
    return {...selected,totals,groups};
  }
  const run=(f,dimension='plate')=>group(select(f),f,dimension);
  // ---- Conciliaciones: son globales (no dependen de los segmentadores) y se calculan con todos los partes.
  function reconcilePersonnel(){
    if(!payroll)return null;
    const months=[...new Set(payroll.rows.map(r=>r.period))].sort(),imputedAll=new Map();
    for(const p of data.parts){const m=p.date.slice(0,7);imputedAll.set(m,(imputedAll.get(m)||0)+driverBlock(p));}
    const rows=months.map(m=>{let real=0;for(const [k,v] of pool)if(k.startsWith(m+'|'))real+=v;const imp=imputedAll.get(m)||0;return {month:m,payroll:real,imputed:imp,pct:real>0?imp/real:null,gap:real-imp};});
    const last=months[months.length-1],types={};
    for(const [k,v] of pool){const [m,t]=k.split('|');if(m===last)types[t]={payroll:v,imputed:imputed.get(k)||0};}
    const byType=Object.entries(types).map(([t,v])=>({type:t,label:payroll.typeLabels[t]||t,...v,pct:v.payroll>0?v.imputed/v.payroll:null}));
    let overhead=0;for(const r of payroll.rows)if(r.period===last&&!sections[r.company]?.[String(r.section)]?.driver)overhead+=r.cost;
    const structure=data.parts.filter(p=>p.date.slice(0,7)===last).reduce((s,p)=>s+p.structure,0);
    const tp=rows.reduce((s,r)=>s+r.payroll,0),ti=rows.reduce((s,r)=>s+r.imputed,0);
    return {rows,byType,last,structure,overhead,cumulative:tp>0?ti/tp:null,versions:payroll.versions||[]};
  }
  function reconcileFuel(){
    const sol=data.fuel?.solred,sur=data.fuel?.surtidor;if(!sol&&!sur)return null;
    const nave=new Set(data.metadata.naveStations||[]),owners=[...new Set(data.parts.map(p=>p.owner))].filter(o=>o!=='Sin titular');
    const months=[...new Set((sol?.rows||[]).map(r=>r.month))].sort();
    const rows=months.map(m=>{
      const pm=data.parts.filter(p=>p.date.slice(0,7)===m),fuelParts=pm.filter(p=>p.litres>0),byOwner={};
      for(const o of owners){
        const declared=fuelParts.filter(p=>p.owner===o&&!nave.has(p.station)).reduce((s,p)=>s+p.litres,0);
        const card=(sol?.rows||[]).filter(r=>r.month===m&&r.kind==='gasoleo'&&r.owner===o).reduce((s,r)=>s+r.litros,0);
        byOwner[o]={declared,card};
      }
      const sum=(rs,f)=>rs.reduce((s,r)=>s+f(r),0),card=(k)=>(sol?.rows||[]).filter(r=>r.month===m&&r.kind===k);
      return {month:m,declared:sum(fuelParts,p=>p.litres),declaredNave:sum(fuelParts.filter(p=>nave.has(p.station)),p=>p.litres),card:sum(card('gasoleo'),r=>r.litros),pump:sum((sur?.rows||[]).filter(r=>r.month===m),r=>r.litros),byOwner,
        adblue:{declaredL:sum(pm,p=>p.adblueLitres),declaredEur:sum(pm,p=>p.adblue),cardL:sum(card('adblue'),r=>r.litros),cardEur:sum(card('adblue'),r=>r.base)},
        tolls:{card:sum(card('peaje'),r=>r.base),expensesVehicle:sum(pm,p=>p.expensesVehicle)}};
    });
    return {rows,owners,solred:sol?.meta||null,surtidor:sur?.meta||null};
  }
  // ---- Contabilidad real (CxConta): la referencia de rentabilidad. Por sociedad y mes; solo meses cerrados.
  const ledger=data.ledger||null;
  const societyOf=(owner)=>{const up=String(owner||'').toUpperCase();for(const [k,v] of Object.entries(ledger?.titularASociedad||{}))if(up.includes(k))return v;return null;};
  // Cada matrícula, ¿de qué sociedad es? (por mayoría de sus partes de Access). Sirve para separar los viajes hechos con
  // NUESTROS camiones de los subcontratados: un viaje facturado con una matrícula que no es de la sociedad es subcontratado
  // (para Agetrans, un viaje con camión de Razo es subcontratado a Razo; a nivel grupo, un camión de Razo sí es propio).
  const plateSociety=(()=>{const cnt=new Map();for(const p of data.parts){if(!p.plate)continue;const s=societyOf(p.owner);if(!s)continue;const m=cnt.get(p.plate)||{};m[s]=(m[s]||0)+1;cnt.set(p.plate,m);}const out=new Map();for(const [pl,m] of cnt)out.set(pl,Object.entries(m).sort((a,b)=>b[1]-a[1])[0][0]);return out;})();
  function ownFleet(f){
    const names=ledger?Object.values(ledger.sociedades):['Razo','Agetrans'],wanted=f.companies?.length?f.companies:names;
    const own=new Set();for(const [pl,s] of plateSociety)if(wanted.includes(s))own.add(pl);
    const from=f.from.slice(0,7),to=f.to.slice(0,7);
    let total=0,ownRev=0,noPlate=0,other=0;
    for(const l of data.lines){const m=(l.invoiceDate||'').slice(0,7);if(m<from||m>to)continue;if(!wanted.includes(l.company))continue;const r=l.revenue||0;total+=r;if(!l.plate)noPlate+=r;else if(own.has(l.plate))ownRev+=r;else other+=r;}
    return {total,own:ownRev,sub:total-ownRev,noPlate,otherSoc:other,fraction:total>0?ownRev/total:null};
  }
  const monthList=(from,to)=>{const out=[];let [y,m]=from.slice(0,7).split('-').map(Number);const [ye,me]=to.slice(0,7).split('-').map(Number);while(y<ye||(y===ye&&m<=me)){out.push(y+'-'+String(m).padStart(2,'0'));if(++m>12){m=1;y++;}}return out;};
  const monthEnd=(month)=>{const [y,m]=month.split('-').map(Number);return month+'-'+String(new Date(Date.UTC(y,m,0)).getUTCDate()).padStart(2,'0');};
  function ledgerView(f){
    if(!ledger)return null;
    const names=ledger.sociedades,wanted=f.companies?.length?f.companies:Object.values(names),closed=ledger.meta.lastClosed;
    const all=monthList(f.from,f.to),months=all.filter(m=>!closed||m<=closed),excludedMonths=all.filter(m=>closed&&m>closed);
    const set=new Set(months),rows=ledger.rows.filter(r=>set.has(r.month)&&wanted.includes(names[r.company]));
    // Intragrupo (facturación consolidada): ingreso/gasto entre Razo y Agetrans medido en el libro. El ingreso es siempre
    // servicio de transporte (705 -> 'servicios') y el gasto subcontratación (607 -> 'subcontratacion'); consolidar = quitarlos.
    const intra=(ledger.intragrupo||[]).filter(r=>set.has(r.month)&&wanted.includes(names[r.company]));
    const igIncome=intra.reduce((s,r)=>s+(r.ingreso||0),0),igExpense=intra.reduce((s,r)=>s+(r.gasto||0),0);
    const igByCompany=Object.values(names).filter(n=>wanted.includes(n)).map(n=>{const rs=intra.filter(r=>names[r.company]===n);return {key:n,income:rs.reduce((s,r)=>s+(r.ingreso||0),0),expense:rs.reduce((s,r)=>s+(r.gasto||0),0)};});
    const igByMonth=months.map(m=>{const rs=intra.filter(r=>r.month===m);return {key:m,income:rs.reduce((s,r)=>s+(r.ingreso||0),0),expense:rs.reduce((s,r)=>s+(r.gasto||0),0)};});
    const intragrupo={income:igIncome,expense:igExpense,net:igIncome-igExpense,byCompany:igByCompany,byMonth:igByMonth,metodo:ledger.meta.intragrupoMetodo||''};
    const con=!!f.consolidado;
    const income=rows.filter(r=>r.kind==='i').reduce((s,r)=>s+r.amount,0)-(con?igIncome:0);
    const expenses=rows.filter(r=>r.kind==='g').reduce((s,r)=>s+r.amount,0)-(con?igExpense:0);
    const cat=(kind)=>ledger.categories[kind==='g'?'gastos':'ingresos'].map(c=>{let amount=rows.filter(r=>r.kind===kind&&r.cat===c.id).reduce((s,r)=>s+r.amount,0);if(con&&kind==='i'&&c.id==='servicios')amount-=igIncome;if(con&&kind==='g'&&c.id==='subcontratacion')amount-=igExpense;return {...c,amount};}).filter(c=>Math.abs(c.amount)>.5).sort((a,b)=>b.amount-a.amount);
    const byMonth=months.map(m=>{const rs=rows.filter(r=>r.month===m),ig=con?igByMonth.find(x=>x.key===m):null,i=rs.filter(r=>r.kind==='i').reduce((s,r)=>s+r.amount,0)-(ig?ig.income:0),g=rs.filter(r=>r.kind==='g').reduce((s,r)=>s+r.amount,0)-(ig?ig.expense:0);return {key:m,income:i,expenses:g,result:i-g,marginPct:divide(i-g,i)};});
    const byCompany=Object.values(names).filter(n=>wanted.includes(n)).map(n=>{const rs=rows.filter(r=>names[r.company]===n),ig=con?igByCompany.find(x=>x.key===n):null,i=rs.filter(r=>r.kind==='i').reduce((s,r)=>s+r.amount,0)-(ig?ig.income:0),g=rs.filter(r=>r.kind==='g').reduce((s,r)=>s+r.amount,0)-(ig?ig.expense:0);return {key:n,income:i,expenses:g,result:i-g,marginPct:divide(i-g,i)};});
    const partial=months.length>0&&(f.from.slice(0,7)===months[0]&&f.from.slice(8)!=='01'||(f.to.slice(0,7)===months[months.length-1]&&f.to<monthEnd(months[months.length-1])));
    // Detalle por CUENTA contable (para desplegar cada naturaleza). El ajuste intragrupo se hace por categoría, no por cuenta.
    const accMap=new Map();
    for(const r of rows){const k=r.kind+'|'+r.cat+'|'+r.cuenta;let x=accMap.get(k);if(!x){x={cuenta:r.cuenta,label:ledger.accounts?.[r.cuenta]||'',kind:r.kind,cat:r.cat,amount:0};accMap.set(k,x);}x.amount+=r.amount;}
    const accounts=[...accMap.values()].filter(a=>Math.abs(a.amount)>.5).sort((a,b)=>b.amount-a.amount);
    return {income,expenses,result:income-expenses,marginPct:divide(income-expenses,income),months,excludedMonths,partial,expenseCategories:cat('g'),incomeCategories:cat('i'),accounts,byMonth,byCompany,lastClosed:closed,consolidado:con,intragrupo};
  }
  // Coste de personal ACUMULADO por tramo (sección de la nómina) en el periodo y sociedades elegidos. Agregado, sin
  // nombres: suma el coste de empresa de la gestoría por tipo de trabajo (conductor hormigonera/nacional/bañera,
  // administración, taller…). Sirve para el acumulado y para comparar un periodo con otro.
  function personnelByTramo(f){
    if(!payroll)return null;
    const from=f.from.slice(0,7),to=f.to.slice(0,7);
    const names=Object.keys(sections||{}),wanted=f.companies?.length?f.companies:(names.length?names:['Razo','Agetrans']);
    const rows=payroll.rows.filter(r=>r.period>=from&&r.period<=to&&wanted.includes(r.company));
    const map=new Map();
    for(const r of rows){
      const s=sections[r.company]?.[String(r.section)],type=s?.type||'otros';
      const x=map.get(type)||{type,label:payroll.typeLabels?.[type]||type,driver:!!s?.driver,unsure:false,cost:0,months:new Set()};
      x.cost+=r.cost||0;x.months.add(r.period);if(s?.porConfirmar)x.unsure=true;
      map.set(type,x);
    }
    const items=[...map.values()].map(x=>({type:x.type,label:x.label,driver:x.driver,unsure:x.unsure,cost:x.cost,months:x.months.size})).sort((a,b)=>b.cost-a.cost);
    const total=items.reduce((s,x)=>s+x.cost,0),monthsAll=[...new Set(rows.map(r=>r.period))].sort();
    return {items,total,months:monthsAll.length,monthList:monthsAll,driverCost:items.filter(x=>x.driver).reduce((s,x)=>s+x.cost,0),structureCost:items.filter(x=>!x.driver).reduce((s,x)=>s+x.cost,0)};
  }
  // Puente: lo que dice la contabilidad frente a lo que captan los partes de Access, por concepto (mismos meses y sociedades).
  function bridge(f){
    const view=ledgerView(f);if(!view)return null;
    const names=ledger.sociedades,wanted=f.companies?.length?f.companies:Object.values(names),set=new Set(view.months);
    const rows=ledger.rows.filter(r=>r.kind==='g'&&set.has(r.month)&&wanted.includes(names[r.company]));
    const ps=data.parts.filter(p=>set.has(p.date.slice(0,7))&&wanted.includes(societyOf(p.owner)));
    const groups=ledger.puente.map(g=>{
      let led=rows.filter(r=>g.cats.includes(r.cat)).reduce((s,r)=>s+r.amount,0);
      if(f.consolidado&&g.id==='subcontratacion')led-=view.intragrupo.expense; // la subcontratación a la otra casa se elimina
      const parts=ps.reduce((s,p)=>s+g.partes.reduce((a,k)=>a+(p[k]||0),0),0);
      return {id:g.id,label:g.label,note:g.nota||'',ledger:led,parts,difference:led-parts,coverage:g.partes.length?divide(parts,led):0,inParts:g.partes.length>0};
    });
    const residual=ps.reduce((s,p)=>s+p.residual,0);
    const totalLedger=groups.reduce((s,g)=>s+g.ledger,0),totalParts=groups.reduce((s,g)=>s+g.parts,0)+residual;
    return {groups,residual,totalLedger,totalParts,coverage:divide(totalParts,totalLedger),missing:totalLedger-totalParts,parts:ps.length,months:view.months,view};
  }
  // ---- Telemática (Movertis, vía el ERP): km y litros medidos por el propio camión; solo días fiables.
  const telemetry=data.telemetry||null;
  function telemetryView(f){
    if(!telemetry)return null;
    const from=f.from>telemetry.meta.desde?f.from:telemetry.meta.desde,to=f.to<telemetry.meta.hasta?f.to:telemetry.meta.hasta;
    if(from>to)return null;
    const plates=f.plates?.length?new Set(f.plates):null;
    const rows=telemetry.rows.filter(r=>r.date>=from&&r.date<=to&&(!plates||plates.has(r.plate)));
    if(!rows.length)return null;
    const partKm=new Map();
    for(const p of data.parts){if(p.date<from||p.date>to)continue;const k=p.plate+'|'+p.date;partKm.set(k,(partKm.get(k)||0)+p.km);}
    const has=(r)=>partKm.has(r.plate+'|'+r.date),active=rows.filter(r=>r.km>=30),withPart=active.filter(has),without=active.filter(r=>!has(r));
    const porFuente={};for(const r of rows)porFuente[r.src||'erp']=(porFuente[r.src||'erp']||0)+1;   // de dónde sale cada día-camión del periodo
    const withFuel=active.filter(r=>r.litres>0),litres=sum(withFuel,'litres'),kmFuel=sum(withFuel,'km'),kmWith=sum(withPart,'km');
    const partKmSame=withPart.reduce((s,r)=>s+partKm.get(r.plate+'|'+r.date),0);
    const byPlate=new Map();
    for(const r of active){
      const x=byPlate.get(r.plate)||{key:r.plate,label:r.plate,activeDays:0,daysWithoutPart:0,km:0,kmWithoutPart:0,litres:0,kmFuel:0,daysFuel:0};
      x.activeDays++;x.km+=r.km;if(!has(r)){x.daysWithoutPart++;x.kmWithoutPart+=r.km;}if(r.litres>0){x.litres+=r.litres;x.kmFuel+=r.km;x.daysFuel++;}
      byPlate.set(r.plate,x);
    }
    const plateRows=[...byPlate.values()].map(x=>({...x,sensor:x.litres>0,consumption:x.litres>0?divide(x.litres*100,x.kmFuel):null,pctWithoutPart:divide(x.daysWithoutPart,x.activeDays)})).sort((a,b)=>b.kmWithoutPart-a.kmWithoutPart);
    // Sensor de consumo (litros por CANbus): NO lo llevan todos. Solo los vehículos CON MOTOR (tractora, rígido) pueden
    // tenerlo; un remolque no gasta gasoil. Se clasifica por el tipo del ERP (razo_clase), no por la matrícula. El inventario
    // se hace sobre TODAS las matrículas medidas en el periodo (no solo las que superan 30 km/día), que es la flota real.
    const clases=telemetry.clases||{},inv=new Map();
    for(const r of rows){const x=inv.get(r.plate)||{plate:r.plate,clase:clases[r.plate]||'',km:0,litres:0,kmFuel:0};x.km+=r.km;if(r.litres>0){x.litres+=r.litres;x.kmFuel+=r.km;}inv.set(r.plate,x);}
    const motorClases=['tractora','rigido','camion','furgoneta'];
    const invRows=[...inv.values()].map(x=>({label:x.plate,clase:x.clase||'',motor:motorClases.includes(x.clase)||x.litres>0,sensor:x.litres>0,km:x.km,litres:x.litres,consumption:x.litres>0?divide(x.litres*100,x.kmFuel):null}));
    const motor=invRows.filter(r=>r.motor),trailers=invRows.filter(r=>r.clase==='remolque'),otros=invRows.filter(r=>!r.motor&&r.clase!=='remolque');
    const motorNoSensor=motor.filter(r=>!r.sensor).sort((a,b)=>b.km-a.km);
    const sensorInv={motor:motor.length,conSensor:motor.filter(r=>r.sensor).length,sinSensor:motorNoSensor.length,sinSensorPlates:motorNoSensor.map(r=>r.label),remolques:trailers.length,otros:otros.length,rows:motor.slice().sort((a,b)=>b.km-a.km)};
    return {from,to,km:sum(active,'km'),litres,kmFuel,consumption:divide(litres*100,kmFuel),activeDays:active.length,daysWithoutPart:without.length,pctWithoutPart:divide(without.length,active.length),kmWithoutPart:sum(without,'km'),kmWithPart:kmWith,ratio:divide(partKmSame,kmWith),plates:byPlate.size,plateRows,sensorInv,dias:rows.length,porFuente,recortado:from!==f.from||to!==f.to};
  }
  // ---- Actividad operativa (GesRuta): viajes reales (albarán de cantera), km, m³/t e importe, por mes/cliente/vehículo.
  const activity=data.actividad||null;
  function activityView(f){
    if(!activity)return null;
    const A=activity;                                    // filas posicionales [c,m,ci,mi,oi,di,li,ld,km,m3,t,imp,h]
    const C=0,M=1,CI=2,MI=3,OI=4,DI=5,LI=6,LD=7,KM=8,M3=9,T=10,IMP=11;
    const from=f.from.slice(0,7),to=f.to.slice(0,7),wanted=f.companies?.length?f.companies:['Razo','Agetrans'];
    const wc=new Set(wanted.map(w=>A.co.indexOf(w)).filter(i=>i>=0));
    const rows=A.rows.filter(r=>{const m=A.mo[r[M]];return m>=from&&m<=to&&wc.has(r[C]);});
    if(!rows.length)return null;
    const blank=k=>({key:k,viajes:0,km:0,m3:0,t:0,imp:0});
    const add=(x,r)=>{x.viajes++;x.km+=r[KM];x.m3+=r[M3];x.t+=r[T];x.imp+=r[IMP];};
    const tot=blank('');for(const r of rows)add(tot,r);
    const mMap=new Map();for(const r of rows){const k=A.mo[r[M]];let x=mMap.get(k);if(!x){x=blank(k);mMap.set(k,x);}add(x,r);}
    const byMonth=[...mMap.values()].sort((a,b)=>a.key<b.key?-1:1);
    const grp=(fn)=>{const map=new Map();for(const r of rows){const k=fn(r)||'(sin asignar)';let x=map.get(k);if(!x){x=blank(k);map.set(k,x);}add(x,r);}return [...map.values()].sort((a,b)=>b.viajes-a.viajes);};
    // Zonas anidadas en TRES niveles: provincia -> localidad (pueblo) -> punto (planta, cantera u obra).
    // paths(r) da los extremos que cuentan para el viaje (salida, llegada o ambos). Un viaje suma UNA sola vez en cada
    // nodo aunque sus dos extremos caigan en el mismo (p. ej. sale y llega en A Coruña: cuenta una vez en A Coruña).
    const PO=13,PD=14;
    const arbol=(paths)=>{
      const top=new Map();
      for(const r of rows){
        const visto=new Set();
        for(const [pi,li,qi] of paths(r)){
          const p=A.prov[pi],lc=A.loc[li],pn=A.pt?(A.pt[qi]??A.pt[0]):null;
          let z=top.get(p);if(!z){z=blank(p);z.hijos=new Map();top.set(p,z);}
          if(!visto.has('P'+p)){visto.add('P'+p);add(z,r);}
          let l=z.hijos.get(lc);if(!l){l=blank(lc);l.hijos=new Map();z.hijos.set(lc,l);}
          if(!visto.has('L'+p+'|'+lc)){visto.add('L'+p+'|'+lc);add(l,r);}
          if(pn!=null){let q=l.hijos.get(pn);if(!q){q=blank(pn);l.hijos.set(pn,q);}
            if(!visto.has('Q'+p+'|'+lc+'|'+pn)){visto.add('Q'+p+'|'+lc+'|'+pn);add(q,r);}}
        }
      }
      const ord=m=>[...m.values()].sort((a,b)=>b.viajes-a.viajes);
      return ord(top).map(z=>({...z,hijos:ord(z.hijos).map(l=>({...l,hijos:ord(l.hijos)}))}));
    };
    const zonasAmbos=arbol(r=>[[r[OI],r[LI],r[PO]],[r[DI],r[LD],r[PD]]]);
    const rutas=grp(r=>A.prov[r[OI]]+' → '+A.prov[r[DI]]);
    return {tot,byMonth,byClient:grp(r=>A.cli[r[CI]]),byVeh:grp(r=>A.mat[r[MI]]||'(sin matrícula)'),
            zonasSalida:arbol(r=>[[r[OI],r[LI],r[PO]]]),zonasLlegada:arbol(r=>[[r[DI],r[LD],r[PD]]]),zonasAmbos,rutas,months:byMonth.map(m=>m.key),from,to};
  }
  function marginView(f){
    if(!activity||!activity.margen)return null;                 // P&L operativo de GesRuta (inggas): ingreso - gasto directo por viaje
    const A=activity,from=f.from.slice(0,7),to=f.to.slice(0,7),wanted=f.companies?.length?f.companies:['Razo','Agetrans'];
    const wc=new Set(wanted.map(w=>A.co.indexOf(w)).filter(i=>i>=0));
    const rows=A.margen.rows.filter(r=>r.m>=from&&r.m<=to&&wc.has(r.c));
    if(!rows.length)return null;
    const blank=k=>({key:k,ing:0,materiales:0,subcontratacion:0,gasoil:0,peajes:0,adblue:0});
    const add=(x,r)=>{x.ing+=r.i;x.materiales+=r.ma;x.subcontratacion+=r.s;x.gasoil+=r.g;x.peajes+=r.p;x.adblue+=r.ad;};
    const cerrar=x=>{x.directos=x.materiales+x.subcontratacion;x.gasto=x.directos+x.gasoil+x.peajes+x.adblue;x.margen=x.ing-x.gasto;x.margenPct=x.ing?x.margen/x.ing:null;return x;};
    const tot=blank('');for(const r of rows)add(tot,r);cerrar(tot);
    const cMap=new Map();for(const r of rows){let x=cMap.get(r.cli);if(!x){x=blank(r.cli);cMap.set(r.cli,x);}add(x,r);}
    const byClient=new Map();for(const [k,x] of cMap){byClient.set(k,cerrar(x));}
    const mMap=new Map();for(const r of rows){let x=mMap.get(r.m);if(!x){x=blank(r.m);mMap.set(r.m,x);}add(x,r);}
    const byMonth=[...mMap.values()].map(cerrar).sort((a,b)=>a.key<b.key?-1:1);
    return {tot,byClient,byMonth};
  }
  // Margen NETO por cliente y zona: reparte el coste REAL de la contabilidad a cada viaje por su base (litros→combustible,
  // horas→personal, km→flota fija, ingreso→directos e indirectos), escalado al ingreso capturado en los viajes. Así el
  // conjunto cuadra con el margen contable. Marca la fiabilidad (fracción de ingreso con km/horas MEDIDOS por localizador).
  // El reparto es MES A MES: el gasto de cada mes del libro va a los viajes de ese mes (nunca a otro). Dentro del mes, cada
  // partida (combustible, personal, flota) se divide entre los viajes propios MEDIDOS (los que llevan litros/horas/km del
  // localizador) y los NO medidos por su peso en el ingreso; los medidos se la reparten por su base real y los no medidos
  // por su ingreso. Así un mes sin traza no cuelga su gasto de los meses con traza, ni las bañeras medidas cargan con el
  // gasoil de las hormigoneras sin traza. Un mes sin contabilidad cerrada usa los coeficientes del último mes cerrado
  // (coste ESTIMADO, marcado). El impuesto de sociedades no es coste del viaje (margen antes de impuestos).
  function _reparto(f){
    if(!activity||!ledger)return null;
    const lv=ledgerView(f);if(!lv||lv.income<=0)return null;
    const A=activity,C=0,M=1,CI=2,MI=3,DI=5,OI=4,M3=9,T=10,IMP=11,KMR=15,LIT=16,DUR=17,TRM=18,IMPRO=19;
    const from=f.from.slice(0,7),to=f.to.slice(0,7),wanted=f.companies?.length?f.companies:['Razo','Agetrans'];
    const wc=new Set(wanted.map(w=>A.co.indexOf(w)).filter(i=>i>=0));
    const rows=A.rows.filter(r=>{const m=A.mo[r[M]];return m>=from&&m<=to&&wc.has(r[C]);});
    if(!rows.length||A.rows[0].length<21)return null;      // hace falta impro (índice 19) + día (índice 20)
    const sub=r=>(r[IMPRO]||0)>0,nameOf=r=>A.cli[r[CI]],mesOf=r=>A.mo[r[M]];
    const baseOf={lit:r=>r[LIT]||0,dur:r=>r[DUR]||0,km:r=>r[KMR]||0};
    const BASE={combustible:'lit',adblue:'lit',personal:'dur',dietas:'dur',repuestos:'km',reparaciones:'km',seguros:'km',amortizacion:'km',alquileres:'km',peajes:'km',neumaticos:'km'};   // AdBlue por litros de gasoil (su consumo va con el del motor), no por ingreso
    const DIR=new Set(['aridos','subcontratacion','impuesto_sociedades']);   // no van por base: subcontratación por IMPPRO real, áridos por cliente, el impuesto no es coste del viaje
    // Gasto del libro por MES y naturaleza (mismas sociedades y mismo ajuste intragrupo que ledgerView).
    const names=ledger.sociedades,closed=new Set(lv.months),catM=new Map();
    for(const r of ledger.rows){if(r.kind!=='g'||!closed.has(r.month)||!wanted.includes(names[r.company]))continue;const x=catM.get(r.month)||{};x[r.cat]=(x[r.cat]||0)+r.amount;catM.set(r.month,x);}
    if(f.consolidado)for(const ig of lv.intragrupo.byMonth){const x=catM.get(ig.key);if(x)x.subcontratacion=(x.subcontratacion||0)-ig.expense;}
    const incomeM=new Map(lv.byMonth.map(x=>[x.key,x.income]));
    // Bases de cada mes: ingreso total, IMPPRO de los subcontratados y, por partida, base e ingreso de los viajes propios medidos / no medidos.
    const S=new Map();
    for(const r of rows){
      const m=mesOf(r);let s=S.get(m);if(!s){s={SI:0,SP:0,ingOwn:0,meas:{lit:{base:0,ing:0},dur:{base:0,ing:0},km:{base:0,ing:0}},unm:{lit:0,dur:0,km:0},cliIng:new Map(),ownT:new Map(),subT:new Map(),subRet:new Map()};S.set(m,s);}
      const ing=r[IMP]||0,tn=r[T]||0,cn=nameOf(r);s.SI+=ing;
      // Subcontratado: a la subcontrata se le pasa lo suyo (IMPPRO) y el resto es nuestro (Roberto 24/09), también el material
      // que se vende en ese viaje (compraventa): sus toneladas cuentan para repartir el material del cliente.
      if(sub(r)){s.SP+=r[IMPRO]||0;if(tn>0){s.subT.set(cn,(s.subT.get(cn)||0)+tn);s.subRet.set(cn,(s.subRet.get(cn)||0)+Math.max(0,ing-(r[IMPRO]||0)));}continue;}
      s.ingOwn+=ing;s.cliIng.set(cn,(s.cliIng.get(cn)||0)+ing);if(tn>0)s.ownT.set(cn,(s.ownT.get(cn)||0)+tn);
      for(const b of ['lit','dur','km']){const v=baseOf[b](r);if(v>0){s.meas[b].base+=v;s.meas[b].ing+=ing;}else s.unm[b]+=ing;}
    }
    // Material (áridos comprados) por cliente y mes, según el P&L de inggas: no hay coste de material por línea.
    const cliMaM=new Map();
    if(A.margen)for(const g of A.margen.rows){if(!wc.has(g.c)||g.m<from||g.m>to)continue;let mm=cliMaM.get(g.m);if(!mm){mm=new Map();cliMaM.set(g.m,mm);}mm.set(g.cli,(mm.get(g.cli)||0)+(g.ma||0));}
    // Coeficientes por mes.
    const K=new Map();let last=null;
    for(const m of [...S.keys()].sort()){
      const s=S.get(m),cats=catM.get(m);
      if(!cats){K.set(m,null);continue;}                    // sin contabilidad cerrada: se resuelve después con el último mes cerrado
      const inc=incomeM.get(m)||0,scale=inc>0?s.SI/inc:1;    // coste soportado por los viajes = gasto del mes × (ingreso capturado / ingreso libro)
      const bucket={lit:0,dur:0,km:0,imp:0};
      for(const [id,amt] of Object.entries(cats)){if(DIR.has(id))continue;bucket[BASE[id]||'imp']+=amt;}
      const k={m,scale,coef:{},coefU:{},imp:0,factorS:0,dRate:new Map(),sRate:new Map(),estimado:false,gasto:0};
      const subAmt=cats.subcontratacion||0;if(s.SP>0)k.factorS=subAmt*scale/s.SP;else bucket.imp+=subAmt;   // subcontratación: IMPPRO real reescalado a la cuenta 607 del mes
      // Material del cliente y mes: entre sus viajes propios (por ingreso, como siempre) y sus subcontratados que llevan
      // toneladas (por toneladas: el material va con la carga). Parte de los subcontratados = sus toneladas frente a las de
      // los propios; si los propios no llevan toneladas, por el ingreso que nos queda (ingreso − IMPPRO) frente al de los propios.
      const mm=cliMaM.get(m)||new Map(),cls=new Set([...s.cliIng.keys(),...s.subT.keys()]);let sumMa=0;for(const c of cls)sumMa+=mm.get(c)||0;
      const arAmt=cats.aridos||0;
      if(sumMa>0){const fMa=arAmt*scale/sumMa;
        for(const c of cls){const mc=(mm.get(c)||0)*fMa;if(!(mc>0))continue;
          const tS=s.subT.get(c)||0,tO=s.ownT.get(c)||0,iO=s.cliIng.get(c)||0,rS=s.subRet.get(c)||0;
          const pS=tS>0?(iO>0?(tO>0?mc*tS/(tS+tO):mc*rS/(rS+iO)):mc):0;
          if(tS>0)k.sRate.set(c,pS/tS);
          if(iO>0)k.dRate.set(c,(mc-pS)/iO);}
      }else bucket.imp+=arAmt;
      for(const b of ['lit','dur','km']){
        const meas=s.meas[b],unm=s.unm[b],tot=meas.ing+unm;
        if(!(tot>0)){bucket.imp+=bucket[b];k.coef[b]=0;k.coefU[b]=0;continue;}   // sin viajes propios en el mes: todo por ingreso
        const amt=bucket[b]*scale,pm=amt*(meas.ing/tot),pu=amt*(unm/tot);
        k.coef[b]=meas.base>0?pm/meas.base:0;k.coefU[b]=unm>0?pu/unm:0;
      }
      k.imp=s.SI>0?bucket.imp*scale/s.SI:0;
      k.gasto=Object.entries(cats).filter(([id])=>id!=='impuesto_sociedades').reduce((a,[,v])=>a+v,0);
      K.set(m,k);last=k;
    }
    const firstK=[...K.values()].find(Boolean);
    for(const [m,k] of K)if(!k)K.set(m,(last||firstK)?{...(last||firstK),estimado:true,m}:null);   // mes sin cerrar: coeficientes del último cerrado
    const VACIO={combustible:0,personal:0,flota:0,indirectos:0,aridos:0,subcontrata:0,estimado:true};
    const desglose=r=>{
      const k=K.get(mesOf(r));if(!k)return VACIO;
      const ing=r[IMP]||0;
      if(sub(r))return {combustible:0,personal:0,flota:0,indirectos:ing*k.imp,aridos:(r[T]||0)*(k.sRate.get(nameOf(r))||0),subcontrata:(r[IMPRO]||0)*k.factorS,estimado:k.estimado};
      const part=b=>{const v=baseOf[b](r);return v>0?v*k.coef[b]:ing*k.coefU[b];};
      return {combustible:part('lit'),personal:part('dur'),flota:part('km'),indirectos:ing*k.imp,aridos:ing*(k.dRate.get(nameOf(r))||0),subcontrata:0,estimado:k.estimado};
    };
    const cost=r=>{const d=desglose(r);return d.combustible+d.personal+d.flota+d.indirectos+d.aridos+d.subcontrata;};
    const dRateOf=r=>{const k=K.get(mesOf(r));return k?(k.dRate.get(nameOf(r))||0):0;};
    // Coeficientes MEDIOS del periodo, solo para explicarlos: coste de los viajes medidos / sus bases medidas.
    const coef={lit:0,dur:0,km:0,imp:0};{const num={lit:0,dur:0,km:0,imp:0},den={lit:0,dur:0,km:0,imp:0};for(const [m,k] of K){const s=S.get(m);if(!k||!s)continue;for(const b of ['lit','dur','km']){num[b]+=k.coef[b]*s.meas[b].base;den[b]+=s.meas[b].base;}num.imp+=k.imp*s.SI;den.imp+=s.SI;}for(const b in coef)coef[b]=den[b]>0?num[b]/den[b]:0;}
    let SI=0;for(const s of S.values())SI+=s.SI;
    const mesesEstimados=[...K.entries()].filter(([,k])=>k&&k.estimado).map(([m])=>m).sort();
    const isoc=lv.expenseCategories.filter(c=>c.id==='impuesto_sociedades').reduce((a,c)=>a+c.amount,0);
    return {A,rows,cost,desglose,dRateOf,nameOf,sub,coef,K,mesesEstimados,income:lv.income,gasto:lv.expenses-isoc,margenLibroPct:divide(lv.income-(lv.expenses-isoc),lv.income),scale:SI/lv.income,from,to,ix:{C,M,CI,MI,DI,OI,M3,T,IMP,KMR,LIT,DUR,TRM,IMPRO}};
  }
  function netaView(f){
    const R=_reparto(f);if(!R)return null;
    const {A,rows,cost,ix}=R,{CI,OI,IMP,TRM}=ix;
    const blank=k=>({key:k,viajes:0,ingreso:0,coste:0,medido:0});
    const add=(x,r)=>{x.viajes++;x.ingreso+=r[IMP]||0;x.coste+=cost(r);if(r[TRM]<=1||R.sub(r))x.medido+=r[IMP]||0;};   // medido/repartido (localizador) o subcontratado (coste real de factura) = coste real, no estimado
    const cerrar=x=>{x.coste=Math.round(x.coste);x.ingreso=Math.round(x.ingreso);x.margen=x.ingreso-x.coste;x.margenPct=x.ingreso?x.margen/x.ingreso:null;x.fiable=x.ingreso?x.medido/x.ingreso:0;return x;};
    const grp=fn=>{const m=new Map();for(const r of rows){const k=fn(r)||'(sin asignar)';let x=m.get(k);if(!x){x=blank(k);m.set(k,x);}add(x,r);}return [...m.values()].map(cerrar).sort((a,b)=>b.ingreso-a.ingreso);};
    const tot=blank('');for(const r of rows)add(tot,r);cerrar(tot);
    return {tot,byClient:grp(r=>A.cli[r[CI]]),byZona:grp(r=>A.prov[r[OI]]),coef:R.coef,mesesEstimados:R.mesesEstimados,income:Math.round(R.income),gasto:Math.round(R.gasto),margenLibroPct:R.margenLibroPct,scale:R.scale,from:R.from,to:R.to};
  }
  // Margen NETO por VIAJE individual (tabla paginada en la pestaña «Margen por viaje»): mismo reparto, sin agregar.
  function netaTrips(f){
    const R=_reparto(f);if(!R)return null;
    const {A,rows,cost,desglose,dRateOf,nameOf,sub,ix}=R,{C,M,MI,DI,OI,M3,T,IMP,KMR,LIT,DUR,TRM,IMPRO}=ix;
    const TR=['medido','repartido','estimado','sin traza'];
    const hhmm=s=>s?String(s).slice(11,16):null;
    return rows.map(r=>{const d=desglose(r),ing=Math.round(r[IMP]),cst=Math.round(d.combustible+d.personal+d.flota+d.indirectos+d.aridos+d.subcontrata),alto=!sub(r)&&dRateOf(r)>1;const x={mes:A.mo[r[M]],dia:(A.dia&&A.dia[r[20]])||A.mo[r[M]],cliente:nameOf(r),ruta:A.prov[r[OI]]+' → '+A.prov[r[DI]],carga:A.pt[r[13]]||A.loc[r[6]]||'—',descarga:A.pt[r[14]]||A.loc[r[7]]||'—',mat:A.mat[r[MI]]||'—',m3:Math.round(r[M3]),t:Math.round(r[T]),km:Math.round(r[KMR]),horas:r[DUR]?+(r[DUR]/60).toFixed(1):null,ingreso:ing,coste:cst,margen:ing-cst,margenPct:ing?(ing-cst)/ing:null,fiab:(sub(r)?'subcontrata':(TR[r[TRM]]||'—'))+(alto?' ⚠':'')+(d.estimado?' (mes sin cerrar)':''),emp:A.co[r[C]],locO:A.loc[r[6]]||null,locD:A.loc[r[7]]||null,lit:(r[LIT]||0)>0?+Number(r[LIT]).toFixed(1):null,horm:!!r[12],sub:sub(r),costeEstimado:!!d.estimado};
      // desglose del coste real del viaje (mismo reparto mensual que cost(r)): sirve para el detalle desplegable
      x.desg=sub(r)?(d.aridos>0?{subcontrata:d.subcontrata,indirectos:d.indirectos,aridos:d.aridos}:{subcontrata:d.subcontrata,indirectos:d.indirectos}):{combustible:d.combustible,personal:d.personal,flota:d.flota,indirectos:d.indirectos,aridos:d.aridos};
      // triangulado v2 (índices 21..31): hora real de inicio/fin, orden del día, minutos de conducción/espera, método, confianza, chofer del tacógrafo
      if(r.length>=32){const ti=r[21]||null,tf=r[22]||null;x.tini=hhmm(ti);x.tfin=tf?hhmm(tf)+(ti&&tf.slice(0,10)!==ti.slice(0,10)?' +1':''):null;x.orden=r[23]||null;x.cond=r[24]==null?null:Math.round(r[24]);x.espera=r[25]==null?null:Math.round(r[25]);x.otros=r[26]==null?null:Math.round(r[26]);x.metodo=(A.met&&A.met[r[27]])||null;x.conf=(A.conf&&A.conf[r[28]])||null;x.chofer=(A.chot&&A.chot[r[29]])||null;x.nocturna=!!r[30];x.medido=!!r[31];x.mapaKey=(x.medido&&x.mat&&x.mat!=='—'&&x.dia)?x.mat+'_'+x.dia:null;
        if(r.length>=34){x.kmCarg=r[32]==null?null:Math.round(r[32]);x.kmVac=r[33]==null?null:Math.round(r[33]);}
        // 34: paradas y esperas del viaje [hh:mm, minutos, lugar, qué hacía]
        if(r.length>=35&&Array.isArray(r[34]))x.paradas=r[34].map(p=>({t:p[0],min:p[1],lugar:A.pt[p[2]]||'',rol:['carga','descarga','espera','fuera'][p[3]]||''}));
        // 35..63: todo el detalle del viaje (hitos, minutos por actividad, litros, fuentes, jornada, identidad)
        if(r.length>=64){x.tCarga=r[35]||null;x.tCargaFin=r[36]||null;x.tDesc=r[37]||null;x.tDescFin=r[38]||null;x.disp=r[39];x.desc=r[40];x.sinDato=r[41];x.minFuente=(A.mfu&&A.mfu[r[42]])||null;x.coherente=r[43]==null?null:!!r[43];x.transc=r[44];x.litC=r[45];x.litV=r[46];x.distOd=r[47];x.obraMin=r[48];x.viajesDia=r[49];x.motivo=(A.mot&&A.mot[r[50]])||null;x.fechaGes=(A.dia&&A.dia[r[51]])||null;x.choferGes=(A.chot&&A.chot[r[52]])||null;x.choferOk=r[53]==null?null:!!r[53];x.tipo=(A.tipo&&A.tipo[r[54]])||null;x.larga=!!r[55];x.espejo=!!r[56];x.jIni=r[57]||null;x.jFin=r[58]||null;x.kmFuente=(A.kmf&&A.kmf[r[59]])||null;x.litRaw=r[60];x.litCal=r[61];x.viaje=r[62]||null;x.cantera=r[63]||null;}
        x.kmAlb=r[8]||0;}
      return x;});
  }
  // ---- Vista REAL por dimensión (vehículo, cliente, mes, tipo, ruta): el MISMO reparto que «Margen por viaje», agregado.
  // Cada viaje real suma su ingreso facturado y su coste real (combustible por litros, personal por horas, flota por km,
  // indirectos por ingreso; subcontratado = factura real). El «material» es la compra de áridos atribuida por cliente:
  // ingreso de transporte y servicios = ingreso facturado − material. Sin contabilidad cerrada no hay coste (real=false).
  const IX={C:0,M:1,CI:2,MI:3,OI:4,DI:5,LI:6,LD:7,KM:8,M3:9,T:10,IMP:11,HORM:12,PO:13,PD:14,KMR:15,LIT:16,DUR:17,TRM:18,IMPRO:19,DIA:20};
  const plateKeyOf=s=>String(s||'').toUpperCase().replace(/[^A-Z0-9]/g,'');
  function realView(f,dim='plate'){
    if(!activity)return null;
    const A=activity,from=f.from.slice(0,7),to=f.to.slice(0,7),wanted=f.companies?.length?f.companies:['Razo','Agetrans'];
    const wc=new Set(wanted.map(w=>A.co.indexOf(w)).filter(i=>i>=0));
    let rows=A.rows.filter(r=>{const m=A.mo[r[IX.M]];return m>=from&&m<=to&&wc.has(r[IX.C]);});
    const plates=f.plates?.length?new Set(f.plates.map(plateKeyOf)):null;   // segmentador de vehículo del informe
    if(plates)rows=rows.filter(r=>plates.has(plateKeyOf(A.mat[r[IX.MI]])));
    if(!rows.length)return null;
    const R=_reparto(f);                                  // coeficientes fijos del periodo (no cambian al filtrar)
    const sub=r=>(r[IX.IMPRO]||0)>0,plateOf=r=>A.mat[r[IX.MI]]||'',cliOf=r=>A.cli[r[IX.CI]]||'(sin asignar)';
    const tipoOf=r=>{const t=r.length>=64&&A.tipo?A.tipo[r[54]]:'';return t||(r[IX.HORM]?'hormigonera':(sub(r)?'subcontratado':''));};
    const keyFns={plate:r=>plateOf(r)||'(sin matrícula)',client:cliOf,month:r=>A.mo[r[IX.M]],tipo:tipoOf,ruta:r=>A.prov[r[IX.OI]]+' → '+A.prov[r[IX.DI]],carga:r=>A.pt[r[IX.PO]]||A.loc[r[IX.LI]]||'(sin punto)',descarga:r=>A.pt[r[IX.PD]]||A.loc[r[IX.LD]]||'(sin punto)'};
    const keyOf=keyFns[dim]||keyFns.plate;
    const blank=k=>({key:k,viajes:0,ingreso:0,ingPropio:0,material:0,materialPropio:0,coste:0,combustible:0,personal:0,flota:0,indirectos:0,subcontrata:0,km:0,kmMed:0,horas:0,litros:0,kmLit:0,m3:0,t:0,medido:0,subViajes:0,subIng:0,viajesMed:0,kmCarg:0,kmVac:0,cond:0,espera:0,costeEstimado:0,dias:new Set(),mats:new Set(),clis:new Set(),tipos:new Map()});
    const add=(x,r)=>{
      const ing=r[IX.IMP]||0,es=sub(r);x.viajes++;x.ingreso+=ing;x.m3+=r[IX.M3]||0;x.t+=r[IX.T]||0;x.dias.add(r[IX.DIA]);x.mats.add(plateOf(r));x.clis.add(cliOf(r));
      const tp=tipoOf(r);x.tipos.set(tp,(x.tipos.get(tp)||0)+1);
      if(es){x.subViajes++;x.subIng+=ing;}
      else{x.ingPropio+=ing;x.km+=r[IX.KMR]||0;x.horas+=(r[IX.DUR]||0)/60;x.litros+=r[IX.LIT]||0;if((r[IX.LIT]||0)>0)x.kmLit+=r[IX.KMR]||0;if(r[IX.TRM]<=1)x.kmMed+=r[IX.KMR]||0;}
      if(r[IX.TRM]<=1||es)x.medido+=ing;
      if(r.length>=32&&r[31]){x.viajesMed++;if(r[24]!=null)x.cond+=r[24];if(r[25]!=null)x.espera+=r[25];}
      if(r.length>=34){if(r[32]!=null)x.kmCarg+=r[32];if(r[33]!=null)x.kmVac+=r[33];}
      if(R){
        const d=R.desglose(r);
        x.combustible+=d.combustible;x.personal+=d.personal;x.flota+=d.flota;x.indirectos+=d.indirectos;x.material+=d.aridos;if(!es)x.materialPropio+=d.aridos;x.subcontrata+=d.subcontrata;
        x.coste+=d.combustible+d.personal+d.flota+d.indirectos+d.aridos+d.subcontrata;if(d.estimado)x.costeEstimado++;
      }
    };
    const cerrar=x=>{
      x.dias=x.dias.size;x.matriculas=x.mats.size;x.clientes=x.clis.size;delete x.mats;delete x.clis;
      x.tipo=[...x.tipos.entries()].sort((a,b)=>b[1]-a[1])[0]?.[0]||'';x.tipos=Object.fromEntries(x.tipos);
      x.ingTransporte=x.ingreso-x.material;x.propio=x.subViajes<x.viajes/2;
      x.costeTransporte=R?x.coste-x.material:null;   // coste comparable al ingreso de transporte: fuera el material (compraventa)
      x.margen=R?x.ingreso-x.coste:null;x.margenPct=R&&x.ingreso?x.margen/x.ingreso:null;x.margenTransPct=R&&x.ingTransporte?x.margen/x.ingTransporte:null;
      x.fiable=x.ingreso?x.medido/x.ingreso:0;
      const ingKmBase=x.ingPropio-x.materialPropio;   // por km y por hora: solo viajes propios (los subcontratados no llevan km ni horas nuestros)
      x.ingKm=divide(ingKmBase,x.km);x.ingHora=divide(ingKmBase,x.horas);
      x.margenKm=R?divide(ingKmBase-(x.combustible+x.personal+x.flota+x.indirectos*(x.ingreso?x.ingPropio/x.ingreso:1)),x.km):null;
      x.margenHora=R?divide(ingKmBase-(x.combustible+x.personal+x.flota+x.indirectos*(x.ingreso?x.ingPropio/x.ingreso:1)),x.horas):null;
      x.costeKm=R?divide(x.combustible+x.personal+x.flota,x.km):null;x.l100=x.kmLit>0?x.litros/x.kmLit*100:null;
      return x;};
    const agrupar=(rs,fn,porMes)=>{const m=new Map();for(const r of rs){const k=fn(r);let x=m.get(k);if(!x){x=blank(k);m.set(k,x);}add(x,r);}return [...m.values()].map(cerrar).sort((a,b)=>porMes?(a.key<b.key?-1:1):b.ingreso-a.ingreso);};
    const groups=agrupar(rows,keyOf,dim==='month');
    const tot=blank('TOTAL');for(const r of rows)add(tot,r);cerrar(tot);
    // detalle de un grupo: sus viajes reagrupados por mes, cliente, matrícula, ruta, tipo y lugares de carga/descarga
    const detail=key=>{const rs=rows.filter(r=>keyOf(r)===key);return {byMonth:agrupar(rs,keyFns.month,true),byClient:agrupar(rs,keyFns.client),byPlate:agrupar(rs,keyFns.plate),byRuta:agrupar(rs,keyFns.ruta),byTipo:agrupar(rs,keyFns.tipo),byCarga:agrupar(rs,keyFns.carga),byDescarga:agrupar(rs,keyFns.descarga),viajes:rs.length};};
    return {dim,groups,tot,detail,real:!!R,coef:R?R.coef:null,mesesEstimados:R?R.mesesEstimados:[],scale:R?R.scale:null,income:R?R.income:null,gasto:R?R.gasto:null,margenLibroPct:R?R.margenLibroPct:null,from,to};
  }
  // Localizador por matrícula en el periodo (todos los días, con y sin viaje): km, días activos, litros del sensor.
  function telemetryByPlate(f){
    const out=new Map();if(!telemetry)return out;
    for(const r of telemetry.rows){if(r.date<f.from||r.date>f.to)continue;let x=out.get(r.plate);if(!x){x={plate:r.plate,dias:0,activos:0,km:0,litros:0,kmFuel:0,diasFuel:0,desde:r.date,hasta:r.date,clase:telemetry.clases?.[r.plate]||''};out.set(r.plate,x);}
      x.dias++;if(r.km>=30)x.activos++;x.km+=r.km;if(r.litres>0){x.litros+=r.litres;x.kmFuel+=r.km;x.diasFuel++;}if(r.date<x.desde)x.desde=r.date;if(r.date>x.hasta)x.hasta=r.date;}
    for(const x of out.values())x.l100=x.kmFuel>0?x.litros/x.kmFuel*100:null;
    return out;
  }
  // Tarjeta Solred por matrícula en los meses del periodo: litros y euros (sin IVA) de gasóleo. Solo los meses con fichero.
  function solredByPlate(f){
    const out=new Map(),sol=data.fuel?.solred;if(!sol)return out;
    const from=f.from.slice(0,7),to=f.to.slice(0,7);
    for(const r of sol.rows){if(r.kind!=='gasoleo'||!r.plate||r.month<from||r.month>to)continue;let x=out.get(r.plate);if(!x){x={plate:r.plate,litros:0,base:0,n:0,meses:new Set()};out.set(r.plate,x);}x.litros+=r.litros||0;x.base+=r.base||0;x.n+=r.n||0;x.meses.add(r.month);}
    for(const x of out.values())x.meses=[...x.meses].sort();
    return out;
  }
  // Partes de Access por matrícula en el periodo (DECLARADO, solo como referencia).
  function partsByPlate(f){
    const out=new Map();
    for(const p of data.parts){if(p.date<f.from||p.date>f.to||!p.plate)continue;let x=out.get(p.plate);if(!x){x={plate:p.plate,partes:0,km:0,horas:0,litros:0,coste:0,owner:p.owner,category:p.category};out.set(p.plate,x);}x.partes++;x.km+=p.km;x.horas+=p.hours;x.litros+=p.litres;x.coste+=p.stored;}
    return out;
  }
  // Puntos GEO del periodo elegido (para el MAPA): agrega los viajes filtrados por su punto de origen/destino y une la
  // coordenada real del localizador (paradas GPS de la flota). Respeta periodo y sociedad.
  function zonasGeo(f){
    if(!activity||!activity.coords)return null;
    const A=activity,C=0,M=1,M3=9,T=10,IMP=11,PO=13,PD=14;
    const from=f.from.slice(0,7),to=f.to.slice(0,7),wanted=f.companies?.length?f.companies:['Razo','Agetrans'];
    const wc=new Set(wanted.map(w=>A.co.indexOf(w)).filter(i=>i>=0));
    const rows=A.rows.filter(r=>{const m=A.mo[r[M]];return m>=from&&m<=to&&wc.has(r[C]);});
    const pts=new Map();
    const bump=(nameIx,rol,r)=>{const name=A.pt[nameIx];const c=name&&A.coords[name];if(!c)return;let p=pts.get(name);if(!p){p={name,lat:c[0],lon:c[1],loc:c[2],prov:c[3],viajes:0,t:0,m3:0,ing:0,orig:0,dest:0};pts.set(name,p);}p.viajes++;p.t+=r[T]||0;p.m3+=r[M3]||0;p.ing+=r[IMP]||0;p[rol]++;};
    for(const r of rows){bump(r[PO],'orig',r);bump(r[PD],'dest',r);}
    return {puntos:[...pts.values()].map(p=>({...p,t:Math.round(p.t),m3:Math.round(p.m3),ing:Math.round(p.ing)})).sort((a,b)=>b.viajes-a.viajes)};
  }
  return {run,select,aggregate,group,weights,factor,pool,imputed,payrollMonths,reconcilePersonnel,personnelByTramo,reconcileFuel,ledgerView,bridge,societyOf,plateSociety,ownFleet,telemetryView,activityView,marginView,netaView,netaTrips,zonasGeo,realView,telemetryByPlate,solredByPlate,partsByPlate};
}
