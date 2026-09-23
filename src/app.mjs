const $=id=>document.getElementById(id);
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
// useGrouping 'always': el formato español del navegador NO separa los miles con cuatro cifras («5576» junto a «16.071»).
const _nf={};
const nf=(v,n=0)=>v==null||!Number.isFinite(v)?'—':(_nf[n]||(_nf[n]=new Intl.NumberFormat('es-ES',{minimumFractionDigits:n,maximumFractionDigits:n,useGrouping:'always'}))).format(v);
const eur=v=>v==null?'—':nf(v,2)+' €';
const pct=v=>v==null?'—':nf(v*100,1)+' %';
const short=v=>new Intl.NumberFormat('es-ES',{notation:'compact',maximumFractionDigits:1}).format(v);
const date=d=>d?new Intl.DateTimeFormat('es-ES',{day:'2-digit',month:'short',year:'numeric',timeZone:'Europe/Madrid'}).format(new Date(d.length===10?d+'T12:00:00Z':d)):'—';
const moneyCol=(label,key)=>({label,key,format:eur,numeric:true});
const numberCol=(label,key,n=0)=>({label,key,format:v=>nf(v,n),numeric:true});
const percentCol=(label,key)=>({label,key,format:pct,numeric:true,signed:true});
const signedTone=(c,r)=>c.signed&&typeof r[c.key]==='number'?(r[c.key]>0?'pos strong':r[c.key]<0?'neg strong':''):'';
// Búsqueda sin tildes ni mayúsculas («coruña» = «CORUÑA» = «coruna»)
const norm=s=>String(s??'').normalize('NFD').replace(/[̀-ͯ]/g,'').toLocaleLowerCase('es');
// Estado de la tabla activa: búsqueda por palabras, filtros por columna, orden, página y filas desplegadas
const freshTable=()=>({page:0,query:'',sort:'',asc:false,filters:{},showFilters:false,open:new Set(),forTitle:''});
let D,M,state,selection,current,baseline=null,tableState=freshTable(),tableDefinition;
const slicerDefs=[['plates','Vehículo','plate','plateLabel'],['clients','Cliente','clientId','client'],['categories','Tipo de vehículo','category','category'],['loads','Carga','load','load'],['concepts','Tipo de servicio (cuenta)','concept','concept']];
let slicerOptions={},ledgerCtx={},zoneMode='salida',zonasAbiertas=new Set(),zonasVista={zonas:[],total:0};
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
// Cobertura del localizador: qué días hay y de qué fuente (ERP-Movertis, histórico bajado de Wialon, Locatel).
function telemetriaCobertura(){
 const m=D.telemetry.meta,fu=m.fuentes||{};
 return `Datos del localizador disponibles del <b>${date(m.desde)}</b> al <b>${date(m.hasta)}</b>: ${fu.erp?'ERP (Movertis) del '+date(fu.erp.desde)+' al '+date(fu.erp.hasta):''}${fu.historico?'; histórico bajado de Wialon del '+date(fu.historico.desde)+' al '+date(fu.historico.hasta)+' ('+nf(fu.historico.unidades)+' camiones, '+nf(fu.historico.dias)+' días-camión)':'; sin histórico anterior al ERP'}${fu.locatel?'; Locatel (solo km) del '+date(fu.locatel.desde)+' al '+date(fu.locatel.hasta):''}. ${nf(m.diasDescartados)} días-camión sin lectura fiable no se cuentan.`;
}
// Cómo se reparte lo medido por el localizador entre camiones y días (media, mediana, dispersión) y qué camiones gastan fuera
// de lo normal DE SU CLASE (tractora, rígido…): atípico = fuera de Q1 − 1,5·IQR … Q3 + 1,5·IQR del consumo de su clase.
function telemetriaReparto(v){
 const T=D.telemetry,pl=state.plates?.length?new Set(state.plates.map(p=>String(p).toUpperCase().replace(/[^A-Z0-9]/g,''))):null;
 const act=T.rows.filter(r=>r.date>=v.from&&r.date<=v.to&&(!pl||pl.has(r.plate))&&r.km>=30);if(act.length<5)return '';
 const cl=p=>(T.clases&&T.clases[p])||'(sin tipo en el ERP)';
 const byP=new Map();for(const r of act){const x=byP.get(r.plate)||{plate:r.plate,km:0,lit:0,kmF:0,dias:0};x.km+=r.km;x.dias++;if(r.litres>0){x.lit+=r.litres;x.kmF+=r.km;}byP.set(r.plate,x);}
 const P=[...byP.values()];
 const F=[['Km por día activo (30 km o más)',statsDe(act.map(r=>r.km)),'km',0],['Litros por día activo (camiones con sensor)',statsDe(act.filter(r=>r.litres>0).map(r=>r.litres)),'L',0],
  ['Consumo por día (días de 100 km o más, con sensor)',statsDe(act.filter(r=>r.km>=100&&r.litres>0).map(r=>r.litres/r.km*100)),'L/100 km',1],['Días activos por camión',statsDe(P.map(x=>x.dias)),'días',0],['Km por camión en el periodo',statsDe(P.map(x=>x.km)),'km',0]];
 const avisos=[];
 for(const c of [...new Set(P.filter(x=>x.kmF>=1000).map(x=>cl(x.plate)))].sort()){
  const xs=P.filter(x=>x.kmF>=1000&&cl(x.plate)===c).map(x=>({...x,l100:x.lit/x.kmF*100}));if(xs.length<3)continue;
  const S=statsDe(xs.map(x=>x.l100));F.push(['Consumo por camión · '+c+' ('+xs.length+' camiones con sensor y 1.000 km o más)',S,'L/100 km',1]);
  const iqr=S.q3-S.q1,hi=S.q3+1.5*iqr,lo=S.q1-1.5*iqr,alto=xs.filter(x=>x.l100>hi).sort((a,b)=>b.l100-a.l100),bajo=xs.filter(x=>x.l100<lo).sort((a,b)=>a.l100-b.l100);
  const q=x=>`<b>${esc(plateFmt(x.plate))}</b> ${nf(x.l100,1)} L/100 km <small>(${nf(x.kmF)} km con sensor)</small>`;
  if(alto.length||bajo.length)avisos.push(`<li><b>${esc(c)}</b> (mediana ${nf(S.mediana,1)} L/100 km): ${alto.length?'muy por encima de su clase — revisar el sensor de consumo o el camión: '+alto.map(q).join(', '):''}${alto.length&&bajo.length?'; ':''}${bajo.length?'muy por debajo — revisar el sensor (¿mal calibrado?): '+bajo.map(q).join(', '):''}.</li>`);
  else{const s=xs.slice().sort((a,b)=>b.l100-a.l100);avisos.push(`<li><b>${esc(c)}</b> (mediana ${nf(S.mediana,1)} L/100 km): ninguno fuera de lo normal; los que más gastan ${s.slice(0,3).map(q).join(', ')}; los que menos ${s.slice(-3).reverse().map(q).join(', ')}.</li>`);}
 }
 return `<details class="tstats" style="margin-top:14px"><summary>Cómo se reparte entre camiones y días: media, mediana, dispersión y camiones que gastan fuera de lo normal</summary><div class="tripdetail"><div style="grid-column:1/-1">${statsTabla(F)}${avisos.length?`<p class="sub" style="margin:10px 0 4px"><b>Camiones fuera de lo normal de su clase</b> (consumo por encima de Q3 + 1,5 veces el rango intercuartílico, o por debajo de Q1 − 1,5 veces; solo camiones con sensor y 1.000 km o más en el periodo):</p><ul class="rel">${avisos.join('')}</ul>`:''}</div></div></details>`;
}
function telemetryPanel(){
 if(!D.telemetry)return '';
 const v=M.telemetryView(state);
 if(!v)return `<section class="panel"><h2>Medido por el camión (localizador)</h2><p class="sub">Km y litros medidos por el propio camión en el periodo elegido (${date(state.from)} – ${date(state.to)}).</p><div class="info">No hay días del localizador en el periodo elegido. ${telemetriaCobertura()}</div></section>`;
 const fuenteTxt=Object.entries(v.porFuente||{}).map(([k,n])=>({erp:'ERP (Movertis)',historico:'histórico Wialon',locatel:'Locatel'}[k]||k)+' '+nf(n)).join(' · ');
 return `<section class="panel"><h2>Medido por el camión (localizador)</h2><p class="sub">Km y litros medidos por el propio camión <b>del ${date(v.from)} al ${date(v.to)}</b>${v.recortado?' (el periodo elegido, '+date(state.from)+' – '+date(state.to)+', se recorta a los días con lectura)':' (el periodo elegido arriba)'}. Solo días con lectura fiable: un día sin lectura no cuenta como cero. Días-camión de este periodo por fuente: ${fuenteTxt}. ${telemetriaCobertura()}</p><div class="kpi-grid">${[
  ['Km medidos',nf(v.km),nf(v.plates)+' camiones activos'],['Camiones con sensor de consumo',nf(v.sensorInv.conSensor)+' de '+nf(v.sensorInv.motor)+' con motor',v.sensorInv.sinSensor?('sin sensor: '+v.sensorInv.sinSensorPlates.join(', ')+(v.sensorInv.remolques?'. '+nf(v.sensorInv.remolques)+' remolques no cuentan':'')):(v.sensorInv.remolques?nf(v.sensorInv.remolques)+' remolques no gastan gasoil':'todos lo llevan')],['Litros medidos',nf(v.litres),'Solo los '+nf(v.sensorInv.conSensor)+' camiones con sensor'],['Consumo medido',nf(v.consumption,1)+' l/100 km','Solo camiones con sensor; el resto no mide litros'],['Días-camión activos',nf(v.activeDays),'Circula 30 km o más ese día'],['Días activos sin parte',nf(v.daysWithoutPart)+' ('+pct(v.pctWithoutPart)+')','El camión circuló y no hay parte de Access'],['Km del parte / km medidos',nf(v.ratio,2),'En los días con parte (1 = coinciden)']
 ].map(([l,x,h])=>`<div class="smallkpi"><span class="label">${l}</span><span class="value">${x}</span><small>${h}</small></div>`).join('')}</div>${telemetriaReparto(v)}</section>`;
}
function telemetryAuditPanel(){
 if(!D.telemetry)return '';
 const v=M.telemetryView(state);if(!v)return '';
 const rows=v.plateRows.slice(0,15).map(r=>({label:r.label,activeDays:r.activeDays,daysWithoutPart:r.daysWithoutPart,pct:r.pctWithoutPart,km:r.km,kmWithoutPart:r.kmWithoutPart,consumption:r.consumption}));
 return panel('Localizador frente a partes de Access',`Localizador (ERP-Movertis, histórico Wialon y Locatel), del ${date(v.from)} al ${date(v.to)}.`,`<div class="warn"><strong>En el ${pct(v.pctWithoutPart)} de los días en que un camión circuló no hay parte de Access</strong> (${nf(v.daysWithoutPart)} de ${nf(v.activeDays)} días-camión, ${nf(v.kmWithoutPart)} km). Cuando el parte existe, su kilometraje coincide con el medido (cociente ${nf(v.ratio,2)}). Por eso el coste de los partes queda corto y por eso el consumo declarado no sirve.</div>`+simpleTable([{label:'Matrícula',key:'label'},{label:'Días activos',key:'activeDays',numeric:true,format:v=>nf(v)},{label:'Sin parte',key:'daysWithoutPart',numeric:true,format:v=>nf(v)},{label:'% sin parte',key:'pct',numeric:true,format:dash(pct)},{label:'Km medidos',key:'km',numeric:true,format:v=>nf(v)},{label:'Km sin parte',key:'kmWithoutPart',numeric:true,format:v=>nf(v)},{label:'Consumo medido (l/100 km)',key:'consumption',numeric:true,format:dash(v=>nf(v,1))}],rows)+`<p class="sub" style="margin-top:12px">Primeros 15 camiones por kilómetros sin parte. Consumo medido: solo camiones con sensor de combustible y lectura fiable.</p>`);
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
 return `<div class="tablewrap"><table><thead><tr>${columns.map(c=>`<th class="plain ${c.numeric?'num':''}">${esc(c.label)}</th>`).join('')}</tr></thead><tbody>${rows.map(r=>`<tr class="${r.total?'total':''}">${columns.map(c=>`<td class="${c.numeric?'num':''} ${signedTone(c,r)||(c.tone&&c.tone(r))||''}" title="${cell(c,r)}">${cell(c,r)}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`;
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
// stats (opcional): función (filas visibles) → HTML con la estadística de lo que se ve; sigue a la búsqueda y a los filtros.
const STATS_KEY='rz_stats_open';
function setTable(title,subtitle,rows,columns,drill=null,detail=null,stats=null){
 if(tableState.forTitle!==title){tableState.filters={};tableState.query='';tableState.showFilters=false;tableState.open=new Set();tableState.page=0;tableState.forTitle=title;}
 rows.forEach((r,i)=>{r.__i=i;});
 for(const c of columns)if(c.filter===undefined)c.filter=filterKind(c,rows);
 tableDefinition={title,subtitle,rows,columns,drill,detail,stats};
 const k=activeFilterCount(),open=tableState.showFilters||k>0;
 const st=stats?`<details id="tstats" class="tstats"${lsGet(STATS_KEY,false)?' open':''}><summary>Estadística de los <b id="tstatsN">${nf(rows.length)}</b> viajes que ves: media, mediana, dispersión y rectas para calcular <small>(sigue a la búsqueda y a los filtros)</small></summary><div id="tstatsBody" class="tripdetail"></div></details>`:'';
 return `<section class="panel"><h2>${title}</h2><p class="sub">${subtitle}</p><div class="tabletools"><div class="tabletools-l"><input id="tableSearch" type="search" placeholder="Buscar palabras (todas deben aparecer; da igual tildes o mayúsculas)…" aria-label="Buscar en tabla" value="${esc(tableState.query)}"><button id="tableFilters" type="button" class="${open?'on':''}" aria-expanded="${open}">Filtros${k?' · '+k:''}</button></div><span id="tableCount"></span></div><div id="tableFilterBar" class="filterbar" ${open?'':'hidden'}>${filterBarHtml(columns,rows)}</div><div id="tableChips" class="active-filters tchips"></div>${st}<div id="tableArea"></div></section>`;
}
function drawStats(){
 const def=tableDefinition;if(!def||!def.stats)return;
 const rows=tableState.lastRows||def.rows,n=$('tstatsN');if(n)n.textContent=nf(rows.length);
 const d=$('tstats');if(d&&d.open){const b=$('tstatsBody');if(b)b.innerHTML=def.stats(rows)||'<div class="empty">Sin viajes con dato en lo que ves.</div>';}
}
// Qué filtro le toca a cada columna: fechas (desde/hasta), cifra (mín./máx.) y, todo lo demás, TEXTO QUE SE ESCRIBE (contiene
// todas las palabras, sin tildes; con sugerencias de los valores reales). Roberto 23/09: «los buscadores tienen que poder
// escribir en ellos para ir buscando sin tener que hacerlo en una lista» — fuera los desplegables.
function filterKind(c,rows){
 if(c.html)return false;
 if(c.numeric)return 'number';
 let n=0,dateLike=true,sample=null;
 for(const r of rows){const v=r[c.key];if(v==null||v==='')continue;const s=String(v);n++;if(sample===null)sample=s;if(dateLike&&!/^\d{4}-\d{2}(-\d{2})?$/.test(s)){dateLike=false;break;}}
 if(!n)return false;
 if(dateLike){c.dateLen=sample.length;return 'date';}
 return 'text';
}
function filterBarHtml(columns,rows){
 const f=tableState.filters,out=[];
 for(const c of columns){
  if(!c.filter||c.filter==='number')continue;
  const v=f[c.key];
  if(c.filter==='date'){const t=c.dateLen===7?'month':'date';out.push(`<label class="fctl"><span>${esc(c.label)} desde</span><input type="${t}" data-tfilter="${esc(c.key)}" data-part="from" value="${esc(v?.from||'')}"></label><label class="fctl"><span>${esc(c.label)} hasta</span><input type="${t}" data-tfilter="${esc(c.key)}" data-part="to" value="${esc(v?.to||'')}"></label>`);continue;}
  const freq=new Map();for(const r of rows){const x=r[c.key];if(x==null||x==='')continue;const s=String(x);freq.set(s,(freq.get(s)||0)+1);}
  if(c.filter==='select'){const opts=[...freq.keys()].sort((a,b)=>a.localeCompare(b,'es',{numeric:true}));out.push(`<label class="fctl"><span>${esc(c.label)}</span><select data-tfilter="${esc(c.key)}"><option value="">Todos</option>${opts.map(o=>`<option value="${esc(o)}"${v===o?' selected':''}>${esc(o)}</option>`).join('')}</select></label>`);}
  else{const opts=[...freq.entries()].sort((a,b)=>b[1]-a[1]).slice(0,300).map(e=>e[0]).sort((a,b)=>a.localeCompare(b,'es'));const lid='dl_'+String(c.key).replace(/\W/g,'_');out.push(`<label class="fctl"><span>${esc(c.label)}</span><input type="search" list="${lid}" data-tfilter="${esc(c.key)}" placeholder="escribe (varias palabras)…" autocomplete="off" value="${esc(v||'')}"><datalist id="${lid}">${opts.map(o=>`<option value="${esc(o)}">`).join('')}</datalist></label>`);}
 }
 const nums=columns.filter(c=>c.filter==='number');
 if(nums.length){const n=f.__num||{};out.push(`<div class="fctl fnum"><span>Cifra entre (elige la columna)</span><div class="fnumrow"><select data-tnum="key"><option value="">— columna —</option>${nums.map(c=>`<option value="${esc(c.key)}"${n.key===c.key?' selected':''}>${esc(c.label)}</option>`).join('')}</select><input type="number" step="any" data-tnum="min" placeholder="mín." aria-label="mínimo" value="${esc(n.min??'')}"><input type="number" step="any" data-tnum="max" placeholder="máx." aria-label="máximo" value="${esc(n.max??'')}"></div></div>`);}
 out.push(`<div class="fctl fact"><span>&nbsp;</span><button id="tableClearFilters" type="button">Quitar todos los filtros</button></div>`);
 return out.join('');
}
const numSet=v=>v!==''&&v!=null&&!Number.isNaN(Number(v));
function activeFilterCount(){let k=0;for(const [key,v] of Object.entries(tableState.filters)){if(key==='__num'){if(v&&v.key&&(numSet(v.min)||numSet(v.max)))k++;}else if(v&&typeof v==='object'){if(v.from)k++;if(v.to)k++;}else if(v!=null&&v!=='')k++;}return k;}
function rowPasses(r,def){
 const f=tableState.filters;
 for(const c of def.columns){
  const v=f[c.key];if(v==null||v===''||!c.filter||c.filter==='number')continue;
  const raw=r[c.key];
  if(c.filter==='select'){if(String(raw??'')!==v)return false;}
  else if(c.filter==='date'){if(!v.from&&!v.to)continue;const s=String(raw??'').slice(0,c.dateLen);if(v.from&&s<v.from.slice(0,c.dateLen))return false;if(v.to&&s>v.to.slice(0,c.dateLen))return false;}
  else{const s=norm(raw);for(const t of norm(v).split(/\s+/))if(t&&!s.includes(t))return false;}
 }
 const n=f.__num;
 if(n&&n.key&&(numSet(n.min)||numSet(n.max))){const x=r[n.key];if(typeof x!=='number')return false;if(numSet(n.min)&&x<Number(n.min))return false;if(numSet(n.max)&&x>Number(n.max))return false;}
 return true;
}
// Texto de la fila para la búsqueda por palabras (se calcula una vez por fila y tabla)
const hayOf=(r,def)=>{if(r.__hayT!==def.title){r.__hay=def.columns.map(c=>c.html?'':norm(r[c.key])).join('\u0001');r.__hayT=def.title;}return r.__hay;};
function chipsHtml(def){
 const f=tableState.filters,out=[],lab=k=>def.columns.find(c=>c.key===k)?.label||k;
 for(const [key,v] of Object.entries(f)){
  if(key==='__num'){if(v&&v.key&&(numSet(v.min)||numSet(v.max)))out.push(`<button class="chip" data-tremove="__num" title="Quitar filtro">${esc(lab(v.key))}${numSet(v.min)?' ≥ '+esc(v.min):''}${numSet(v.max)?' ≤ '+esc(v.max):''} ×</button>`);}
  else if(v&&typeof v==='object'){if(v.from)out.push(`<button class="chip" data-tremove="${esc(key)}" data-part="from" title="Quitar filtro">${esc(lab(key))} desde ${esc(v.from)} ×</button>`);if(v.to)out.push(`<button class="chip" data-tremove="${esc(key)}" data-part="to" title="Quitar filtro">${esc(lab(key))} hasta ${esc(v.to)} ×</button>`);}
  else if(v!=null&&v!=='')out.push(`<button class="chip" data-tremove="${esc(key)}" title="Quitar filtro">${esc(lab(key))}: ${esc(v)} ×</button>`);
 }
 return out.join('');
}
function removeFilter(key,part){
 const f=tableState.filters,bar=$('tableFilterBar'),q=s=>bar?bar.querySelector(s):null;
 if(key==='__num'){delete f.__num;if(bar)bar.querySelectorAll('[data-tnum]').forEach(el=>{el.value='';});}
 else if(part){if(f[key]&&typeof f[key]==='object'){delete f[key][part];if(!f[key].from&&!f[key].to)delete f[key];}const el=q(`[data-tfilter="${CSS.escape(key)}"][data-part="${part}"]`);if(el)el.value='';}
 else{delete f[key];const el=q(`[data-tfilter="${CSS.escape(key)}"]`);if(el)el.value='';}
 tableState.page=0;drawTable();
}
function applyFilterControl(el){
 if(el.dataset.tfilter!==undefined){const k=el.dataset.tfilter,p=el.dataset.part;if(p){const cur=tableState.filters[k]&&typeof tableState.filters[k]==='object'?tableState.filters[k]:{};tableState.filters[k]={...cur,[p]:el.value};}else tableState.filters[k]=el.value;}
 else if(el.dataset.tnum!==undefined){const bar=$('tableFilterBar'),g=n=>bar?.querySelector(`[data-tnum="${n}"]`)?.value??'';tableState.filters.__num={key:g('key'),min:g('min'),max:g('max')};}
 else return;
 tableState.page=0;drawTable();
}
function drawTable(){
 const def=tableDefinition;if(!def||!$('tableArea'))return;
 const terms=norm(tableState.query).split(/\s+/).filter(Boolean);
 let rows=def.rows.filter(r=>rowPasses(r,def)&&(!terms.length||(h=>terms.every(t=>h.includes(t)))(hayOf(r,def))));
 const count=rows.length,k=activeFilterCount();tableState.lastRows=rows;
 if(tableState.sort){const key=tableState.sort;rows=rows.slice().sort((a,b)=>{const aa=a[key],bb=b[key];const res=typeof aa==='number'&&typeof bb==='number'?aa-bb:String(aa??'').localeCompare(String(bb??''),'es',{numeric:true});return tableState.asc?res:-res;});}
 tableState.page=Math.min(tableState.page,Math.max(0,Math.ceil(rows.length/50)-1));
 const view=rows.slice(tableState.page*50,tableState.page*50+50);
 const chips=$('tableChips');if(chips)chips.innerHTML=chipsHtml(def);
 const fb=$('tableFilters');if(fb){fb.textContent='Filtros'+(k?' · '+k:'');fb.classList.toggle('on',k>0||tableState.showFilters);}
 $('tableCount').textContent=`${nf(count)} filas${(terms.length||k)?' encontradas':''} · ${nf(def.rows.length)} en el ámbito. La búsqueda y los filtros de la tabla no modifican los indicadores.`;
 const ncol=def.columns.length,cls=c=>`${c.numeric?'num':''} ${c.center?'ctr':''}`;
 const cell=(c,r,i)=>i===0&&def.drill?`<button class="tablelink" data-drill="${def.drill}" data-key="${esc(r.key)}">${esc(r[c.key])} ↗</button>`:(c.html?String(c.format?c.format(r[c.key]):r[c.key]??''):esc(c.format?c.format(r[c.key]):r[c.key]));
 $('tableArea').innerHTML=count?`<div class="tablewrap"><table class="${def.detail?'expandable':''}"><thead><tr>${def.columns.map(c=>`<th scope="col" class="${cls(c)}" aria-sort="${tableState.sort===c.key?(tableState.asc?'ascending':'descending'):'none'}"><button data-sort="${c.key}">${esc(c.label)} ${tableState.sort===c.key?(tableState.asc?'↑':'↓'):'↕'}</button></th>`).join('')}</tr></thead><tbody>${view.map(r=>{const open=Boolean(def.detail)&&tableState.open.has(r.__i);return `<tr${def.detail?` class="exp${open?' open':''}" data-row="${r.__i}" title="Pincha para ${open?'plegar':'ver'} el detalle"`:''}>${def.columns.map((c,i)=>`<td class="${cls(c)} ${signedTone(c,r)||(c.numeric&&r[c.key]<0?'neg':'')}" title="${esc(c.format?c.format(r[c.key]):r[c.key])}">${i===0&&def.detail?`<span class="caret" aria-hidden="true">${open?'▾':'▸'}</span>`:''}${cell(c,r,i)}</td>`).join('')}</tr>${open?`<tr class="detailrow"><td colspan="${ncol}">${def.detail(r)}</td></tr>`:''}`;}).join('')}</tbody></table></div><div class="pager"><span>${tableState.page*50+1}–${Math.min((tableState.page+1)*50,count)} de ${nf(count)} · todas las filas están disponibles</span><div><button data-page="-1" ${tableState.page===0?'disabled':''}>← Anterior</button><button data-page="1" ${(tableState.page+1)*50>=count?'disabled':''}>Siguiente →</button></div></div>`:`<div class="empty">No hay datos para esta combinación. Cambie los filtros o el texto de búsqueda.</div>`;
 drawStats();
}
// ---- Recuadros explicativos (.info): cada uno se puede ocultar y un botón general los oculta/muestra todos; se recuerda en el navegador.
const INFO_KEY='rz_info_hidden',INFO_ALL='rz_info_all';
const lsGet=(k,d)=>{try{const v=localStorage.getItem(k);return v==null?d:JSON.parse(v);}catch(e){return d;}};
const lsSet=(k,v)=>{try{localStorage.setItem(k,JSON.stringify(v));}catch(e){}};
const hashStr=s=>{let h=0;for(let i=0;i<s.length;i++)h=(h*31+s.charCodeAt(i))|0;return (h>>>0).toString(36);};
function wireInfo(){
 document.querySelectorAll('#content .info, #message .info').forEach(el=>{
  if(el.dataset.infoId)return;
  const id=hashStr(el.textContent.trim().slice(0,160));el.dataset.infoId=id;
  const btn=document.createElement('button');btn.className='info-x';btn.type='button';btn.dataset.infoHide=id;btn.title='Ocultar esta explicación';btn.textContent='Ocultar';el.appendChild(btn);
  const min=document.createElement('div');min.className='info-min';min.innerHTML=`<span aria-hidden="true">ⓘ</span><button type="button" class="textbtn" data-info-show="${id}">Mostrar la explicación</button>`;el.after(min);
 });
 applyInfo();
}
function applyInfo(){
 const all=lsGet(INFO_ALL,true),hidden=new Set(lsGet(INFO_KEY,[]));
 const gb=$('infoToggle');if(gb)gb.textContent=all?'Ocultar explicaciones':'Mostrar explicaciones';
 document.querySelectorAll('[data-info-id]').forEach(el=>{const off=!all||hidden.has(el.dataset.infoId);el.hidden=off;const min=el.nextElementSibling;if(min&&min.classList.contains('info-min'))min.hidden=!off||!all;});
}
function infoSet(id,hide){const hidden=new Set(lsGet(INFO_KEY,[]));if(hide)hidden.add(id);else hidden.delete(id);lsSet(INFO_KEY,[...hidden]);applyInfo();}
function infoAll(){lsSet(INFO_ALL,!lsGet(INFO_ALL,true));applyInfo();}
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
// Árbol de zonas en UNA tabla: provincia ▸ localidad (pueblo) ▸ punto (planta, cantera u obra).
// Se despliega sin repintar el resto de la pestaña y recuerda lo abierto al cambiar de periodo o de modo.
function zonaFila(n,nivel,clave,total,abierta,conHijos){
 const tog=conHijos?`<button class="ztog" data-ztoggle="${esc(clave)}" aria-expanded="${abierta}" aria-label="${abierta?'Plegar':'Desplegar'} ${esc(n.key)}">${abierta?'▾':'▸'}</button>`:'<span class="ztog"></span>';
 const nombre=/^\(sin /.test(n.key)?`<span class="zsin">${esc(n.key)}</span>`:esc(n.key);
 const o=v=>v?nf(v,0):'—';   // en nacional no hay m³ ni toneladas: guion en vez de un cero que no dice nada
 return `<tr class="z${nivel}"><td>${tog}${nombre}</td><td class="num">${nf(n.viajes)}</td><td class="num">${pct(total?n.viajes/total:null)}</td><td class="num">${o(n.m3)}</td><td class="num">${o(n.t)}</td><td class="num">${o(n.km)}</td><td class="num">${eur(n.imp)}</td></tr>`;
}
function zonasTabla(zonas,total){
 let filas='';
 for(const z of zonas){
  const kz='P|'+z.key,az=zonasAbiertas.has(kz);
  filas+=zonaFila(z,1,kz,total,az,z.hijos.length>0);
  if(!az)continue;
  for(const l of z.hijos){
   const kl='L|'+z.key+'|'+l.key,al=zonasAbiertas.has(kl);
   filas+=zonaFila(l,2,kl,total,al,(l.hijos||[]).length>0);
   if(al)for(const q of l.hijos)filas+=zonaFila(q,3,'',total,false,false);
  }
 }
 return `<div class="ztree-wrap"><table class="ztree"><thead><tr><th class="plain">Zona</th><th class="plain num">Viajes</th><th class="plain num">% de los viajes</th><th class="plain num">m³</th><th class="plain num">Toneladas</th><th class="plain num">Km hormigón</th><th class="plain num">Importe</th></tr></thead><tbody>${filas}</tbody></table></div>`;
}
function zonesBlock(zonas,total){zonasVista={zonas,total};return `<p class="ztip">Pulsa ▸ para desplegar: provincia → localidad (el pueblo) → punto (planta, cantera u obra).</p><div id="zonasTabla">${zonasTabla(zonas,total)}</div>`;}
// Fila de un árbol de costes (cascada).
function treeRow(l,v,strong,soft,hint){return `<div style="display:flex;justify-content:space-between;gap:12px;padding:7px 2px;border-bottom:1px solid #eef2f7;${strong?'font-weight:700;':''}${soft?'color:#6b7a90;':''}"><span>${l}${hint?` <small style="color:#6b7a90">${hint}</small>`:''}</span><b>${eur(v)}</b></div>`;}
// Árbol de costes / cascada del P&L operativo de GesRuta (inggas).
function costTree(t){
 return `<div style="max-width:660px">${treeRow('Ingresos (GesRuta)',t.ing,1)}${treeRow('− Materiales (áridos comprados)',-t.materiales)}${treeRow('− Subcontratación (portes)',-t.subcontratacion)}${treeRow('= Coste directo comprado',-t.directos,1)}${treeRow('− Gasoil declarado en GesRuta',-t.gasoil,0,1)}${treeRow('− Peajes y AdBlue',-(t.peajes+t.adblue),0,1)}${treeRow('= Margen operativo',t.margen,1,0,pct(t.margenPct))}</div>`;
}
// Línea desplegable del árbol: la suma como cabecera y, dentro, cada cuenta de la contabilidad.
function treeGroup(label,subs){
 const items=subs.filter(s=>Math.abs(s.amount)>0.5).sort((a,b)=>b.amount-a.amount);
 const total=items.reduce((s,x)=>s+x.amount,0);
 const body=items.map(s=>`<div style="display:flex;justify-content:space-between;gap:12px;padding:5px 2px 5px 20px;color:#6b7a90;border-bottom:1px solid #f3f6fa"><span>${esc(s.label)}</span><span>${eur(-s.amount)}</span></div>`).join('');
 return `<details><summary style="display:flex;justify-content:space-between;gap:12px;padding:7px 2px;border-bottom:1px solid #eef2f7;color:#6b7a90;cursor:pointer;list-style:none"><span>− ${label} <small style="color:#9aa7b8">▸ desglose</small></span><b>${eur(-total)}</b></summary>${body}</details>`;
}
// Árbol NETO desde la contabilidad real (reconcilia con el resultado): Directos comprados → contribución → Flota → Indirectos.
const NETO_DIRECTOS=['aridos','subcontratacion'],NETO_FLOTA=['combustible','personal','amortizacion','reparaciones','seguros','repuestos','alquileres','dietas','peajes'];
function netTree(lv){
 const by=Object.fromEntries(lv.expenseCategories.map(c=>[c.id,c.amount])),g=id=>by[id]||0;
 const sub=ids=>lv.expenseCategories.filter(c=>ids.includes(c.id)).map(c=>({label:c.label,amount:c.amount}));
 const directos=g('aridos')+g('subcontratacion');
 const flotaOtrosSubs=sub(NETO_FLOTA.filter(id=>id!=='combustible'&&id!=='personal'));
 const indirectosSubs=lv.expenseCategories.filter(c=>!NETO_DIRECTOS.includes(c.id)&&!NETO_FLOTA.includes(c.id)).map(c=>({label:c.label,amount:c.amount}));
 return `<div style="max-width:660px">${treeRow('Ingresos contables',lv.income,1)}${treeRow('− Áridos comprados',-g('aridos'))}${treeRow('− Subcontratación',-g('subcontratacion'))}${treeRow('= Margen de contribución',lv.income-directos,1)}${treeRow('− Combustible (diésel real)',-g('combustible'),0,1)}${treeRow('− Personal',-g('personal'),0,1)}${treeGroup('Otros de flota (amortización, talleres, seguros, neumáticos…)',flotaOtrosSubs)}${treeGroup('Indirectos y estructura',indirectosSubs)}${treeRow('= Resultado real',lv.result,1,0,pct(lv.marginPct))}</div>`;
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
 const zonas=panel('Actividad por zona (provincia → localidad → punto)','Ordenado por viajes. «Salida» cuenta por el origen; «Llegada», por el destino; «Ambos», por los dos extremos (un viaje que sale y llega en la misma zona cuenta una sola vez en ella).',toggle+zonesBlock(zset,t.viajes));
 const rutas=panel('Rutas principales (origen → destino)','Primeras 20 combinaciones de provincia de origen y destino por número de viajes.',simpleTable([{label:'Ruta',key:'key'},numberCol('Viajes','viajes'),numberCol('m³','m3'),numberCol('Toneladas','t'),numberCol('Km','km'),moneyCol('Importe','imp')],v.rutas.slice(0,20)));
 const veh=panel('Por vehículo (primeros 15 por viajes)','Viajes reales, km, m³ e importe por camión.',simpleTable([{label:'Matrícula',key:'key'},{label:'Viajes',key:'viajes',numeric:true,format:x=>nf(x)},{label:'Km',key:'km',numeric:true,format:x=>nf(x,0)},{label:'m³',key:'m3',numeric:true,format:x=>nf(x,0)},{label:'Importe',key:'imp',numeric:true,format:eur}],v.byVeh.slice(0,15)));
 // Cliente: producción (cantera) + P&L operativo (inggas), unidos por nombre del maestro.
 const cmap=new Map();
 for(const r of v.byClient)cmap.set(r.key,{key:r.key,viajes:r.viajes,m3:r.m3,t:r.t,ing:0,directos:0,margen:0,margenPct:null});
 if(mv)for(const [k,x] of mv.byClient){const c=cmap.get(k)||{key:k,viajes:0,m3:0,t:0};c.ing=x.ing;c.directos=x.directos;c.margen=x.margen;c.margenPct=x.margenPct;cmap.set(k,c);}
 const clientRows=[...cmap.values()].sort((a,b)=>(b.margen||0)-(a.margen||0));
 const cli=setTable('Cliente: actividad y margen','Producción (viajes, m³, t) y P&L operativo de GesRuta (ingreso − coste directo comprado). El margen es antes del coste real de flota y personal. Ordenable y con búsqueda.',clientRows,[{label:'Cliente',key:'key'},numberCol('Viajes','viajes'),numberCol('m³','m3'),numberCol('Toneladas','t'),moneyCol('Ingreso','ing'),moneyCol('Coste directo','directos'),{...moneyCol('Margen op','margen'),signed:true},percentCol('% margen','margenPct')]);
 // Margen NETO por cliente y zona: coste real de la contabilidad repartido por las bases del viaje (litros/horas/km/ingreso).
 const nv=M.netaView(state);
 const pctPlain=(l,k)=>({label:l,key:k,numeric:true,format:pct});
 const netoCols=[{label:'Cliente',key:'key'},numberCol('Viajes','viajes'),moneyCol('Ingreso','ingreso'),moneyCol('Coste real','coste'),{...moneyCol('Margen neto','margen'),signed:true},percentCol('% neto','margenPct'),pctPlain('Medido','fiable')];
 const zonaCols=[{label:'Zona (salida)',key:'key'},numberCol('Viajes','viajes'),moneyCol('Ingreso','ingreso'),{...moneyCol('Margen neto','margen'),signed:true},percentCol('% neto','margenPct'),pctPlain('Medido','fiable')];
 const netoDim=nv?panel('Margen NETO por cliente y por zona',
   'El coste REAL de la contabilidad de cada mes repartido a los viajes de ese mes por su base —combustible por litros, personal por horas, flota por km, indirectos por ingreso— y escalado al ingreso capturado en los viajes, de modo que el conjunto cuadra con el margen contable de los meses cerrados, antes del impuesto de sociedades ('+pct(nv.margenLibroPct)+'). Verde gana, rojo pierde. «Medido» = qué parte del ingreso lleva km y horas REALES del localizador; los viajes sin traza reciben su parte del gasto por su ingreso (no cargan a los medidos).'+(nv.mesesEstimados&&nv.mesesEstimados.length?' Meses sin contabilidad cerrada ('+nv.mesesEstimados.map(monthName).join(', ')+'): coste ESTIMADO con los coeficientes del último mes cerrado.':''),
   '<div class="info">Coeficientes medios del periodo (viajes medidos): <b>'+eur(nv.coef.lit)+' / litro</b> · <b>'+eur(nv.coef.dur*60)+' / hora</b> · <b>'+eur(nv.coef.km)+' / km</b>. Los directos (áridos y subcontratación) van por CLIENTE según su P&L de inggas; el resto por base del viaje, mes a mes. Es una atribución con método, no una factura por cliente.</div>'
   +'<h3>Por cliente</h3>'+simpleTable(netoCols,[...nv.byClient,{...nv.tot,key:'TOTAL',total:true}])
   +'<h3>Por zona (provincia de salida)</h3>'+simpleTable(zonaCols,nv.byZona.slice(0,15))):'';
 return `<div class="info">Viaje real = cada entrega con <b>albarán de cantera</b>. Producción (viajes, m³/t, km) de las líneas de albarán. <b>Margen operativo</b> del P&L por viaje de GesRuta (inggas): ingreso − material − subcontratación − circulación, <b>antes</b> del coste real de flota. Debajo, el <b>resultado real</b> de la contabilidad tras diésel, personal e indirectos.</div>`+cards+arbol+neto+netoDim+trend+mensual+zonas+rutas+veh+cli;
}
function viajesTab(){
 const t=M.netaTrips(state);
 if(!t)return panel('Margen por viaje','Margen neto de cada viaje real.','<div class="info">Necesita la triangulación (km y horas por viaje) y la contabilidad. No disponible para este periodo o empresa.</div>');
 const v2=t.some(x=>x.tini!=null||x.metodo);
 const cols=[{label:'Día',key:'dia',center:true},{label:'Cliente',key:'cliente'},{label:'Lugar de carga',key:'carga'},{label:'Lugar de descarga',key:'descarga'},{label:'Provincias',key:'ruta'},{label:'Matrícula',key:'mat',center:true}]
  .concat(v2?[numberCol('Nº día','orden'),{label:'Inicio',key:'tini',center:true},{label:'Fin',key:'tfin',center:true}]:[])
  .concat([numberCol('m³','m3'),numberCol('Toneladas','t'),numberCol('Km','km')])
  .concat(t.some(x=>x.kmCarg!=null)?[numberCol('Km cargado','kmCarg'),numberCol('Km vacío','kmVac')]:[])
  .concat([numberCol('Horas','horas',1),numberCol('Litros','lit',1)])
  .concat(v2?[numberCol('Min. conducción','cond'),numberCol('Min. espera','espera'),{label:'Chofer (tacógrafo)',key:'chofer',center:true}]:[])
  .concat([moneyCol('Ingreso','ingreso'),moneyCol('Coste real','coste'),{...moneyCol('Margen neto','margen'),signed:true},percentCol('% neto','margenPct'),{label:'Fiabilidad',key:'fiab',center:true}])
  .concat(v2?[{label:'Método',key:'metodo',center:true},{label:'Confianza',key:'conf',center:true},{label:'Mapa',key:'mapaKey',html:true,center:true,format:v=>v?`<a class="noprint" href="dias/${encodeURIComponent(v)}.html" target="_blank" rel="noopener">ver día</a>`:'—'}]:[]);
 const tri=D.actividad&&D.actividad.tri;
 const largasTxt=tri&&tri.largas_medidas!=null?`largo recorrido (≥200 km): <b>${nf(tri.largas_medidas||0)}</b> de ${nf(tri.largas_con_traza||0)} con traza medidos de carga a descarga aunque crucen días (horas = de trabajo, sin los descansos), con <b>km cargado y en vacío</b>`:`largas distancias pendientes de la pasada de nacional ${nf(tri&&tri.largas||0)}`;
 const triHtml=tri?`<div class="info"><b>Triangulación v${tri.version||2}</b> (${esc(tri.generado||'')}): <b>${nf(tri.medido||0)}</b> de ${nf(tri.con_traza||tri.viajes||0)} viajes de áridos/nacional <b>con traza del localizador</b>${tri.desde_traza?` (${esc(tri.desde_traza)} → ${esc(tri.hasta_traza||'')})`:''} tienen <b>hora real de inicio y fin</b> (${tri.pct_con_traza!=null?tri.pct_con_traza:tri.pct||0} %); ${nf(tri.sin_traza||0)} viajes más son de fechas sin traza bajada, camiones ajenos o sin localizador · confianza alta ${nf(tri.alta||0)} / media ${nf(tri.media||0)} · ${largasTxt} · minutos del <b>tacógrafo</b> en ${nf(tri.taco||0)} viajes${tri.taco_descartado?` (en ${nf(tri.taco_descartado)} más el localizador no recibe el tacógrafo: se usa la traza)`:''} · el chofer del tacógrafo coincide con GesRuta en ${nf(tri.chofer_ok||0)} de ${nf((tri.chofer_ok||0)+(tri.chofer_no||0))} · jornadas nocturnas ${nf(tri.nocturnas||0)} · albaranes sin ciclo en la traza ${nf(tri.sin_ciclo||0)} (<b>sin dato, no cero</b>) · nº de cantera repetido (error de grabación) ${nf(tri.repetidas||0)}${tri.espejos?` · ${nf(tri.espejos)} portes que salen en Razo y en Agetrans (espejo intercompañía) medidos una vez y marcados «espejo»`:''}. <b>Inicio/Fin</b> en hora de Madrid («+1» = acaba al día siguiente).</div>`:'';
 return `<div class="info">Cada <b>viaje real</b> con su <b>margen neto</b>: ingreso menos el coste real (combustible, personal, flota, subcontratación e indirectos). <b>Pincha en un viaje</b> para desplegar su detalle: lugares de carga y descarga, horario real, km cargado y en vacío, litros, minutos de conducción y de espera, desglose del coste y el mapa del día. Ordena por «Margen neto» para ver los peores; busca por palabras o abre «Filtros» para acotar por cliente, lugar, matrícula, fechas o cifras. «Fiabilidad»: <b>medido/repartido</b> = km y horas del localizador; <b>subcontrata</b> = coste real de la factura del subcontratista (por línea, cuadra con la contabilidad); <b>estimado</b> = hormigón (horas de la traza GPS). El aviso <b>⚠</b> marca algún viaje propio suelto de clientes casi todo subcontratados, donde el reparto de áridos sale inflado — ahí fíate del margen por <b>cliente</b>.</div>`+triHtml+setTable('Margen por viaje','Los '+nf(t.length)+' viajes del periodo, ordenables, con búsqueda por palabras y filtros por columna. Verde gana, rojo pierde. Pincha en una fila para desplegar el detalle del viaje. Abre «Estadística de los viajes que ves» para la media, la mediana, la dispersión y las rectas de justo los viajes que dejan la búsqueda y los filtros (por ejemplo, una ruta).',t,cols,null,tripDetail,rows=>estadViajes(rows,''));
}
// ---- HALLAZGOS: lo que el cruce GesRuta ↔ localizador ↔ tacógrafo descubre y sirve para actuar (listas medidas, con qué hacer).
const HZ_ROL={carga:'cargando',descarga:'descargando',espera:'espera en ruta',fuera:'fuera de viaje'};
function hzBloque(id,titulo,sub,columns,rows,abierto=false,max=400){
 const n=rows.length;
 return `<details class="hz" ${abierto?'open':''}><summary>${esc(titulo)} <span class="hzn">${nf(n)}</span></summary><p class="sub">${sub}</p>${n?simpleTable(columns,rows.slice(0,max)):'<div class="empty">Nada que señalar.</div>'}${n>max?`<p class="sub">Se muestran ${max} de ${nf(n)}; el fichero triangulado_v2.json en P:\\_RENTABILIDAD tiene la lista completa.</p>`:''}</details>`;
}
function hallazgosTab(){
 const H=D.actividad&&D.actividad.tri&&D.actividad.tri.hallazgos;
 if(!H)return panel('Hallazgos','','<div class="info">Sin datos de la triangulación.</div>');
 const R=H.resumen||{},j=a=>(a||[]).join(', ');
 const kp=(l,v,h)=>`<div class="smallkpi"><span class="label">${l}</span><span class="value">${v}</span><small>${h}</small></div>`;
 let html=`<div class="info">Lo que el cruce de GesRuta con el <b>localizador</b> y el <b>tacógrafo</b> descubre y <b>sirve para actuar</b>. Cada lista es un dato medido sobre todo el periodo con traza (no se filtra por las fechas de arriba); en cada una se dice qué hacer con ella. La tabla de cargas sin albarán admite búsqueda y filtros; las demás se despliegan pinchando en su título.</div>`;
 html+=`<section class="panel"><div class="kpi-grid" style="grid-template-columns:repeat(4,1fr)">${kp('Cargas sin albarán',nf(R.cargas_sin_albaran),'ciclos del camión sin albarán en GesRuta')}${kp('Albaranes sin ciclo',nf(R.albaranes_sin_ciclo),'albaranes que la traza no explica')}${kp('Canteras repetidas',nf(R.canteras_repetidas),'nº de cantera grabado dos veces')}${kp('Localizador sin tacógrafo',nf(R.camiones_tacografo_descartado),'camiones: instalación de Movertis')}${kp('Chofer distinto',nf(R.chofer_discrepante_viajes),'viajes con tarjeta ≠ albarán')}${kp('Unidades incoherentes',nf(R.unidades_incoherentes),'traza que no casa con sus albaranes')}${kp('Sin localizador',nf(R.sin_localizador_viajes),'viajes de camiones sin traza')}${kp('Largos sin traza contigua',nf(R.largos_pendientes),'se medirán al bajarla')}${R.albaranes_matricula_baja!=null?kp('Matrícula dada de baja',nf(R.albaranes_matricula_baja),'albaranes tras la baja del camión en el ERP'):''}</div></section>`;
 const csa=(H.cargas_sin_albaran||[]).map(r=>({fecha:r.fecha,mat:r.matricula,tipo:r.tipo,ini:(r.t_ini||'').slice(11),fin:(r.t_fin||'').slice(11),min:r.min,km:r.km,origen:r.origen_nombre||r.origen||'—',destino:r.destino_nombre||r.destino||'—',minObra:r.min_obra,mapa:r.matricula&&r.fecha?r.matricula+'_'+r.fecha:null}));
 html+=setTable('Cargas sin albarán en GesRuta','Ciclos reales del camión (salida cargado → descarga → vuelta, de al menos 10 minutos y 1 km) que ese día no tienen ningún albarán en GesRuta: <b>posibles cargas sin facturar</b> o albaranes grabados en otra fecha o matrícula. Compruébalos en GesRuta antes de dar nada por perdido; «ver día» enseña la traza.',csa,[{label:'Fecha',key:'fecha',center:true},{label:'Matrícula',key:'mat',center:true},{label:'Tipo',key:'tipo',center:true},{label:'Inicio',key:'ini',center:true},{label:'Fin',key:'fin',center:true},numberCol('Min','min'),numberCol('Km','km',1),{label:'Carga en',key:'origen'},{label:'Descarga / obra en',key:'destino'},numberCol('Min en obra','minObra'),{label:'Mapa',key:'mapa',html:true,center:true,format:v=>v?`<a class="noprint" href="dias/${encodeURIComponent(v)}.html" target="_blank" rel="noopener">ver día</a>`:'—'}]);
 html+=hzBloque('sc','Albaranes que la traza no explica (sin ciclo)','Albaranes cuya carga no aparece en la traza del camión ese día (hay más albaranes que ciclos). Causas típicas: matrícula o fecha grabadas mal en GesRuta, dos albaranes de una misma carga que no caben en la cuba, o planta no localizada. Sin dato, no cero.',[{label:'Fecha',key:'fecha'},{label:'Empresa',key:'empresa'},{label:'Viaje',key:'viaje'},{label:'Alb. cantera',key:'cantera'},{label:'Matrícula',key:'matricula'},{label:'Cliente',key:'cliente'},{label:'Origen',key:'origen_nombre'},{label:'Destino',key:'destino_nombre'},{label:'Tipo',key:'tipo'},{label:'Motivo',key:'motivo'}],(H.albaranes_sin_ciclo||[]).map(r=>({...r,origen_nombre:r.origen_nombre||r.origen,destino_nombre:r.destino_nombre||r.destino})));
 if(H.albaranes_matricula_baja)html+=hzBloque('mb','Albaranes con matrícula dada de baja','Albaranes fechados más de 7 días después de la baja del camión en el ERP (vendido, achatarrado): la matrícula está mal grabada en GesRuta y el viaje lo hizo otro camión. Corregir la matrícula en GesRuta; mientras, el viaje no lleva km ni horas de ningún camión.',[{label:'Fecha',key:'fecha'},{label:'Matrícula',key:'matricula'},{label:'Baja en el ERP',key:'fecha_baja'},{label:'Motivo de la baja',key:'motivo_baja'},{label:'Empresa',key:'empresa'},{label:'Viaje',key:'viaje'},{label:'Alb. cantera',key:'cantera'},{label:'Cliente',key:'cliente'},{label:'Origen',key:'origen_nombre'},{label:'Destino',key:'destino_nombre'}],(H.albaranes_matricula_baja||[]).map(r=>({...r,origen_nombre:r.origen_nombre||r.origen,destino_nombre:r.destino_nombre||r.destino})),true);
 html+=hzBloque('rep','Nº de cantera repetido (error de grabación)','El mismo número de albarán de cantera está grabado en varias líneas del mismo año y origen. Es un error de grabación en GesRuta: hasta corregirlo, esos viajes quedan sin recorrido (decidir por ellos sería inventar).',[{label:'Empresa',key:'empresa'},{label:'Origen',key:'origen_nombre'},{label:'Alb. cantera',key:'cantera'},{label:'Año',key:'anio'},numberCol('Líneas','lineas'),{label:'Viajes',key:'viajes_t'},{label:'Matrículas',key:'mats'},{label:'Fechas',key:'fechas_t'},{label:'Clientes',key:'cli'}],(H.canteras_repetidas||[]).map(r=>({...r,origen_nombre:r.origen_nombre||r.origen,viajes_t:j(r.viajes),mats:j(r.matriculas),fechas_t:j(r.fechas),cli:j(r.clientes)})));
 html+=hzBloque('tac','Localizador que no lee el tacógrafo','Viajes medidos cuyo tacógrafo se descartó: el localizador no recibe la tarjeta o su actividad no refleja la conducción. Si el tacógrafo es analógico (columna del ERP) el localizador nunca podrá leerlo; si es digital y casi todo se descarta, la tarjeta SÍ está en la unidad (comprobado) y es la instalación de Movertis la que no lee el tacógrafo: avisar a Movertis.',[{label:'Matrícula',key:'matricula'},{label:'Clase (ERP)',key:'clase'},{label:'Tacógrafo (ERP)',key:'tacografo_tipo'},numberCol('Viajes medidos','viajes_medidos'),numberCol('Con tacógrafo','con_tacografo'),numberCol('Sin tarjeta','sin_tarjeta_en_ranura_1'),numberCol('No refleja la conducción','tacografo_no_refleja_la_conduccion'),percentCol('% descartado','pct')],(H.tacografo_por_camion||[]).map(r=>({...r,clase:r.clase||'—',tacografo_tipo:r.tacografo_tipo||'(sin apuntar)',pct:(r.pct_descartado||0)/100})),false);
 html+=hzBloque('cho','Chofer del tacógrafo distinto al del albarán','La tarjeta que conducía lleva un código de chofer que no es el del albarán. Casi siempre es la misma persona con dos fichas en GesRuta (dos códigos); si no, el albarán está a nombre de otro. Unificar las fichas.',[{label:'Empresa',key:'empresa'},{label:'Chofer tacógrafo',key:'chofer_tacografo'},{label:'Chofer albarán',key:'chofer_gesruta'},numberCol('Viajes','viajes'),{label:'Matrículas',key:'mats'},{label:'Desde',key:'desde'},{label:'Hasta',key:'hasta'}],(H.chofer_discrepante||[]).map(r=>({...r,mats:j(r.matriculas)})));
 html+=hzBloque('coh','Coherencia de cada localizador con sus albaranes','Porcentaje de viajes cortos de cada unidad cuyo ciclo se corta por la geografía del albarán (la planta o cantera de origen, el destino). Si una unidad baja del 60 %, su localizador puede estar montado en otro camión o sus cargas no dejan parada: revisar.',[{label:'Matrícula',key:'matricula'},{label:'Tipo',key:'tipo'},numberCol('Viajes con traza','viajes_con_traza'),percentCol('Geografía del albarán','pct'),numberCol('Sin ciclo','sin_ciclo'),numberCol('Otra planta','otra_planta')],(H.coherencia_por_unidad||[]).map(r=>({...r,pct:(r.pct_geografia_albaran||0)/100})));
 html+=hzBloque('par','Dónde para la flota y cuánto (cargas, descargas y esperas)','Paradas de 5 minutos o más de los viajes medidos, por lo que hacía el camión y el lugar (lugar conocido más cercano; en blanco si no lo hay). Los lugares con más minutos acumulados son donde se pierde el tiempo: cargaderos lentos, obras que hacen esperar.',[{label:'Qué hacía',key:'rolT'},{label:'Lugar',key:'lug'},numberCol('Paradas','paradas'),numberCol('Minutos','minutos'),numberCol('Media (min)','media_min',1),numberCol('Mediana (min)','mediana_min',1),numberCol('p90 (min)','p90_min',1),numberCol('Desv. típica','desv_min',1),numberCol('Camiones','camiones')],(H.paradas_por_lugar||[]).map(r=>({...r,rolT:HZ_ROL[r.rol]||r.rol,lug:r.lugar_nombre||r.lugar||'(lugar no conocido)'})),false,200);
 html+=hzBloque('esp','Espera por cliente','Minutos parado o esperando (todo lo que no es conducir) por viaje medido, por cliente. Es el tiempo que el camión trabaja sin moverse: base para hablar de esperas y de precios.',[{label:'Cliente',key:'cliente'},numberCol('Viajes medidos','viajes_medidos'),numberCol('Min espera total','min_espera_total'),numberCol('Espera media (min)','min_espera_medio',1),numberCol('Espera mediana (min)','min_espera_mediana',1),numberCol('Espera p90 (min)','min_espera_p90',1),numberCol('Desv. típica','min_espera_desv',1),numberCol('Conducción media (min)','min_conduccion_medio',1),numberCol('Conducción mediana (min)','min_conduccion_mediana',1)],H.espera_por_cliente||[]);
 html+=hzBloque('sl','Camiones con albaranes y sin traza (y por qué)','Matrículas con albaranes en GesRuta de las que no hay traza en esas fechas. El motivo lo dice: «camion_ajeno» = subcontratado (su coste va por la factura del subcontratista); «sin_traza_en_esas_fechas_locatel» = unidad de LOCATEL pendiente de bajar su histórico (no es que no lleve localizador); «pendiente_bajada» = unidad de Movertis en cola; «sin_telemetria_o_pendiente_locatel» = sin traza de ninguna fuente todavía.',[{label:'Matrícula',key:'matricula'},numberCol('Viajes','viajes'),{label:'Motivo',key:'motivo'},{label:'Empresas',key:'emp'},{label:'Desde',key:'desde'},{label:'Hasta',key:'hasta'}],(H.sin_localizador||[]).map(r=>({...r,emp:j(r.empresas)})));
 html+=hzBloque('fc','Tickets hechos en otra fecha','Albaranes cuya fecha en GesRuta no es la del viaje real: la traza dice cuándo se hizo. El informe usa la fecha real.',[{label:'Empresa',key:'empresa'},{label:'Viaje',key:'viaje'},{label:'Alb. cantera',key:'cantera'},{label:'Matrícula',key:'matricula'},{label:'Fecha GesRuta',key:'fecha_gesruta'},{label:'Fecha real',key:'fecha_real'}],H.fecha_corregida||[]);
 html+=hzBloque('lp','Viajes largos pendientes de traza contigua','Viajes de largo recorrido que aún no se han podido medir de carga a descarga porque falta la traza de los días contiguos; se miden solos cuando entra.',[{label:'Matrícula',key:'matricula'},numberCol('Viajes','viajes')],H.largos_pendientes_de_traza||[]);
 html+=hzBloque('pl','Plantas de hormigón aprendidas de la traza','Dónde está de verdad cada planta (aprendido de dónde cargan y duermen las hormigoneras). El maestro y la geocodificación apuntaban a veces a la cantera o al centro del pueblo.',[{label:'Código',key:'cod'},{label:'Nombre',key:'nombre'},numberCol('Lat','lat',5),numberCol('Lon','lon',5),numberCol('Días',
 'dias'),numberCol('Visitas','visitas')],Object.entries(H.plantas_aprendidas||{}).map(([k,v])=>({cod:k,...v})));
 return html;
}
// Detalle de un viaje (fila desplegada de «Margen por viaje»): lo que sabemos de ese viaje concreto, sin inventar nada.
function tripDetail(t){
 const row=(k,v)=>v==null||v===''||v==='—'?'':`<div><span class="k">${k}</span><span class="v">${v}</span></div>`;
 const grp=s=>`<div class="grp">${s}</div>`;
 const lugar=(p,l)=>esc(p)+(l&&!/^\(/.test(l)&&norm(l)!==norm(p)?` <small>(${esc(l)})</small>`:'');
 const dur=(a,b)=>{if(!a||!b)return null;const [h1,m1]=a.split(':').map(Number),[h2,m2]=b.split(':').map(Number);let d=(h2*60+m2)-(h1*60+m1);if(d<0)d+=1440;return d;};
 const lab={combustible:'Combustible (por litros)',personal:'Personal (por horas)',flota:'Flota: reparaciones, seguros, amortización… (por km)',indirectos:'Gastos generales (por ingreso)',aridos:'Compra de áridos (por cliente)',subcontrata:'Subcontratista (factura real)'};
 const costes=Object.entries(t.desg||{}).filter(([,v])=>Math.abs(v)>=0.5).map(([k,v])=>row(lab[k]||k,eur(v))).join('');
 const l100=t.lit&&t.km?nf(t.lit/t.km*100,1)+' l/100 km':null;
 const carga=(t.m3?nf(t.m3)+' m³':'')+(t.t?(t.m3?' · ':'')+nf(t.t)+' t':'');
 const tCar=dur(t.tCarga,t.tCargaFin),tDes=dur(t.tDesc,t.tDescFin);
 const fuenteMin=t.minFuente==='tacografo'?'tacógrafo':(t.minFuente==='traza'?(t.coherente===false?'movimiento de la traza (el tacógrafo del localizador no vale)':'movimiento de la traza'):null);
 const tipo=({banera:'áridos (bañera)',hormigonera:'hormigón (hormigonera)',nacional:'nacional'})[t.tipo]||t.tipo||(t.horm?'hormigón':null);
 return `<div class="tripdetail">
  ${grp(`${esc(t.emp||'')}${t.viaje?' · viaje GesRuta '+esc(t.viaje):''}${t.cantera?' · albarán de cantera '+esc(t.cantera):''} · ${esc(t.cliente||'')}${tipo?' · '+esc(tipo):''}${t.larga?' · largo recorrido':''}${t.sub?' · subcontratado':''}${t.espejo?' · espejo intercompañía (medido en la otra casa)':''}`)}
  ${row('Lugar de carga',lugar(t.carga,t.locO))}${row('Lugar de descarga',lugar(t.descarga,t.locD))}
  ${row('Fecha',esc(t.dia||'')+(t.fechaGes&&t.fechaGes!==t.dia?' <small>(en el albarán: '+esc(t.fechaGes)+')</small>':''))}
  ${row('Matrícula',esc(t.mat))}
  ${row('Chofer',(t.chofer?'tacógrafo '+esc(t.chofer):'')+(t.choferGes?(t.chofer?' · ':'')+'albarán '+esc(t.choferGes):'')+(t.choferOk===false?' <small>(no coinciden)</small>':''))}
  ${grp('Tiempos (hora de Madrid, del localizador)')}
  ${row('Jornada del camión',t.jIni?esc(t.jIni)+' → '+esc(t.jFin||'?')+(t.nocturna?' (cruza la medianoche)':''):null)}
  ${row('Viaje',t.tini?esc(t.tini)+' → '+esc(t.tfin||'?')+(t.orden?' · nº '+t.orden+(t.viajesDia?' de '+t.viajesDia:'')+' del día':''):null)}
  ${row('Carga: llega → sale',t.tCarga?esc(t.tCarga)+' → '+esc(t.tCargaFin||'?')+(tCar!=null?' · '+nf(tCar)+' min cargando':''):null)}
  ${row('Descarga: llega → sale',t.tDesc?esc(t.tDesc)+' → '+esc(t.tDescFin||'?')+(tDes!=null?' · '+nf(tDes)+' min descargando':'')+(t.obraMin!=null?' · en obra '+nf(t.obraMin)+' min':''):null)}
  ${row('Duración',t.horas!=null?nf(t.horas,1)+' h de trabajo'+(t.transc!=null&&Math.abs(t.transc-t.horas*60)>5?' · '+nf(t.transc)+' min transcurridos (con descansos)':''):null)}
  ${row('Conductor',t.cond!=null?nf(t.cond)+' min conduciendo · '+nf(t.espera)+' min parado o esperando'+(t.otros!=null?' · otros trabajos '+nf(t.otros):'')+(t.disp!=null?' · disponible '+nf(t.disp):'')+(t.desc!=null?' · descanso '+nf(t.desc):'')+(t.sinDato?' · sin dato '+nf(t.sinDato):'')+(fuenteMin?' <small>(fuente: '+fuenteMin+')</small>':''):null)}
  ${grp('Kilómetros y combustible')}
  ${row('Km del localizador',t.km?nf(t.km)+' km'+(t.kmCarg!=null?' · cargado '+nf(t.kmCarg)+' · en vacío '+nf(t.kmVac):'')+(t.kmFuente?' <small>('+esc(t.kmFuente==='can_mileage'?'contador CAN del camión':t.kmFuente)+')</small>':''):null)}
  ${row('Km del albarán',t.kmAlb?nf(t.kmAlb)+' km':null)}${row('Distancia origen–destino',t.distOd!=null?nf(t.distOd,1)+' km en línea recta':null)}
  ${row('Combustible',t.lit?nf(t.lit,1)+' L'+(l100?' · '+l100:'')+(t.litC!=null?' · cargado '+nf(t.litC,1)+' L · en vacío '+nf(t.litV||0,1)+' L':'')+(t.litRaw!=null&&t.litCal!=null&&Math.abs(t.litRaw-t.litCal)>0.5?' <small>(contador '+nf(t.litRaw,1)+' L · calibrado '+nf(t.litCal,1)+' L)</small>':''):null)}
  ${grp('Carga y dinero')}
  ${row('Carga transportada',carga)}
  ${row('Resultado','ingreso '+eur(t.ingreso)+' − coste real '+eur(t.coste)+' = <b class="'+(t.margen>=0?'pos':'neg')+'">'+eur(t.margen)+'</b> ('+pcm(t.margenPct)+')')}
  ${costes}
  ${grp('Fiabilidad de la medida')}
  ${row('Medida',esc(t.fiab)+(t.metodo?' · método '+esc(t.metodo)+(t.conf?' · confianza '+esc(t.conf):''):'')+(t.motivo?' · '+esc(t.motivo):'')+(t.costeEstimado?' · <small>coste estimado: el mes aún no está cerrado en contabilidad (coeficientes del último mes cerrado)</small>':''))}
  ${t.paradas&&t.paradas.length?`<div class="grp">Paradas y esperas del viaje (≥ 5 min): ${t.paradas.map(p=>`<span class="stop ${esc(p.rol)}">${esc(p.t)} · ${nf(p.min)} min · ${esc(p.lugar||'lugar no conocido')} <small>${({carga:'cargando',descarga:'descargando',espera:'espera',fuera:'fuera de viaje'})[p.rol]||''}</small></span>`).join('')}</div>`:''}
  ${t.mapaKey?`<div><span class="k">Mapa del día</span><a class="v noprint" href="dias/${encodeURIComponent(t.mapaKey)}.html${t.orden?'#v='+t.orden:''}" target="_blank" rel="noopener">ver la traza, las paradas y las esperas ↗</a></div>`:''}
 </div>`;
}
let _map=null,_mapLayer=null,_mapMetric='viajes',_mapStyle='carreteras',_tileLayers=[];
const ESRI='https://server.arcgisonline.com/ArcGIS/rest/services/';
// Basemaps de Esri SIN CLAVE: funcionan al abrir el informe como archivo local (OSM da 403 sin Referer; CARTO estampa marca de agua sin API key).
// «satelite» es HÍBRIDO: imagen aérea + capas transparentes de carreteras y rótulos encima.
const MAP_STYLES={
 carreteras:[{url:ESRI+'World_Street_Map/MapServer/tile/{z}/{y}/{x}',opt:{maxZoom:19,attribution:'© Esri · © OpenStreetMap'}}],
 satelite:[
  {url:ESRI+'World_Imagery/MapServer/tile/{z}/{y}/{x}',opt:{maxZoom:19,attribution:'© Esri · Maxar · Earthstar Geographics'}},
  {url:ESRI+'Reference/World_Transportation/MapServer/tile/{z}/{y}/{x}',opt:{maxZoom:19}},
  {url:ESRI+'Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}',opt:{maxZoom:19}}
 ]
};
function setMapStyle(style){
 if(!_map)return;_mapStyle=MAP_STYLES[style]?style:'carreteras';
 _tileLayers.forEach(l=>{try{_map.removeLayer(l);}catch(e){}});_tileLayers=[];
 MAP_STYLES[_mapStyle].forEach((p,idx)=>{
  const t=L.tileLayer(p.url,p.opt).addTo(_map);_tileLayers.push(t);
  if(_mapStyle==='carreteras'&&idx===0){let errs=0;t.on('tileerror',()=>{errs++;if(errs>4){try{_map.removeLayer(t);}catch(e){}_tileLayers[0]=L.tileLayer(ESRI+'World_Topo_Map/MapServer/tile/{z}/{y}/{x}',{maxZoom:19,attribution:'© Esri · © OpenStreetMap'}).addTo(_map);}});}
 });
}
const mapNorm=s=>(s||'').normalize('NFD').replace(/[̀-ͯ]/g,'').toUpperCase();
const mapGal=p=>['A CORUNA','LUGO','PONTEVEDRA','OURENSE'].includes(mapNorm(p.prov));
function mapa(){
 const nv=M.zonasGeo(state);
 if(!nv||!nv.puntos.length)return panel('Mapa de zonas','Dónde trabaja la flota.','<div class="info">No hay puntos con coordenada del localizador en el periodo elegido.</div>');
 return panel('Mapa de zonas','Dónde trabaja la flota, por los puntos GPS reales donde para (planta, cantera u obra), sobre el mapa base. Rueda para acercar/alejar, arrastra para mover, pincha un punto para ver sus datos.',
  `<div class="mapmetric">Vista: ${['carreteras','satelite'].map(s=>`<button class="segbtn${s===_mapStyle?' on':''}" data-ms="${s}">${({carreteras:'Carreteras',satelite:'Satélite'})[s]}</button>`).join('')}</div>
  <div class="mapmetric">Tamaño de cada punto por: ${['viajes','t','m3','ing'].map(m=>`<button class="segbtn${m===_mapMetric?' on':''}" data-mm="${m}">${({viajes:'Viajes',t:'Toneladas',m3:'m³',ing:'Ingreso'})[m]}</button>`).join('')}</div>
  <div id="mapContainer" class="mapbox"></div>
  <p class="sub" id="mapInfo">${nf(nv.puntos.length)} puntos en el periodo elegido. Pincha uno para ver sus datos.</p>`);
}
function mapaRender(){
 const el=$('mapContainer');if(!el)return;
 if(typeof L==='undefined'){el.innerHTML='<div class="info" style="padding:16px">No se pudo cargar el mapa de OpenStreetMap (¿sin conexión a internet?). Los datos de los puntos están, pero el mapa de fondo necesita internet.</div>';return;}
 const nv=M.zonasGeo(state);if(!nv)return;
 if(_map){try{_map.remove();}catch(e){}_map=null;_mapLayer=null;}
 _map=L.map(el).setView([42.9,-8.1],7);
 setMapStyle(_mapStyle);   // Esri sin clave; «satelite» = híbrido (aérea + carreteras + rótulos). Ver MAP_STYLES.
 drawMapPoints(nv.puntos);
 document.querySelectorAll('.segbtn[data-ms]').forEach(b=>b.onclick=()=>{document.querySelectorAll('.segbtn[data-ms]').forEach(x=>x.classList.remove('on'));b.classList.add('on');setMapStyle(b.dataset.ms);const z=M.zonasGeo(state);if(z)drawMapPoints(z.puntos);});
 document.querySelectorAll('.segbtn[data-mm]').forEach(b=>b.onclick=()=>{document.querySelectorAll('.segbtn[data-mm]').forEach(x=>x.classList.remove('on'));b.classList.add('on');_mapMetric=b.dataset.mm;const z=M.zonasGeo(state);if(z)drawMapPoints(z.puntos);});
}
function drawMapPoints(pts){
 if(!_map)return;
 if(_mapLayer)_map.removeLayer(_mapLayer);
 _mapLayer=L.layerGroup().addTo(_map);
 const mx=Math.max(...pts.map(p=>p[_mapMetric]||0))||1,bounds=[];
 const sat=_mapStyle==='satelite';
 for(const p of pts){const v=p[_mapMetric]||0;if(v<=0)continue;const r=6+26*Math.sqrt(v/mx),isGal=mapGal(p);
  const c=L.circleMarker([p.lat,p.lon],{radius:r,color:sat?'#ffffff':'#12233b',weight:sat?1.5:1,fillColor:isGal?'#2563eb':(sat?'#e0862f':'#8a5a2b'),fillOpacity:sat?.72:.5});
  c.bindTooltip(`<b>${esc(p.name)}</b><br>${esc(p.loc)} (${esc(p.prov)})<br>viajes ${nf(p.viajes)} · t ${nf(p.t)} · m³ ${nf(p.m3)}<br>ingreso ${eur(p.ing)}`,{sticky:true});
  c.on('click',()=>{const mi=$('mapInfo');if(mi)mi.innerHTML=`<b>${esc(p.name)}</b> — ${esc(p.loc)} (${esc(p.prov)}): viajes ${nf(p.viajes)}, toneladas ${nf(p.t)}, m³ ${nf(p.m3)}, ingreso ${eur(p.ing)} · sale ${nf(p.orig)} / llega ${nf(p.dest)}`;});
  c.addTo(_mapLayer);bounds.push([p.lat,p.lon]);}
 if(bounds.length)_map.fitBounds(bounds,{padding:[30,30],maxZoom:11});
}
// ---- Informe por CLIENTE: lista gana/pierde + ficha (KPIs, comparación de periodos, operaciones agrupables) ----
let _cliSel=null,_cliGroupBy='mes',_cliGroups=[];
const pcm=x=>x==null?'—':(x>=0?'+':'')+nf(x*100,1)+' %';
const CLI_THEAD='<thead><tr><th>Fecha</th><th class="num">Nº</th><th>Inicio</th><th>Fin</th><th>Lugar de carga</th><th>Lugar de descarga</th><th>Matrícula</th><th>Chofer</th><th class="num">m³</th><th class="num">t</th><th class="num">km</th><th class="num">Km carg.</th><th class="num">Km vacío</th><th class="num">Horas</th><th class="num">Min. cond.</th><th class="num">Min. espera</th><th class="num">Ingreso</th><th class="num">Coste</th><th class="num">Margen</th><th class="num">%</th><th>Fiab.</th><th>Método</th><th>Conf.</th><th class="noprint">Mapa</th></tr></thead>';
const cliTrow=t=>`<tr><td>${t.dia||t.mes}</td><td class="num">${t.orden||'—'}</td><td>${esc(t.tini||'—')}</td><td>${esc(t.tfin||'—')}</td><td>${esc(t.carga||t.ruta)}</td><td>${esc(t.descarga||'')}</td><td>${esc(t.mat||'—')}</td><td>${esc(t.chofer||'—')}</td><td class="num">${t.m3||'—'}</td><td class="num">${t.t||'—'}</td><td class="num">${nf(t.km)}</td><td class="num">${t.kmCarg==null?'—':nf(t.kmCarg)}</td><td class="num">${t.kmVac==null?'—':nf(t.kmVac)}</td><td class="num">${t.horas==null?'—':t.horas}</td><td class="num">${t.cond==null?'—':t.cond}</td><td class="num">${t.espera==null?'—':t.espera}</td><td class="num">${eur(t.ingreso)}</td><td class="num">${eur(t.coste)}</td><td class="num ${t.margen>=0?'pos':'neg'}" style="font-weight:600">${eur(t.margen)}</td><td class="num ${t.margen>=0?'pos':'neg'}">${pcm(t.margenPct)}</td><td>${esc(t.fiab||'')}</td><td>${esc(t.metodo||'—')}</td><td>${esc(t.conf||'—')}</td><td class="noprint">${t.tini&&t.mat&&t.mat!=='—'?`<a href="dias/${encodeURIComponent(t.mat)}_${esc(t.dia)}.html" target="_blank" rel="noopener">ver día</a>`:'—'}</td></tr>`;
function cliOpsHtml(trips){
 if(_cliGroupBy==='none'){const shown=trips.slice(0,400);return `<div class="cli-tablewrap"><table class="cli-optable">${CLI_THEAD}<tbody>${shown.map(cliTrow).join('')}</tbody></table></div>${trips.length>400?`<p class="sub">Mostrando 400 de ${nf(trips.length)} viajes. Agrupa para verlos todos organizados por grupos.</p>`:''}`;}
 const gk=t=>({mes:(t.dia||t.mes||'').slice(0,7),carga:t.carga,descarga:t.descarga,ruta:t.ruta,mat:t.mat})[_cliGroupBy]||'—';
 const m=new Map();for(const t of trips){const k=gk(t);let g=m.get(k);if(!g){g={key:k,trips:[],ing:0,cost:0};m.set(k,g);}g.trips.push(t);g.ing+=t.ingreso;g.cost+=t.coste;}
 _cliGroups=[...m.values()].sort((a,b)=>_cliGroupBy==='mes'?(a.key<b.key?-1:1):(b.ing-a.ing));
 return _cliGroups.map((g,i)=>{const mg=g.ing-g.cost,p=g.ing?mg/g.ing:0;return `<div class="cli-grp"><div class="cli-grphead" data-gi="${i}"><span class="caret">▶</span><b>${esc(g.key)}</b><span class="cli-grpsub">${nf(g.trips.length)} viajes · ${eur(g.ing)} · <span class="${mg>=0?'pos':'neg'}">${eur(mg)} (${pcm(p)})</span></span></div><div class="cli-grpbody" hidden></div></div>`;}).join('');
}
function clienteDet(){
 const nv=M.netaView(state);
 if(!nv||!nv.byClient.length)return panel('Informe por cliente','','<div class="info">No hay actividad de GesRuta en el periodo elegido.</div>');
 const list=nv.byClient.filter(c=>c.ingreso>0);
 if(!_cliSel||!list.find(c=>c.key===_cliSel))_cliSel=list[0]&&list[0].key;
 const c=list.find(x=>x.key===_cliSel)||list[0];if(!c)return panel('Informe por cliente','','<div class="info">No hay clientes en el periodo.</div>');
 const cr=comparisonRange(),nvB=cr&&cr.valid?M.netaView({...state,from:cr.from,to:cr.to}):null,cB=nvB&&nvB.byClient.find(x=>x.key===_cliSel);
 const trips=M.netaTrips(state).filter(t=>t.cliente===_cliSel),gana=c.margen>=0;
 const listHtml=list.map(x=>`<div class="cli-row${x.key===_cliSel?' sel':''}" data-cli="${esc(x.key)}"><span>${esc(x.key)}</span><span class="${x.margen>=0?'pos':'neg'}" style="font-weight:700;white-space:nowrap">${pcm(x.margenPct)}</span></div>`).join('');
 const cmpHtml=nvB?`<div class="cli-cmp"><div class="cli-box"><div class="t">${date(state.from)} – ${date(state.to)}</div>ingreso ${eur(c.ingreso)} · margen <b class="${gana?'pos':'neg'}">${eur(c.margen)} (${pcm(c.margenPct)})</b> · ${nf(c.viajes)} viajes</div><div class="cli-box"><div class="t">${date(cr.from)} – ${date(cr.to)}</div>${cB?`ingreso ${eur(cB.ingreso)} · margen <b class="${cB.margen>=0?'pos':'neg'}">${eur(cB.margen)} (${pcm(cB.margenPct)})</b> · ${nf(cB.viajes)} viajes`:'<span class="sub">este cliente no tuvo actividad en la comparación</span>'}</div></div>`:'<p class="sub">Elige «Comparar con» en la barra de arriba (año anterior, periodo anterior o fechas a tu gusto) para contrastar dos periodos.</p>';
 return `<div class="cli-grid">
 <div><div class="cli-search"><input id="cliQ" placeholder="Buscar cliente…"></div><div class="cli-list" id="cliList">${listHtml}</div></div>
 <div id="cliDetalle"><div class="cli-head"><h2>${esc(c.key)}</h2><button class="textbtn noprint" id="cliPrint">🖨 Imprimir ficha</button><span class="badge-gp ${gana?'g':'p'}">${gana?'GANA':'PIERDE'} ${eur(c.margen)}</span></div>
 <div class="kpi-grid cli-kpis" style="grid-template-columns:repeat(4,1fr)"><article class="card"><span class="label">Ingreso facturado</span><div class="value">${eur(c.ingreso)}</div></article><article class="card"><span class="label">Coste real</span><div class="value">${eur(c.coste)}</div></article><article class="card"><span class="label">Margen</span><div class="value ${gana?'pos':'neg'}">${pcm(c.margenPct)}</div></article><article class="card"><span class="label">Fiabilidad</span><div class="value">${Math.round(c.fiable*100)} %</div></article></div>
 <div class="tripdetail" style="margin:6px 0 10px">${estadViajes(trips,'Estadística de sus viajes: media, mediana y dispersión')}</div>
 <h3 class="cli-h3">Comparar entre fechas</h3>${cmpHtml}
 <div class="cli-opshead"><b>Operaciones (${nf(trips.length)} viajes)</b> — agrupar por: <select id="cliGroup"><option value="mes"${_cliGroupBy==='mes'?' selected':''}>Mes</option><option value="carga"${_cliGroupBy==='carga'?' selected':''}>Lugar de carga</option><option value="descarga"${_cliGroupBy==='descarga'?' selected':''}>Lugar de descarga</option><option value="ruta"${_cliGroupBy==='ruta'?' selected':''}>Ruta</option><option value="mat"${_cliGroupBy==='mat'?' selected':''}>Matrícula</option><option value="none"${_cliGroupBy==='none'?' selected':''}>Sin agrupar</option></select> <span class="sub">pincha un grupo para desplegar sus viajes</span></div>
 <div id="cliOps">${cliOpsHtml(trips)}</div></div></div>`;
}
function wireCliGroups(){document.querySelectorAll('#cliOps .cli-grphead').forEach(h=>h.onclick=()=>{const b=h.nextElementSibling,gi=+h.dataset.gi;if(b.hidden&&!b.dataset.filled){b.innerHTML=`<div class="cli-tablewrap"><table class="cli-optable">${CLI_THEAD}<tbody>${_cliGroups[gi].trips.map(cliTrow).join('')}</tbody></table></div>`;b.dataset.filled='1';}b.hidden=!b.hidden;h.classList.toggle('open',!b.hidden);});}
function clienteDetWire(){
 const q=$('cliQ');if(q)q.oninput=()=>{const ws=norm(q.value).split(/\s+/).filter(Boolean);document.querySelectorAll('#cliList .cli-row').forEach(r=>{const h=norm(r.dataset.cli);r.hidden=!ws.every(w=>h.includes(w));});};
 document.querySelectorAll('#cliList .cli-row').forEach(r=>r.onclick=()=>{_cliSel=r.dataset.cli;renderContent();const el=$('content');if(el)el.scrollIntoView({block:'start'});});
 const g=$('cliGroup');if(g)g.onchange=()=>{_cliGroupBy=g.value;$('cliOps').innerHTML=cliOpsHtml(M.netaTrips(state).filter(t=>t.cliente===_cliSel));wireCliGroups();};
 const pr=$('cliPrint');if(pr)pr.onclick=()=>window.print();
 wireCliGroups();
}
// De cada 100 € de gasto contable: combustible, personal (conductores / estructura), vehículos, compras y estructura general.
// Misma contabilidad y categorías que el resto del informe (config\cuentas-contables.json); el reparto conductor/estructura
// del personal sale de la nómina por secciones (oficina y taller = estructura).
const ESTR_FLOTA=['amortizacion','reparaciones','seguros','repuestos','alquileres','peajes','neumaticos'],ESTR_COMPRAS=['aridos','subcontratacion'];
// Las partes del gasto (combustible, personal conductores / estructura, vehículos, compras, estructura general) de una
// lectura de contabilidad. Sirve para el panel del periodo y para el detalle de cada mes.
function estructuraPartes(lv,f){
 const amt=id=>lv.expenseCategories.filter(c=>c.id===id).reduce((s,c)=>s+c.amount,0);
 const tot=lv.expenses,comb=amt('combustible'),pers=amt('personal')+amt('dietas'),flota=ESTR_FLOTA.reduce((s,id)=>s+amt(id),0),compras=ESTR_COMPRAS.reduce((s,id)=>s+amt(id),0);
 const known=new Set(['combustible','personal','dietas','impuesto_sociedades',...ESTR_FLOTA,...ESTR_COMPRAS]),isoc=amt('impuesto_sociedades');
 const gen=lv.expenseCategories.filter(c=>!known.has(c.id)).reduce((s,c)=>s+c.amount,0);
 const pt=M.personnelByTramo?M.personnelByTramo(f):null,fe=pt&&pt.total?pt.structureCost/pt.total:null;
 const persEst=fe!=null?pers*fe:0,persCond=pers-persEst;
 const partes=[['Combustible',comb,'#d97706'],[fe!=null?'Personal: conductores':'Personal',persCond,'#2563eb']]
  .concat(fe!=null?[['Personal de estructura (oficina, taller)',persEst,'#7c3aed']]:[])
  .concat([['Vehículos: amortización, reparaciones, repuestos y neumáticos, seguros, peajes, renting',flota,'#0e9488'],['Compras: áridos y subcontratación',compras,'#64748b'],['Estructura general: otros servicios, tributos, financieros, otras compras, suministros, extraordinarios',gen,'#c1394b']]).concat(isoc?[['Impuesto de sociedades (sobre el resultado; no es coste de explotación)',isoc,'#94a3b8']]:[]);
 return {partes,tot,fe,estrTot:gen+persEst,aridos:amt('aridos'),subcontratacion:amt('subcontratacion'),ventas:lv.incomeCategories.filter(c=>c.id==='ventas').reduce((s,c)=>s+c.amount,0)};
}
function estructuraPanel(){
 const lv=ledgerCtx.lv;if(!lv||!lv.expenses)return '';
 const E=estructuraPartes(lv,state),{partes,tot,fe,estrTot}=E;
 const bar=partes.map(([l,v,c])=>`<span style="width:${(100*Math.max(0,v)/tot).toFixed(2)}%;background:${c}" title="${esc(l)}: ${pct(v/tot)}"></span>`).join('');
 const rows=partes.map(([l,v,c])=>`<tr><td><i class="sw" style="background:${c}"></i>${esc(l)}</td><td class="num">${eur(v)}</td><td class="num">${pct(v/tot)}</td><td class="num">${pct(lv.income?v/lv.income:null)}</td></tr>`).join('');
 return panel('De cada 100 € de gasto','Estructura del gasto real de la contabilidad en el periodo y sociedades elegidos'+(lv.consolidado?' (consolidado, sin la subcontratación entre Razo y Agetrans)':'')+'. <b>Coste de estructura</b> = estructura general + personal de oficina y taller: <b>'+pct(estrTot/tot)+'</b> del gasto, <b>'+pct(lv.income?estrTot/lv.income:null)+'</b> de los ingresos.'+(fe!=null?' El reparto conductores / estructura del personal aplica la proporción de la nómina por secciones ('+pct(fe)+' estructura).':''),`<div class="stackbar">${bar}</div><div class="tablewrap" style="max-height:none"><table class="estr"><thead><tr><th class="plain">Naturaleza del gasto</th><th class="plain num">Importe</th><th class="plain num">% del gasto</th><th class="plain num">% de ingresos</th></tr></thead><tbody>${rows}<tr class="total"><td>Gasto total</td><td class="num">${eur(tot)}</td><td class="num">100 %</td><td class="num">${pct(lv.income?tot/lv.income:null)}</td></tr></tbody></table></div>`);
}
// ---- Detalle de un MES de «Resultado mes a mes»: naturalezas y cuentas, por sociedad, estructura, transporte sin el
// material y la operación del mes (viajes reales con el coste real repartido). Todo del mismo mes y sociedades elegidas.
const detRow=(k,v)=>v==null||v===''||v==='—'?'':`<div><span class="k">${k}</span><span class="v">${v}</span></div>`;
function monthDetail(r){
 const m=r.key,f={...state,from:m+'-01',to:monthEndOf(m)},lv=M.ledgerView(f);
 if(!lv||!lv.months.length)return '<div class="info">Este mes no tiene contabilidad cerrada.</div>';
 const br=M.bridge(f),rv=M.realView(state,'month'),op=rv&&rv.groups.find(g=>g.key===m),E=estructuraPartes(lv,f);
 const accs=(kind,cat)=>lv.accounts.filter(a=>a.kind===kind&&a.cat===cat);
 const catList=(cats,kind,tot)=>`<div class="ldg">${cats.map(c=>{const as=accs(kind,c.id);return `<details class="ldgc"><summary><span>${esc(c.label)}</span><small>${pct(tot?c.amount/tot:null)}</small><b>${eur(c.amount)}</b></summary>${as.map(a=>`<div class="ldga"><span><code>${esc(a.cuenta)}</code> ${esc(a.label||'')}</span><b>${eur(a.amount)}</b></div>`).join('')||'<div class="ldga"><span>sin detalle por cuenta</span></div>'}</details>`;}).join('')}<div class="ldgt"><span>Total</span><b>${eur(tot)}</b></div></div>`;
 const bar=E.partes.map(([l,v,c])=>`<span style="width:${(100*Math.max(0,v)/E.tot).toFixed(2)}%;background:${c}" title="${esc(l)}: ${pct(v/E.tot)}"></span>`).join('');
 const legend=E.partes.map(([l,v,c])=>`<span><i style="background:${c}"></i>${esc(l.split(':')[0])} ${pct(v/E.tot)}</span>`).join('');
 const ingT=lv.income-E.aridos,gastoT=lv.expenses-E.aridos;
 const soc=lv.byCompany.map(c=>`<b>${esc(c.key)}</b>: ingresos ${eur(c.income)} · gastos ${eur(c.expenses)} · resultado <b class="${c.result>=0?'pos':'neg'}">${eur(c.result)}</b> (${pcm(c.marginPct)})`).join(' &nbsp;·&nbsp; ');
 return `<div class="tripdetail">
  <div class="grp">${esc(monthName(m))}: ingresos ${eur(lv.income)} − gastos ${eur(lv.expenses)} = <b class="${lv.result>=0?'pos':'neg'}">${eur(lv.result)}</b> (${pcm(lv.marginPct)})${lv.consolidado?' · consolidado (sin intragrupo)':''}</div>
  <div style="grid-column:1/-1;font-size:13px">${soc}</div>
  <div class="grp">Transporte y servicios (sin el material)</div>
  ${detRow('Material que va dentro del precio (compra de áridos y productos)',eur(E.aridos))}
  ${detRow('Ingreso de transporte y servicios','<b>'+eur(ingT)+'</b> <small>(ingresos − material)</small>')}
  ${detRow('Gasto sin el material',eur(gastoT))}
  ${detRow('Margen sobre transporte',pcm(ingT?lv.result/ingT:null)+' <small>(el resultado no cambia: '+eur(lv.result)+')</small>')}
  ${E.ventas?detRow('Venta de productos (cuenta 700; no es transporte)',eur(E.ventas)):''}
  ${detRow('Subcontratación pagada',eur(E.subcontratacion))}
  <div class="grp">De cada 100 € de gasto del mes${E.fe!=null?' <small>(personal conductores / estructura según la nómina por secciones)</small>':''}</div>
  <div style="grid-column:1/-1"><div class="stackbar">${bar}</div><div class="legend">${legend}</div></div>
  <div class="grp">Contabilidad por naturaleza <small>(pincha una naturaleza para ver sus cuentas${lv.consolidado?'; el ajuste intragrupo se aplica a la naturaleza, no a cada cuenta':''})</small></div>
  <div class="ldg2" style="grid-column:1/-1"><div><h4>Ingresos</h4>${catList(lv.incomeCategories,'i',lv.income)}</div><div><h4>Gastos</h4>${catList(lv.expenseCategories,'g',lv.expenses)}</div></div>
  <div class="grp">Operación del mes</div>
  ${detRow('Facturas GesRuta del mes',eur(r.gesruta))}
  ${op?detRow('Viajes reales',nf(op.viajes)+' viajes · '+nf(op.dias)+' días · '+nf(op.matriculas)+' matrículas · '+nf(op.clientes)+' clientes'):''}
  ${op?detRow('Ingreso capturado en los viajes',eur(op.ingreso)+' <small>('+pct(lv.income?op.ingreso/lv.income:null)+' del ingreso contable; material '+eur(op.material)+')</small>'):''}
  ${op?detRow('Medido por el localizador',nf(op.km)+' km · '+nf(op.horas,1)+' h · '+nf(op.litros)+' L'+(op.l100?' · '+nf(op.l100,1)+' l/100 km':'')+' · '+pct(op.fiable)+' del ingreso con km y horas reales'):''}
  ${op&&rv.real?detRow('Coste real repartido a los viajes',eur(op.coste)+' → margen neto <b class="'+(op.margen>=0?'pos':'neg')+'">'+eur(op.margen)+'</b> ('+pcm(op.margenPct)+')'):''}
  ${br?detRow('Lo que captan los partes de Access',pct(br.coverage)+' del gasto real ('+eur(br.totalParts)+'); faltan '+eur(br.missing)+' <small>(subcontratación, áridos, generales)</small>'):''}
  ${estadViajes(M.netaTrips(state).filter(t=>t.mes===m),'Estadística de los viajes del mes: media, mediana y dispersión')}
 </div>`;
}
// ---- Vehículos y Clientes sobre el motor REAL (mismo reparto que «Margen por viaje»), con detalle al pinchar la fila.
const plateFmt=p=>/^\d{4}[A-Z]{3}$/.test(p||'')?p.slice(0,4)+'-'+p.slice(4):(p||'');
const pkey=s=>String(s||'').toUpperCase().replace(/[^A-Z0-9]/g,'');
const TIPO_LBL={banera:'áridos (bañera)',hormigonera:'hormigón',nacional:'nacional',subcontratado:'subcontratado'};
const tipoLabel=t=>TIPO_LBL[t]||t||'—';
let _rvCur=null;
// ---- ESTADÍSTICA de los viajes (Roberto 23/09: «los km son un abanico… media y mediana… usa tus habilidades estadísticas para
// darme información y poder hacer los cálculos»). Para cada dato que resume muchos viajes: n, media, mediana, desviación típica,
// CV, p10, Q1, Q3, p90, mín, máx, atípicos (fuera de 1,5 × IQR), IC 95 % de la media e histograma; y rectas y = a + b·km con R².
function statsDe(xs,bins=8){
 const v=xs.filter(x=>x!=null&&Number.isFinite(x)).sort((a,b)=>a-b),n=v.length;if(!n)return null;
 const q=p=>{const i=p*(n-1),lo=Math.floor(i),hi=Math.min(n-1,lo+1);return v[lo]+(v[hi]-v[lo])*(i-lo);};
 const media=v.reduce((s,x)=>s+x,0)/n,sd=n>1?Math.sqrt(v.reduce((s,x)=>s+(x-media)**2,0)/(n-1)):0,q1=q(.25),q3=q(.75),iqr=q3-q1,ee=n>1?sd/Math.sqrt(n):0;
 const out={n,media,mediana:q(.5),sd,cv:media?sd/Math.abs(media):null,p10:q(.1),q1,q3,p90:q(.9),min:v[0],max:v[n-1],atip:v.filter(x=>x<q1-1.5*iqr||x>q3+1.5*iqr).length,ic:[media-1.96*ee,media+1.96*ee],hist:[]};
 if(n>=5){let lo=q(.01),hi=q(.99);if(hi<=lo)hi=lo+1;const w=(hi-lo)/bins,cnt=new Array(bins).fill(0);for(const x of v){const i=x<hi?Math.floor((x-lo)/w):bins-1;cnt[Math.max(0,Math.min(bins-1,i))]++;}out.hist=cnt.map((c,i)=>[lo+i*w,lo+(i+1)*w,c]);}
 return out;
}
// Recta y = a + b·x por mínimos cuadrados, ROBUSTA: con 20 pares o más se apartan los viajes a más de 3 errores típicos de
// la primera recta (lecturas raras del sensor, un día de avería) y se reajusta; se dice cuántos se apartaron.
function ajusteLineal(p){const n=p.length,mx=p.reduce((s,[x])=>s+x,0)/n,my=p.reduce((s,[,y])=>s+y,0)/n;let sxx=0,sxy=0,syy=0;for(const [x,y] of p){sxx+=(x-mx)**2;sxy+=(x-mx)*(y-my);syy+=(y-my)**2;}
 if(!(sxx>0)||!(syy>0))return null;const b=sxy/sxx,a=my-b*mx;let ssr=0;for(const [x,y] of p)ssr+=(y-(a+b*x))**2;return {a,b,r2:Math.max(0,1-ssr/syy),n,mx,my,se:n>2?Math.sqrt(ssr/(n-2)):0};}
function regresion(pares){
 const p=pares.filter(([x,y])=>x!=null&&y!=null&&Number.isFinite(x)&&Number.isFinite(y)&&x>0);if(p.length<8)return null;
 let f=ajusteLineal(p);if(!f)return null;let apartados=0;
 if(p.length>=20&&f.se>0){const q=p.filter(([x,y])=>Math.abs(y-(f.a+f.b*x))<=3*f.se);if(q.length>=8&&q.length<p.length){const g=ajusteLineal(q);if(g){f=g;apartados=p.length-q.length;}}}
 return {...f,apartados};
}
function histSVG(D,ud,dec){
 if(!D||!D.hist||!D.hist.length)return '';
 const W=230,H=44,pad=2,n=D.hist.length,mx=Math.max(1,...D.hist.map(b=>b[2])),bw=(W-2*pad)/n,lo=D.hist[0][0],hi=D.hist[n-1][1],x=v=>pad+(W-2*pad)*(Math.min(hi,Math.max(lo,v))-lo)/((hi-lo)||1);
 const bars=D.hist.map((b,i)=>{const h=(H-12)*b[2]/mx;return `<rect x="${(pad+i*bw+.5).toFixed(1)}" y="${(H-8-h).toFixed(1)}" width="${(bw-1).toFixed(1)}" height="${h.toFixed(1)}" rx="1" fill="#2C5FD6" opacity=".5"><title>${nf(b[0],dec)} – ${nf(b[1],dec)} ${esc(ud)}: ${nf(b[2])} viajes</title></rect>`;}).join('');
 const lin=(v,col,dash,t)=>`<line x1="${x(v).toFixed(1)}" x2="${x(v).toFixed(1)}" y1="2" y2="${H-8}" stroke="${col}" stroke-width="1.6"${dash?' stroke-dasharray="3 2"':''}><title>${t} ${nf(v,dec)} ${esc(ud)}</title></line>`;
 return `<svg class="hist" viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" role="img" aria-label="cuántos viajes hay en cada tramo">${bars}${lin(D.mediana,'#C1394B',false,'mediana')}${lin(D.media,'#0E9488',true,'media')}<text x="${pad}" y="${H-1}" font-size="7" fill="#8891a0">${nf(lo,dec)}</text><text x="${W-pad}" y="${H-1}" font-size="7" text-anchor="end" fill="#8891a0">${nf(hi,dec)}</text></svg>`;
}
function statsTabla(filas){
 const th=['Dato','n','Media','Mediana','Desv. típica','CV','p10','Q1 (25 %)','Q3 (75 %)','p90','Mín','Máx','IC 95 % de la media','Atípicos','Cuántos viajes en cada tramo'];
 const tr=filas.filter(f=>f[1]&&f[1].n).map(([l,S,ud,d])=>`<tr><td>${l} <small>(${esc(ud)})</small></td><td class="num">${nf(S.n)}</td><td class="num"><b>${nf(S.media,d)}</b></td><td class="num"><b>${nf(S.mediana,d)}</b></td><td class="num">${nf(S.sd,d)}</td><td class="num">${S.cv==null?'—':pct(S.cv)}</td><td class="num">${nf(S.p10,d)}</td><td class="num">${nf(S.q1,d)}</td><td class="num">${nf(S.q3,d)}</td><td class="num">${nf(S.p90,d)}</td><td class="num">${nf(S.min,d)}</td><td class="num">${nf(S.max,d)}</td><td class="num">${nf(S.ic[0],d)} – ${nf(S.ic[1],d)}</td><td class="num">${nf(S.atip)}${S.n?' ('+pct(S.atip/S.n)+')':''}</td><td>${histSVG(S,ud,d)}</td></tr>`).join('');
 return tr?`<div class="tablewrap" style="max-height:none"><table class="stat"><thead><tr>${th.map((h,i)=>`<th class="plain${i===0||i===th.length-1?'':' num'}">${h}</th>`).join('')}</tr></thead><tbody>${tr}</tbody></table></div>`:'';
}
function relaciones(trips){
 const own=trips.filter(t=>!t.sub&&t.km>0);
 const R=[['Litros según los km',regresion(own.map(t=>[t.km,t.lit])),'L'],['Horas de trabajo según los km',regresion(own.map(t=>[t.km,t.horas])),'h'],['Coste real según los km',regresion(own.map(t=>[t.km,t.coste])),'€'],['Ingreso según los km',regresion(own.map(t=>[t.km,t.ingreso])),'€']];
 const li=R.filter(([,r])=>r).map(([l,r,uy])=>{const ej=Math.round(r.mx);return `<li><b>${l}</b>: ${uy} = <b>${nf(r.a,2)}</b> + <b>${nf(r.b,3)}</b> × km <small>(R² ${nf(r.r2,2)}, ${nf(r.n)} viajes medidos${r.apartados?', '+nf(r.apartados)+' apartados por raros':''})</small>. Parte fija por viaje ${nf(r.a,2)} ${uy}; cada km más, ${nf(r.b,3)} ${uy}. Ejemplo: ${nf(ej)} km → ${nf(r.a+r.b*ej,1)} ${uy}${r.se?' (8 de cada 10 viajes así, entre '+nf(Math.max(0,r.a+r.b*ej-1.2816*r.se),1)+' y '+nf(r.a+r.b*ej+1.2816*r.se,1)+')':''}.</li>`;}).join('');
 return li?`<ul class="rel">${li}</ul><p class="sub" style="margin:6px 0 0">R² = qué parte de la variación entre viajes explican los km (1 = todo, 0 = nada). Con R² bajo los km no bastan para calcular: pesan las esperas, la carga o el tipo de ruta; usa entonces la mediana del dato. «Apartados por raros» = viajes a más de 3 errores típicos de la recta (lecturas raras, averías), que no se usan para trazarla.</p>`:'';
}
function estadViajes(trips,titulo){
 const own=trips.filter(t=>!t.sub);
 const F=[['Km por viaje (localizador)',statsDe(own.map(t=>t.km>0?t.km:null)),'km',0],['Horas de trabajo por viaje',statsDe(own.map(t=>t.horas)),'h',1],['Litros por viaje',statsDe(own.map(t=>t.lit)),'L',1],['Litros por 100 km',statsDe(own.map(t=>t.lit&&t.km?t.lit/t.km*100:null)),'L/100 km',1],['Km por hora de trabajo',statsDe(own.map(t=>t.horas&&t.km?t.km/t.horas:null)),'km/h',1],['Minutos parado o esperando',statsDe(own.map(t=>t.espera)),'min',0],['Minutos conduciendo',statsDe(own.map(t=>t.cond)),'min',0],['m³ por viaje',statsDe(trips.map(t=>t.m3>0?t.m3:null)),'m³',1],['Toneladas por viaje',statsDe(trips.map(t=>t.t>0?t.t:null)),'t',1],['Ingreso por viaje',statsDe(trips.map(t=>t.ingreso)),'€',0],['Coste real por viaje',statsDe(trips.map(t=>t.coste)),'€',0],['Margen por viaje',statsDe(trips.map(t=>t.margen)),'€',0],['Ingreso por km',statsDe(own.map(t=>t.km>0?t.ingreso/t.km:null)),'€/km',2],['Coste real por km',statsDe(own.map(t=>t.km>0?t.coste/t.km:null)),'€/km',2]];
 const tabla=statsTabla(F);if(!tabla)return '';
 return `${titulo?`<div class="grp">${titulo}</div>`:''}<div style="grid-column:1/-1"><p class="sub" style="margin:0 0 8px">Media y mediana con su dispersión: desviación típica, CV (desviación ÷ media), el 50 % central entre Q1 y Q3, el 80 % entre p10 y p90, valores atípicos (fuera de 1,5 veces el rango intercuartílico) e intervalo de confianza del 95 % de la media (con esos viajes, la media real está ahí con un 95 % de seguridad). Km, horas, litros y esperas solo de viajes propios con dato del localizador; los subcontratados no llevan km ni horas nuestros.</p>${tabla}${relaciones(trips)}</div>`;
}
function realCols(dim,real){
 const cols=[dim==='plate'?{label:'Matrícula',key:'label'}:{label:'Cliente',key:'label'}];
 if(dim==='plate')cols.push({label:'Tipo',key:'tipoT',center:true},{label:'Propio / subcontratado',key:'propioT',center:true});
 else cols.push(numberCol('Vehículos','matriculas'));
 cols.push(numberCol('Viajes reales','viajes'),moneyCol('Ingreso facturado','ingreso'),moneyCol('Material (áridos)','material'),moneyCol('Ingreso transporte y servicios','ingTransporte'));
 if(real)cols.push(moneyCol('Coste real','coste'),{...moneyCol('Margen neto','margen'),signed:true},percentCol('% sobre facturado','margenPct'),percentCol('% sobre transporte','margenTransPct'));
 cols.push({label:'Medido',key:'fiable',numeric:true,format:pct},numberCol('Km (localizador)','km'),numberCol('Horas','horas',1),numberCol('Litros','litros'),numberCol('l/100 km','l100',1),moneyCol('Ingreso por km','ingKm'));
 if(real)cols.push(moneyCol('Margen por km','margenKm'),moneyCol('Coste flota por km','costeKm'));
 cols.push(moneyCol('Ingreso por hora','ingHora'));
 if(real)cols.push(moneyCol('Margen por hora','margenHora'));
 cols.push(numberCol('Días con viaje','dias'),numberCol('m³','m3'),numberCol('Toneladas','t'),numberCol('Min. espera','espera'));
 return cols;
}
function realTab(dim){
 const rv=M.realView(state,dim),isP=dim==='plate';
 if(!rv)return panel(isP?'Vehículos':'Clientes','','<div class="info">No hay viajes reales de GesRuta en el periodo y empresa elegidos.</div>');
 const rows=rv.groups.map(g=>({...g,label:isP?plateFmt(g.key):g.key,tipoT:tipoLabel(g.tipo),propioT:g.subViajes===0?'propio':g.subViajes===g.viajes?'subcontratado':(g.propio?'propio (algún viaje subcontratado)':'subcontratado (algún viaje propio)')}));
 const t=rv.tot;
 const cardsRows=[['Viajes reales',nf(t.viajes),nf(rows.length)+(isP?' matrículas':' clientes')+' · '+nf(t.dias)+' días con viaje'],
  ['Ingreso facturado',eur(t.ingreso),'material (áridos comprados) '+eur(t.material)+' → transporte y servicios <b>'+eur(t.ingTransporte)+'</b>'],
  rv.real?['Coste real repartido',eur(t.coste),'combustible '+eur(t.combustible)+' · personal '+eur(t.personal)+' · flota '+eur(t.flota)+' · indirectos '+eur(t.indirectos)+' · subcontrata '+eur(t.subcontrata)+' · material '+eur(t.material)]:['Coste real','—','sin contabilidad cerrada en el periodo'],
  rv.real?['Margen neto',eur(t.margen),pct(t.margenPct)+' sobre facturado · '+pct(t.margenTransPct)+' sobre transporte · el conjunto cuadra con el libro de los meses cerrados, antes de impuestos ('+pct(rv.margenLibroPct)+')']:['Medido',pct(t.fiable),'ingreso con km y horas del localizador']];
 const cards=`<section class="cards" style="margin-bottom:16px">${cardsRows.map(([l,x,h])=>`<article class="card"><span class="label">${l}</span><div class="value">${x}</div><div class="hint">${h}</div></article>`).join('')}</section>`;
 const intra=isP?'':' <b>Razo o Agetrans como cliente</b> = facturación entre las dos empresas: su margen mide el precio al que una le cobra a la otra (en el grupo se compensa con el viaje de la otra casa), no un cliente real.';
 const info=`<div class="info"><b>${isP?'Cada vehículo':'Cada cliente'} con sus viajes reales</b> (albaranes de GesRuta) y el <b>coste REAL de la contabilidad</b> repartido a cada viaje por lo que midió el localizador: combustible por litros, personal por horas, flota (reparaciones, seguros, amortización…) por km, gastos generales por ingreso; los viajes subcontratados llevan la factura real del subcontratista. <b>Material</b> = compra de áridos que va dentro del precio (compraventa), atribuida por cliente: se descuenta para dar el <b>ingreso de transporte y servicios</b>. <b>Pincha en una fila</b> para desplegar el detalle (por mes, ${isP?'cliente':'matrícula'}, ruta, lugares de carga y descarga${isP?', localizador, Solred y partes':''}). Busca por palabras o abre «Filtros».${intra}${rv.real?' El gasto de cada mes va a los viajes de ese mes; los viajes sin traza reciben su parte por su ingreso, no cargan a los medidos. Coeficientes medios del periodo: '+eur(rv.coef.lit)+'/litro · '+eur(rv.coef.dur*60)+'/hora · '+eur(rv.coef.km)+'/km.'+(rv.mesesEstimados.length?' <b>Meses sin contabilidad cerrada ('+rv.mesesEstimados.map(monthName).join(', ')+')</b>: coste estimado con los coeficientes del último mes cerrado.':''):' <b>Sin contabilidad cerrada en el periodo</b>: se ven viajes, ingresos y medidas, pero no el coste real.'}</div>`;
 const top=panel(isP?'Vehículos con más ingreso de transporte':'Clientes con más ingreso de transporte','Primeros ocho por ingreso de transporte y servicios (sin el material); tabla completa debajo.',bars(rows.slice(0,8).map(x=>({label:x.label,v:x.ingTransporte,note:rv.real&&x.margen!=null?'margen '+pcm(x.margenPct):''})),'v'));
 _rvCur=rv;
 return info+cards+top+setTable(isP?'Rentabilidad real por vehículo':'Rentabilidad real por cliente','Ordenable, con búsqueda por palabras y filtros por columna. Verde gana, rojo pierde. Pincha en una fila para ver su detalle.',rows,realCols(dim,rv.real),null,x=>realDetail(x,dim));
}
function realDetail(r,dim){
 const rv=_rvCur;if(!rv)return '';
 const d=rv.detail(r.key),isP=dim==='plate',real=rv.real,k=pkey(r.key);
 const grp=s=>`<div class="grp">${s}</div>`;
 const mini=(title,rows,first,fmt,max=12)=>{if(!rows.length)return '';const cols=[{label:first,key:'label'},numberCol('Viajes','viajes'),moneyCol('Ingreso','ingreso'),moneyCol('Ing. transporte','ingTransporte')].concat(real?[moneyCol('Coste real','coste'),{...moneyCol('Margen','margen'),signed:true},percentCol('%','margenPct')]:[]).concat([numberCol('Km','km'),numberCol('Horas','horas',1),numberCol('Litros','litros'),{label:'Medido',key:'fiable',numeric:true,format:pct}]);
  return `<div class="dtab"><h4>${title}${rows.length>max?' <small>(primeros '+max+' de '+nf(rows.length)+')</small>':''}</h4>${simpleTable(cols,rows.slice(0,max).map(x=>({...x,label:fmt?fmt(x.key):x.key})))}</div>`;};
 const soc=isP?M.plateSociety.get(k):null,tel=isP?M.telemetryByPlate(state).get(k):null,sol=isP?M.solredByPlate(state).get(k):null,par=isP?M.partsByPlate(state).get(k):null;
 const trips=M.netaTrips(state).filter(isP?(t=>pkey(t.mat)===k):(t=>t.cliente===r.key));
 const lab={combustible:'Combustible (por litros medidos)',personal:'Personal (por horas medidas)',flota:'Flota: reparaciones, seguros, amortización… (por km)',indirectos:'Gastos generales (por ingreso)',subcontrata:'Subcontratistas (factura real)',material:'Material: compra de áridos (por cliente)'};
 const costes=real?['combustible','personal','flota','indirectos','subcontrata','material'].filter(c=>Math.abs(r[c])>=0.5).map(c=>detRow(lab[c],eur(r[c]))).join(''):'';
 const cabecera=(isP?plateFmt(r.key)+' · '+tipoLabel(r.tipo):esc(r.key))+(soc?' · flota de '+esc(soc):'')+(tel&&tel.clase?' · '+esc(tel.clase)+' (ERP)':'')+' · '+nf(r.viajes)+' viajes reales en '+nf(r.dias)+' días'+(isP?' · '+nf(r.clientes)+' clientes':' · '+nf(r.matriculas)+' matrículas')+(r.subViajes?' · '+nf(r.subViajes)+' subcontratados':'');
 const tipos=Object.entries(r.tipos||{}).filter(([t])=>t).map(([t,n])=>tipoLabel(t)+' '+nf(n)).join(' · ');
 return `<div class="tripdetail">
  ${grp(cabecera)}
  ${detRow('Ingreso facturado',eur(r.ingreso)+(r.subIng?' <small>(subcontratado '+eur(r.subIng)+')</small>':''))}
  ${detRow('Material (compra de áridos atribuida)',eur(r.material))}
  ${detRow('Ingreso de transporte y servicios','<b>'+eur(r.ingTransporte)+'</b>')}
  ${real?detRow('Coste real',eur(r.coste)):detRow('Coste real','sin contabilidad cerrada en el periodo')}
  ${costes}
  ${real?detRow('Margen neto','<b class="'+(r.margen>=0?'pos':'neg')+'">'+eur(r.margen)+'</b> · '+pcm(r.margenPct)+' sobre facturado · '+pcm(r.margenTransPct)+' sobre transporte'+(r.costeEstimado?' <small>('+nf(r.costeEstimado)+' viajes de meses sin cerrar, coste estimado)</small>':'')):''}
  ${detRow('Medido',pct(r.fiable)+' del ingreso con km y horas reales del localizador'+(r.viajesMed?' · '+nf(r.viajesMed)+' viajes medidos':''))}
  ${grp('Medidas de los viajes (localizador)')}
  ${detRow('Km en viajes',r.km?nf(r.km)+' km'+((r.kmCarg||r.kmVac)?' · cargado '+nf(r.kmCarg)+' · en vacío '+nf(r.kmVac):''):null)}
  ${detRow('Horas de trabajo',r.horas?nf(r.horas,1)+' h'+(r.cond?' · conduciendo '+nf(r.cond/60,1)+' h · parado o esperando '+nf(r.espera/60,1)+' h':''):null)}
  ${detRow('Litros',r.litros?nf(r.litros)+' L'+(r.l100?' · '+nf(r.l100,1)+' l/100 km':''):null)}
  ${detRow('Por km y por hora (viajes propios)',r.km?'ingreso '+eur(r.ingKm)+'/km · '+eur(r.ingHora)+'/h'+(real?' · margen '+eur(r.margenKm)+'/km · '+eur(r.margenHora)+'/h · coste de flota '+eur(r.costeKm)+'/km':''):null)}
  ${detRow('Carga transportada',(r.m3?nf(r.m3)+' m³':'')+(r.t?(r.m3?' · ':'')+nf(r.t)+' t':''))}
  ${detRow('Tipos de viaje',tipos)}
  ${estadViajes(trips,'Estadística de sus viajes: media, mediana y dispersión')}
  ${isP?grp('El camión en todo el periodo (con y sin viaje)'):''}
  ${isP?detRow('Localizador',tel?nf(tel.km)+' km en '+nf(tel.dias)+' días con lectura ('+nf(tel.activos)+' activos, del '+date(tel.desde)+' al '+date(tel.hasta)+')'+(tel.litros?' · '+nf(tel.litros)+' L del sensor · '+nf(tel.l100,1)+' l/100 km':' · sin sensor de consumo'):'sin lectura del localizador en el periodo'):''}
  ${isP&&tel&&tel.km?detRow('Km en viajes / km del localizador',pct(r.km/tel.km)+' <small>(el resto: vacíos entre viajes, nave, taller o viajes sin albarán)</small>'):''}
  ${isP?detRow('Tarjeta Solred (gasóleo)',sol?nf(sol.litros)+' L · '+eur(sol.base)+' sin IVA · '+nf(sol.n)+' repostajes en '+sol.meses.length+' meses con fichero ('+sol.meses[0]+' → '+sol.meses[sol.meses.length-1]+')':null):''}
  ${isP?detRow('Partes de Access (declarado)',par?nf(par.partes)+' partes · '+nf(par.km)+' km · '+nf(par.horas,1)+' h · '+nf(par.litros)+' L · coste imputado '+eur(par.coste)+' · '+esc(par.owner)+' · '+esc(par.category):null):''}
  <div class="grp noprint">${isP?`<button class="textbtn" data-verviajes="${esc(r.key)}">Ver sus viajes uno a uno ↗</button> · <button class="textbtn" data-drill="plates" data-key="${esc(k)}">Filtrar todo el informe por este vehículo ↗</button>`:`<button class="textbtn" data-fichacli="${esc(r.key)}">Abrir la ficha del cliente (comparar periodos, operaciones) ↗</button> · <button class="textbtn" data-verviajes="${esc(r.key)}">Ver sus viajes uno a uno ↗</button>`}</div>
 </div>
 ${mini('Por mes',d.byMonth,'Mes',monthName,36)}
 ${isP?mini('Por cliente',d.byClient,'Cliente'):mini('Por matrícula',d.byPlate,'Matrícula',plateFmt)}
 ${mini('Por ruta (provincia de carga → provincia de descarga)',d.byRuta,'Ruta')}
 ${mini('Por lugar de carga',d.byCarga,'Lugar de carga')}
 ${mini('Por lugar de descarga',d.byDescarga,'Lugar de descarga')}
 ${mini('Por tipo de viaje',d.byTipo,'Tipo',tipoLabel)}`;
}
function renderContent(){
 tableDefinition=null;let html='';
 if(state.tab==='summary'&&ledgerCtx.ledgerOn){
   const {lv,br,lvBase}=ledgerCtx,op=new Map(M.group(selection,state,'month').groups.map(m=>[m.key,m]));
   const plRows=lv.byMonth.map(m=>({key:m.key,label:monthName(m.key),income:m.income,expenses:m.expenses,result:m.result,marginPct:m.marginPct,gesruta:op.get(m.key)?.revenue??0,parts:op.get(m.key)?.[state.costMode==='stored'?'rawCost':state.costMode==='recalculated'?'calcCost':'realCost']??0}));
   const totalExp=lv.expenses||1,cats=lv.expenseCategories.filter(c=>c.amount>0).slice(0,11).map(c=>({label:c.label,cost:c.amount,note:nf(c.amount/totalExp*100,0)+' %'}));
   html=`<div class="grid2">${panel('Ingresos y gastos por mes','Contabilidad real (CxConta), solo meses cerrados.'+(lvBase?' Líneas discontinuas: '+ledgerCtx.priorLabel.toLowerCase()+'.':''),`<div class="legend"><span><i style="background:var(--blue)"></i>Ingresos</span><span><i style="background:#169389"></i>Gastos</span>${lvBase?'<span style="color:var(--blue)"><i class="dash"></i>Ingresos (comparación)</span><span style="color:#169389"><i class="dash"></i>Gastos (comparación)</span>':''}</div>${plChart(lv.byMonth,lvBase?.byMonth)}`)}${panel('De qué está hecho el gasto real','Por naturaleza de la cuenta contable, en el periodo cerrado.',bars(cats,'cost'))}</div>${estructuraPanel()}${intercompanyPanel()}${fuelPersonnelPanel()}${ratiosPanel()}${metrics()}`;
   html+=setTable('Resultado mes a mes','Ingresos y gastos de la contabilidad. A la derecha, lo que captan las facturas de GesRuta y los partes de Access el mismo mes (el gasto de los partes es incompleto). <b>Pincha en un mes</b> para desplegar su detalle: naturalezas y cuentas, por sociedad, estructura del gasto, transporte sin el material y la operación del mes.',plRows,[{label:'Mes',key:'label'},moneyCol('Ingresos','income'),moneyCol('Gastos','expenses'),{...moneyCol('Resultado','result'),signed:true},percentCol('Margen','marginPct'),moneyCol('Facturas GesRuta','gesruta'),moneyCol('Coste en partes','parts')],null,monthDetail);
 }else if(state.tab==='summary'){
   const months=M.group(selection,state,'month').groups.sort((a,b)=>a.key.localeCompare(b.key));
   const mix=D.costFields.map(([key,label])=>({label,cost:current.totals.breakdown[key]}));
   if(state.costMode==='recalculated'){mix.find(r=>r.label==='Estructura').cost=selection.costs.reduce((n,r)=>n+r.componentDirect*r.rate*r.share,0);mix.find(r=>r.label==='Diferencia guardado / desglose').cost=0;}
   html=`<div class="grid2">${panel('Evolución mensual','Ingresos según el criterio elegido · costes según fecha del parte.',`<div class="legend"><span><i style="background:#2868dd"></i>Ingresos sin IVA</span><span><i style="background:#169389"></i>Coste disponible</span></div>${trendChart(months)}`)}${panel('De qué está hecho el coste','Desglose conservado del parte de Access.',bars(mix.filter(r=>Math.abs(r.cost)>.001).sort((a,b)=>b.cost-a.cost),'cost'))}</div>${metrics()}`;
   html+=setTable('Mes a mes','Esta tabla y los indicadores comparten el mismo cálculo. Los recuentos de facturas y viajes son distintos, no sumas de subtotales.',months,groupColumns());
 }else if(['plate','client'].includes(state.tab)){
   html=realTab(state.tab);
 }else if(state.tab==='invoices'){
   html=setTable('Detalle completo de facturación','Todas las líneas de la selección. El importe sin IVA respeta suplidos y ajustes de cabecera; ambas fechas quedan visibles.',selection.lines,[{label:'Factura',key:'invoice'},{label:'Empresa',key:'company'},{label:'Fecha factura',key:'invoiceDate'},{label:'Fecha línea',key:'lineDate'},{label:'Cliente',key:'client'},{label:'Vehículo',key:'plateLabel'},{label:'Viaje',key:'trip'},{label:'Albarán',key:'delivery'},{label:'Carga',key:'load'},{label:'Tipo de servicio',key:'concept'},{label:'Concepto (texto de la línea)',key:'conceptText'},{label:'Cuenta',key:'account'},numberCol('Cantidad','quantity',2),moneyCol('Precio','price'),moneyCol('Ingreso sin IVA','revenue'),{label:'Tipo',key:'kind'},{label:'Matrícula tomada de',key:'plateSource'}]);
 }else if(state.tab==='parts'){
   html=setTable('Partes y composición del coste','El coste origen es íntegro; el coste en selección aplica la cuota comercial. Un mismo parte puede contribuir a varios clientes. No se modifica el dato de Access.',partRows(),[{label:'Parte Access',key:'id'},{label:'Fecha',key:'date'},{label:'Matrícula',key:'plateLabel'},{label:'Tipo vehículo',key:'category'},{label:'Titular actual',key:'owner'},{label:'Cliente del parte',key:'partClient'},moneyCol('Coste origen','stored'),percentCol('Cuota en selección','allocation'),moneyCol('Coste en selección','allocated'),moneyCol('Recalculado origen','recalculated'),moneyCol('Descuadre directo','residual'),...D.costFields.filter(([k])=>k!=='residual').map(([k,l])=>moneyCol(l,k)),numberCol('Km origen','km'),numberCol('Horas origen','hours',2),numberCol('Viajes Access origen','trips')]);
 }else if(state.tab==='audit')html=audit();
 else if(state.tab==='personal')html=personalView();
 else if(state.tab==='actividad')html=activityTab();
 else if(state.tab==='viajes')html=viajesTab();
 else if(state.tab==='mapa')html=mapa();
 else if(state.tab==='hallazgos')html=hallazgosTab();
 else if(state.tab==='clientedet')html=clienteDet();
 else html=method();
 $('content').innerHTML=html;drawTable();wireInfo();
 if(state.tab==='mapa')mapaRender();
 if(state.tab==='clientedet')clienteDetWire();
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
 tableState=freshTable();renderContent();
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
function switchTab(tab){state.tab=tab;tableState=freshTable();document.querySelectorAll('#tabs button').forEach(b=>{const on=b.dataset.tab===tab;b.classList.toggle('selected',on);if(on)b.setAttribute('aria-current','page');else b.removeAttribute('aria-current');});renderContent();}
function bind(){
 document.addEventListener('click',e=>{
  const tr=e.target.closest('tr.exp');
  if(tr&&!e.target.closest('a,button,input,select,label')){const i=Number(tr.dataset.row);if(tableState.open.has(i))tableState.open.delete(i);else tableState.open.add(i);drawTable();return;}
  const b=e.target.closest('button');if(!b)return;
  if(b.id==='tableFilters'){tableState.showFilters=!tableState.showFilters;const bar=$('tableFilterBar');if(bar)bar.hidden=!tableState.showFilters;b.setAttribute('aria-expanded',String(tableState.showFilters));b.classList.toggle('on',tableState.showFilters||activeFilterCount()>0);return;}
  if(b.id==='tableClearFilters'){tableState.filters={};const bar=$('tableFilterBar');if(bar)bar.querySelectorAll('input,select').forEach(el=>{el.value='';});tableState.page=0;drawTable();return;}
  if(b.dataset.tremove!==undefined){removeFilter(b.dataset.tremove,b.dataset.part);return;}
  if(b.dataset.infoHide!==undefined){infoSet(b.dataset.infoHide,true);return;}
  if(b.dataset.infoShow!==undefined){infoSet(b.dataset.infoShow,false);return;}
  if(b.id==='infoToggle'){infoAll();return;}
  if(b.dataset.company!==undefined){state.companies=b.dataset.company?[b.dataset.company]:[];tableState.page=0;update();}
  if(b.dataset.tab)switchTab(b.dataset.tab);
  if(b.id==='personalGo')unlockPersonal();
  if(b.id==='personalLock'){personal=personalEmpty();tableState=freshTable();renderContent();}
  if(b.dataset.ptype!==undefined){personal.type=b.dataset.ptype;tableState=freshTable();renderContent();}
  if(b.dataset.clear){state[b.dataset.clear]=[];tableState.page=0;update();}
  if(b.dataset.remove){state[b.dataset.remove]=state[b.dataset.remove].filter(v=>v!==b.dataset.value);tableState.page=0;update();}
  if(b.dataset.drill){state[b.dataset.drill]=[b.dataset.key==='Sin matrícula'?UNASSIGNED:b.dataset.key];update();}
  if(b.dataset.verviajes!==undefined){const q=b.dataset.verviajes;switchTab('viajes');tableState.query=q;const inp=$('tableSearch');if(inp)inp.value=q;drawTable();return;}
  if(b.dataset.fichacli!==undefined){_cliSel=b.dataset.fichacli;switchTab('clientedet');return;}
  if(b.dataset.sort){tableState.asc=tableState.sort===b.dataset.sort?!tableState.asc:true;tableState.sort=b.dataset.sort;drawTable();}
  if(b.dataset.page){tableState.page+=Number(b.dataset.page);drawTable();}
  if(b.dataset.period){const [from,to]=b.dataset.period.split('|');$('from').value=from;$('to').value=to;tableState.page=0;update();}
  if(b.dataset.zmode){zoneMode=b.dataset.zmode;renderContent();}
  if(b.dataset.ztoggle){const k=b.dataset.ztoggle;if(zonasAbiertas.has(k))zonasAbiertas.delete(k);else zonasAbiertas.add(k);const c=$('zonasTabla');if(c)c.innerHTML=zonasTabla(zonasVista.zonas,zonasVista.total);}
 });
 document.addEventListener('keydown',e=>{if(e.key==='Enter'&&e.target.id==='personalKey')unlockPersonal();});
 // la estadística de lo que se ve se calcula al abrirla (y se recuerda abierta en este navegador)
 document.addEventListener('toggle',e=>{const d=e.target;if(!d||d.id!=='tstats')return;lsSet(STATS_KEY,d.open);if(d.open)drawStats();},true);
 document.addEventListener('change',e=>{
  const el=e.target;if(el.id==='personalMonth'){personal.month=el.value;tableState=freshTable();renderContent();return;}
  if(el.dataset.slicer){const k=el.dataset.slicer;state[k]=el.checked?[...new Set([...state[k],el.value])]:state[k].filter(v=>v!==el.value);tableState.page=0;update();}
 });
 document.addEventListener('input',e=>{
  if(e.target.dataset.searchSlicer){const id=e.target.dataset.searchSlicer,ws=norm(e.target.value).split(/\s+/).filter(Boolean);$('options-'+id).querySelectorAll('label').forEach(l=>{const h=norm(l.textContent);l.hidden=!ws.every(w=>h.includes(w));});}
  if(e.target.id==='tableSearch'){tableState.query=e.target.value;tableState.page=0;drawTable();}
  applyFilterControl(e.target);
 });
 for(const id of ['from','to','dateBasis','compare','compareFrom','compareTo','costMode','billing'])$(id).addEventListener('change',()=>{$('customCompare').hidden=$('compare').value!=='custom';tableState.page=0;update();});
 $('reset').onclick=()=>{state={...state,companies:[],plates:[],clients:[],categories:[],loads:[],concepts:[]};$('from').value=D.metadata.defaultFrom;$('to').value=D.metadata.defaultTo;$('dateBasis').value='invoice';$('costMode').value=D.payroll?'real':'stored';$('compare').value='none';$('customCompare').hidden=true;tableState=freshTable();update();};
 $('methodlink').onclick=e=>{e.preventDefault();switchTab('method');};
}
async function boot(){
 const bytes=Uint8Array.from(atob('__PACKED_DATA__'),c=>c.charCodeAt(0));
 D=JSON.parse(await new Response(new Blob([bytes]).stream().pipeThrough(new DecompressionStream('gzip'))).text());
 M=createModel(D);state={from:D.metadata.defaultFrom,to:D.metadata.defaultTo,dateBasis:'invoice',costMode:D.payroll?'real':'stored',consolidado:false,tab:'summary',companies:[],plates:[],clients:[],categories:[],loads:[],concepts:[]};
 if(!D.payroll)$('costMode').querySelector('option[value="real"]').remove();
 if(!D.ledger?.intragrupo?.length)$('billing').closest('label').hidden=true;
 $('costMode').value=state.costMode;$('billing').value='suma';renderSources();$('personalTab').hidden=!PERSONAL_BLOB;$('actividadTab').hidden=!D.actividad;$('viajesTab').hidden=!D.actividad;$('clientedetTab').hidden=!D.actividad;$('mapaTab').hidden=!(D.actividad&&D.actividad.coords);$('hallazgosTab').hidden=!(D.actividad&&D.actividad.tri&&D.actividad.tri.hallazgos);
 for(const id of ['from','to','compareFrom','compareTo']){$(id).min=D.metadata.from;$(id).max=D.metadata.to;}
 $('from').value=state.from;$('to').value=state.to;$('compareFrom').value=priorYear(state.from);$('compareTo').value=priorYear(state.to);
 $('fresh').textContent='Lectura '+new Date(D.metadata.accessReadAt).toLocaleString('es-ES',{timeZone:'Europe/Madrid'})+' · datos hasta '+date(D.metadata.to);
 $('refreshMode').textContent=D.metadata.refresh?.mode==='scheduled'?'Actualización nocturna '+D.metadata.refresh.at:'Actualización nocturna pendiente';
 $('reloadReport').onclick=()=>location.reload();
 $('months').innerHTML=quickPeriods(D.metadata.from,D.metadata.to).map(r=>`<button data-period="${r.from}|${r.to}">${r.label}</button>`).join('');
 makeSlicers();bind();update();
}
boot().catch(error=>{$('message').innerHTML='<div class="alert error">No se pudo abrir el informe. Utilice una versión actual de Chrome, Edge o Firefox y vuelva a cargar. Los datos no se han modificado.</div>';$('fresh').textContent='No se ha podido cargar';console.error(error);});
