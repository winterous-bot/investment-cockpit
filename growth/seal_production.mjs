import {readFileSync,writeFileSync} from 'node:fs';
import {randomBytes,createCipheriv} from 'node:crypto';
import {gzipSync,gunzipSync} from 'node:zlib';
import assert from 'node:assert/strict';
const valid=x=>{const r=x?.report;assert(r?.version==='growth-scanner-v1.4.2'&&r.model_frozen===true&&r.data_coverage_pass===true&&r.asof===r.quote_date&&/^\d{8}$/.test(r.asof)&&Array.isArray(x.rows)&&x.rows.length===r.complete_metrics&&x.rows.length>0&&x.rows.length<=7000&&Array.isArray(r.presets)&&r.presets.length===3);return r.asof};
const aad=d=>Buffer.from('northstar-growth-prod-v2:'+d);
const [src,dst,expected]=process.argv.slice(2);
const hex=process.env.RADAR_KEY||'';
if(!/^[0-9a-fA-F]{64}$/.test(hex))throw Error('RADAR_KEY missing/invalid');
const k=Buffer.from(hex,'hex'),key=await crypto.subtle.importKey('raw',k,'AES-GCM',false,['decrypt']);
async function decode(q){assert(q.version===2&&q.codec==='gzip'&&/^\d{8}$/.test(q.asof));const iv=Buffer.from(q.iv,'base64');assert(iv.length===12&&q.ciphertext.length<=20000000);const raw=await crypto.subtle.decrypt({name:'AES-GCM',iv,additionalData:aad(q.asof),tagLength:128},key,Buffer.from(q.ciphertext,'base64'));const plain=gunzipSync(Buffer.from(raw),{maxOutputLength:80*1024*1024});assert.equal(valid(JSON.parse(plain)),q.asof);return plain}
if(src==='--verify'){const q=JSON.parse(readFileSync(dst,'utf8'));await decode(q);if(expected)assert.equal(q.asof,expected);console.log('Authenticated growth snapshot: '+q.asof);process.exit(0)}
const plain=readFileSync(src),x=JSON.parse(plain),day=valid(x);if(expected)assert.equal(day,expected);
const zipped=gzipSync(plain,{level:9}),iv=randomBytes(12),cipher=createCipheriv('aes-256-gcm',k,iv);cipher.setAAD(aad(day));const enc=Buffer.concat([cipher.update(zipped),cipher.final(),cipher.getAuthTag()]);
const q={version:2,codec:'gzip',asof:day,iv:iv.toString('base64'),ciphertext:enc.toString('base64')};
assert.deepEqual(await decode(q),plain);writeFileSync(dst,JSON.stringify(q));console.log(JSON.stringify({asof:day,rows:x.rows.length,unique_candidates:x.report.preset_statistics.unique_candidates,compressed_bytes:zipped.length,cipher_file_bytes:Buffer.byteLength(JSON.stringify(q))}));
