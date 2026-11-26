'use strict';
(function(){
 const api='https://api.github.com/repos/winterous-bot/investment-cockpit/actions/workflows/research-refresh.yml/runs?branch=main&per_page=5';
 const link='https://github.com/winterous-bot/investment-cockpit/actions/workflows/research-refresh.yml';
 const raw='https://raw.githubusercontent.com/winterous-bot/investment-cockpit/main/data/research-update-status.json';
 const label={ready:'已验证最新',waiting:'尚未到更新时间',stale:'数据滞后',missing:'尚未生成',invalid:'认证失败',partial:'部分报告未完成',failed:'更新失败'};
 const modules={radar:'行业热点雷达',growth:'高质量成长股扫描器',watchlist:'个股研究观察池'};
 const fmt=d=>/^\d{8}$/.test(d||'')?d.slice(0,4)+'-'+d.slice(4,6)+'-'+d.slice(6):'—';
 const localTime=s=>{const t=new Date(s);return Number.isFinite(+t)?new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',dateStyle:'short',timeStyle:'short'}).format(t):'—'};
 async function get(u){const c=new AbortController(),t=setTimeout(()=>c.abort(),6000);try{const r=await fetch(u,{cache:'no-store',signal:c.signal});if(!r.ok)throw Error('HTTP '+r.status);return await r.json()}finally{clearTimeout(t)}}
 function e(tag,text){const n=document.createElement(tag);if(text)n.textContent=text;return n}
 const nav=document.querySelector('.module-nav');if(!nav)return;
 const panel=e('details');panel.className='radar-panel';panel.style.margin='8px 0';
 const summary=e('summary','后台更新状态 · V2.2.1');const body=e('div'),state=e('p','展开后检查后台，不影响本地快照加载。');state.className='radar-muted';
 const list=e('div'),actions=e('div');actions.className='radar-row';
 const refresh=e('button','检查后台');refresh.type='button';refresh.className='radar-chip';
 const a=e('a','手动启动后台更新');a.href=link;a.target='_blank';a.rel='noopener noreferrer';
 actions.append(refresh,a);body.append(state,list,actions,e('p','手动启动需登录 GitHub 并选择 Run workflow；完成后返回对应模块刷新。状态只反映最后一次后台审计，不代表手机已经下载。'));panel.append(summary,body);nav.after(panel);
 let busy=false,last=0;
 async function check(force=false){
  if(busy||(!force&&Date.now()-last<60000))return;
  busy=true;last=Date.now();refresh.disabled=true;state.textContent='检查后台审计及任务状态…';
  try{
   const [m,r]=await Promise.allSettled([get(raw+'?t='+Date.now()),get(api+'&t='+Date.now())]);
   list.replaceChildren();
   const d=m.status==='fulfilled'?m.value:null,run=r.status==='fulfilled'?r.value.workflow_runs?.find(x=>x.event!=='pull_request'):null;
   if(d?.version===1&&/^\d{8}$/.test(d.target)&&d.modules){
    for(const [id,name] of Object.entries(modules)){const x=d.modules[id]||{};const p=e('p',name+' · '+(label[x.state]||'未核实')+' · '+fmt(x.asof));list.append(p)}
    state.textContent='最近审计 '+localTime(d.checked_at)+'（北京时间） · 目标交易日 '+fmt(d.target);
   }else state.textContent='尚无可靠后台审计记录，请查看运行记录；保留本地快照。';
   if(run){
    const active=['queued','in_progress','waiting','requested','pending'].includes(run.status);
    const newer=!d||Date.parse(run.created_at)>Date.parse(d.checked_at);
    state.textContent+=' · '+(active?'后台任务 '+(run.status==='queued'?'排队中':'运行中'):newer?'有更新任务尚无审计结果（'+(run.conclusion||run.status)+'）':'最近任务 '+(run.conclusion==='success'?'成功':run.conclusion==='failure'?'失败':run.conclusion||run.status));
   }else state.textContent+=' · 实时任务状态暂不可核实';
   const today=new Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date()).replaceAll('-','');
   if(d&&d.target!==today)state.textContent+=' · 目标非今日，请结合交易日及更新时间判断';
  }catch{state.textContent='后台状态查询失败，本地数据不受影响。'}
  finally{busy=false;refresh.disabled=false}
 }
 panel.addEventListener('toggle',()=>{if(panel.open)check()});refresh.onclick=()=>check(true);
})();
