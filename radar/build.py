#!/usr/bin/env python3
"""Build an offline HTML radar and aggregate validation. No public Pages publication."""
from __future__ import annotations
from pathlib import Path
from datetime import date,datetime,timedelta
from zoneinfo import ZoneInfo
from collections import defaultdict
import argparse,json,sys,os,math,html,statistics
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"scripts"))
from tushare_5000 import Tushare,SafeAPIError,POINTS,num
from model import cross_section,ret,mdd,summarize
POINTS["index_member_all"]=2000
START="20211001"
BENCHMARKS={"000300.SH":.30,"000905.SH":.25,"000852.SH":.25,"932000.CSI":.20}
def code(x):
    v=str(x or "").split(".")[0]
    return v+".SI" if len(v)==6 and v.isdigit() else None
def calendar(api,end):
    a=api.ask("trade_cal",{"exchange":"SSE","start_date":START,"end_date":end,"is_open":"1"},"cal_date,is_open")
    return sorted({str(x["cal_date"]) for x in a if str(x.get("is_open"))=="1"})
def get_classification(api,level):
    a=api.ask("index_classify",{"level":level,"src":"SW2021"},"index_code,industry_name,level,is_pub,parent_code")
    result={code(r["index_code"]):str(r["industry_name"]) for r in a if code(r.get("index_code")) and str(r.get("is_pub","1")) not in ("0","False") and r.get("level")==level}
    if not (len(result)==31 if level=="L1" else 110<=len(result)<=134):raise RuntimeError("unexpected SW2021 classification coverage "+level+":"+str(len(result)))
    return result
def get_series(api,endpoint,k,days,fields):
    a=api.ask(endpoint,{"ts_code":k,"start_date":days[0],"end_date":days[-1]},fields)
    d={str(x["trade_date"]):x for x in a}
    return [d.get(x,{}) for x in days]
def benchmark(api,days):
    close={k:[num(x.get("close")) for x in get_series(api,"index_daily",k,days,"trade_date,close")] for k in BENCHMARKS}
    b=[None]*len(days)
    for i,d in enumerate(days):
        weights={k:w for k,w in BENCHMARKS.items() if k!="932000.CSI" or (i>0 and days[i-1]>="20230811")}
        if not all(close[k][i] is not None and close[k][i]>0 for k in weights):continue
        if i==0 or b[i-1] is None:b[i]=1.
        elif all(close[k][i-1] is not None and close[k][i-1]>0 for k in weights):
            b[i]=b[i-1]*(1+sum(w*(close[k][i]/close[k][i-1]-1) for k,w in weights.items())/sum(weights.values()))
    return b
def historical(api,days,classes):
    prices={};amount={}
    for k in sorted({k for d in classes.values() for k in d}):
        rows=get_series(api,"sw_daily",k,days,"ts_code,trade_date,close,amount")
        prices[k]=[num(x.get("close")) for x in rows]
        amount[k]=[num(x.get("amount")) for x in rows]
    # Same-provider L1 total. Never add L2 to denominator. Reject missing amounts.
    base=[sum(amount[k][i] for k in classes["L1"]) if all(amount[k][i] is not None and amount[k][i]>0 for k in classes["L1"]) else None for i in range(len(days))]
    shares={k:[v/base[i] if v is not None and v>0 and base[i] and v<=base[i] else None for i,v in enumerate(a)] for k,a in amount.items()}
    return prices,shares
def run_level(days,series,shares,bench):
    ranks=[];hist=[]
    for i in range(len(days)):
        x=cross_section(series,shares,bench,i,ranks);hist.append(x)
        ranks.append({k:v["rank_pct"] for k,v in x.items()})
    return hist
def backtest(days,series,bench,hist):
    report={}
    # Calendar-week sample, entry next session close, exit H sessions later.
    for H in (5,10,20):
        samples=defaultdict(list)
        for i in range(len(days)-H-1):
            if days[i]<"20220101" or not hist[i]:continue
            if i+1<len(days) and date.fromisoformat(days[i][:4]+"-"+days[i][4:6]+"-"+days[i][6:]).isocalendar()[:2]==date.fromisoformat(days[i+1][:4]+"-"+days[i+1][4:6]+"-"+days[i+1][6:]).isocalendar()[:2]:continue
            entry=i+1;exit=entry+H;rb=ret(bench,exit,H)
            if rb is None:continue
            fut={k:ret(p,exit,H) for k,p in series.items()}
            fut={k:v for k,v in fut.items() if v is not None}
            if len(fut)<math.ceil(.9*len(series)):continue
            top=set(sorted(fut,key=lambda k:(-fut[k],k))[:math.ceil(len(fut)*.25)])
            chosen=[k for k,x in hist[i].items() if x["stage"]=="启动"]
            # compare identical dates and counts; exclude missing outcome from both.
            if not chosen or any(k not in fut for k in chosen):continue
            naive=[k for k in sorted(hist[i],key=lambda k:hist[i][k]["rank"])[:len(chosen)]]
            if any(k not in fut for k in naive):continue
            for key,ks in (("startup",chosen),("top5day_matched",naive)):
                for k in ks:
                    samples[key].append({"date":days[i],"excess":fut[k]-rb,"drawdown":mdd(series[k][entry:exit+1]),"top":k in top})
        report[str(H)]={key:{**summarize(samples[key]),"2022_2023":summarize([x for x in samples[key] if x["date"]<"20240101"]),"2024_plus":summarize([x for x in samples[key] if x["date"]>="20240101"])} for key in ("startup","top5day_matched")}
    return report
def members_and_breadth(api,classes,dates):
    # Point-in-time current membership only. Partition by L1 to avoid row limit.
    d=dates[-1];first=dates[0];membership={};ambiguous=set();names={};issues=[]
    for l1 in classes["L1"]:
        try:a=api.ask("index_member_all",{"l1_code":l1,"is_new":"Y"},"l1_code,l2_code,ts_code,name,in_date,out_date,is_new")
        except SafeAPIError:issues.append(l1);continue
        if not a or len(a)>=2000:issues.append(l1);continue
        for x in a:
            k=str(x.get("ts_code",""));start=str(x.get("in_date") or "");end=str(x.get("out_date") or "")
            if not k.endswith((".SH",".SZ")) or not start or start>first or (end and end<=d):continue
            pair=(code(x.get("l1_code")),code(x.get("l2_code")))
            if pair[0] not in classes["L1"] or pair[1] not in classes["L2"]:continue
            if k in membership and membership[k]!=pair:ambiguous.add(k)
            membership[k]=pair;names[k]=str(x.get("name") or k)
    listed=api.ask("stock_basic",{"list_status":"L"},"ts_code,list_date")
    listed={str(x["ts_code"]) for x in listed if str(x.get("ts_code","")).endswith((".SH",".SZ")) and str(x.get("list_date") or "99999999")<=first}
    membership={k:v for k,v in membership.items() if k in listed}
    if issues or len(listed)<4500 or len(membership)<max(3500,.85*len(listed)):
        return {},{"status":"incomplete","members":len(membership),"listed_eligible":len(listed),"failed_L1":issues,"reason":"成分覆盖不足，不输出广度或个股排名"}
    for k in ambiguous:membership.pop(k,None)
    daily=[]
    for day in dates:
        a=api.ask("daily",{"trade_date":day},"ts_code,pct_chg,amount")
        x={str(r["ts_code"]):(num(r.get("pct_chg")),num(r.get("amount"))) for r in a if str(r.get("ts_code","")).endswith((".SH",".SZ"))}
        if len(x)<max(3500,.9*len(listed)):return {},{"status":"incomplete","members":len(membership),"reason":"个股日线覆盖不足"}
        daily.append(x)
    aggregate=defaultdict(list);totals=defaultdict(int)
    for k,pair in membership.items():
        for sector in pair:totals[sector]+=1
        vals=[a.get(k) for a in daily]
        if any(v is None or v[0] is None or v[0]<=-100 or v[1] is None or v[1]<=0 for v in vals):continue
        rr=math.prod(1+v[0]/100 for v in vals)-1
        for sector in pair:aggregate[sector].append({"code":k,"name":names[k],"r5":rr})
    res={}
    for k,a in aggregate.items():
        if len(a)<5 or len(a)/totals[k]<.8:continue
        res[k]={"n":len(a),"total":totals[k],"rising5":sum(x["r5"]>0 for x in a)/len(a),"leaders":sorted(a,key=lambda x:(-x["r5"],x["code"]))[:5]}
    return res,{"status":"ok","members":len(membership),"listed_eligible":len(listed),"ambiguous_excluded":len(ambiguous),"sectors":len(res),"method":"沪深有效成分，连续5日有效交易，日涨跌幅复合；成分须在观察期起点已纳入"}
def render_html(out,path):
    def esc(x):return html.escape(str(x))
    def p(x):return "—" if x is None else f"{x*100:+.2f}%"
    def pp(x):return "—" if x is None else f"{x*100:.1f}%"
    cards=[]
    for level in ("L1","L2"):
        rows=[]
        for x in out["levels"][level]:
            b=x.get("breadth") or {}
            leaders=" · ".join(esc(y["name"])+" "+p(y["r5"]) for y in b.get("leaders",[]))
            rows.append(f'<tr data-stage="{esc(x["stage"])}" data-name="{esc(x["name"])}"><td>{x["rank"]}</td><td><b>{esc(x["name"])}</b><small>{esc(x["code"])}</small></td><td>{esc(x["stage"])}</td><td>{p(x["r5"])}</td><td>{p(x["rs5"])}</td><td>{p(x["r20"])}</td><td>{x["attention"]:.2f}x</td><td>{pp(b.get("rising5"))}</td><td>{p(x["rank_move"])}</td><td>{leaders or "—"}</td></tr>')
        cards.append(f'<section id="{level}"><h2>{"申万一级" if level=="L1" else "申万二级"}行业 · {len(rows)}个有效</h2><div class="scroll"><table><thead><tr><th>排名</th><th>行业</th><th>阶段</th><th>5日涨幅</th><th>5日超额</th><th>20日涨幅</th><th>关注度</th><th>5日上涨占比</th><th>排名改善</th><th>近5日领涨股</th></tr></thead><tbody>{"".join(rows)}</tbody></table></div></section>')
    content="".join(cards)
    path.write_text(f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>行业热点雷达 V1.0</title><style>
body{{font:15px system-ui,sans-serif;max-width:1200px;margin:0 auto;padding:18px;background:#f4f6f8;color:#172635}}h1{{font-size:25px;margin-bottom:6px}}h2{{font-size:18px}}section{{background:white;border:1px solid #dae1e7;border-radius:12px;padding:12px;margin:16px 0}}.scroll{{overflow-x:auto}}table{{border-collapse:collapse;width:100%;min-width:1050px;font-variant-numeric:tabular-nums}}th,td{{padding:10px;border-bottom:1px solid #e5e8eb;text-align:left;white-space:nowrap}}th{{background:#eaf0f5}}small{{display:block;color:#667688}}input,select{{font:inherit;padding:10px;border:1px solid #c7d0d9;border-radius:8px;max-width:100%;margin:5px 0}}[data-stage="启动"] td:nth-child(3){{color:#176e56;font-weight:700}}[data-stage="过热"] td:nth-child(3){{color:#a0641d}}.note{{color:#516579;font-size:13px}}[hidden]{{display:none!important}}</style><body><h1>行业热点雷达 V1.0</h1><p>行情日期 {esc(out["asof"])} · 北京时间 · 收盘快照</p><p class="note">强度排名按5日相对宽基收益；关注度为最近5日成交额占申万一级合计的均值 / 前20日均值。排名改善为分位变化，不是涨跌幅。阶段仅为观察规则，非买卖建议。行业广度缺失显示 —。</p><label>阶段 <select id="stage"><option>全部</option><option>启动</option><option>主升</option><option>潜伏</option><option>过热</option><option>退潮</option><option>普通</option><option>证据不足</option></select></label> <label>搜索 <input id="query" placeholder="行业名称"></label><p><a href="#L1">一级行业</a> · <a href="#L2">二级行业</a></p>{content}<script>const s=document.getElementById("stage"),q=document.getElementById("query");function f(){{document.querySelectorAll("tr[data-stage]").forEach(r=>r.hidden=(s.value!=="全部"&&r.dataset.stage!==s.value)||!r.dataset.name.includes(q.value.trim()))}}s.addEventListener("change",f);q.addEventListener("input",f);</script></body></html>''',encoding="utf-8")
def main():
    p=argparse.ArgumentParser();p.add_argument("--output",required=True);p.add_argument("--end");a=p.parse_args()
    end=a.end or (datetime.now(ZoneInfo("Asia/Shanghai")).date()-timedelta(days=0)).strftime("%Y%m%d")
    api=Tushare(os.environ.get("TUSHARE_TOKEN"));days=calendar(api,end)
    classes={x:get_classification(api,x) for x in ("L1","L2")}
    prices,shares=historical(api,days,classes);bench=benchmark(api,days)
    hist={level:run_level(days,{k:prices[k] for k in cl},{k:shares[k] for k in cl},bench) for level,cl in classes.items()}
    latest=next((i for i in range(len(days)-1,max(30,len(days)-8),-1) if all(hist[l][i] and sum(x["stage"]!="证据不足" for x in hist[l][i].values())>=.9*len(classes[l]) for l in classes)),None)
    if latest is None:raise RuntimeError("no recent fully covered sector snapshot")
    try:breadth,health=members_and_breadth(api,classes,days[latest-4:latest+1])
    except SafeAPIError:breadth,health={},{"status":"incomplete","reason":"成分或个股数据接口调用失败"}
    out={"version":"industry-radar-v1.0","asof":days[latest],"requested_end":end,"taxonomy":"SW2021","breadth_health":health,"levels":{}}
    report={"asof":days[latest],"history_start":"20220101","coverage":{},"backtest":{},"breadth_health":health,
      "notes":["Index-only historical validation; no historical constituents used.","SW2021 published taxonomy and available histories may have retrospective classification/coverage changes.","Weekly overlapping observations are not independent; no costs, no tradable portfolio result.","Compare startup with equal count top 5d sectors on same signal dates; entry next close.","Breadth is current-only and not included in frozen stage classifier.","No Tushare raw rows/series or tokens committed. Personal research output; no Pages deployment."]}
    for level,cl in classes.items():
        x=hist[level][latest]
        out["levels"][level]=[{"code":k,"name":cl[k],**v,"breadth":breadth.get(k)} for k,v in sorted(x.items(),key=lambda z:z[1]["rank"])]
        report["coverage"][level]={"listed":len(cl),"valid":len(x),"stage_counts":dict(__import__("collections").Counter(v["stage"] for v in x.values()))}
        report["backtest"][level]=backtest(days,{k:prices[k] for k in cl},bench,hist[level])
    output=Path(a.output);output.mkdir(parents=True,exist_ok=True)
    (output/"radar_snapshot.json").write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding="utf-8")
    (output/"validation.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    render_html(out,output/"radar.html")
    print(json.dumps(report,ensure_ascii=False))
if __name__=="__main__":main()
