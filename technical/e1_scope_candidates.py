"""Independent DW/H research candidates. No changes to frozen model or outcomes."""
from datetime import datetime
from collections import defaultdict
from bisect import bisect_left,bisect_right
from .model_e0 import digest,QualityHistory,CachedHistory,feature_calendar_diagnostics,CALENDAR_START
from .quality import MIN_COMBINED,WARMUP
from .indicators import date,period,number,normalize
from .model_a import weighted,direction_state,cycle,relative_component,volume_component,_completed_week_views
from .e1_q1_r1 import DATA_ERRORS,fetch_raw,audited,diagnosis
from tushare_5000 import SafeAPIError
import time
HORIZONS=(1,5,10,20,40)
DW={"short":(65/90,25/90),"medium":(25/75,50/75)}
ARMS=("A3","DW","A3-H","DW-H")
def dw_scores(a,view):
    ready=all(view["groups"][f]["feature_ready"] for f in ("day","week"))
    scores={}
    for h,w in DW.items():
        t=weighted([a["cycles"][f]["T"] for f in ("day","week")],w)
        m=weighted([a["cycles"][f]["M"] for f in ("day","week")],w)
        v=a["horizons"][h]["V"]["V"];r=a["horizons"][h]["R"]["R"]
        d=weighted([t,m,v,r],(.55,.20,.10,.15)) if ready else None
        scores[h]=d
    return ready,scores

def independent_dw(q,d,cal,indexes):
    v=q.view(d,cal);cy={f:cycle(v,f) for f in ("day","week")};weeks=_completed_week_views(q,v,cal)
    a={"cycles":cy,"horizons":{}}
    for h,ns in (("short",(5,20)),("medium",(20,60))):
        vv=volume_component(v,"day") if h=="short" else volume_component(weeks[0],"week") if weeks else {"V":None}
        a["horizons"][h]={"V":vv,"R":relative_component(v["groups"]["day"]["bars"],indexes,cal,d,ns)}
    return dw_scores(a,v)
def invalid_dates(raw,fs,code):
    """Conservative localized validation, dates only; cannot place ambiguous rows."""
    rm=defaultdict(list);fm=defaultdict(list)
    for rows,m in ((raw,rm),(fs,fm)):
        for r in rows:
            try:d=date(r.get("trade_date"))
            except DATA_ERRORS:return None
            if r.get("ts_code")!=code:return None
            m[d].append(r)
    bad=set()
    for d,rs in rm.items():
        try:normalize(rs,fm.get(d,[]),code,d)
        except DATA_ERRORS:bad.add(d)
    # Duplicate factor identity invalid even when unused; other unused factors
    # follow frozen normalization (numeric factor needed only on observed bars).
    bad.update(d for d,rs in fm.items() if len(rs)!=1)
    return sorted(bad)
def fetch_inputs(api,k,interval,cutoff):
    """Preserve original R2 source fingerprint and retain raw only in memory."""
    raw=[];fs=[];err=[]
    for attempt in range(2):
        try:
            raw,fs=fetch_raw(api,k,interval,cutoff);q=audited(raw,fs,k)
            return q,raw,fs,{"state":"ok","source":digest([q.raw,q.factors]),"attempts":attempt+1}
        except SafeAPIError:err.append("source_unavailable")
        except DATA_ERRORS:err.append("data_quality")
        if not attempt:time.sleep(.65)
    if err[-1]=="source_unavailable":
        return None,[],[],{"state":"source_unavailable","source":None}
    problems=diagnosis(raw,fs,k);ds=[x["date"] for x in problems if x["date"] is not None]
    first=min(ds) if ds and all(x["date"] is not None for x in problems) else None
    q=None
    if first:
        try:q=audited([r for r in raw if r["trade_date"]<first],[r for r in fs if r["trade_date"]<first],k)
        except DATA_ERRORS:pass
    return q,raw,fs,{"state":"data_quality","source":digest([raw,fs]),"first_invalid":first,
        "observed_dates":sorted({r["trade_date"] for r in raw if isinstance(r.get("trade_date"),str)}),"problems":problems[:20]}
def next_month(d):
    y,m=int(d[:4]),int(d[4:6]);return f"{y+(m==12):04d}{m%12+1:02d}01"
def segment_bounds(bad,d,cal):
    if bad is None:return None,None,None
    i=bisect_right(bad,d)
    if i==0:return None,None,bad[0] if bad else None
    b=bad[i-1];lo=max(next_month(b),CALENDAR_START)
    # CALENDAR_START is verified natural-day Jan 1, 2012; calendar starts first open.
    j=bisect_left(cal,lo);start=cal[j] if j<len(cal) else None
    return b,start,bad[i] if i<len(bad) else None
def h_history(raw,fs,code,d,cal,bad,cache=None):
    """Source future rows only extend segment for labels. Selection uses bad<=d."""
    if bad is None:return None,{"reason":"unlocalizable"}
    b,start,stop=segment_bounds(bad,d,cal)
    if b is not None and (start is None or start>d):return None,{"reason":"restart_not_reached","boundary":b,"start":start}
    key=(b,start,stop)
    if cache is not None and key in cache:return cache[key]
    rr=[r for r in raw if (start is None or r["trade_date"]>=start) and (stop is None or r["trade_date"]<stop)]
    ff=[r for r in fs if (start is None or r["trade_date"]>=start) and (stop is None or r["trade_date"]<stop)]
    meta={"boundary":b,"start":start,"next_invalid":stop,"reason":"segment",
          "excluded_rows":sum(r["trade_date"]<start for r in raw) if start else 0,
          "excluded_digest":digest([[r for r in raw if r["trade_date"]<start],[r for r in fs if r["trade_date"]<start]]) if start else None}
    try:q=CachedHistory(audited(rr,ff,code),cal)
    except DATA_ERRORS:q=None;meta["reason"]="invalid_segment"
    out=q,meta
    if cache is not None:cache[key]=out
    return out
def restart_checks(q,v,cal,freqs):
    # Require post-restart complete clean windows; no partially observed first
    # week/month counted as complete. Frozen major-event cut stays in force.
    d=v["asof"];obs=set(q.dates);counts={}
    for f in freqs:
        n=max(MIN_COMBINED[f],WARMUP+1);bars=v["groups"][f]["bars"]
        eligible=[b for b in bars if f=="day" or b["complete"]]
        if len(eligible)<n:counts[f]="insufficient_restart_warmup";continue
        first=eligible[-n]["date"]
        if f!="day":
            ps=[x for x in cal if x<=first and period(x,f)==period(first,f)]
            if not ps or period(first,f)==period(cal[0],f):counts[f]="calendar_not_covered";continue
            first=ps[0]
        if first not in cal or d not in cal:counts[f]="calendar_not_covered";continue
        if any(x not in obs for x in cal if first<=x<=d):counts[f]="gaps";continue
        counts[f]="complete"
    return counts
def label_only(q,d,h,cal,bad=None):
    # Do not allow invalid rows between t and t+h; never consult later rows
    # to decide feature display. Unlocatable invalid source remains blocked.
    i=bisect_left(cal,d)
    if i+h>=len(cal):return {"eligible":False,"reason":"future_not_available"}
    end=cal[i+h]
    if bad is not None and any(d<=x<=end for x in bad):
        return {"eligible":False,"reason":"invalid_source_in_label_window"}
    return q.label_admission(d,h,cal)
def arm_result(r,q,d,cal,mode,restart=False,bad=None):
    if r is None:return {"ready":False,"scored":False,"strict":False,"context":False,"D":{},"labels":{},"reason":"no_valid_history"}
    v,a=r["view"],r["A"];freqs=("day","week") if mode=="DW" else ("day","week","month")
    if mode=="DW":ready,ds=dw_scores(a,v)
    else:ready=v["combined_feature_ready"];ds={h:x["D"] for h,x in a["horizons"].items()}
    strict=all(r["coverage"][f]["state"]=="complete" for f in freqs)
    restart_state=restart_checks(q,v,cal,freqs) if restart else {}
    if restart:
        # Distinguish numerical component evidence from permitted recovered score.
        guard=all(x=="complete" for x in restart_state.values())
        ready=ready and guard;strict=strict and guard
    scored=bool(ready and all(x is not None for x in ds.values()))
    strict=bool(scored and strict)
    labels={}
    for h in HORIZONS:
        if not ready:ad={"eligible":False,"reason":"insufficient_feature_history"}
        elif mode=="DW" or restart:
            if not all(r["coverage"][f]["state"]=="complete" for f in freqs) or (restart and not all(x=="complete" for x in restart_state.values())):
                ad={"eligible":False,"reason":"feature_calendar_incomplete"}
            else:ad=label_only(q,d,h,cal,bad)
        else:ad=r["admission"][str(h)]
        labels[str(h)]={"eligible":bool(ad["eligible"]),"reason":ad["reason"]}
    ctx=r["B"]["market_industry_context"]
    return {"ready":bool(ready),"scored":scored,"strict":strict,"context":all(ctx[k] for k in ("market_ready","breadth_ready","liquidity_ready","industry_ready")),
        "D":ds if scored else {},"labels":labels,"restart_state":restart_state,
        "risk_veto":r["C"]["locations"]["short"].get("risk_veto"),"reason":"ok" if scored else "feature_or_component_blocked"}
def blank():return arm_result(None,None,None,None,"A3")
