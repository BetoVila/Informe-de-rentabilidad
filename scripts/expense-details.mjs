const norm=s=>String(s||'').normalize('NFD').replace(/[\u0300-\u036f]/g,'').toUpperCase();
const plate=s=>(norm(s).match(/\b\d{4}[ -]?[BCDFGHJKLMNPRSTVWXYZ]{3}\b/)||[])[0]?.replace(/[^A-Z0-9]/g,'')||'';
const families=[['640','Personal: salarios'],['641','Personal: indemnizaciones'],['642','Seguridad Social'],['649','Otros gastos de personal'],
 ['607','Servicios subcontratados'],['625','Seguros'],['622','Reparaciones y mantenimiento'],['621','Alquileres y renting'],['623','Servicios profesionales'],
 ['626','Servicios bancarios'],['628','Suministros'],['681','Amortizacion'],['66','Gastos financieros'],['63','Tributos'],['67','Gastos extraordinarios'],
 ['600','Compras'],['601','Materias primas'],['602','Otros aprovisionamientos'],['629','Otros servicios']];
export function classifyExpense(concept,account='',source='',accountName=''){
 const text=norm(concept),book=families.find(([p])=>String(account).startsWith(p))?.[1]||'Sin clasificar';
 const rules=[[/\bAD[ -]?BLUE\b/,'AdBlue'],[/\b(GASOIL|GASOLEO|DIESEL)\b/,'Gasoleo'],[/\b(PEAJE|AUTOPISTA)\b/,'Peajes'],
  [/\b(NEUMATICOS?|RUEDAS?|INFLADO)\b/,'Neumaticos'],[/\b(MANTENIMIENTO|MANTENIMIETO|REPARACION|TALLER)\b/,'Reparaciones y mantenimiento']];
 const fromConcept=rules.find(([re])=>re.test(text))?.[1],fromName=rules.find(([re])=>re.test(norm(accountName)))?.[1];
 const explicit=source==='Seguros'?'Seguros':fromConcept||fromName;
 return {family:explicit||book,classification:source==='Seguros'?'Recibo de la poliza':fromConcept?'Concepto del documento':fromName?'Descripcion de la subcuenta':'Cuenta contable',
   warning:explicit&&book==='Seguros'&&explicit!=='Seguros'?'Concepto y cuenta de seguros no coinciden':''};
}
export function expenseDetails({contab,softic,seguros,gesruta}){
 const rows=[],sources=[];
 const add=r=>{
   if(!Number.isFinite(r.amount))throw new Error('Gasto sin importe numerico: '+r.id);
   const c=classifyExpense(r.concept,r.account,r.source,r.accountName);
   // El informe general no debe revelar nombres/sueldos del area privada de personal.
   if(String(r.account).startsWith('64'))r={...r,concept:c.family,accountName:c.family,supplier:'',document:'Apunte de personal',plate:''};
   rows.push({...r,...c});
 };
 if(contab){sources.push({id:'CxConta',generated:contab.metadata.leido});for(const r of contab.detalleGastos||[])add({
   id:r.id,source:'CxConta',company:({1:'Razo',2:'Agetrans'})[r.company_id]||String(r.company_id),date:r.fecha,
   amount:r.importe,concept:r.concepto,account:r.cuenta,accountName:r.cuenta_nombre,document:r.documento||'',supplier:'',
   plate:plate(r.cuenta_nombre+' '+r.concepto),basis:'Apunte contable',origin:`Asiento ${r.asiento} · linea ${r.linea} · libro ${r.libro}`,status:'Contabilizado'});}
 if(softic){
   sources.push({id:'Softic',generated:softic.generado});const accounts=new Map(softic.cuentas.map(x=>[x.id,x])),docs=new Map(softic.documentos.map(x=>[x.id,x])),vehicles=new Map(softic.vehiculos.map(x=>[x.id,x]));
   const companies=new Map(softic.empresas.map(x=>[x.id,norm(x.vat).includes('B15226095')?'Razo':norm(x.vat).includes('B15938442')?'Agetrans':x.name]));
   for(const r of softic.rows){const a=accounts.get(r.account_id[0]),d=docs.get(r.move_id[0])||{};add({id:'SOFTIC:'+r.id,source:'Softic',company:companies.get(r.company_id[0]),
     date:r.date,amount:r.balance,concept:r.name||'',account:a?.code||'',accountName:a?.name||'',document:d.ref||d.name||r.move_name,supplier:r.partner_id?.[1]||'',
     plate:vehicles.get(r.vehicle_id?.[0])?.license_plate||plate(r.name),basis:'Base contabilizada, sin IVA deducible',origin:d.name+' · apunte '+r.id,status:'Contabilizado',
     url:softic.fuente+'/web#id='+r.move_id[0]+'&model=account.move&view_type=form'});}
 }
 if(gesruta){sources.push({id:'GesRuta',generated:gesruta.generado});for(const r of gesruta.rows)add({id:r.id,source:'GesRuta',company:r.empresa,date:r.fecha,amount:r.importe,
   concept:r.concepto,account:'',accountName:'',document:r.documento,supplier:r.proveedor||'',plate:r.matricula||'',basis:'Gasto operativo',
   origin:'Viaje '+r.viaje+' · albaran '+r.albaran,status:r.enlazado_contabilidad?'Enlace contable declarado':'Sin enlace contable declarado',nif:r.nif_proveedor||''});}
 if(seguros){sources.push({id:'Seguros',generated:seguros.generado});for(const r of seguros.rows)add({id:r.id,source:'Seguros',company:r.empresa,date:String(r.fecha||'').slice(0,10),amount:r.importe,
   concept:'Poliza '+r.poliza,account:'',accountName:'',document:r.documento||'',supplier:r.proveedor||'',plate:r.matricula||'',basis:'Total del recibo',
   origin:r.empresa_fuente+' · cobertura '+String(r.cobertura_desde||'').slice(0,10)+' a '+String(r.cobertura_hasta||'').slice(0,10),status:r.devuelto?'Devuelto: revisar':'Recibo documentado',returned:r.devuelto});}
 // Solo se marcan candidatos dentro de la misma fuente. No se eliminan coincidencias automaticamente.
 const seen=new Map();for(const r of rows){if(!r.document||String(r.account).startsWith('64'))continue;const k=JSON.stringify([r.source,r.company,r.supplier,r.document,r.date,r.amount,r.concept]);
   if(seen.has(k)){r.possibleDuplicate=true;seen.get(k).possibleDuplicate=true;}else seen.set(k,r);}
 return {sources,rows,note:'Las fuentes se cotejan por separado: no se suman CxConta, Softic, GesRuta y Seguros, porque contienen copias del mismo gasto.'};
}

// Mismo detalle que la app: el ERP consulta esta proyeccion, sin volver a clasificar ni contabilizar.
export function expenseSnapshot(expenses, now=new Date()){
 const vat={Razo:'B15226095',Agetrans:'B15938442'},ids=['CxConta','Softic','GesRuta','Seguros'];
 const sources=expenses.sources.map(s=>{const date=new Date(s.generated);return {
   id:s.id,generated:Number.isFinite(+date)?date.toISOString():null,count:expenses.rows.filter(r=>r.source===s.id).length};});
 const rows=expenses.rows.map(r=>({...r,companyVat:vat[r.company]||null}));
 return {version:1,generatedAt:now.toISOString(),snapshotComplete:sources.length===4&&ids.every(id=>sources.some(s=>s.id===id&&s.generated&&s.count>0))&&rows.every(r=>r.companyVat||r.company==='Sin sociedad identificada'),
   sources,rows,note:expenses.note};
}
