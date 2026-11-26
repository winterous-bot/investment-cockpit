"""V1.0 research-only earnings acceleration, quarterly year-on-year.
All amounts CNY, rates decimal. No price inputs to signal.
"""
from __future__ import annotations
from datetime import date
import math,statistics
from collections import Counter

VERSION="earnings-acceleration-v1.0"
PARAMS={"base_profit_min":10_000_000,"base_margin_min":.01,"revenue_growth_min":.10,
        "margin_improvement_min":.01,"cash_conversion_min":.80,
        "early_latest_min":.20,"early_prior_max":.20,"early_acceleration_min":.20,
        "sustained_latest_min":.30,"sustained_last_delta_min":.10,"sustained_prev_delta_min":.05}
FIELDS={"income_vip":("revenue","n_income","comp_type"),
        "fina_indicator_vip":("profit_dedt",),
        "cashflow_vip":("n_cashflow_act",)}
def num(x):
    try:
        v=float(x)
        return v if math.isfinite(v) else None
    except (ValueError,TypeError):return None
def valid_date(x):
    s=str(x or "")
    try:
        return s if len(s)==8 and date(int(s[:4]),int(s[4:6]),int(s[6:])) else None
    except (ValueError,TypeError):return None
def qindex(period):
    return int(period[:4])*4+("0331","0630","0930","1231").index(period[4:])
def period(q):
    y,m=divmod(q,4)
    return str(y)+("0331","0630","0930","1231")[m]
def cutoff(q):
    y,m=divmod(q,4)
    return str(y+int(m==3))+("0430","0831","1031","0430")[m]
def latest_common(asof):
    # No separate Q4 signal on annual/Q1 common statutory cutoff.
    y=int(asof[:4]);q=y*4
    return max(t for t in range(q-4,q+3) if t%4!=3 and cutoff(t)<=asof)
def select(raw,endpoint,p,asof):
    fields=FIELDS[endpoint];by={};conflicts=0;invalid=0
    for r in raw:
        k=r.get("ts_code")
        if not isinstance(k,str) or not k.endswith((".SH",".SZ")) or str(r.get("end_date"))!=p:continue
        a=valid_date(r.get("ann_date"));f=valid_date(r.get("f_ann_date"))
        if endpoint!="fina_indicator_vip" and str(r.get("report_type"))!="1":continue
        if not a or (endpoint!="fina_indicator_vip" and not f):invalid+=1;continue
        known=max(a,f or a)
        if known>asof:continue
        v={k:num(r.get(k)) for k in fields}
        by.setdefault(k,[]).append((known,v))
    out={}
    for k,g in by.items():
        t=max(d for d,_ in g)
        same=[v for d,v in g if d==t]
        # Compatible supersets only, no field stitching or vendor future update flag.
        best=[v for v in same if all(all(u[f] is None or v[f]==u[f] for f in fields) for u in same)]
        if not best:conflicts+=1;continue
        out[k]=best[0]
    return out,{"selected":len(out),"conflicts":conflicts,"invalid_date":invalid}
def quarter(data,endpoint,k,q,field):
    a=data.get((endpoint,q),{}).get(k,{}).get(field)
    if a is None:return None
    if q%4==0:return a
    b=data.get((endpoint,q-1),{}).get(k,{}).get(field)
    return a-b if b is not None else None
def quarter_pair(data,k,q):
    rev=quarter(data,"income_vip",k,q,"revenue")
    profit=quarter(data,"fina_indicator_vip",k,q,"profit_dedt")
    return rev,profit
def yoy(a,b):return a/b-1 if a is not None and b is not None and b>0 else None
def metrics(data,k,q):
    p=PARAMS
    # All 3 current and comparison quarters must be ordinary industrial firms.
    for t in (q,q-1,q-2,q-4,q-5,q-6):
        if data.get(("income_vip",t),{}).get(k,{}).get("comp_type")!=1:return None,"company_type_or_missing"
    hist=[]
    for t in (q-2,q-1,q):
        r,e=quarter_pair(data,k,t);br,be=quarter_pair(data,k,t-4)
        if any(v is None for v in (r,e,br,be)):return None,"quarter_missing"
        if min(r,br,e,be)<=0:return None,"nonpositive_profit_or_revenue"
        if be<p["base_profit_min"] or be/br<p["base_margin_min"]:return None,"low_base"
        hist.append({"period":period(t),"profit":e/1e8,"base_profit":be/1e8,
                     "revenue":r/1e8,"profit_yoy":e/be-1,"revenue_yoy":r/br-1,
                     "margin":e/r,"base_margin":be/br,"margin_change":e/r-be/br})
    cash=[quarter(data,"cashflow_vip",k,t,"n_cashflow_act") for t in range(q-3,q+1)]
    net=[quarter(data,"income_vip",k,t,"n_income") for t in range(q-3,q+1)]
    if any(v is None for v in cash+net):return None,"ttm_cash_or_net_missing"
    if sum(net)<=0:return None,"nonpositive_ttm_net"
    cc=sum(cash)/sum(net);g0,g1,g2=[z["profit_yoy"] for z in hist]
    a=g2-g1;b=g1-g0
    x={"code":k,"period":period(q),"history":hist,"growth":g2,"prior_growth":g1,
       "acceleration":a,"prior_acceleration":b,"revenue_growth":hist[-1]["revenue_yoy"],
       "margin_change":hist[-1]["margin_change"],"cash_conversion":cc,
       "ocf_ttm":sum(cash)/1e8,"net_ttm":sum(net)/1e8}
    if x["revenue_growth"]<p["revenue_growth_min"]:return x,"revenue_gate"
    if x["margin_change"]<p["margin_improvement_min"]:return x,"margin_gate"
    if cc<p["cash_conversion_min"]:return x,"cash_gate"
    return x,"ok"
def classify(x):
    p=PARAMS;eps=1e-10
    if x["growth"]+eps>=p["sustained_latest_min"] and x["acceleration"]+eps>=p["sustained_last_delta_min"] and x["prior_acceleration"]+eps>=p["sustained_prev_delta_min"]:
        return "sustained"
    if x["growth"]+eps>=p["early_latest_min"] and x["prior_growth"]<p["early_prior_max"]-eps and x["acceleration"]+eps>=p["early_acceleration_min"]:
        return "early"
    return None
def scan(data,q,codes=None):
    source=data.get(("income_vip",q),{})
    universe=set(source) if codes is None else set(source)&set(codes)
    rows=[];excluded=Counter()
    for k in sorted(universe):
        x,reason=metrics(data,k,q)
        excluded[reason]+=1
        if reason!="ok":continue
        x["signal"]=classify(x);rows.append(x)
    return rows,{"scope":len(universe),"quality_eligible":len(rows),"reasons":dict(excluded),
                "signals":dict(Counter(x["signal"] or "none" for x in rows))}
def groups(rows):
    top=sorted(rows,key=lambda x:(-x["growth"],x["code"]))
    out={}
    for name in ("early","sustained","union"):
        sig=[x for x in rows if x["signal"] and (name=="union" or x["signal"]==name)]
        base=top[:len(sig)]
        out[name]=(sig,base)
    return out
def outcome(data,k,q):
    r,p=quarter_pair(data,k,q);br,bp=quarter_pair(data,k,q-4)
    # Future losses are retained, not filtered out. Missing outcome remains missing.
    return yoy(p,bp)
def paired_stats(signal,base,values):
    a=[values[x["code"]] for x in signal if x["code"] in values and values[x["code"]] is not None]
    b=[values[x["code"]] for x in base if x["code"] in values and values[x["code"]] is not None]
    n=len(signal);m=len(base)
    valid=bool(n and m and len(a)>=.8*n and len(b)>=.8*m)
    return {"n":n,"baseline_n":m,"observed":len(a),"baseline_observed":len(b),
            "overlap":len({x["code"] for x in signal}&{x["code"] for x in base}),
            "coverage_pass":valid,"signal_median":statistics.median(a) if a else None,
            "baseline_median":statistics.median(b) if b else None,
            "signal_mean":statistics.mean(a) if a else None,"baseline_mean":statistics.mean(b) if b else None,
            "median_gap":statistics.median(a)-statistics.median(b) if valid else None,
            "mean_gap":statistics.mean(a)-statistics.mean(b) if valid else None}
