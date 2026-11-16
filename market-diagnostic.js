'use strict';
/* This module deliberately has no server writes: all portfolio and diagnostic decisions stay on this device. */
(function(){
  const FACTORS=[
    {id:'trend',name:'价格趋势与技术结构',weight:30,tip:'中证全指及宽基指数的均线方向、阶段回撤。当前只可自动参考上证MA20/60/250，不代表全市场趋势。'},
    {id:'breadth',name:'市场广度与行业结构',weight:20,tip:'全A位于MA60/120上方比例、上涨行业占比、等权与市值加权指数的差异。'},
    {id:'flow',name:'资金流动与交易活跃度',weight:20,tip:'成交额历史分位、融资余额变化、宽基ETF净申购持续性。成交量放大不一定是流入。'},
    {id:'earnings',name:'宏观经济与企业盈利',weight:15,tip:'PMI与新订单、社融趋势、上市公司盈利预期与上修比例。'},
    {id:'policy',name:'国内政策与流动性',weight:10,tip:'货币财政政策、资本市场政策及落地效果。政策宣布与政策见效要区分。'},
    {id:'overseas',name:'海外金融环境',weight:5,tip:'美股科技、美元、美国国债收益率、人民币及重大海外风险。'}
  ];
  const STAGES={bull:'牛市主升',structural:'结构性行情',range:'震荡市',bottoming:'震荡筑底',bear:'熊市'};
  const RISK={normal:'正常',warning:'警戒',severe:'严重'};
  const scoreBand=n=>n>=80?'强支持':n>=60?'偏支持':n>=41?'中性':n>=21?'偏不利':'明显不利';
  const initialDraft=()=>({scores:[null,null,null,null,null,null],technicalManual:false,trend:'unknown',breadth:'unknown',priorDecline:false,bottoms:{price:false,momentum:false,breadth:false},stable:false,risk:'normal',event:'',pro:'',contra:'',stage:state.regime,reason:''});
  function ensure(){
    if(!state.diagnostic||typeof state.diagnostic!=='object')state.diagnostic={version:1,draft:initialDraft(),history:[]};
    const d=state.diagnostic;
    if(!d.draft||typeof d.draft!=='object')d.draft=initialDraft();
    if(!Array.isArray(d.draft.scores))d.draft.scores=[null,null,null,null,null,null];
    if(!d.draft.bottoms||typeof d.draft.bottoms!=='object')d.draft.bottoms={price:false,momentum:false,breadth:false};
    if(!Array.isArray(d.history))d.history=[];
    return d;
  }
  function freshTechnical(){
    const t=market.technical,i=market.index;
    const px=Number(i?.price),ma20=Number(t?.ma20),ma60=Number(t?.ma60),ma250=Number(t?.ma250),slope=Number(t?.ma20_slope_5_sessions);
    const stamp=i?.trade_at||market.updated_at;
    const ts=Date.parse(stamp||'');
    if(!t||!i||!Number.isFinite(ts)||Date.now()-ts>8*86400000||ts>Date.now()+86400000)return null;
    if(![px,ma20,ma60,ma250,slope].every(Number.isFinite)||[px,ma20,ma60,ma250].some(v=>v<=0))return null;
    const score=20+(px>=ma20?25:0)+(px>=ma60?20:0)+(px>=ma250?15:0)+(slope>0?20:0);
    return {score,px,ma20,ma60,ma250,slope,stamp,source:'上证单指数均线简化辅助评分（非全市场趋势评分）'};
  }
  function calculate(d){
    const tech=freshTechnical();
    const values=FACTORS.map((f,i)=>{
      if(i===0&&tech&&!d.technicalManual)return {value:tech.score,source:'自动·单指数代理'};
      const raw=d.scores?.[i];
      const num=raw===null||raw===''||raw===undefined?NaN:Number(raw);
      return Number.isFinite(num)&&num>=0&&num<=100?{value:num,source:'人工'}:{value:null,source:'待评估'};
    });
    const coverage=FACTORS.reduce((s,f,i)=>s+(values[i].value===null?0:f.weight),0);
    const score=coverage?Math.round(FACTORS.reduce((s,f,i)=>s+(values[i].value===null?0:f.weight*values[i].value),0)/coverage):null;
    const bottoms=['price','momentum','breadth'].filter(k=>Boolean(d.bottoms?.[k])).length;
    const enough=coverage>=70&&d.trend!=='unknown'&&d.breadth!=='unknown';
    let suggestion=null,candidate=null;
    if(d.trend==='down'){
      if(d.priorDecline&&bottoms>=2){
        candidate='bottoming';
        suggestion=d.stable?'bottoming':'bear';
      }else suggestion='bear';
    }else if(d.trend==='up'){
      suggestion=d.breadth==='weak'?'range':d.breadth==='broad'&&values[0].value>=70&&values[2].value>=55&&d.stable?'bull':'structural';
    }else if(d.trend==='sideways'){
      if(d.priorDecline&&bottoms>=2&&d.stable)suggestion='bottoming';
      else suggestion=d.breadth==='narrow'&&values[0].value>=50&&values[2].value>=50?'structural':'range';
    }
    const contradictory=(d.trend==='up'&&values[0].value!==null&&values[0].value<40)||(d.trend==='down'&&values[0].value!==null&&values[0].value>=70);
    const confidence=!enough?'证据不足':coverage>=85&&d.stable&&!contradictory?'较高':coverage>=70&&!contradictory?'中等':'偏低';
    return {tech,values,coverage,score,bottoms,enough,suggestion:enough?suggestion:null,candidate,candidateLabel:candidate&&!d.stable?'筑底信号待持续确认':'',confidence,contradictory};
  }
  function readForm(){
    const old=ensure().draft;
    const el=id=>document.getElementById(id);
    const scores=FACTORS.map((_,i)=>{
      if(i===0&&!el('diagTechnicalManual').checked)return null;
      const raw=el('diagScore'+i)?.value.trim();
      if(raw===undefined||raw==='')return null;
      const x=Number(raw);
      if(!Number.isFinite(x)||x<0||x>100)throw new Error('六维评分必须是0—100的数字，或留空');
      return x;
    });
    const trend=el('diagTrend').value,breadth=el('diagBreadth').value,risk=el('diagRisk').value;
    if(!['unknown','up','sideways','down'].includes(trend)||!['unknown','broad','narrow','weak'].includes(breadth)||!Object.hasOwn(RISK,risk))throw new Error('诊断选项有误');
    const stage=el('diagStage').value;
    if(!Object.hasOwn(STAGES,stage))throw new Error('市场阶段有误');
    return {...old,scores,technicalManual:el('diagTechnicalManual').checked,trend,breadth,priorDecline:el('diagPreviousDecline').checked,
      bottoms:{price:el('diagBottomPrice').checked,momentum:el('diagBottomMomentum').checked,breadth:el('diagBottomBreadth').checked},
      stable:el('diagStable').checked,risk,event:el('diagEvent').value.trim().slice(0,600),pro:el('diagPro').value.trim().slice(0,1200),
      contra:el('diagContra').value.trim().slice(0,1200),stage,reason:el('diagReason').value.trim().slice(0,600)};
  }
  function riskText(d){
    if(d.risk==='severe')return '严重风险：暂停新增风险仓位的价格触发预算；不得据此自动卖出存量资产。已保存的5×5硬上限不被静默修改。';
    if(d.risk==='warning')return '警戒：暂缓增加融资与高波动仓位，优先核查近期风险变化。';
    return '正常：遵循已确认市场阶段及5×5组合约束。';
  }
  function statusHTML(result,d){
    const status=result.enough?STAGES[result.suggestion]:'证据不足';
    const className=result.enough?'good':'warn';
    return `<div class="diag-summary"><div class="metric"><div class="label">已评分维度的加权均值</div><div class="val">${result.score===null?'—':result.score+' /100'}</div><div class="hint">证据覆盖权重 ${result.coverage}% · 缺失项不按0分处理</div></div><div class="metric"><div class="label">模型规则建议</div><div class="val" style="font-size:18px">${esc(status)}</div><div class="hint">${esc(result.confidence)} · ${result.enough?'非未来涨跌概率':'不触发阶段推断'}</div></div></div>
    ${result.candidateLabel?`<div class="notice">${esc(result.candidateLabel)}：当前不能直接升级为已确认筑底。</div>`:''}
    ${result.contradictory?'<div class="warning-band">当前人工趋势判断与技术评分明显冲突，请检查日期及判断依据。</div>':''}
    <div class="notice">${esc(riskText(d))}</div>`;
  }
  function entryCard(){
    const d=ensure().draft,result=calculate(d);
    return `<section class="panel diag-entry" style="margin-top:12px"><div class="row-between"><div><div class="eyebrow">MARKET REGIME DIAGNOSTICS</div><div style="font-size:16px;font-weight:800;margin-top:5px">市场阶段诊断</div></div><span class="pill ${result.enough?'good':'warn'}">${result.enough?'证据覆盖 '+result.coverage+'%':'待完善证据'}</span></div>
      <div class="diag-entry-row"><span>模型建议：<b>${esc(result.enough?STAGES[result.suggestion]:'证据不足')}</b></span><span>已确认：<b>${esc(regimeName(state.regime))}</b></span></div>
      <div class="muted-note">模型不会自动修改市场阶段；仅上证指数均线可提供部分自动参考，其余维度需人工核验。</div>
      <button class="button secondary block" style="margin-top:12px" data-tab-jump="diagnostic">进入市场阶段诊断</button></section>`;
  }
  function renderDiagnostic(){
    const d=ensure().draft,result=calculate(d);
    const auto=result.tech;
    const techDescription=auto?`上证 ${fnum(auto.px)} · MA20 ${fnum(auto.ma20)} / MA60 ${fnum(auto.ma60)} / MA250 ${fnum(auto.ma250)} · MA20五日斜率 ${fnum(auto.slope)} · ${dateBeijing(auto.stamp)}`:'自动技术数据暂无有效值或已过期；可临时人工评分，不能据此声称已自动覆盖趋势指标。';
    const dimensionFields=FACTORS.map((f,i)=>{
      const activeAuto=i===0&&auto&&!d.technicalManual;
      const val=activeAuto?auto.score:d.scores[i];
      const source=result.values[i].source;
      return `<div class="diag-factor"><div class="row-between"><label for="diagScore${i}">${esc(f.name)} <span class="mini">${f.weight}%</span></label><span class="mini">${esc(source)}</span></div>
        <input id="diagScore${i}" type="number" min="0" max="100" step="1" inputmode="decimal" value="${val===null||val===undefined?'':val}" ${activeAuto?'disabled':''} placeholder="未评估，留空" aria-label="${esc(f.name)}评分">
        <div class="muted-note">${esc(f.tip)}</div></div>`;
    }).join('');
    const checks=[['price','价格低点趋稳 / 不再持续创新低'],['momentum','短期均线或MACD下跌动能修复'],['breadth','市场广度或资金参与有所改善']].map(([k,t])=>`<label class="diag-check"><input id="diagBottom${k[0].toUpperCase()+k.slice(1)}" type="checkbox" ${d.bottoms[k]?'checked':''}>${esc(t)}</label>`).join('');
    const history=ensure().history.slice(-6).reverse().map(h=>`<div class="diag-history-item"><div><b>${esc(h.applied?'已应用':'仅记录')} · ${esc(STAGES[h.stage]||'未知')}</b><div class="mini">${dateBeijing(h.at)} · 加权均值 ${h.score??'—'}/100 · 证据覆盖 ${h.coverage}%</div></div><span class="pill">${esc(RISK[h.risk]||'正常')}</span></div>`).join('');
    return `<div class="intro-top"><div><div class="eyebrow">MARKET REGIME DIAGNOSTICS / V1.3</div><h1 class="page-title">市场阶段诊断</h1><div class="subtle">多维证据 × 趋势/广度识别 × 事件风险 × 人工确认</div></div></div>
      <section class="panel" style="margin-top:14px">${statusHTML(result,d)}<div class="divider"></div><div class="row-between"><span class="mini">当前实际应用阶段</span><b>${esc(regimeName(state.regime))}</b></div><div class="muted-note" style="margin-top:8px">本模型用于未来1—3个月的风险预算；六维权重和阈值属于初始假设，尚未完成历史回测。</div></section>
      <div class="section-heading"><h2>一、自动技术参考</h2><span class="pill">只覆盖部分技术信号</span></div>
      <section class="panel"><div class="muted-note">${esc(techDescription)}</div><label class="diag-check" style="margin-top:12px"><input id="diagTechnicalManual" type="checkbox" ${d.technicalManual?'checked':''}>不用单指数代理评分，改为人工判断技术维度（勾选后点预览生效）</label></section>
      <div class="section-heading"><h2>二、六维评分</h2><span class="mini">满分100，权重合计100%</span></div>
      <section class="panel"><div class="diag-scores-tip">参考口径：0—20明显不利；21—40偏不利；41—59中性；60—79偏支持；80—100强支持。评分必须有可核查的事实支持。</div>${dimensionFields}</section>
      <div class="section-heading"><h2>三、趋势与广度识别</h2></div>
      <section class="panel"><div class="fields">
        <div class="field"><label for="diagTrend">中期主要趋势</label><select id="diagTrend">${[['unknown','尚未判断'],['up','向上'],['sideways','震荡'],['down','向下']].map(([v,t])=>`<option value="${v}" ${d.trend===v?'selected':''}>${t}</option>`).join('')}</select></div>
        <div class="field"><label for="diagBreadth">市场广度</label><select id="diagBreadth">${[['unknown','缺乏证据'],['broad','广泛扩散'],['narrow','少数行业领涨'],['weak','多数股票疲弱']].map(([v,t])=>`<option value="${v}" ${d.breadth===v?'selected':''}>${t}</option>`).join('')}</select></div>
      </div><div class="divider"></div><label class="diag-check"><input id="diagPreviousDecline" type="checkbox" ${d.priorDecline?'checked':''}>此前经历显著的中期下跌（筑底判断前提）</label>${checks}
      <div class="divider"></div><label class="diag-check"><input id="diagStable" type="checkbox" ${d.stable?'checked':''}>已观察至少5个交易日或两个周线收盘进行确认（由我核验）</label>
      <div class="muted-note" style="margin-top:8px">只有过去存在明显下跌、修复证据充分且持续确认，才将熊市升级为震荡筑底；单日反弹不能替代趋势确认。</div></section>
      <div class="section-heading"><h2>四、系统性风险与事实证据</h2></div>
      <section class="panel"><div class="field"><label for="diagRisk">独立风险等级（人工核验）</label><select id="diagRisk">${[['normal','正常'],['warning','警戒'],['severe','严重']].map(([v,t])=>`<option value="${v}" ${d.risk===v?'selected':''}>${t}</option>`).join('')}</select></div>
        <div class="field" style="margin-top:12px"><label for="diagEvent">事件和风险描述（可选）</label><textarea id="diagEvent" maxlength="600" placeholder="例如：波动率跃升、流动性骤降及信息来源">${esc(d.event||'')}</textarea></div>
        <div class="field" style="margin-top:12px"><label for="diagPro">支持本次判断的事实</label><textarea id="diagPro" maxlength="1200" placeholder="指标数值、来源和日期；建议至少两项">${esc(d.pro||'')}</textarea></div>
        <div class="field" style="margin-top:12px"><label for="diagContra">反对证据 / 尚未满足的条件</label><textarea id="diagContra" maxlength="1200" placeholder="哪些条件不成立？什么会推翻判断？">${esc(d.contra||'')}</textarea></div></section>
      <div class="section-heading"><h2>五、人工最终确认</h2></div>
      <section class="panel"><div class="field"><label for="diagStage">拟应用市场阶段</label><select id="diagStage">${REGIMES.map(x=>`<option value="${x.id}" ${d.stage===x.id?'selected':''}>${esc(x.name)}</option>`).join('')}</select></div>
        <div class="field" style="margin-top:12px"><label for="diagReason">人工判断与模型不同、或证据不足时的覆盖理由</label><textarea id="diagReason" maxlength="600" placeholder="简述判断依据；与系统模型不同或数据不足时必填">${esc(d.reason||'')}</textarea></div>
        <div class="action-toolbar"><button class="button secondary" data-action="diag-preview">预览诊断</button><button class="button secondary" data-action="diag-save">保存判断记录</button><button class="button" data-action="diag-apply">确认并应用到风控矩阵</button></div>
        <div class="muted-note" style="margin-top:10px">预览只保存编辑草稿；保存判断记录不改变现有市场阶段；确认并应用会修改风控矩阵当前阶段、影响持仓提醒，但绝不会自动下单。严重风险级别会阻止新增价格触发仓位预算。</div>
      </section>
      <div class="section-heading"><h2>六、最近判断记录</h2><span class="mini">本机保留最近30条</span></div>
      <section class="panel">${history||'<div class="empty">尚无诊断记录；完成评分后点击「保存判断记录」。</div>'}<div class="muted-note" style="margin-top:10px">记录随完整JSON备份导出，不上传GitHub。历史判断用于复盘，不保证未来收益。</div></section>
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
  renderSettings=function(){return baseSettings().replace('版本 1.2','版本 1.3 · 六维市场诊断').replace('<div class="section-heading"><h2>产品边界</h2></div>',entryCard()+'<div class="section-heading"><h2>产品边界</h2></div>');};
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
        root.history.push({at:new Date().toISOString(),applied:action==='diag-apply',stage:d.stage,suggested:res.suggestion,score:res.score,coverage:res.coverage,confidence:res.confidence,risk:d.risk,details:clone(d)});
        root.history=root.history.slice(-30);
      }
      persist();render();
      toast(action==='diag-apply'?'阶段已确认，风控预算已更新':action==='diag-save'?'诊断记录已保存（未改变市场阶段）':'诊断结果已重新计算（尚未应用）');
    }catch(e){toast('无法保存诊断：'+e.message);}
  };
  window.NorthstarDiagnostic={FACTORS,calculate,freshTechnical,version:'1.3'};
  ensure();
})();
