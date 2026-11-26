import {readFileSync,writeFileSync} from 'node:fs';
import {health,report} from './research-health.mjs';
const plan=JSON.parse(readFileSync(process.argv[2],'utf8'));
const result=report(plan.target,new Date().toISOString(),process.env.GITHUB_RUN_ID,health(plan.target),plan.due,{
 radar:process.env.RADAR_RESULT,growth:process.env.GROWTH_RESULT,watchlist:process.env.WATCHLIST_RESULT
});
writeFileSync('data/research-update-status.json',JSON.stringify(result,null,2)+'\n');
const bad=Object.values(result.modules).some(m=>m.due&&m.state!=='ready');
console.log('Research freshness audit: '+(bad?'incomplete':'all due modules authenticated'));
if(bad)process.exitCode=2;
