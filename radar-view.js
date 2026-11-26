'use strict';
/* View consumes authenticated JSON only; never executes HTML from the encrypted report. */
(function(root){
 const modes=[['discover','机会发现'],['strong','强势行业'],['breadth','扩散变化'],['risk','退潮警戒'],['all','全部行业']];
 const valid=x=>typeof x==='number'&&Number.isFinite(x), val=x=>valid(x)?x:-Infinity;
 const flags=x=>Array.isArray(x.flags)?x.flags:[];
 const has=(x,f)=>flags(x).includes(f);
 const desc=(a,get)=>a.slice().sort((x,y)=>val(get(y))-val(get(x))||String(x.code).localeCompare(String(y.code)));
 const asc=(a,get)=>a.filter(x=>valid(get(x))).slice().sort((x,y)=>get(x)-get(y)||String(x.code).localeCompare(String(y.code)));
 const change=x=>x.breadth?.breadth_change;
 function groups(items,mode){
  const a=items.slice();
  if(mode==='discover')return [
   {title:'量价前兆',note:'关注度≥1.3倍、近5日涨0–3%、相对强度不弱且排名改善。没有信号就不强行推荐。',rows:desc(a.filter(x=>has(x,'量价前兆')),x=>x.attention)},
   {title:'排名跃升 TOP 5',note:'只列排名分位改善≥20个百分点的行业。先研究是否有产业催化。',rows:desc(a.filter(x=>has(x,'排名跃升')),x=>x.rank_move).slice(0,5)},
   {title:'成交关注度异动 TOP 5',note:'只列关注度≥1.3倍的行业。放量下跌也会出现，需结合涨跌与广度。',rows:desc(a.filter(x=>has(x,'关注度异动')),x=>x.attention).slice(0,5)}];
  if(mode==='strong')return [{title:'5日相对强度 TOP 10',note:'按5日超额收益由高到低，不代表未来涨幅；留意过热及扩散收窄。',rows:desc(a,x=>x.rs5).slice(0,10)}];
  if(mode==='breadth')return [{title:'扩散增强 TOP 10',note:'最近5日上涨比例较此前5日增加至少15个百分点。',rows:desc(a.filter(x=>has(x,'扩散增强')),change).slice(0,10)},
   {title:'扩散收窄 TOP 10',note:'上涨比例减少至少15个百分点，可能是少数股票维持行业表现。',rows:asc(a.filter(x=>has(x,'扩散收窄')),change).slice(0,10)}];
  if(mode==='risk')return [{title:'退潮 / 放量走弱',note:'退潮、放量下跌或放量相对弱势；按5日超额从弱到强。',rows:asc(a.filter(x=>x.stage==='退潮'||has(x,'放量下跌')||has(x,'放量相对弱势')),x=>x.rs5)},
   {title:'过热观察',note:'原V1.1过热标记，按5日涨幅排列；不是卖出信号。',rows:desc(a.filter(x=>x.stage==='过热'),x=>x.r5)}];
  return [{title:'全部行业',note:'按5日相对强度排序；输入行业名称或代码可直接定位。',rows:desc(a,x=>x.rs5)}];
 }
 function extract(html,asof){
  if(typeof html!=='string'||!html.startsWith('<!doctype html>'))throw Error('快照内容异常');
  const m=html.match(/<script type="application\/json" id="data">([\s\S]*?)<\/script>/);
  if(!m)throw Error('快照没有可读取的行业数据');
  const d=JSON.parse(m[1]);
  if(d.version!=='industry-radar-v1.1'||d.asof!==asof||!d.levels||!['L1','L2'].every(l=>Array.isArray(d.levels[l])&&d.levels[l].length>0&&d.levels[l].length<=200&&d.levels[l].every(x=>x&&typeof x.name==='string'&&typeof x.code==='string')))throw Error('行业数据版本或日期不匹配');
  return d;
 }
 const pct=(x,sign=true)=>valid(x)?(sign&&x>0?'+':'')+(x*100).toFixed(2)+'%':'—';
 const pp=x=>valid(x)?(x>0?'+':'')+(x*100).toFixed(1)+'pp':'—';
 const ratio=x=>valid(x)?x.toFixed(2)+'倍':'—';
 function mount(host,data,prior={}){
  let level=prior.level==='L1'?'L1':'L2',mode=modes.some(x=>x[0]===prior.mode)?prior.mode:'discover',query='';
  const e=(tag,t,cls)=>{const n=document.createElement(tag);if(t!==undefined)n.textContent=t;if(cls)n.className=cls;return n};
  const button=(t,fn,active=false)=>{const n=e('button',t,'radar-chip'+(active?' selected':''));n.type='button';n.onclick=fn;n.setAttribute('aria-pressed',String(active));return n};
  const controls=e('div',undefined,'radar-controls'), levels=e('div',undefined,'radar-levels'),tabs=e('div',undefined,'radar-tabs'),search=e('input',undefined,'radar-search');search.placeholder='搜索行业名称 / 代码';search.type='search';search.setAttribute('aria-label','搜索行业');const coverage=e('div',undefined,'radar-muted'),list=e('div',undefined,'radar-results');
  const detail=e('dialog',undefined,'radar-dialog');const close=e('button','关闭','radar-chip');close.onclick=()=>detail.close();const content=e('div');detail.append(close,content);
  controls.append(levels,tabs,search,coverage);host.replaceChildren(controls,list,detail);
  function metric(label,value,cls){const b=e('div',undefined,'radar-metric');b.append(e('span',label,'radar-muted'),e('b',value,cls));return b}
  function stockTable(title,items){
   const sec=e('section',undefined,'radar-panel');sec.append(e('h3',title));
   if(!items?.length){sec.append(e('p','暂无符合条件或数据不足','radar-muted'));return sec}
   for(const x of items){const row=e('div',undefined,'radar-stock');row.append(e('b',x.name+' '+x.code),e('span','5日 '+pct(x.r5)+' · 20日 '+pct(x.r20),'radar-muted'),e('span','相对行业 '+pct(x.rs5)+' · 成交额 '+ratio(x.amount_ratio),'radar-muted'));const add=root.NorthstarWatchlistLink?.addButton(x,e);if(add)row.append(add);sec.append(row)}
   return sec;
  }
  function open(x){
   content.replaceChildren(e('h2',x.name+' · '+x.stage),e('p',flags(x).join(' · ')||'暂无观察标记','radar-muted'));
   const grid=e('div',undefined,'radar-metrics');grid.append(metric('5日涨幅',pct(x.r5)),metric('5日超额',pct(x.rs5)),metric('20日涨幅',pct(x.r20)),metric('关注度',ratio(x.attention)),metric('排名改善',pp(x.rank_move)),metric('广度变化',pp(change(x))),metric('上涨比例',pct(x.breadth?.rising5,false)),metric('当前名次','#'+x.rank));content.append(grid);
   const t=e('section',undefined,'radar-panel');t.append(e('h3','最近20个交易日的强度轨迹'),e('p','排名分位越接近0越强；日期从左至右。','radar-muted'));
   const arr=Array.isArray(x.timeline)?x.timeline:[],ns='http://www.w3.org/2000/svg',svg=document.createElementNS(ns,'svg');svg.setAttribute('viewBox','0 0 320 110');svg.setAttribute('width','100%');svg.setAttribute('aria-label','20日排名分位走势');
   let path='',ongoing=false;arr.forEach((v,i)=>{if(!valid(v.rank_pct)){ongoing=false;return}path+=(ongoing?' L':' M')+(10+i*300/Math.max(1,arr.length-1))+' '+(10+v.rank_pct*85);ongoing=true});const line=document.createElementNS(ns,'path');line.setAttribute('d',path);line.setAttribute('stroke','#83ced5');line.setAttribute('stroke-width','2.5');line.setAttribute('fill','none');svg.append(line);t.append(svg);
   const dates=e('div',undefined,'radar-range');dates.append(e('span',arr[0]?.date||'—'),e('span',arr.at(-1)?.date||'—'));t.append(dates);
   const history=e('details');history.append(e('summary','展开逐日指标'));for(const v of arr.slice().reverse()){const r=e('div',undefined,'radar-history');r.append(e('b',v.date+' · '+v.stage),e('span','排名 '+(v.rank??'—')+' · 5日超额 '+pct(v.rs5)+' · '+ratio(v.attention),'radar-muted'));history.append(r)}t.append(history);
   content.append(t,stockTable('近5日领涨股',x.breadth?.leaders),stockTable('潜在补涨观察（非买点）',x.breadth?.laggard_watch));
   if(typeof detail.showModal==='function')detail.showModal();else detail.setAttribute('open','');
  }
  function card(x){
   const b=e('button',undefined,'radar-industry');b.type='button';b.onclick=()=>open(x);const top=e('div',undefined,'radar-row');const name=e('div');name.append(e('b',x.name),e('span',' #'+x.rank+' · '+x.stage,'radar-muted'));top.append(name,e('strong',pct(x.r5),x.r5>0?'radar-up':x.r5<0?'radar-down':''));b.append(top);
   const tags=e('div',undefined,'radar-tags');flags(x).forEach(f=>tags.append(e('span',f,'radar-tag')));if(tags.childNodes.length)b.append(tags);
   const grid=e('div',undefined,'radar-metrics');grid.append(metric('关注度',ratio(x.attention)),metric('排名改善',pp(x.rank_move)),metric('广度变化',pp(change(x))));b.append(grid);return b;
  }
  function render(){
   levels.replaceChildren(button('二级细分',()=>{level='L2';query='';search.value='';render()},level==='L2'),button('一级行业',()=>{level='L1';query='';search.value='';render()},level==='L1'));
   tabs.replaceChildren(...modes.map(([id,label])=>button(label,()=>{mode=id;query='';search.value='';render()},mode===id)));
   search.hidden=mode!=='all';const a=data.levels[level],h=data.breadth_health||{};
   coverage.textContent='覆盖 '+a.length+' 个行业 · 广度有效 '+a.filter(x=>x.breadth).length+' · '+(h.status==='ok'?'数据已验证':'广度数据可能不完整');
   const items=mode==='all'&&query?a.filter(x=>x.name.includes(query)||x.code.includes(query)):a;
   list.replaceChildren();for(const g of groups(items,mode)){const s=e('section',undefined,'radar-panel');const heading=e('div',undefined,'radar-row');heading.append(e('h2',g.title),e('span',g.rows.length+'项','radar-muted'));s.append(heading,e('p',g.note,'radar-muted'));if(!g.rows.length)s.append(e('p','暂无符合条件行业','radar-empty'));else g.rows.forEach(x=>s.append(card(x)));list.append(s)}
   host.dataset.level=level;host.dataset.mode=mode;
  }
  search.oninput=()=>{query=search.value.trim();render()};render();
 }
 const api={groups,extract,mount};if(typeof module!=='undefined'&&module.exports)module.exports=api;else root.NorthstarRadarView=api;
})(typeof window!=='undefined'?window:globalThis);
