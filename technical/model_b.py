"""V1.0-B market/industry context; no new votes, no trade actions."""
from statistics import fmean
from math import ceil
from .indicators import number,date
from .model_a import INDEX_WEIGHTS,finite,pos,analyze,relative_component
from .quality import QualityHistory
VERSION="technical-model-v1.0-B"
TAXONOMY="SW2021"
# Only use SW2021 from its implementation date; earlier regimes require another version.
SW_START="20211213"
def half(x):return round(x*2)/2
def window(rows,sessions,asof,n):
    required=[d for d in sessions if d<=asof][-n:]
    if len(required)!=n or required[-1]!=asof or not rows or rows[-1]["date"]!=asof or [b["date"] for b in rows[-n:]]!=required:return None
    return rows[-n:]
def index_trend(rows,sessions,asof):
    w=window(rows,sessions,asof,260)
    if not w or not all(pos(b.get("close")) for b in w):return {"score":None,"state":"unknown","asof":None}
    c=[b["close"] for b in w];p=c[-1];m20=fmean(c[-20:]);m60=fmean(c[-60:]);m250=fmean(c[-250:]);old=fmean(c[-25:-5])
    votes={"above_ma20":p>=m20,"above_ma60":p>=m60,"above_ma250":p>=m250,"ma20_rising":m20>old,"return20_positive":p>c[-21]}
    s=sum(votes.values())
    return {"score":s,"state":band(s),"asof":asof,"votes":votes}
def band(s):return "unknown" if s is None else "weak" if s<=1.5 else "strong" if s>=3.5 else "mixed"
def market_trend(indices,sessions,asof):
    vals={k:index_trend(indices.get(k),sessions,asof) for k in INDEX_WEIGHTS}
    valid={k:v for k,v in vals.items() if v["score"] is not None}
    cov=sum(INDEX_WEIGHTS[k] for k in valid)
    s=half(sum(INDEX_WEIGHTS[k]*v["score"] for k,v in valid.items())/cov) if len(valid)>=3 and cov>=.75-1e-12 else None
    return {"score":s,"coverage":round(cov*100,3),"state":band(s),"asof":asof if s is not None else None,"indices":vals}
def point_membership(rows,code,asof,taxonomy):
    if asof<SW_START:return {"state":"unavailable","reason":"pre_SW2021"}
    matches=set()
    try:
        for r in rows:
            if r.get("ts_code")!=code:raise ValueError("wrong_stock")
            start=date(str(r["in_date"]));end=date(str(r["out_date"])) if r.get("out_date") not in (None,"") else None
            if end and end<=start:raise ValueError("invalid_interval")
            if start<=asof and (end is None or asof<end):
                k=str(r["l1_code"]).split(".")[0]+".SI"
                if k not in taxonomy:raise ValueError("outside_SW2021")
                matches.add((k,start,end))
        # Same L1 with overlapping subindustry records is okay only when interval evidence agrees;
        # conservative: reject ambiguous differing intervals rather than assume continuous tenure.
        if len(matches)!=1:return {"state":"unavailable","reason":"no_or_ambiguous_membership","matches":len(matches)}
        k,start,end=next(iter(matches))
        return {"state":"matched","code":k,"name":taxonomy[k],"in_date":start,"out_date":end,"taxonomy":TAXONOMY,"asof":asof}
    except (ValueError,KeyError,TypeError):return {"state":"unavailable","reason":"invalid_membership"}
def industry_context(q,asof,sessions,indices,taxonomy,membership,sector_rows):
    m=point_membership(membership,q.code,asof,taxonomy)
    out={"membership":m,"trend":{"score":None,"state":"unknown"},"industry_vs_market":{"R":None},"stock_vs_industry":{},"ready":False}
    if m["state"]!="matched":return out
    b=sector_rows.get(m["code"])
    out["trend"]=index_trend(b,sessions,asof)
    rs=relative_component(b or [],indices,sessions,asof,(20,))
    v=rs.get("values",{}).get("20")
    out["industry_vs_market"]={**rs,"relative_state":"unknown" if v is None else "outperforming" if v>2 else "underperforming" if v< -2 else "neutral"}
    stock=q.view(asof,sessions)["groups"]["day"]["bars"]
    for n in (5,20,60):
        a=window(stock,sessions,asof,n+1);z=window(b,sessions,asof,n+1)
        # Do not compare against today's sector across a change of membership.
        out["stock_vs_industry"][str(n)]=100*((a[-1]["close"]/a[0]["close"])/(z[-1]["close"]/z[0]["close"])-1) if a and z and m["in_date"]<=a[0]["date"] and all(pos(x["close"]) for x in a+z) else None
    out["ready"]=out["trend"]["score"] is not None and v is not None and all(finite(x) for x in out["stock_vs_industry"].values())
    return out
def sector_breadth(sectors,sessions,asof):
    a=[];p=[]
    for rows in sectors.values():
        w=window(rows,sessions,asof,60)
        if w and all(pos(x["close"]) for x in w):
            c=[b["close"] for b in w];a.append(c[-1]>fmean(c));p.append(c[-1]>c[-21])
    n=len(a);total=len(sectors);cov=100*n/total if total else 0
    s=half(5*(.65*fmean(a)+.35*fmean(p))) if total==31 and n>=27 else None
    return {"id":"industry_trend","weight":.35,"score":s,"coverage":cov if s is not None else 0,"asof":asof if s is not None else None,"sample":n,"expected":total,"above_ma60":fmean(a) if n else None,"positive20":fmean(p) if n else None}
def eligible_at(universe,d):
    return {k for k,(start,end) in universe.items() if start<=d and (end is None or d<end)}
def stock_breadth(universe,prices,factors,sessions,asof):
    ds=[d for d in sessions if d<=asof][-80:]
    def point(w):
        if len(w)!=60:return (0,0,0,None)
        d=w[-1];eligible=eligible_at(universe,d); # new IPOs excluded from 60d denominator
        seasoned={k for k in eligible if universe[k][0]<=w[0]}
        if not seasoned:return (0,0,0,None)
        # require sufficient source coverage at each session, independently of suspension exclusions.
        for t in w:
            u=eligible_at(universe,t)
            if not u or len(set(prices.get(t,{}))&u)/len(u)<.85 or len(set(factors.get(t,{}))&u)/len(u)<.85:return (0,len(seasoned),0,None)
        valid=above=0
        for k in seasoned:
            xs=[]
            for t in w:
                p=prices[t].get(k);f=factors[t].get(k)
                if not pos(p) or not pos(f):break
                xs.append(p*f)
            if len(xs)==60:
                valid+=1;above+=int(xs[-1]>fmean(xs))
        return valid,len(seasoned),above,above/valid if valid else None
    a,b=point(ds[-60:]),point(ds[:60] if len(ds)==80 else [])
    cov=min(100*a[0]/a[1] if a[1] else 0,100*b[0]/b[1] if b[1] else 0)
    ok=a[0]>=2800 and b[0]>=2800 and cov>=75 and a[3] is not None and b[3] is not None
    s=half(5*(.7*a[3]+.3*max(0,min(1,.5+2*(a[3]-b[3]))))) if ok else None
    return {"id":"stock_trend","weight":.4,"score":s,"coverage":cov if ok else 0,"asof":asof if ok else None,"sample":a[0],"expected":a[1],"past_sample":b[0],"past_expected":b[1],"above_ma60":a[3],"change20":a[3]-b[3] if a[3] is not None and b[3] is not None else None}
def participation(universe,changes,sessions,asof):
    ds=[d for d in sessions if d<=asof][-5:];ratios=[];cov=[];counts=[]
    for d in ds:
        u=eligible_at(universe,d);x={k:v for k,v in changes.get(d,{}).items() if k in u and finite(v)}
        if not u or len(x)<2800 or len(x)/len(u)<.85:break
        ratios.append(sum(v>0 for v in x.values())/len(x));cov.append(100*len(x)/len(u));counts.append(len(x))
    ok=len(ratios)==5
    return {"id":"participation","weight":.25,"score":half(5*fmean(ratios)) if ok else None,"coverage":min(cov) if ok else 0,"asof":asof if ok else None,"sample":min(counts) if ok else 0,"avg_rising_ratio":fmean(ratios) if ok else None}
def combine_breadth(parts,asof):
    valid=[p for p in parts if p.get("asof")==asof and finite(p.get("score")) and finite(p.get("coverage")) and 0<=p["coverage"]<=100]
    c=sum(p["weight"]*p["coverage"]/100 for p in valid)
    s=half(sum(p["weight"]*p["coverage"]/100*p["score"] for p in valid)/c) if c>=.8-1e-12 else None
    return {"score":s,"coverage":round(c*100,3),"asof":asof if s is not None else None,"state":band(s),"components":parts}
def activity(sh,sz,sessions,asof):
    a=window(sh,sessions,asof,65);b=window(sz,sessions,asof,65)
    if not a or not b or not all(pos(x.get("amount")) for x in a+b):return {"score":None,"coverage":0,"asof":None,"state":"unknown"}
    v=[(x["amount"]+y["amount"])*1000 for x,y in zip(a,b)]
    ratio=fmean(v[-20:])/fmean(v[-40:-20]);rank=sum(x<=v[-1] for x in v[-60:])/60
    s=half(5*(.55*rank+.45*max(0,min(1,(ratio-.7)/.6))))
    return {"score":s,"coverage":100,"asof":asof,"state":band(s),"turnover_yuan":v[-1],"ratio20":ratio,"percentile60":rank,"semantics":"activity_not_net_inflow"}
def context_gate(market,breadth,liquidity,industry,asof,severe_risk=None):
    # User-confirmed severe risk cannot be overridden by any market score.
    fresh=lambda x: x.get("asof")==asof and finite(x.get("score"))
    mt=fresh(market) and market.get("coverage",0)>=75
    br=fresh(breadth) and breadth.get("coverage",0)>=80
    li=fresh(liquidity) and liquidity.get("coverage",0)>=80
    ind=industry.get("ready") is True and industry.get("membership",{}).get("asof")==asof and industry.get("trend",{}).get("asof")==asof
    defensive=severe_risk is True or (mt and br and market["score"]<=1.5 and breadth["score"]<=1.5)
    return {"state":"defensive" if defensive else "context_ready" if mt and br and li and ind else "incomplete",
            "block_new_exposure":True if defensive else None if not(mt and br and li and ind) or severe_risk is None else False,
            "market_ready":bool(mt),"breadth_ready":bool(br),"liquidity_ready":bool(li),"industry_ready":bool(ind),"user_risk_verified":severe_risk is not None}
def attach(report,market,breadth,liquidity,industry,severe_risk=None):
    g=context_gate(market,breadth,liquidity,industry,report["asof"],severe_risk)
    return {**report,"context_version":VERSION,"market_industry_context":g,"market":{"trend":market,"breadth":breadth,"activity":liquidity},"industry":industry,
            "action":"evidence_insufficient_features" if not report["composite_ready"] else "defensive_no_new_exposure" if g["state"]=="defensive" else "pending_V1.0-C" if g["state"]=="context_ready" else "evidence_insufficient_context","probability":None}
