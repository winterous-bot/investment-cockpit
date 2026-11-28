"""V1.0-C causal price evidence and conditional plan; research only.
Consumes guarded foundation and A/B reports. No changes to A/B scores or policies.
"""
from statistics import fmean
from .indicators import risk_features,indicators,period,wilder
from .model_a import pos,finite,cycle
from .quality import QualityHistory,WARMUP
VERSION="technical-model-v1.0-C"
LOOKBACK={"day":120,"week":52,"month":24}
EPS=1e-10

def atr_series(bs):
    if not bs:return []
    tr=[bs[0]["high"]-bs[0]["low"]]+[max(b["high"]-b["low"],abs(b["high"]-a["close"]),abs(b["low"]-a["close"])) for a,b in zip(bs,bs[1:])]
    return [v if i>=14 else None for i,v in enumerate(wilder(tr,14))]

def completed_bars(view,freq,sessions):
    bs=view["groups"][freq]["bars"]
    if freq=="day":return bs
    # Require actual close on final exchange session AND full observed period.
    # Only use periods inside verified calendar; no partial/suspended bar as confirmation.
    cal={}
    for d in sessions:cal.setdefault(period(d,freq),[]).append(d)
    out=[]
    for b in bs:
        ds=cal.get(period(b["date"],freq),[])
        if b["complete"] and ds and ds[-1]==b["date"] and b["sessions"]==len(ds) and ds[0]>sessions[0]:out.append(b)
    return out

def contiguous_tail(bs,freq,sessions,asof):
    # Never bridge a suspended day or missing completed period.
    if not bs:return []
    if freq=="day":expected=[d for d in sessions if d<=asof]
    else:
        cal={}
        for d in sessions:cal[period(d,freq)]=d
        expected=sorted(d for d in cal.values() if d<=asof)
    out=[]
    for b,d in zip(reversed(bs),reversed(expected)):
        if b["date"]!=d:break
        out.append(b)
    return list(reversed(out))

def pivot_events(bs,freq,major=False,atr_values=None,clean_offset=0):
    """Trailing extrema, followed by *observed* three-bar rejection.
    Formation is never usable before confirmation date. No future bars.
    Thresholds: trailing 5 bars, >=1 formation-period ATR rejection in
    next 3 observed complete bars, no close through level by >0.25 ATR.
    """
    av=atr_series(bs) if atr_values is None else atr_values;out=[];start=max(5,len(bs)-LOOKBACK[freq])
    for i in range(start,len(bs)-3):
        b=bs[i];a=av[i]
        if not pos(a) or (major and clean_offset+i+1<WARMUP):continue
        prior=bs[i-5:i];future=bs[i+1:i+4]
        for side,key,sgn in (("support","low",1),("resistance","high",-1)):
            p=b[key]
            extremum=p<=min(x[key] for x in prior) if sgn==1 else p>=max(x[key] for x in prior)
            if not extremum:continue
            # Rejection must be a closing move away; exclude a broken level.
            if min(sgn*(x["close"]-p) for x in future)<-.25*a-EPS:continue
            strength=max(sgn*(x["close"]-p)/a for x in future)
            if strength<1-EPS:continue
            out.append({"price":p,"side":side,"frequency":freq,"formation":b["date"],"confirmed":future[-1]["date"],"rejection_atr":strength})
    return out

def cluster(events,atr):
    out=[]
    for e in sorted(events,key=lambda x:(x["price"],x["formation"],x["frequency"])):
        p=e["price"]
        if out and p-out[-1]["low"]<=.5*atr+EPS:
            out[-1]["high"]=p;out[-1]["events"].append(e)
        else:out.append({"low":p,"high":p,"events":[e]})
    return out

def independent_dates(events,session_index):
    # Same episode across frequencies is not multiple touches. At least five
    # actual exchange sessions separate touch episodes.
    ds=sorted({e["formation"] for e in events if e["formation"] in session_index})
    kept=[]
    for d in ds:
        if not kept or session_index[d]-session_index[kept[-1]]>=5:kept.append(d)
    return kept

def valid_zones(events,daily,atr,sessions,ma_refs=None):
    if not daily or not pos(atr):return {"support":[],"resistance":[],"rejected":[]}
    close=daily[-1]["close"];ix={d:i for i,d in enumerate(sessions)};out={"support":[],"resistance":[],"rejected":[]}
    for z in cluster(events,atr):
        lo,hi=z["low"],z["high"]
        side="support" if hi<close else "resistance" if lo>close else None
        if not side:
            out["rejected"].append({"low":lo,"high":hi,"reason":"inside_current_zone"});continue
        es=[e for e in z["events"] if e["side"]==side];dates=independent_dates(es,ix)
        if len(dates)<2:
            out["rejected"].append({"low":lo,"high":hi,"reason":"fewer_than_two_independent_rejections"});continue
        # Last confirmed rejection must be <=60/120/252 exchange sessions old
        # for day/week/month evidence respectively. At least one fresh event.
        fresh=[e for e in es if e["confirmed"] in ix and ix[daily[-1]["date"]]-ix[e["confirmed"]]<={"day":60,"week":120,"month":252}[e["frequency"]]]
        if not fresh:
            out["rejected"].append({"low":lo,"high":hi,"reason":"stale_evidence"});continue
        last=max(e["confirmed"] for e in es)
        after=[b for b in daily if b["date"]>last]
        bad=lambda b: b["close"]<lo-.25*atr-EPS if side=="support" else b["close"]>hi+.25*atr+EPS
        if any(bad(a) and bad(b) and ix.get(b["date"],-99)-ix.get(a["date"],-100)==1 for a,b in zip(after,after[1:])):
            out["rejected"].append({"low":lo,"high":hi,"reason":"invalidated_by_two_closes"});continue
        # MA confluence is explanatory only; it cannot create a level.
        ma=[k for k,v in (ma_refs or {}).items() if pos(v) and lo-.25*atr<=v<=hi+.25*atr]
        out[side].append({"low":lo,"high":hi,"touches":len(dates),"touch_dates":dates,"last_confirmation":last,
                          "frequencies":sorted(set(e["frequency"] for e in es)),"max_rejection_atr":max(e["rejection_atr"] for e in es),"ma_confluence":ma,
                          "evidence":es})
    out["support"].sort(key=lambda z:z["high"],reverse=True)
    out["resistance"].sort(key=lambda z:z["low"])
    return out

def breakout_events(bs,freq,major=False,atr_values=None,clean_offset=0):
    """Per-lookback state machine, replayed from guarded contiguous prefix.
    Next observed *exchange-contiguous* bar confirms only if still beyond the
    frozen pre-break level. Retest uses low/high near level, close reclaimed,
    volume <= prior20 mean. Failed breakout: close back through level within
    5 bars of confirmation; later loss is invalidation. Expire after 20 bars.
    All prices share analysis-date adjustment anchor.
    """
    av=atr_series(bs) if atr_values is None else atr_values;out=[]
    for n in (20,60):
        for sign,label in ((1,"up"),(-1,"down")):
            state=None
            for i,b in enumerate(bs):
                if i<max(n,20) or (major and clean_offset+i+1<WARMUP):continue
                a=av[i];prior=fmean(x["vol"] for x in bs[i-20:i])
                if not pos(a) or not pos(prior):continue
                vr=b["vol"]/prior
                if state is not None:
                    age=i-state["i"];lev=state["level"];delta=sign*(b["close"]-lev)
                    if state["state"]=="candidate":
                        state.update(state="confirmed" if age==1 and delta>EPS else "false_breakout",event_date=b["date"])
                        if state["state"]=="confirmed":state["confirmation_date"]=b["date"];state["confirmed_i"]=i
                    elif state["state"] in ("confirmed","retest"):
                        if delta<=EPS:
                            state.update(state="false_breakout" if i-state["confirmed_i"]<=5 else "invalidated",event_date=b["date"])
                        elif age>20:
                            state.update(state="expired",event_date=b["date"])
                        elif state["state"]=="confirmed":
                            edge=b["low"] if sign==1 else b["high"]
                            if abs(edge-lev)<=.5*a+EPS and vr<=1+EPS:
                                state.update(state="retest",event_date=b["date"])
                    if state["state"] in ("candidate","confirmed","retest"):continue
                    # Preserve terminal event at this bar, do not overwrite it with
                    # another candidate until a later close.
                    if state["event_date"]==b["date"]:continue
                lev=max(x["high"] for x in bs[i-n:i]) if sign==1 else min(x["low"] for x in bs[i-n:i])
                if sign*(b["close"]-lev)>EPS and vr>=1.5-EPS:
                    state={"state":"candidate","direction":label,"frequency":freq,"lookback":n,"level":lev,"i":i,"formation_date":b["date"],"event_date":b["date"],"volume_ratio":vr}
            if state:
                out.append({k:v for k,v in state.items() if k not in ("i","confirmed_i")})
    return out

def role_reversal_events(bs,freq,major=False,atr_values=None,clean_offset=0):
    # Replay only the most recent 24 bars for role reversal evidence. A retest
    # is a touch, not an independent rejection until three more closes observed.
    av=atr_series(bs) if atr_values is None else atr_values
    out=[];seen=set()
    for i in range(max(21,len(bs)-27),len(bs)-3):
        a=av[i]
        if not pos(a):continue
        for e in breakout_events(bs[:i+1],freq,major,av[:i+1],clean_offset):
            if e["state"]!="retest" or e["event_date"]!=bs[i]["date"]:continue
            p=e["level"];sgn=1 if e["direction"]=="up" else -1
            future=bs[i+1:i+4];strength=max(sgn*(b["close"]-p)/a for b in future)
            if strength<1-EPS or min(sgn*(b["close"]-p) for b in future)<-.25*a-EPS:continue
            key=(e["event_date"],e["direction"],p)
            if key in seen:continue
            seen.add(key)
            out.append({"price":p,"side":"support" if sgn==1 else "resistance","frequency":freq,
                        "formation":e["event_date"],"confirmed":future[-1]["date"],"rejection_atr":strength,
                        "role_reversal":True,"breakout_date":e["formation_date"]})
    return out

def location_c(q,asof,sessions):
    if not isinstance(q,QualityHistory):raise TypeError("audited history required")
    if list(sessions)!=sorted(set(sessions)) or asof not in sessions:raise ValueError("invalid sessions")
    v=q.view(asof,sessions);daily=v["groups"]["day"]["bars"];major=bool(v["last_major"])
    if not daily or (major and len(daily)<WARMUP):return {"state":"unknown","reason":"quality_warmup","risk_veto":True}
    a=risk_features(daily)["atr14"];c=daily[-1]["close"]
    if not pos(a):return {"state":"unknown","reason":"atr_missing","risk_veto":True}
    all_events=[];breaks=[];coverage={}
    for f in LOOKBACK:
        bs=completed_bars(v,f,sessions)
        tail=contiguous_tail(bs,f,sessions,asof)
        coverage[f]=len(tail)
        # Use the full clean completed series to seed ATR, not the two-year
        # calendar suffix. Candidate/confirmation windows still never cross gaps.
        full=[b for b in v["groups"][f]["bars"] if f=="day" or b["complete"]]
        full_index={b["date"]:i for i,b in enumerate(full)}
        av=atr_series(full)
        offset=full_index[tail[0]["date"]] if tail else 0
        vals=[av[full_index[b["date"]]] for b in tail]
        ev=pivot_events(tail,f,major,vals,offset)
        # A weekly/monthly extreme may have formed on an earlier daily bar;
        # resolve its source date before deduplicating cross-frequency touches.
        for e in ev:
            if f!="day":
                key="low" if e["side"]=="support" else "high"
                hits=[b["date"] for b in daily if period(b["date"],f)==period(e["formation"],f) and abs(b[key]-e["price"])<=EPS*max(1,e["price"])]
                if not hits:continue
                e={**e,"period_end":e["formation"],"formation":hits[0]}
            all_events.append(e)
        breaks.extend(breakout_events(tail,f,major,vals,offset))
        # Role reversal evidence is restricted to day bars for exact touch dates.
        if f=="day":all_events.extend(role_reversal_events(tail,f,major,vals,offset))
    wk=contiguous_tail(completed_bars(v,"week",sessions),"week",sessions,asof)
    completed_week_trend=cycle(q.view(wk[-1]["date"],sessions),"week")["trend"] if wk else "unknown"
    ma={}
    for f in LOOKBACK:
        for k in ("ma20","ma60","ma250") if f=="day" else ("ma20",):
            # developing weekly/monthly MA is not confirmed confluence
            bs=v["groups"][f]["bars"]
            if bs and (f=="day" or bs[-1]["complete"]):
                ma[f+"."+k]=v["groups"][f]["indicators"].get(k)
    zones=valid_zones(all_events,daily,a,sessions,ma)
    s=zones["support"][0] if zones["support"] else None;r=zones["resistance"][0] if zones["resistance"] else None
    stop=s["low"]-.5*a if s else None
    if not pos(stop):stop=None
    target=r["low"] if r else None
    risk=(c-stop)/c if stop is not None else None;rr=(target-c)/(c-stop) if target is not None and stop is not None else None
    ind=v["groups"]["day"]["indicators"];m=ind.get("ma20");rsi=ind.get("rsi6")
    ext=(c-m)/a>=2-EPS if pos(m) else None;ob=rsi>=80 if finite(rsi) else None
    extension=True if ext is True or ob is True else False if ext is False and ob is False else None
    flags={"extension":extension,"distance_risk":risk>=.08-EPS if risk is not None else None,"high_volatility":a/c>=.05-EPS,
           "unfavorable_rr":rr<2-EPS if rr is not None else None,"missing_level":stop is None or target is None}
    return {"state":"ready" if not any(x is not False for x in flags.values()) else "caution","risk_veto":any(x is not False for x in flags.values()),
            "price":c,"atr14":a,"support":s,"resistance":r,"invalidation":stop,"target_reference":target,
            "reward_risk":rr,"risk_fraction":risk,"flags":flags,"zones":zones,"breakouts":breaks,"contiguous_counts":coverage,"completed_week_trend":completed_week_trend,"completed_week_date":wk[-1]["date"] if wk else None}

def conditional_plan(report,loc,holding=None,portfolio_permission=None):
    """Separate exit review and new-risk permission. Never issue orders.
    portfolio_permission is an explicit external 5x5 risk-budget approval;
    unknown is not permission. B's defensive veto remains unchanged.
    """
    ctx=report.get("market_industry_context") or {}
    if not isinstance(ctx,dict):ctx={}
    cy=report.get("cycles",{});w=cy.get("week",{});m=cy.get("month",{})
    d=report.get("horizons",{}).get("short",{}).get("D")
    events=loc.get("breakouts",[])
    # Downside review independently visible even when new-risk gate blocked.
    down=any(e["direction"]=="down" and e["state"] in ("confirmed","retest") and e["frequency"] in ("day","week") for e in events)
    held="review_risk" if holding is True and (w.get("trend")=="bearish" or down) else "hold_review" if holding is True else "not_applicable" if holding is False else "holding_status_unknown"
    if not report.get("composite_ready"):
        action="evidence_insufficient_features"
    elif ctx.get("state")=="defensive" or ctx.get("block_new_exposure") is True:
        action="defensive_no_new_exposure"
    elif ctx.get("state")!="context_ready" or ctx.get("block_new_exposure") is not False:
        action="evidence_insufficient_context_or_risk"
    elif portfolio_permission is not True:
        action="portfolio_permission_unverified_or_denied"
    elif loc.get("risk_veto") is not False:
        action="observe_no_chasing"
    else:
        # Only current candidate or current retest can trigger a new plan;
        # an old confirmed breakout is context, not a fresh entry.
        active=any(e["direction"]=="up" and e["state"] in ("candidate","retest") and e["event_date"]==report["asof"] for e in events)
        weekly_ok=(w.get("trend")=="bullish" if w.get("provisional") is False else loc.get("completed_week_trend")=="bullish" and w.get("trend") in ("bullish","range"))
        good=weekly_ok and m.get("trend") not in ("bearish","unknown",None) and finite(d) and d>=20
        action="conditional_opportunity" if good and active else "watch"
    return {"new_exposure":action,"holding_review":held,"portfolio_permission_verified":portfolio_permission is not None,
            "reference_entry":loc.get("price") if action=="conditional_opportunity" else None,
            "reference_invalidation":loc.get("invalidation"),"reference_target":loc.get("target_reference"),
            "reward_risk":loc.get("reward_risk"),"execution":"research_only_Tplus1_limit_gap_liquidity_unverified","probability":None}

def attach_c(q,report,sessions,holding=None,portfolio_permission=None):
    if report.get("code")!=q.code:raise ValueError("report symbol mismatch")
    loc=location_c(q,report["asof"],sessions)
    return {**report,"location_baseline_A":report.get("location"),"location":loc,"plan":conditional_plan(report,loc,holding,portfolio_permission),"location_version":VERSION,"probability":None}
