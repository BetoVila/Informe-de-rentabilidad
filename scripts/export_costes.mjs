// Reparto del gasto contable por sociedad, año y mes en las categorías del informe (config\cuentas-contables.json), con el
// personal partido en conductores / estructura por la nómina de secciones y el gasoil por fuente. Es el MARCO COMÚN de costes
// para tarifas, el ERP y este informe: se publica cada noche en \\SERVIDOR\Programas\_RENTABILIDAD\export\costes.json.
// Uso: node export_costes.mjs <current.json.gz> <salida.json>
import fs from 'node:fs';import path from 'node:path';import zlib from 'node:zlib';import {fileURLToPath,pathToFileURL} from 'node:url';
const here=path.dirname(fileURLToPath(import.meta.url));
const {createModel}=await import(pathToFileURL(path.join(here,'..','src','model.mjs')).href);
const [src,dst]=process.argv.slice(2);
if(!src||!dst){console.error('uso: export_costes.mjs <current.json.gz> <salida.json>');process.exit(2);}
const D=JSON.parse(zlib.gunzipSync(fs.readFileSync(src)).toString('utf8'));
const M=createModel(D);
if(!D.ledger){console.error('sin contabilidad: no se publica costes.json');process.exit(1);}
const cuentas=JSON.parse(fs.readFileSync(path.join(here,'..','config','cuentas-contables.json'),'utf8'));
const FLOTA=['amortizacion','reparaciones','seguros','repuestos','alquileres','peajes','neumaticos'],COMPRAS=['aridos','subcontratacion'];
const base={dateBasis:'invoice',costMode:'real',tab:'summary',plates:[],clients:[],categories:[],loads:[],concepts:[]};
const r2=v=>Math.round(v*100)/100,pc=(a,b)=>b?Math.round(1000*a/b)/10:null;
const monthEnd=m=>{const [y,mm]=m.split('-').map(Number);return m+'-'+String(new Date(Date.UTC(y,mm,0)).getUTCDate()).padStart(2,'0');};
// titular de cada matrícula (para el surtidor de la nave): la sociedad que más partes tiene de esa matrícula
const own=new Map();for(const p of D.parts){if(!p.plate)continue;const m=own.get(p.plate)||new Map();m.set(p.owner,(m.get(p.owner)||0)+1);own.set(p.plate,m);}
const soc=cuentas.titularASociedad||{};
const socOf=owner=>{for(const [k,v] of Object.entries(soc))if(String(owner||'').toUpperCase().includes(k))return v;return null;};
const ownerOf=pl=>{const m=own.get(pl);return m?socOf([...m.entries()].sort((a,b)=>b[1]-a[1])[0][0]):null;};
function bloque(lv,f){
 if(!lv||!lv.months.length)return null;
 const cat={};for(const c of lv.expenseCategories)cat[c.id]=r2((cat[c.id]||0)+c.amount);
 const amt=id=>cat[id]||0;
 const pt=M.personnelByTramo?M.personnelByTramo(f):null,fe=pt&&pt.total?pt.structureCost/pt.total:null;
 const pers=amt('personal')+amt('dietas'),persEst=fe!=null?pers*fe:null,persCond=fe!=null?pers-persEst:null;
 const flota=FLOTA.reduce((s,id)=>s+amt(id),0),compras=COMPRAS.reduce((s,id)=>s+amt(id),0);
 const known=new Set(['combustible','personal','dietas','impuesto_sociedades',...FLOTA,...COMPRAS]);
 const gen=lv.expenseCategories.filter(c=>!known.has(c.id)).reduce((s,c)=>s+c.amount,0);
 const tot=lv.expenses;
 return {meses:lv.months,ingresos:r2(lv.income),gastos:r2(tot),resultado:r2(lv.result),margen_pct:pc(lv.result,lv.income),
  intragrupo:lv.intragrupo?{ingreso:r2(lv.intragrupo.income),gasto:r2(lv.intragrupo.expense),eliminado:!!lv.consolidado}:null,
  categorias:cat,
  personal:pt&&pt.total?{nomina_total:r2(pt.total),conductores:r2(pt.driverCost),estructura:r2(pt.structureCost),fraccion_estructura:r2(fe),
   secciones:pt.items.map(x=>({tipo:x.type,label:x.label,conductor:x.driver,coste:r2(x.cost),por_confirmar:x.unsure}))}:null,
  agregados:{gasoil:r2(amt('combustible')),personal:r2(pers),personalConductor:persCond==null?null:r2(persCond),personalEstructura:persEst==null?null:r2(persEst),
   vehiculos:r2(flota),compras_aridos_subcontratacion:r2(compras),estructura_general:r2(gen),estructura_total:persEst==null?null:r2(gen+persEst),impuesto_sociedades:r2(amt('impuesto_sociedades'))},
  pct_del_gasto:{gasoil:pc(amt('combustible'),tot),personal:pc(pers,tot),personalConductor:persCond==null?null:pc(persCond,tot),personalEstructura:persEst==null?null:pc(persEst,tot),
   vehiculos:pc(flota,tot),compras_aridos_subcontratacion:pc(compras,tot),estructura_general:pc(gen,tot),estructura_total:persEst==null?null:pc(gen+persEst,tot),
   gasoil_mas_conductor_sobre_total:persCond==null?null:pc(amt('combustible')+persCond,tot),
   gasoil_mas_conductor_sobre_gasto_sin_aridos_ni_subcontratacion:persCond==null?null:pc(amt('combustible')+persCond,tot-compras)},
  pct_de_ingresos:{estructura_total:persEst==null?null:pc(gen+persEst,lv.income),gasto_total:pc(tot,lv.income)}};
}
const out={generado:new Date().toISOString().slice(0,16),
 fuente:'Contabilidad CxConta (espejo razo_cxconta_apunte del ERP), solo meses cerrados (lastClosed '+D.ledger.meta.lastClosed+'); nómina de la gestoría por secciones (coste de empresa); GesproWin (surtidor de la nave) y partes de Access para los litros.',
 esquema:{categorias:'importes SIN IVA por categoría del informe; cada categoría = prefijos de cuenta del PGC (ver cuentas). combustible = 6280000000 (tarjeta Solred + depósito propio). aridos = 600+601+6020000006+6020000022. repuestos = repuestos y neumáticos (6020020000+6020000003). adblue = 6020000000 (AdBlue a granel para el depósito; el de gasolinera va dentro de combustible, en la tarjeta Solred; desde el 23/09/2026). otras_compras = resto de 602/608/609. peajes = 6290000070. dietas = 6290080.',
  agregados:'gasoil = combustible; personal = personal + dietas; personalConductor / personalEstructura = personal repartido con la fracción de la nómina por secciones (oficina y taller = estructura); vehiculos = amortizacion+reparaciones+seguros+repuestos+alquileres+peajes; compras = aridos+subcontratacion; estructura_general = todo lo demás (otros, tributos, financieros, otras_compras, adblue, suministros, extraordinarios; el adblue sigue aquí como cuando iba en otras_compras, para no mover las cifras de quien ya las usa: su importe está aparte en categorias.adblue); estructura_total = estructura_general + personalEstructura.',
  grupo:'Grupo_consolidado = Razo + Agetrans sin la facturación entre ellas (ingreso 705 y gasto 607 intragrupo eliminados).',
  reglas_roberto_2026_09_23:'Para el coste del camión (tarifas): de los recambios comprados se descuenta un 10 % que queda en stock; las compras de camiones no son gasto (van al 218 y entran por la amortización 681); los materiales de construcción comprados no son coste del camión. Este fichero NO aplica esas reglas: da la contabilidad tal cual.'},
 cuentas:Object.fromEntries(cuentas.gastos.map(c=>[c.id,{label:c.label,prefijos:c.prefijos}])),
 sociedades:{}};
const scopes=[['Razo',['Razo'],false],['Agetrans',['Agetrans'],false],['Grupo_suma',[],false],['Grupo_consolidado',[],true]];
const years=[...new Set(D.ledger.rows.map(r=>String(r.month).slice(0,4)))].sort();
for(const [name,companies,con] of scopes){
 const s={anios:{},meses:{}};
 for(const y of years){
  const f={...base,from:y+'-01-01',to:y+'-12-31',companies,consolidado:con};
  const b=bloque(M.ledgerView(f),f);if(!b)continue;
  // litros por fuente del año (surtidor de la nave por titular de la matrícula; partes de Access por titular)
  const wanted=companies.length?companies:['Razo','Agetrans'];
  const surt=(D.fuel?.surtidor?.rows||[]).filter(r=>String(r.month).startsWith(y)&&wanted.includes(ownerOf(r.plate))).reduce((a,r)=>a+(r.litros||0),0);
  const partes=D.parts.filter(p=>p.date.startsWith(y)&&wanted.includes(socOf(p.owner)));
  b.gasoil_litros={surtidor_nave_gesprowin:Math.round(surt),partes_access_declarados:Math.round(partes.reduce((a,p)=>a+(p.litres||0),0)),partes_access_importe:r2(partes.reduce((a,p)=>a+(p.fuel||0),0))};
  s.anios[y]=b;
  for(const m of b.meses){const fm={...base,from:m+'-01',to:monthEnd(m),companies,consolidado:con};const bm=bloque(M.ledgerView(fm),fm);if(bm){delete bm.personal;s.meses[m]={ingresos:bm.ingresos,gastos:bm.gastos,resultado:bm.resultado,categorias:bm.categorias,agregados:bm.agregados};}}
 }
 out.sociedades[name]=s;
}
fs.writeFileSync(dst,JSON.stringify(out,null,1),'utf8');
console.log(JSON.stringify({ok:true,sociedades:Object.keys(out.sociedades),anios:years,bytes:fs.statSync(dst).size}));
