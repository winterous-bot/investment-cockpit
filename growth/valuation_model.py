"""Relative valuation references, not intrinsic fair value or buy signals."""
from __future__ import annotations
from collections import defaultdict
from datetime import datetime
from growth_model import number,valid_date,PRESETS,passes

MIN_HISTORY=24
MIN_PEERS=8
MATCH={"revenue_cagr":.15,"deducted_yoy":.30,"roic":.07}
def positive(v):
    x=number(v)
    return x if x is not None and x>0 else None
def percentile(values,q):
    a=sorted(values)
    if not a:return None
    i=(len(a)-1)*q
    lo=int(i);hi=min(lo+1,len(a)-1)
    return a[lo]+(a[hi]-a[lo])*(i-lo)
def reference(multiples,eps,price):
    if not multiples or not positive(eps) or not positive(price):return None
    m=[percentile(multiples,q) for q in (.25,.5,.75)]
    p=[x*eps for x in m]
    return {"n":len(multiples),"multiple":m,"price":p,
            "relative_to_median":price/p[1]-1}
def verified_quote(row,quote,day):
    """Verify same-date price and vendor multiple/capitalization against base scan."""
    if not quote or quote.get("trade_date")!=day:return None
    close=positive(quote.get("close"));mv=positive(quote.get("total_mv"));shares=positive(quote.get("total_share"))
    if not close:return None
    old_mv=positive(row.get("market_cap"))
    old_pe=positive(row.get("pe"));pe=positive(quote.get("pe_ttm"))
    # A corrected or missing valuation field is not silently mixed with the old scan.
    consistent=bool(mv and old_mv and abs(mv/10000/old_mv-1)<=.01 and
        ((old_pe is None and pe is None) or (old_pe and pe and abs(pe/old_pe-1)<=.01)))
    share_ok=bool(consistent and shares and abs(close*shares/mv-1)<=.02)
    return {"close":close,"pe":pe,"consistent":consistent,"share_ok":share_ok}
def historical(row,quote,history,dates):
    # Exactly the last 36 completed calendar month ends; positive reported PE only.
    if not quote or not quote["consistent"] or not quote["share_ok"] or not quote["pe"]:return None
    a=[positive(history.get(d)) for d in dates]
    n=sum(v is not None for v in a)
    # Avoid a reference drawn solely from one profitable subperiod.
    if len(dates)!=36 or n<MIN_HISTORY or any(sum(v is not None for v in a[i:i+12])<6 for i in (0,12,24)):return None
    values=[v for v in a if v is not None]
    r=reference(values,quote["close"]/quote["pe"],quote["close"])
    r.update({"percentile":sum(v<quote["pe"] for v in values)/n+.5*sum(v==quote["pe"] for v in values)/n,
              "first":dates[0],"last":dates[-1],"expected":len(dates)})
    return r
def peer_reference(row,quote,cohort):
    # Use TTM deducted PE throughout this anchor. Never mix with reported PE.
    pe=positive(row.get("deducted_pe"))
    if not quote or not quote["share_ok"] or not pe or not row.get("industry") or row["industry"]=="未分类":return None,None
    pool=[p for p in cohort if p["code"]!=row["code"] and p.get("industry")==row["industry"] and positive(p.get("deducted_pe"))]
    context={"n":len(pool),"median":percentile([p["deducted_pe"] for p in pool],.5)} if len(pool)>=MIN_PEERS else None
    matched=[p for p in pool if all(number(row.get(k)) is not None and number(p.get(k)) is not None and abs(row[k]-p[k])<=v+1e-12 for k,v in MATCH.items())]
    if len(matched)<MIN_PEERS:return None,context
    r=reference([p["deducted_pe"] for p in matched],quote["close"]/pe,quote["close"])
    r["industry"]=row["industry"]
    return r,context
def completed_month_ends(calendar,asof):
    d=valid_date(asof)
    if not d:raise ValueError("Invalid cutoff")
    y,m=int(d[:4]),int(d[4:6]);months=[]
    for i in range(36):
        m-=1
        if m==0:y-=1;m=12
        months.append(f"{y:04d}{m:02d}")
    by={}
    for x in calendar:
        t=valid_date(x.get("cal_date"))
        if t and str(x.get("is_open"))=="1" and t[:6] in months:by[t[:6]]=max(t,by.get(t[:6],""))
    if len(by)!=36:raise ValueError("Calendar does not cover 36 completed months")
    return [by[k] for k in reversed(months)]
def enrich(rows,quotes,histories,dates,day):
    q={x["code"]:verified_quote(x,quotes.get(x["code"]),day) for x in rows}
    cohorts=defaultdict(list)
    for x in rows:
        z=q[x["code"]]
        if z and z["share_ok"]:cohorts[x["industry"]].append(x)
    for x in rows:
        z=q[x["code"]];h=historical(x,z,histories.get(x["code"],{}),dates)
        p,c=peer_reference(x,z,cohorts[x["industry"]])
        ordinary=positive(x.get("pe"));deducted=positive(x.get("deducted_pe"))
        x["valuation"]={"close":z["close"] if z else None,"quote_date":day if z else None,
            "quote_consistent":bool(z and z["consistent"]),"share_verified":bool(z and z["share_ok"]),
            "historical":h,"peer":p,"industry_context":c,
            "earnings_basis_warning":bool(ordinary and deducted and (deducted/ordinary>1.3 or deducted/ordinary<1/1.3)),
            "peer_match_limits":MATCH}
    def count(group):
        vs=[x["valuation"] for x in group]
        return {"n":len(vs),"price":sum(v["close"] is not None for v in vs),"share_verified":sum(v["share_verified"] for v in vs),
                "historical":sum(v["historical"] is not None for v in vs),"peer":sum(v["peer"] is not None for v in vs),
                "either":sum(v["historical"] is not None or v["peer"] is not None for v in vs),
                "both":sum(v["historical"] is not None and v["peer"] is not None for v in vs),
                "industry_context":sum(v["industry_context"] is not None for v in vs),"earnings_basis_warning":sum(v["earnings_basis_warning"] for v in vs)}
    return {"all":count(rows),"unique_presets":count([x for x in rows if any(passes(x,p["limits"]) for p in PRESETS)]),
            "presets":{p["id"]:count([x for x in rows if passes(x,p["limits"])]) for p in PRESETS}}
