"""Independent implementation and vendor-field alignment for research acceptance."""
from datetime import datetime
from math import isclose
from statistics import fmean
from .indicators import normalize,aggregate,period,number,date
from .signals import signal_snapshot
from .data import calendar
from tushare_5000 import POINTS
from .diagnostics import emit,groups

def provider_periods(rows,code,freq,asof,local,adjusted=True):
    # A Friday/calendar-month-end label need not equal last exchange trading date.
    # end_date identifies the snapshot cutoff, not the period label.
    out={};rejected=0;duplicates=0
    for r in rows:
        try:
            if r.get("ts_code")!=code:raise ValueError("symbol")
            if adjusted and str(r.get("freq","")).lower()!=freq:raise ValueError("frequency")
            label=date(str(r["trade_date"]));key=period(label,freq)
            b=local.get(key)
            if not b or not b["complete"]:continue
            cutoff=date(str(r["end_date"])) if adjusted and r.get("end_date") else b["date"]
            if cutoff>asof or cutoff<b["date"] or period(cutoff,freq)!=key:raise ValueError("cutoff")
            required=("close","vol","close_hfq","close_qfq") if adjusted else ("open","high","low","close","vol")
            val=tuple(number(r[k]) for k in required)
            # Multiple running snapshots for same period: newest verified cutoff wins.
            old=out.get(key)
            if old and cutoff==old[0]:
                if val!=old[1]:raise RuntimeError("conflicting duplicate cutoff")
                duplicates+=1;continue
            if not old or cutoff>old[0]:out[key]=(cutoff,val)
        except (ValueError,KeyError,TypeError):rejected+=1
    return out,rejected,duplicates

def provider_check_r2(api,code,bars,raw,factors,asof,cal):
    for ep in ("stk_week_month_adj","weekly","monthly"):POINTS.setdefault(ep,2000)
    start=str(int(asof[:4])-2)+"0101"
    raw_bars=normalize(raw,None,code,asof)
    anchor=number(next(x["adj_factor"] for x in factors if x["trade_date"]==asof))
    for freq in ("week","month"):
        adj={period(x["date"],freq):x for x in aggregate(bars,freq,asof,cal)}
        raw_periods={period(x["date"],freq):x for x in aggregate(raw_bars,freq,asof,cal)}
        for endpoint in ("stk_week_month_adj","weekly" if freq=="week" else "monthly"):
            adjusted=endpoint=="stk_week_month_adj"
            try:
                params={"ts_code":code,"start_date":start,"end_date":asof}
                if adjusted:params["freq"]=freq
                fields="ts_code,trade_date,end_date,freq,close,close_hfq,close_qfq,vol" if adjusted else "ts_code,trade_date,open,high,low,close,vol"
                remote=api.ask(endpoint,params,fields)
                matched,rejected,duplicates=provider_periods(remote,code,freq,asof,adj,adjusted)
                keys=sorted(matched)[-12:]
                if not keys:
                    emit("TECH_PROVIDER_R2",{"code":code,"period":freq,"endpoint":endpoint,"state":"no_comparable_periods","rows":len(remote),"rejected":rejected,"fields_present":sorted(remote[0]) if remote else []})
                    continue
                close_errors=[];volume_errors=[];adjusted_errors=[];qfq_errors=[];ohlc_errors=[]
                for k in keys:
                    vals=matched[k][1];r=raw_periods[k];a=adj[k]
                    if adjusted:
                        raw_close,vol,hfq,qfq=vals
                        adjusted_errors.append(abs(hfq/anchor-a["close"]))
                        qfq_errors.append(abs(qfq-a["close"]))
                    else:
                        o,h,l,raw_close,vol=vals
                        ohlc_errors.extend(abs(v-r[name]) for name,v in zip(("open","high","low"),(o,h,l)))
                    close_errors.append(abs(raw_close-r["close"]))
                    volume_errors.append(abs(vol-r["vol"]))
                out={"code":code,"period":freq,"endpoint":endpoint,"state":"compared","count":len(keys),"first":adj[keys[0]]["date"],"last":adj[keys[-1]]["date"],"rows":len(remote),"rejected":rejected,"duplicate_identical":duplicates,
                     "raw_close_within_002":sum(x<=.02000001 for x in close_errors),"raw_close_max_abs":round(max(close_errors),6),"volume_within_one_hand":sum(x<=1 for x in volume_errors),"volume_max_abs":round(max(volume_errors),3)}
                if adjusted:out.update(hfq_reanchored_within_002=sum(x<=.02000001 for x in adjusted_errors),hfq_reanchored_max_abs=round(max(adjusted_errors),6),qfq_direct_max_abs=round(max(qfq_errors),6))
                else:out.update(raw_ohl_max_abs=round(max(ohlc_errors),6),raw_ohl_within_002=sum(x<=.02000001 for x in ohlc_errors))
                emit("TECH_PROVIDER_R2",out)
            except Exception as e:emit("TECH_PROVIDER_R2",{"code":code,"period":freq,"endpoint":endpoint,"state":"unavailable","reason":type(e).__name__})

def oracle(bars,freq):
    # Independent simple loops: no calls to the production indicators/crossing implementation.
    c=[x["close"] for x in bars]
    def diff(n,m,t):
        return sum(c[t-n:t])/n-sum(c[t-m:t])/m if t>=max(n,m) else None
    def trend(a,b):
        if a is None or b is None:return None
        return 1 if a<=0<b else -1 if a>=0>b else 0
    e12=e26=c[0];dea=0.;hist=[]
    for x in c:
        e12+=(x-e12)*2/13;e26+=(x-e26)*2/27
        dif=e12-e26;dea+=(dif-dea)*2/10
        hist.append(dif-dea)
    n=len(c)
    out={"ma5_ma10_cross":trend(diff(5,10,n-1),diff(5,10,n)),
         "ma10_ma20_cross":trend(diff(10,20,n-1),diff(10,20,n)),
         "macd_cross":trend(hist[-2],hist[-1]) if n>=36 else None,
         "close_ma20_cross":trend(c[-2]-sum(c[-21:-1])/20,c[-1]-sum(c[-20:])/20) if n>=21 else None}
    for k in (20,60):
        if n<=k:out.update({"prior_high"+str(k):None,"prior_low"+str(k):None,"breakout"+str(k):None});continue
        high=low=None
        for i in range(n-k-1,n-1):
            high=bars[i]["high"] if high is None else max(high,bars[i]["high"])
            low=bars[i]["low"] if low is None else min(low,bars[i]["low"])
        out.update({"prior_high"+str(k):high,"prior_low"+str(k):low,"breakout"+str(k):1 if c[-1]>high else -1 if c[-1]<low else 0})
    return out
def signal_checks(code,raw,factors,asof,cal):
    # Real historical data across the latest 120 daily, 60 weekly and 36 monthly prefixes.
    # Within a single anchored price series these sign/level checks are scale-consistent.
    # Full historical point-in-time evaluation is separately tested in historical_checks.
    bars=normalize(raw,factors,code,asof)
    for freq,bs in groups(bars,asof,cal).items():
        count=0;passed=0;events={"up":0,"down":0,"neutral":0};failures=[]
        cap={"day":120,"week":60,"month":36}[freq]
        for end in range(max(61,len(bs)-cap+1),len(bs)+1):
            a=signal_snapshot(bs[:end],freq);b=oracle(bs[:end],freq)
            for k,v in b.items():
                w=a.get(k);ok=(v==w if v is None or w is None or not k.startswith("prior_") else isclose(v,w,abs_tol=1e-9,rel_tol=1e-12))
                count+=1;passed+=int(ok)
                if not ok and len(failures)<5:failures.append({"date":bs[end-1]["date"],"metric":k})
                if k.endswith("cross") or k.startswith("breakout"):
                    if v in (-1,0,1):events[{-1:"down",0:"neutral",1:"up"}[v]]+=1
        emit("TECH_SIGNALS_R2",{"code":code,"period":freq,"comparisons":count,"passed":passed,"events":events,"examples_of_failure":failures})
        if not count or count!=passed:raise RuntimeError("signal oracle mismatch")
