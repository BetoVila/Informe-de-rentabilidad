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
  const monthList=(from,to)=>{const out=[];let [y,m]=from.slice(0,7).split('-').map(Number);const [ye,me]=to.slice(0,7).split('-').map(Number);while(y<ye||(y===ye&&m<=me)){out.push(y+'-'+String(m).padStart(2,'0'));if(++m>12){m=1;y++;}}return out;};
  const monthEnd=(month)=>{const [y,m]=month.split('-').map(Number);return month+'-'+String(new Date(Date.UTC(y,m,0)).getUTCDate()).padStart(2,'0');};
  function ledgerView(f){
    if(!ledger)return null;
    const names=ledger.sociedades,wanted=f.companies?.length?f.companies:Object.values(names),closed=ledger.meta.lastClosed;
    const all=monthList(f.from,f.to),months=all.filter(m=>!closed||m<=closed),excludedMonths=all.filter(m=>closed&&m>closed);
    const set=new Set(months),rows=ledger.rows.filter(r=>set.has(r.month)&&wanted.includes(names[r.company]));
    const income=rows.filter(r=>r.kind==='i').reduce((s,r)=>s+r.amount,0),expenses=rows.filter(r=>r.kind==='g').reduce((s,r)=>s+r.amount,0);
    const cat=(kind)=>ledger.categories[kind==='g'?'gastos':'ingresos'].map(c=>({...c,amount:rows.filter(r=>r.kind===kind&&r.cat===c.id).reduce((s,r)=>s+r.amount,0)})).filter(c=>Math.abs(c.amount)>.5).sort((a,b)=>b.amount-a.amount);
    const byMonth=months.map(m=>{const rs=rows.filter(r=>r.month===m),i=rs.filter(r=>r.kind==='i').reduce((s,r)=>s+r.amount,0),g=rs.filter(r=>r.kind==='g').reduce((s,r)=>s+r.amount,0);return {key:m,income:i,expenses:g,result:i-g,marginPct:divide(i-g,i)};});
    const byCompany=Object.values(names).filter(n=>wanted.includes(n)).map(n=>{const rs=rows.filter(r=>names[r.company]===n),i=rs.filter(r=>r.kind==='i').reduce((s,r)=>s+r.amount,0),g=rs.filter(r=>r.kind==='g').reduce((s,r)=>s+r.amount,0);return {key:n,income:i,expenses:g,result:i-g,marginPct:divide(i-g,i)};});
    const partial=months.length>0&&(f.from.slice(0,7)===months[0]&&f.from.slice(8)!=='01'||(f.to.slice(0,7)===months[months.length-1]&&f.to<monthEnd(months[months.length-1])));
    return {income,expenses,result:income-expenses,marginPct:divide(income-expenses,income),months,excludedMonths,partial,expenseCategories:cat('g'),incomeCategories:cat('i'),byMonth,byCompany,lastClosed:closed};
  }
  // Puente: lo que dice la contabilidad frente a lo que captan los partes de Access, por concepto (mismos meses y sociedades).
  function bridge(f){
    const view=ledgerView(f);if(!view)return null;
    const names=ledger.sociedades,wanted=f.companies?.length?f.companies:Object.values(names),set=new Set(view.months);
    const rows=ledger.rows.filter(r=>r.kind==='g'&&set.has(r.month)&&wanted.includes(names[r.company]));
    const ps=data.parts.filter(p=>set.has(p.date.slice(0,7))&&wanted.includes(societyOf(p.owner)));
    const groups=ledger.puente.map(g=>{
      const led=rows.filter(r=>g.cats.includes(r.cat)).reduce((s,r)=>s+r.amount,0),parts=ps.reduce((s,p)=>s+g.partes.reduce((a,k)=>a+(p[k]||0),0),0);
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
    const withFuel=active.filter(r=>r.litres>0),litres=sum(withFuel,'litres'),kmFuel=sum(withFuel,'km'),kmWith=sum(withPart,'km');
    const partKmSame=withPart.reduce((s,r)=>s+partKm.get(r.plate+'|'+r.date),0);
    const byPlate=new Map();
    for(const r of active){
      const x=byPlate.get(r.plate)||{key:r.plate,label:r.plate,activeDays:0,daysWithoutPart:0,km:0,kmWithoutPart:0,litres:0,kmFuel:0};
      x.activeDays++;x.km+=r.km;if(!has(r)){x.daysWithoutPart++;x.kmWithoutPart+=r.km;}if(r.litres>0){x.litres+=r.litres;x.kmFuel+=r.km;}
      byPlate.set(r.plate,x);
    }
    const plateRows=[...byPlate.values()].map(x=>({...x,consumption:divide(x.litres*100,x.kmFuel),pctWithoutPart:divide(x.daysWithoutPart,x.activeDays)})).sort((a,b)=>b.kmWithoutPart-a.kmWithoutPart);
    return {from,to,km:sum(active,'km'),litres,kmFuel,consumption:divide(litres*100,kmFuel),activeDays:active.length,daysWithoutPart:without.length,pctWithoutPart:divide(without.length,active.length),kmWithoutPart:sum(without,'km'),kmWithPart:kmWith,ratio:divide(partKmSame,kmWith),plates:byPlate.size,plateRows};
  }
  return {run,select,aggregate,group,weights,factor,pool,imputed,payrollMonths,reconcilePersonnel,reconcileFuel,ledgerView,bridge,societyOf,telemetryView};
}
