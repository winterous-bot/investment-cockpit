"""C R1: independent horizon-specific price evidence, no changes to A/B/C baseline.
All levels use the analysis-date adjustment anchor. Research, not executable orders.
"""
from .model_c import (atr_series,completed_bars,contiguous_tail,pivot_events,
    breakout_events,role_reversal_events,independent_dates,EPS,location_c,conditional_plan)
from .model_a import pos,finite,cycle
from .indicators import indicators,period,risk_features
from .quality import QualityHistory,WARMUP

VERSION="technical-model-v1.0-C-R1"
# Predeclared engineering hypotheses; no fit to the nine acceptance examples.
MAX_DISTANCE_ATR={"short":3.0,"medium":3.0}
AGE={"day":60,"week":120,"month":252}
HORIZON_FREQ={"short":("day",),"medium":("day","week")}

def collect(q,asof,sessions):
    if not isinstance(q,QualityHistory):raise TypeError("audited history required")
    if list(sessions)!=sorted(set(sessions)) or asof not in sessions:raise ValueError("invalid calendar")
    v=q.view(asof,sessions);daily=v["groups"]["day"]["bars"];major=bool(v["last_major"])
    ev=[];breaks=[];dyn=[];scales={};counts={};last_week=None
    for f in ("day","week","month"):
        full=[b for b in v["groups"][f]["bars"] if f=="day" or b["complete"]]
        tail=contiguous_tail(completed_bars(v,f,sessions),f,sessions,asof)
        counts[f]=len(tail)
        if not tail:continue
        ix={b["date"]:i for i,b in enumerate(full)};av=atr_series(full);offset=ix[tail[0]["date"]]
        vals=[av[ix[b["date"]]] for b in tail]
        ready=not major or ix[tail[-1]["date"]]+1>=WARMUP
        scales[f]=vals[-1] if ready else None
        if f=="week":last_week=tail[-1]["date"]
        if not ready:continue
        for e in pivot_events(tail,f,major,vals,offset):
            if f!="day":
                key="low" if e["side"]=="support" else "high"
                hits=[b["date"] for b in daily if period(b["date"],f)==period(e["formation"],f) and abs(b[key]-e["price"])<=EPS*max(1,e["price"])]
                if not hits:continue
                e={**e,"period_end":e["formation"],"formation":hits[0]}
            ev.append({**e,"kind":"rejection"})
        if f=="day":
            ev.extend({**e,"kind":"rejection"} for e in role_reversal_events(tail,f,major,vals,offset))
        bs=breakout_events(tail,f,major,vals,offset);breaks.extend(bs)
        for e in bs:
            if e["state"] in ("confirmed","retest"):
                ev.append({"price":e["level"],"side":"support" if e["direction"]=="up" else "resistance",
                           "frequency":f,"formation":e["formation_date"],"confirmed":e["confirmation_date"],"kind":"confirmed_break"})
        # Prior extremes are B obstacles, not proof of a durable support or target.
        # Include current bar in observed extrema to retain newly established levels.
        for n in (20,60) if f!="month" else (20,):
            if len(tail)<n:continue
            for side,key,choose in (("support","low",min),("resistance","high",max)):
                x=choose(tail[-n:],key=lambda b:b[key])
                ev.append({"price":x[key],"side":side,"frequency":f,"formation":x["date"],"confirmed":x["date"],"kind":"range_extreme","lookback":n})
        ind=indicators(full[:ix[tail[-1]["date"]]+1],f)
        for k in (("ma20","ma60","ma250","boll_upper","boll_lower") if f=="day" else ("ma20","boll_upper","boll_lower")):
            if pos(ind.get(k)):dyn.append({"price":ind[k],"frequency":f,"date":tail[-1]["date"],"kind":k,"grade":"C"})
    week_trend=cycle(q.view(last_week,sessions),"week")["trend"] if last_week else "unknown"
    return v,ev,breaks,dyn,scales,counts,last_week,week_trend

def zones_for(events,daily,scale,sessions,freqs):
    """Same-side clustering; validate each evidence episode before grading.
    A=two distinct surviving rejection dates, B=one rejection/break/extreme.
    Non-rejection B can constrain a target but cannot anchor a stop.
    """
    result={"support":[],"resistance":[],"rejected":[],"at_price":[]}
    if not daily or not pos(scale):return result
    c=daily[-1]["close"];ix={d:i for i,d in enumerate(sessions)};now=ix[daily[-1]["date"]]
    usable=[]
    for e in events:
        if e["frequency"] not in freqs or not pos(e["price"]):continue
        d=e["confirmed"];p=e["price"];side=e["side"]
        if d not in ix or e["formation"] not in ix or not ix[e["formation"]]<=ix[d]<=now:continue
        if now-ix[d]>AGE[e["frequency"]]:continue
        after=[b for b in daily if b["date"]>d]
        bad=lambda b: b["close"]<p-.25*scale-EPS if side=="support" else b["close"]>p+.25*scale+EPS
        if any(bad(a) and bad(b) and ix.get(b["date"],-999)-ix.get(a["date"],-1000)==1 for a,b in zip(after,after[1:])):
            result["rejected"].append({"price":p,"side":side,"reason":"invalidated","kind":e["kind"],"confirmed":d});continue
        if (side=="support" and p>c+EPS) or (side=="resistance" and p<c-EPS):continue
        usable.append(e)
    for side in ("support","resistance"):
        clusters=[]
        for e in sorted((e for e in usable if e["side"]==side),key=lambda x:(x["price"],x["confirmed"],x["kind"])):
            p=e["price"]
            if clusters and p-clusters[-1]["low"]<=.5*scale+EPS:
                clusters[-1]["high"]=p;clusters[-1]["evidence"].append(e)
            else:clusters.append({"low":p,"high":p,"evidence":[e]})
        for z in clusters:
            reactions=[e for e in z["evidence"] if e["kind"]=="rejection"]
            touches=independent_dates(reactions,ix)
            # Stop may only use observed rejection bounds, never an untested extreme.
            anchor=min(e["price"] for e in reactions) if reactions else None
            z.update(grade="A" if len(touches)>=2 else "B",touches=len(touches),touch_dates=touches,
                stop_anchor=anchor,last_confirmation=max(e["confirmed"] for e in z["evidence"]),
                frequencies=sorted({e["frequency"] for e in z["evidence"]}),kinds=sorted({e["kind"] for e in z["evidence"]}))
            if z["low"]-EPS<=c<=z["high"]+EPS:result["at_price"].append({**z,"side":side})
            else:result[side].append(z)
    result["support"].sort(key=lambda z:z["high"],reverse=True);result["resistance"].sort(key=lambda z:z["low"])
    return result

def horizon_location(h,c,scale,daily_atr,z,dyn,extension):
    cap=MAX_DISTANCE_ATR[h]*scale if pos(scale) else None
    if not pos(c) or not pos(scale) or not pos(daily_atr):
        return {"state":"unknown","risk_veto":True,"reason":"missing_horizon_scale","reward_risk":None}
    near_s=[x for x in z["support"] if c-x["high"]<=cap+EPS]
    near_r=[x for x in z["resistance"] if x["low"]-c<=cap+EPS]
    # Keep nearest B resistance even when a far A exists. Never skip obstacle.
    s=next((x for x in near_s if pos(x["stop_anchor"])),None);r=near_r[0] if near_r else None
    stop=s["stop_anchor"]-.5*scale if s else None
    if not pos(stop) or c-stop>cap+EPS:stop=None
    target=r["low"] if r else None
    # Current price inside/on a resistance zone is unresolved, not an entry target.
    overlap=any(x["side"]=="resistance" for x in z["at_price"])
    if overlap:target=None
    rr=(target-c)/(c-stop) if target is not None and stop is not None else None
    risk=(c-stop)/c if stop is not None else None
    flags={"extension":extension,"distance_risk":risk>=.08-EPS if risk is not None else None,
           "high_volatility":daily_atr/c>=.05-EPS,"unfavorable_rr":rr<2-EPS if rr is not None else None,
           "missing_level":stop is None or target is None,"unresolved_obstacle":overlap}
    return {"state":"caution" if any(x is not False for x in flags.values()) else "ready","risk_veto":any(x is not False for x in flags.values()),
            "price":c,"atr14":scale,"atr_frequency":"day" if h=="short" else "week","daily_atr14":daily_atr,"distance_cap":cap,
            "support":s,"resistance":r,"nearest_support_obstacle":near_s[0] if near_s else None,
            "invalidation":stop,"target_reference":target,"reward_risk":rr,"risk_fraction":risk,"flags":flags,
            "remote_support": [x for x in z["support"] if x not in near_s],
            "remote_resistance":[x for x in z["resistance"] if x not in near_r],
            "dynamic_references":dyn,"at_price":z["at_price"],"zones":z,
            "target_status":"unresolved_at_price" if overlap else "within_horizon" if target is not None else "remote_only" if z["resistance"] else "no_structural_resistance"}

def trend_tracking(report,loc,daily):
    """A separate watch-only research path; not an alternate entry permission."""
    if not report.get("composite_ready") or loc.get("target_status") not in ("remote_only","no_structural_resistance") or not daily:return None
    w=report["cycles"]["week"];m=report["cycles"]["month"]
    d=report["horizons"]["medium"]["D"]
    if w.get("trend")!="bullish" or loc.get("completed_week_trend")!="bullish" or m.get("trend") in ("bearish","unknown",None) or not finite(d) or d<50:return None
    if len(daily)<21:return None
    low=min(x["low"] for x in daily[-21:-1]);high=max(x["high"] for x in daily[-21:-1])
    if not pos(loc.get("daily_atr14")):return None
    trail=low-.5*loc["daily_atr14"]
    return {"state":"research_watch_only","target":None,"reward_risk":None,"breakout_reference":high,
            "dynamic_invalidation_reference":trail if 0<trail<daily[-1]["close"] else None,
            "conditions":["confirmed_breakout_or_retest","daily_trailing_reference_recalculated_after_close","risk_budget_and_market_gate_required","exit_rule_not_backtested"],
            "new_exposure_allowed":False}

def analyze_r1(q,report,sessions,holding=None,portfolio_permission=None):
    if q.code!=report.get("code"):raise ValueError("symbol mismatch")
    asof=report["asof"];v,e,br,dyn,scales,counts,wdate,wtrend=collect(q,asof,sessions)
    daily=v["groups"]["day"]["bars"];c=daily[-1]["close"] if daily else None;da=scales.get("day")
    ind=v["groups"]["day"]["indicators"];m=ind.get("ma20");rsi=ind.get("rsi6")
    ext=(c-m)/da>=2-EPS if pos(c) and pos(m) and pos(da) else None;ob=rsi>=80 if finite(rsi) else None
    extension=True if ext is True or ob is True else False if ext is False and ob is False else None
    locs={}
    for h,fs in HORIZON_FREQ.items():
        scale=da if h=="short" else scales.get("week")
        z=zones_for(e,daily,scale,sessions,fs)
        loc=horizon_location(h,c,scale,da,z,[x for x in dyn if x["frequency"] in fs],extension)
        loc.update(completed_week_trend=wtrend,completed_week_date=wdate,breakouts=[x for x in br if x["frequency"] in fs])
        locs[h]=loc
    # No mix of short stop and medium target. Existing plan only accepts short
    # location, and medium context remains advisory until D validates policy.
    plan=conditional_plan(report,locs["short"],holding,portfolio_permission)
    if locs["short"].get("risk_veto") is not False:assert plan["new_exposure"]!="conditional_opportunity"
    tracking=trend_tracking(report,locs["short"],daily)
    # Monthly levels are background only, never an input into either RR.
    bg=zones_for(e,daily,scales.get("month"),sessions,("month",))
    return {"version":VERSION,"code":q.code,"asof":asof,"locations":locs,"monthly_background":bg,
            "monthly_dynamic":[x for x in dyn if x["frequency"]=="month"],"trend_tracking":tracking,"plan":plan,
            "coverage":counts,"direction_scores":report["horizons"],"probability":None}
