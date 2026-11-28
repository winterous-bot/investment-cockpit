"""V1.0-A: proposed deterministic six-dimension research engine, no forecasts.
Only consumes the frozen QualityHistory. Market/industry and final action plans
remain separate, pending V1.0-B/C. Never mutate raw bars or risk budgets.
"""
from math import isfinite
from statistics import fmean
from .indicators import indicators, risk_features, relative_strength, period, date
from .quality import QualityHistory, WARMUP, public_summary

VERSION="technical-model-v1.0-A"
FREQS=("day","week","month")
WEIGHTS={"short":(.65,.25,.10),"medium":(.25,.50,.25)}
INDEX_WEIGHTS={"000300.SH":.30,"000905.SH":.25,"000852.SH":.25,"932000.CSI":.20}
def finite(v):
    return isinstance(v,(int,float)) and not isinstance(v,bool) and isfinite(v)
def pos(v):return finite(v) and v>0
def vote(x,t):
    if not finite(x):return None
    # Explicit numerical tolerance prevents binary float boundary drift.
    return 1 if x>t+1e-12 else -1 if x< -t-1e-12 else 0
def weighted(vs,ws):
    if len(vs)!=len(ws) or any(not finite(v) for v in vs):return None
    return round(sum(v*w for v,w in zip(vs,ws)),10)
def trend_score(cur,old_ma20):
    c,a,b,m=(cur.get(k) for k in ("close","ma5","ma10","ma20"))
    if not all(pos(x) for x in (c,a,b,m,old_ma20)):return None
    return weighted([100*vote(c/m-1,.0025),100*vote(a/b-1,.0025),
                     100*vote(b/m-1,.0025),100*vote(m/old_ma20-1,.005)],(.30,.20,.25,.25))
def momentum_score(cur,prev_macd):
    c,macd,rsi=(cur.get(k) for k in ("close","macd","rsi12"))
    if not pos(c) or not all(finite(x) for x in (macd,prev_macd,rsi)) or not 0<=rsi<=100:return None
    return weighted([100*vote(macd/c,.001),100*vote((macd-prev_macd)/c,.0005),
                     100*(1 if rsi>55 else -1 if rsi<45 else 0)],(.40,.35,.25))
def trend_state(t):
    if t is None:return "unknown"
    return "bullish" if t>=50 else "bearish" if t<=-50 else "range"
def direction_state(d):
    if d is None:return "unknown"
    if d>=50:return "strong_positive"
    if d>=20:return "positive"
    if d<=-50:return "strong_negative"
    if d<=-20:return "negative"
    return "mixed"

def cycle(view,freq):
    g=view["groups"][freq];bs=g["bars"];cur=g["indicators"]
    result={"date":bs[-1]["date"] if bs else None,
            "provisional":bool(bs and freq!="day" and not bs[-1]["complete"]),
            "latest_completed_date":next((x["date"] for x in reversed(bs) if freq=="day" or x["complete"]),None),
            "feature_ready":g["feature_ready"],"T":None,"M":None,"trend":"unknown",
            "strong":False,"ma20_slope5":None,"rsi6":cur.get("rsi6"),"rsi24":cur.get("rsi24")}
    # Sliced clean bars use the SAME adjustment anchor as current data.
    # Recursion guard for the previous bar must also be satisfied.
    if len(bs)>=25:
        old=indicators(bs[:-5],freq).get("ma20")
        if pos(old) and pos(cur.get("ma20")):
            result["ma20_slope5"]=cur["ma20"]/old-1
            result["T"]=trend_score(cur,old)
    if len(bs)>=36:
        prior=bs[:-1]
        n=len(prior) if freq=="day" else sum(bool(b["complete"]) for b in prior)
        if not view["last_major"] or n>=WARMUP:
            result["M"]=momentum_score(cur,indicators(prior,freq).get("macd"))
    result["trend"]=trend_state(result["T"])
    result["strong"]=result["T"] is not None and abs(result["T"])>=75
    return result

def volume_component(view,freq):
    bs=view["groups"][freq]["bars"]
    if len(bs)<21 or (freq!="day" and not bs[-1]["complete"]):
        return {"V":None,"reason":"insufficient_completed_bars"}
    if view["last_major"] and len(bs)<WARMUP:return {"V":None,"reason":"recursive_warmup"}
    prior=fmean(b["vol"] for b in bs[-21:-1]);atr=risk_features(bs)["atr14"]
    if not pos(prior) or not pos(atr):return {"V":None,"reason":"invalid_volume_or_atr"}
    delta=bs[-1]["close"]-bs[-2]["close"];vr=bs[-1]["vol"]/prior
    v=100*(1 if delta>0 else -1 if delta<0 else 0) if vr>=1.5-1e-12 and abs(delta)>=.5*atr-1e-12 else 0
    state="high_volume_up" if v>0 else "high_volume_down" if v<0 else "low_volume" if vr<=.75+1e-12 else "other"
    return {"V":v,"ratio":vr,"atr14":atr,"price_change":delta,"state":state,"date":bs[-1]["date"]}

def relative_component(bars,indexes,sessions,asof,horizons):
    # Both horizons use one fixed set of current benchmarks with full aligned windows.
    nmax=max(horizons)
    required=[d for d in sessions if d<=asof][-(nmax+1):]
    if len(required)!=nmax+1 or required[-1]!=asof or [b["date"] for b in bars[-(nmax+1):]]!=required:
        return {"R":None,"coverage":0,"reason":"stock_calendar_window_incomplete","values":{}}
    valid={}
    for code,w in INDEX_WEIGHTS.items():
        b=indexes.get(code)
        if not b or b[-1]["date"]!=asof or [x["date"] for x in b[-(nmax+1):]]!=required:continue
        values=[relative_strength(bars,b,n) for n in horizons]
        if all(finite(x) for x in values):valid[code]=(w,values)
    coverage=sum(w for w,_ in valid.values())
    if len(valid)<3 or coverage<.75-1e-12:return {"R":None,"coverage":coverage,"reason":"benchmark_coverage","values":{},"indices":sorted(valid)}
    values={str(n):sum(w*vs[i] for w,vs in valid.values())/coverage for i,n in enumerate(horizons)}
    thresholds={5:1,20:2,60:3}
    r=fmean(100*vote(values[str(n)],thresholds[n]) for n in horizons)
    return {"R":r,"coverage":round(coverage,4),"values":values,"indices":sorted(valid)}

def alignment(cycles):
    d,w,m=(cycles[f]["trend"] for f in FREQS)
    if "unknown" in (d,w,m):return "unknown"
    if d==w==m=="bullish":return "bullish_alignment"
    if d==w==m=="bearish":return "bearish_alignment"
    if d=="bullish" and w=="bearish":return "rebound_in_downtrend"
    if d=="bearish" and w=="bullish":return "pullback_in_uptrend"
    return "mixed"

def medium_state(cycles):
    w,m=(cycles[f]["trend"] for f in ("week","month"))
    if "unknown" in (w,m):return "unknown"
    if w=="bullish" and m!="bearish":return "bullish"
    if w=="bearish" and m!="bullish":return "bearish"
    return "conflicting_or_range"

def _completed_week_views(q,view,sessions,limit=3):
    # Completed week is accepted only if its close matches the last exchange
    # session in its period. No suspended close treated as completed signal.
    out=[]
    calendar_ends={}
    for d in sessions:calendar_ends[period(d,"week")]=d
    observed={b["date"] for b in view["groups"]["week"]["bars"] if b["complete"]}
    expected=sorted(d for d in calendar_ends.values() if d<=view["asof"])[-limit:]
    for d in reversed(expected):
        if d not in observed:break
        out.append(q.view(d,sessions))
    return out

def _qualifies(view,sign):
    s=cycle(view,"week");ind=view["groups"]["week"]["indicators"]
    c,m,h=(ind.get(k) for k in ("close","ma20","macd"))
    if s["T"] is None or not all(finite(x) for x in (c,m,h,s["ma20_slope5"])):return False
    return sign*s["T"]>=50 and sign*(c-m)>0 and sign*s["ma20_slope5"]>0 and sign*h>0

def reversal(q,view,sessions,completed=None):
    vs=_completed_week_views(q,view,sessions) if completed is None else completed
    dates=[v["asof"] for v in vs]
    states=[cycle(v,"week")["trend"] for v in vs]
    for sign,opposite,label in [(1,"bearish","bullish"),(-1,"bullish","bearish")]:
        if len(vs)>=3 and states[2]==opposite and _qualifies(vs[1],sign) and _qualifies(vs[0],sign):
            return {"state":label+"_confirmed","date":dates[0],"completed_dates":dates}
        if len(vs)>=2 and states[1]==opposite and _qualifies(vs[0],sign):
            return {"state":label+"_candidate","date":dates[0],"completed_dates":dates}
        if cycle(view,"week")["provisional"] and vs and states[0]==opposite and _qualifies(view,sign):
            return {"state":label+"_provisional_candidate","date":view["asof"],"completed_dates":dates}
    return {"state":"none" if len(vs)>=3 else "unknown","completed_dates":dates}

def cluster_levels(levels,atr):
    if not pos(atr):return []
    out=[]
    for price,source in sorted(levels):
        if not pos(price):continue
        if out and price-out[-1]["low"]<=.5*atr+1e-12:
            out[-1]["high"]=price;out[-1]["sources"].append(source)
        else:out.append({"low":price,"high":price,"sources":[source]})
    return out

def location(view):
    # Preliminary price/risk primitives. Full breakout/retest/action layer is C.
    g=view["groups"]["day"];bs=g["bars"];cur=g["indicators"]
    c=cur.get("close");atr=risk_features(bs)["atr14"] if bs and (not view["last_major"] or len(bs)>=WARMUP) else None
    if not pos(c) or not pos(atr):return {"state":"unknown","risk_veto":None,"reason":"price_or_atr_missing"}
    levels=[]
    for f in FREQS:
        x=view["groups"][f]
        keys=("ma20","ma60","ma250") if f=="day" else ("ma20",)
        for k in keys:
            v=x["indicators"].get(k)
            if pos(v):levels.append((v,f+"."+k))
        keys=("prior_high20","prior_low20","prior_high60","prior_low60") if f=="day" else ("prior_high20","prior_low20")
        for k in keys:
            v=x["signals"].get(k)
            if pos(v):levels.append((v,f+"."+k))
    lower=cluster_levels([(v,k) for v,k in levels if v<c],atr)
    upper=cluster_levels([(v,k) for v,k in levels if v>c],atr)
    support=lower[-1] if lower else None;resistance=upper[0] if upper else None
    stop=support["low"]-.5*atr if support else None
    if not pos(stop):stop=None
    target=resistance["low"] if resistance else None
    rr=(target-c)/(c-stop) if stop is not None and target is not None else None
    risk=(c-stop)/c if stop is not None else None
    rsi=cur.get("rsi6");ma=cur.get("ma20")
    extension=(c-ma)/atr>=2-1e-12 if pos(ma) else None
    overbought=rsi>=80 if finite(rsi) else None
    extended=True if extension is True or overbought is True else False if extension is False and overbought is False else None
    flags={"extension":extended,"distance_risk":risk>=.08-1e-12 if risk is not None else None,"high_volatility":atr/c>=.05-1e-12,
           "unfavorable_rr":rr<2-1e-12 if rr is not None else None,"missing_level":stop is None or target is None}
    veto=any(x is True for x in flags.values()) or any(x is None for x in flags.values())
    return {"state":"caution" if veto else "research_location_ok","risk_veto":veto,"price":c,"atr14":atr,"support":support,
            "resistance":resistance,"invalidation":stop,"target_reference":target,"reward_risk":rr,"risk_fraction":risk,"flags":flags}

def analyze(q,asof,sessions,indexes):
    if not isinstance(q,QualityHistory):raise TypeError("audited history required")
    asof=date(asof)
    if list(sessions)!=sorted(set(sessions)) or asof not in sessions:raise ValueError("invalid exchange sessions")
    v=q.view(asof,sessions);cy={f:cycle(v,f) for f in FREQS}
    weeks=_completed_week_views(q,v,sessions)
    volumes={"short":volume_component(v,"day"),"medium":volume_component(weeks[0],"week") if weeks else {"V":None,"reason":"completed_week_unavailable"}}
    # Stale/future benchmark input is rejected rather than automatically sliced.
    rs={h:relative_component(v["groups"]["day"]["bars"],indexes,sessions,asof,ns) for h,ns in (("short",(5,20)),("medium",(20,60)))}
    hs={}
    for h,w in WEIGHTS.items():
        t=weighted([cy[f]["T"] for f in FREQS],w);m=weighted([cy[f]["M"] for f in FREQS],w)
        d=weighted([t,m,volumes[h]["V"],rs[h]["R"]],(.55,.20,.10,.15)) if v["combined_feature_ready"] else None
        hs[h]={"T":t if v["combined_feature_ready"] else None,"M":m if v["combined_feature_ready"] else None,
               "V":volumes[h],"R":rs[h],"D":d,"direction":direction_state(d)}
    ready=all(x["D"] is not None for x in hs.values())
    return {"version":VERSION,"code":q.code,"asof":asof,"quality":public_summary(v),"cycles":cy,"horizons":hs,
            "alignment":alignment(cy),"medium_structure":medium_state(cy),"weekly_reversal":reversal(q,v,sessions,weeks),
            "location":location(v),"composite_ready":ready,"market_industry_context":"pending_V1.0-B",
            "action":"evidence_insufficient_context" if ready else "evidence_insufficient_features","probability":None}
