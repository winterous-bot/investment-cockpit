'use strict';
const assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs'),{webcrypto,randomBytes}=require('node:crypto');
const {extract}=require('../radar-view.js');
const code=fs.readFileSync(require('node:path').join(__dirname,'../industry-radar.js'),'utf8');
const hex=randomBytes(32).toString('hex'),old=randomBytes(32).toString('hex'),asof='20261125',rev='a'.repeat(40);
const snapshot={version:'industry-radar-v1.1',asof,levels:{L1:[{name:'甲',code:'a'}],L2:[{name:'乙',code:'b'}]}};
const html='<!doctype html><script type="application/json" id="data">'+JSON.stringify(snapshot)+'</script>';
async function encrypt(h){const key=await webcrypto.subtle.importKey('raw',Buffer.from(h,'hex'),'AES-GCM',false,['encrypt']);const iv=randomBytes(12);const c=await webcrypto.subtle.encrypt({name:'AES-GCM',iv,additionalData:new TextEncoder().encode('northstar-radar-v1:'+asof),tagLength:128},key,new TextEncoder().encode(html));return {version:1,asof,iv:iv.toString('base64'),ciphertext:Buffer.from(c).toString('base64')}}
const memory=new Map(),wait=ms=>new Promise(r=>setTimeout(r,ms));
async function main(){
 const current=await encrypt(hex),stale=await encrypt(old);
 function launch(){
  let mounted=0,urls=[];
  const nodes=new Map();
  const get=id=>{if(!nodes.has(id))nodes.set(id,{value:'',checked:true,hidden:true,children:[],dataset:{},setAttribute(){},replaceChildren(){this.children=[]},select(){}});return nodes.get(id)};
  const context={window:{NorthstarRadarView:{extract,mount(h){h.children=[1];mounted++}}},document:{getElementById:get},indexedDB:{open(){throw Error('IDB blocked')}},localStorage:{getItem:k=>memory.get(k)||null,setItem:(k,v)=>memory.set(k,v),removeItem:k=>memory.delete(k)},navigator:{storage:{persist:async()=>true}},location:{protocol:'https:'},crypto:webcrypto,atob,TextEncoder,TextDecoder,Uint8Array,AbortController,setTimeout,clearTimeout,Intl,confirm:()=>true,fetch:async u=>{urls.push(u);return {ok:true,json:async()=>u.includes('api.github.com')?[{sha:rev}]:u.includes(rev)?current:stale}}};
  vm.runInNewContext(fs.readFileSync('snapshot-store.js','utf8'),context);
  vm.runInNewContext(code,context);
  return {get,urls,mounted:()=>mounted};
 }
 let a=launch();await wait(40);
 assert.match(a.get('radarStatus').textContent,/首次使用/);
 a.get('radarKeyInput').value=hex;
 await a.get('radarSave').onclick();await wait(100);
 assert.equal(a.mounted(),1);assert.equal(memory.get('northstar-radar-fixed-key-v1'),hex);
 assert.ok(a.urls.some(u=>u.includes(rev)));
 // A fresh page with IndexedDB unavailable must recover the same fixed key automatically.
 let b=launch();await wait(100);
 assert.equal(b.mounted(),1);assert.match(b.get('radarStatus').textContent,/2026-11-25/);
 console.log('Fixed-key recovery after reload, immutable current snapshot and WebCrypto authentication passed');
}
main().catch(e=>{console.error(e);process.exitCode=1});
