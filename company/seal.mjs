import {readFileSync,writeFileSync,unlinkSync} from 'node:fs';
import {randomBytes,createCipheriv} from 'node:crypto';
import {gunzipSync} from 'node:zlib';
import assert from 'node:assert/strict';
const hex=process.env.RADAR_KEY||'';
if(!/^[0-9a-fA-F]{64}$/.test(hex))throw Error('Existing fixed key missing');
const key=await crypto.subtle.importKey('raw',Buffer.from(hex,'hex'),'AES-GCM',false,['decrypt']);
if(process.argv[2]==='--growth'){
 const q=JSON.parse(readFileSync(process.argv[3],'utf8'));
 assert(q.version===2&&q.codec==='gzip'&&/^\d{8}$/.test(q.asof));
 const raw=await crypto.subtle.decrypt({name:'AES-GCM',iv:Buffer.from(q.iv,'base64'),additionalData:Buffer.from('northstar-growth-prod-v2:'+q.asof),tagLength:128},key,Buffer.from(q.ciphertext,'base64'));
 const data=gunzipSync(Buffer.from(raw),{maxOutputLength:80*1024*1024});const r=JSON.parse(data).report;
 assert(r.asof===q.asof&&r.version==='growth-scanner-v1.4.2'&&r.data_coverage_pass===true);writeFileSync(process.argv[4],data);
 console.log('Growth peer source authenticated');process.exit(0);
}
const dir=process.argv[2],src=dir+'/snapshot.json',raw=readFileSync(src),x=JSON.parse(raw),asof=x.report.asof;
assert(x.report.version==='company-fundamentals-v1.0'&&x.companies.length===5&&x.report.filing_fields_matched===20);
const iv=randomBytes(12),aad=Buffer.from('northstar-company-v1:'+asof),cipher=createCipheriv('aes-256-gcm',Buffer.from(hex,'hex'),iv);cipher.setAAD(aad);
const c=Buffer.concat([cipher.update(raw),cipher.final(),cipher.getAuthTag()]);const back=await crypto.subtle.decrypt({name:'AES-GCM',iv,additionalData:aad,tagLength:128},key,c);assert.deepEqual(Buffer.from(back),raw);
const q={version:1,asof,iv:iv.toString('base64'),ciphertext:c.toString('base64')};
const template=readFileSync(new URL('./view.html',import.meta.url),'utf8');assert.equal(template.split('__CIPHER__').length,2);writeFileSync(dir+'/company.html',template.replace('__CIPHER__',JSON.stringify(q)));unlinkSync(src);console.log('Encrypted company research report verified');
