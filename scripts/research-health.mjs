// Public health metadata must never contain decrypted company/industry details.
import assert from 'node:assert/strict';
import {readFileSync,existsSync} from 'node:fs';
import {join} from 'node:path';
import {execFileSync} from 'node:child_process';
import {createDecipheriv} from 'node:crypto';
import {pathToFileURL} from 'node:url';
import {keyFromEnv,priorManifest,open} from '../company/watchlist_seal.mjs';
const names=['radar','growth','watchlist'];
const paths={radar:'industry_radar.enc.json',growth:'growth.enc.json',watchlist:'watchlist.enc.json'};
const read=p=>JSON.parse(readFileSync(p,'utf8'));
const validDay=x=>typeof x==='string'&&/^\d{8}$/.test(x);
export function classify(date,target,complete=true){
 assert(validDay(date)&&validDay(target));
 return date<target?'stale':complete?'ready':'partial';
}
export function health(target,root='data',key=keyFromEnv()){
 assert(validDay(target));
 const out={};
 for(const name of names){
  const path=join(root,paths[name]);
  if(!existsSync(path)){out[name]={asof:null,state:'missing'};continue}
  try{
   const q=read(path);assert(validDay(q.asof));let complete=true;
   if(name==='radar'){
    assert(q.version===1);
    const iv=Buffer.from(q.iv,'base64'),c=Buffer.from(q.ciphertext,'base64');assert(iv.length===12&&c.length>=16);
    const d=createDecipheriv('aes-256-gcm',key,iv);d.setAAD(Buffer.from('northstar-radar-v1:'+q.asof));d.setAuthTag(c.subarray(-16));
    const plain=Buffer.concat([d.update(c.subarray(0,-16)),d.final()]).toString('utf8');
    const m=plain.match(/<script type="application\/json" id="data">([\s\S]*?)<\/script>/);
    assert(m);const x=JSON.parse(m[1]);assert(x.asof===q.asof&&x.version==='industry-radar-v1.1'&&['L1','L2'].every(l=>Array.isArray(x.levels?.[l])&&x.levels[l].length>0)&&x.breadth_health?.status==='ok');
   }else if(name==='growth'){
    execFileSync(process.execPath,['growth/seal_production.mjs','--verify',path,q.asof],{stdio:'ignore',env:{...process.env,RADAR_KEY:key.toString('hex')}});
   }else{
    const m=priorManifest(key,root);assert(m.asof===q.asof);
    const dq=read(join(root,'company-directory.enc.json')),directory=open(key,dq,'northstar-directory-v11');
    assert(dq.asof===q.asof&&directory.asof===q.asof&&directory.version==='company-directory-v1.1'&&directory.stocks.length>=4500);
    for(const e of m.entries){
     if(e.status==='unsupported')continue;
     if(e.status!=='ready'||e.report_asof!==q.asof){complete=false;continue}
     const cq=read(join(root,'companies',e.id+'.enc.json')),x=open(key,cq,'northstar-company-v11:'+e.id);
     assert(cq.asof===q.asof&&x.version==='company-report-v1.1'&&x.company?.asof===q.asof&&x.company?.code===e.code);
    }
   }
   out[name]={asof:q.asof,state:classify(q.asof,target,complete)};
  }catch{out[name]={asof:null,state:'invalid'}}
 }
 return out;
}
export function report(target,checkedAt,runId,modules,due,results){
 const states={};
 for(const name of names){
  const m=modules[name],d=due[name]===true;
  let state=m.state;
  if(!d&&state!=='ready')state='waiting';
  else if(d&&state!=='ready'&&state!=='partial'&&['failure','cancelled'].includes(results[name]))state='failed';
  states[name]={asof:m.asof,state,due:d};
 }
 return {version:1,target,checked_at:checkedAt,run_id:String(runId),modules:states};
}
function main(){
 const [target,flag,arg]=process.argv.slice(2),h=health(target);
 if(flag==='--ready'){process.exitCode=h[arg]?.state==='ready'?0:1;return}
 console.log(JSON.stringify(h));
}
if(process.argv[1]&&import.meta.url===pathToFileURL(process.argv[1]).href)main();
