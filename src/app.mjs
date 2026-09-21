const $=id=>document.getElementById(id);
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const nf=(v,n=0)=>v==null||!Number.isFinite(v)?'—':new Intl.NumberFormat('es-ES',{minimumFractionDigits:n,maximumFractionDigits:n}).format(v);
const eur=v=>v==null?'—':nf(v,2)+' €';
const pct=v=>v==null?'—':nf(v*100,1)+' %';
const short=v=>new Intl.NumberFormat('es-ES',{notation:'compact',maximumFractionDigits:1}).format(v);
const date=d=>d?new Intl.DateTimeFormat('es-ES',{day:'2-digit',month:'short',year:'numeric',timeZone:'Europe/Madrid'}).format(new Date(d.length===10?d+'T12:00:00Z':d)):'—';
const moneyCol=(label,key)=>({label,key,format:eur,numeric:true});
const numberCol=(label,key,n=0)=>({label,key,format:v=>nf(v,n),numeric:true});
const percentCol=(label,key)=>({label,key,format:pct,numeric:true});
let D,M,state,selection,current,baseline=null,tableState={page:0,query:'',sort:'',asc:false},tableDefinition;
const slicerDefs=[['plates','Vehículo','plate','plateLabel'],['clients','Cliente','clientId','client'],['categories','Tipo de vehículo','category','category'],['loads','Carga','load','load'],['concepts','Concepto de facturación','concept','concept']];
let slicerOptions={},ledgerCtx={},zoneMode='salida';
const hasFilters=()=>Boolean(state.plates.length||state.clients.length||state.categories.length||state.loads.length||state.concepts.length);
const monthName=m=>new Intl.DateTimeFormat('es',{month:'long',year:'numeric',timeZone:'UTC'}).format(new Date(m+'-01T12:00:00Z'));
const monthShort=m=>new Intl.DateTimeFormat('es',{month:'short',year:'2-digit',timeZone:'UTC'}).format(new Date(m+'-01T12:00:00Z'));
const monthRange=months=>!months.length?'':months.length===1?monthName(months[0]):monthName(months[0])+' – '+monthName(months[months.length-1]);
const monthEndOf=m=>{const [y,mm]=m.split('-').map(Number);return m+'-'+String(new Date(Date.UTC(y,mm,0)).getUTCDate()).padStart(2,'0');};
const costLabels={real:'con nómina real',stored:'declarado en Access',recalculated:'recalculado'};
const costField=()=>({real:'real',stored:'stored',recalculated:'recalculated'}[state.costMode]||'stored');

function makeSlicers(){
 for(const [id,,field,label] of slicerDefs){
   const map=new Map();
   for(const r of D.lines){const key=r[field]||UNASSIGNED;map.set(key,id==='clients'?`${r[label]} · ${r.company}`:r[label]||UNASSIGNED);}
   if(['plates','categories'].includes(id))for(const r of D.parts)map.set(r[field]||UNASSIGNED,r[label]||UNASSIGNED);
   if(!['plates','categories'].includes(id))map.set(UNASSIGNED,UNASSIGNED);
   slicerOptions[id]=[...map].sort((a,b)=>a[1].localeCompare(b[1],'es'));
 }
 $('slicers').innerHTML=slicerDefs.map(([id,title])=>`<details class="slicer" id="slice-${id}"><summary>${title}<small id="count-${id}">Todos</small></summary><input type="search" data-search-slicer="${id}" aria-label="Buscar ${title.toLowerCase()}" placeholder="Buscar…"><div class="mini-actions"><span>${slicerOptions[id].length} opciones</span><button class="textbtn" data-clear="${id}">Quitar selección</button></div><div class="options" id="options-${id}">${slicerOptions[id].map(([v,label])=>`<label><input type="checkbox" data-slicer="${id}" value="${esc(v)}"><span>${esc(label)}</span></label>`).join('')}</div></details>`).join('');
}
function syncFilters(){
 for(const [id,title] of slicerDefs){$('count-'+id).textContent=state[id].length?`${state[id].length} seleccionados`:'Todos';document.querySelectorAll(`[data-slicer="${id}"]`).forEach(el=>el.checked=state[id].includes(el.value));}
 document.querySelectorAll('[data-company]').forEach(b=>{const on=state.companies[0]===(b.dataset.company||undefined);b.classList.toggle('selected',on);b.setAttribute('aria-pressed',on);});
 $('active').innerHTML=slicerDefs.flatMap(([id,title])=>state[id].map(v=>`<button class="chip" data-remove="${id}" data-value="${esc(v)}" title="Quitar filtro">${title}: ${esc(slicerOptions[id].find(o=>o[0]===v)?.[1]||v)} ×</button>`)).join('');
}
function comparisonRange(){
 const mode=$('compare').value;
 if(mode==='none')return null;
 let from,to;
 if(mode==='custom'){from=$('compareFrom').value;to=$('compareTo').value;}
 else if(mode==='year'){
   const prior=d=>{const x=new Date(d+'T12:00:00Z'),month=x.getUTCMonth();x.setUTCFullYear(x.getUTCFullYear()-1);if(x.getUTCMonth()!==month)x.setUTCDate(0);return x.toISOString().slice(0,10);};from=prior(state.from);to=prior(state.to);
 }else{const a=new Date(state.from+'T12:00:00Z'),b=new Date(state.to+'T12:00:00Z'),days=Math.round((b-a)/864e5)+1;to=new Date(+a-864e5).toISOString().slice(0,10);from=new Date(+a-days*864e5).toISOString().slice(0,10);}
 return {from,to,valid:from>=D.metadata.from&&to<=D.metadata.to&&from<=to};
}
function update(){
 state.from=$('from').value;state.to=$('to').value;state.dateBasis=$('dateBasis').value;state.costMode=$('costMode').value;state.consolidado=$('billing').value==='consolidada';
 syncFilters();
 if(!state.from||!state.to||state.from>state.to||state.from<D.metadata.from||state.to>D.metadata.to){$('message').innerHTML=`<div class="alert error">Seleccione un periodo válido dentro de ${date(D.metadata.from)}–${date(D.metadata.to)}.</div>`;$('cards').innerHTML='';$('content').innerHTML='';return;}
 selection=M.select(state);current=M.group(selection,state,'plate');
 const range=comparisonRange();baseline=range?.valid?M.run({...state,...range}).totals:null;
 const unassignedParts=selection.physicalParts.filter(p=>!M.weights.has(p.date.slice(0,7)+'|'+p.plate));
 const excluded=sum(unassignedParts,costField());
 const t=current.totals;
 const lv=D.ledger?M.ledgerView(state):null,br=lv?M.bridge(state):null,lvBase=range?.valid&&lv?M.ledgerView({...state,...range}):null,ledgerOn=Boolean(lv&&lv.months.length&&!hasFilters());
 ledgerCtx={lv,br,lvBase,ledgerOn,range};
 const notices=[];
 if(lv&&ledgerOn){
  if(lv.excludedMonths.length)notices.push('La contabilidad de '+monthRange(lv.excludedMonths)+' todavía no está cerrada y no se incluye: el resultado cubre '+monthRange(lv.months)+'.');
  if(lv.partial)notices.push('La contabilidad se toma por meses completos ('+monthRange(lv.months)+'); las fechas elegidas cortan meses.');
 }
 if(lv&&!ledgerOn&&hasFilters()&&br)notices.push('Con filtros de vehículo, cliente, carga o concepto solo se ve el coste que los partes imputan a vehículos: NO incluye subcontratación, compra de áridos ni gastos generales ('+eur(br.missing)+' en el periodo). No es el resultado real de esa selección.');
 if(lv&&!lv.months.length)notices.push('No hay meses de contabilidad cerrados en este periodo; se muestra solo el coste de los partes de Access, que no es el gasto real.');
 if(!D.ledger)notices.push('Sin contabilidad en esta lectura: el gasto que se ve es solo el de los partes de Access y no es el real.');
 if(!ledgerOn){
  if(state.costMode==='real'&&D.payroll&&state.to.slice(0,7)>[...M.payrollMonths].sort().pop())notices.push('La nómina real llega hasta '+monthName([...M.payrollMonths].sort().pop())+'; los meses posteriores usan el coste de conductor declarado.');
  if(state.companies.length&&excluded>0)notices.push(`${eur(excluded)} de costes del ámbito de vehículos y fechas quedan sin empresa y no están incluidos en esta sociedad.`);
  else if(!state.clients.length&&!state.loads.length&&!state.concepts.length&&excluded>0)notices.push(`${eur(excluded)} de coste sin asignar incluidos en Ambas.`);
  if(t.uncoveredRevenue>0.01)notices.push(`${eur(t.uncoveredRevenue)} de ingreso no tiene un parte enlazado en el mismo mes.`);
  if(incompleteMonth(D.metadata.to)&&state.to>=D.metadata.to.slice(0,7)+'-01')notices.push('El último mes está incompleto: corte hasta '+date(D.metadata.to)+'.');
 }
 if(range&&!range.valid)notices.push('La comparación queda fuera del periodo disponible; no se trata como cero.');
 if(D.metadata.refresh?.mode!=='scheduled')notices.push('Actualización nocturna pendiente de activar. Este es el último corte disponible.');
 else if(Date.now()-new Date(D.metadata.generatedAt)>48*3600e3)notices.push('La última lectura tiene más de 48 horas. Consulte Estado de actualización; los datos no son actuales.');
 $('message').innerHTML=notices.length?`<div class="alert">${notices.map(esc).join('<br>')} <button data-tab="audit">Ver conciliación</button></div>`:'';
 const compareHint=baseline?` · comparación ${date(range.from)}–${date(range.to)}`:'';
 const priorLabel=range?.valid?({year:'Año anterior',previous:'Periodo anterior',custom:'Comparación'}[$('compare').value]||'Comparación'):'';
 ledgerCtx.priorLabel=priorLabel;
 const cmp=(value,prior,goodUp=true,fmt=eur)=>compareHtml(value,prior,goodUp,fmt,priorLabel);
 const kcard=(label,value,hint,extra='',primary=false)=>`<article class="card ${primary?'primary':''}"><span class="label">${label}</span><div class="value">${value}</div><div class="hint">${hint}</div>${extra}</article>`;
 if(ledgerOn){
  $('cards').innerHTML=[
   kcard('Ingresos contables'+(lv.consolidado?' (consolidados)':''),eur(lv.income),'Contabilidad, '+monthRange(lv.months)+'. Facturas GesRuta de esos mismos meses: '+eur(M.run({...state,from:lv.months[0]+'-01',to:monthEndOf(lv.months[lv.months.length-1])}).totals.revenue)+'.'+(lv.consolidado?' Consolidado: excluidos '+eur(lv.intragrupo.income)+' de facturación intragrupo Razo–Agetrans.':''),cmp(lv.income,lvBase?.income),true),
   kcard('Gastos contables'+(lv.consolidado?' (consolidados)':''),eur(lv.expenses),'Todo el gasto real. Los partes de Access solo captan el '+pct(br.coverage)+' ('+eur(br.totalParts)+').'+(lv.consolidado?' Consolidado: excluidos '+eur(lv.intragrupo.expense)+' de subcontratación intragrupo.':''),cmp(lv.expenses,lvBase?.expenses,false)),
   kcard('Resultado contable',eur(lv.result),'Margen '+pct(lv.marginPct)+' sobre ingresos'+(lv.consolidado?' del grupo (sin intragrupo)':'')+'. Es el resultado de la contabilidad, no un cálculo de los partes.',cmp(lv.result,lvBase?.result)),
   kcard('Gasto que no llega a los partes',eur(br.missing),'Subcontratación, compra de áridos, generales… existen en la contabilidad y no en ningún parte de vehículo.',cmp(br.missing,lvBase?M.bridge({...state,...range}).missing:null,false))].join('');
 }else{
  $('cards').innerHTML=[
   card('Ingresos sin IVA (facturas GesRuta)',eur(t.revenue),'Base de facturación · '+(state.dateBasis==='invoice'?'fecha de factura':'fecha de línea'),'revenue',true),
   card('Coste imputable a vehículos ('+costLabels[state.costMode]+')',eur(t.cost),'Solo lo que los partes imputan. No incluye subcontratación, compra de áridos ni gastos generales.','cost'),
   card('Saldo aparente',eur(t.balance),'Ingresos − coste imputable. NO es el resultado real: faltan gastos.','balance'),
   card('Cobertura de ingresos',pct(t.coverage),'Ingreso con parte del mismo mes y matrícula; no certifica que estén todos los gastos.','coverage')].join('');
 }
 $('footer').textContent=`${date(state.from)}–${date(state.to)}${compareHint} · ${nf(selection.lines.length)} líneas incluidas · ${nf(t.parts)} partes de origen · Costes según fecha del parte. Lectura de Access: ${date(D.metadata.accessReadAt)}; GesRuta: ${date(D.metadata.gesrutaReadAt)}.`;
 renderContent();
}
function compareHtml(value,prior,goodUp=true,fmt=eur,label='Comparación'){
 if(prior==null||!Number.isFinite(prior)||!Number.isFinite(value))return '';
 const d=value-prior,rel=prior?d/Math.abs(prior):null,tone=Math.abs(d)<.005?'neutral':(d>0)===goodUp?'good':'bad',isPct=fmt===pct;
 return `<div class="compare"><span class="compare-prior">${label}: ${fmt(prior)}</span><span class="compare-delta ${tone}">${d>=0?'▲ +':'▼ −'}${isPct?nf(Math.abs(d)*100,1)+' puntos':eur(Math.abs(d))}${rel!=null&&!isPct?' ('+(d>=0?'+':'−')+nf(Math.abs(rel)*100,1)+' %)':''}</span></div>`;
}
function card(label,value,hint,key,primary=false){
 const delta=baseline?compareHtml(current.totals[key],baseline[key],key!=='cost',key==='coverage'?pct:eur,ledgerCtx.priorLabel||'Comparación'):'';
 return `<article class="card ${primary?'primary':''}"><span class="label">${label}</span><div class="value">${value}</div><div class="hint">${hint}</div>${delta}</article>`;
}
// Ratios de rentabilidad con la contabilidad real (meses cerrados). Por km y por hora hacen falta km y horas medidos de toda la flota.
function ratiosPanel(){
 const {lv}=ledgerCtx;if(!lv||!(lv.expenses>0))return '';
 const kpi=[['Ingresos por € de gasto',nf(lv.income/lv.expenses,3),'Cada € gastado devuelve esto en ingresos (contabilidad)'],['Beneficio por € de gasto',nf(lv.result/lv.expenses,3),'Resultado ÷ gastos (contabilidad)'],
  ['Ingresos por km medido','pendiente','Necesita los km medidos de toda la flota y de todo el periodo'],['Beneficio por hora trabajada','pendiente','Necesita las horas medidas (Movertis y Locatel); hoy solo hay desde el 20/08']];
 return panel('Ratios de rentabilidad','Ingresos y beneficio por € gastado, por km y por hora, y por persona (pestaña Personal). Por cliente y por vehículo están en sus pestañas.',`<div class="kpi-grid" style="grid-template-columns:repeat(4,1fr)">${kpi.map(([l,x,h])=>`<div class="smallkpi ${x==='pendiente'?'soft':''}"><span class="label">${l}</span><span class="value">${x}</span><small>${h}</small></div>`).join('')}</div>`);
}
function telemetryPanel(){
 if(!D.telemetry)return '';
 const v=M.telemetryView(state),m=D.telemetry.meta;
 if(!v)return `<section class="panel"><h2>Medido por el camión (Movertis)</h2><p class="sub">Km y litros medidos por el propio camión.</p><div class="info">No hay días de Movertis en el periodo elegido: el ERP empezó a bajarlos el ${date(m.desde)} y llegan hasta el ${date(m.hasta)}. El histórico anterior aún no está cargado.</div></section>`;
 return `<section class="panel"><h2>Medido por el camión (Movertis)</h2><p class="sub">Km y litros medidos por el propio camión, del ${date(v.from)} al ${date(v.to)}. Solo días con lectura fiable: un día sin lectura no cuenta como cero. El ERP empezó a bajarlos el ${date(m.desde)}; el histórico anterior aún no está cargado.</p><div class="kpi-grid">${[
  ['Km medidos',nf(v.km),nf(v.plates)+' camiones activos'],['Camiones con sensor de consumo',nf(v.sensorInv.conSensor)+' de '+nf(v.sensorInv.motor)+' con motor',v.sensorInv.sinSensor?('sin sensor: '+v.sensorInv.sinSensorPlates.join(', ')+(v.sensorInv.remolques?'. '+nf(v.sensorInv.remolques)+' remolques no cuentan':'')):(v.sensorInv.remolques?nf(v.sensorInv.remolques)+' remolques no gastan gasoil':'todos lo llevan')],['Litros medidos',nf(v.litres),'Solo los '+nf(v.sensorInv.conSensor)+' camiones con sensor'],['Consumo medido',nf(v.consumption,1)+' l/100 km','Solo camiones con sensor; el resto no mide litros'],['Días-camión activos',nf(v.activeDays),'Circula 30 km o más ese día'],['Días activos sin parte',nf(v.daysWithoutPart)+' ('+pct(v.pctWithoutPart)+')','El camión circuló y no hay parte de Access'],['Km del parte / km medidos',nf(v.ratio,2),'En los días con parte (1 = coinciden)']
 ].map(([l,x,h])=>`<div class="smallkpi"><span class="label">${l}</span><span class="value">${x}</span><small>${h}</small></div>`).join('')}</div></section>`;
}
function telemetryAuditPanel(){
 if(!D.telemetry)return '';
 const v=M.telemetryView(state);if(!v)return '';
 const rows=v.plateRows.slice(0,15).map(r=>({label:r.label,activeDays:r.activeDays,daysWithoutPart:r.daysWithoutPart,pct:r.pctWithoutPart,km:r.km,kmWithoutPart:r.kmWithoutPart,consumption:r.consumption}));
 return panel('Localizador frente a partes de Access',`Movertis, del ${date(v.from)} al ${date(v.to)}.`,`<div class="warn"><strong>En el ${pct(v.pctWithoutPart)} de los días en que un camión circuló no hay parte de Access</strong> (${nf(v.daysWithoutPart)} de ${nf(v.activeDays)} días-camión, ${nf(v.kmWithoutPart)} km). Cuando el parte existe, su kilometraje coincide con el medido (cociente ${nf(v.ratio,2)}). Por eso el coste de los partes queda corto y por eso el consumo declarado no sirve.</div>`+simpleTable([{label:'Matrícula',key:'label'},{label:'Días activos',key:'activeDays',numeric:true,format:v=>nf(v)},{label:'Sin parte',key:'daysWithoutPart',numeric:true,format:v=>nf(v)},{label:'% sin parte',key:'pct',numeric:true,format:dash(pct)},{label:'Km medidos',key:'km',numeric:true,format:v=>nf(v)},{label:'Km sin parte',key:'kmWithoutPart',numeric:true,format:v=>nf(v)},{label:'Consumo medido (l/100 km)',key:'consumption',numeric:true,format:dash(v=>nf(v,1))}],rows)+`<p class="sub" style="margin-top:12px">Primeros 15 camiones por kilómetros sin parte. Consumo medido: solo camiones con sensor de combustible y lectura fiable.</p>`);
}
function sensorDetailPanel(){
 if(!D.telemetry)return '';
 const v=M.telemetryView(state);if(!v||!v.sensorInv||!v.sensorInv.rows.length)return '';
 const s=v.sensorInv;
 const rows=s.rows.map(r=>({label:r.label,clase:r.clase||'(sin tipo)',km:r.km,sensor:r.sensor?'Sí':'No',litres:r.sensor?r.litres:null,consumption:r.consumption}));
 const cols=[{label:'Matrícula',key:'label'},{label:'Tipo',key:'clase'},{label:'Km medidos',key:'km',numeric:true,format:x=>nf(x)},{label:'Sensor de consumo',key:'sensor',tone:r=>r.sensor==='No'?'neg':''},{label:'Litros medidos',key:'litres',numeric:true,format:dash(x=>nf(x))},{label:'Consumo (l/100 km)',key:'consumption',numeric:true,format:dash(x=>nf(x,1))}];
 const sub=`De los <b>${nf(s.motor)}</b> camiones con motor que Movertis mide (${date(v.from)}–${date(v.to)}), <b>${nf(s.conSensor)}</b> tienen sensor de consumo y <b>${nf(s.sinSensor)}</b> no (solo dan km). Los <b>${nf(s.remolques)}</b> remolques no cuentan (no gastan gasoil).${s.otros?' '+nf(s.otros)+' sin tipo asignado en el ERP.':''} El consumo del informe sale solo de los que tienen sensor.`;
 return panel('Qué camiones tienen sensor de consumo',sub,simpleTable(cols,rows));
}
function metrics(){const t=current.totals;return telemetryPanel()+`<section class="panel"><h2>Actividad declarada en los partes</h2><p class="sub">Lo que rellena quien registra el parte de Access: no es una medición ni está completo. Compárelo con lo medido por el camión (Movertis) y con la contabilidad (pestaña Conciliación). Cuando hay filtros comerciales, los km, horas y repostajes se reparten con el coste.</p><div class="kpi-grid">${[
 ['Viajes GesRuta',nf(t.trips),'Referencias de viaje distintas'],['Albaranes GesRuta',nf(t.deliveries),'No se cuentan como viajes'],['Viajes Access',nf(t.tripsAccess,1),'Contador de los partes · prorrateado'],['Km declarados',nf(t.km),'Partes de Access, sin los de más de 1.500 km'],['Horas declaradas',nf(t.hours,1),'Pueden ser aproximadas'],['Litros declarados',nf(t.litres,1),'Gasóleo · partes de Access'],['Consumo declarado',nf(t.consumption,2)+' l/100 km','NO es real: ver Conciliación','soft'],['Coste imputable por km',eur(t.costKm),'Solo lo que imputan los partes / km declarados','soft'],['Coste imputable por hora',eur(t.costHour),'Solo lo que imputan los partes / horas','soft'],['Km vacíos declarados',pct(t.emptyPct),'Vacíos / (cargados + vacíos)'],['Metros cúbicos',nf(t.m3,1),'Declarados en partes'],['Toneladas',nf(t.tonnes,1),'Declaradas en partes'],['Facturas',nf(t.invoices),'Facturas distintas en selección'],['Partes equivalentes',nf(t.partEquivalents,2),'Suma de cuotas asignadas'],['Saldo aparente / ingresos',pct(t.marginPct),'NO es el margen real: faltan gastos','soft']
 ].map(([l,v,h,c])=>`<div class="smallkpi ${c||''}"><span class="label">${l}</span><span class="value">${v}</span><small>${h}</small></div>`).join('')}</div></section>`;}
function trendChart(rows){
 const monthMap=new Map(rows.map(r=>[r.key,r]));
 let month=state.from.slice(0,7);const months=[];while(month<=state.to.slice(0,7)&&months.length<36){months.push(monthMap.get(month)||{key:month,revenue:0,cost:0});const d=new Date(month+'-01T12:00:00Z');d.setUTCMonth(d.getUTCMonth()+1);month=d.toISOString().slice(0,7);}
 const w=760,h=265,left=60,right=15,top=15,bottom=40,inner=h-top-bottom,max=Math.max(1,...months.flatMap(r=>[r.revenue,r.cost])),min=Math.min(0,...months.flatMap(r=>[r.revenue,r.cost])),range=max-min,y=v=>top+(max-v)/range*inner,step=(w-left-right)/Math.max(1,months.length),bw=Math.min(24,step*.28);
 const grid=Array.from({length:5},(_,i)=>{const v=min+(max-min)*i/4;return `<line x1="${left}" x2="${w-right}" y1="${y(v)}" y2="${y(v)}" stroke="#e6ecf4"/><text x="${left-10}" y="${y(v)+4}" text-anchor="end">${esc(short(v))}</text>`;}).join('');
 const bars=months.map((r,i)=>{const x=left+step*(i+.5);return [['revenue','#2868dd',-bw-2],['cost','#169389',2]].map(([key,color,offset])=>`<rect x="${x+offset}" y="${Math.min(y(0),y(r[key]))}" width="${bw}" height="${Math.max(.5,Math.abs(y(0)-y(r[key])))}" fill="${color}" rx="2"><title>${esc(r.key+' · '+(key==='cost'?'Coste':'Ingreso')+': '+eur(r[key]))}</title></rect>`).join('')+`<text x="${x}" y="${h-12}" text-anchor="middle">${esc(new Intl.DateTimeFormat('es',{month:'short',year:'2-digit'}).format(new Date(r.key+'-01T12:00:00Z')))}</text>`;}).join('');
 return `<svg class="chart" viewBox="0 0 ${w} ${h}" role="img" aria-label="Ingresos y costes por mes; los valores exactos aparecen en la tabla mensual">${grid}${bars}</svg>`;
}
function plChart(rows,prior){
 const w=760,h=265,left=60,right=15,top=15,bottom=40,inner=h-top-bottom,all=rows.concat(prior||[]).flatMap(r=>[r.income,r.expenses]);
 const max=Math.max(1,...all),min=Math.min(0,...all),range=max-min,y=v=>top+(max-v)/range*inner,step=(w-left-right)/Math.max(1,rows.length),bw=Math.min(24,step*.28);
 const grid=Array.from({length:5},(_,i)=>{const v=min+(max-min)*i/4;return `<line x1="${left}" x2="${w-right}" y1="${y(v)}" y2="${y(v)}" stroke="#e6ecf4"/><text x="${left-10}" y="${y(v)+4}" text-anchor="end">${esc(short(v))}</text>`;}).join('');
 const bars=rows.map((r,i)=>{const x=left+step*(i+.5);return [['income','#2C5FD6',-bw-2],['expenses','#169389',2]].map(([key,color,offset])=>`<rect x="${x+offset}" y="${Math.min(y(0),y(r[key]))}" width="${bw}" height="${Math.max(.5,Math.abs(y(0)-y(r[key])))}" fill="${color}" rx="2"><title>${esc(monthName(r.key)+' · '+(key==='expenses'?'Gastos':'Ingresos')+': '+eur(r[key]))}</title></rect>`).join('')+`<text x="${x}" y="${h-12}" text-anchor="middle">${esc(monthShort(r.key))}</text>`;}).join('');
 const line=(key,color)=>prior?.length?`<polyline points="${prior.map((r,i)=>`${left+step*(i+.5)},${y(r[key])}`).join(' ')}" fill="none" stroke="${color}" stroke-width="2" stroke-dasharray="5 4" opacity=".85"/>`+prior.map((r,i)=>`<circle cx="${left+step*(i+.5)}" cy="${y(r[key])}" r="2.6" fill="${color}"><title>${esc(monthName(r.key)+' (comparación) · '+(key==='expenses'?'Gastos':'Ingresos')+': '+eur(r[key]))}</title></circle>`).join(''):'';
 return `<svg class="chart" viewBox="0 0 ${w} ${h}" role="img" aria-label="Ingresos y gastos contables por mes; los valores exactos aparecen en la tabla mensual">${grid}${bars}${line('income','#2C5FD6')}${line('expenses','#169389')}</svg>`;
}
function bars(rows,valueKey,labelKey='label'){const max=Math.max(1,...rows.map(r=>Math.abs(r[valueKey])));return rows.map(r=>`<div class="barrow"><span class="barlabel" title="${esc(r[labelKey])}">${esc(r[labelKey])}</span><div class="bartrack"><div class="barfill" style="width:${Math.abs(r[valueKey])/max*100}%;${r[valueKey]<0?'background:#bd3747':''}"></div></div><span class="barnum">${eur(r[valueKey])}${r.note?` <small>${esc(r.note)}</small>`:''}</span></div>`).join('');}
function panel(title,sub,body){return `<section class="panel"><h2>${title}</h2><p class="sub">${sub}</p>${body}</section>`;}
function simpleTable(columns,rows){
 const cell=(c,r)=>esc(c.format?c.format(r[c.key],r):r[c.key]);
 return `<div class="tablewrap"><table><thead><tr>${columns.map(c=>`<th class="plain ${c.numeric?'num':''}">${esc(c.label)}</th>`).join('')}</tr></thead><tbody>${rows.map(r=>`<tr class="${r.total?'total':''}">${columns.map(c=>`<td class="${c.numeric?'num':''} ${(c.tone&&c.tone(r))||''}" title="${cell(c,r)}">${cell(c,r)}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`;
}
const dash=(fmt)=>(v)=>v==null?'—':fmt(v);
// Puente: gasto real de la contabilidad frente a lo que captan los partes de Access.
function intercompanyPanel(){
 const {lv}=ledgerCtx;if(!lv||!lv.intragrupo)return '';
 const ig=lv.intragrupo;if(!(ig.income>1||ig.expense>1))return '';
 const gap=ig.income-ig.expense,con=lv.consolidado;
 const razo=(ig.byCompany||[]).find(c=>c.key==='Razo'),age=(ig.byCompany||[]).find(c=>c.key==='Agetrans');
 const li=(l,v,cls='')=>`<div class="ic-row ${cls}"><span>${l}</span><b>${eur(v)}</b></div>`;
 let body='<div class="ic-grid">';
 if(razo&&razo.income>1)body+=li('Razo factura a Agetrans',razo.income);
 if(age&&age.income>1)body+=li('Agetrans factura a Razo',age.income);
 body+=li('Facturación intragrupo (ingreso)',ig.income,'sub');
 body+=li('Gasto intragrupo ya contabilizado (subcontratación)',ig.expense);
 body+=li('Sin casar por fecha de contabilización',gap,'gap');
 body+='</div>';
 body+=`<p class="ic-note">La otra sociedad todavía no ha contabilizado como gasto <b>${eur(gap)}</b> de facturas ya emitidas (sobre todo por la fecha en que las mete; no es un error de cálculo). ${con?'Estás viendo la <b>consolidada</b>: ese intragrupo se ha quitado de ingresos y de gastos, y el resultado del grupo queda '+eur(gap)+' por debajo de la suma de las dos empresas mientras el desfase no cierre.':'Estás viendo la <b>suma de las dos empresas</b>: la cifra de negocio del grupo cuenta dos veces esos '+eur(ig.income)+'. Cambia «Facturación» a <b>Consolidada</b> para eliminar el intragrupo.'}</p>`;
 return panel('Facturación entre Razo y Agetrans (intragrupo)','Medido en el libro contable por la cuenta de empresas del grupo, '+monthRange(lv.months)+'.',body);
}
function fuelPersonnelPanel(){
 const {lv}=ledgerCtx;if(!lv||!(lv.income>0))return '';
 const fuel=lv.expenseCategories.find(c=>c.id==='combustible')?.amount||0,pers=lv.expenseCategories.find(c=>c.id==='personal')?.amount||0;
 if(fuel<=0&&pers<=0)return '';
 const income=lv.income,base=lv.result,both=fuel+pers,res=(df,dp)=>base-fuel*df-pers*dp;
 const of=M.ownFleet({...state,from:lv.months[0]+'-01',to:monthEndOf(lv.months[lv.months.length-1])});
 const frac=of&&of.fraction!=null?of.fraction:null,ownInc=frac!=null?income*frac:null;
 // 1) De dónde sale la facturación
 const split=`<div class="ic-grid"><div class="ic-row"><span>Lo que facturas en total</span><b>${eur(income)}</b></div>`+(frac!=null?`<div class="ic-row sub"><span>Lo mueven nuestros camiones (viajes propios)</span><b>${eur(ownInc)} · ${pct(frac)}</b></div><div class="ic-row"><span>Lo hacen otros (subcontratado)</span><b>${eur(income-ownInc)} · ${pct(1-frac)}</b></div>`:'')+`<div class="ic-row"><span>Resultado</span><b>${eur(base)} · margen ${pct(base/income)}</b></div></div>`;
 // 2) Cuánto pesan el gasoil y el personal (sobre el total y sobre los viajes propios)
 const wcols=[{label:'Coste',key:'label'},{label:'Cuánto cuesta',key:'v',numeric:true,format:eur},{label:'% de la facturación total',key:'pt',numeric:true,format:pct}];
 if(frac!=null)wcols.push({label:'% de los viajes propios',key:'pp',numeric:true,format:dash(pct)});
 const wrows=[{label:'Combustible (gasoil)',v:fuel,pt:fuel/income,pp:ownInc?fuel/ownInc:null},{label:'Personal',v:pers,pt:pers/income,pp:ownInc?pers/ownInc:null},{label:'Los dos juntos',v:both,pt:both/income,pp:ownInc?both/ownInc:null,total:true}];
 const wnote=`<p class="ic-note">El gasoil y el personal solo los pone <b>nuestra flota</b>, así que lo que de verdad cuenta es su peso sobre <b>los viajes que hacen nuestros camiones</b>, no sobre el total (que incluye lo subcontratado, donde no ponemos ni gasoil ni conductores).${frac!=null?' Por eso el gasoil parece un '+pct(fuel/income)+' del total, pero es un <b>'+pct(fuel/ownInc)+'</b> de tus viajes propios.':''} El reparto propio/subcontratado sale de la matrícula de cada factura.</p>`;
 // 3) Qué pasa si suben esos costes (frases claras en vez de matriz)
 const scen=[['Si el gasoil sube un 5 %',res(0.05,0)],['Si el gasoil sube un 10 %',res(0.10,0)],['Si el personal sube un 5 %',res(0,0.05)],['Si el personal sube un 10 %',res(0,0.10)],['Si suben los dos un 5 %',res(0.05,0.05)],['Si suben los dos un 10 %',res(0.10,0.10)]];
 const scols=[{label:'Escenario',key:'label'},{label:'El resultado quedaría en',key:'v',numeric:true,format:eur},{label:'Cambio',key:'d',numeric:true,format:eur,tone:r=>r.d<-1?'neg':''}];
 const srows=scen.map(([l,v])=>({label:l,v,d:v-base}));
 const snote=`<p class="ic-note">Hoy el resultado es <b>${eur(base)}</b>. Por cada 1 % que sube el gasoil pierdes <b>${eur(fuel/100)}</b>; por cada 1 % que sube el personal, <b>${eur(pers/100)}</b>. Al revés funciona igual: si esos costes bajan, el resultado sube esos mismos importes.</p>`;
 return panel('El resultado según el combustible y el personal',`Sobre la contabilidad real (${monthRange(lv.months)}${lv.consolidado?', consolidada':''}). Cuánto pesan el gasoil y el personal, y qué le pasaría al resultado si cambian.`,split+`<h3>Cuánto pesan el gasoil y el personal</h3>`+simpleTable(wcols,wrows)+wnote+`<h3>Qué pasaría si suben esos costes</h3>`+simpleTable(scols,srows)+snote);
}
function bridgePanel(){
 const {br,lv}=ledgerCtx;if(!br||!lv?.months.length)return '';
 const top=br.groups.filter(g=>g.difference>0).sort((a,b)=>b.difference-a.difference).slice(0,3);
 const rows=br.groups.map(g=>({label:g.label,note:g.note,ledger:g.ledger,parts:g.inParts?g.parts:null,difference:g.inParts?g.difference:g.ledger,coverage:g.inParts?g.coverage:0}));
 if(Math.abs(br.residual)>1)rows.push({label:'Diferencia guardado / desglose del parte',note:'',ledger:0,parts:br.residual,difference:-br.residual,coverage:null});
 rows.push({label:'TOTAL',note:'',ledger:br.totalLedger,parts:br.totalParts,difference:br.missing,coverage:br.coverage,total:true});
 return panel('Puente: contabilidad frente a partes de Access',`Mismos meses (${monthRange(lv.months)}) y sociedades elegidas. La contabilidad es el gasto real; los partes solo captan lo que sus campos recogen.`,`<div class="warn"><strong>Los partes captan el ${pct(br.coverage)} del gasto real.</strong> Faltan ${eur(br.missing)} en el periodo${top.length?', sobre todo: '+top.map(g=>g.label.toLowerCase()+' ('+eur(g.difference)+')').join('; '):''}. Un margen calculado solo con los partes sale por encima del real.</div>`+simpleTable([{label:'Concepto',key:'label'},{label:'Contabilidad (real)',key:'ledger',numeric:true,format:eur},{label:'Partes de Access',key:'parts',numeric:true,format:dash(eur)},{label:'Falta en los partes',key:'difference',numeric:true,format:eur,tone:r=>r.difference>1?'neg':''},{label:'Captado',key:'coverage',numeric:true,format:dash(pct)},{label:'Nota',key:'note'}],rows));
}
// Personal: nómina real de la gestoría frente a lo que los partes imputan al conductor.
function personnelTramosPanel(){
 if(!D.payroll)return '';
 const cur=M.personnelByTramo(state);if(!cur||!cur.items.length)return '';
 const range=ledgerCtx.range,prev=range?.valid?M.personnelByTramo({...state,...range}):null;
 const prevMap=new Map((prev?.items||[]).map(x=>[x.type,x.cost]));
 const rows=cur.items.map(x=>{const pv=prevMap.get(x.type);return {label:x.label+(x.driver?'':' ·')+(x.unsure?' (por confirmar)':''),cost:x.cost,share:cur.total>0?x.cost/cur.total:0,meses:x.months,prev:pv??null,delta:pv!=null?x.cost-pv:null,deltaPct:(pv!=null&&pv!==0)?(x.cost-pv)/pv:null};});
 rows.push({label:'TOTAL',cost:cur.total,share:1,meses:cur.months,prev:prev?prev.total:null,delta:prev?cur.total-prev.total:null,deltaPct:(prev&&prev.total)?(cur.total-prev.total)/prev.total:null,total:true});
 const cols=[{label:'Tramo',key:'label'},{label:'Coste acumulado',key:'cost',numeric:true,format:eur},{label:'% del total',key:'share',numeric:true,format:pct},{label:'Meses',key:'meses',numeric:true,format:v=>nf(v,0)}];
 if(prev)cols.push({label:ledgerCtx.priorLabel||'Periodo anterior',key:'prev',numeric:true,format:dash(eur)},{label:'Δ',key:'delta',numeric:true,format:dash(eur),tone:r=>r.delta>1?'neg':r.delta<-1?'pos':''},{label:'Δ %',key:'deltaPct',numeric:true,format:dash(pct),tone:r=>r.deltaPct>0?'neg':r.deltaPct<0?'pos':''});
 const sub='Coste de empresa de la nómina de la gestoría (devengos + Seguridad Social + dietas), sumado en el periodo por tramo de la plantilla (· = no conduce)'+(prev?', comparado con '+(ledgerCtx.priorLabel||'el periodo anterior').toLowerCase():' (elige «Comparar con» arriba para contrastar)')+'. Importes agregados, sin datos de personas. Un aumento sale en rojo.';
 return panel('Costes de personal por tramo (acumulado'+(prev?' y comparado':'')+')',sub,bars(cur.items.map(x=>({label:x.label,cost:x.cost})),'cost')+simpleTable(cols,rows));
}
function personnelPanel(){
 const rec=M.reconcilePersonnel();if(!rec||!rec.rows.length)return '';
 const rows=rec.rows.slice(-12).reverse().map(r=>({label:monthName(r.month),payroll:r.payroll,imputed:r.imputed,pct:r.pct,gap:r.gap}));
 const types=rec.byType.map(t=>({label:t.label,payroll:t.payroll,imputed:t.imputed,pct:t.pct,gap:t.payroll-t.imputed}));
 return panel('Personal: nómina real frente a partes','Coste de empresa de los conductores según la gestoría (devengos + Seguridad Social + dietas) frente a lo que los partes imputan como conductor, horas extra y gastos de empleado.',`<div class="info">Acumulado: los partes imputan el ${pct(rec.cumulative)} de la nómina real de conductores. Este informe reparte la nómina real sobre los partes en «Con nómina real»; los meses sin partes suficientes quedan sin imputar.</div>`+simpleTable([{label:'Mes',key:'label'},{label:'Nómina real de conductores',key:'payroll',numeric:true,format:eur},{label:'Imputado en partes',key:'imputed',numeric:true,format:eur},{label:'Imputado',key:'pct',numeric:true,format:dash(pct)},{label:'Sin imputar',key:'gap',numeric:true,format:eur,tone:r=>r.gap>1?'neg':''}],rows)+`<h3>Último mes (${monthName(rec.last)}) por tipo de trabajo</h3>`+simpleTable([{label:'Tipo de trabajo',key:'label'},{label:'Nómina real',key:'payroll',numeric:true,format:eur},{label:'Imputado en partes',key:'imputed',numeric:true,format:eur},{label:'Imputado',key:'pct',numeric:true,format:dash(pct)},{label:'Sin imputar',key:'gap',numeric:true,format:eur}],types)+`<p class="sub" style="margin-top:12px">Resto de la nómina del mes (administración, taller, otros que no conducen): ${eur(rec.overhead)}, frente a ${eur(rec.structure)} de estructura imputada por los partes.</p>`);
}
// Combustible: tarjeta Solred y surtidor de la nave frente a los litros declarados.
// Sociedades cuyo combustible de Solred solo llega como resumen por matrícula (informe «Vehículos»), sin detalle por mes.
function resumenAviso(){
 const owners=D.metadata.solredResumen||[];if(!owners.length)return '';
 const infs=(D.fuel?.solredVehiculos||[]).filter(i=>owners.includes(i.owner));
 return `<div class="info"><strong>${owners.map(o=>esc(o.replace(/,? S\.L\.?/i,''))).join(' y ')} solo llega como resumen por matrícula</strong>${infs.length?' (informe «Vehículos» de Solred, '+infs.map(i=>date(i.desde)+' – '+date(i.hasta)).join('; ')+')':''}: se ve cuánto combustible compró cada camión en el periodo, pero no mes a mes. Para el detalle mensual faltan sus ficheros de operaciones en texto.</div>`;
}
function vehiculosSolred(){
 const infs=D.fuel?.solredVehiculos||[];if(!infs.length)return '';
 const nave=new Set(D.metadata.naveStations||[]);
 return infs.map(inf=>{
  const rows=inf.rows.map(r=>{const declared=D.parts.filter(p=>p.plate===r.plate&&p.date>=inf.desde&&p.date<=inf.hasta&&p.litres>0&&!nave.has(p.station)).reduce((s,p)=>s+p.litres,0);return {plate:r.plate,litros:r.litros,importe:r.importe,operaciones:r.operaciones,declared,cover:divide(r.litros,declared)};}).sort((a,b)=>b.litros-a.litros);
  const tot={plate:'TOTAL',litros:sum(rows,'litros'),importe:sum(rows,'importe'),operaciones:sum(rows,'operaciones'),declared:sum(rows,'declared'),total:true};tot.cover=divide(tot.litros,tot.declared);rows.push(tot);
  return `<h3>Informe «Vehículos» de Solred · ${esc(inf.owner.replace(/,? S\.L\.?/i,''))} · ${date(inf.desde)} – ${date(inf.hasta)}</h3>`+simpleTable([{label:'Matrícula',key:'plate'},{label:'Litros Solred',key:'litros',numeric:true,format:v=>nf(v,0)},{label:'Importe Solred (€)',key:'importe',numeric:true,format:eur},{label:'Operaciones',key:'operaciones',numeric:true,format:v=>nf(v)},{label:'Litros en partes (mismo periodo, fuera de la nave)',key:'declared',numeric:true,format:v=>nf(v,0)},{label:'Solred / partes',key:'cover',numeric:true,format:dash(pct)}],rows)+`<p class="sub" style="margin-top:8px">Fichero ${esc(inf.fichero)} · NIF ${esc(inf.nif||'—')}. Un camión con dos tarjetas suma las dos. Importe tal como lo da Solred.</p>`;
 }).join('');
}
function fuelPanel(){
 const rec=M.reconcileFuel();if(!rec||!rec.rows.length)return '';
 const cov=D.metadata.solredCoverage||{},weak=Object.entries(cov).filter(([,c])=>c<0.6);
 const rows=rec.rows.filter(r=>r.card>1000).reverse().map(r=>({label:monthName(r.month),declared:r.declared,card:r.card,cover:divide(r.card,r.declared),declaredNave:r.declaredNave,pump:r.pump,adL:r.adblue.declaredL,adC:r.adblue.cardL,tolls:r.tolls.card,tollsDecl:r.tolls.expensesVehicle}));
 return panel('Combustible: tarjeta y surtidor frente a partes','Litros de gasóleo por mes. La tarjeta Solred es real; los litros de los partes son declarados. Los repostajes en la nave (surtidor propio) se comparan aparte.',(resumenAviso()+(weak.length?`<div class="warn"><strong>Falta el fichero Solred de ${weak.map(([o])=>esc(o.replace(/,? S\.L\.?/i,''))).join(' y ')}</strong>: solo cubre ${weak.map(([,c])=>pct(c)).join(' y ')} de los litros declarados. Sin él no se puede confirmar su combustible; no se rellena con ceros.</div>`:''))+simpleTable([{label:'Mes',key:'label'},{label:'Litros en partes (fuera de la nave)',key:'declared',numeric:true,format:v=>nf(v,0)},{label:'Litros Solred',key:'card',numeric:true,format:v=>nf(v,0)},{label:'Solred / partes',key:'cover',numeric:true,format:dash(pct)},{label:'Litros en partes (nave)',key:'declaredNave',numeric:true,format:v=>nf(v,0)},{label:'Litros surtidor',key:'pump',numeric:true,format:v=>nf(v,0)},{label:'AdBlue partes (l)',key:'adL',numeric:true,format:v=>nf(v,0)},{label:'AdBlue Solred (l)',key:'adC',numeric:true,format:v=>nf(v,0)},{label:'Peajes Solred (€)',key:'tolls',numeric:true,format:eur},{label:'Gastos vehículo partes (€)',key:'tollsDecl',numeric:true,format:eur}],rows)+vehiculosSolred()+`<p class="sub" style="margin-top:12px">Solred llega hasta el ${date(rec.solred?.maxFecha)}${rec.surtidor?'; el surtidor de la nave hasta el '+date(rec.surtidor.maxFecha):''}. Los peajes reales están en Solred (VIA T y autopistas); en los partes van mezclados con otros gastos del vehículo.</p>`);
}
// Calidad de los partes de Access.
function qualityPanel(){
 const q=D.metadata.quality;if(!q)return '';
 return panel('Calidad de los partes de Access','Comprobaciones sobre los datos que rellenan los conductores y la oficina.',`<div class="audit-grid">${[['Partes con km imposibles (> '+nf(q.kmMaxParte)+' km)',nf(q.partesKmImposible),q.partesKmImposible?'bad':''],['Km excluidos de los totales',nf(q.kmExcluidos),q.kmExcluidos?'bad':'']].map(([l,v,c])=>`<div class="audititem ${c}"><span>${l}</span><strong>${v}</strong></div>`).join('')}</div>${q.peorParte?.length?`<p class="sub">Peores partes: ${q.peorParte.map(p=>`${esc(p.plate)} (${date(p.date)}): ${nf(p.km)} km`).join('; ')}. Sus importes se conservan; solo se excluyen los km imposibles.</p>`:''}<p class="sub">Comparados con el localizador, cuando un parte existe su kilometraje suele ser correcto; el problema es que falta el parte en muchos días en que el camión circula, y por eso el gasto de los partes queda corto.</p>`);
}
const groupColumns=()=>[{label:'Detalle',key:'label'},moneyCol('Ingresos sin IVA','revenue'),moneyCol('Coste imputable','cost'),moneyCol('Saldo aparente','balance'),percentCol('Cobertura','coverage'),numberCol('Viajes GesRuta','trips'),numberCol('Albaranes','deliveries'),numberCol('Km declarados','km'),numberCol('Horas','hours',1),moneyCol('Ingresos por km','revenueKm'),moneyCol('Beneficio por km','profitKm'),moneyCol('Ingresos por hora','revenueHour'),moneyCol('Beneficio por hora','profitHour'),numberCol('Ingresos por € de coste','revenuePerCost',2),numberCol('Beneficio por € de coste','profitPerCost',2),numberCol('Litros declarados','litres',1),numberCol('l/100 km declarado','consumption',2),moneyCol('€/km imputable','costKm'),numberCol('Facturas','invoices')];
const ratioNote='Los ratios (por € de coste, por km y por hora) usan el coste imputable y los km y horas DECLARADOS en los partes: son orientativos. El cálculo completo (contabilidad, subcontratistas reales, km y horas de Movertis y Locatel) está en construcción y se irá afinando.';
// Aviso de que el coste por vehículo o cliente es parcial: solo lo que los partes imputan.
const partialWarn=()=>{const br=ledgerCtx.br;return br&&br.totalLedger>0?`<div class="warn"><strong>El coste que se ve aquí es parcial.</strong> Solo es lo que los partes de Access imputan a vehículos (el ${pct(br.coverage)} del gasto real de ${monthRange(br.months)}). Faltan subcontratación, compra de áridos y gastos generales (${eur(br.missing)}), así que el saldo de cada fila es aparente y sale por encima del real. El resultado real está en la contabilidad (pestaña Resumen).</div>`:'';};
function setTable(title,subtitle,rows,columns,drill=null){tableDefinition={title,subtitle,rows,columns,drill};return `<section class="panel"><h2>${title}</h2><p class="sub">${subtitle}</p><div class="tabletools"><input id="tableSearch" type="search" placeholder="Buscar en todas las filas…" aria-label="Buscar en tabla" value="${esc(tableState.query)}"><span id="tableCount"></span></div><div id="tableArea"></div></section>`;}
function drawTable(){
 const def=tableDefinition;if(!def||!$('tableArea'))return;
 const query=tableState.query.toLocaleLowerCase('es');let rows=def.rows.filter(r=>!query||def.columns.some(c=>String(r[c.key]??'').toLocaleLowerCase('es').includes(query)));
 const count=rows.length;
 if(tableState.sort){const key=tableState.sort;rows=rows.slice().sort((a,b)=>{const aa=a[key],bb=b[key];const res=typeof aa==='number'&&typeof bb==='number'?aa-bb:String(aa??'').localeCompare(String(bb??''),'es',{numeric:true});return tableState.asc?res:-res;});}
 tableState.page=Math.min(tableState.page,Math.max(0,Math.ceil(rows.length/50)-1));
 const view=rows.slice(tableState.page*50,tableState.page*50+50);
 $('tableCount').textContent=`${nf(count)} filas${query?' encontradas':''} · ${nf(def.rows.length)} en el ámbito. La búsqueda de tabla no modifica los indicadores.`;
 $('tableArea').innerHTML=count?`<div class="tablewrap"><table><thead><tr>${def.columns.map(c=>`<th scope="col" aria-sort="${tableState.sort===c.key?(tableState.asc?'ascending':'descending'):'none'}"><button data-sort="${c.key}">${esc(c.label)} ${tableState.sort===c.key?(tableState.asc?'↑':'↓'):'↕'}</button></th>`).join('')}</tr></thead><tbody>${view.map(r=>`<tr>${def.columns.map((c,i)=>`<td class="${c.numeric?'num':''} ${c.numeric&&r[c.key]<0?'neg':''}" title="${esc(c.format?c.format(r[c.key]):r[c.key])}">${i===0&&def.drill?`<button class="tablelink" data-drill="${def.drill}" data-key="${esc(r.key)}">${esc(r[c.key])} ↗</button>`:esc(c.format?c.format(r[c.key]):r[c.key])}</td>`).join('')}</tr>`).join('')}</tbody></table></div><div class="pager"><span>${tableState.page*50+1}–${Math.min((tableState.page+1)*50,count)} de ${nf(count)} · todas las filas están disponibles</span><div><button data-page="-1" ${tableState.page===0?'disabled':''}>← Anterior</button><button data-page="1" ${(tableState.page+1)*50>=count?'disabled':''}>Siguiente →</button></div></div>`:`<div class="empty">No hay datos para esta combinación. Cambie los filtros o el texto de búsqueda.</div>`;
}
function partRows(){const map=new Map();for(const r of selection.costs){if(!map.has(r.id))map.set(r.id,{...r,allocation:0,allocated:0});const x=map.get(r.id);x.allocation+=r.share;x.allocated+=(state.costMode==='recalculated'?r.recalculated:r.stored)*r.share;}return [...map.values()].sort((a,b)=>b.date.localeCompare(a.date));}
// Barras de viajes reales por mes (una serie), con todos los volúmenes en el tooltip.
function activityChart(byMonth){
 const map=new Map(byMonth.map(r=>[r.key,r]));
 let mth=state.from.slice(0,7);const months=[];
 while(mth<=state.to.slice(0,7)&&months.length<36){months.push(map.get(mth)||{key:mth,viajes:0,m3:0,t:0,km:0,imp:0});const d=new Date(mth+'-01T12:00:00Z');d.setUTCMonth(d.getUTCMonth()+1);mth=d.toISOString().slice(0,7);}
 const w=760,h=240,left=48,right=15,top=15,bottom=40,inner=h-top-bottom,base=top+inner,max=Math.max(1,...months.map(r=>r.viajes)),y=v=>top+(max-v)/max*inner,step=(w-left-right)/Math.max(1,months.length),bw=Math.min(30,step*.55);
 const grid=Array.from({length:5},(_,i)=>{const v=max*i/4;return `<line x1="${left}" x2="${w-right}" y1="${y(v)}" y2="${y(v)}" stroke="#e6ecf4"/><text x="${left-8}" y="${y(v)+4}" text-anchor="end">${esc(short(v))}</text>`;}).join('');
 const bars=months.map((r,i)=>{const x=left+step*(i+.5);return `<rect x="${x-bw/2}" y="${y(r.viajes)}" width="${bw}" height="${Math.max(.5,base-y(r.viajes))}" fill="#2868dd" rx="2"><title>${esc(monthName(r.key)+' · '+nf(r.viajes)+' viajes · '+nf(r.m3,0)+' m³ · '+nf(r.t,0)+' t · '+eur(r.imp))}</title></rect><text x="${x}" y="${h-12}" text-anchor="middle">${esc(monthShort(r.key))}</text>`;}).join('');
 return `<svg class="chart" viewBox="0 0 ${w} ${h}" role="img" aria-label="Viajes reales por mes; los valores exactos están en la tabla mensual">${grid}${bars}</svg>`;
}
// Provincias como desplegables; dentro, sus localidades.
function zonesBlock(zones){
 const cols=[{label:'Localidad',key:'key'},numberCol('Viajes','viajes'),numberCol('m³','m3'),numberCol('Toneladas','t'),numberCol('Km','km'),moneyCol('Importe','imp')];
 return `<div class="zonelist">${zones.map(z=>`<details class="zone"><summary style="display:flex;justify-content:space-between;gap:12px;cursor:pointer;padding:9px 10px;border-bottom:1px solid #eef2f7"><b>${esc(z.key)}</b><span class="hint" style="white-space:nowrap">${nf(z.viajes)} viajes · ${nf(z.m3,0)} m³ · ${nf(z.t,0)} t · ${eur(z.imp)}</span></summary><div style="padding:6px 10px 14px">${simpleTable(cols,z.locs.slice(0,30))}${z.locs.length>30?`<p class="hint">+${z.locs.length-30} localidades más</p>`:''}</div></details>`).join('')}</div>`;
}
// Fila de un árbol de costes (cascada).
function treeRow(l,v,strong,soft,hint){return `<div style="display:flex;justify-content:space-between;gap:12px;padding:7px 2px;border-bottom:1px solid #eef2f7;${strong?'font-weight:700;':''}${soft?'color:#6b7a90;':''}"><span>${l}${hint?` <small style="color:#6b7a90">${hint}</small>`:''}</span><b>${eur(v)}</b></div>`;}
// Árbol de costes / cascada del P&L operativo de GesRuta (inggas).
function costTree(t){
 return `<div style="max-width:660px">${treeRow('Ingresos (GesRuta)',t.ing,1)}${treeRow('− Materiales (áridos comprados)',-t.materiales)}${treeRow('− Subcontratación (portes)',-t.subcontratacion)}${treeRow('= Coste directo comprado',-t.directos,1)}${treeRow('− Gasoil declarado en GesRuta',-t.gasoil,0,1)}${treeRow('− Peajes y AdBlue',-(t.peajes+t.adblue),0,1)}${treeRow('= Margen operativo',t.margen,1,0,pct(t.margenPct))}</div>`;
}
// Árbol NETO desde la contabilidad real (reconcilia con el resultado): Directos comprados → contribución → Flota → Indirectos.
function netTree(lv){
 const by=Object.fromEntries(lv.expenseCategories.map(c=>[c.id,c.amount])),g=id=>by[id]||0;
 const directos=g('aridos')+g('subcontratacion');
 const flotaOtros=g('amortizacion')+g('reparaciones')+g('seguros')+g('repuestos')+g('peajes')+g('alquileres')+g('dietas');
 const flota=g('combustible')+g('personal')+flotaOtros;
 const indirectos=lv.expenses-directos-flota;
 return `<div style="max-width:660px">${treeRow('Ingresos contables',lv.income,1)}${treeRow('− Áridos comprados',-g('aridos'))}${treeRow('− Subcontratación',-g('subcontratacion'))}${treeRow('= Margen de contribución',lv.income-directos,1)}${treeRow('− Combustible (diésel real)',-g('combustible'),0,1)}${treeRow('− Personal',-g('personal'),0,1)}${treeRow('− Amortización, reparaciones, seguros, neumáticos…',-flotaOtros,0,1)}${treeRow('− Indirectos (estructura, tributos, financieros…)',-indirectos,0,1)}${treeRow('= Resultado real',lv.result,1,0,pct(lv.marginPct))}</div>`;
}
function activityTab(){
 const v=M.activityView(state);
 if(!v)return panel('Actividad','Viajes reales de GesRuta (cada entrega con albarán de cantera).','<div class="info">No hay actividad de GesRuta en el periodo o empresa elegidos.</div>');
 const t=v.tot,mv=M.marginView(state);
 const prod=[['Viajes reales',nf(t.viajes),'cada entrega con albarán de cantera'],['Metros cúbicos',nf(t.m3,0),'hormigón'],['Toneladas',nf(t.t,0),'áridos'],['Km hormigón',nf(t.km,0),'campo «Km. Viaje»']];
 const eco=mv?[['Ingreso (GesRuta)',eur(mv.tot.ing),'inggas, todos los conceptos'],['Coste directo',eur(mv.tot.directos),'áridos + subcontratación'],['Margen operativo',eur(mv.tot.margen),pct(mv.tot.margenPct)+' · antes de flota y personal']]:[];
 const card=([l,x,h])=>`<article class="card"><span class="label">${l}</span><div class="value">${x}</div><div class="hint">${h}</div></article>`;
 const cards=`<section class="cards" style="margin-bottom:16px">${prod.map(card).join('')}</section>`+(eco.length?`<section class="cards" style="margin-bottom:16px">${eco.map(card).join('')}</section>`:'');
 const arbol=mv?panel('Margen operativo (GesRuta)','P&L que registra GesRuta por viaje (inggas): ingresos menos el coste directo comprado (material y subcontratación) y los gastos de circulación. Es ANTES del coste real de flota (diésel Solred+Access), personal (nómina) e indirectos.',costTree(mv.tot)):'';
 const lv=ledgerCtx.lv;
 const neto=(lv&&lv.months.length&&!hasFilters())?panel('Resultado real (contabilidad)','La contabilidad real de los meses cerrados ('+monthRange(lv.months)+(lv.consolidado?', consolidada':'')+'): del ingreso a lo que queda de verdad tras TODOS los costes. El margen operativo de arriba se come casi entero con el coste real de la flota, el personal y los indirectos — esto es el margen NETO.',netTree(lv)+`<p class="sub" style="margin-top:10px">Reconcilia con la pestaña Resumen. El margen operativo (GesRuta) y este resultado miden cosas distintas: aquel es por viaje y antes de la flota; este es el resultado contable real del grupo.</p>`):'';
 const trend=panel('Evolución de viajes','Viajes reales por mes; pasa el ratón por cada barra para ver volumen e importe.',activityChart(v.byMonth));
 const mes=v.byMonth.map(m=>({label:monthName(m.key),viajes:m.viajes,m3:m.m3,t:m.t,km:m.km,imp:m.imp}));
 const mensual=panel('Evolución mes a mes','Viajes reales, volumen e importe por mes.',simpleTable([{label:'Mes',key:'label'},{label:'Viajes',key:'viajes',numeric:true,format:x=>nf(x)},{label:'m³',key:'m3',numeric:true,format:x=>nf(x,0)},{label:'Toneladas',key:'t',numeric:true,format:x=>nf(x,0)},{label:'Km hormigón',key:'km',numeric:true,format:x=>nf(x,0)},{label:'Importe',key:'imp',numeric:true,format:eur}],mes));
 const modes=[['salida','Salida (origen)'],['llegada','Llegada (destino)'],['ambos','Ambos extremos']];
 const toggle=`<div class="segmented" style="margin-bottom:10px">${modes.map(([m,l])=>`<button data-zmode="${m}" aria-pressed="${zoneMode===m}" class="${zoneMode===m?'selected':''}">${esc(l)}</button>`).join('')}</div>`;
 const zset=zoneMode==='llegada'?v.zonasLlegada:zoneMode==='ambos'?v.zonasAmbos:v.zonasSalida;
 const zonas=panel('Actividad por zona (provincia → localidad)','Provincias ordenadas por viajes; despliega cada una para ver sus localidades. «Salida» cuenta por la provincia de origen; «Llegada», por la de destino; «Ambos», el viaje suma en las dos.',toggle+zonesBlock(zset));
 const rutas=panel('Rutas principales (origen → destino)','Primeras 20 combinaciones de provincia de origen y destino por número de viajes.',simpleTable([{label:'Ruta',key:'key'},numberCol('Viajes','viajes'),numberCol('m³','m3'),numberCol('Toneladas','t'),numberCol('Km','km'),moneyCol('Importe','imp')],v.rutas.slice(0,20)));
 const veh=panel('Por vehículo (primeros 15 por viajes)','Viajes reales, km, m³ e importe por camión.',simpleTable([{label:'Matrícula',key:'key'},{label:'Viajes',key:'viajes',numeric:true,format:x=>nf(x)},{label:'Km',key:'km',numeric:true,format:x=>nf(x,0)},{label:'m³',key:'m3',numeric:true,format:x=>nf(x,0)},{label:'Importe',key:'imp',numeric:true,format:eur}],v.byVeh.slice(0,15)));
 // Cliente: producción (cantera) + P&L operativo (inggas), unidos por nombre del maestro.
 const cmap=new Map();
 for(const r of v.byClient)cmap.set(r.key,{key:r.key,viajes:r.viajes,m3:r.m3,t:r.t,ing:0,directos:0,margen:0,margenPct:null});
 if(mv)for(const [k,x] of mv.byClient){const c=cmap.get(k)||{key:k,viajes:0,m3:0,t:0};c.ing=x.ing;c.directos=x.directos;c.margen=x.margen;c.margenPct=x.margenPct;cmap.set(k,c);}
 const clientRows=[...cmap.values()].sort((a,b)=>(b.margen||0)-(a.margen||0));
 const cli=setTable('Cliente: actividad y margen','Producción (viajes, m³, t) y P&L operativo de GesRuta (ingreso − coste directo comprado). El margen es antes del coste real de flota y personal. Ordenable y con búsqueda.',clientRows,[{label:'Cliente',key:'key'},numberCol('Viajes','viajes'),numberCol('m³','m3'),numberCol('Toneladas','t'),moneyCol('Ingreso','ing'),moneyCol('Coste directo','directos'),moneyCol('Margen op','margen'),percentCol('% margen','margenPct')]);
 return `<div class="info">Viaje real = cada entrega con <b>albarán de cantera</b>. Producción (viajes, m³/t, km) de las líneas de albarán. <b>Margen operativo</b> del P&L por viaje de GesRuta (inggas): ingreso − material − subcontratación − circulación, <b>antes</b> del coste real de flota. Debajo, el <b>resultado real</b> de la contabilidad tras diésel, personal e indirectos.</div>`+cards+arbol+neto+trend+mensual+zonas+rutas+veh+cli;
}
function renderContent(){
 tableDefinition=null;let html='';
 if(state.tab==='summary'&&ledgerCtx.ledgerOn){
   const {lv,br,lvBase}=ledgerCtx,op=new Map(M.group(selection,state,'month').groups.map(m=>[m.key,m]));
   const plRows=lv.byMonth.map(m=>({key:m.key,label:monthName(m.key),income:m.income,expenses:m.expenses,result:m.result,marginPct:m.marginPct,gesruta:op.get(m.key)?.revenue??0,parts:op.get(m.key)?.[state.costMode==='stored'?'rawCost':state.costMode==='recalculated'?'calcCost':'realCost']??0}));
   const totalExp=lv.expenses||1,cats=lv.expenseCategories.filter(c=>c.amount>0).slice(0,11).map(c=>({label:c.label,cost:c.amount,note:nf(c.amount/totalExp*100,0)+' %'}));
   html=`<div class="grid2">${panel('Ingresos y gastos por mes','Contabilidad real (CxConta), solo meses cerrados.'+(lvBase?' Líneas discontinuas: '+ledgerCtx.priorLabel.toLowerCase()+'.':''),`<div class="legend"><span><i style="background:var(--blue)"></i>Ingresos</span><span><i style="background:#169389"></i>Gastos</span>${lvBase?'<span style="color:var(--blue)"><i class="dash"></i>Ingresos (comparación)</span><span style="color:#169389"><i class="dash"></i>Gastos (comparación)</span>':''}</div>${plChart(lv.byMonth,lvBase?.byMonth)}`)}${panel('De qué está hecho el gasto real','Por naturaleza de la cuenta contable, en el periodo cerrado.',bars(cats,'cost'))}</div>${intercompanyPanel()}${fuelPersonnelPanel()}${ratiosPanel()}${metrics()}`;
   html+=setTable('Resultado mes a mes','Ingresos y gastos de la contabilidad. A la derecha, lo que captan las facturas de GesRuta y los partes de Access el mismo mes (el gasto de los partes es incompleto).',plRows,[{label:'Mes',key:'label'},moneyCol('Ingresos','income'),moneyCol('Gastos','expenses'),moneyCol('Resultado','result'),percentCol('Margen','marginPct'),moneyCol('Facturas GesRuta','gesruta'),moneyCol('Coste en partes','parts')]);
 }else if(state.tab==='summary'){
   const months=M.group(selection,state,'month').groups.sort((a,b)=>a.key.localeCompare(b.key));
   const mix=D.costFields.map(([key,label])=>({label,cost:current.totals.breakdown[key]}));
   if(state.costMode==='recalculated'){mix.find(r=>r.label==='Estructura').cost=selection.costs.reduce((n,r)=>n+r.componentDirect*r.rate*r.share,0);mix.find(r=>r.label==='Diferencia guardado / desglose').cost=0;}
   html=`<div class="grid2">${panel('Evolución mensual','Ingresos según el criterio elegido · costes según fecha del parte.',`<div class="legend"><span><i style="background:#2868dd"></i>Ingresos sin IVA</span><span><i style="background:#169389"></i>Coste disponible</span></div>${trendChart(months)}`)}${panel('De qué está hecho el coste','Desglose conservado del parte de Access.',bars(mix.filter(r=>Math.abs(r.cost)>.001).sort((a,b)=>b.cost-a.cost),'cost'))}</div>${metrics()}`;
   html+=setTable('Mes a mes','Esta tabla y los indicadores comparten el mismo cálculo. Los recuentos de facturas y viajes son distintos, no sumas de subtotales.',months,groupColumns());
 }else if(['plate','client'].includes(state.tab)){
   let rows=M.group(selection,state,state.tab).groups.sort((a,b)=>b.revenue-a.revenue);
   if(state.tab==='client')rows=rows.map(r=>({...r,label:r.label+' · '+(r.key===UNASSIGNED?UNASSIGNED:r.key.split('|')[0])}));
   html=partialWarn()+`<div class="info">${ratioNote}</div>`+panel(state.tab==='plate'?'Vehículos con más ingresos':'Clientes con más ingresos','Primeros ocho por ingresos; tabla completa debajo.',bars(rows.slice(0,8),'revenue'));
   html+=setTable(state.tab==='plate'?'Rentabilidad por vehículo':'Rentabilidad por cliente',state.tab==='plate'?'Al elegir un vehículo se filtra todo el informe. El coste total de la matrícula es el del parte; la cuota comercial es estimada.':'Costes, km y horas ESTIMADOS por la cuota de ingresos positivos del mes y vehículo. No acreditan el coste real de cada servicio.',rows,groupColumns(),state.tab==='plate'?'plates':'clients');
 }else if(state.tab==='invoices'){
   html=setTable('Detalle completo de facturación','Todas las líneas de la selección. El importe sin IVA respeta suplidos y ajustes de cabecera; ambas fechas quedan visibles.',selection.lines,[{label:'Factura',key:'invoice'},{label:'Empresa',key:'company'},{label:'Fecha factura',key:'invoiceDate'},{label:'Fecha línea',key:'lineDate'},{label:'Cliente',key:'client'},{label:'Vehículo',key:'plateLabel'},{label:'Viaje',key:'trip'},{label:'Albarán',key:'delivery'},{label:'Carga',key:'load'},{label:'Concepto',key:'concept'},numberCol('Cantidad','quantity',2),moneyCol('Precio','price'),moneyCol('Ingreso sin IVA','revenue'),{label:'Tipo',key:'kind'},{label:'Matrícula tomada de',key:'plateSource'}]);
 }else if(state.tab==='parts'){
   html=setTable('Partes y composición del coste','El coste origen es íntegro; el coste en selección aplica la cuota comercial. Un mismo parte puede contribuir a varios clientes. No se modifica el dato de Access.',partRows(),[{label:'Parte Access',key:'id'},{label:'Fecha',key:'date'},{label:'Matrícula',key:'plateLabel'},{label:'Tipo vehículo',key:'category'},{label:'Titular actual',key:'owner'},{label:'Cliente del parte',key:'partClient'},moneyCol('Coste origen','stored'),percentCol('Cuota en selección','allocation'),moneyCol('Coste en selección','allocated'),moneyCol('Recalculado origen','recalculated'),moneyCol('Descuadre directo','residual'),...D.costFields.filter(([k])=>k!=='residual').map(([k,l])=>moneyCol(l,k)),numberCol('Km origen','km'),numberCol('Horas origen','hours',2),numberCol('Viajes Access origen','trips')]);
 }else if(state.tab==='audit')html=audit();
 else if(state.tab==='personal')html=personalView();
 else if(state.tab==='actividad')html=activityTab();
 else html=method();
 $('content').innerHTML=html;drawTable();
}
function audit(){
 const dates=h=>inRange(h.invoiceDate,state.from,state.to), hs=D.headers.filter(h=>dates(h)&&includes(state.companies,h.company)&&includes(state.clients,h.clientId));
 const detailed=Boolean(state.plates.length||state.categories.length||state.loads.length||state.concepts.length);
 const invLines=D.lines.filter(r=>inRange(r.invoiceDate,state.from,state.to)&&includes(state.companies,r.company)&&includes(state.clients,r.clientId));
 const linePeriod=D.lines.filter(r=>inRange(r.lineDate,state.from,state.to)&&includes(state.companies,r.company)&&includes(state.clients,r.clientId));
 const base=sum(hs,'base'),invoiceLines=sum(invLines,'revenue'),lineIncome=sum(linePeriod,'revenue');
 const p=selection.physicalParts,raw=sum(p,'stored'),recalc=sum(p,'recalculated'),bad=p.filter(r=>Math.abs(r.residual)>.01);
 const unassigned=p.filter(r=>!M.weights.has(r.date.slice(0,7)+'|'+r.plate));
 let html=bridgePanel()+telemetryAuditPanel()+sensorDetailPanel()+personnelTramosPanel()+personnelPanel()+fuelPanel()+qualityPanel()+panel('Conciliación de facturas','Control de cabeceras: respeta empresa, cliente y fechas. Las cabeceras no se desglosan por vehículo, carga o concepto.',`${detailed?'<div class="info">Se mantienen los filtros de empresa, cliente y fechas; los filtros de vehículo, tipo, carga y concepto no se aplican a este control de cabeceras completas.</div>':''}<div class="audit-grid">${[
 ['Bases de cabecera',eur(base)],['Líneas por fecha factura',eur(invoiceLines)],['Diferencia líneas / bases',eur(invoiceLines-base)],['IVA en cabeceras',eur(sum(hs,'vat'))],['Total de facturas',eur(sum(hs,'gross'))],['Ingresos por fecha de línea',eur(lineIncome)]
 ].map(([l,v])=>`<div class="audititem"><span>${l}</span><strong>${v}</strong></div>`).join('')}</div><p class="sub">Cambiar la fecha explica ${eur(invoiceLines-lineIncome)}. El total de factura puede incluir IVA, retenciones, suplidos o bonificaciones: no se utiliza como ingreso de rentabilidad.</p>`);
 html+=panel('Conciliación de Access','Coste físico: mismos vehículos, tipos y fechas. Sin reparto por empresa facturadora, cliente, carga ni concepto.',`<div class="audit-grid">${[['Coste guardado en partes',eur(raw)],['Coste recalculado',eur(recalc)],['Diferencia con estructura',eur(recalc-raw)],['Partes con diferencia > 0,01 €',nf(bad.length)],['Ingreso diario declarado en Access',eur(sum(p,'accessRevenue'))],['Coste sin asignación mensual',eur(sum(unassigned,'stored'))]].map(([l,v])=>`<div class="audititem"><span>${l}</span><strong>${v}</strong></div>`).join('')}</div><div class="info">El ingreso diario de Access y las facturas de GesRuta tienen distinto detalle y cobertura. La diferencia no demuestra por sí sola una pérdida o un error. El coste de clientes sigue siendo estimado.</div>`);
 html+=setTable('Partes con diferencias internas','Se conserva el coste guardado como referencia de Access. Puede consultar el recalculado con el selector superior. Las diferencias pequeñas de redondeo se incluyen en los totales.',bad.map(r=>({...r,difference:r.recalculated-r.stored})),[{label:'Parte Access',key:'id'},{label:'Fecha',key:'date'},{label:'Vehículo',key:'plateLabel'},moneyCol('Directo guardado','direct'),moneyCol('Suma de conceptos','componentDirect'),moneyCol('Diferencia directa','residual'),moneyCol('Total guardado','stored'),moneyCol('Total recalculado','recalculated'),moneyCol('Diferencia total','difference')]);
 return html;
}
function method(){return `<div class="method">${panel('Criterios de cálculo','La procedencia y los límites del dato forman parte del informe.',`<ol>${D.definitions.map(t=>`<li>${esc(t)}</li>`).join('')}</ol>`)}${panel('Fuentes y fechas','Lecturas de los sistemas de origen, sin utilizar la base de pruebas del ERP.',`<p>Periodo disponible: <strong>${date(D.metadata.from)}–${date(D.metadata.to)}</strong>. Publicado: ${date(D.metadata.generatedAt)}.</p><p>Access: ${date(D.metadata.accessReadAt)} · ${nf(D.parts.length)} partes. GesRuta: ${date(D.metadata.gesrutaReadAt)} · ${nf(D.lines.length)} líneas, incluidos ajustes identificados.</p><p>Access: <code>P:\\PartesTrabajo\\Partes 7.0.accdb</code> · PartesTrabajo, Máquinas, Categorías, Empresas, Clientes y PlantasHormigon.</p><p>GesRuta: <code>P:\\Gesruta\\EMPTR21</code> y <code>P:\\Gesruta\\EMPAG21</code> · facturas.dbf, linfaclib.dbf, albara.dbf y mascli.dbf.</p>${D.ledger?`<p>Contabilidad: CxConta traspasada al ERP cada noche · leída ${date(D.ledger.meta.leido)} · cerrada hasta ${D.ledger.meta.lastClosed?monthName(D.ledger.meta.lastClosed):'—'}.</p>`:''}<h3>Qué es real y qué es declarado</h3><p><strong>Real:</strong> la contabilidad (CxConta), la tarjeta Solred, el surtidor de la nave y la nómina de la gestoría. <strong>Declarado:</strong> los partes de Access (km, litros, horas, gastos): los rellena una persona, faltan en muchos días y traen errores. Se muestran, pero no se toman como verdad. Los km y el consumo medidos por el propio camión (Movertis, Locatel) todavía no están conectados en este informe.</p><h3>Cuándo puede llamarse rentabilidad completa</h3><p>El resultado contable de cada sociedad es completo: incluye todos los gastos e ingresos. El resultado por vehículo o por cliente todavía no: falta repartir con criterio la subcontratación, la compra de áridos y los gastos generales, y enlazar los servicios de GesRuta con el vehículo que los hizo.</p><h3>Revisión realizada</h3><p>Se comprobaron claves de factura y línea, bases frente a cabeceras, totalidad del coste y del detalle, fechas, distribución mensual y conservación de importes al filtrar. El detalle ya no se limita a las 180 líneas de mayor importe.</p>`)}</div>`;}
// ---- Coste por empleado: capa privada CIFRADA con la clave que elige Roberto (AES-256-GCM en el navegador).
const PERSONAL_BLOB='__PACKED_PERSONAL__';
const personalEmpty=()=>({data:null,months:[],month:'',type:'all',error:'',busy:false});
let personal=personalEmpty();
async function unlockPersonal(){
 const key=$('personalKey')?.value||'';if(!key||personal.busy)return;
 if(!globalThis.crypto?.subtle){personal.error='Este navegador no permite descifrar desde esta dirección. Abra el informe con Edge o Chrome desde el icono del escritorio.';renderContent();return;}
 personal.busy=true;$('personalGo').disabled=true;$('personalGo').textContent='Descifrando…';
 try{
  const data=JSON.parse(await criptoDescifrar(PERSONAL_BLOB,key)),months=[...new Set(data.people.flatMap(p=>p.rows.map(r=>r.period)))].sort();
  personal={...personalEmpty(),data,months,month:months[months.length-1]||''};
 }catch(e){personal={...personalEmpty(),error:e.message==='CLAVE_INCORRECTA'?'La clave no es correcta.':'No se ha podido descifrar: '+e.message};}
 tableState={page:0,query:'',sort:'',asc:false};renderContent();
}
function personalRows(){
 const P=personal.data,out=[];
 const info=(company,section)=>{const s=P.sectionLabels?.[company]?.[String(section)];return {label:s?.label||'Sin sección',type:s?.type||'otros',unsure:Boolean(s?.porConfirmar)};};
 for(const p of P.people){
  const rs=p.rows.filter(r=>r.period===personal.month);if(!rs.length)continue;
  const total=k=>rs.reduce((s,r)=>s+(r[k]||0),0),main=rs.slice().sort((a,b)=>b.cost-a.cost)[0],t=info(main.company,main.section),cost=total('cost');
  const hours=rs.some(r=>r.hours!=null)?rs.reduce((s,r)=>s+(r.hours||0),0):null,access=p.costeHoraOrd??null;
  const km=rs.some(r=>r.km!=null)?total('km'):null,revenue=rs.some(r=>r.revenue!=null)?total('revenue'):null;
  out.push({key:p.key,name:p.name,company:main.company,typeLabel:t.label+(t.unsure?' (por confirmar)':''),type:t.type,cost,devengos:total('devengos'),ss:total('ss'),dietas:total('dietas'),hours,km,revenue,perHour:hours>0?cost/hours:null,accessHour:access,gap:hours>0&&access?cost/hours-access:null,costKm:km>0?cost/km:null,revenueHour:hours>0&&revenue!=null?revenue/hours:null,revenueKm:km>0&&revenue!=null?revenue/km:null,revenuePerCost:cost>0&&revenue!=null?revenue/cost:null,profitPerCost:cost>0&&revenue!=null?(revenue-cost)/cost:null});
 }
 return out.sort((a,b)=>b.cost-a.cost);
}
function personalView(){
 if(!personal.data)return `<section class="panel lock"><h2>Coste por empleado</h2><p class="sub">Este apartado muestra el coste de cada persona. Cualquiera con acceso a la carpeta puede abrir el informe, así que se protege con una clave: sin ella los datos no se pueden leer (no están en claro en el fichero). El resto del informe se ve igual sin la clave.</p><input id="personalKey" type="password" placeholder="Clave del apartado de personal" autocomplete="off" aria-label="Clave del apartado de personal"><div class="err" id="personalErr" role="alert">${esc(personal.error)}</div><button id="personalGo" class="go">Desbloquear</button><p class="sub" style="margin-top:12px">La clave la elige quien instala el informe (icono «Clave del personal»). Si se olvida, se elige otra y en la siguiente lectura se vuelve a cifrar.</p></section>`;
 const P=personal.data,all=personalRows(),types=[...new Set(all.map(r=>r.type))],rows=personal.type==='all'?all:all.filter(r=>r.type===personal.type);
 const cost=sum(rows,'cost'),hours=sum(rows,'hours'),withHours=rows.filter(r=>r.hours>0);
 const chips=[['all','Todos']].concat(types.map(t=>[t,P.typeLabels?.[t]||t])).map(([t,l])=>`<button data-ptype="${esc(t)}" class="${personal.type===t?'selected':''}">${esc(l)}</button>`).join('');
 const head=`<section class="panel"><div class="tabletools" style="margin-top:0"><div><h2>Coste por empleado y mes</h2><p class="sub" style="margin:0">Coste de empresa exacto de la nómina de la gestoría, por persona, con el trabajo que realiza. Las horas y los €/hora salen de los partes de Access (esas horas son declaradas).</p></div><button id="personalLock" class="textbtn">Bloquear</button></div>
 <div class="periodbar" style="margin-bottom:12px"><label>Mes<select id="personalMonth">${personal.months.slice().reverse().map(m=>`<option value="${m}" ${m===personal.month?'selected':''}>${esc(monthName(m))}</option>`).join('')}</select></label></div>
 <div class="chips2">${chips}</div>
 <div class="kpi-grid" style="grid-template-columns:repeat(4,1fr)">${[['Personas',nf(rows.length),'con nómina en el mes'],['Coste de empresa',eur(cost),monthName(personal.month)],['Horas en partes',nf(hours,1),nf(withHours.length)+' personas con partes'],['€/hora real medio',hours>0?eur(sum(withHours,'cost')/sum(withHours,'hours')):'—','Coste ÷ horas de sus partes']].map(([l,v,h])=>`<div class="smallkpi"><span class="label">${l}</span><span class="value">${v}</span><small>${h}</small></div>`).join('')}</div></section>`;
 const table=setTable('Personas','«€/hora real» = coste de empresa del mes ÷ horas de sus partes. «€/hora en Access» es la tarifa del contrato que usan los partes: la diferencia dice qué tarifas hay que corregir. «Facturación declarada» es la que anota el parte de Access (no la factura): los ratios por hora, km y € de coste son orientativos hasta cruzar cada viaje con GesRuta y los localizadores. Bajas, vacaciones y personas sin partes aparecen igual, con las horas en blanco.',rows,[{label:'Persona',key:'name'},{label:'Trabajo que realiza',key:'typeLabel'},{label:'Empresa',key:'company'},moneyCol('Coste empresa','cost'),moneyCol('Devengos','devengos'),moneyCol('Seg. Social','ss'),moneyCol('Dietas','dietas'),numberCol('Horas en partes','hours',1),numberCol('Km en partes','km'),moneyCol('€/hora real','perHour'),moneyCol('€/km de coste','costKm'),moneyCol('€/hora en Access','accessHour'),moneyCol('Diferencia','gap'),moneyCol('Facturación declarada','revenue'),moneyCol('Facturación por hora','revenueHour'),moneyCol('Facturación por km','revenueKm'),numberCol('Facturación por € de coste','revenuePerCost',2),numberCol('Beneficio por € de coste','profitPerCost',2)]);
 return head+table+`<p class="sub">Nombres casados con las fichas de Access: ${nf(P.match?.casadas)} de ${nf(P.match?.total)} meses de nómina (los no casados salen sin horas). Este apartado no se guarda: al cerrar o recargar el informe vuelve a pedir la clave.</p>`;
}
function renderSources(){
 const label={ok:'✓',parcial:'parcial',pendiente:'· pendiente',sin:'· sin datos'};
 $('sources').innerHTML=(D.metadata.sources||[]).map(s=>`<span class="src-pill ${s.state}" title="${esc(s.note+(s.to?' · hasta '+(String(s.to).length===7?monthName(s.to):date(s.to)):''))}">${esc(s.name)} ${label[s.state]||''}</span>`).join('');
}
function switchTab(tab){state.tab=tab;tableState={page:0,query:'',sort:'',asc:false};document.querySelectorAll('#tabs button').forEach(b=>{const on=b.dataset.tab===tab;b.classList.toggle('selected',on);if(on)b.setAttribute('aria-current','page');else b.removeAttribute('aria-current');});renderContent();}
function bind(){
 document.addEventListener('click',e=>{
  const b=e.target.closest('button');if(!b)return;
  if(b.dataset.company!==undefined){state.companies=b.dataset.company?[b.dataset.company]:[];tableState.page=0;update();}
  if(b.dataset.tab)switchTab(b.dataset.tab);
  if(b.id==='personalGo')unlockPersonal();
  if(b.id==='personalLock'){personal=personalEmpty();tableState={page:0,query:'',sort:'',asc:false};renderContent();}
  if(b.dataset.ptype!==undefined){personal.type=b.dataset.ptype;tableState={page:0,query:'',sort:'',asc:false};renderContent();}
  if(b.dataset.clear){state[b.dataset.clear]=[];tableState.page=0;update();}
  if(b.dataset.remove){state[b.dataset.remove]=state[b.dataset.remove].filter(v=>v!==b.dataset.value);tableState.page=0;update();}
  if(b.dataset.drill){state[b.dataset.drill]=[b.dataset.key==='Sin matrícula'?UNASSIGNED:b.dataset.key];update();}
  if(b.dataset.sort){tableState.asc=tableState.sort===b.dataset.sort?!tableState.asc:true;tableState.sort=b.dataset.sort;drawTable();}
  if(b.dataset.page){tableState.page+=Number(b.dataset.page);drawTable();}
  if(b.dataset.period){const [from,to]=b.dataset.period.split('|');$('from').value=from;$('to').value=to;tableState.page=0;update();}
  if(b.dataset.zmode){zoneMode=b.dataset.zmode;renderContent();}
 });
 document.addEventListener('keydown',e=>{if(e.key==='Enter'&&e.target.id==='personalKey')unlockPersonal();});
 document.addEventListener('change',e=>{
  const el=e.target;if(el.id==='personalMonth'){personal.month=el.value;tableState={page:0,query:'',sort:'',asc:false};renderContent();return;}
  if(el.dataset.slicer){const k=el.dataset.slicer;state[k]=el.checked?[...new Set([...state[k],el.value])]:state[k].filter(v=>v!==el.value);tableState.page=0;update();}
 });
 document.addEventListener('input',e=>{
  if(e.target.dataset.searchSlicer){const id=e.target.dataset.searchSlicer,q=e.target.value.toLocaleLowerCase('es');$('options-'+id).querySelectorAll('label').forEach(l=>l.hidden=!l.textContent.toLocaleLowerCase('es').includes(q));}
  if(e.target.id==='tableSearch'){tableState.query=e.target.value;tableState.page=0;drawTable();}
 });
 for(const id of ['from','to','dateBasis','compare','compareFrom','compareTo','costMode','billing'])$(id).addEventListener('change',()=>{$('customCompare').hidden=$('compare').value!=='custom';tableState.page=0;update();});
 $('reset').onclick=()=>{state={...state,companies:[],plates:[],clients:[],categories:[],loads:[],concepts:[]};$('from').value=D.metadata.defaultFrom;$('to').value=D.metadata.defaultTo;$('dateBasis').value='invoice';$('costMode').value=D.payroll?'real':'stored';$('compare').value='none';$('customCompare').hidden=true;tableState={page:0,query:'',sort:'',asc:false};update();};
 $('methodlink').onclick=e=>{e.preventDefault();switchTab('method');};
}
async function boot(){
 const bytes=Uint8Array.from(atob('__PACKED_DATA__'),c=>c.charCodeAt(0));
 D=JSON.parse(await new Response(new Blob([bytes]).stream().pipeThrough(new DecompressionStream('gzip'))).text());
 M=createModel(D);state={from:D.metadata.defaultFrom,to:D.metadata.defaultTo,dateBasis:'invoice',costMode:D.payroll?'real':'stored',consolidado:false,tab:'summary',companies:[],plates:[],clients:[],categories:[],loads:[],concepts:[]};
 if(!D.payroll)$('costMode').querySelector('option[value="real"]').remove();
 if(!D.ledger?.intragrupo?.length)$('billing').closest('label').hidden=true;
 $('costMode').value=state.costMode;$('billing').value='suma';renderSources();$('personalTab').hidden=!PERSONAL_BLOB;$('actividadTab').hidden=!D.actividad;
 for(const id of ['from','to','compareFrom','compareTo']){$(id).min=D.metadata.from;$(id).max=D.metadata.to;}
 $('from').value=state.from;$('to').value=state.to;$('compareFrom').value=priorYear(state.from);$('compareTo').value=priorYear(state.to);
 $('fresh').textContent='Lectura '+new Date(D.metadata.accessReadAt).toLocaleString('es-ES',{timeZone:'Europe/Madrid'})+' · datos hasta '+date(D.metadata.to);
 $('refreshMode').textContent=D.metadata.refresh?.mode==='scheduled'?'Actualización nocturna '+D.metadata.refresh.at:'Actualización nocturna pendiente';
 $('reloadReport').onclick=()=>location.reload();
 $('months').innerHTML=quickPeriods(D.metadata.from,D.metadata.to).map(r=>`<button data-period="${r.from}|${r.to}">${r.label}</button>`).join('');
 makeSlicers();bind();update();
}
boot().catch(error=>{$('message').innerHTML='<div class="alert error">No se pudo abrir el informe. Utilice una versión actual de Chrome, Edge o Firefox y vuelva a cargar. Los datos no se han modificado.</div>';$('fresh').textContent='No se ha podido cargar';console.error(error);});
