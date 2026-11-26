import {readFileSync,writeFileSync,existsSync,mkdirSync,readdirSync,rmSync,copyFileSync} from 'node:fs';
import {join} from 'node:path';
import {randomBytes,createCipheriv,createDecipheriv,createHmac} from 'node:crypto';
import {gzipSync,gunzipSync} from 'node:zlib';
import assert from 'node:assert/strict';
export const LIMIT=20, CODE=/^[0-9]{6}\.(SH|SZ)$/, ID=/^[0-9a-f]{64}$/, REV=/^[0-9a-f]{32}$/, DATE=/^\d{8}$/;
export function codesValid(a){assert(Array.isArray(a)&&a.length<=LIMIT&&a.every(x=>typeof x==='string'&&CODE.test(x))&&new Set(a).size===a.length,'Invalid watchlist');return a}
export function keyFromEnv(){const h=process.env.RADAR_KEY||'';assert(/^[a-fA-F0-9]{64}$/.test(h),'Existing key missing/invalid');return Buffer.from(h,'hex')}
export function slot(key,code){assert(CODE.test(code));return createHmac('sha256',key).update('northstar-company-slot-v11:'+code).digest('hex')}
export function seal(key,obj,asof,domain,gzip=true){
 assert(DATE.test(asof));const iv=randomBytes(12),cipher=createCipheriv('aes-256-gcm',key,iv);cipher.setAAD(Buffer.from(domain+':'+asof));
 const plain=Buffer.from(JSON.stringify(obj)),src=gzip?gzipSync(plain,{level:9}):plain;
 const c=Buffer.concat([cipher.update(src),cipher.final(),cipher.getAuthTag()]);
 const q={version:1,codec:gzip?'gzip':'json',asof,iv:iv.toString('base64'),ciphertext:c.toString('base64')};
 assert.deepEqual(open(key,q,domain),obj);return q
}
export function open(key,q,domain){
 assert(q?.version===1&&['gzip','json'].includes(q.codec)&&DATE.test(q.asof)&&typeof q.ciphertext==='string'&&q.ciphertext.length<=12000000&&typeof q.iv==='string','Invalid encrypted envelope');
 const iv=Buffer.from(q.iv,'base64'),c=Buffer.from(q.ciphertext,'base64');assert(iv.length===12&&c.length>=16);
 const d=createDecipheriv('aes-256-gcm',key,iv);d.setAAD(Buffer.from(domain+':'+q.asof));d.setAuthTag(c.subarray(-16));
 const p=Buffer.concat([d.update(c.subarray(0,-16)),d.final()]);return JSON.parse((q.codec==='gzip'?gunzipSync(p,{maxOutputLength:32*1024*1024}):p).toString('utf8'))
}
const manifestDomain='northstar-watchlist-v11',requestDomain='northstar-watchlist-request-v11',directoryDomain='northstar-directory-v11';
const companyDomain=id=>'northstar-company-v11:'+id;
const read=p=>JSON.parse(readFileSync(p,'utf8'));
const write=(p,obj)=>writeFileSync(p,JSON.stringify(obj));
const empty=()=>({version:'watchlist-v1.1',revision:'empty',asof:null,entries:[]});
export function validateManifest(m,key){
 assert(m?.version==='watchlist-v1.1'&&REV.test(m.revision)&&DATE.test(m.asof)&&Array.isArray(m.entries));
 codesValid(m.entries.map(x=>x.code));
 for(const e of m.entries){assert(e.id===slot(key,e.code)&&['ready','failed','incomplete','unsupported'].includes(e.status));assert(e.report_asof===null||DATE.test(e.report_asof))}
 return m
}
export function priorManifest(key,dir){const p=join(dir,'watchlist.enc.json');if(!existsSync(p))return empty();const q=read(p),m=validateManifest(open(key,q,manifestDomain),key);assert(m.asof===q.asof);return m}
export function prepare(key,prior,mode,request){
 assert(['sync','refresh','bootstrap'].includes(mode),'Invalid mode');
 if(mode==='bootstrap'){assert(prior.revision==='empty','Watchlist already exists');return {codes:[],revision:randomBytes(16).toString('hex')}}
 if(mode==='refresh'){assert(prior.revision!=='empty','No watchlist exists');return {codes:prior.entries.map(x=>x.code),revision:prior.revision}}
 assert(typeof request==='string'&&request.length<=12000,'Invalid sync request');
 let q;try{q=JSON.parse(request)}catch{throw Error('Invalid encrypted sync request')}
 assert(q.codec==='json','Invalid request codec');
 const p=open(key,q,requestDomain);
 assert(prior.revision!=='empty'&&p?.version==='watchlist-request-v1.1'&&p.base===prior.revision&&p.asof===q.asof,'Outdated request: refresh server watchlist and prepare again');
 return {codes:codesValid(p.codes),revision:randomBytes(16).toString('hex')}
}
export function assemble(key,prior,req,work,target){
 const result=read(join(work,'results.json')),directory=read(join(work,'directory.json'));
 assert(DATE.test(result.asof)&&Array.isArray(directory)&&directory.length>=4500&&Array.isArray(result.entries)&&result.entries.length===req.codes.length);
 assert.deepEqual(result.entries.map(x=>x.code),req.codes);
 assert(!prior.asof||result.asof>=prior.asof,'Older data refused');
 const by=new Map(directory.map(x=>[x.code,x]));assert(by.size===directory.length&&directory.every(x=>CODE.test(x.code)&&typeof x.name==='string'&&typeof x.industry==='string'));
 const old=new Map(prior.entries.map(e=>[e.code,e]));const entries=[];
 mkdirSync(target,{recursive:true});mkdirSync(join(target,'companies'),{recursive:true});
 for(const e of result.entries){
  assert(CODE.test(e.code)&&['ready','failed','incomplete','unsupported'].includes(e.status));
  const id=slot(key,e.code),path=join(target,'companies',id+'.enc.json'),previous=old.get(e.code);
  let reportAsOf=null;
  if(e.status==='ready'){
   assert(/^company-\d+\.json$/.test(e.file)&&e.asof===result.asof);
   const x=read(join(work,e.file));assert(x.code===e.code&&x.asof===result.asof&&x.valuation?.share_verified===true&&['revenue','deducted_profit','cfo','capex'].every(k=>Number.isFinite(x.profile?.ttm?.[k])));
   write(path,seal(key,{version:'company-report-v1.1',company:x},x.asof,companyDomain(id)));reportAsOf=x.asof;
  }else if(previous?.report_asof&&existsSync(path)){
   const q=read(path),x=open(key,q,companyDomain(id));assert(x.version==='company-report-v1.1'&&x.company.code===e.code&&q.asof===previous.report_asof&&x.company.asof===q.asof);reportAsOf=q.asof;
  }
  entries.push({code:e.code,id,name:by.get(e.code)?.name||previous?.name||e.code,industry:by.get(e.code)?.industry||previous?.industry||'未分类',status:e.status,reason:e.reason||null,report_asof:reportAsOf});
 }
 const keep=new Set(entries.filter(e=>e.report_asof).map(e=>e.id+'.enc.json'));
 for(const f of readdirSync(join(target,'companies')))if(/^[0-9a-f]{64}\.enc\.json$/.test(f)&&!keep.has(f))rmSync(join(target,'companies',f));
 const m={version:'watchlist-v1.1',revision:req.revision,asof:result.asof,entries};validateManifest(m,key);
 // Only encrypted snapshots are written to the repository. Same request revision
 // survives daily refresh, but changes on any explicit pool replacement.
 write(join(target,'watchlist.enc.json'),seal(key,m,result.asof,manifestDomain));
 write(join(target,'company-directory.enc.json'),seal(key,{version:'company-directory-v1.1',asof:result.asof,stocks:directory},result.asof,directoryDomain));
 console.log(JSON.stringify({published_reports:entries.filter(x=>x.status==='ready').length,retained_prior:entries.filter(x=>x.status!=='ready'&&x.report_asof).length,pool_size:entries.length}))
 return m
}
async function main(){
 const [mode,root,work]=process.argv.slice(2),key=keyFromEnv(),prior=priorManifest(key,root);
 if(mode==='prepare'){
  const request=prepare(key,prior,process.env.WATCHLIST_MODE||'refresh',process.env.WATCHLIST_REQUEST||'');
  mkdirSync(work,{recursive:true});write(join(work,'request.json'),request);console.log(JSON.stringify({requested:request.codes.length}));return
 }
 if(mode==='assemble'){assemble(key,prior,read(join(work,'request.json')),work,root);return}
 throw Error('Unknown command')
}
if(process.argv[1]&&new URL(import.meta.url).pathname===process.argv[1])main().catch(()=>{console.error('Watchlist authenticated preparation or publication failed; no plaintext output.');process.exitCode=1});
