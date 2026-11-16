'use strict';
/* This module deliberately has no server writes: all portfolio and diagnostic decisions stay on this device. */
(function(){
  const FACTORS=[{"id":"trend","name":"价格趋势与技术结构","weight":30,"tip":"自动：沪深300(30%)、中证500(25%)、中证1000(25%)、中证2000(20%)；按MA20/60/250、MA20斜率与20日涨幅打分。"},{"id":"breadth","name":"市场广度与行业结构","weight":20,"tip":"个股MA60趋势广度40%、同源行业趋势35%、近5日市场参与度25%；积累足够历史后才能自动评分。"},{"id":"flow","name":"资金流动与交易活跃度","weight":20,"tip":"自动仅覆盖成交活跃度：近60交易日两市成交额分位及20日量能变化；不等于ETF申购、融资余额或资金净流入。"},{"id":"earnings","name":"宏观经济与企业盈利","weight":15,"tip":"人工：PMI、新订单、社融趋势和上市公司盈利预期；必须有来源和日期。"},{"id":"policy","name":"国内政策与流动性","weight":10,"tip":"人工：货币财政与资本市场政策，区分政策发布和实际见效。"},{"id":"overseas","name":"海外金融环境","weight":5,"tip":"人工：美股科技、美元、美债利率、人民币和重大海外风险。"}];
    const STAGES={bull:'牛市主升',structural:'结构性行情',range:'震荡市',bottoming:'震荡筑底',bear:'熊市'};
  const RISK={normal:'正常',warning:'警戒',severe:'严重'};
  const scoreBand=n=>n>=4?'强支持':n>=3?'偏支持':n>=2?'中性':n>=1?'偏不利':'明显不利';
  function initialDraft(){return {scores:[null,null,null,null,null,null],technicalManual:false,manualOverrides:{trend:false,breadth:false,flow:false},trend:'unknown',breadth:'unknown',priorDecline:false,bottoms:{price:false,momentum:false,breadth:false},stable:false,risk:'normal',event:'',pro:'',contra:'',stage:state.regime,reason:''};}
    function ensure(){
 if(!state.diagnostic||typeof state.diagnostic!=='object')state.diagnostic={version:2,draft:initialDraft(),history:[]};
 const d=state.diagnostic;
 if(!d.draft||typeof d.draft!=='object')d.draft=initialDraft();
 if(!Array.isArray(d.draft.scores))d.draft.scores=[null,null,null,null,null,null];
 if((Number(d.version)||1)<2){
  // Migrate only the active draft; historical snapshots retain their /100 denominator.
  d.draft.scores=d.draft.scores.map(x=>x===null||x===''||x===undefined?null:Math.max(0,Math.min(5,Math.round(Number(x)/10)/2)));
  d.version=2;
 }
 if(!d.draft.manualOverrides||typeof d.draft.manualOverrides!=='object')
  d.draft.manualOverrides={trend:!!d.draft.technicalManual,breadth:false,flow:false};
 if(!d.draft.bottoms||typeof d.draft.bottoms!=='object')d.draft.bottoms={price:false,momentum:false,breadth:false};
 if(!Array.isArray(d.history))d.history=[];
 return d;
}
    let signalCache=null;
  let signalError='自动数据尚未下载';
  const SIGNAL_KEYS=['technical','breadth','liquidity'];
  const half=n=>Math.max(0,Math.min(5,Math.round(Number(n)*2)/2));
  function recentSignal(key){
    const b=signalCache&&signalCache[key];
    if(!b||b.score===null||b.score===undefined||!Number.isFinite(Number(b.score)))return null;
    const ts=Date.parse(b.asof||'');
    if(!Number.isFinite(ts)||Date.now()-ts>8*86400000||ts>Date.now()+86400000)return null;
    const n=Number(b.score);
    if(n<0||n>5)return null;
    return {...b,score:half(n)};
  }
  async function loadSignals(){
    const url='./data/market_signals.json?v='+Date.now();
    try{
      const response=await fetch(url,{cache:'no-store'});
      if(!response.ok)throw new Error('HTTP '+response.status);
      const payload=await response.json();
      if(payload?.version!==3||!payload.technical||!payload.breadth||!payload.liquidity)
        throw new Error('自动指标版本或结构不匹配');
      signalCache=payload;
      signalError='';
      return true;
    }catch(e){signalError=String(e.message||e);return false;}
  }
  function freshTechnical(){return recentSignal('technical');}
    function calculate(d){
  const tech=recentSignal('technical');
  const values=FACTORS.map((f,i)=>{
    const auto=i<3?recentSignal(SIGNAL_KEYS[i]):null;
    const override=Boolean(d.manualOverrides?.[f.id]||(i===0&&d.technicalManual));
    if(auto&&!override){
      const raw=Number(auto.coverage);
      const sourceCoverage=Number.isFinite(raw)?Math.max(0,Math.min(1,raw/100)):0;
      if(sourceCoverage>0)return {value:auto.score,source:i===2?'自动·成交活跃代理':'自动·公开数据',sourceCoverage,auto};
    }
    const raw=d.scores?.[i],num=raw===null||raw===''||raw===undefined?NaN:Number(raw);
    return Number.isFinite(num)&&num>=0&&num<=5&&Math.abs(num*2-Math.round(num*2))<1e-8
      ?{value:num,source:'人工',sourceCoverage:1}:{value:null,source:'待评估',sourceCoverage:0};
  });
  const weightedEvidence=FACTORS.reduce((v,f,i)=>v+f.weight*values[i].sourceCoverage,0);
  const coverage=Math.round(weightedEvidence*10)/10;
  const score=weightedEvidence?half(FACTORS.reduce((v,f,i)=>v+f.weight*values[i].sourceCoverage*(values[i].value??0),0)/weightedEvidence):null;
  const bottoms=['price','momentum','breadth'].filter(k=>Boolean(d.bottoms?.[k])).length;
  const enough=coverage>=70&&d.trend!=='unknown'&&d.breadth!=='unknown';
  let suggestion=null,candidate=null;
  if(d.trend==='down'){
    if(d.priorDecline&&bottoms>=2){candidate='bottoming';suggestion=d.stable?'bottoming':'bear';}
    else suggestion='bear';
  }else if(d.trend==='up'){
    suggestion=d.breadth==='weak'?'range':d.breadth==='broad'&&values[0].value>=3.5&&values[2].value>=3&&d.stable?'bull':'structural';
  }else if(d.trend==='sideways'){
    if(d.priorDecline&&bottoms>=2&&d.stable)suggestion='bottoming';
    else suggestion=d.breadth==='narrow'&&values[0].value>=2.5&&values[2].value>=2.5?'structural':'range';
  }
  const contradictory=(d.trend==='up'&&values[0].value!==null&&values[0].value<2)||(d.trend==='down'&&values[0].value!==null&&values[0].value>=3.5);
  const confidence=!enough?'证据不足':coverage>=85&&d.stable&&!contradictory?'较高':coverage>=70&&!contradictory?'中等':'偏低';
  return {tech,values,coverage,score,bottoms,enough,suggestion:enough?suggestion:null,candidate,candidateLabel:candidate&&!d.stable?'筑底信号待持续确认':'',confidence,contradictory};
}
    function readForm(){
 const old=ensure().draft;
 const el=id=>document.getElementById(id);
 const overrides={trend:el('diagManual0').checked,breadth:el('diagManual1').checked,flow:el('diagManual2').checked};
 const scores=FACTORS.map((f,i)=>{
  if(i<3&&recentSignal(SIGNAL_KEYS[i])&&!overrides[f.id])return null;
  const raw=el('diagScore'+i)?.value.trim();
  if(raw===undefined||raw==='')return null;
  const x=Number(raw);
  if(!Number.isFinite(x)||x<0||x>5||Math.abs(x*2-Math.round(x*2))>1e-8)
    throw new Error('六维评分请输入0—5且以0.5分递增的数字，或留空');
  return x;
 });
 const trend=el('diagTrend').value,breadth=el('diagBreadth').value,risk=el('diagRisk').value;
 if(!['unknown','up','sideways','down'].includes(trend)||!['unknown','broad','narrow','weak'].includes(breadth)||!Object.hasOwn(RISK,risk))throw new Error('诊断选项有误');
 const stage=el('diagStage').value;
 if(!Object.hasOwn(STAGES,stage))throw new Error('市场阶段有误');
 return {...old,scores,manualOverrides:overrides,technicalManual:overrides.trend,
  trend,breadth,priorDecline:el('diagPreviousDecline').checked,
  bottoms:{price:el('diagBottomPrice').checked,momentum:el('diagBottomMomentum').checked,breadth:el('diagBottomBreadth').checked},
  stable:el('diagStable').checked,risk,event:el('diagEvent').value.trim().slice(0,600),
  pro:el('diagPro').value.trim().slice(0,1200),contra:el('diagContra').value.trim().slice(0,1200),
  stage,reason:el('diagReason').value.trim().slice(0,600)};
}
    function riskText(d){
    if(d.risk==='severe')return '严重风险：暂停新增风险仓位的价格触发预算；不得据此自动卖出存量资产。已保存的5×5硬上限不被静默修改。';
    if(d.risk==='warning')return '警戒：暂缓增加融资与高波动仓位，优先核查近期风险变化。';
    return '正常：遵循已确认市场阶段及5×5组合约束。';
  }
  function statusHTML(result,d){
    const status=result.enough?STAGES[result.suggestion]:'证据不足';
    const className=result.enough?'good':'warn';
    return `<div class="diag-summary"><div class="metric"><div class="label">已评分维度的加权均值</div><div class="val">${result.score===null?'—':result.score.toFixed(1)+' /5'}</div><div class="hint">有效证据覆盖权重 ${result.coverage}% · 子项缺失按真实权重折算</div></div><div class="metric"><div class="label">模型规则建议</div><div class="val" style="font-size:18px">${esc(status)}</div><div class="hint">${esc(result.confidence)} · ${result.enough?'非未来涨跌概率':'不触发阶段推断'}</div></div></div>
    ${result.candidateLabel?`<div class="notice">${esc(result.candidateLabel)}：当前不能直接升级为已确认筑底。</div>`:''}
    ${result.contradictory?'<div class="warning-band">当前人工趋势判断与技术评分明显冲突，请检查日期及判断依据。</div>':''}
    <div class="notice">${esc(riskText(d))}</div>`;
  }
  function entryCard(){
    const d=ensure().draft,result=calculate(d);
    return `<section class="panel diag-entry" style="margin-top:12px"><div class="row-between"><div><div class="eyebrow">MARKET REGIME DIAGNOSTICS</div><div style="font-size:16px;font-weight:800;margin-top:5px">市场阶段诊断</div></div><span class="pill ${result.enough?'good':'warn'}">${result.enough?'证据覆盖 '+result.coverage+'%':'待完善证据'}</span></div>
      <div class="diag-entry-row"><span>模型建议：<b>${esc(result.enough?STAGES[result.suggestion]:'证据不足')}</b></span><span>已确认：<b>${esc(regimeName(state.regime))}</b></span></div>
      <div class="muted-note">模型不会自动修改市场阶段；四宽基趋势、市场广度及两市成交活跃度可自动评分；部分数据缺失时请人工核验。</div>
      <button class="button secondary block" style="margin-top:12px" data-tab-jump="diagnostic">进入市场阶段诊断</button></section>`;
  }
  function renderBreadthBreakdown(){
  const b=signalCache?.breadth;
  if(!b)return '';
  const parts=(b.components||[]).map(c=>{
    const days=c.days==null?'':` · 已累积 ${c.days}/${c.need_days} 个交易日`;
    const sample=c.sample?` · 样本 ${c.sample} 只`:'';
    const score=c.score==null?'待数据齐备':`${c.score}/5分`;
    return `<div class="diag-breakdown-row"><div class="row-between"><b>${esc(c.name)}（权重 ${Math.round(c.weight*100)}%）</b><b>${score}</b></div>
    <div class="muted-note">数据覆盖：${c.coverage||0}%${days}${sample}</div>
    ${c.issue?`<div class="muted-note" style="color:#dcbb81">${esc(c.issue)}</div>`:''}</div>`;
  }).join('');
  const info=b.spot||{};
  const spot=[info.rising_stock_ratio!=null?`当日沪深A股上涨家数比 ${(info.rising_stock_ratio*100).toFixed(1)}%`:'',
       info.rising_industry_ratio!=null?`当日行业上涨比 ${(info.rising_industry_ratio*100).toFixed(1)}%（${esc(info.industry_source||'')}）`:''].filter(Boolean).join('；');
  return `<div class="diag-breakdown"><div style="font-size:12px;font-weight:750">三项市场广度 · 模型内有效覆盖 ${b.coverage||0}%</div>${parts}
    ${spot?`<div class="muted-note">当日辅助参考（不代替60日趋势）：${spot}</div>`:''}
    ${b.source_taxonomy?`<div class="muted-note">行业分类：${esc(b.source_taxonomy)}，不同供应商不拼接历史。</div>`:''}</div>`;
}
  function renderDiagnostic(){
 const d=ensure().draft,result=calculate(d);
 const allIndex=signalCache?.technical?.indices||[];
 const idxText=allIndex.length?allIndex.map(x=>x.name+' '+x.score+'/5（权重'+Math.round(x.weight*100)+'% · '+x.asof+'）').join('；'):'尚未获得有效的四宽基数据';
 const dimensionFields=FACTORS.map((f,i)=>{
  const auto=i<3?recentSignal(SIGNAL_KEYS[i]):null;
  const overridden=Boolean(d.manualOverrides?.[f.id]);
  const activeAuto=Boolean(auto&&!overridden);
  const val=activeAuto?auto.score:d.scores[i];
  const source=result.values[i].source;
  const trace=auto?('数据日期 '+auto.asof+' · 采集覆盖 '+auto.coverage+'% · '+(auto.method||'')):
       (i<3?'自动数据不可用、过期或历史积累不足；可人工评分，或等待后台采集。':'');
  const issue=i<3?(signalCache?.[SIGNAL_KEYS[i]]?.issues||[]).join('；'):'';
  return `<div class="diag-factor"><div class="row-between"><label for="diagScore${i}">${esc(f.name)} <span class="mini">${f.weight}%</span></label><span class="mini">${esc(source)}</span></div>
    ${i<3?`<label class="diag-check"><input id="diagManual${i}" type="checkbox" ${overridden?'checked':''}>改为人工评分（勾选后立即解锁）</label>`:''}
    <input id="diagScore${i}" type="number" min="0" max="5" step="0.5" inputmode="decimal" value="${val===null||val===undefined?'':val}" ${activeAuto?'disabled':''} placeholder="0—5分，每0.5分一档" aria-label="${esc(f.name)}评分">
    ${trace?`<div class="muted-note">${esc(trace)}</div>`:''}
    ${issue?`<div class="muted-note" style="color:#dcbb81">缺失信息：${esc(issue)}</div>`:''}
    ${i===1?renderBreadthBreakdown():""}
    <div class="muted-note">${esc(f.tip)}</div></div>`;
 }).join('');
 const checks=[['price','价格低点趋稳 / 不再持续创新低'],['momentum','短期均线或MACD下跌动能修复'],['breadth','市场广度或资金参与有所改善']].map(([k,t])=>`<label class="diag-check"><input id="diagBottom${k[0].toUpperCase()+k.slice(1)}" type="checkbox" ${d.bottoms[k]?'checked':''}>${esc(t)}</label>`).join('');
 const history=ensure().history.slice(-6).reverse().map(h=>`<div class="diag-history-item"><div><b>${esc(h.applied?'已应用':'仅记录')} · ${esc(STAGES[h.stage]||'未知')}</b><div class="mini">${dateBeijing(h.at)} · 加权均值 ${h.score??'—'}/${h.scoringVersion===2?5:100} · 证据覆盖 ${h.coverage}%</div></div><span class="pill">${esc(RISK[h.risk]||'正常')}</span></div>`).join('');
 return `<div class="intro-top"><div><div class="eyebrow">MARKET REGIME DIAGNOSTICS / V1.5</div><h1 class="page-title">市场阶段诊断</h1><div class="subtle">四宽基趋势 × 三维广度 × 真实覆盖率 × 人工确认</div></div></div>
   <section class="panel" style="margin-top:14px">${statusHTML(result,d)}<div class="divider"></div><div class="row-between"><span class="mini">当前实际应用阶段</span><b>${esc(regimeName(state.regime))}</b></div><div class="muted-note" style="margin-top:8px">本模型用于未来1—3个月的风险预算；历史广度需累计5/60/80个交易日后才能参与评分。成交额不代表资金净流入。</div></section>
   <div class="section-heading"><h2>一、自动指标与来源</h2><span class="pill">公开行情</span></div>
   <section class="panel"><div class="muted-note">${esc(idxText)}</div><div class="muted-note" style="margin-top:9px">数据源：${esc(signalCache?.source||signalError)}。最近生成时间：${esc(signalCache?.updated_at||'—')}。</div>
   <button class="button secondary block" style="margin-top:12px" data-action="diag-refresh-data">重新读取自动市场指标</button>
   <div class="muted-note" style="margin-top:8px">重新读取的是GitHub上最新发布的行情指标，不会主动爬取实时市场数据。每个维度都有独立的人工覆盖选项；自动结果超过8天不再使用。</div></section>
   <div class="section-heading"><h2>二、六维评分</h2><span class="mini">满分5分，每0.5分一档 · 权重100%</span></div>
   <section class="panel"><div class="diag-scores-tip">评分口径：0—0.5明显不利；1—1.5偏不利；2—2.5中性；3—3.5偏支持；4—5强支持。自动指标若缺失请人工判断；输入变化后点「预览诊断」更新结论。</div>${dimensionFields}</section>
   <div class="section-heading"><h2>三、趋势与广度识别</h2></div>
   <section class="panel"><div class="fields">
     <div class="field"><label for="diagTrend">中期主要趋势</label><select id="diagTrend">${[['unknown','尚未判断'],['up','向上'],['sideways','震荡'],['down','向下']].map(([v,t])=>`<option value="${v}" ${d.trend===v?'selected':''}>${t}</option>`).join('')}</select></div>
     <div class="field"><label for="diagBreadth">市场广度</label><select id="diagBreadth">${[['unknown','缺乏证据'],['broad','广泛扩散'],['narrow','少数行业领涨'],['weak','多数股票疲弱']].map(([v,t])=>`<option value="${v}" ${d.breadth===v?'selected':''}>${t}</option>`).join('')}</select></div>
   </div><div class="divider"></div><label class="diag-check"><input id="diagPreviousDecline" type="checkbox" ${d.priorDecline?'checked':''}>此前经历显著的中期下跌（筑底判断前提）</label>${checks}
   <div class="divider"></div><label class="diag-check"><input id="diagStable" type="checkbox" ${d.stable?'checked':''}>已观察至少5个交易日或两个周线收盘进行确认（由我核验）</label>
   <div class="muted-note" style="margin-top:8px">先有明显下跌、再有修复证据、最后持续确认，才可能判为震荡筑底。单日反弹不能替代验证。</div></section>
   <div class="section-heading"><h2>四、系统性风险与事实证据</h2></div>
   <section class="panel"><div class="field"><label for="diagRisk">独立风险等级（人工核验）</label><select id="diagRisk">${[['normal','正常'],['warning','警戒'],['severe','严重']].map(([v,t])=>`<option value="${v}" ${d.risk===v?'selected':''}>${t}</option>`).join('')}</select></div>
    <div class="field" style="margin-top:12px"><label for="diagEvent">事件和风险描述（可选）</label><textarea id="diagEvent" maxlength="600" placeholder="重大波动、流动性变化及信息来源">${esc(d.event||'')}</textarea></div>
    <div class="field" style="margin-top:12px"><label for="diagPro">支持本次判断的事实</label><textarea id="diagPro" maxlength="1200" placeholder="指标数值、来源和日期；建议至少两项">${esc(d.pro||'')}</textarea></div>
    <div class="field" style="margin-top:12px"><label for="diagContra">反对证据 / 尚未满足的条件</label><textarea id="diagContra" maxlength="1200" placeholder="哪些条件不成立？什么会推翻判断？">${esc(d.contra||'')}</textarea></div></section>
   <div class="section-heading"><h2>五、人工最终确认</h2></div>
   <section class="panel"><div class="field"><label for="diagStage">拟应用市场阶段</label><select id="diagStage">${REGIMES.map(x=>`<option value="${x.id}" ${d.stage===x.id?'selected':''}>${esc(x.name)}</option>`).join('')}</select></div>
     <div class="field" style="margin-top:12px"><label for="diagReason">人工覆盖理由（模型不同或证据不足时必填）</label><textarea id="diagReason" maxlength="600" placeholder="简述人工判断依据">${esc(d.reason||'')}</textarea></div>
     <div class="action-toolbar"><button class="button secondary" data-action="diag-preview">预览诊断</button><button class="button secondary" data-action="diag-save">保存判断记录</button><button class="button" data-action="diag-apply">确认并应用到风控矩阵</button></div>
     <div class="muted-note" style="margin-top:10px">预览保存草稿；保存判断记录不改变当前阶段；确认并应用才改变风控矩阵。不会自动下单。严重风险会阻止新增价格触发仓位预算。</div></section>
   <div class="section-heading"><h2>六、最近判断记录</h2><span class="mini">本机最近30条</span></div>
   <section class="panel">${history||'<div class="empty">尚无诊断记录；完成评分后点击「保存判断记录」。</div>'}<div class="muted-note" style="margin-top:10px">历史评分保留旧制单位标记，防止把100分制和5分制混淆。记录只存储在本机及完整JSON备份中。</div></section>
   <button class="button quiet block" style="margin:15px 0 22px" data-tab-jump="rules">返回风控规则与完整比例矩阵</button>`;
}
    const baseRender=render;
  render=function(){
    if(activeTab==='diagnostic'){
      $('#app').innerHTML=renderDiagnostic();
      all('.nav-link').forEach(x=>{x.classList.remove('active');x.setAttribute('aria-current','false');});
    }else baseRender();
  };
  const baseOverview=renderOverview;
  renderOverview=function(){
    const html=baseOverview();
    const marker='<div class="section-heading"><h2>市场阶段与融资预算</h2>';
    return html.includes(marker)?html.replace(marker,entryCard()+marker):entryCard()+html;
  };
  const baseRules=renderRules;
  renderRules=function(){
    const html=baseRules(),marker='<div class="panel" style="margin-top:15px">';
    return html.includes(marker)?html.replace(marker,entryCard()+marker):entryCard()+html;
  };
  const baseSettings=renderSettings;
  renderSettings=function(){return baseSettings().replace('版本 1.2','版本 1.5 · 多时段市场广度与有效证据覆盖').replace('<div class="section-heading"><h2>产品边界</h2></div>',entryCard()+'<div class="section-heading"><h2>产品边界</h2></div>');};
  const baseAlerts=computeAlerts;
  computeAlerts=function(p){
    const a=baseAlerts(p),d=ensure().draft;
    if(d.risk==='severe')a.unshift({severity:'error',title:'系统性风险：严重',desc:'已阻止新增价格触发仓位预算，建议暂停融资加仓；不会自动卖出。'+(d.event?' 原因：'+d.event:'')});
    else if(d.risk==='warning')a.unshift({severity:'warning',title:'系统性风险：警戒',desc:'请审查流动性和波动率风险，暂缓新增融资。'+(d.event?' 原因：'+d.event:'')});
    return a;
  };
  const baseExposure=exposureStatus;
  exposureStatus=function(p,w){
    const x=baseExposure(p,w);
    if(x&&ensure().draft.risk==='severe'){x.budgetCap=0;x.riskBlocked=true;}
    return x;
  };
  const baseAction=handleAction;
  handleAction=function(action,el){
    if(action==='diag-refresh-data'){loadSignals().then(ok=>{render();toast(ok?'市场指标已重新读取':'自动数据未更新：'+signalError);});return;}
    if(!['diag-preview','diag-save','diag-apply'].includes(action))return baseAction(action,el);
    try{
      const d=readForm(),res=calculate(d),root=ensure();
      if(action==='diag-apply'){
        if((!res.enough||res.suggestion!==d.stage)&&!d.reason.trim()){toast('证据不全或与模型建议不同，请填写人工覆盖理由');return;}
        if(!confirm('确认将市场阶段改为「'+STAGES[d.stage]+'」？全部仓位和融资风险预算将立即按该阶段更新。'))return;
      }
      root.draft=d;
      if(action!=='diag-preview'){
        if(action==='diag-apply')state.regime=d.stage;
        root.history.push({at:new Date().toISOString(),applied:action==='diag-apply',stage:d.stage,suggested:res.suggestion,score:res.score,coverage:res.coverage,confidence:res.confidence,scoringVersion:2,risk:d.risk,details:clone(d)});
        root.history=root.history.slice(-30);
      }
      persist();render();
      toast(action==='diag-apply'?'阶段已确认，风控预算已更新':action==='diag-save'?'诊断记录已保存（未改变市场阶段）':'诊断结果已重新计算（尚未应用）');
    }catch(e){toast('无法保存诊断：'+e.message);}
  };
  window.NorthstarDiagnostic={FACTORS,calculate,freshTechnical,recentSignal,version:'1.5'};
  document.addEventListener('change',event=>{
    const match=/^diagManual([012])$/.exec(event.target?.id||'');
    if(!match)return;
    const i=Number(match[1]),input=document.getElementById('diagScore'+i),auto=recentSignal(SIGNAL_KEYS[i]);
    if(!input)return;
    if(auto){input.disabled=!event.target.checked;input.value=event.target.checked?(ensure().draft.scores[i]??''):auto.score;}
    else input.disabled=false;
  });
  loadSignals().then(()=>{
    if(activeTab==='diagnostic'&&!document.activeElement?.matches('input,select,textarea'))render();
  });
  document.getElementById('refreshTop')?.addEventListener('click',()=>{loadSignals();});
  ensure();
})();
