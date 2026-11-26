// Reuse previously encrypted personal research output, without another API download.
import {readFileSync,writeFileSync} from 'node:fs';
const [source,dest]=process.argv.slice(2);
const hex=process.env.RADAR_KEY||'';
if(!/^[a-fA-F0-9]{64}$/.test(hex))throw Error('RADAR_KEY missing or invalid');
const m=readFileSync(source,'utf8').match(/<script type="application\/json" id="cipher">([\s\S]*?)<\/script>/);
if(!m)throw Error('Missing encrypted source');
const x=JSON.parse(m[1]);
if(x.version!==1||x.asof!=='20261125')throw Error('Unexpected source date or version');
const key=await crypto.subtle.importKey('raw',Buffer.from(hex,'hex'),'AES-GCM',false,['decrypt']);
const plain=await crypto.subtle.decrypt({name:'AES-GCM',iv:Buffer.from(x.iv,'base64'),additionalData:new TextEncoder().encode('northstar-growth-v1:'+x.asof),tagLength:128},key,Buffer.from(x.ciphertext,'base64'));
const o=JSON.parse(new TextDecoder().decode(plain));
if(o.report.version!=='growth-scanner-v1.0'||o.report.asof!==x.asof||o.rows.length!==o.report.complete_metrics)throw Error('Source validation failed');
writeFileSync(dest,JSON.stringify(o));console.log('Prior authenticated snapshot recovered; no API requests.');
