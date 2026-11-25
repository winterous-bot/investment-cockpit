#!/usr/bin/env python3
"""V2.0c downside-risk research. No return optimization or account permissions.
Frozen V2.0b 60/120d adverse-path thresholds; exploratory 20d threshold.
Only aggregated summaries enter public repo. Historical research, not blinded."""
from __future__ import annotations
import json,math,statistics,sys,argparse
from pathlib import Path
from collections import defaultdict
from datetime import date
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"v2b"))
from validate import Tushare,dt,source_series,active,INDEX_WEIGHTS,window,mean,ret,drawdown
HORIZONS={20:(.07,.05),60:(.12,.08),120:(.15,.12)}
GROUPS={"volatility":(0,.33,.67,1.01),"extension":(-1,-.05,.05,.15,10),
        "pressure":(0,.04,.08,.12,1.01),"breadth_change":(-2,-.08,-.03,.03,.08,2),
        "divergence":(-.01,.5,1.01)}
def rank(a,x): return sum(v<=x for v in a)/len(a)
def group(x,edges):
    if x is None:return None
    return next((i for i,(l,r) in enumerate(zip(edges,edges[1:])) if l<=x<r),None)
def bucket_rate(xs):
    n=len(xs); k=sum(xs)
    return {"n":n,"events":k,"rate":round(k/n,4) if n else None}
def quantile(xs,p):
    x=sorted(xs)
    if not x:return None
    q=p*(len(x)-1);a=int(q);return x[a]+(x[min(a+1,len(x)-1)]-x[a])*(q-a)
def load(api,end):
    records=api.ask("trade_cal",{"exchange":"SSE","start_date":"20130101","end_date":end.replace("-",""),"is_open":"1"},"cal_date,is_open")
    days=sorted({dt(str(x["cal_date"])) for x in records if str(x.get("is_open"))=="1"})
    idx={k:source_series(api,"index_daily",k,days) for k in INDEX_WEIGHTS}
    C=[None]*len(days)
    for i,d in enumerate(days):
        use=active(days[max(0,i-1)])
        if not all(idx[k][i] is not None for k in use):continue
        if i==0 or C[i-1] is None:C[i]=1.
        elif all(idx[k][i-1] is not None for k in use):
            C[i]=C[i-1]*(1+sum(w*(idx[k][i]/idx[k][i-1]-1) for k,w in use.items())/sum(use.values()))
    return days,idx,C
def features(days,idx,C,shards):
    vv=[None]*len(days); out=[]
    for i,d in enumerate(days):
        w=window(C,i,21)
        if w:vv[i]=statistics.pstdev([math.log(w[k]/w[k-1]) for k in range(1,len(w))])*math.sqrt(252)
        hist=[v for v in vv[max(0,i-756):i] if v is not None]
        vol=rank(hist,vv[i]) if vv[i] is not None and len(hist)>=600 else None
        ma=window(C,i,120); ext=C[i]/mean(ma)-1 if ma else None
        w=window(C,i,60); dd=1-C[i]/max(w) if w else None
        r20=ret(C,i,20); r5=ret(C,i,5)
        b=shards.get(d,{}).get("B"); prev=shards.get(days[i-20],{}).get("B") if i>=20 else None
        db=b-prev if b is not None and prev is not None else None
        diver=int(r20>=.03 and db<=-.08) if r20 is not None and db is not None else None
        bench=idx["000300.SH"];m=window(bench,i,120)
        ma120=bench[i]/mean(m)-1 if m else None
        x={"volatility":vol,"extension":ext,"pressure":dd,"breadth_change":db,"divergence":diver,
           "r20":r20,"r5":r5,"ma120":ma120}
        y={}
        for H,(md,ad) in HORIZONS.items():
            if i+H<len(C) and (z:=window(C,i+H,H+1)):
                mdd=drawdown(z); adverse=max(0.,1-min(z)/z[0])
                y[H]={"event":int(mdd>md or adverse>ad),"mdd":mdd,"adverse":adverse,"ret":z[-1]/z[0]-1}
        week=date.fromisoformat(d).isocalendar()[:2]
        weekly=i+1<len(days) and date.fromisoformat(days[i+1]).isocalendar()[:2]!=week
        out.append({"i":i,"date":d,"x":x,"y":y,"weekly":weekly})
    return out
def risk_summary(rows,H):
    ys=[r["y"][H] for r in rows]
    d=bucket_rate([x["event"] for x in ys])
    d.update({"median_mdd":quantile([x["mdd"] for x in ys],.5),
              "p90_mdd":quantile([x["mdd"] for x in ys],.9),
              "median_adverse":quantile([x["adverse"] for x in ys],.5),
              "median_return":quantile([x["ret"] for x in ys],.5)})
    return d
def univariate(rows,H):
    ans={}
    for f,edges in GROUPS.items():
        valid=[r for r in rows if group(r["x"][f],edges) is not None]
        ans[f]={"baseline":risk_summary(valid,H),"bins":[{"range":[l,u],**risk_summary([r for r in valid if group(r["x"][f],edges)==j],H)}
                    for j,(l,u) in enumerate(zip(edges,edges[1:]))]}
    return ans
def auc(probs,ys):
    pos=[p for p,y in zip(probs,ys) if y];neg=[p for p,y in zip(probs,ys) if not y]
    return (sum((p>n)+.5*(p==n) for p in pos for n in neg)/(len(pos)*len(neg))) if pos and neg else None
def fit(train,H,fields):
    # Explicit empirical-Bayes additive log-odds; shrink each marginal group to base
    # using 20 pseudo-observations. Average deviations to limit double counting.
    n=len(train); base=(sum(r["y"][H]["event"] for r in train)+1)/(n+2)
    def logit(p):return math.log(p/(1-p))
    tables={}
    for f in fields:
        edges=GROUPS[f];table=[]
        for j in range(len(edges)-1):
            g=[r for r in train if group(r["x"][f],edges)==j]
            rate=(sum(r["y"][H]["event"] for r in g)+20*base)/(len(g)+20)
            table.append(logit(rate)-logit(base))
        tables[f]=table
    def score(r):
        deviations=[tables[f][group(r["x"][f],GROUPS[f])] for f in fields]
        z=logit(base)+mean(deviations)
        return 1/(1+math.exp(-z))
    return score,base
def compare(rows,H,fields,first_year):
    # Walk-forward by calendar year. Training outcomes must mature BEFORE Jan1.
    # Purge overlapping labels at annual cut. Require 80 training weeks.
    pred=[]
    for year in sorted({int(r["date"][:4]) for r in rows if int(r["date"][:4])>=first_year}):
        cut=next(r["i"] for r in rows if r["date"][:4]==str(year))
        train=[r for r in rows if r["i"]+H<cut and all(group(r["x"][f],GROUPS[f]) is not None for f in fields)]
        test=[r for r in rows if r["date"][:4]==str(year) and all(group(r["x"][f],GROUPS[f]) is not None for f in fields)]
        if len(train)<80 or not test:continue
        score,base=fit(train,H,fields)
        # Thresholds learned ONLY in earlier years. Matched ex-post ranking
        # reported separately as discrimination, not a tradable rule.
        cutoffs={str(p):quantile([score(r) for r in train],p) for p in (.25,.5,.75)}
        for r in test:
            pred.append({"row":r,"p":score(r),"base":base,"cutoffs":cutoffs,"train_n":len(train)})
    if not pred:return {"n":0}
    yy=[p["row"]["y"][H]["event"] for p in pred]; pp=[p["p"] for p in pred]
    out={"n":len(pred),"period":[pred[0]["row"]["date"],pred[-1]["row"]["date"]],
         "auc":auc(pp,yy),"ma120_auc":auc([-p["row"]["x"]["ma120"] for p in pred],yy),
         "brier":mean([(p["p"]-y)**2 for p,y in zip(pred,yy)]),
         "base_brier":mean([(p["base"]-y)**2 for p,y in zip(pred,yy)]),
         "base":risk_summary([p["row"] for p in pred],H),"permission":{},"ranking":{},"yearly":{}}
    for q in (.25,.5,.75):
        a=[p["row"] for p in pred if p["p"]<=p["cutoffs"][str(q)]]
        out["permission"][str(q)]={"coverage":len(a)/len(pred),"risk":risk_summary(a,H)}
        n=max(1,round(len(pred)*q)); ranked=sorted(pred,key=lambda p:(p["p"],p["row"]["date"]))[:n]
        # Compare to MA120 margin descending on the identical dates/coverage.
        simple=sorted(pred,key=lambda p:(-p["row"]["x"]["ma120"],p["row"]["date"]))[:n]
        out["ranking"][str(q)]={"model":risk_summary([p["row"] for p in ranked],H),
            "ma120":risk_summary([p["row"] for p in simple],H)}
    for year in sorted({p["row"]["date"][:4] for p in pred}):
        a=[p for p in pred if p["row"]["date"].startswith(year)]
        y=[p["row"]["y"][H]["event"] for p in a]
        permitted=[p["row"] for p in a if p["p"]<=p["cutoffs"]["0.5"]]
        out["yearly"][year]={"n":len(a),"train_n":a[0]["train_n"],"auc":auc([p["p"] for p in a],y),
                              "base":bucket_rate(y),"low_half_training_cut":risk_summary(permitted,H)}
    return out
def main():
    p=argparse.ArgumentParser();p.add_argument("--shards",required=True);p.add_argument("--output",required=True);args=p.parse_args()
    shards={};years={}
    for f in Path(args.shards).rglob("year_*.json"):
        raw=json.loads(f.read_text())
        if raw.get("version")!="V2.0a-frozen-2026-11-17" or raw.get("raw_paid_data_committed") is not False:raise RuntimeError("bad shard")
        years[str(raw["year"])]=len(raw["rows"])
        for r in raw["rows"]:shards[r["date"]]=r
    # Index-only analysis does not depend on expired breadth shards.
    end="2026-11-20"
    api=Tushare();days,idx,C=load(api,end);allrows=features(days,idx,C,shards)
    out={"version":"V2.0c-risk-research-2026-11-25","end":days[-1],"breadth_years":years,"horizons":HORIZONS,"groups":GROUPS,
        "notes":["20-day risk threshold 7% peak-to-trough or 5% adverse is exploratory.",
        "60/120d thresholds unchanged from V2.0b. Weekly outcomes overlap; counts not independent.",
        "Volatility historical rank uses prior 756 sessions (>=600 valid), no future values.",
        "No asset allocation or leverage limit is authorized. No tuning based on 2024+ results.",
        "Historical artifacts may be expired; breadth study restricted to actually available years.",
        "Index-only model and breadth-enhanced model evaluated on separate and common samples.",
        "Annual rolling estimates use only fully matured training outcomes. Ranking at equal coverage is retrospective, not executable.",
        "Probabilities are exploratory shrunken scores, not calibrated forecasts. Earlier data use three indices.",
        "Prior SW2021 historical backcast limitation affects breadth before 2022."],"results":{}}
    for H in HORIZONS:
        rows=[r for r in allrows if r["date"]>="2016-01-01" and r["weekly"] and H in r["y"] and r["x"]["ma120"] is not None]
        complete=[r for r in rows if all(group(r["x"][f],GROUPS[f]) is not None for f in ("volatility","extension","pressure","breadth_change","divergence"))]
        idxfields=["volatility","extension","pressure"]
        out["results"][str(H)]={"all":risk_summary(rows,H),"univariate":univariate(rows,H),
            "univariate_2022_plus":univariate([r for r in rows if r["date"]>="2022-01-01"],H),
            "index_only":compare(rows,H,idxfields,2020),"index_common":compare(complete,H,idxfields,2022),
            "with_breadth":compare(complete,H,idxfields+["breadth_change","divergence"],2022)}
    path=Path(args.output);path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(out,ensure_ascii=False,indent=2))
    print(json.dumps({"years":years,"summary":{h:{k:v.get(k) for k in ("all","index_only","with_breadth")} for h,v in out["results"].items()}},ensure_ascii=False)[:22000])
if __name__=="__main__":main()
