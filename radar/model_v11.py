"""Radar 1.1 transparent independent observation flags, not trade signals."""
from __future__ import annotations
import math,statistics
def flags(x):
    a=x.get("attention");r=x.get("r5");rs=x.get("rs5");move=x.get("rank_move");gap=x.get("ma20_gap")
    if any(v is None for v in (a,r,rs,move,gap)):return []
    f=[]
    if a>=1.3:f.append("关注度异动")
    if move>=.20:f.append("排名跃升")
    if a>=1.3 and 0<=r<=.03 and rs>=0 and move>=.10:f.append("量价前兆")
    if a>=1.3 and r<0:f.append("放量下跌")
    if a>=1.3 and r>=0 and rs<0:f.append("放量相对弱势")
    return f
def compound(v):return math.prod(1+x[0]/100 for x in v)-1
def valid(v):return v is not None and v[0] is not None and v[0]>-100 and v[1] is not None and v[1]>0
def stock_metrics(vals,industry5,industry20):
    """25 complete sessions: nonoverlap 5 versus preceding 20, comparable returns."""
    if len(vals)!=25 or not all(valid(v) for v in vals):return None
    r5=compound(vals[-5:]);prev5=compound(vals[-10:-5]);r20=compound(vals[-20:])
    a=statistics.mean(v[1] for v in vals[-5:])/statistics.mean(v[1] for v in vals[:-5])
    return {"r5":r5,"prev5":prev5,"r20":r20,"amount_ratio":a,
            "rs5":r5-industry5 if industry5 is not None else None,
            "rs20":r20-industry20 if industry20 is not None else None}
def stock_lists(a,industry5,industry20):
    # Same eligible sample for both breadth windows; stocks have equal weight.
    if not a:return {}
    n=len(a);r=sum(x["r5"]>0 for x in a)/n;old=sum(x["prev5"]>0 for x in a)/n
    leaders=sorted(a,key=lambda x:(-x["r5"],x["code"]))[:5]
    # Relative laggards with positive 5d returns, improving 5d momentum, volume
    # confirmation and positive 20d absolute trend. Never label falling knives buyable.
    candidates=[x for x in a if industry5 is not None and industry20 is not None and industry5>0 and industry20>0
                and 0<x["r5"]<industry5 and x["r5"]>x["prev5"] and x["r20"]>0 and x["amount_ratio"]>=1.2]
    candidates=sorted(candidates,key=lambda x:(-x["amount_ratio"],-x["r5"],x["code"]))[:5]
    return {"n":n,"rising5":r,"prior_rising5":old,"breadth_change":r-old,
            "leaders":leaders,"laggard_watch":candidates}
def timeline(hist,days,k,i):
    keys=("rank","rank_pct","stage","r5","rs5","attention","rank_move")
    return [{"date":days[j],**{a:hist[j][k].get(a) for a in keys}} if k in hist[j] else {"date":days[j],"stage":"证据不足"} for j in range(max(0,i-19),i+1)]
