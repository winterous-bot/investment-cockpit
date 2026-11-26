'use strict';
(function(){

const $=id=>document.getElementById(id), node=(tag,t,c)=>{const x=document.createElement(tag);if(t!==undefined)x.textContent=t;if(c)x.className=c;return x};let data=null,limit=50,scene="balanced";
const fields=[['revenue_cagr','3年营收CAGR下限（%）',100],['deducted_yoy','扣非TTM增长下限（%）',100],['roic','年度ROIC下限（%）',100],['cash_conversion','经营现金流/净利润下限（%）',100],['debt_ratio','资产负债率上限（%）',100],['pe','PE-TTM上限（倍）',1]];
const pct=x=>x==null?'—':(x*100).toFixed(1)+'%',num=x=>x==null?'—':x.toFixed(1);
function choose(id){scene=id;const p=data.report.presets.find(x=>x.id===id);if(!p)throw Error('场景配置缺失');for(const [k,_,s] of fields)$(k).value=+(p.limits[k]*s).toFixed(6);$('value').checked=p.valuation;$('sort').value=p.sort;$('query').value='';limit=50;render()}
function reset(){choose(scene)}
function sceneStatus(){
 const p=data.report.presets.find(x=>x.id===scene);
 const custom=fields.some(([k,_,s])=>Math.abs($(k).valueAsNumber/s-p.limits[k])>1e-8||!Number.isFinite($(k).valueAsNumber))||$('value').checked!==p.valuation;
 $('sceneNote').textContent=p.description+(custom?' · 已手动调整参数':' · 使用预设参数')+'；估值上限仅在勾选时生效。';
 for(const b of $('presets').children){b.classList.toggle('active',b.dataset.id===scene);b.setAttribute('aria-pressed',String(b.dataset.id===scene))}
}
function createPresets(){const stats=data.report.preset_statistics.scenarios;for(const p of data.report.presets){const b=node('button',p.label);b.type='button';b.dataset.id=p.id;b.setAttribute('aria-pressed','false');const s=stats.find(x=>x.id===p.id);b.append(node('small','预设 '+s.quality_count+' 家'));b.onclick=()=>choose(p.id);$('presets').append(b)}}
const dcfReasons={missing_financials:'历史财报字段不完整或有冲突',missing_fcff_ebit_roic:'FCFF、EBIT或ROIC缺失',nonpositive_annual_or_ttm_fcff_ebit:'至少一个年度或TTM的FCFF/EBIT非正',nonpositive_annual_roic:'历史ROIC非正',unstable_cash_conversion:'现金流转化波动过大或异常',roic_outside_model_range:'历史ROIC超出模型适用范围',unverified_equity_value:'收盘价与股本未通过校验',missing_ev_bridge:'净债务或权益字段缺失',minority_equity_mismatch:'少数股东权益核验失败',invalid_ev_bridge:'净债务或少数股东权益异常',invalid_other_equity:'其他权益工具异常',nonpositive_enterprise_value:'企业价值非正',ambiguous:'多解或不唯一',price_above_model_range:'价格超过模型可解释范围',price_below_model_range:'价格低于模型可解释范围',no_solution:'无有效解',residual_error:'数值校验未通过',requires_more_than_100pct_reinvestment:'需超过100%再投资'};
Object.assign(dcfReasons,{missing_statement:'合并财报缺失或版本冲突',income_identity:'利润表勾稽校验失败',balance_identity:'资产负债表勾稽校验失败',cashflow_identity:'直接法与间接法现金流不一致',unstable_or_missing_effective_tax:'有效所得税率样本不足',nonpositive_invested_capital:'投入资本非正',base_scan_mismatch_ocf_ttm:'现金流与原筛选截面不一致',base_scan_mismatch_revenue_ttm:'收入与原筛选截面不一致',base_scan_mismatch_debt_ratio:'负债率与原筛选截面不一致',invalid_income:'利润表字段异常',invalid_cash:'现金余额异常',invalid_capex:'资本支出异常',invalid_debt_or_investments:'债务或金融投资字段异常',debt_exceeds_liabilities:'重构债务超过负债合计',missing_optional_schema:'报表接口缺少字段'});
Object.assign(dcfReasons,{negative_current_minority_requires_review:'最新少数股东权益为负，需核实少数权益市场价值后再估值',negative_minority_unconfirmed:'少数权益为负但缺少单列字段佐证',missing_fin_exp_int_exp:'利息费用缺失，需核对财报附注'});
function auditDetails(r){
 const a=r?.audit;if(!a)return null;
 const d=node('details');d.append(node('summary','查看利息、少数权益及ROIC口径排查'));
 const fmt=v=>v==null?'缺失':num(v/1e8)+'亿';
 for(const t of a.interest){
   if(t.interest_expense==null||t.interest_expense<0||t.interest_income==null||t.interest_income<0)
     d.append(node('p',t.period+'：利息费用 '+fmt(t.interest_expense)+'；利息收入 '+fmt(t.interest_income)+'；EBIT−利润总额（未验证代理） '+fmt(t.implied_interest)+'；不自动填补。','muted'));
 }
 for(const t of a.balance){
   if(t.minority_implied<0||Object.keys(t.negative_items).length||Math.abs(t.minority_gap||0)>1e5)
     d.append(node('p',t.period+'：单列少数权益 '+fmt(t.minority_reported)+'；权益差额 '+fmt(t.minority_implied)+(t.minority_negative_verified?'（负值勾稽一致）':'')+'；负值科目 '+Object.entries(t.negative_items).map(([k,v])=>k+' '+fmt(v)).join(' / '),'muted'));
 }
 const b=r.accounting?.roic_bridge?.at(-1);
 if(b){
  const labels={adjusted:'V1.4.2分类ROIC',v141_all_investments_deducted:'V1.4.1全扣投资ROIC',vendor_roic:'供应商ROIC',no_investment_deduction:'分母不扣金融投资',beginning_capital:'采用期初投入资本',closing_capital:'采用期末投入资本',unadjusted_operating:'分子不扣非核心收益',pbt_plus_interest:'分子采用利润总额加利息',actual_tax_roic:'采用当年实际税率'};
  const grid=node('div',undefined,'grid');for(const [k,label] of Object.entries(labels)){const x=node('div',undefined,'metric');x.append(node('span',label),node('b',pct(b[k])));grid.append(x)}d.append(grid,node('p','每项均单独改变定义，只用于归因，不自动替换DCF使用的ROIC。差异超过10个百分点时提示人工复核。','muted'));
 }
 if(!d.querySelector('p'))d.append(node('p','未发现需要列示的利息或权益异常。','muted'));
 return d;
}
function accountingDetails(r){
 const a=r?.accounting;if(!a)return null;
 const d=node('details');d.append(node('summary','查看自主财务计算及校验'));
 d.append(node('p','最近三年自主ROIC：'+a.roics.map(pct).join(' / ')+'；上一年供应商ROIC '+pct(a.vendor_roic_last),'muted'));
 d.append(node('p','正常化实际税率 '+pct(a.tax)+'；有效年度样本 '+a.tax_observations.map(pct).join(' / '),'muted'));
 const t=a.ttm,fmt=v=>v==null?'缺失':num(v/1e8)+'亿元';
 d.append(node('p','TTM CFO '+fmt(t.cfo)+' − CAPEX '+fmt(t.capex)+' − 估计利息调整 '+fmt(t.interest_adjustment)+' = FCFF代理 '+fmt(t.fcff),'muted'));
 d.append(node('p','独立经营利润/折旧/营运资本法FCFF诊断：'+fmt(t.accrual_fcff)+'；缺失时不补零。','muted'));
 const c=a.capital[a.capital.length-2];
 d.append(node('p','报告期债务代理 '+fmt(c.debt)+'，现金代理 '+fmt(c.cash)+'，识别的非经营投资 '+fmt(c.investments)+'。未分类负债 '+fmt(c.other_liab_unclassified),'muted'));
 d.append(node('p','可选报表空白项目按未披露处理，近似按0计算：利润表 '+a.optional_blank_income+' 项，资产负债表 '+a.optional_blank_balance+' 项；关键字段禁止补零。','muted'));
 const names={material_noncore_income:'非核心收益占比较高',accrual_cashflow_divergence:'现金流与独立勾稽桥差异较大',material_unclassified_liabilities:'未分类负债占比较高',negative_book_minority:'历史负少数权益（已核验）',roic_gap_material:'自主ROIC与供应商相差超过10个百分点',material_unclassified_investments:'未确认用途投资超过投入资本10%，需人工核对'};
 if(a.warnings.length)d.append(node('p','需人工复核：'+a.warnings.map(v=>names[v]||v).join('；'),'muted'));
 return d;
}
function classificationDetails(x){
 const a=x.reverse_dcf?.accounting,cl=a?.investment_classification;if(!cl)return null;
 const d=node('details');d.append(node('summary','查看投入资本分类与V1.4.1对照'));
 const fmt=v=>v==null?'缺失':num(v/1e8)+'亿元';
 const labels={trad_asset:'交易性金融资产',debt_invest:'债权投资',oth_debt_invest:'其他债权投资',oth_eq_invest:'其他权益工具投资',oth_illiq_fin_assets:'其他非流动金融资产',lt_eqt_invest:'长期股权投资'};
 const cur=a.capital.at(-2);
 for(const [k,v] of Object.entries(cur.investment_items))d.append(node('p',labels[k]+'：'+(cur.investment_blank_items.includes(k)?'未披露（近似0）':fmt(v))+' · '+(cl.deducted_fields.includes(k)?'按非经营债权代理扣除':'用途未核实，保留在资本中'),'muted'));
 d.append(node('p','最新扣除 '+fmt(cl.latest_deducted)+'；未分类保留 '+fmt(cl.latest_retained),'muted'),
 node('p','历史3年ROIC：旧口径 '+cl.old_roics.map(pct).join(' / ')+'；新口径 '+a.roics.map(pct).join(' / '),'muted'),
 node('p','EV旧口径 '+num(cl.old_ev)+'亿元；新口径 '+num(a.ev)+'亿元','muted'));
 if(cl.material)d.append(node('p','分类不确定性较大：部分年度未分类投资超过投入资本10%。结果仅供情景研究，需核实财报附注。','muted'));
 const old=x.v141_result;
 if(old){for(const n of [5,10]){const q=old.center?.[String(n)],v=x.reverse_dcf?.sensitivity?.find(t=>t.years===n&&t.wacc===.10&&t.terminal===.03);const f=t=>t?.status==='ok'?pct(t.growth??t.nopat_growth):(dcfReasons[t?.status]||'不适用');d.append(node('p',n+'年隐含NOPAT增速（同批原始报表）：旧 '+f(q)+' → 新 '+f(v),'muted'))}}
 d.append(node('p','暂按账面债权投资扣除，交易性金融资产及权益类持仓并非确定的经营资产；由于分子仍剔除投资收益，保留金额是保守情景，不是精确经营ROIC。未逐股核实附注、公允价值或受限状态。','muted'));
 return d;
}
function reverseDCFCard(x){
 const r=x.reverse_dcf,box=node('div',undefined,'dcf');box.append(node('h3','反向DCF · 股价隐含经营预期'));
 if(!r||r.status!=='ok'){box.append(node('p',(r?.category==='model'?'财务计算完成，模型不适用：':'财务数据不足或校验失败：')+(dcfReasons[r?.reason]||(r?.reason||'模型输入不足')),'muted'));const a=accountingDetails(r);if(a)box.append(a);const au=auditDetails(r);if(au)box.append(au);const cl=classificationDetails(x);if(cl)box.append(cl);return box}
 const b=r.base,center=n=>r.sensitivity.find(v=>v.years===n&&v.wacc===.10&&v.terminal===.03);
 box.append(node('p','基准假设：WACC 10% · 永续增长3% · 历史3年中位ROIC '+pct(b.roic),'muted'));
 const g=node('div',undefined,'grid');
 for(const n of [5,10]){
  const z=center(n),c=node('div',undefined,'metric');c.append(node('span',n+'年隐含NOPAT CAGR'));
  c.append(node('b',z?.status==='ok'?pct(z.nopat_growth):(dcfReasons[z?.status]||'无有效解')));
  if(z?.status==='ok')c.append(node('span','对应FCFF CAGR '+pct(z.fcff_cagr)+' · 再投资率 '+pct(z.reinvestment)));
  g.append(c);
 }
 box.append(g,node('p','不是实际预测。FCFF CAGR由标准化基期到增长期末推算，NOPAT增长为求解变量。','muted'));
 const detail=node('details');detail.append(node('summary','查看敏感性、现金流基数和估值假设'));
 detail.append(node('p','正常化FCFF '+num(b.fcff)+'亿元 · TTM FCFF '+num(b.ttm_fcff)+'亿元 · TTM税后经营利润 '+num(b.nopat)+'亿元','muted'),
 node('p','最近三年FCFF '+b.annual_fcff.map(num).join(' / ')+' 亿元 · 正常化实际税率 '+pct(b.tax),'muted'),
 node('p','市值 '+num(b.equity)+'亿元 + 净债务 '+num(b.netdebt)+' − 非经营投资 '+num(b.investments)+' + 少数股东权益 '+num(b.minority)+' + 其他权益工具 '+num(b.other_equity)+' = 企业价值 '+num(b.ev)+'亿元','muted'));
 function table(headers,rows){const t=node('table'),head=node('tr');headers.forEach(v=>head.append(node('th',v)));t.append(head);for(const row of rows){const tr=node('tr');row.forEach(v=>tr.append(node('td',v)));t.append(tr)}return t}
 for(const n of [5,10]){
  detail.append(node('h4',n+'年：隐含NOPAT增长敏感性'));
  const grid=[.08,.10,.12].map(w=>[pct(w),...[.02,.03,.04].map(t=>{const z=r.sensitivity.find(v=>v.years===n&&v.wacc===w&&v.terminal===t);return z?.status==='ok'?pct(z.nopat_growth):(dcfReasons[z?.status]||'—')})]);
  detail.append(table(['WACC / 永续','2%','3%','4%'],grid));
  detail.append(node('h4',n+'年：假设增长率对应价格（WACC 10%，永续3%）'));
  detail.append(table(['NOPAT增长','参考价格','再投资率'],r.forward.filter(v=>v.years===n).map(v=>[pct(v.growth),v.status==='ok'&&v.price!=null?v.price.toFixed(2)+'元':(dcfReasons[v.status]||'不适用'),v.status==='ok'?pct(v.reinvestment):'—'])));
 }
 detail.append(node('p','增长期再投资率=max(增长率,0)/历史3年中位ROIC；仅接受不超过100%的再投资。终值ROIC=WACC。使用自主重构的净债务及债权投资代理（未分类投资不单独计价），少数权益按账面值。FCFF为现金流量表法的近似值，受现金税、利息、租赁及未分类科目影响；并非审计后精确FCFF。','muted'),
 node('p','超过模型范围不代表股票必然高估；未来增量ROIC、利润率、融资及增长持续时间变化均可能改变结果。','muted'));
 box.append(detail);const a=accountingDetails(r);if(a)box.append(a);const au=auditDetails(r);if(au)box.append(au);const cl=classificationDetails(x);if(cl)box.append(cl);return box;
}
function valuationCard(x){
 const v=x.valuation||{},out=node('div',undefined,'valuation'),line=node('div',undefined,'price-line');
 const yuan=n=>n==null?'—':n.toFixed(2)+' 元';
 line.append(node('span','最新收盘价','muted'),node('strong',yuan(v.close)));out.append(line,node('div',v.quote_date?'行情日期 '+v.quote_date+' · 非盘中实时':'暂无有效收盘价','muted'));
 function anchor(title,ref,info,missing){
  const box=node('div',undefined,'reference');box.append(node('span',title,'muted'));
  if(!ref){box.append(node('span',missing,'muted'));out.append(box);return}
  box.append(node('b',ref.price[0].toFixed(2)+'–'+ref.price[2].toFixed(2)+' 元'),node('span','中位参照 '+yuan(ref.price[1])+' · '+ref.multiple[0].toFixed(1)+'–'+ref.multiple[2].toFixed(1)+' 倍','muted'),node('div',(ref.relative_to_median<=0?'较中位折价 ':'较中位溢价 ')+pct(Math.abs(ref.relative_to_median)),'discount'),node('span',info,'muted'));
  out.append(box);
 }
 anchor('历史PE参考区间（P25–P75）',v.historical,v.historical?'正PE样本 '+v.historical.n+'/36 · 当前历史分位 '+pct(v.historical.percentile):'','历史正PE样本不足或价格/股本未通过校验');
 anchor('匹配同行扣非PE参考区间（P25–P75）',v.peer,v.peer?'匹配 '+v.peer.n+' 家 · '+v.peer.industry:'','相似同行不足8家或价格/股本未通过校验');
 if(!v.peer&&v.industry_context)out.append(node('p','仅供背景：同分类 '+v.industry_context.n+' 家扣非PE中位 '+num(v.industry_context.median)+' 倍；不生成参考价格。','muted'));
 if(v.earnings_basis_warning)out.append(node('p','普通与扣非PE差异较大，请核查非经常性损益或利润口径。','muted'));
 out.append(node('p','相对估值区间不是目标价或内在价值。两种方法利润口径不同，不作平均。','muted'));return out;
}
function render(){if(!data)return;sceneStatus();$('pe').disabled=!$('value').checked;const lim={};for(const [k,_,s] of fields){const v=$(k).valueAsNumber;if(!Number.isFinite(v)||(k==='pe'&&v<=0)||(k==='debt_ratio'&&(v<0||v>100))){$('count').textContent='请输入有效筛选条件';$('rows').replaceChildren();return}lim[k]=v/s}
const q=$('query').value.trim(),k=$('sort').value;const all=data.rows.filter(x=>fields.slice(0,4).every(([f])=>x[f]!=null&&x[f]>=lim[f])&&x.debt_ratio!=null&&x.debt_ratio<=lim.debt_ratio&&(!$('value').checked||(x.pe>0&&x.pe<=lim.pe)));
const selected=all.filter(x=>!q||[x.name,x.code,x.industry].some(v=>String(v).includes(q)));selected.sort((a,b)=>k==='pe'?(a.pe??Infinity)-(b.pe??Infinity):b[k]-a[k]);$('count').textContent='符合条件 '+all.length+' 家 · 当前显示 '+Math.min(limit,selected.length)+' / '+selected.length+' 家';$('rows').replaceChildren();for(const x of selected.slice(0,limit)){const r=node('div',undefined,'stock');r.append(node('b',x.name+' '+x.code),node('div',x.industry+' · 市值 '+num(x.market_cap)+' 亿元','muted'));const g=node('div',undefined,'metrics');for(const [name,v] of [['营收CAGR',pct(x.revenue_cagr)],['扣非增长',pct(x.deducted_yoy)],['ROIC',pct(x.roic)],['现金转化',pct(x.cash_conversion)],['负债率',pct(x.debt_ratio)],['PE-TTM',num(x.pe)],['扣非PE',num(x.deducted_pe)],['扣非TTM(亿)',num(x.deducted_ttm)],['简化FCF(亿)',num(x.fcf_proxy)]]){const d=node('div',undefined,'metric');d.append(node('span',name),node('b',v));g.append(d)}const add=typeof window!=='undefined'&&window.NorthstarWatchlistLink?.addButton(x,node);if(add)r.append(add);r.append(g,valuationCard(x),reverseDCFCard(x));$('rows').append(r)}$('more').hidden=selected.length<=limit;}
function mount(snapshot){data=snapshot;limit=50;const r=data.report;document.getElementById('growthMain').hidden=false;$('health').replaceChildren(node('p',r.data_coverage_pass?'财务基础数据覆盖检查通过':'覆盖不足：仅供诊断','muted'),node('p','估值日期 '+r.quote_date+' · 财报期 '+r.periods.latest),node('p','沪深上市 '+r.listed_shsz+' · 工商业样本 '+r.industrial_commercial+' · 指标完整 '+r.complete_metrics),node('p','默认质量通过 '+r.quality_pass+' · 同时满足估值 '+r.quality_and_valuation_pass),node('p','反向DCF仅在适用时展示；并非内在价值或收益预测。','muted'));$('filters').replaceChildren();$('presets').replaceChildren();for(const [k,label,s] of fields){const l=node('label',label),i=node('input');i.id=k;i.type='number';i.step='any';i.oninput=()=>{limit=50;render()};l.append(i);$('filters').append(l)}createPresets();choose(scene)}
window.NorthstarGrowthView={mount};
$('reset').onclick=reset;$('query').oninput=()=>{limit=50;render()};$('sort').onchange=()=>{limit=50;render()};$('value').onchange=()=>{limit=50;render()};$('more').onclick=()=>{limit+=50;render()};

})();
