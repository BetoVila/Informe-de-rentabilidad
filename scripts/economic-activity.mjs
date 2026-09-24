// Facturas = ingreso autoritativo. Coste por carga = misma salida versionada que Tarifas.
// La identidad siempre incluye sociedad; ni el cliente ni el mes identifican una compra de material.
const id=v=>String(v??'').trim().replace(/^0+(?=\d)/,'');
const key=(c,v,a)=>[c,id(v),id(a)].join('|');
const tipo=l=>String(l.account||'').startsWith('705003')?'hormigonera':String(l.account||'').startsWith('705002')?'banera':'';
export function costSnapshot(costs,readAt){
  if(!costs.length)return {rows:[],state:'sin',generated:null,note:'Sin export de costes: margen pendiente.'};
  const stamps=[...new Set(costs.map(c=>c.generado))];
  if(stamps.length!==1||!stamps[0]||costs.some(c=>c.version_coste!==2))throw new Error('Export de costes mezclado, sin fecha o de version antigua');
  const generated=stamps[0],fresh=generated.slice(0,10)===String(readAt).slice(0,10);
  return {rows:fresh?costs:[],state:fresh?'ok':'sin',generated,note:fresh?'Costes imputados por carga, lectura '+generated+'.':'Costes de '+generated+'; no corresponden al dia de lectura de facturas. Margen pendiente.'};
}
export function reconcileActivity(activity, invoices, costs){
  const rows=(activity?.rows||[]).map(r=>({...r,economia:[],costeCanonico:null}));
  const byDelivery=new Map(), byTrip=new Map(), byCost=new Map();
  const put=(map,k,v)=>{if(!map.has(k))map.set(k,[]);map.get(k).push(v);};
  for(const r of rows){put(byTrip,key(r.c,r.v,''),r);for(const a of r.albaranes||[])put(byDelivery,key(r.c,r.v,a),r);}
  for(const c of costs){
    if(c.version_coste!==2)continue; // nunca aceptar el export antiguo que convertia desconocido en cero
    const cantera=c.cantera==='A'+c.albaran?'':c.cantera;
    const k=key(c.empresa,c.viaje,cantera||'@'+id(c.albaran));
    let d=byCost.get(k);if(!d){d={componentes:{},completo:true,faltantes:[],fuente:'Tarifas / coste_cargas v2',generado:c.generado};byCost.set(k,d);}
    for(const [campo,valor] of Object.entries(c.coste||{}))if(valor!=null)d.componentes[campo]=(d.componentes[campo]||0)+valor;
    d.completo=d.completo&&c.coste_completo===true;
    d.faltantes=[...new Set([...d.faltantes,...(c.faltantes||[])])];
  }
  const costKeys=r=>r.cant?[key(r.c,r.v,r.cant)]:(r.albaranes||[]).map(a=>key(r.c,r.v,'@'+id(a)));
  const users=new Map();for(const r of rows)for(const k of new Set(costKeys(r)))put(users,k,r);
  for(const r of rows){
    const keys=[...new Set(costKeys(r))],ds=keys.map(k=>byCost.get(k));
    if(ds.some(Boolean)){
      const d={componentes:{},completo:ds.every(x=>x?.completo),faltantes:[...new Set(ds.flatMap(x=>x?.faltantes||['coste de albaran sin enlace']))],fuente:'Tarifas / coste_cargas v2',generado:ds.find(Boolean).generado};
      keys.forEach((k,i)=>{const x=ds[i];if(!x)return;const rs=users.get(k),den=rs.reduce((s,r)=>s+Math.abs(r.imp||0),0),share=den?Math.abs(r.imp||0)/den:1/rs.length;
        for(const [f,v] of Object.entries(x.componentes))d.componentes[f]=(d.componentes[f]||0)+v*share;
      });
      r.costeCanonico=d;
    }
  }
  let unmatched=0, matched=0;
  for(const l of invoices){
    if(!Number.isFinite(l.revenue))throw new Error('Importe de factura no numerico: '+l.id);
    let candidates=l.trip&&l.delivery?byDelivery.get(key(l.company,l.trip,l.delivery)):null;
    if(!candidates?.length&&l.trip){const rs=byTrip.get(key(l.company,l.trip,''));if(rs?.length===1)candidates=rs;}
    if(candidates?.length){
      const specific=candidates.filter(r=>r.conceptos?.includes(l.article));
      if(specific.length)candidates=specific;
    }
    if(!candidates?.length){
      const date=l.serviceDate||l.lineDate||l.invoiceDate;
      const r={c:l.company,v:l.trip||'',cant:'',cli:l.client,mat:l.plate||'',mes:date.slice(0,7),dia:date,
        tipo:tipo(l),horm:tipo(l)==='hormigonera',imp:0,economia:[],costeCanonico:null,soloFactura:true};
      rows.push(r);candidates=[r];unmatched+=l.revenue;
    }else matched+=l.revenue;
    const total=candidates.reduce((s,r)=>s+Math.abs(r.imp||0),0);
    let assigned=0;
    candidates.forEach((r,i)=>{
      const revenue=i===candidates.length-1?l.revenue-assigned:l.revenue*(total?Math.abs(r.imp||0)/total:1/candidates.length);
      assigned+=revenue;
      r.economia.push({id:l.id,invoiceDate:l.invoiceDate,lineDate:l.lineDate,clientId:l.clientId,client:l.client,
        load:l.load,concept:l.concept,category:l.category,account:l.account,revenue});
      if(!r.tipo&&tipo(l))r.tipo=tipo(l);
    });
  }
  for(const r of rows){r.importeAlbaran=r.imp||0;r.imp=r.economia.reduce((s,l)=>s+l.revenue,0);}
  const expected=invoices.reduce((s,l)=>s+l.revenue,0),actual=rows.reduce((s,r)=>s+r.imp,0);
  if(Math.abs(expected-actual)>.01)throw new Error('La actividad no concilia con facturas');
  return {rows,control:{facturado:expected,asignado:matched,sinViaje:unmatched,costes:byCost.size,
    filasSinCoste:rows.filter(r=>r.economia.length&&!r.costeCanonico?.completo).length}};
}
