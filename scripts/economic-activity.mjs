// Facturas = ingreso autoritativo. Coste por carga = misma salida versionada que Tarifas.
// La identidad siempre incluye sociedad; ni el cliente ni el mes identifican una compra de material.
const id=v=>String(v??'').trim().replace(/^0+(?=\d)/,'');
const key=(c,v,a)=>[c,id(v),id(a)].join('|');
const tipo=l=>String(l.account||'').startsWith('705003')?'hormigonera':String(l.account||'').startsWith('705002')?'banera':'';
const cents=v=>Math.round(Number(v)*100);
function tieneEvidenciaRealViaje(c){
  const e=c.evidencia_real,componentes=Object.entries(c.coste||{}).filter(([,v])=>v!=null&&Math.abs(Number(v))>=0.005);
  if(c.coste_completo!==true||e?.granularidad!=='viaje'||e?.conciliada!==true||!Array.isArray(e.lineas)||!e.lineas.length)return false;
  if(componentes.some(([,v])=>!Number.isFinite(Number(v))))return false;
  const esperados=new Map(componentes.map(([k,v])=>[k,cents(v)])),vistos=new Map();
  for(const l of e.lineas){
    if(!esperados.has(l.componente)||!String(l.fuente||'').trim()||!/^[a-f0-9]{64}$/i.test(String(l.documento_sha256||''))||!String(l.linea||'').trim()||typeof l.importe!=='number'||!Number.isFinite(l.importe))return false;
    vistos.set(l.componente,(vistos.get(l.componente)||0)+cents(l.importe));
  }
  return vistos.size===esperados.size&&[...esperados].every(([k,v])=>Math.abs((vistos.get(k)??Infinity)-v)<=1);
}
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
    let d=byCost.get(k);if(!d){d={componentes:{},completo:true,realConfirmado:true,faltantes:[],fuente:'Tarifas / coste_cargas v2',generado:c.generado};byCost.set(k,d);}
    for(const [campo,valor] of Object.entries(c.coste||{}))if(valor!=null)d.componentes[campo]=(d.componentes[campo]||0)+valor;
    d.completo=d.completo&&c.coste_completo===true;
    d.realConfirmado=d.realConfirmado&&tieneEvidenciaRealViaje(c);
    d.faltantes=[...new Set([...d.faltantes,...(c.faltantes||[])])];
  }
  const costKeys=r=>r.cant?[key(r.c,r.v,r.cant)]:(r.albaranes||[]).map(a=>key(r.c,r.v,'@'+id(a)));
  const users=new Map();for(const r of rows)for(const k of new Set(costKeys(r)))put(users,k,r);
  for(const r of rows){
    const keys=[...new Set(costKeys(r))],ds=keys.map(k=>byCost.get(k));
    if(ds.some(Boolean)){
      const d={componentes:{},completo:ds.every(x=>x?.completo),realConfirmado:ds.every(x=>x?.realConfirmado),faltantes:[...new Set(ds.flatMap(x=>x?.faltantes||['coste de albaran sin enlace']))],fuente:'Tarifas / coste_cargas v2',generado:ds.find(Boolean).generado};
      keys.forEach((k,i)=>{const x=ds[i];if(!x){d.realConfirmado=false;return;}const rs=users.get(k),den=rs.reduce((s,r)=>s+Math.abs(r.imp||0),0),share=den?Math.abs(r.imp||0)/den:1/rs.length;
        if(rs.length!==1||Math.abs(share-1)>1e-9)d.realConfirmado=false;
        for(const [f,v] of Object.entries(x.componentes))d.componentes[f]=(d.componentes[f]||0)+v*share;
      });
      d.realConfirmado=d.realConfirmado&&d.completo;
      r.costeCanonico=d;
    }
  }
  for(const l of invoices)if(!Number.isFinite(l.revenue))throw new Error('Importe de factura no numerico: '+l.id);
  for(const r of rows)r.importeAlbaran=r.imp||0;   // la VENTA de la carga (sus lineas de albaran), antes de enlazar facturas
  // Una linea de factura que no se puede atribuir a ninguna carga va en su propia fila, visible y sin coste inventado. Su
  // matricula se escribe como en las cargas de ese camion («6033MDD» de la factura = «6033 MDD»): un camion, un grupo.
  const pk=p=>String(p||'').toUpperCase().replace(/[^A-Z0-9]/g,''),matDe=new Map();
  for(const r of rows){const k=pk(r.mat);if(k&&!matDe.has(k))matDe.set(k,r.mat);}
  const soloFactura=(l,revenue,extra)=>{
    const date=l.serviceDate||l.lineDate||l.invoiceDate;
    const r={c:l.company,v:l.trip||'',cant:'',cli:l.client,mat:matDe.get(pk(l.plate))||l.plate||'',mes:date.slice(0,7),dia:date,texto:l.conceptText||'',
      tipo:tipo(l),horm:tipo(l)==='hormigonera',imp:0,importeAlbaran:null,economia:[],costeCanonico:null,soloFactura:true,...extra};
    r.economia.push(apunte(l,revenue));rows.push(r);return r;
  };
  const exacto=rows.some(r=>Array.isArray(r.facturas));
  const {facturas,...control}=exacto?enlazarPorFactura(rows,invoices,soloFactura):enlazarPorAlbaran(rows,invoices,soloFactura,byDelivery,byTrip);
  for(const r of rows)r.imp=r.economia.reduce((s,l)=>s+l.revenue,0);
  const expected=invoices.reduce((s,l)=>s+l.revenue,0),actual=rows.reduce((s,r)=>s+r.imp,0);
  if(Math.abs(expected-actual)>.01)throw new Error('La actividad no concilia con facturas');
  const completados=byCost.size?completarCostes(rows):null;   // sin export de costes de Tarifas no se estima nada
  return {rows,facturas:facturas||{},control:{facturado:expected,...control,costes:byCost.size,costesCompletados:completados,
    filasSinCoste:rows.filter(r=>r.economia.length&&!r.costeCanonico?.completo).length}};
}
// COMPLEMENTO / AJUSTE = se cobra sin carga fisica propia. Misma lista que export_rentabilidad_gesruta_actividad_v1.py (lineas de
// albaran) y que extraer_muestra_tarifas.COMPLEMENTO_KW (Tarifas), mas lo visto en 2026 en lineas sin unidad.
// Lista unificada con Tarifas el 27/09/2026 (extraer_muestra_tarifas.COMPLEMENTO_KW, commit d8e1a70): «ABONO» a secas
// atrapaba «TRANSPORTE DE ABONO ORGANICO» (abono = fertilizante, una carga real, no un abono/devolucion); Tarifas ya
// lo protege con test_datos_reales usando las dos frases especificas de abajo. «AUTOPISTA» a secas (antes «GASTOS
// AUTOPISTA») incluye tambien «GSATOS AUTOPISTAS» (error de tecleo) y «AUTOPISTA» sola.
const COMPLEMENTO_KW=['MINIMO','HORA EXTRA','HORAS EXTRA','H. EXTRA','H EXTRA','INCREMENTO','COMIDA','DIETA','DESPLAZAM','ESPERA','DEMORA',
  'PARALIZAC','SUPLEM','FESTIVO','FACTURACION MINIMA','ABONO POR ERROR','ABONO GASOIL','COMPLEMENT','COMPLEMETO','CLAUSULA','REVISION CLAUSULA','REVISON',
  'REGULARIZACION','DESCARGA ADICIONAL','EXTRAS','AUTOPISTA','DIFERENCIA','COMBUSTIBLE','PEAJE','COMISION'];
const sinTildes=s=>String(s||'').normalize('NFD').replace(/[̀-ͯ]/g,'').toUpperCase().replace(/\s+/g,' ');
export const esComplemento=texto=>{const c=sinTildes(texto);return COMPLEMENTO_KW.some(k=>c.includes(k));};
const COMPONENTES=['gasoil','conductor','material','subcontrata','peajes','vertedero','otros_albaran','otros_vehiculo','estructura'];
const FALTA_A_COMPONENTES={'litros':['gasoil'],'precio gasoil':['gasoil'],'horas':['conductor'],'coste hora nomina':['conductor'],'indirectos':['otros_vehiculo','estructura']};
// COSTE QUE FALTA (27/09/2026, Roberto: «hazlo»). El coste por carga lo pone Tarifas (coste_cargas); lo que no trae:
//  - complemento o ajuste (sin carga fisica propia: su coste ya va en las cargas del viaje), diferencia de una factura con sus
//    cargas, abono, factura rectificada con su rectificativa, e ingresos que no son transporte (cuentas 75/77/79: venta de
//    vehiculos, alquileres) -> coste 0 por regla, dicha;
//  - el resto (servicio real sin unidad o sin albaran, coste incompleto de Tarifas por faltar litros u horas, venta de producto)
//    -> ESTIMADO (E): la proporcion coste/venta, componente a componente, de las cargas con coste completo de Tarifas de su
//    empresa, tipo y mes (si no hay 20 cargas y 2.000 EUR de apoyo, de su año, de su tipo, de su empresa, del grupo). Es la regla
//    de siempre del informe para lo no medido (reparto por cuota de ingreso), ahora con el coste por carga de Tarifas.
// Nada es R: R exige evidencia por viaje (tieneEvidenciaRealViaje). Cada carga dice como se sabe su coste (metodo).
function completarCostes(rows){
  const tipoDe=r=>r.tipo||(r.soloFactura&&/^7050000/.test(String(r.economia[0]?.account||''))?'nacional':(r.horm?'hormigonera':r.nac?'nacional':'banera'));
  const niveles=r=>{const t=tipoDe(r),s=(r.impro||0)>0?'sub':'propio',m=String(r.dia||r.mes||'').slice(0,7),y=m.slice(0,4);
    return [[`${r.c}|${t}|${s}|${m}`,'de su empresa, tipo y mes'],[`${r.c}|${t}|${s}|${y}`,'de su empresa, tipo y año'],[`${r.c}|${t}|${s}`,'de su empresa y tipo'],[`${r.c}|${s}`,'de su empresa'],[`*|${s}`,'del grupo']];};
  const acc=new Map();
  for(const r of rows){
    const d=r.costeCanonico;
    if(!d||!d.completo||d.estimado||d.sinCostePropio||r.soloFactura||!(r.importeAlbaran>0))continue;
    for(const [k] of niveles(r)){let a=acc.get(k);if(!a){a={venta:0,n:0,comp:{}};acc.set(k,a);}a.venta+=r.importeAlbaran;a.n++;
      for(const c of COMPONENTES)a.comp[c]=(a.comp[c]||0)+(d.componentes[c]||0);}
  }
  const proporcion=r=>{for(const [k,txt] of niveles(r)){const a=acc.get(k);if(a&&a.n>=20&&a.venta>=2000)return {a,txt};}return null;};
  const st={complemento:0,sinCostePropio:0,estimado:0,completado:0,sinBase:0,eurEstimado:0};
  const cero=(r,metodo)=>{r.costeCanonico={componentes:{},completo:true,estimado:false,sinCostePropio:true,realConfirmado:false,faltantes:[],fuente:'Sin coste propio',metodo};};
  // parejas factura rectificada + rectificativa (misma empresa y cliente, importes opuestos) entre las lineas sin carga
  const opuestas=new Map();
  for(const r of rows)if(r.soloFactura&&!r.ajusteFactura){const k=r.c+'|'+(r.cli||'')+'|'+Math.round(Math.abs(r.imp)*100);if(!opuestas.has(k))opuestas.set(k,[]);opuestas.get(k).push(r);}
  const rectificadas=new Set();
  for(const g of opuestas.values()){const pos=g.filter(r=>r.imp>0),neg=g.filter(r=>r.imp<0);for(let i=0;i<Math.min(pos.length,neg.length);i++){rectificadas.add(pos[i]);rectificadas.add(neg[i]);}}
  for(const r of rows){
    const d=r.costeCanonico;
    if(d?.completo)continue;
    if(r.soloFactura){
      const cuenta=String(r.economia[0]?.account||'');
      if(r.ajusteFactura){cero(r,'Diferencia de la factura con las ventas de sus cargas: sin coste propio (el coste va en sus cargas).');st.sinCostePropio++;continue;}
      if(esComplemento(r.texto)){cero(r,'Complemento o ajuste de precio facturado aparte: sin coste propio.');st.complemento++;continue;}
      if(/^(75|77|79)/.test(cuenta)){cero(r,'No es transporte (venta de vehículo, alquiler u otros ingresos): sin coste de transporte.');st.sinCostePropio++;continue;}
      if(r.imp<0){cero(r,'Abono: no deshace el coste del servicio que corrige.');st.sinCostePropio++;continue;}
      if(rectificadas.has(r)){cero(r,'Factura rectificada y su rectificativa: se anulan y el servicio lleva su coste donde se volvió a facturar.');st.sinCostePropio++;continue;}
    }else if(r.complemento&&!d){cero(r,'Complemento del servicio (mínimos, esperas, dietas, cláusula de combustible…): sin coste propio, su coste va en las cargas del viaje.');st.complemento++;continue;}
    const p=proporcion(r),base=r.soloFactura?r.imp:(r.importeAlbaran||0);
    if(!p){st.sinBase++;continue;}
    // carga con albaranes sin coste en Tarifas: su coste conocido es solo de una parte -> se estima entera
    const parcial=!!d&&(d.faltantes||[]).includes('coste de albaran sin enlace'),usa=d&&!parcial?d:null;
    const faltan=usa?[...new Set((usa.faltantes||[]).flatMap(f=>FALTA_A_COMPONENTES[f]||[]))]:COMPONENTES;
    const comp={...(usa?.componentes||{})};
    for(const c of faltan)comp[c]=p.a.comp[c]/p.a.venta*base;
    const metodo=usa?`Tarifas${faltan.length?' + estimación de '+faltan.join(', ')+' (faltaba '+(usa.faltantes||[]).join(', ')+')':' (reparto de subcontratación sin acreditar)'} con la proporción coste/venta de ${p.a.n} cargas ${p.txt}.`
      :`Estimado: ${parcial?'la carga tiene albaranes sin coste en Tarifas':'sin coste por carga en Tarifas'}${r.soloFactura?' (servicio facturado sin albarán)':''}; proporción coste/venta de ${p.a.n} cargas ${p.txt}.`;
    r.costeCanonico={componentes:comp,completo:true,estimado:true,realConfirmado:false,faltantes:d?.faltantes||[],fuente:usa?'Tarifas + estimación':'Estimado',metodo,generado:d?.generado||null};
    if(usa)st.completado++;else st.estimado++;
    st.eurEstimado+=faltan.reduce((s,c)=>s+(comp[c]||0),0);
  }
  st.eurEstimado=Math.round(st.eurEstimado);
  return st;
}
const apunte=(l,revenue,extra)=>({id:l.id,invoice:l.invoiceId||'',invoiceDate:l.invoiceDate,lineDate:l.lineDate,clientId:l.clientId,client:l.client,
  load:l.load,concept:l.concept,category:l.category,account:l.account,revenue,...extra});
// INGRESO POR CARGA (26/09/2026). Cada carga se enlaza con la factura que la cobro por la cabecera de su albaran (SERIE +
// NUMFAC, en r.facturas = [[«empresa|serie-numero», venta de la carga en esa factura]]) y lleva SU venta, con la fecha y el
// cliente de esa factura. La factura agrupa las cargas del mes por tarifa: el «albaran» de su linea no identifica la carga,
// y enlazar por el repartia un mes entero entre las pocas cargas de un albaran (Prebetong 26-24: 25.362,65 € en una carga
// de 432 €) y dejaba a las demas sin ingreso. Para los filtros (cuenta, carga, concepto, categoria) la venta de la carga se
// reparte entre los grupos de lineas de su factura en su proporcion. Lo que la factura tenga de mas o de menos que las
// ventas de sus cargas (minimos, complementos, descuentos, lineas movidas de una factura a otra) va en una fila aparte de
// esa factura: no se inventa a que carga corresponde. Facturas sin cargas (manuales, rectificativas, abonos): cada linea
// en su fila, como siempre. Medido el 26/09 con los datos del 26/09: 3.451 de 3.480 facturas con cargas cuadran al centimo.
function enlazarPorFactura(rows,invoices,soloFactura){
  const byInvoice=new Map();
  for(const l of invoices){const f=l.invoiceId||'';if(!byInvoice.has(f))byInvoice.set(f,[]);byInvoice.get(f).push(l);}
  const partes=new Map();let sinFacturaLeida=0;
  for(const r of rows){
    r.enlaceIngreso='sin_factura_leida';
    for(const [f,venta] of r.facturas||[]){
      if(!f||!byInvoice.has(f)||f===''){sinFacturaLeida+=venta||0;continue;}    // su factura cae fuera del periodo leido
      if(!partes.has(f))partes.set(f,[]);partes.get(f).push([r,venta||0]);
    }
  }
  let enCargas=0,ajustes=0,sinCargas=0,facturasCuadran=0,facturasConDiferencia=0;
  const facturas={};
  for(const [f,ls] of byInvoice){
    const ps=partes.get(f)||[],fact=ls.reduce((s,l)=>s+l.revenue,0),venta=ps.reduce((s,[,v])=>s+v,0);
    if(!f||!ps.length||Math.abs(fact)<.005||Math.abs(venta)<.005){
      for(const l of ls)soloFactura(l,l.revenue,{enlaceIngreso:'factura_sin_cargas'});
      sinCargas+=fact;continue;
    }
    const grupos=new Map();
    for(const l of ls){const k=[l.account,l.load,l.concept,l.category,l.clientId].join('\u0001');let g=grupos.get(k);if(!g){g={l,revenue:0};grupos.set(k,g);}g.revenue+=l.revenue;}
    const gs=[...grupos.values()].filter(g=>Math.abs(g.revenue)>=1e-9);
    const dif=fact-venta,cuadra=Math.abs(dif)<.005;
    for(const [r,v] of ps){
      gs.forEach((g,i)=>r.economia.push(apunte(g.l,v*g.revenue/fact,{id:f+'|'+r.v+'|'+r.cant+'|'+i,lineDate:r.dia||g.l.lineDate})));
      if(!r.tipo){const mayor=gs.reduce((a,b)=>Math.abs(b.revenue)>Math.abs(a.revenue)?b:a,gs[0]);if(mayor&&tipo(mayor.l))r.tipo=tipo(mayor.l);}
      r.enlaceIngreso=r.enlaceIngreso==='factura_con_diferencia'||!cuadra?'factura_con_diferencia':'factura';
    }
    enCargas+=venta;
    if(cuadra)facturasCuadran++;
    else{
      facturasConDiferencia++;ajustes+=dif;
      const h=ls[0],aj=soloFactura(h,0,{enlaceIngreso:'ajuste_factura',ajusteFactura:true,v:''});aj.economia=[];
      gs.forEach((g,i)=>aj.economia.push(apunte(g.l,g.revenue*dif/fact,{id:f+'|ajuste|'+i})));
    }
    facturas[f]=[ps.length,Math.round(venta*100)/100,Math.round(fact*100)/100];
  }
  return {enlace:'factura',asignado:enCargas,ajustes,sinViaje:sinCargas+ajustes,sinCargas,sinFacturaLeida,facturasCuadran,facturasConDiferencia,facturas};
}
// Extracciones anteriores al 26/09/2026 (sin r.facturas): enlace por empresa + viaje + albaran de la linea de factura,
// repartido entre las cargas de ese albaran en proporcion a su venta. Se conserva solo para leer esos datos.
function enlazarPorAlbaran(rows,invoices,soloFactura,byDelivery,byTrip){
  let unmatched=0, matched=0;
  for(const l of invoices){
    let candidates=l.trip&&l.delivery?byDelivery.get(key(l.company,l.trip,l.delivery)):null;
    if(!candidates?.length&&l.trip){const rs=byTrip.get(key(l.company,l.trip,''));if(rs?.length===1)candidates=rs;}
    if(candidates?.length){
      const specific=candidates.filter(r=>r.conceptos?.includes(l.article));
      if(specific.length)candidates=specific;
    }
    if(!candidates?.length){soloFactura(l,l.revenue,{enlaceIngreso:'factura_sin_cargas'});unmatched+=l.revenue;continue;}
    matched+=l.revenue;
    const total=candidates.reduce((s,r)=>s+Math.abs(r.imp||0),0);
    let assigned=0;
    candidates.forEach((r,i)=>{
      const revenue=i===candidates.length-1?l.revenue-assigned:l.revenue*(total?Math.abs(r.imp||0)/total:1/candidates.length);
      assigned+=revenue;
      r.economia.push(apunte(l,revenue));
      r.enlaceIngreso=candidates.length>1?'albaran_repartido':'albaran';
      if(!r.tipo&&tipo(l))r.tipo=tipo(l);
    });
  }
  return {enlace:'albaran',asignado:matched,sinViaje:unmatched};
}
