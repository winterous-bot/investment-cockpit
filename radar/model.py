"""Industry radar v1.0: rules fixed before initial historical test.
All quantities computed in memory. No paid raw data in Git commits.
"""
from __future__ import annotations
import math,statistics
def avg(a):return statistics.mean(a) if a and all(x is not None for x in a) else None
def ret(a,i,n):
    if i<n or any(v is None or v<=0 for v in a[i-n:i+1]):return None
    return a[i]/a[i-n]-1
def metrics(prices,shares,bench,i):
    if i<25:return None
    r={h:ret(prices,i,h) for h in (3,5,10,20)}
    b={h:ret(bench,i,h) for h in r}
    past=avg(shares[i-24:i-4]);recent=avg(shares[i-4:i+1])
    ma=avg(prices[i-19:i+1])
    if any(v is None for v in (*r.values(),*b.values(),past,recent,ma)) or past<=0 or ma<=0:return None
    return {"r3":r[3],"r5":r[5],"r10":r[10],"r20":r[20],"rs5":r[5]-b[5],"rs10":r[10]-b[10],"rs20":r[20]-b[20],
            "share":recent,"attention":recent/past,"ma20_gap":prices[i]/ma-1,"breakout":prices[i]>max(prices[i-20:i])}
def classify(x):
    """Ordered, descriptive rules. Rank percentile 0=strongest, 1=weakest."""
    if x["rs5"]<0 and x["rank_move"]<=-.15 and x["attention"]<1:return "退潮"
    if x["r5"]>=.12 or (x["ma20_gap"]>=.12 and x["attention"]>=1.5):return "过热"
    if x["rank_pct"]<=.25 and x["rs5"]>=.02 and x["rank_move"]>=.20 and x["attention"]>=1.2 and x["r5"]>0:return "启动"
    if x["rank_pct"]<=.25 and x["rs20"]>0 and x["rs5"]>0 and x["persistence"]>=3:return "主升"
    if x["attention"]>=1.2 and x["rank_move"]>=.10 and x["rs5"]>=0:return "潜伏"
    return "普通"
def cross_section(series,shares,bench,i,prior_ranks):
    data={k:m for k,p in series.items() if (m:=metrics(p,shares[k],bench,i)) is not None}
    if len(data)<math.ceil(.9*len(series)):return {}
    order=sorted(data,key=lambda k:(-data[k]["rs5"],k));n=len(order)
    for j,k in enumerate(order):
        x=data[k];rank=j/max(1,n-1)
        old=prior_ranks[i-5].get(k) if i>=5 else None
        hist=[prior_ranks[q].get(k) for q in range(max(0,i-4),i)]
        x.update(rank=j+1,rank_pct=rank,rank_move=old-rank if old is not None else None,
                 persistence=sum(v is not None and v<=.25 for v in hist)+(rank<=.25))
        x["stage"]=classify(x) if old is not None and len(hist)==4 and all(v is not None for v in hist) else "证据不足"
    return data
def mdd(a):
    peak=a[0];d=0.
    for x in a:peak=max(peak,x);d=max(d,1-x/peak)
    return d
def summarize(samples):
    if not samples:return {"n":0}
    return {"n":len(samples),"dates":len({s["date"] for s in samples}),
            "positive_excess":sum(s["excess"]>0 for s in samples)/len(samples),
            "median_excess":statistics.median(s["excess"] for s in samples),
            "median_drawdown":statistics.median(s["drawdown"] for s in samples),
            "p90_drawdown":sorted(s["drawdown"] for s in samples)[math.ceil(.9*len(samples))-1],
            "top_quartile":sum(s["top"] for s in samples)/len(samples)}
