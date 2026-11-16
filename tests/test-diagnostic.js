/* Offline browser-model regression: effective coverage must not overstate partial industry data. */
'use strict';
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');
async function main(){
 const original=fs.readFileSync('market-diagnostic.js','utf8');
 const ctx={
   state:{regime:'structural'},market:{},activeTab:'overview',
   render(){},renderOverview(){return''},renderRules(){return''},renderSettings(){return''},
   computeAlerts(){return[]},exposureStatus(){return null},handleAction(){},persist(){},
   regimeName:x=>x,fnum:x=>x,dateBeijing:x=>x,esc:x=>x,
   all:()=>[],$:()=>({innerHTML:''}),REGIMES:[{id:'structural',name:'结构性行情'}],
   clone:x=>JSON.parse(JSON.stringify(x)),toast(){},confirm:()=>true,
   window:{},document:{getElementById:()=>({addEventListener(){}}),addEventListener(){}},
   fetch:async()=>({ok:true,json:async()=>({
     version:3,technical:{score:3,coverage:100,asof:new Date().toISOString()},
     breadth:{score:2,coverage:60,asof:new Date().toISOString(),components:[]},
     liquidity:{score:1,coverage:100,asof:new Date().toISOString()}
   })}),
   Date,console,Math,Number,String,Array,Object
 };
 vm.runInNewContext(original,ctx,{filename:'market-diagnostic.js'});
 await new Promise(resolve=>setImmediate(resolve));
 const d=ctx.state.diagnostic.draft;
 d.trend='up';d.breadth='broad';d.scores[3]=4;
 const c=ctx.window.NorthstarDiagnostic.calculate(d);
 assert.equal(c.coverage,77,'30% technical + 12% breadth + 20% liquidity + 15% manual = 77%');
 assert.equal(c.score,2.5);
 assert.equal(c.values[1].sourceCoverage,0.6);
 d.manualOverrides.breadth=true;
 d.scores[1]=4;
 const changed=ctx.window.NorthstarDiagnostic.calculate(d);
 assert.equal(changed.coverage,85,'manual fully evidenced factor replaces partial auto coverage');
 assert.equal(changed.values[1].sourceCoverage,1);
 console.log('PASS V1.5 effective-coverage and manual-override regression');
}
main().catch(err=>{console.error(err);process.exitCode=1});
