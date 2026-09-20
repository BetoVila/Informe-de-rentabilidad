// Periodos relativos al corte: no dejar el programa anclado en agosto de 2026.
export function priorYear(iso){
 const d=new Date(iso+'T12:00:00Z'),month=d.getUTCMonth();
 d.setUTCFullYear(d.getUTCFullYear()-1);
 if(d.getUTCMonth()!==month)d.setUTCDate(0);
 return d.toISOString().slice(0,10);
}
export function quickPeriods(from,to){
 const year=Number(to.slice(0,4)),month=Number(to.slice(5,7));
 const rows=[{label:'Año '+year,from:year+'-01-01',to}];
 for(let i=0;i<month;i++){
  const first=new Date(Date.UTC(year,i,1)),last=new Date(Date.UTC(year,i+1,0));
  rows.push({label:new Intl.DateTimeFormat('es',{month:'short',timeZone:'UTC'}).format(first),from:first.toISOString().slice(0,10),to:[last.toISOString().slice(0,10),to].sort()[0]});
 }
 rows.push({label:String(year-1),from:(year-1)+'-01-01',to:(year-1)+'-12-31'});
 return rows.filter(r=>r.to>=from).map(r=>({...r,from:r.from<from?from:r.from}));
}
export function incompleteMonth(to){
 const d=new Date(to+'T12:00:00Z');
 return d.getUTCDate()!==new Date(Date.UTC(d.getUTCFullYear(),d.getUTCMonth()+1,0)).getUTCDate();
}
