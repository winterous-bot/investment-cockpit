// Encrypted radar delivery: AES-256-GCM, fresh 96-bit IV per update.
// Key is supplied by GitHub Actions secret, never logged or committed.
import {createCipheriv,randomBytes,createDecipheriv} from 'node:crypto';
import {readFileSync,writeFileSync} from 'node:fs';
export function seal(html,asof,keyHex){
 if(!/^[a-fA-F0-9]{64}$/.test(keyHex||''))throw Error('RADAR_KEY must be a 64-character random hexadecimal key');
 if(!/^\d{8}$/.test(asof))throw Error('invalid snapshot date');
 const iv=randomBytes(12),aad=Buffer.from('northstar-radar-v1:'+asof,'utf8'),cipher=createCipheriv('aes-256-gcm',Buffer.from(keyHex,'hex'),iv);
 cipher.setAAD(aad);
 const ciphertext=Buffer.concat([cipher.update(html,'utf8'),cipher.final(),cipher.getAuthTag()]);
 return {version:1,asof,iv:iv.toString('base64'),ciphertext:ciphertext.toString('base64')};
}
if(process.argv[2]==='--test'){
 const key=randomBytes(32).toString('hex'),sample='行业测试',o=seal(sample,'20261125',key),b=Buffer.from(o.ciphertext,'base64');
 const dec=createDecipheriv('aes-256-gcm',Buffer.from(key,'hex'),Buffer.from(o.iv,'base64'));
 dec.setAAD(Buffer.from('northstar-radar-v1:'+o.asof));dec.setAuthTag(b.subarray(-16));
 if(Buffer.concat([dec.update(b.subarray(0,-16)),dec.final()]).toString()!==sample)throw Error('roundtrip failed');
 const webkey=await globalThis.crypto.subtle.importKey('raw',Buffer.from(key,'hex'),'AES-GCM',false,['decrypt']);
 const plain=await globalThis.crypto.subtle.decrypt({name:'AES-GCM',iv:Buffer.from(o.iv,'base64'),additionalData:Buffer.from('northstar-radar-v1:'+o.asof),tagLength:128},webkey,b);
 if(new TextDecoder().decode(plain)!==sample)throw Error('WebCrypto roundtrip failed');
 let rejected=false;try{await globalThis.crypto.subtle.decrypt({name:'AES-GCM',iv:Buffer.from(o.iv,'base64'),additionalData:Buffer.from('northstar-radar-v1:20261126')},webkey,b)}catch{rejected=true}
 if(!rejected)throw Error('tamper test failed');
 console.log('AES-GCM / WebCrypto roundtrip and authentication passed');
}else{
 const [dir,out]=process.argv.slice(2);
 const snapshot=JSON.parse(readFileSync(dir+'/radar_snapshot.json','utf8'));
 if(snapshot.version!=='industry-radar-v1.1'||snapshot.asof!==snapshot.requested_end)throw Error('invalid or stale snapshot');
 const html=readFileSync(dir+'/radar.html','utf8');
 if(!html.startsWith('<!doctype html>')||html.length>5000000)throw Error('invalid HTML payload');
 writeFileSync(out,JSON.stringify(seal(html,snapshot.asof,process.env.RADAR_KEY)));
}
