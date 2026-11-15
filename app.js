'use strict';
/* Northstar 投资决策驾驶舱 v1.0 — 本地风控计算，不向服务器上传用户持仓 */
const STORAGE_KEY = 'northstar_investment_cockpit_v1';
const MARKET_CACHE_KEY = 'northstar_market_cache_v1';
const CATEGORIES = [
  {id:'growth',name:'科技高增长'}, {id:'core',name:'白马/行业龙头'},
  {id:'theme',name:'题材/高波动'}, {id:'other',name:'其他'}
];
const REGIMES = [
  {id:'bull',name:'牛市主升'}, {id:'structural',name:'结构性行情'},
  {id:'range',name:'震荡市'}, {id:'bottoming',name:'震荡筑底'}, {id:'bear',name:'熊市'}
];
const DEFAULT_RULES = {
 bull:{debtSuggest:'10–20%',debtCap:30,totalCap:125, growth:{single:15,total:55},core:{single:25,total:75},theme:{single:8,total:20},other:{single:10,total:25}},
 structural:{debtSuggest:'5–15%',debtCap:20,totalCap:105,growth:{single:12,total:45},core:{single:20,total:65},theme:{single:5,total:15},other:{single:8,total:20}},
 range:{debtSuggest:'0–5%',debtCap:10,totalCap:80,growth:{single:8,total:30},core:{single:15,total:50},theme:{single:3,total:8},other:{single:5,total:15}},
 bottoming:{debtSuggest:'0%',debtCap:5,totalCap:60,growth:{single:5,total:20},core:{single:10,total:35},theme:{single:2,total:5},other:{single:4,total:10}},
 bear:{debtSuggest:'0%',debtCap:0,totalCap:35,growth:{single:3,total:10},core:{single:8,total:25},theme:{single:1,total:3},other:{single:2,total:5}}
};
const DEFAULT_WATCH = [
 {symbol:'002475',name:'立讯精密',sector:'消费电子 / AI互联',category:'growth',thesis:'关注汽车电子、数据中心互联、盈利质量及估值',levels:[],thesisValid:true},
 {symbol:'002371',name:'北方华创',sector:'半导体设备',category:'growth',thesis:'关注国产设备渗透率、毛利率和估值',levels:[],thesisValid:true},
 {symbol:'300604',name:'长川科技',sector:'半导体测试设备',category:'growth',thesis:'关注测试设备订单、利润增长和现金流',levels:[],thesisValid:true},
 {symbol:'600089',name:'特变电工',sector:'电网 / 能源设备',category:'core',thesis:'周期属性明显；此分类仅为示例，可自行调整',levels:[],thesisValid:true},
 {symbol:'001248',name:'华润新能',sector:'新能源 / 次新股',category:'theme',thesis:'关注底部结构、次新股流动性与基本面',levels:[],thesisValid:true}
];
const clone = x => JSON.parse(JSON.stringify(x));
const $ = selector => document.querySelector(selector);
const all = selector => [...document.querySelectorAll(selector)];
const esc = value => String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const n = value => Number.isFinite(Number(value)) ? Number(value) : 0;
const money = value => !Number.isFinite(value) ? '—' : (Math.abs(value)>=100000000 ? (value/100000000).toFixed(2)+'亿' : Math.abs(value)>=10000 ? (value/10000).toFixed(2)+'万' : value.toLocaleString('zh-CN',{maximumFractionDigits:0}));
const msign = value => Number.isFinite(value) ? (value<0?'-':'')+'¥'+money(Math.abs(value)) : '—';
const percent = value => Number.isFinite(value) ? value.toFixed(1)+'%' : '—';
const fnum = (value,digits=2) => Number.isFinite(value) ? value.toFixed(digits) : '—';
const dateBeijing = input => {if(!input)return '尚未采集';let d=new Date(input);return Number.isNaN(d.getTime())?'未知':new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false}).format(d)+' 北京时间';};
const normNum = raw => {const v=Number(raw);return raw!==''&&raw!==null&&Number.isFinite(v)&&v>=0?v:null;};
function initState(){return {v:1,regime:'structural',cash:0,debt:0,watch:clone(DEFAULT_WATCH),holdings:[],rules:clone(DEFAULT_RULES)};}
let state;
try{const saved=JSON.parse(localStorage.getItem(STORAGE_KEY)||'null');state=saved&&Array.isArray(saved.watch)&&saved.rules?{...initState(),...saved}:initState();}catch(_){state=initState();}
let market={updated_at:null,source:'等待首次行情采集',count:0,quotes:{},index:null,technical:null};
try{const saved=JSON.parse(localStorage.getItem(MARKET_CACHE_KEY)||'null');if(saved&&saved.quotes)market=saved;}catch(_){}
let activeTab='overview';
let searchText='';
let toastTimeout;
function persist(){try{localStorage.setItem(STORAGE_KEY,JSON.stringify(state));}catch(e){toast('保存失败：本机储存空间不足或已禁用');}}
function toast(message){const root=$('#toastRoot');if(!root)return;root.innerHTML='<div class="toast">'+esc(message)+'</div>';clearTimeout(toastTimeout);toastTimeout=setTimeout(()=>root.innerHTML='',3500);}
function findWatch(symbol){return state.watch.find(w=>w.symbol===symbol);}
function categoryName(id){return CATEGORIES.find(c=>c.id===id)?.name||'其他';}
function regimeName(id){return REGIMES.find(r=>r.id===id)?.name||'未知';}
function rule(){return state.rules[state.regime]||DEFAULT_RULES.structural;}
function marketAgeDays(){const t=new Date(market.updated_at||0).getTime();return t?Math.max(0,(Date.now()-t)/86400000):9999;}
function quoteFor(symbol){const w=findWatch(symbol);if(w&&n(w.manualPrice)>0){return {price:n(w.manualPrice),change:null,source:'手动价格',updated_at:w.manualAt||null,manual:true};}const q=market.quotes?.[symbol];if(q&&n(q.price)>0)return {...q,source:'自动行情',manual:false,updated_at:q.trade_at||market.updated_at};return null;}
function isFresh(q){if(!q)return false;const t=new Date(q.updated_at||0).getTime();return Boolean(t)&&Date.now()-t<6*86400000;}
function portfolio(){
  const rows=state.holdings.filter(h=>n(h.qty)>0).map(h=>{
    const w=findWatch(h.symbol);const q=quoteFor(h.symbol);const price=q?.price??null;
    const mv=price!==null?price*n(h.qty):null;
    const unitCost=n(h.cost),costValue=n(h.qty)*unitCost;
    return {...h,name:w?.name||h.symbol,category:w?.category||'other',sector:w?.sector||'其他',q,price,mv,unitCost,costValue,profit:mv!==null?mv-costValue:null};
  });
  const missing=rows.filter(r=>r.mv===null);
  const ready=missing.length===0;
  const stockValue=ready?rows.reduce((s,r)=>s+r.mv,0):null;
  const equity=ready?stockValue+n(state.cash)-n(state.debt):null;
  const valid=ready&&equity>0;
  const totalCost=rows.reduce((s,r)=>s+r.costValue,0);
  const categoryMV={growth:0,core:0,theme:0,other:0};
  rows.forEach(r=>{if(r.mv!==null)categoryMV[r.category]=(categoryMV[r.category]||0)+r.mv;});
  return {rows,missing,ready,valid,stockValue,equity,totalCost,categoryMV, debtPct:valid?n(state.debt)/equity*100:null, stockPct:valid?stockValue/equity*100:null};
}
function stockPct(p,symbol){if(!p.valid)return null;return (p.rows.find(r=>r.symbol===symbol)?.mv||0)/p.equity*100;}
function getTriggered(w,quote){if(!quote||!isFresh(quote)||w.thesisValid===false)return null;return [...(w.levels||[])].filter(l=>n(l.price)>0&&n(l.target)>0&&quote.price<=n(l.price)).sort((a,b)=>n(b.target)-n(a.target))[0]||null;}
function exposureStatus(p,w){if(!p.valid)return null;const classRule=rule()[w.category]||rule().other;const own=stockPct(p,w.symbol);const total=(p.categoryMV[w.category]||0)/p.equity*100;return {own,total,singleCap:classRule.single,categoryCap:classRule.total,room:Math.max(0,classRule.total-(total-own))};}
function computeAlerts(p){
 const alerts=[];
 if(p.missing.length) alerts.push({severity:'error',title:`有 ${p.missing.length} 只持仓缺少有效行情`,desc:'仓位、净资产及融资风险计算暂时停用。请等待自动报价，或给这几只股票填入手动价格。'});
 if(!p.rows.length)alerts.push({severity:'info',title:'尚未导入持仓',desc:'在「持仓」录入股票数量、成本、可用现金及融资余额，即可计算真实风险敞口。'});
 if(p.ready&&p.equity!==null&&p.equity<=0)alerts.push({severity:'error',title:'账户净资产不大于零',desc:'请检查融资负债和现金输入；无法计算有效的仓位占比。'});
 if(p.valid){
   const r=rule();
   if(p.debtPct>r.debtCap+1e-8)alerts.push({severity:'error',title:`融资比例 ${percent(p.debtPct)} 超过 ${percent(r.debtCap)} 上限`,desc:`当前采用「${regimeName(state.regime)}」的风险规则；融资余额/净资产作为统一口径。`});
   else if(p.debtPct>0&&r.debtCap>0&&p.debtPct>=r.debtCap*0.8)alerts.push({severity:'warning',title:`融资比例已接近上限 ${percent(r.debtCap)}`,desc:`当前为 ${percent(p.debtPct)}，不要因为买价触发而自动增加融资。`});
   if(p.stockPct>r.totalCap)alerts.push({severity:'error',title:`股票总敞口 ${percent(p.stockPct)} 超过上限 ${percent(r.totalCap)}`,desc:'总敞口按持仓市值/净资产计算，融资时可能超过100%。'});
   CATEGORIES.forEach(cat=>{
     const actual=(p.categoryMV[cat.id]||0)/p.equity*100,cap=(r[cat.id]||r.other).total;
     if(actual>cap+.01)alerts.push({severity:'error',title:`${cat.name}合计 ${percent(actual)} 超配`,desc:`类别上限 ${percent(cap)}；请优先调整同类资产合计敞口。`});
   });
   p.rows.forEach(row=>{
     const cap=(r[row.category]||r.other).single;
     const actual=row.mv/p.equity*100;
     if(actual>cap+.01)alerts.push({severity:actual>cap*1.5?'error':'warning',title:`${row.name} 占净资产 ${percent(actual)}`,desc:`当前市场阶段的单股上限 ${percent(cap)}；超出 ${percent(actual-cap)}。`});
     if(row.q&&!isFresh(row.q))alerts.push({severity:'warning',title:`${row.name} 行情可能过期`,desc:`最新报价时间：${dateBeijing(row.q.updated_at)}，建议核实后再计算买卖计划。`});
   });
 }
 state.watch.forEach(w=>{
   const q=quoteFor(w.symbol),level=getTriggered(w,q);
   if(level){
     const e=exposureStatus(p,w);const limit=e?Math.min(n(level.target),e.singleCap,e.room):Math.min(n(level.target),(rule()[w.category]||rule().other).single);
     const hasRoom=!e||e.own+.01<limit;
     const gapYuan=e?Math.max(0,(limit-e.own)*p.equity/100):null;
     const cashFundable=gapYuan===null?null:Math.min(gapYuan,n(state.cash));
     const budgetText=e?`当下实际 ${percent(e.own)}，规则约束后的累计目标最多 ${percent(limit)}；目标仓位缺口 ${msign(gapYuan)}，现有现金最多覆盖 ${msign(cashFundable)}`:'录入持仓后可计算目标差额';
     alerts.push({severity:hasRoom&&(!e||cashFundable>0)?'info':'warning',title:`${w.name} 进入第${level.stage||'?'}档买价观察区`,desc:`最新价 ${fnum(q.price)} ≤ 预设价 ${fnum(n(level.price))} 元；预设累计目标 ${percent(n(level.target))}，${budgetText}。${hasRoom?'仅观察，不构成自动买入指令；不得因买价触发自动增加融资。':'当前风险预算不足，不宜机械加仓。'}`});
   }
 });
 if(!market.updated_at&&state.watch.some(w=>n(w.manualPrice)<=0))alerts.push({severity:'info',title:'尚未取得自动行情',desc:'GitHub Actions首次运行后，行情将按工作日自动更新；也可为个股临时输入手动价格。'});
 return alerts.sort((a,b)=>({error:0,warning:1,info:2}[a.severity]-{error:0,warning:1,info:2}[b.severity]));
}
function alertHtml(a){return `<article class="alert ${esc(a.severity)}"><span class="dot"></span><div><div class="alert-title">${esc(a.title)}</div><div class="alert-desc">${esc(a.desc)}</div></div></article>`;}
function trackHtml(name,pct,limit){const pp=Number.isFinite(pct)?pct:0;return `<div class="track-row"><div class="track-head"><span>${esc(name)}</span><span><b class="${pp>limit?'numeric-bad':''}">${percent(pct)}</b> <span class="mini">/ 上限 ${percent(limit)}</span></span></div><div class="track"><span class="${pp>limit?'over':''}" style="width:${Math.min(100,Math.max(0,limit>0?pp/limit*100:pp>0?100:0))}%"></span></div></div>`;}
function currentMarketBadge(){const age=marketAgeDays();return `<span class="pill ${age>6?'warn':'info'}">${market.updated_at?dateBeijing(market.updated_at):'待自动采集'}</span>`;}
function renderOverview(){
 const p=portfolio(),r=rule(),alerts=computeAlerts(p), tech=market.technical;
 const marketMessage=tech?`规则辅助判断：<b>${esc(regimeName(tech.suggested))}</b> · 上证指数 ${fnum(n(market.index?.price))} · MA20 ${fnum(n(tech.ma20))} / MA60 ${fnum(n(tech.ma60))}`:'自动行情尚未计算市场技术参考；请先使用手动阶段。';
 const watchRows=state.watch.slice(0,5).map(w=>{
  const q=quoteFor(w.symbol),tr=getTriggered(w,q),changes=q&&Number.isFinite(q.change)?`${q.change>=0?'+':''}${fnum(q.change)}%`:'—';
  return `<div class="row-between" style="padding:11px 0;border-bottom:1px solid #2a3a4e"><div><div style="font-size:13px;font-weight:750">${esc(w.name)} <span class="mini">${esc(w.symbol)}</span></div><div class="mini" style="margin-top:4px">${esc(w.sector)} · ${esc(categoryName(w.category))}</div></div><div style="text-align:right"><div style="font-size:16px;font-weight:800">${q?fnum(q.price):'—'}</div><div class="mini ${q?.change>=0?'up':'down'}">${tr?'到达预设买价':changes}</div></div></div>`;
 }).join('');
 const catTracks=CATEGORIES.map(c=>trackHtml(c.name,p.valid?(p.categoryMV[c.id]||0)/p.equity*100:null,(r[c.id]||r.other).total)).join('');
 return `<div class="intro-top"><div><div class="eyebrow">PORTFOLIO COMMAND CENTER</div><h1 class="page-title">决策总览</h1><div class="subtle">按风险预算管理仓位，不用回本价决定交易</div></div></div>
 <section class="panel hero" style="margin-top:15px"><div class="hero-head"><div class="hero-label">账户净资产 · A股 / 人民币</div><span class="pill">${esc(regimeName(state.regime))}</span></div><div class="hero-value">${p.valid?msign(p.equity):'待完善数据'}</div><div class="hero-small">${p.valid?'净资产 = 持仓市值 + 可用现金 − 融资负债':'添加持仓和现金，并确保每只持仓有有效价格'}</div><div class="hero-line"></div><div class="quickstats"><div><div class="qs-label">股票总敞口</div><div class="qs-num ${p.stockPct>r.totalCap?'numeric-bad':''}">${percent(p.stockPct)}</div></div><div><div class="qs-label">融资 / 净资产</div><div class="qs-num ${p.debtPct>r.debtCap?'numeric-bad':''}">${percent(p.debtPct)}</div></div><div><div class="qs-label">待处理信号</div><div class="qs-num">${alerts.length}<span style="font-size:12px;font-weight:400"> 项</span></div></div></div></section>
 <div class="section-heading"><h2>市场阶段与融资预算</h2><span class="mini">支持手动确认</span></div>
 <section class="panel"><div class="field"><label for="quickRegime">当前市场阶段</label><select id="quickRegime">${REGIMES.map(x=>`<option value="${x.id}" ${state.regime===x.id?'selected':''}>${esc(x.name)}</option>`).join('')}</select></div><div class="cards-grid" style="margin-top:13px"><div class="metric"><div class="label">建议融资范围</div><div class="val">${esc(r.debtSuggest)}</div><div class="hint">债务 / 净资产</div></div><div class="metric"><div class="label">融资硬上限</div><div class="val">${percent(r.debtCap)}</div><div class="hint">达到即预警</div></div></div><div class="notice" style="margin-top:11px">${marketMessage}${tech&&tech.suggested!==state.regime?`<div style="margin-top:9px"><button class="button small secondary" data-action="use-suggested">确认采用参考阶段</button></div>`:''}</div></section>
 <div class="section-heading"><h2>风险提醒</h2><span class="pill ${alerts.some(a=>a.severity==='error')?'bad':alerts.length?'warn':'good'}">${alerts.length?`${alerts.length}项提醒`:'暂无越线'}</span></div>${alerts.length?alerts.slice(0,7).map(alertHtml).join(''):'<div class="empty"><strong>暂无风险提醒</strong><br>持续检查价格、仓位与融资规则</div>'}${alerts.length>7?'<button class="button quiet block" data-tab-jump="holdings">查看全部持仓风险</button>':''}
 <div class="section-heading"><h2>分类风险敞口</h2><button class="expand-link" data-tab-jump="rules">编辑规则</button></div><div class="panel">${p.valid?catTracks:'<div class="empty">录入持仓并取得报价后，显示四类股票实际占净资产比例</div>'}</div>
 <div class="section-heading"><h2>长期观察池</h2><button class="expand-link" data-tab-jump="watch">管理观察池</button></div><div class="panel">${watchRows||'<div class="empty">尚无观察标的</div>'}<div style="padding-top:11px">${currentMarketBadge()}</div></div>`;
}
function watchCard(w,p){
 const q=quoteFor(w.symbol),trigger=getTriggered(w,q),e=exposureStatus(p,w);
 const levels=(w.levels||[]).length?([...w.levels].sort((a,b)=>b.price-a.price).map(l=>`<span class="pill ${trigger&&q?.price<=l.price?'good':''}">${l.stage||'档'}档 ≤${fnum(n(l.price))} / ${percent(n(l.target))}</span>`).join('')):'<span class="mini">未设定分档买入计划</span>';
 const status=w.thesisValid===false?'<span class="pill bad">逻辑待复核</span>':trigger?'<span class="pill good">价格触达</span>':q&&!isFresh(q)?'<span class="pill warn">行情待核实</span>':'<span class="pill">观察中</span>';
 return `<article class="list-card"><div class="stock-header"><div><div><span class="stock-name">${esc(w.name)}</span><span class="stock-code">${esc(w.symbol)}</span></div><div class="stock-tags"><span class="pill">${esc(w.sector)}</span><span class="pill">${esc(categoryName(w.category))}</span>${status}</div></div><div><div class="price">${q?fnum(q.price):'—'}</div><div class="change ${q?.change>=0?'up':'down'}">${q&&Number.isFinite(q.change)?`${q.change>=0?'+':''}${fnum(q.change)}%`:(q?'手工报价':'暂无报价')}</div></div></div>
 <div class="kv-list"><div><div class="k">实际仓位 / 净资产</div><div class="v">${percent(e?.own)}</div></div><div><div class="k">当前阶段单股上限</div><div class="v">${percent((rule()[w.category]||rule().other).single)}</div></div></div>
 <div class="mini" style="margin:12px 0 7px">分档买价 → 累计目标仓位</div><div class="pill-gap">${levels}</div>
 ${w.thesis?`<div class="signal" style="margin-top:12px">研究要点：${esc(w.thesis)}</div>`:''}
 <div class="small-actions"><span class="date-stamp">${q?`${esc(q.source)} · ${dateBeijing(q.updated_at)}`:'自动价格待更新'}</span><button class="button small secondary" data-action="edit-stock" data-symbol="${esc(w.symbol)}">编辑计划</button></div></article>`;
}
function renderWatch(){
 const p=portfolio();const filtered=state.watch.filter(w=>`${w.symbol} ${w.name} ${w.sector} ${categoryName(w.category)}`.toLowerCase().includes(searchText.toLowerCase()));
 return `<div class="intro-top"><div><div class="eyebrow">RESEARCH & BUY ZONES</div><h1 class="page-title">赛道观察池</h1><div class="subtle">预设价格与累计目标仓位，触发后人工复核</div></div><button class="button" data-action="add-stock">+ 添加</button></div>
 <input class="search-input" id="stockSearch" placeholder="搜索公司、代码、赛道或分类" value="${esc(searchText)}" aria-label="搜索观察池">
 <div class="row-between" style="margin:2px 0 13px"><div class="mini">共 ${state.watch.length} 只 · 当前显示 ${filtered.length} 只</div>${currentMarketBadge()}</div>
 ${filtered.length?filtered.map(w=>watchCard(w,p)).join(''):'<div class="empty">没有匹配标的。点击「添加」建立自己的长期观察池。</div>'}
 <div class="notice">分档仓位是<strong>累计目标仓位</strong>，不是每一档追加的仓位。例如：50元配置5%，45元配置10%，意为跌到45元时总持仓目标10%。实际执行还受市场阶段、单股上限、类别上限及现金约束。</div>`;
}
function renderHoldings(){
 const p=portfolio(),r=rule(),alerts=computeAlerts(p).filter(a=>a.title.includes('融资')||a.title.includes('超配')||a.title.includes('股票总敞口')||a.title.includes('占净资产'));
 const rows=p.rows.map(row=>{
   const cap=(r[row.category]||r.other).single;
   const weight=p.valid?row.mv/p.equity*100:null;
   const rr=Number.isFinite(row.profit)&&row.costValue>0?row.profit/row.costValue*100:null;
   return `<div class="list-card"><div class="row-between"><div><span class="stock-name">${esc(row.name)}</span><span class="stock-code">${esc(row.symbol)}</span><div class="mini" style="margin-top:5px">${esc(categoryName(row.category))} · ${Number(row.qty).toLocaleString('zh-CN')}股</div></div><div style="text-align:right"><div style="font-size:18px;font-weight:780">${row.price===null?'待报价':fnum(row.price)}</div><div class="mini">成本 ${fnum(n(row.cost))}</div></div></div><div class="kv-list"><div><div class="k">持仓市值</div><div class="v">${row.mv===null?'—':msign(row.mv)}</div></div><div><div class="k">持仓盈亏</div><div class="v ${row.profit>=0?'up':'down'}">${row.profit===null?'—':msign(row.profit)} <span class="mini">${percent(rr)}</span></div></div></div><div style="margin-top:12px">${trackHtml('占净资产比例',weight,cap)}</div><div class="small-actions"><span class="mini">上限 ${percent(cap)} · 当前 ${percent(weight)}</span><div class="flex-gap"><button class="button small secondary" data-action="edit-holding" data-symbol="${esc(row.symbol)}">编辑</button><button class="button small quiet" data-action="delete-holding" data-symbol="${esc(row.symbol)}">删除</button></div></div></div>`;
 }).join('');
 return `<div class="intro-top"><div><div class="eyebrow">POSITIONS & LEVERAGE</div><h1 class="page-title">持仓与融资</h1><div class="subtle">用真实仓位对照动态风险预算</div></div><button class="button" data-action="add-holding">+ 持仓</button></div>
 <div class="panel" style="margin-top:15px"><div class="fields"><div class="field"><label for="cashInput">可用现金（元）</label><input id="cashInput" inputmode="decimal" type="number" step="0.01" min="0" value="${n(state.cash)}"></div><div class="field"><label for="debtInput">融资负债余额（元）</label><input id="debtInput" inputmode="decimal" type="number" step="0.01" min="0" value="${n(state.debt)}"></div></div><div class="action-toolbar"><button class="button small" data-action="save-accounts">保存现金 / 融资</button></div><div class="muted-note" style="margin-top:8px">仅计算当前A股账户，不含其他账户资产。融资余额包括你需要偿还的相关负债；请与券商口径核对。</div></div>
 <div class="cards-grid" style="margin-top:10px"><div class="metric"><div class="label">净资产</div><div class="val">${p.valid?'¥'+money(p.equity):'—'}</div><div class="hint">市值+现金-融资</div></div><div class="metric"><div class="label">融资比例</div><div class="val ${p.debtPct>r.debtCap?'numeric-bad':''}">${percent(p.debtPct)}</div><div class="hint">当前上限 ${percent(r.debtCap)}</div></div><div class="metric"><div class="label">股票总敞口</div><div class="val ${p.stockPct>r.totalCap?'numeric-bad':''}">${percent(p.stockPct)}</div><div class="hint">当前上限 ${percent(r.totalCap)}</div></div><div class="metric"><div class="label">持仓数量</div><div class="val">${p.rows.length} <span class="mini">只</span></div><div class="hint">${p.missing.length?'缺失报价 '+p.missing.length+' 只':'报价完整 '+p.rows.length+' 只'}</div></div></div>
 <div class="section-heading"><h2>持仓明细</h2><span class="pill">${esc(regimeName(state.regime))}风控</span></div>${rows||'<div class="empty">尚未录入持仓。支持按股票代码、股数、成本逐只录入。<br>没有自动读取券商账户权限。</div>'}
 <div class="section-heading"><h2>持仓风险告警</h2></div>${alerts.length?alerts.map(alertHtml).join(''):'<div class="notice">完成持仓与行情录入后，这里将显示单股超限、类别超限、融资超限、总敞口超限。</div>'}
 <div class="notice" style="margin-top:12px"><strong>口径提醒：</strong>融资比例 = 融资负债 / 净资产；股票敞口 = 持仓市值 / 净资产。维持担保比例还涉及信用账户折算和券商风控规则，本工具不替代券商风控。</div>`;
}
function renderRules(){
 const r=rule(),p=portfolio();
 return `<div class="intro-top"><div><div class="eyebrow">RISK BUDGET / EDITABLE</div><h1 class="page-title">动态风控规则</h1><div class="subtle">数字是可编辑的纪律，不是行情预测</div></div></div>
 <div class="panel" style="margin-top:15px"><div class="field"><label for="ruleRegime">正在编辑的市场阶段</label><select id="ruleRegime">${REGIMES.map(x=>`<option value="${x.id}" ${state.regime===x.id?'selected':''}>${esc(x.name)}</option>`).join('')}</select></div><div class="notice" style="margin-top:12px">当前选定：${esc(regimeName(state.regime))}。修改后立即用于所有持仓、预设买价与告警。</div></div>
 <section class="panel" style="margin-top:11px"><div class="section-heading" style="margin:0 0 14px"><h2>总风险预算</h2><span class="mini">单位：净资产百分比</span></div><div class="fields"><div class="field"><label for="debtSuggest">建议融资范围（文本）</label><input id="debtSuggest" value="${esc(r.debtSuggest)}" placeholder="如：0–10%"></div><div class="field"><label for="debtCap">融资硬上限（%）</label><input id="debtCap" type="number" min="0" max="100" step="1" value="${r.debtCap}"></div><div class="field wide"><label for="totalCap">股票总敞口上限（%）</label><input id="totalCap" type="number" min="0" max="300" step="1" value="${r.totalCap}"></div></div><div class="muted-note" style="margin-top:10px">市场弱势时优先限制融资；股票总敞口可能高于100%，因为融资放大了市值/净资产比例。</div></section>
 <section class="panel" style="margin-top:11px"><div class="section-heading" style="margin:0 0 7px"><h2>个股与类别仓位上限</h2></div><div class="risk-row risk-head"><span>分类</span><span>单股上限 %</span><span>类别上限 %</span></div>${CATEGORIES.map(c=>`<div class="risk-row"><span style="font-size:12px">${esc(c.name)}</span><span class="field"><input type="number" min="0" max="300" step="1" class="risk-single" data-category="${c.id}" aria-label="${esc(c.name)}单股上限" value="${r[c.id].single}"></span><span class="field"><input type="number" min="0" max="300" step="1" class="risk-total" data-category="${c.id}" aria-label="${esc(c.name)}类别上限" value="${r[c.id].total}"></span></div>`).join('')}<button class="button block" style="margin-top:15px" data-action="save-rules">保存当前阶段风控规则</button></section>
 <div class="section-heading"><h2>当前规则执行情况</h2></div><div class="panel">${p.valid?`${trackHtml('股票总敞口',p.stockPct,r.totalCap)}${trackHtml('融资比例',p.debtPct,r.debtCap)}${CATEGORIES.map(c=>trackHtml(c.name,(p.categoryMV[c.id]||0)/p.equity*100,r[c.id].total)).join('')}`:'<div class="empty">录入持仓、现金、融资和股票行情，自动对比超配比例。</div>'}</div><div class="warning-band">默认预算属于保守到中性的示范参数，应结合账户规模、个股相关性、财报质量和融资条款校准。尤其不要把“有融资额度”等同于“应该使用融资”。</div>`;
}
function renderSettings(){
 return `<div class="intro-top"><div><div class="eyebrow">DATA / PRIVACY / SYNC</div><h1 class="page-title">数据与设置</h1><div class="subtle">行情从公开数据源采集；个人仓位仅保存在本机</div></div></div>
 <div class="section-heading"><h2>行情自动更新</h2></div><div class="panel"><div class="row-between"><span class="mini">行情来源</span><b style="font-size:12px">${esc(market.source||'尚未采集')}</b></div><div class="divider"></div><div class="row-between"><span class="mini">最近采集</span><b style="font-size:12px">${dateBeijing(market.updated_at)}</b></div><div class="divider"></div><div class="row-between"><span class="mini">报价数量</span><b style="font-size:12px">${n(market.count).toLocaleString('zh-CN')} 只</b></div><div class="action-toolbar"><button class="button" data-action="refresh">立即重新读取</button></div><div class="muted-note" style="margin-top:11px">定时采集由GitHub Actions执行（北京时间工作日16:23）。手机的「立即读取」只是重新加载服务端最新快照，并不直接向交易所发起实时行情请求。节假日和任务失败可能出现延迟。</div></div>
 <div class="section-heading"><h2>数据迁移与备份</h2></div><div class="panel"><div class="notice">观察池、买入价格、实际持仓、现金和融资数据均位于当前浏览器的本地存储。它们不会被GitHub Pages自动同步到其他设备，也不会自动传给行情采集脚本。</div><div class="action-toolbar"><button class="button secondary" data-action="export-backup">导出完整JSON备份</button><button class="button secondary" data-action="import-backup">导入JSON</button><button class="button quiet" data-action="export-csv">导出投资汇总CSV</button></div><div class="warning-band">JSON备份包含真实持仓与融资信息，不要上传至公开GitHub仓库，也不要随意转发。安装到iPhone主屏幕后，建议在主屏幕版内完成数据录入，避免Safari和主屏幕版存储隔离造成误解。</div></div>
 <div class="section-heading"><h2>产品边界</h2></div><div class="panel"><div class="tableish"><div class="row-between" style="margin-bottom:11px"><span>每日A股收盘快照</span><span class="pill good">已实现</span></div><div class="row-between" style="margin-bottom:11px"><span>多档买价、仓位提醒</span><span class="pill good">已实现</span></div><div class="row-between" style="margin-bottom:11px"><span>本地备份与数据导出</span><span class="pill good">已实现</span></div><div class="row-between" style="margin-bottom:11px"><span>手机后台推送通知</span><span class="pill">暂不支持</span></div><div class="row-between" style="margin-bottom:11px"><span>券商账户自动同步</span><span class="pill">暂不支持</span></div><div class="row-between"><span>美股行情 / 财报估值模型</span><span class="pill">后续扩展</span></div></div></div><div class="section-heading"><h2>危险操作</h2></div><button class="button danger" data-action="reset">清空本机设置与持仓</button><div class="subtle" style="margin:13px 0 22px">版本 1.0 · 使用北京时间 · 仅提供风险预算与行情展示，不会自动下单</div>`;
}
function render(){const renderers={overview:renderOverview,watch:renderWatch,holdings:renderHoldings,rules:renderRules,settings:renderSettings};$('#app').innerHTML=renderers[activeTab]();all('.nav-link').forEach(el=>{el.classList.toggle('active',el.dataset.tab===activeTab);el.setAttribute('aria-current',el.dataset.tab===activeTab?'page':'false');});}
function go(tab){activeTab=tab;render();window.scrollTo({top:0,behavior:'instant'});}
function modal(html){$('#modalRoot').innerHTML=`<div class="modal-backdrop" id="modalBackdrop"><section class="modal-sheet" role="dialog" aria-modal="true">${html}</section></div>`;$('#modalBackdrop').addEventListener('click',ev=>{if(ev.target.id==='modalBackdrop')closeModal();});}
function closeModal(){$('#modalRoot').innerHTML='';}
function stockModal(symbol=null){
 const current=symbol?findWatch(symbol):null;const w=current?clone(current):{symbol:'',name:'',sector:'',category:'growth',thesis:'',levels:[],thesisValid:true};
 const levels=Array.from({length:3},(_,i)=>w.levels?.find(l=>Number(l.stage)===i+1)||{stage:i+1,price:'',target:''});
 modal(`<div class="modal-top"><div><div class="eyebrow">WATCHLIST CONFIGURATION</div><div class="modal-title">${current?'编辑观察计划':'添加观察标的'}</div></div><button class="icon-button" data-action="close-modal" aria-label="关闭">×</button></div>
 <form id="stockForm" class="fields"><div class="field"><label for="wSymbol">A股代码（6位）</label><input id="wSymbol" required inputmode="numeric" pattern="[0-9]{6}" maxlength="6" value="${esc(w.symbol)}" ${current?'readonly':''} placeholder="如：002475"></div>
 <div class="field"><label for="wName">股票名称</label><input id="wName" required value="${esc(w.name)}" placeholder="如：立讯精密"></div>
 <div class="field"><label for="wSector">中长期赛道</label><input id="wSector" value="${esc(w.sector)}" placeholder="如：半导体设备"></div>
 <div class="field"><label for="wCategory">风险类别</label><select id="wCategory">${CATEGORIES.map(c=>`<option value="${c.id}" ${w.category===c.id?'selected':''}>${esc(c.name)}</option>`).join('')}</select></div>
 <div class="field wide"><label for="wThesis">研究逻辑 / 基本面观察点</label><textarea id="wThesis" placeholder="为什么关注？什么情况会推翻投资逻辑？">${esc(w.thesis)}</textarea></div>
 <div class="field wide"><label>买入计划（价格为 ≤ 触发价；仓位为净资产累计目标）</label><div class="thresholds"><div class="threshold-labels"><span></span><span>观察买价（元）</span><span>累计目标仓位（%）</span></div>${levels.map((l,i)=>`<div class="threshold"><span class="badge-num">${i+1}档</span><input class="level-price" type="number" min="0" step="0.01" inputmode="decimal" placeholder="价格" value="${l.price??''}"><input class="level-target" type="number" min="0" max="300" step="0.5" inputmode="decimal" placeholder="仓位%" value="${l.target??''}"></div>`).join('')}</div><div class="muted-note">例如：50元→5%，45元→10%，40元→15%。档位价格需递减，目标仓位需递增；均为用户自己制定的计划。</div></div>
 <div class="field"><label for="wManual">手动行情价（可选，优先于自动报价）</label><input id="wManual" type="number" min="0" step="0.01" inputmode="decimal" placeholder="留空=自动" value="${w.manualPrice??''}"></div>
 <div class="field"><label for="wThesisValid">投资逻辑有效性</label><select id="wThesisValid"><option value="true" ${w.thesisValid!==false?'selected':''}>有效，可提示买价</option><option value="false" ${w.thesisValid===false?'selected':''}>待复核，暂停买价提醒</option></select></div>
 <div class="field wide"><div class="inline-fields"><button type="submit" class="button" style="flex:1">${current?'保存修改':'添加标的'}</button>${current?`<button type="button" class="button danger" data-action="delete-stock" data-symbol="${esc(w.symbol)}">删除观察</button>`:''}</div></div></form>`);
 $('#wSymbol')?.addEventListener('change',()=>{const q=market.quotes?.[$('#wSymbol').value.trim()];if(q&&$('#wName').value==='')$('#wName').value=q.name||'';});
 $('#stockForm').addEventListener('submit',ev=>{ev.preventDefault();const code=$('#wSymbol').value.trim();if(!/^\d{6}$/.test(code)){toast('请输入六位A股股票代码');return;}
  if(!current&&findWatch(code)){toast('该股票已在观察池');return;}
  const prices=all('.level-price'),targets=all('.level-target'),savedLevels=[];
  for(let i=0;i<3;i++){
   const p=prices[i].value.trim(),t=targets[i].value.trim();if(!p&&!t)continue;
   if(!p||!t||Number(p)<=0||Number(t)<=0){toast('每档买价和累计仓位必须同时填写正数');return;}
   if(Number(t)>300){toast('累计目标仓位不能超过300%');return;}
   savedLevels.push({stage:i+1,price:Number(p),target:Number(t)});
  }
  for(let i=1;i<savedLevels.length;i++)if(savedLevels[i].price>=savedLevels[i-1].price||savedLevels[i].target<=savedLevels[i-1].target){toast('买价须逐档下降，目标仓位须逐档增加');return;}
  const manual=$('#wManual').value.trim();
  const next={symbol:code,name:$('#wName').value.trim(),sector:$('#wSector').value.trim()||'其他',category:$('#wCategory').value,thesis:$('#wThesis').value.trim(),levels:savedLevels,thesisValid:$('#wThesisValid').value==='true'};
  if(manual){if(Number(manual)<=0){toast('手动行情价必须大于0');return;}next.manualPrice=Number(manual);next.manualAt=current?.manualPrice===next.manualPrice?current.manualAt:new Date().toISOString();}
  if(current)state.watch=state.watch.map(x=>x.symbol===code?next:x);else state.watch.push(next);
  persist();closeModal();render();toast('观察计划已保存在本机');
 });
}
function holdingModal(symbol=null){
 const current=symbol?state.holdings.find(h=>h.symbol===symbol):null;const rows=state.watch;
 modal(`<div class="modal-top"><div><div class="eyebrow">PORTFOLIO POSITION</div><div class="modal-title">${current?'编辑实际持仓':'添加实际持仓'}</div></div><button class="icon-button" data-action="close-modal">×</button></div>
 <form id="holdingForm" class="fields"><div class="field wide"><label for="hSymbol">股票（请先在观察池添加）</label><select id="hSymbol" ${current?'disabled':''}>${rows.map(w=>`<option value="${w.symbol}" ${symbol===w.symbol?'selected':''}>${esc(w.name)} · ${esc(w.symbol)}</option>`).join('')}</select></div>
 <div class="field"><label for="hQty">实际持仓股数</label><input id="hQty" required type="number" min="1" step="1" inputmode="numeric" value="${current?.qty??''}" placeholder="例如 10000"></div><div class="field"><label for="hCost">每股成本（元）</label><input id="hCost" required type="number" min="0" step="0.001" inputmode="decimal" value="${current?.cost??''}" placeholder="例如 49.50"></div>
 <div class="field wide"><div class="notice">该输入是你券商显示的持仓成本；不会自动同步成交记录和手续费。持仓占比将按最新有效行情自动计算。</div></div>
 <div class="field wide"><button class="button block" type="submit">保存实际持仓</button></div></form>`);
 $('#holdingForm').addEventListener('submit',ev=>{ev.preventDefault();const code=$('#hSymbol').value;const qty=Number($('#hQty').value),cost=Number($('#hCost').value);if(!code||!Number.isInteger(qty)||qty<=0||!Number.isFinite(cost)||cost<0){toast('请输入有效的持仓股数和成本');return;}if(state.holdings.some(h=>h.symbol===code&&h.symbol!==symbol)){toast('该股票已在持仓中，请直接编辑');return;}
  state.holdings=state.holdings.filter(h=>h.symbol!==code);state.holdings.push({symbol:code,qty,cost});persist();closeModal();render();toast('持仓已保存');
 });
}
function downloadText(filename,data,type){const blob=new Blob([data],{type});const url=URL.createObjectURL(blob);const a=document.createElement('a');a.href=url;a.download=filename;document.body.appendChild(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);}
function exportCSV(){const p=portfolio();const rows=[['股票代码','股票名称','赛道','分类','最新价','行情状态','持股数','持仓成本','市值','实际仓位占净资产%','单股上限%','一档价','一档目标%','二档价','二档目标%','三档价','三档目标%']];state.watch.forEach(w=>{const q=quoteFor(w.symbol),h=p.rows.find(x=>x.symbol===w.symbol),cat=rule()[w.category]||rule().other;const lv=Array.from({length:3},(_,i)=>(w.levels||[]).find(x=>Number(x.stage)===i+1)||{});rows.push([w.symbol,w.name,w.sector,categoryName(w.category),q?.price??'',q?.manual?'手动':'自动',h?.qty??'',h?.cost??'',h?.mv??'',p.valid?(h?.mv||0)/p.equity*100:'',cat.single,...lv.flatMap(l=>[l.price??'',l.target??''])]);});const csv='\ufeff'+rows.map(a=>a.map(x=>'"'+String(x??'').replace(/"/g,'""')+'"').join(',')).join('\r\n');downloadText('投资驾驶舱_观察池及持仓.csv',csv,'text/csv;charset=utf-8');toast('已生成CSV汇总');}
function exportJSON(){downloadText('投资驾驶舱_本机备份_'+new Date().toISOString().slice(0,10)+'.json',JSON.stringify({app:'northstar-investment-cockpit',version:1,exported_at:new Date().toISOString(),state},null,2),'application/json;charset=utf-8');toast('已导出完整备份，请妥善保管');}
function handleAction(action,el){
 switch(action){
 case 'add-stock':stockModal();break;
 case 'edit-stock':stockModal(el.dataset.symbol);break;
 case 'delete-stock':{const code=el.dataset.symbol;if(state.holdings.some(h=>h.symbol===code)){toast('请先删除实际持仓，再移除观察标的');break;}if(confirm('确定删除这只观察股票及其买价计划？')){state.watch=state.watch.filter(w=>w.symbol!==code);persist();closeModal();render();}break;}
 case 'add-holding':if(!state.watch.length){toast('请先在观察池添加股票');go('watch');}else holdingModal();break;
 case 'edit-holding':holdingModal(el.dataset.symbol);break;
 case 'delete-holding':if(confirm('确定删除这笔实际持仓记录？')){state.holdings=state.holdings.filter(h=>h.symbol!==el.dataset.symbol);persist();render();}break;
 case 'close-modal':closeModal();break;
 case 'save-accounts':{const c=normNum($('#cashInput').value),d=normNum($('#debtInput').value);if(c===null||d===null){toast('现金和融资余额不能为负数');break;}state.cash=c;state.debt=d;persist();render();toast('资金与融资余额已保存');break;}
 case 'save-rules':{
   const rr=state.rules[state.regime];const d=normNum($('#debtCap').value),t=normNum($('#totalCap').value);if(d===null||d>100||t===null||t>300){toast('融资上限应在0–100%，敞口上限在0–300%');break;}
   const values={};let bad=false;
   CATEGORIES.forEach(cat=>{const single=normNum($(`.risk-single[data-category="${cat.id}"]`).value),total=normNum($(`.risk-total[data-category="${cat.id}"]`).value);if(single===null||total===null||single>total||total>300)bad=true;values[cat.id]={single,total};});
   if(bad){toast('单股上限不得超过类别上限，且范围应为0–300%');break;}
   rr.debtCap=d;rr.totalCap=t;rr.debtSuggest=$('#debtSuggest').value.trim()||'0%';CATEGORIES.forEach(c=>rr[c.id]=values[c.id]);persist();render();toast('当前市场阶段的规则已保存');break;
 }
 case 'use-suggested':if(market.technical?.suggested&&confirm(`确认将市场阶段改为「${regimeName(market.technical.suggested)}」？风控预算将立即变化。`)){state.regime=market.technical.suggested;persist();render();}break;
 case 'refresh':refreshMarket(true);break;
 case 'export-backup':exportJSON();break;
 case 'export-csv':exportCSV();break;
 case 'import-backup':$('#importFile').click();break;
 case 'reset':if(confirm('将删除当前设备中的所有观察计划、实际持仓、风险参数。该操作无法撤销，建议先导出备份。')&&confirm('再次确认：要清空本机所有投资数据吗？')){state=initState();persist();render();toast('已恢复初始示例观察池');}break;
 }
}
async function refreshMarket(notify=false){
 const refresh=$('#refreshTop');refresh?.classList.add('loading');
 try{
  const response=await fetch('./data/quotes.json?ts='+Date.now(),{cache:'no-store'});
  if(!response.ok)throw new Error('HTTP '+response.status);
  const data=await response.json();if(!data||typeof data!=='object'||!data.quotes)throw new Error('数据格式不符');
  if(!data.updated_at){if(notify)toast('远程行情尚未采集；请先在GitHub运行更新任务');return;}
  market=data;
  const keep={};const codes=new Set([...state.watch.map(w=>w.symbol),...state.holdings.map(h=>h.symbol)]);
  codes.forEach(code=>{if(data.quotes[code])keep[code]=data.quotes[code];});
  try{localStorage.setItem(MARKET_CACHE_KEY,JSON.stringify({...data,quotes:keep}));}catch(_){/* 离线缓存可选 */}
  render();if(notify)toast('已读取行情快照：'+dateBeijing(data.updated_at));
 }catch(e){if(notify)toast('远程更新未成功：继续使用本机缓存。'+e.message);}
 finally{refresh?.classList.remove('loading');}
}
document.addEventListener('click',ev=>{
 const nav=ev.target.closest('[data-tab]');if(nav){go(nav.dataset.tab);return;}
 const jump=ev.target.closest('[data-tab-jump]');if(jump){go(jump.dataset.tabJump);return;}
 const btn=ev.target.closest('[data-action]');if(btn){handleAction(btn.dataset.action,btn);}
});
document.addEventListener('change',ev=>{
 if(ev.target.id==='quickRegime'||ev.target.id==='ruleRegime'){state.regime=ev.target.value;persist();render();toast('市场阶段已调整，风险预算同步更新');}
});
document.addEventListener('input',ev=>{
 if(ev.target.id==='stockSearch'){searchText=ev.target.value;const selectionStart=ev.target.selectionStart;render();const input=$('#stockSearch');input?.focus();if(input)input.setSelectionRange(selectionStart,selectionStart);}
});
$('#refreshTop').addEventListener('click',()=>refreshMarket(true));
$('#importFile').addEventListener('change',async ev=>{
 const file=ev.target.files[0];if(!file)return;
 try{const raw=JSON.parse(await file.text());const s=raw.state;if(raw.app!=='northstar-investment-cockpit'||!s||!Array.isArray(s.watch)||!Array.isArray(s.holdings)||!s.rules)throw new Error('不是本工具的有效备份');
 if(!confirm('导入备份将覆盖本机观察池、持仓和融资规则。确定继续？'))return;
 state={...initState(),...s};persist();render();toast('备份导入成功');
 }catch(e){toast('导入失败：'+e.message);}finally{ev.target.value='';}
});
render();refreshMarket();
if('serviceWorker' in navigator&&location.protocol.startsWith('http'))window.addEventListener('load',()=>navigator.serviceWorker.register('./sw.js').catch(()=>{}));
