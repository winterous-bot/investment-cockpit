"""V1.0 conservative quality admission. No price or factor repairs, no forecasts."""
from collections import Counter
from math import isclose
from bisect import bisect_right
from .indicators import normalize,number,date,period,aggregate,indicators,directions,risk_features
from .signals import signal_snapshot

VERSION="technical-quality-v1.0"
# Policies fixed before live validation. The minor rule is a conservative engineering
# threshold, not a universal rounding guarantee: both absolute and relative limits.
PRE_CLOSE_TOL=.01
PCT_TOL=.01 # percentage points
MINOR_PRICE_MAX=.05
MINOR_REL_MAX=.0001 # one basis point of reference price
WARMUP=120 # full clean bars before exposing recursive features after a severe break
MIN_COMBINED={"day":253,"week":61,"month":61}
RECURSIVE=("dif","dea","macd","rsi6","rsi12","rsi24")

def classify(a,b,fp,fc):
    change=not isclose(fp,fc,rel_tol=1e-10,abs_tol=1e-12)
    try:
        prev,pre,close,pct=map(number,(a["close"],b["pre_close"],b["close"],b["pct_chg"]))
        if min(prev,pre,close,fp,fc)<=0:raise ValueError("nonpositive")
        implied=prev*fp/fc
        pe=abs(implied-pre)
        pcterr=abs(100*(close/pre-1)-pct)
        re=abs(100*(close/implied-1)-pct)
        bound=100*close*PRE_CLOSE_TOL/(pre*implied)+PCT_TOL
        metrics={"pre_close_abs":round(pe,8),"pct_error_pp":round(pcterr,8),"adjusted_return_error_pp":round(re,8),"return_bound_pp":round(bound,8)}
        if pe<=PRE_CLOSE_TOL+1e-8 and pcterr<=PCT_TOL+1e-8 and re<=bound+1e-8:
            return None
        minor=change and pe<=MINOR_PRICE_MAX+1e-8 and pe/pre<=MINOR_REL_MAX+1e-12 and pcterr<=PCT_TOL+1e-8 and re<=bound+1e-8
        return {"date":b["trade_date"],"severity":"minor" if minor else "major","reason":"small_factor_price_discrepancy" if minor else "continuity_failure","factor_change":change,**metrics}
    except (ValueError,TypeError,KeyError,OverflowError):
        return {"date":b["trade_date"],"severity":"major","reason":"missing_or_invalid_reference","factor_change":change}

class QualityHistory:
    """An immutable-in-use audited history. All severe boundaries are retained, not clipped."""
    def __init__(self,raw,factors,code,asof):
        self.code=code;self.asof=date(asof)
        normalize(raw,factors,code,self.asof) # fails closed on missing factors, invalid OHLC, duplicates, future data
        self.raw=sorted((dict(r) for r in raw),key=lambda r:r["trade_date"])
        self.factors=sorted((dict(r) for r in factors),key=lambda r:r["trade_date"])
        self.dates=[r["trade_date"] for r in self.raw]
        fm={r["trade_date"]:number(r["adj_factor"]) for r in self.factors}
        self.events=[]
        for a,b in zip(self.raw,self.raw[1:]):
            e=classify(a,b,fm[a["trade_date"]],fm[b["trade_date"]])
            if e:self.events.append(e)

    def view(self,asof,calendar):
        asof=date(asof)
        if asof not in self.dates:raise ValueError("feature asof not observed")
        # Re-normalize from actual historical prefix, never use future factor or future exception.
        raw=self.raw[:bisect_right(self.dates,asof)]
        factors=[r for r in self.factors if r["trade_date"]<=asof]
        bars=normalize(raw,factors,self.code,asof)
        events=[dict(e) for e in self.events if e["date"]<=asof]
        major=[e["date"] for e in events if e["severity"]=="major"]
        cut=major[-1] if major else None
        clean=[b for b in bars if cut is None or b["date"]>cut]
        # Exclude the ENTIRE affected week/month, not just the event day.
        gs={"day":clean}
        for freq in ("week","month"):
            eligible=[b for b in clean if cut is None or period(b["date"],freq)>period(cut,freq)]
            gs[freq]=aggregate(eligible,freq,asof,calendar)
        result={}
        for freq,bs in gs.items():
            n=len(bs)
            # A current incomplete week/month is permitted for daily reporting, but
            # only completed bars count toward post-break recursive warmup.
            complete_n=n if freq=="day" else sum(bool(b["complete"]) for b in bs)
            ind=indicators(bs,freq) if bs else {}
            ds=directions(bs,freq) if bs else {}
            ss=signal_snapshot(bs,freq) if bs else {}
            if cut:
                if complete_n<WARMUP:
                    for k in RECURSIVE:
                        if k in ind:ind[k]=None
                if complete_n<WARMUP+1:
                    for k in RECURSIVE:
                        if k in ds:ds[k]=None
                    if "macd_cross" in ss:ss["macd_cross"]=None
            ready=n>=MIN_COMBINED[freq] and (not cut or complete_n>=WARMUP+1)
            result[freq]={"bars":bs,"count":n,"completed_count":complete_n,"feature_ready":ready,
                          "indicators":ind,"directions":ds,"signals":ss}
        state="blocked" if any(not x["feature_ready"] for x in result.values()) else "ready_with_warning" if events else "ready"
        return {"asof":asof,"events":events,"last_major":cut,"state":state,
                "combined_feature_ready":all(x["feature_ready"] for x in result.values()),"groups":result}

    def label_admission(self,feature_date,horizon,sessions):
        """Future label gate only. Sessions must be verified full exchange calendar,
        not the set of observed stock bars. Never skip suspended/missing dates.
        """
        f=date(feature_date)
        if not isinstance(horizon,int) or isinstance(horizon,bool) or horizon<1:raise ValueError("invalid horizon")
        if list(sessions)!=sorted(set(sessions)) or any(date(d)!=d for d in sessions):raise ValueError("invalid sessions")
        if f not in sessions or f not in self.dates:return {"eligible":False,"reason":"feature_not_observed","label_end":None}
        i=sessions.index(f);end=i+horizon
        if end>=len(sessions) or sessions[end]>self.asof:return {"eligible":False,"reason":"future_not_available","label_end":None}
        window=sessions[i:end+1];last=window[-1]
        major=[e["date"] for e in self.events if e["severity"]=="major" and f<=e["date"]<=last]
        if major:return {"eligible":False,"reason":"major_event_in_label_window","label_end":last,"events":major}
        if any(d not in self.dates for d in window):return {"eligible":False,"reason":"missing_or_suspended_session","label_end":last}
        minor=[e["date"] for e in self.events if e["severity"]=="minor" and f<=e["date"]<=last]
        return {"eligible":True,"reason":"minor_warning" if minor else "clean","label_end":last,"warnings":minor}

    def training_admission(self,feature_date,horizon,sessions):
        """Mandatory two-sided gate for later model research; no training labels computed here."""
        v=self.view(feature_date,sessions)
        if not v["combined_feature_ready"]:
            return {"eligible":False,"reason":"insufficient_clean_feature_history","label_end":None}
        # Require exchange session coverage of daily feature window; no implicit
        # suspension forward-fill. Upstream must supply verified trade_cal sessions.
        d=v["groups"]["day"]["bars"][-MIN_COMBINED["day"]]["date"]
        if d not in sessions or feature_date not in sessions:
            return {"eligible":False,"reason":"feature_calendar_not_covered","label_end":None}
        observed=set(self.dates)
        if any(x not in observed for x in sessions if d<=x<=feature_date):
            return {"eligible":False,"reason":"missing_feature_session","label_end":None}
        return self.label_admission(feature_date,horizon,sessions)

def public_summary(view):
    return {"version":VERSION,"state":view["state"],"asof":view["asof"],
            "event_counts":dict(Counter(e["severity"] for e in view["events"])),
            "events":view["events"],"last_major":view["last_major"],
            "combined_feature_ready":view["combined_feature_ready"],
            "clean_counts":{k:v["count"] for k,v in view["groups"].items()},
            "completed_clean_counts":{k:v["completed_count"] for k,v in view["groups"].items()},
            "feature_ready":{k:v["feature_ready"] for k,v in view["groups"].items()}}
