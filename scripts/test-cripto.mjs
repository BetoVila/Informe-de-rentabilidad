import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import vm from 'node:vm';
import {criptoCifrar,criptoDescifrar} from '../src/cripto.mjs';
const texto=JSON.stringify({personas:Array.from({length:6000},(_,i)=>({n:'Peña Muñoz, José '+i,coste:1234.56+i,nota:'€ ñ á é ü'}))});
let t0=performance.now();
const c=await criptoCifrar(texto,'clave de prueba 1');
console.log('cifrar %d bytes -> %d chars base64 en %d ms',texto.length,c.length,Math.round(performance.now()-t0));
t0=performance.now();
assert.equal(await criptoDescifrar(c,'clave de prueba 1'),texto);
const derivar=Math.round(performance.now()-t0);console.log('descifrar (incluye derivar la clave): %d ms',derivar);
assert.ok(derivar<1500,'derivar la clave tarda demasiado');
await assert.rejects(()=>criptoDescifrar(c,'otra clave'),{message:'CLAVE_INCORRECTA'});
for(const pos of [0,1,20,40,c.length-6]){
 const b=Uint8Array.from(atob(c),x=>x.charCodeAt(0));const k=Math.min(Math.floor(pos*b.length/c.length),b.length-1);b[k]^=1;
 await assert.rejects(()=>criptoDescifrar(btoa(String.fromCharCode(...b)),'clave de prueba 1'),{message:'CLAVE_INCORRECTA'},'alteracion en '+k);
}
assert.notEqual(await criptoCifrar(texto,'clave de prueba 1'),c,'sal e iv deben ser aleatorios');
assert.ok(c.length<texto.length,'el texto se comprime antes de cifrar');
// el patron de build.mjs: quitar "export " y pegar dentro de un script
const fuente=(await fs.readFile(new URL('../src/cripto.mjs',import.meta.url),'utf8')).replace(/^export /gm,'');
const ctx=vm.createContext({crypto,CompressionStream,DecompressionStream,Blob,Response,TextEncoder,TextDecoder,btoa,atob,Uint8Array,String});
vm.runInContext(fuente+'\nglobalThis.cifrar=criptoCifrar;globalThis.descifrar=criptoDescifrar;',ctx);
const dentro=await ctx.cifrar('hola ñ €','k');assert.equal(await ctx.descifrar(dentro,'k'),'hola ñ €');
await assert.rejects(()=>ctx.descifrar(dentro,'x'),{message:'CLAVE_INCORRECTA'});
console.log('OK: ida y vuelta, clave incorrecta, alteración, sal aleatoria, compresión y patrón de build.');
