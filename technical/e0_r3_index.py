"""Exact C R1 research-only indexed implementation. Frozen C modules unchanged."""
from bisect import bisect_right
from contextlib import contextmanager
from . import model_c_r1 as C
from .model_c_r1 import (QualityHistory,WARMUP,EPS,AGE,pos,cycle,atr_series,pivot_events,role_reversal_events,breakout_events,independent_dates)
from .e0_r2_acceleration import acceleration
_INDEX=None

class CalendarIndex:
    def __init__(self,sessions):
        if not sessions or list(sessions)!=sorted(set(sessions)):raise ValueError("invalid calendar")
        self.sessions=sessions;self.ix={d:i for i,d in enumerate(sessions)};self.groups={};self.ends={"day":sessions}
        for f in ("week","month"):
            g={}
            for d in sessions:g.setdefault(C.period(d,f),[]).append(d)
            self.groups[f]=g;self.ends[f]=sorted(v[-1] for v in g.values())

def completed_bars(view,freq,sessions):
    if sessions is not _INDEX.sessions:raise ValueError("calendar identity")
    bs=view["groups"][freq]["bars"]
    if freq=="day":return bs
    out=[]
    for b in bs:
        ds=_INDEX.groups[freq].get(C.period(b["date"],freq),[])
        if b["complete"] and ds and ds[-1]==b["date"] and b["sessions"]==len(ds) and ds[0]>sessions[0]:out.append(b)
    return out

def contiguous_tail(bs,freq,sessions,asof):
    if sessions is not _INDEX.sessions:raise ValueError("calendar identity")
    if not bs:return []
    ends=_INDEX.ends[freq];i=bisect_right(ends,asof);out=[]
    for b,j in zip(reversed(bs),range(i-1,-1,-1)):
        if b["date"]!=ends[j]:break
        out.append(b)
    return list(reversed(out))

def collect(q,asof,sessions):
    if not isinstance(q,QualityHistory):raise TypeError("audited history required")
    if sessions is not _INDEX.sessions or asof not in _INDEX.ix:raise ValueError("invalid calendar")
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
        by_period={}
        if f!="day":
            for b in daily:by_period.setdefault(C.period(b["date"],f),[]).append(b)
        for e in C.pivot_events(tail,f,major,vals,offset):
            if f!="day":
                key="low" if e["side"]=="support" else "high"
                hits=[b["date"] for b in by_period.get(C.period(e["formation"],f),[]) if abs(b[key]-e["price"])<=EPS*max(1,e["price"])]
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
        ind=C.indicators(full[:ix[tail[-1]["date"]]+1],f)
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
    c=daily[-1]["close"];ix=_INDEX.ix;now=ix[daily[-1]["date"]];dates=[b["date"] for b in daily]
    usable=[]
    for e in events:
        if e["frequency"] not in freqs or not pos(e["price"]):continue
        d=e["confirmed"];p=e["price"];side=e["side"]
        if d not in ix or e["formation"] not in ix or not ix[e["formation"]]<=ix[d]<=now:continue
        if now-ix[d]>AGE[e["frequency"]]:continue
        after=daily[bisect_right(dates,d):]
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


@contextmanager
def indexed(index):
    global _INDEX
    if _INDEX is not None:raise RuntimeError("nested index scope")
    _INDEX=index
    patches={k:getattr(C,k) for k in ("collect","zones_for","contiguous_tail")}
    try:
        C.collect=collect;C.zones_for=zones_for;C.contiguous_tail=contiguous_tail
        yield
    finally:
        for k,v in patches.items():setattr(C,k,v)
        _INDEX=None
