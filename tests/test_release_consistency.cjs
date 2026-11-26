'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs');
const read=p=>fs.readFileSync(p,'utf8');
const release=read('README.md').match(/^# 投资决策驾驶舱 V(\d+\.\d+\.\d+)/)?.[1];
assert(release,'README release version missing');
assert.equal(JSON.parse(read('release.json')).version,release);
const sw=read('sw.js'),cache=sw.match(/const CACHE='northstar-shell-([^']+)'/)?.[1];
assert.equal(cache,'v'+release);
for(const page of ['index.html','growth.html','company.html']){
 const html=read(page);
 assert(html.includes('投资决策驾驶舱 V'+release),page+' title');
 assert(html.includes('<meta name="northstar-app-version" content="'+release+'">'),page+' version metadata');
 for(const m of html.matchAll(/(?:src|href)="(\.\/[^"]+\.(?:js|css)\?v=([^"]+))"/g)){
  assert.equal(m[2],release,page+' '+m[1]);
  assert(sw.includes("'"+m[1]+"'"),page+' cache missing '+m[1]);
 }
}
assert.match(read('index.html'),/id="appUpdate"/);
assert(!/后台更新状态 · V\d/.test(read('update-status.js')));
console.log('Release version, three HTML headers, versioned assets and service-worker precache agree: V'+release);
