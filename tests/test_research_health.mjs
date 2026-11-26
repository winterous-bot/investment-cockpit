import assert from 'node:assert/strict';
import {mkdtempSync,rmSync,writeFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {classify,health,report} from '../scripts/research-health.mjs';
import {seal} from '../company/watchlist_seal.mjs';
const d=mkdtempSync(join(tmpdir(),'research-health-')),key=Buffer.alloc(32,3),day='20261126';
try{
 assert.equal(classify('20261125',day),'stale');
 assert.equal(classify(day,day,false),'partial');
 assert.equal(classify(day,day),'ready');
 assert.equal(health(day,d,key).watchlist.state,'missing');
 writeFileSync(join(d,'growth.enc.json'),'{}');
 assert.equal(health(day,d,key).growth.state,'invalid');
 const m={version:'watchlist-v1.1',revision:'a'.repeat(32),asof:day,entries:[]};
 const dir={version:'company-directory-v1.1',asof:day,stocks:Array(4500).fill({code:'000001.SZ'})};
 writeFileSync(join(d,'watchlist.enc.json'),JSON.stringify(seal(key,m,day,'northstar-watchlist-v11')));
 writeFileSync(join(d,'company-directory.enc.json'),JSON.stringify(seal(key,dir,day,'northstar-directory-v11')));
 const h=health(day,d,key);assert.equal(h.watchlist.state,'ready');
 const r=report(day,'2026-11-26T13:30:00Z',12,h,{radar:true,growth:false,watchlist:true},{radar:'failure'});
 assert.equal(r.modules.radar.state,'failed');assert.equal(r.modules.growth.state,'waiting');assert.equal(r.modules.watchlist.state,'ready');
 assert(!JSON.stringify(r).includes('000001.SZ'));
 console.log('Research health, date gates and metadata privacy passed');
}finally{rmSync(d,{recursive:true,force:true})}
