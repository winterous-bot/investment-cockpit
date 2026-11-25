#!/usr/bin/env python3
"""Research V2.0d: historical stress coverage and stage/evolution diagnostics.
No changes to production risk limits. Only summary statistics are published.
"""
from __future__ import annotations
from pathlib import Path
from collections import Counter
from datetime import date
import argparse,json,math,statistics,sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"v2b"))
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"v2c"))
from validate import Tushare,load_prices,features,signals,objective,window,mean,ret,drawdown,STATES
from risk_study import quantile,bucket_rate
def bucket(p): return 0 if p<.33 else 1 if p<.67 else 2
def rate(xs):
    return bucket_rate(list(xs))
def pct(x): return round(x,6) if x is not None else None
def vol_rank(C):
    vv=[None]*len(C);ranks=[None]*len(C)
    for i in range(len(C)):
        w=window(C,i,21)
        if w: vv[i]=statistics.pstdev([math.log(w[k]/w[k-1]) for k in range(1,21)])*math.sqrt(252)
        hist=[x for x in vv[max(0,i-756):i] if x is not None]
        if vv[i] is not None and len(hist)>=600:
            ranks[i]=sum(x<=vv[i] for x in hist)/len(hist)
    return vv,ranks
def stress_study(days,C,rows,ranks,H):
    """Annual expanding q90 scenario, trained on matured labels only.
    Monotonic volatility tiers and existing 20% floor, never relax that floor.
    Conditional quantile is descriptive, not a calibrated confidence guarantee."""
    xs=[]
    for i,r in enumerate(rows):
        if r["date"]<"2016-01-01" or not r["week_end"] or ranks[i] is None or i+H>=len(C):continue
        w=window(C,i+H,H+1)
        if w:xs.append({"date":days[i],"end":days[i+H],"bucket":bucket(ranks[i]),"mdd":drawdown(w),"adverse":1-min(w)/w[0]})
    out=[]; calibration=[]
    for year in sorted({x["date"][:4] for x in xs if x["date"]>="2020-01-01"}):
        tr=[x for x in xs if x["end"]<year+"-01-01"]
        te=[x for x in xs if x["date"].startswith(year)]
        if len(tr)<80:continue
        pooled=quantile([x["mdd"] for x in tr],.90)
        levels=[];n=[]
        for b in range(3):
            t=[x["mdd"] for x in tr if x["bucket"]==b];n.append(len(t))
            q=quantile(t,.90) if len(t)>=25 else pooled
            levels.append(max(.20,q,levels[-1] if levels else 0))
        calibration.append({"year":year,"train_n":len(tr),"bucket_n":n,"pooled":pct(max(.20,pooled)),"levels":[pct(x) for x in levels]})
        for x in te:out.append({**x,"fixed":.20,"pooled":max(.20,pooled),"dynamic":levels[x["bucket"]]})
    def summarize(data):
        z={"n":len(data)}
        for m in ("fixed","pooled","dynamic"):
            z[m]={"shock_mean":pct(mean([x[m] for x in data])),"shock_max":pct(max([x[m] for x in data],default=0)),
                  "path_breach":rate(x["mdd"]>x[m] for x in data),"entry_loss_breach":rate(x["adverse"]>x[m] for x in data),
                  "relative_stock_cap_vs_fixed":pct(mean([.20/x[m] for x in data]))}
        return z
    return {"H":H,"calibration":calibration,"all":summarize(out),
            "2022_plus":summarize([x for x in out if x["date"]>="2022-01-01"]),
            "2024_plus":summarize([x for x in out if x["date"]>="2024-01-01"]),
            "yearly":{y:summarize([x for x in out if x["date"].startswith(y)]) for y in sorted({x["date"][:4] for x in out})},
            "volatility_groups":{str(b):summarize([x for x in out if x["bucket"]==b]) for b in range(3)}}
def direction_values(C,rows,sector):
    """D uses only historical T, B, price and industry participation.
    Four components and thresholds from V2.0c, unchanged."""
    I=[]
    for i in range(len(rows)):
        x=[a[i]>mean(w) for a in sector.values() if (w:=window(a,i,60)) is not None]
        I.append(sum(x)/len(x) if len(x)>=max(25,math.ceil(.85*len(sector))) else None)
    def sign(x,q):return 1 if x>=q else -1 if x<=-q else 0
    scores=[None]*len(rows)
    for i in range(20,len(rows)):
        t=rows[i].get("T");t0=rows[i-20].get("T");b=rows[i].get("B");b0=rows[i-20].get("B")
        r=ret(C,i,20)
        if any(x is None for x in (t,t0,b,b0,r,I[i],I[i-20])):continue
        scores[i]=35*sign(t-t0,20)+35*sign(b-b0,.08)+20*sign(r,.03)+10*sign(I[i]-I[i-20],.10)
    return scores
def stage_study(days,idx,sec,C,rows,D):
    """Compare B2 descriptive stage to a backward-looking reference label.
    The reference is constructed from realized trailing returns, not independent
    expert labels; agreement is diagnostic only, not classification accuracy.
    D is separately checked against future broad returns and transitions."""
    ss=signals(rows,"B2")
    refs={H:[objective(days,idx,sec,C,i-H,H) if i>=H and days[i]>="2019-01-01" else None for i in range(len(days))] for H in (60,120)}
    groups={"all":("2019-01-01","9999-12-31"),"2022_plus":("2022-01-01","9999-12-31"),"2024_plus":("2024-01-01","9999-12-31")}
    report={}
    for name,(lo,hi) in groups.items():
        ii=[i for i,r in enumerate(rows) if lo<=r["date"]<=hi and r["week_end"]]
        block={"stage":{},"direction":{}}
        for H in (60,120):
            cm={s:{t:0 for t in STATES} for s in STATES}
            eligible=[i for i in ii if ss[i]["state"] in STATES and refs[H][i] is not None]
            for i in eligible:cm[ss[i]["state"]][refs[H][i]["label"]]+=1
            block["stage"][str(H)]={"n":len(eligible),"agreement":rate(ss[i]["state"]==refs[H][i]["label"] for i in eligible),"confusion":cm}
        for H,threshold in ((20,.03),(60,.05)):
            bins=[(-101,-60),(-60,-20),(-20,20),(20,60),(60,101)]
            def label(d):
                if d<=-60:return 0
                if d<=-20:return 1
                if d<20:return 2
                if d<60:return 3
                return 4
            eligible=[i for i in ii if D[i] is not None and i+H<len(C) and window(C,i+H,H+1) is not None]
            by=[]
            for k in range(5):
                ix=[i for i in eligible if label(D[i])==k]
                rets=[C[i+H]/C[i]-1 for i in ix]
                by.append({"group":k,"n":len(ix),"median_return":pct(quantile(rets,.5)),
                           "up":rate(x>=threshold for x in rets),"down":rate(x<=-threshold for x in rets),
                           "positive":rate(x>0 for x in rets)})
            # Stage transitions: descriptive label at t vs t+H (trailing 60d reference);
            # no imposed ordering of structural and bottoming stages.
            trans={}
            for k in range(5):
                ct=Counter()
                for i in eligible:
                    if label(D[i])!=k or refs[60][i] is None or refs[60][i+H] is None:continue
                    ct[refs[60][i]["label"]+"->"+refs[60][i+H]["label"]]+=1
                trans[str(k)]=dict(ct)
            block["direction"][str(H)]={"n":len(eligible),"threshold":threshold,"bins":by,"transitions":trans}
        report[name]=block
    return report
def main():
    p=argparse.ArgumentParser();p.add_argument("--shards",required=True);p.add_argument("--output",required=True);a=p.parse_args()
    shards={};years={}
    for f in Path(a.shards).rglob("year_*.json"):
        raw=json.loads(f.read_text())
        if raw.get("version")!="V2.0a-frozen-2026-11-17":raise RuntimeError("unexpected shard")
        years[str(raw["year"])]=len(raw["rows"])
        for r in raw["rows"]:shards[r["date"]]=r
    api=Tushare();days,idx,sec=load_prices(api,"2026-11-20")
    C,rows=features(days,idx,sec,shards);vv,ranks=vol_rank(C);D=direction_values(C,rows,sec)
    report={"version":"V2.0d-research-2026-11-25","end":days[-1],"breadth_years":years,
          "stress":{str(H):stress_study(days,C,rows,ranks,H) for H in (60,120)},
          "stage_evolution":stage_study(days,idx,sec,C,rows,D),
          "notes":["Research only; no account data or live permissions.",
                   "Stress q90 of realized maximum drawdown, not forecast of portfolio loss or confidence guarantee.",
                   "Annual expanding estimates only use matured training windows; fixed 20% floor; monotone volatility bins.",
                   "Weekly observations overlap. 2024+ already inspected in prior research, not blind holdout.",
                   "Category shocks and collateral assumptions are policy scenarios, not historical beta estimates.",
                   "Trailing reference label is not independent expert truth. D thresholds from V2.0c; future return thresholds exploratory.",
                   "SW2021 pre-Dec2021 backcast. Missing breadth artifacts excluded. No production changes."]}
    out=Path(a.output);out.parent.mkdir(parents=True,exist_ok=True);out.write_text(json.dumps(report,ensure_ascii=False,indent=2))
    print(json.dumps({"years":years,"stress":{h:v["all"] for h,v in report["stress"].items()},"stage_2022":report["stage_evolution"]["2022_plus"]["stage"]},ensure_ascii=False))
if __name__=="__main__":main()
