"""E0 preflight utilities. No forward return labels or parameter optimization."""
from collections import defaultdict,Counter,OrderedDict
from hashlib import sha256
from datetime import datetime,timedelta
from statistics import median
from bisect import bisect_right
from .data import series,FIELDS
from .indicators import date,number,period,normalize
from .quality import QualityHistory
from .model_b_data import eligible_at
from .model_a import analyze
from tushare_5000 import POINTS
import json

END="20261127";SEED="E-20261128-v1"
EXCLUDED={"002475.SZ","600000.SH","300750.SZ"}
def digest(x):return sha256(json.dumps(x,sort_keys=True,ensure_ascii=False,separators=(",",":"),allow_nan=False).encode()).hexdigest()
def full_calendar(api,start,end):
    # Calendar days, not just returned open days; reject truncation and gaps.
    result=[]
    for y in range(int(start[:4]),int(end[:4])+1):
        lo=max(start,str(y)+"0101");hi=min(end,str(y)+"1231")
        rows=api.ask("trade_cal",{"exchange":"SSE","start_date":lo,"end_date":hi},"cal_date,is_open")
        m={date(r["cal_date"]):str(r["is_open"]) for r in rows}
        a=datetime.strptime(lo,"%Y%m%d");b=datetime.strptime(hi,"%Y%m%d")
        if len(m)!=len(rows) or len(m)!=(b-a).days+1 or min(m)!=lo or max(m)!=hi or any(v not in ("0","1") for v in m.values()):raise ValueError("calendar gap or duplicate")
        result.extend(sorted(d for d,v in m.items() if v=="1"))
    if not result or result!=sorted(set(result)):raise ValueError("calendar invalid")
    return result
def board(k):
    if k.endswith(".SH") and k[:3] in ("688","689"):return "STAR"
    if k.endswith(".SZ") and k[:3] in ("300","301"):return "ChiNext"
    if (k.endswith(".SH") and k[:3] in ("600","601","603","605")) or (k.endswith(".SZ") and k[:3] in ("000","001","002","003")):return "main"
    return None
def strata(universe,asof,amounts,quarter):
    # Amounts are completed prior sessions only; never include quarter first-day close.
    if any(d>=asof for d in amounts) or len(amounts)!=20:raise ValueError("invalid liquidity window")
    out=defaultdict(list);known=defaultdict(list);missing=Counter()
    for k in sorted(eligible_at(universe,asof)-EXCLUDED):
        b=board(k)
        if not b:continue
        v=[m[k] for m in amounts.values() if k in m and m[k]>0]
        if len(v)!=20:out[b+"/missing"].append(k);missing[b]+=1
        else:known[b].append((median(v),k))
    for b,rows in known.items():
        for i,(_,k) in enumerate(sorted(rows)):
            out[b+"/"+("low","mid","high")[min(2,3*i//len(rows))]].append(k)
    return dict(out)
def draw(groups,n,key):
    groups={k:sorted(set(v)) for k,v in groups.items() if v}
    all_codes=[x for v in groups.values() for x in v]
    if len(all_codes)!=len(set(all_codes)):raise ValueError("overlapping strata")
    total=len(all_codes);n=min(n,total)
    if not n:return {}
    quotas={k:n*len(v)/total for k,v in groups.items()}
    q={k:min(len(v),int(quotas[k])) for k,v in groups.items()}
    if n>=len(groups):
        for k in q:q[k]=max(1,q[k])
    while sum(q.values())>n:
        candidates=[k for k in q if q[k]>(1 if n>=len(groups) else 0)]
        k=min(candidates,key=lambda k:(quotas[k]-q[k],k));q[k]-=1
    while sum(q.values())<n:
        k=min((k for k in q if q[k]<len(groups[k])),key=lambda k:(-(quotas[k]-q[k]),k));q[k]+=1
    return {k:sorted(v,key=lambda code:(sha256(f"{SEED}|{key}|{code}".encode()).hexdigest(),code))[:q[k]] for k,v in sorted(groups.items())}
def historical_history(api,code,interval,cutoff):
    start,end=interval
    if start>cutoff:raise ValueError("not yet listed")
    stop=min(cutoff,end) if end else cutoff
    raw=series(api,"daily",code,start,stop,FIELDS+",pre_close,pct_chg,ah_vol,ah_amount")
    fs=series(api,"adj_factor",code,start,stop,"ts_code,trade_date,adj_factor")
    if not raw:raise ValueError("no history")
    last=max(date(r["trade_date"]) for r in raw)
    # Preserve actual last observation; do not invent a final close on a delist/suspend date.
    extra=sum(r["trade_date"]>last for r in fs)
    q=QualityHistory(raw,[r for r in fs if r["trade_date"]<=last],code,last)
    return q,{"requested_end":stop,"last_observed":last,"bars":len(raw),"factors":len(fs),"factor_rows_after_last":extra,"digest":digest([q.raw,q.factors])}
def calendar_coverage(rows,sessions,start,end):
    expected={d for d in sessions if start<=d<=end};obs={x["date"] for x in rows or []}
    return {"expected":len(expected),"present":len(expected&obs),"missing":len(expected-obs),"unexpected":len(obs-expected) if rows else 0,
            "first_missing":min(expected-obs) if expected-obs else None}
class CachedHistory(QualityHistory):
    """Bounded, per-stock cache; shorten calendar only for view(), not labels.
    Frozen view uses calendar solely for future sessions in its current period.
    Verify exact parity against full calendar oracle before scale.
    """
    def __init__(self,q,calendar,max_views=5):
        self.__dict__.update(q.__dict__);self.calendar=calendar;self.cache=OrderedDict();self.max_views=max_views;self.hits=0;self.misses=0
    def view(self,asof,calendar):
        if calendar is not self.calendar:raise ValueError("calendar identity mismatch")
        if asof in self.cache:
            self.hits+=1;self.cache.move_to_end(asof);return self.cache[asof]
        # Future week/month sessions only; 35 calendar days exceed both periods.
        i=bisect_right(calendar,asof);end=(datetime.strptime(asof,"%Y%m%d")+timedelta(days=35)).strftime("%Y%m%d")
        v=super().view(asof,calendar[i:bisect_right(calendar,end)])
        self.misses+=1;self.cache[asof]=v
        while len(self.cache)>self.max_views:self.cache.popitem(last=False)
        return v
def feature_calendar_diagnostics(q,view,sessions):
    # Full observed daily 253 and full last 61 weekly/monthly windows (or all available).
    # Separate diagnostic; do not modify frozen scoring/eligibility in E0.
    d=view["asof"];obs=set(q.dates);out={}
    for f,n in (("day",253),("week",61),("month",61)):
        b=view["groups"][f]["bars"]
        if len(b)<n:out[f]={"state":"insufficient_bars","missing":None};continue
        first=b[-n]["date"]
        if f!="day":
            prior=[x for x in sessions if x<=first and period(x,f)==period(first,f)]
            if prior:first=prior[0]
        exp=[x for x in sessions if first<=x<=d]
        out[f]={"state":"complete" if exp and not(set(exp)-obs) else "gaps","missing":len(set(exp)-obs),"start":first}
    return out
def admission_counts(q,d,sessions):
    # Do not compute or expose outcomes in E0.
    return {str(h):q.training_admission(d,h,sessions) for h in (1,5,10,20,40)}
def safe_probe(api,name,params,fields,validate):
    # Registration only for client's metadata; zero does not imply free entitlement.
    POINTS.setdefault(name,0)
    try:
        rows=api.ask(name,params,fields,retry=1)
        return {"state":"empty" if not rows else "usable" if validate(rows) else "invalid_or_incomplete","rows":len(rows)}
    except Exception as e:return {"state":"unavailable","error_type":type(e).__name__}
