#!/usr/bin/env python3
"""V1.1 independent daily radar scanner; no public deployment."""
from __future__ import annotations
import argparse,os,sys,math,json,statistics
from pathlib import Path
from datetime import datetime,date
from zoneinfo import ZoneInfo
from collections import defaultdict,Counter
from build import Tushare,SafeAPIError,num,code,calendar,get_classification,historical,benchmark,run_level,backtest
from model import ret,mdd,summarize
from model_v11 import flags,stock_metrics,stock_lists,timeline
def breadth(api,classes,days,hist,idx):
    dates=days[idx-24:idx+1]; first=dates[0]; end=dates[-1]
    membership={};names={};ambiguous=set();issues=[]
    for l1 in classes["L1"]:
        try:a=api.ask("index_member_all",{"l1_code":l1,"is_new":"Y"},"l1_code,l2_code,ts_code,name,in_date,out_date,is_new")
        except SafeAPIError:issues.append(l1);continue
        if not a or len(a)>=2000:issues.append(l1);continue
        for x in a:
            k=str(x.get("ts_code",""));start=str(x.get("in_date") or "");stop=str(x.get("out_date") or "")
            pair=(code(x.get("l1_code")),code(x.get("l2_code")))
            if not k.endswith((".SH",".SZ")) or not start or start>first or (stop and stop<=end):continue
            if pair[0] not in classes["L1"] or pair[1] not in classes["L2"]:continue
            if k in membership and membership[k]!=pair:ambiguous.add(k)
            membership[k]=pair;names[k]=str(x.get("name") or k)
    listed=api.ask("stock_basic",{"list_status":"L"},"ts_code,list_date")
    eligible={str(x["ts_code"]) for x in listed if str(x.get("ts_code","")).endswith((".SH",".SZ")) and str(x.get("list_date") or "99999999")<=first}
    membership={k:v for k,v in membership.items() if k in eligible and k not in ambiguous}
    health={"eligible":len(eligible),"members":len(membership),"failed_L1":issues,"ambiguous":len(ambiguous),"window":dates}
    if issues or len(eligible)<4500 or len(membership)<.85*len(eligible):
        return {},{**health,"status":"incomplete","reason":"成分覆盖不足"}
    daily=[]
    for d in dates:
        a=api.ask("daily",{"trade_date":d},"ts_code,pct_chg,amount")
        x={str(r["ts_code"]):(num(r.get("pct_chg")),num(r.get("amount"))) for r in a if str(r.get("ts_code","")).endswith((".SH",".SZ"))}
        if len(x)<max(3500,.9*len(eligible)):return {},{**health,"status":"incomplete","reason":"个股日线截面不足","failed_date":d}
        daily.append(x)
    h={k:v for level in hist.values() for k,v in level[idx].items()}
    agg=defaultdict(list);tot=Counter()
    for k,pair in membership.items():
        vals=[d.get(k) for d in daily]
        for sector in pair:
            tot[sector]+=1
            m=h.get(sector)
            if not m:continue
            if (x:=stock_metrics(vals,m["r5"],m["r20"])) is not None:
                agg[sector].append({"code":k,"name":names[k],**x})
    out={}
    for k,n in tot.items():
        a=agg[k]
        if len(a)<5 or len(a)<.8*n:continue
        out[k]={"total":n,**stock_lists(a,h[k]["r5"],h[k]["r20"])}
    return out,{**health,"status":"ok","sectors":len(out),"valid_stocks":len({x["code"] for a in agg.values() for x in a}),"method":"现时成分且25日全有效；前后5日同样本比较；非历史PIT"}
def study(days,series,bench,hist):
    # Matched dates and counts, chronological weekly entries. Separate observations,
    # no tuning against previous V1.0 outcomes. Compare early flag to raw attention,
    # and rank leap to simple 5-day strength; no stock-level historical claims.
    result={}
    for flag,key in (("量价前兆","early"),("关注度异动","attention"),("排名跃升","rank_leap")):
        result[key]={}
        for H in (5,10,20):
            samples=defaultdict(list)
            for i in range(len(days)-H-1):
                if days[i]<"20220101" or not hist[i]:continue
                d=lambda x:date(int(x[:4]),int(x[4:6]),int(x[6:]))
                if d(days[i]).isocalendar()[:2]==d(days[i+1]).isocalendar()[:2]:continue
                cand=[k for k,x in hist[i].items() if flag in flags(x)]
                if not cand:continue
                entry=i+1;exit=entry+H;rb=ret(bench,exit,H)
                if rb is None:continue
                fut={k:ret(v,exit,H) for k,v in series.items()}
                fut={k:v for k,v in fut.items() if v is not None}
                if len(fut)<math.ceil(.9*len(series)):continue
                top=set(sorted(fut,key=lambda k:(-fut[k],k))[:math.ceil(.25*len(fut))])
                base=sorted(hist[i],key=lambda k:(-hist[i][k]["r5"],k))[:len(cand)]
                raw=sorted(hist[i],key=lambda k:(-hist[i][k]["attention"],k))[:len(cand)]
                if any(k not in fut for k in cand+base+raw):continue
                for label,ks in (("signal",cand),("strength",base),("attention",raw)):
                    for k in ks:samples[label].append({"date":days[i],"excess":fut[k]-rb,"drawdown":mdd(series[k][entry:exit+1]),"top":k in top})
            result[key][str(H)]={k:{**summarize(samples[k]),"2024_plus":summarize([s for s in samples[k] if s["date"]>="20240101"])} for k in ("signal","strength","attention")}
    return result
def main():
    from view_v11 import render
    p=argparse.ArgumentParser();p.add_argument("--output",required=True);p.add_argument("--end");a=p.parse_args()
    end=a.end or datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y%m%d")
    api=Tushare(os.environ.get("TUSHARE_TOKEN"));days=calendar(api,end)
    classes={l:get_classification(api,l) for l in ("L1","L2")}
    prices,shares=historical(api,days,classes);bench=benchmark(api,days)
    hist={l:run_level(days,{k:prices[k] for k in cl},{k:shares[k] for k in cl},bench) for l,cl in classes.items()}
    i=next((i for i in range(len(days)-1,max(30,len(days)-8),-1) if all(hist[l][i] and sum(x["stage"]!="证据不足" for x in hist[l][i].values())>=.9*len(classes[l]) for l in classes)),None)
    if i is None:raise RuntimeError("no recent complete snapshot")
    try:b,h=breadth(api,classes,days,hist,i)
    except SafeAPIError:b,h={},{"status":"incomplete","reason":"成分或个股接口失败"}
    out={"version":"industry-radar-v1.1","asof":days[i],"requested_end":end,"breadth_health":h,"levels":{}}
    report={"version":out["version"],"asof":days[i],"breadth_health":{k:v for k,v in h.items() if k!="window"},"levels":{},"validation":{},
            "notes":["Frozen V1.1 observation thresholds; exploratory historical evidence only; 2024+ not blind.",
              "Index-only historical validation, matched signal dates/counts, next close entry, no costs, weekly overlapping samples.",
              "Current breadth and stock candidates use 25 fully valid sessions and current memberships only; no stock backtest.",
              "All results are derived research data; no raw Tushare series or personal positions. No Pages deployment."]}
    for l,cl in classes.items():
        data=[]
        for k,x in sorted(hist[l][i].items(),key=lambda z:z[1]["rank"]):
            f=flags(x);v=b.get(k)
            if v and v["breadth_change"]>=.15:f.append("扩散增强")
            if v and v["breadth_change"]<=-.15:f.append("扩散收窄")
            data.append({"code":k,"name":cl[k],**x,"flags":f,"breadth":v,"timeline":timeline(hist[l],days,k,i)})
        out["levels"][l]=data
        def short(x):return {"name":x["name"],"rank":x["rank"],"r5":round(x["r5"],4),"attention":round(x["attention"],3),"move":round(x["rank_move"],4) if x["rank_move"] is not None else None,"flags":x["flags"],"breadth_change":round(x["breadth"]["breadth_change"],4) if x["breadth"] else None}
        report["levels"][l]={"listed":len(cl),"valid":len(data),"flag_counts":dict(Counter(f for x in data for f in x["flags"])),
             "attention_top":[short(x) for x in sorted(data,key=lambda x:-x["attention"])[:5]],
             "rank_leap_top":[short(x) for x in sorted([x for x in data if x["rank_move"] is not None],key=lambda x:-x["rank_move"])[:5]],
             "early":[short(x) for x in data if "量价前兆" in x["flags"]],
             "breadth_covered":sum(x["breadth"] is not None for x in data)}
        report["validation"][l]=study(days,{k:prices[k] for k in cl},bench,hist[l])
    p=Path(a.output);p.mkdir(parents=True,exist_ok=True)
    (p/"radar_snapshot.json").write_text(json.dumps(out,ensure_ascii=False),encoding="utf-8")
    (p/"validation.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    render(out,p/"radar.html")
    # Public log: coverage and historical aggregate only; do not print stock or industry derived rankings.
    print(json.dumps({**report,"levels":{l:{k:v for k,v in x.items() if k not in ("attention_top","rank_leap_top","early")} for l,x in report["levels"].items()}},ensure_ascii=False))
if __name__=="__main__":main()
