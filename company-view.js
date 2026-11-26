(function(root){
'use strict';const $=id=>document.getElementById(id),el=(t,x,c)=>{const e=document.createElement(t);if(x!==undefined)e.textContent=x;if(c)e.className=c;return e};
const n=x=>typeof x==='number'&&Number.isFinite(x)?x.toFixed(2):'—',pct=x=>typeof x==='number'&&Number.isFinite(x)?(100*x).toFixed(1)+'%':'—',pp=x=>typeof x==='number'&&Number.isFinite(x)?(100*x).toFixed(1)+'pp':'—';
function panel(title){const s=el('section',undefined,'panel');s.append(el('h2',title));return s}
function grid(rows){const g=el('div',undefined,'grid');for(const [k,v] of rows){const m=el('div',undefined,'metric');m.append(el('span',k),el('b',v));g.append(m)}return g}
function table(headers,rows){const wrap=el('div',undefined,'section'),t=el('table'),h=el('tr');for(const x of headers)h.append(el('th',x));t.append(h);for(const row of rows){const r=el('tr');for(const x of row)r.append(el('td',x));t.append(r)}wrap.append(t);return wrap}
function annualBars(rows){const s=el('div');const max=Math.max(1,...rows.map(x=>Math.abs(x.revenue||0)));for(const x of rows){const r=el('div',undefined,'barrow'),track=el('div',undefined,'track'),bar=el('div',undefined,'bar');bar.style.width=(x.revenue===null?0:Math.max(0,x.revenue/max*100))+'%';track.append(bar);r.append(el('span',x.period.slice(0,4)),track,el('span',n(x.revenue)+' 亿'));s.append(r)}return s}
function detail(title,content){const x=el('details');x.append(el('summary',title),content);return x}
function render(x){
 if(!x)return;const p=x.profile,t=p.ttm,b=p.balance,v=x.valuation,d=x.reverse_dcf,c=$('content');c.replaceChildren();$('meta').textContent='行情 '+(v.quote_date||'无')+' · 共通财报期 '+x.report_period+' · 亿元 / % · 北京时间';
 const overview=panel(x.name+' '+x.code+' · '+x.industry);overview.append(grid([['最新收盘',n(v.close)+' 元'],['总市值',n(v.market_cap)+' 亿'],['TTM营收',n(t.revenue)+' 亿'],['TTM扣非利润',n(t.deducted_profit)+' 亿'],['3年营收CAGR',pct(p.revenue_cagr3)],['TTM扣非同比',pct(t.deducted_yoy)],['最新年报ROIC（供应商）',pct(p.annual.at(-1).roic)],['TTM现金转化',pct(t.cash_conversion)]]),el('p','成长扫描预设：'+(x.growth_scan.presets.join('、')||'未满足或无法计算')+' · '+x.growth_scan.reason,'muted'));c.append(overview);
 const a=panel('01 / 长期经营成长');a.append(el('p','近五年营业收入（亿元）','muted'),annualBars(p.annual),table(['财年','营收','同比','扣非','同比','ROIC','ROE','毛利率'],p.annual.map(z=>[z.period.slice(0,4),n(z.revenue),pct(z.revenue_yoy),n(z.deducted_profit),pct(z.deducted_yoy),pct(z.roic),pct(z.roe),pct(z.gross_margin)])),el('p','3年扣非CAGR '+pct(p.deducted_cagr3)+'；ROIC及ROE采用供应商年度指标。','muted'));c.append(a);
 const q=panel('02 / 单季盈利趋势');q.append(el('p','最近三个季度扣非同比','muted'),grid(p.quarters.slice(-3).map(z=>[z.period,pct(z.deducted_yoy)])),el('p',p.acceleration.label||'加速标签不适用：'+(p.acceleration.reason||'缺失'),'muted'),table(['季度','营收','营收同比','扣非利润','扣非同比','扣非率'],p.quarters.map(z=>[z.period,n(z.revenue),pct(z.revenue_yoy),n(z.deducted_profit),pct(z.deducted_yoy),pct(z.deducted_margin)])),el('p','加速为描述性标签，不是经过验证的选股信号。低基数或亏损比较不强行计算。','muted'));c.append(q);
 const cash=panel('03 / 现金流与资产负债');cash.append(grid([['TTM经营现金流',n(t.cfo)+' 亿'],['TTM资本开支',n(t.capex)+' 亿'],['TTM CFO−CAPEX',n(t.fcf_proxy)+' 亿'],['资产负债率',pct(b.debt_ratio)],['货币资金',n(b.cash)+' 亿'],['流动比率',n(b.current_ratio)],['应收账款',n(b.receivables)+' 亿'],['存货',n(b.inventory)+' 亿']]),table(['财年','CFO','CAPEX','CFO−CAPEX','现金转化','负债率'],p.annual.map(z=>[z.period.slice(0,4),n(z.cfo),n(z.capex),n(z.fcf_proxy),pct(z.cash_conversion),pct(z.debt_ratio)])),el('p','CFO−CAPEX不是FCFF；现金转化分母为合并净利润。','muted'));c.append(cash);
 const val=panel('04 / 估值与市场隐含增长');val.append(grid([['PE-TTM',n(v.pe)+' 倍'],['扣非PE-TTM',n(v.deducted_pe)+' 倍'],['PB',n(v.pb)+' 倍'],['历史PE分位',v.historical?pct(v.historical.percentile):'—']]));
 for(const [label,z] of [['历史PE参考',v.historical],['可比同行扣非PE参考',v.peer]]){val.append(el('h3',label));if(z)val.append(table(['样本','P25','P50','P75'],[[z.n,...z.multiple.map(n)],['参考价格',...z.price.map(n)]]));else val.append(el('p','条件不足，不显示参考价格','muted'))}
 if(v.industry_context)val.append(el('p','广义同行背景：'+v.industry_context.n+'家 · 扣非PE中位 '+n(v.industry_context.median)+' 倍（不是可比估值）','muted'));
 val.append(el('h3','反向DCF · 冻结 V1.4.2'));
 if(d.status==='ok'){val.append(table(['预测期','WACC','永续增长','隐含NOPAT增速 / 状态'],d.sensitivity.filter(z=>z.wacc===.1&&z.terminal===.03).map(z=>[z.years+'年',pct(z.wacc),pct(z.terminal),z.status==='ok'?pct(z.growth):z.status])),detail('完整18组敏感性',table(['年','WACC','永续增长','隐含增速 / 状态'],d.sensitivity.map(z=>[z.years,pct(z.wacc),pct(z.terminal),z.status==='ok'?pct(z.growth):z.status]))));}
 else val.append(el('p','模型不适用：'+(d.reason||'未找到可行解'),'warn'));
 if(d.accounting?.warnings?.length)val.append(el('p','会计口径提示：'+d.accounting.warnings.join('；'),'warn'));
 val.append(el('p','估值参照不是目标价；反向DCF不是盈利预测，现金流和投入资本口径存在限制。','muted'));c.append(val);
 const risk=panel('05 / 风险核查清单');for(const f of p.risk_flags){const status={review:'需核查',unknown:'数据不足',not_triggered:'未触发'}[f.status];risk.append(el('p',status+' · '+f.explanation,f.status==='review'?'warn':'muted'))}risk.append(el('p','上述阈值仅为研究提示，无风险评分，不代表公司风险大小。','muted'));
 if(x.filing_check){const checks=x.filing_check.checks;const aLink=el('a','年报核对来源');aLink.href=x.filing_check.source;aLink.target='_blank';aLink.rel='noopener noreferrer';risk.append(el('p','2025年报四项原始数据核对 '+checks.filter(z=>z.match).length+'/'+checks.length),aLink)}else risk.append(el('p','未进行单独公开年报人工交叉核对','muted'));c.append(risk)
}

root.NorthstarCompanyView={render};
})(window);
