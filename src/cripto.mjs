// Cifrado con clave de la capa de personal. Solo WebCrypto estandar; sin imports, porque build.mjs pega este fichero
// dentro del HTML (quitando 'export ' a principio de linea). La clave nunca se guarda, ni en disco ni en el navegador.
// Formato: version(1)=1 | sal(16) | iv(12) | AES-256-GCM( gzip(texto) ), en base64. La version va autenticada (additionalData).
const criptoB64=(u8)=>{let s='';for(let i=0;i<u8.length;i+=0x8000)s+=String.fromCharCode.apply(null,u8.subarray(i,i+0x8000));return btoa(s);};
const criptoDeB64=(b)=>Uint8Array.from(atob(b),c=>c.charCodeAt(0));
async function criptoLlave(clave,sal){
 const base=await crypto.subtle.importKey('raw',new TextEncoder().encode(clave),'PBKDF2',false,['deriveKey']);
 return crypto.subtle.deriveKey({name:'PBKDF2',salt:sal,iterations:250000,hash:'SHA-256'},base,{name:'AES-GCM',length:256},false,['encrypt','decrypt']);
}
async function criptoFlujo(bytes,Ctor,formato){
 const flujo=new Blob([bytes]).stream().pipeThrough(new Ctor(formato));
 return new Uint8Array(await new Response(flujo).arrayBuffer());
}
export async function criptoCifrar(texto,clave){
 if(!clave)throw new Error('Falta la clave');
 const sal=crypto.getRandomValues(new Uint8Array(16)),iv=crypto.getRandomValues(new Uint8Array(12)),ver=new Uint8Array([1]);
 const zip=await criptoFlujo(new TextEncoder().encode(texto),CompressionStream,'gzip');
 const ct=new Uint8Array(await crypto.subtle.encrypt({name:'AES-GCM',iv,additionalData:ver},await criptoLlave(clave,sal),zip));
 const out=new Uint8Array(29+ct.length);out.set(ver,0);out.set(sal,1);out.set(iv,17);out.set(ct,29);
 return criptoB64(out);
}
export async function criptoDescifrar(b64,clave){
 try{
  const b=criptoDeB64(b64);
  if(b[0]!==1)throw new Error('version');
  const zip=new Uint8Array(await crypto.subtle.decrypt({name:'AES-GCM',iv:b.subarray(17,29),additionalData:b.subarray(0,1)},await criptoLlave(clave,b.subarray(1,17)),b.subarray(29)));
  return new TextDecoder().decode(await criptoFlujo(zip,DecompressionStream,'gzip'));
 }catch(e){throw new Error('CLAVE_INCORRECTA');}
}
