'use strict';
/* Northstar v1.2 - markets x categories x portfolio constraint layer */
const LEGACY_BASE_RULES=clone(DEFAULT_RULES);
const CATEGORIES_V2=[{"id":"quality_growth","name":"高质量成长","shock":35},{"id":"high_beta_growth","name":"高弹性成长","shock":50},{"id":"stable_leader","name":"稳健经营龙头","shock":30},{"id":"cyclical","name":"周期与资产驱动","shock":45},{"id":"thematic","name":"题材与事件驱动","shock":65}];
const RULES_V2={"bull":{"stockSuggest":"90–110%","debtSuggest":"0–15%","debtCap":25,"totalCap":120,"clusterCap":65,"singleStressCap":6,"drawdownCap":25,"quality_growth":{"single":15,"total":55},"high_beta_growth":{"single":10,"total":35},"stable_leader":{"single":18,"total":65},"cyclical":{"single":10,"total":35},"thematic":{"single":4,"total":10}},"structural":{"stockSuggest":"65–95%","debtSuggest":"0–8%","debtCap":15,"totalCap":105,"clusterCap":50,"singleStressCap":5,"drawdownCap":22,"quality_growth":{"single":12,"total":40},"high_beta_growth":{"single":8,"total":25},"stable_leader":{"single":15,"total":50},"cyclical":{"single":8,"total":25},"thematic":{"single":3,"total":8}},"range":{"stockSuggest":"40–70%","debtSuggest":"0–3%","debtCap":8,"totalCap":80,"clusterCap":40,"singleStressCap":4,"drawdownCap":17,"quality_growth":{"single":10,"total":30},"high_beta_growth":{"single":6,"total":18},"stable_leader":{"single":12,"total":40},"cyclical":{"single":6,"total":15},"thematic":{"single":2,"total":5}},"bottoming":{"stockSuggest":"20–50%","debtSuggest":"0%","debtCap":5,"totalCap":60,"clusterCap":30,"singleStressCap":3,"drawdownCap":13,"quality_growth":{"single":7,"total":20},"high_beta_growth":{"single":4,"total":12},"stable_leader":{"single":8,"total":25},"cyclical":{"single":4,"total":10},"thematic":{"single":1,"total":3}},"bear":{"stockSuggest":"0–25%","debtSuggest":"0%","debtCap":0,"totalCap":35,"clusterCap":20,"singleStressCap":2,"drawdownCap":8,"quality_growth":{"single":4,"total":10},"high_beta_growth":{"single":2,"total":6},"stable_leader":{"single":5,"total":18},"cyclical":{"single":2,"total":6},"thematic":{"single":0,"total":0}}};
function defaultRiskGroup(symbol){return {"002475":"科技成长","002371":"科技成长","300604":"科技成长","688333":"科技成长","600487":"科技成长","600089":"电力能源","001248":"电力能源"}[String(symbol)]||"";}

function initState(){return {v:2,regime:"structural",cash:0,debt:0,watch:clone(DEFAULT_WATCH),holdings:[],liveProxyUrl:"",rules:clone(DEFAULT_RULES)};}

function migrateState(raw){
 const base=initState();
 if(!raw||!Array.isArray(raw.watch)||!Array.isArray(raw.holdings))return base;
 const old=Number(raw.v||1)<2;
 const next={...base,...raw,v:2};
 next.watch=raw.watch.map(w=>{
  let category=w.category,needsCategoryReview=Boolean(w.needsCategoryReview);
  if(!CATEGORIES.some(c=>c.id===category)){category=({growth:"high_beta_growth",core:"stable_leader",theme:"thematic",other:"thematic"})[category]||"thematic";needsCategoryReview=true;}
  return {...w,category,riskGroup:String(w.riskGroup??defaultRiskGroup(w.symbol)).trim().slice(0,36),needsCategoryReview};
 });
 const dest=clone(DEFAULT_RULES);
 for(const r of REGIMES){
  const oldRow=raw.rules?.[r.id]||{},newRow=dest[r.id],legacy=LEGACY_BASE_RULES[r.id];
  if(!old){
   for(const key of ["stockSuggest","debtSuggest","debtCap","totalCap","clusterCap","singleStressCap","drawdownCap"])if(oldRow[key]!==undefined)newRow[key]=oldRow[key];
   for(const cat of CATEGORIES)if(oldRow[cat.id]&&Number.isFinite(Number(oldRow[cat.id].single))&&Number.isFinite(Number(oldRow[cat.id].total)))newRow[cat.id]={single:Number(oldRow[cat.id].single),total:Number(oldRow[cat.id].total)};
  }else{
   for(const key of ["debtSuggest","debtCap","totalCap"])if(oldRow[key]!==undefined&&oldRow[key]!==legacy[key])newRow[key]=oldRow[key];
   for(const [prev,nextCat] of Object.entries({growth:"high_beta_growth",core:"stable_leader",theme:"thematic"})){
    const o=oldRow[prev],l=legacy[prev];
    if(!o||!l)continue;
    if(Number.isFinite(Number(o.single))&&Number(o.single)>=0&&Number(o.single)!==l.single)newRow[nextCat].single=Number(o.single);
    if(Number.isFinite(Number(o.total))&&Number(o.total)>=0&&Number(o.total)!==l.total)newRow[nextCat].total=Number(o.total);
    if(newRow[nextCat].single>newRow[nextCat].total)newRow[nextCat].total=newRow[nextCat].single;
   }
  }
 }
 next.rules=dest;
 if(!REGIMES.some(r=>r.id===next.regime))next.regime="structural";
 return next;
}

function portfolio(){
 const rows=state.holdings.filter(h=>n(h.qty)>0).map(h=>{
  const w=findWatch(h.symbol),q=quoteFor(h.symbol),price=q?.price??null,mv=price!==null?price*n(h.qty):null,costValue=n(h.qty)*n(h.cost);
  return {...h,name:w?.name||h.symbol,category:w?.category||"thematic",sector:w?.sector||"其他",riskGroup:(w?.riskGroup||"").trim(),needsCategoryReview:Boolean(w?.needsCategoryReview),q,price,mv,unitCost:n(h.cost),costValue,profit:mv!==null?mv-costValue:null};
 });
 const missing=rows.filter(row=>row.mv===null),ready=missing.length===0,stockValue=ready?rows.reduce((s,r)=>s+r.mv,0):null,equity=ready?stockValue+n(state.cash)-n(state.debt):null,valid=ready&&equity>0;
 const categoryMV=Object.fromEntries(CATEGORIES.map(c=>[c.id,0])),groupMV={};
 rows.forEach(row=>{if(row.mv!==null){categoryMV[row.category]=(categoryMV[row.category]||0)+row.mv;if(row.riskGroup)groupMV[row.riskGroup]=(groupMV[row.riskGroup]||0)+row.mv;}});
 return {rows,missing,ready,valid,stockValue,equity,totalCost:rows.reduce((s,r)=>s+r.costValue,0),categoryMV,groupMV,debtPct:valid?n(state.debt)/equity*100:null,stockPct:valid?stockValue/equity*100:null};
}

function getTriggered(w,q){if(!q||!isFresh(q)||w.thesisValid===false||w.needsCategoryReview)return null;return [...(w.levels||[])].filter(l=>n(l.price)>0&&n(l.target)>0&&q.price<=n(l.price)).sort((a,b)=>n(b.target)-n(a.target))[0]||null;}

function exposureStatus(p,w){
 if(!p.valid)return null;
 const r=rule(),cat=r[w.category]||r.thematic,cfg=CATEGORIES.find(c=>c.id===w.category)||CATEGORIES[4],own=stockPct(p,w.symbol),total=(p.categoryMV[w.category]||0)/p.equity*100;
 const groupTotal=w.riskGroup?(p.groupMV[w.riskGroup]||0)/p.equity*100:own;
 const categoryRoom=Math.max(0,cat.total-(total-own)),groupRoom=Math.max(0,r.clusterCap-(groupTotal-own)),portfolioRoom=Math.max(0,r.totalCap-(p.stockPct-own)),stressRoom=Math.max(0,r.singleStressCap/(cfg.shock/100)),portfolioStressRoom=Math.max(0,r.drawdownCap/0.2-(p.stockPct-own)),leverageBlocked=p.debtPct>r.debtCap+0.01;
 return {own,total,groupTotal,singleCap:cat.single,categoryCap:cat.total,room:categoryRoom,groupRoom,portfolioRoom,portfolioStressRoom,stressRoom,leverageBlocked,budgetCap:leverageBlocked?0:Math.max(0,Math.min(cat.single,categoryRoom,groupRoom,portfolioRoom,portfolioStressRoom,stressRoom))};
}

function computeAlerts(p){
 const alerts=[];
 if(p.missing.length)alerts.push({severity:"error",title:`有 ${p.missing.length} 只持仓缺少有效行情`,desc:"净资产与风险计算暂时停用；请刷新自动报价或核实手动价格。"});
 if(!p.rows.length)alerts.push({severity:"info",title:"尚未导入持仓",desc:"请填写持仓、现金和融资负债以计算风险。"});
 if(p.ready&&p.equity!==null&&p.equity<=0)alerts.push({severity:"error",title:"账户净资产不大于零",desc:"请检查持仓、现金和融资数据。"});
 const review=p.rows.filter(x=>x.needsCategoryReview);
 if(review.length)alerts.push({severity:"warning",title:`风险分类待复核：${review.length}只持仓`,desc:"旧分类已谨慎迁移；请在观察池确认五类风险归属，复核前暂停买价触发。"});
 const ungrouped=p.rows.filter(x=>!x.riskGroup);
 if(ungrouped.length)alerts.push({severity:"warning",title:`关联风险组未完善：${ungrouped.length}只持仓`,desc:"这些股票无法参与同组集中度检查，请在观察池填写风险组。"});
 if(p.valid){
  const r=rule();
  if(p.debtPct>r.debtCap+0.01)alerts.push({severity:"error",title:`融资比例 ${percent(p.debtPct)} 超过上限`,desc:`当前融资硬上限 ${percent(r.debtCap)}；不因触价增加融资。`});
  else if(r.debtCap>0&&p.debtPct>=r.debtCap*0.85)alerts.push({severity:"warning",title:"融资比例接近上限",desc:`当前 ${percent(p.debtPct)}，上限 ${percent(r.debtCap)}。`});
  if(p.stockPct>r.totalCap+0.01)alerts.push({severity:"error",title:`股票总敞口 ${percent(p.stockPct)} 超过上限`,desc:`本阶段股票敞口硬上限 ${percent(r.totalCap)}。`});
  const loss20=p.stockPct*0.2;
  if(loss20>r.drawdownCap+0.01)alerts.push({severity:"error",title:`组合压力风险超配：情景损失约${percent(loss20)}`,desc:`假设持有股票统一下跌20%，高于组合压力预算 ${percent(r.drawdownCap)}。属于情景假设而非市场预测。`});
  CATEGORIES.forEach(cat=>{const actual=(p.categoryMV[cat.id]||0)/p.equity*100;if(actual>r[cat.id].total+0.01)alerts.push({severity:"error",title:`${cat.name}合计 ${percent(actual)} 超配`,desc:`类别上限 ${percent(r[cat.id].total)}。`});});
  for(const [group,mv] of Object.entries(p.groupMV)){
   const actual=mv/p.equity*100;
   if(actual>r.clusterCap+0.01)alerts.push({severity:"error",title:`风险组「${group}」集中超配 ${percent(actual)}`,desc:`本阶段同组上限 ${percent(r.clusterCap)}，注意相关资产共振风险。`});
  }
  p.rows.forEach(row=>{
   const cat=r[row.category]||r.thematic,actual=row.mv/p.equity*100;
   if(actual>cat.single+0.01)alerts.push({severity:actual>cat.single*1.5?"error":"warning",title:`${row.name} 占净资产 ${percent(actual)}`,desc:`单股硬上限 ${percent(cat.single)}，超过 ${percent(actual-cat.single)}。`});
   const cfg=CATEGORIES.find(c=>c.id===row.category)||CATEGORIES[4],loss=actual*cfg.shock/100;
   if(loss>r.singleStressCap+0.01)alerts.push({severity:"error",title:`${row.name} 单股压力风险超配 ${percent(loss)}`,desc:`假设该股跌${cfg.shock}%，高于单股压力损失上限 ${percent(r.singleStressCap)}；非股价预测。`});
   if(row.q&&!isFresh(row.q))alerts.push({severity:"warning",title:`${row.name} 行情可能过期`,desc:`最近报价 ${dateBeijing(row.q.updated_at)}。`});
  });
 }
 state.watch.forEach(w=>{
  const q=quoteFor(w.symbol),level=getTriggered(w,q);
  if(!level)return;
  const e=exposureStatus(p,w),limit=e?Math.min(n(level.target),e.budgetCap):Math.min(n(level.target),(rule()[w.category]||rule().thematic).single);
  const hasRoom=!e||e.own+0.01<limit,gap=e?Math.max(0,(limit-e.own)*p.equity/100):null,cashFundable=gap===null?null:Math.min(gap,n(state.cash));
  alerts.push({severity:hasRoom&&(!e||cashFundable>0)?"info":"warning",title:`${w.name} 进入第${level.stage||"?"}档买价观察区`,desc:`最新价 ${fnum(q.price)} ≤ 预设价 ${fnum(n(level.price))}；原目标 ${percent(n(level.target))}，组合约束后累计上限 ${percent(limit)}。${e?`当前 ${percent(e.own)}，缺口 ${msign(gap)}，现金覆盖 ${msign(cashFundable)}。`:"待持仓行情完整后计算可增加仓位。"}${hasRoom?"仅供人工复核。":"风险预算不足，不宜机械加仓。"}`});
 });
 if(!market.updated_at&&state.watch.some(w=>n(w.manualPrice)<=0))alerts.push({severity:"info",title:"尚未取得自动行情",desc:"可在设置中主动刷新观察池报价，或等待每日行情更新。"});
 return alerts.sort((a,b)=>({error:0,warning:1,info:2}[a.severity]-{error:0,warning:1,info:2}[b.severity]));
}

function riskMatrixTable(title,headers,rows){
 return `<div class="matrix-box"><h3 class="matrix-title">${esc(title)}</h3><div class="matrix-scroll" role="region" aria-label="${esc(title)}" tabindex="0"><table class="risk-matrix"><thead><tr>${headers.map(v=>`<th scope="col">${esc(v)}</th>`).join("")}</tr></thead><tbody>${rows.map(row=>`<tr class="${row.id===state.regime?"matrix-active":""}"><th scope="row">${esc(row.name)}</th>${row.values.map(v=>`<td>${esc(String(v))}</td>`).join("")}</tr>`).join("")}</tbody></table></div></div>`;
}

function renderRiskMatrices(){
 const rows=REGIMES.map(s=>({id:s.id,name:s.name,r:state.rules[s.id]})),head=["市场阶段",...CATEGORIES.map(c=>c.name)];
 const all=riskMatrixTable("市场总仓位／融资／组合风险",["阶段","建议股票仓位","股票硬上限","建议融资","融资硬上限","同组上限","单股压力损失上限","组合-20%压力损失上限"],rows.map(x=>({id:x.id,name:x.name,values:[x.r.stockSuggest,percent(x.r.totalCap),x.r.debtSuggest,percent(x.r.debtCap),percent(x.r.clusterCap),percent(x.r.singleStressCap),percent(x.r.drawdownCap)]})));
 const single=riskMatrixTable("5×5 单股持仓上限",head,rows.map(x=>({id:x.id,name:x.name,values:CATEGORIES.map(c=>percent(x.r[c.id].single))})));
 const total=riskMatrixTable("5×5 同类别持仓合计上限",head,rows.map(x=>({id:x.id,name:x.name,values:CATEGORIES.map(c=>percent(x.r[c.id].total))})));
 return `<div class="section-heading"><h2>完整比例矩阵 · 5×5</h2></div><section class="panel matrix-panel"><p class="section-intro">以下展示全部5种市场状态的<strong>当前保存规则</strong>；高亮当前阶段。手机左右滑动可查看完整表格，修改上方规则并保存后即时同步。</p>${all}${single}${total}<div class="muted-note">类别压力测试假定：${esc(CATEGORIES.map(c=>`${c.name}股价下跌${c.shock}%`).join("；"))}。组合压力测试统一假设股票下跌20%。这些是静态风险情景，不是概率预测。各类别合计上限并非同时应该配置到上限。</div></section>`;
}

function renderRules(){
 const r=rule(),p=portfolio();
 const groups=p.valid?Object.entries(p.groupMV).sort((a,b)=>b[1]-a[1]).map(([name,mv])=>trackHtml(`关联组：${name}`,mv/p.equity*100,r.clusterCap)).join(""):"";
 const singleWorst=p.valid?Math.max(0,...p.rows.map(row=>(row.mv/p.equity*100)*((CATEGORIES.find(c=>c.id===row.category)||CATEGORIES[4]).shock/100))):null;
 return `<div class="intro-top"><div><div class="eyebrow">RISK BUDGET / EDITABLE</div><h1 class="page-title">动态风控规则</h1><div class="subtle">5种市场状态 × 5类股票风险 × 组合约束</div></div></div>
 <div class="panel" style="margin-top:15px"><div class="field"><label for="ruleRegime">正在编辑的市场阶段</label><select id="ruleRegime">${REGIMES.map(x=>`<option value="${x.id}" ${state.regime===x.id?"selected":""}>${esc(x.name)}</option>`).join("")}</select></div><div class="notice" style="margin-top:12px">切换市场阶段后，仓位约束和风险提醒同步变化。底部可查看全部阶段的完整比例矩阵。</div></div>
 <section class="panel" style="margin-top:11px"><div class="section-heading" style="margin:0 0 14px"><h2>市场与组合总预算</h2><span class="mini">占净资产百分比</span></div><div class="fields">
 <div class="field"><label for="stockSuggest">建议股票总仓位（文本）</label><input id="stockSuggest" value="${esc(r.stockSuggest)}" placeholder="如 65–95%"></div>
 <div class="field"><label for="totalCap">股票总敞口硬上限（%）</label><input id="totalCap" type="number" min="0" max="300" step="1" value="${r.totalCap}"></div>
 <div class="field"><label for="debtSuggest">建议融资范围（文本）</label><input id="debtSuggest" value="${esc(r.debtSuggest)}" placeholder="如 0–8%"></div>
 <div class="field"><label for="debtCap">融资硬上限（%）</label><input id="debtCap" type="number" min="0" max="100" step="1" value="${r.debtCap}"></div>
 <div class="field"><label for="clusterCap">同一关联风险组上限（%）</label><input id="clusterCap" type="number" min="0" max="300" step="1" value="${r.clusterCap}"></div>
 <div class="field"><label for="singleStressCap">单股压力损失上限（%）</label><input id="singleStressCap" type="number" min="0" max="100" step="0.5" value="${r.singleStressCap}"></div>
 <div class="field wide"><label for="drawdownCap">组合下跌20%情景损失上限（%）</label><input id="drawdownCap" type="number" min="0" max="100" step="0.5" value="${r.drawdownCap}"></div>
 </div><div class="muted-note" style="margin-top:10px">融资是允许预算，不是要求使用的目标；关联风险组要在观察池内填写。压力参数是风险情景假设。</div></section>
 <section class="panel" style="margin-top:11px"><div class="section-heading" style="margin:0 0 7px"><h2>当前阶段五类股票上限</h2></div><div class="risk-row risk-head"><span>风险类别</span><span>单股 %</span><span>同类合计 %</span></div>${CATEGORIES.map(c=>`<div class="risk-row"><span style="font-size:12px">${esc(c.name)}<small class="shock-note">压力情景 -${c.shock}%</small></span><span class="field"><input type="number" min="0" max="300" step="1" class="risk-single" data-category="${c.id}" aria-label="${esc(c.name)}单股上限" value="${r[c.id].single}"></span><span class="field"><input type="number" min="0" max="300" step="1" class="risk-total" data-category="${c.id}" aria-label="${esc(c.name)}合计上限" value="${r[c.id].total}"></span></div>`).join("")}<button class="button block" style="margin-top:15px" data-action="save-rules">保存当前阶段全部规则</button></section>
 <div class="section-heading"><h2>组合风险检查</h2></div><div class="panel">${p.valid?`${trackHtml("股票总敞口",p.stockPct,r.totalCap)}${trackHtml("融资比例",p.debtPct,r.debtCap)}${trackHtml("组合-20%情景损失",p.stockPct*0.2,r.drawdownCap)}${CATEGORIES.map(c=>trackHtml(c.name,(p.categoryMV[c.id]||0)/p.equity*100,r[c.id].total)).join("")}${groups||'<div class="muted-note">暂无有效的关联风险组持仓；请在观察池设置。</div>'}${trackHtml("最大单股压力损失",singleWorst,r.singleStressCap)}`:'<div class="empty">补齐每只持仓的有效报价后，才可计算组合约束与压力情景。</div>'}</div>
 <div class="warning-band">默认参数仅是待验证的风险预算基线，并非回测最优解。存量仓位超过限额应结合流动性制订分步处理计划，而不是机械卖出。</div>${renderRiskMatrices()}`;
}

function stockModal(symbol=null){
 const current=symbol?findWatch(symbol):null,w=current?clone(current):{symbol:"",name:"",sector:"",category:"high_beta_growth",riskGroup:"",thesis:"",levels:[],thesisValid:true};
 const levels=Array.from({length:3},(_,i)=>w.levels?.find(l=>Number(l.stage)===i+1)||{stage:i+1,price:"",target:""});
 modal(`<div class="modal-top"><div><div class="eyebrow">WATCHLIST CONFIGURATION</div><div class="modal-title">${current?"编辑观察计划":"添加观察标的"}</div></div><button class="icon-button" data-action="close-modal" aria-label="关闭">×</button></div>
 <form id="stockForm" class="fields"><div class="field"><label for="wSymbol">A股代码（6位）</label><input id="wSymbol" required inputmode="numeric" pattern="[0-9]{6}" maxlength="6" value="${esc(w.symbol)}" ${current?"readonly":""} placeholder="如：002475"></div>
 <div class="field"><label for="wName">股票名称</label><input id="wName" required value="${esc(w.name)}" placeholder="如：立讯精密"></div>
 <div class="field"><label for="wSector">中长期赛道</label><input id="wSector" value="${esc(w.sector)}" placeholder="如：半导体设备"></div>
 <div class="field"><label for="wCategory">风险类别</label><select id="wCategory">${CATEGORIES.map(c=>`<option value="${c.id}" ${w.category===c.id?"selected":""}>${esc(c.name)}</option>`).join("")}</select></div>
 <div class="field wide"><label for="wRiskGroup">关联风险组（组合集中度）</label><input id="wRiskGroup" maxlength="36" value="${esc(w.riskGroup||"")}" placeholder="如：科技成长；同组请使用同样名称"><div class="muted-note">关联风险较高的股票填相同名称；留空会提示尚未完成风险分组。</div></div>
 ${w.needsCategoryReview?'<div class="field wide"><div class="warning-band">此标的由旧版分类迁移而来。请确认新风险类别，保存后解除“分类待复核”提示。</div></div>':""}
 <div class="field wide"><label for="wThesis">研究逻辑 / 基本面观察点</label><textarea id="wThesis" placeholder="为什么关注？什么情况会推翻投资逻辑？">${esc(w.thesis)}</textarea></div>
 <div class="field wide"><label>分档买入计划（累计目标仓位）</label><div class="thresholds"><div class="threshold-labels"><span></span><span>观察买价（元）</span><span>累计目标仓位（%）</span></div>${levels.map((l,i)=>`<div class="threshold"><span class="badge-num">${i+1}档</span><input class="level-price" type="number" min="0" step="0.01" inputmode="decimal" placeholder="价格" value="${l.price??""}"><input class="level-target" type="number" min="0" max="300" step="0.5" inputmode="decimal" placeholder="仓位%" value="${l.target??""}"></div>`).join("")}</div><div class="muted-note">买价依次下降，目标仓位依次增加。触价仍需通过单股、类别、同组和组合压力预算。</div></div>
 <div class="field"><label for="wManual">手动行情价（可选，优先于自动报价）</label><input id="wManual" type="number" min="0" step="0.01" inputmode="decimal" placeholder="留空=自动" value="${w.manualPrice??""}"></div>
 <div class="field"><label for="wThesisValid">投资逻辑有效性</label><select id="wThesisValid"><option value="true" ${w.thesisValid!==false?"selected":""}>有效，可提示买价</option><option value="false" ${w.thesisValid===false?"selected":""}>待复核，暂停买价提醒</option></select></div>
 <div class="field wide"><div class="inline-fields"><button type="submit" class="button" style="flex:1">${current?"保存修改":"添加标的"}</button>${current?`<button type="button" class="button danger" data-action="delete-stock" data-symbol="${esc(w.symbol)}">删除观察</button>`:""}</div></div></form>`);
 $("#wSymbol")?.addEventListener("change",()=>{const q=market.quotes?.[$("#wSymbol").value.trim()];if(q&&$("#wName").value==="")$("#wName").value=q.name||"";});
 $("#stockForm").addEventListener("submit",ev=>{
  ev.preventDefault();const code=$("#wSymbol").value.trim();
  if(!/^\d{6}$/.test(code)){toast("请输入六位A股股票代码");return;}
  if(!current&&findWatch(code)){toast("该股票已在观察池");return;}
  const prices=all(".level-price"),targets=all(".level-target"),savedLevels=[];
  for(let i=0;i<3;i++){const p=prices[i].value.trim(),t=targets[i].value.trim();if(!p&&!t)continue;if(!p||!t||Number(p)<=0||Number(t)<=0){toast("每档价格和累计仓位必须同时填写正数");return;}if(Number(t)>300){toast("累计目标仓位不得超过300%");return;}savedLevels.push({stage:i+1,price:Number(p),target:Number(t)});}
  for(let i=1;i<savedLevels.length;i++)if(savedLevels[i].price>=savedLevels[i-1].price||savedLevels[i].target<=savedLevels[i-1].target){toast("买价须递减，累计目标须递增");return;}
  const manual=$("#wManual").value.trim();
  const next={symbol:code,name:$("#wName").value.trim(),sector:$("#wSector").value.trim()||"其他",category:$("#wCategory").value,riskGroup:$("#wRiskGroup").value.trim().slice(0,36),needsCategoryReview:false,thesis:$("#wThesis").value.trim(),levels:savedLevels,thesisValid:$("#wThesisValid").value==="true"};
  if(manual){if(Number(manual)<=0){toast("手动行情价需大于0");return;}next.manualPrice=Number(manual);next.manualAt=current?.manualPrice===next.manualPrice?current.manualAt:new Date().toISOString();}
  if(current)state.watch=state.watch.map(x=>x.symbol===code?next:x);else state.watch.push(next);
  persist();closeModal();render();toast("观察计划已保存");
 });
}
const BASE_HANDLE_ACTION_V1=handleAction;
handleAction=function(action,el){
 if(action!=='save-rules')return BASE_HANDLE_ACTION_V1(action,el);
 const old=state.rules[state.regime],scalars={};
 for(const key of ['debtCap','totalCap','clusterCap','singleStressCap','drawdownCap']){
  const v=normNum($('#'+key).value),max=(key==='totalCap'||key==='clusterCap')?300:100;
  if(v===null||v>max){toast('组合预算输入无效：'+key);return;}
  scalars[key]=v;
 }
 const limits={};
 for(const cat of CATEGORIES){
  const single=normNum($('.risk-single[data-category="'+cat.id+'"]').value);
  const total=normNum($('.risk-total[data-category="'+cat.id+'"]').value);
  if(single===null||total===null||single>total||total>300){toast('单股上限不得高于同类合计上限');return;}
  limits[cat.id]={single,total};
 }
 Object.assign(old,scalars,{stockSuggest:$('#stockSuggest').value.trim()||'0%',debtSuggest:$('#debtSuggest').value.trim()||'0%'});
 for(const cat of CATEGORIES)old[cat.id]=limits[cat.id];
 persist();render();toast('五类股票与组合风险规则已保存');
};
const BASE_WATCHCARD_V1=watchCard;
watchCard=function(w,p){
 let h=BASE_WATCHCARD_V1(w,p);
 const needle='<span class="pill">'+esc(categoryName(w.category))+'</span>';
 if(w.riskGroup)h=h.replace(needle,needle+'<span class="pill">关联组：'+esc(w.riskGroup)+'</span>');
 if(w.needsCategoryReview)h=h.replace('<span class="pill">观察中</span>','<span class="pill bad">分类待复核</span>');
 return h;
};
CATEGORIES=CATEGORIES_V2;
DEFAULT_RULES=clone(RULES_V2);
DEFAULT_WATCH=DEFAULT_WATCH.map(w=>({
 ...w,
 category:({'002475':'quality_growth','002371':'high_beta_growth','300604':'high_beta_growth','600089':'cyclical','001248':'thematic'})[w.symbol]||'thematic',
 riskGroup:defaultRiskGroup(w.symbol),
 needsCategoryReview:false
}));
state=migrateState(state);
window.__northstarRiskV2Ready=true;
persist();
render();