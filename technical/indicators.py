"""Technical foundation V1.0. Deterministic, as-of only, no prediction."""
from datetime import datetime
from math import isfinite, sqrt, log
from statistics import fmean, pstdev, stdev
from collections import defaultdict

VERSION="technical-foundation-v1.0-r1"
def number(v):
    if isinstance(v,bool): raise ValueError("boolean numeric field")
    n=float(v)
    if not isfinite(n): raise ValueError("nonfinite numeric field")
    return n

def date(v):
    if not isinstance(v,str) or len(v)!=8 or datetime.strptime(v,"%Y%m%d").strftime("%Y%m%d")!=v:
        raise ValueError("invalid date")
    return v

def unique(rows,code,asof):
    out={}
    for r in rows:
        if r.get("ts_code")!=code: raise ValueError("unexpected symbol")
        d=date(r.get("trade_date"))
        if d>asof: raise ValueError("future record")
        if d in out: raise ValueError("duplicate date")
        out[d]=r
    return out

def normalize(rows,factors,code,asof):
    """Prices: raw * factor / as-of factor; volumes stay in hands, amounts in thousand CNY."""
    asof=date(asof); raw=unique(rows,code,asof); fs=unique(factors,code,asof) if factors is not None else None
    if not raw: raise ValueError("no daily bars")
    if max(raw)!=asof: raise ValueError("latest bar missing or suspended")
    if fs is not None and asof not in fs: raise ValueError("as-of factor missing")
    anchor=number(fs[asof]["adj_factor"]) if fs is not None else 1.
    if anchor<=0: raise ValueError("invalid anchor factor")
    result=[]
    for d,r in sorted(raw.items()):
        if fs is not None and d not in fs: raise ValueError("missing daily adjustment factor")
        f=number(fs[d]["adj_factor"]) if fs is not None else 1.
        if f<=0: raise ValueError("invalid factor")
        o,h,l,c=[number(r[k]) for k in ("open","high","low","close")]
        vol,amt=number(r["vol"]),number(r["amount"])
        if min(o,h,l,c)<=0 or l>min(o,c) or h<max(o,c) or vol<0 or amt<0: raise ValueError("invalid OHLCV")
        result.append(dict(date=d,open=o*f/anchor,high=h*f/anchor,low=l*f/anchor,close=c*f/anchor,vol=vol,amount=amt))
    return result

def period(d,freq):
    x=datetime.strptime(d,"%Y%m%d")
    if freq=="week":
        y,w,_=x.isocalendar();return y,w
    if freq=="month":return x.year,x.month
    raise ValueError("unknown aggregation")

def aggregate(bars,freq,asof,calendar):
    groups=defaultdict(list)
    for b in bars:groups[period(b["date"],freq)].append(b)
    result=[]
    for k,items in sorted(groups.items()):
        last=items[-1]
        result.append(dict(date=last["date"],open=items[0]["open"],high=max(b["high"] for b in items),low=min(b["low"] for b in items),close=last["close"],vol=sum(b["vol"] for b in items),amount=sum(b["amount"] for b in items),sessions=len(items),complete=not any(d>asof and period(d,freq)==k for d in calendar)))
    return result

def mean_last(v,n):return fmean(v[-n:]) if len(v)>=n else None
def ema(v,n):
    if not v:return []
    a=2/(n+1);out=[v[0]]
    for x in v[1:]:out.append(a*x+(1-a)*out[-1])
    return out
def wilder(v,n):
    if not v:return []
    out=[v[0]]
    for x in v[1:]:out.append((x+(n-1)*out[-1])/n)
    return out
def rsi(closes,n):
    if len(closes)<=n:return None
    delta=[0.]+[b-a for a,b in zip(closes,closes[1:])]
    up=wilder([max(0.,x) for x in delta],n)[-1]
    denom=wilder([abs(x) for x in delta],n)[-1]
    return 100*up/denom if denom>0 else None
def indicators(bars,freq):
    if not bars:raise ValueError("empty series")
    c=[b["close"] for b in bars];v=[b["vol"] for b in bars]
    out={"close":c[-1],"vol":v[-1],"vol_ma5":mean_last(v,5),"vol_ma10":mean_last(v,10)}
    for n in ((5,10,20,60,250) if freq=="day" else (5,10,20)):
        out["ma"+str(n)]=mean_last(c,n)
    # Full-history initialization, require at least 35 bars for MACD reporting.
    dif=[a-b for a,b in zip(ema(c,12),ema(c,26))];dea=ema(dif,9)
    out.update(dif=dif[-1] if len(c)>=35 else None,dea=dea[-1] if len(c)>=35 else None,macd=2*(dif[-1]-dea[-1]) if len(c)>=35 else None)
    for n in (6,12,24):out["rsi"+str(n)]=rsi(c,n)
    if len(c)>=20:
        m=fmean(c[-20:]);sd=stdev(c[-20:]);out.update(boll_mid=m,boll_upper=m+2*sd,boll_lower=m-2*sd)
    else:out.update(boll_mid=None,boll_upper=None,boll_lower=None)
    return out

def directions(bars,freq):
    """Compare current period to previous actual bar; no fabricated historical completion."""
    if len(bars)<2:return {}
    a,b=indicators(bars[:-1],freq),indicators(bars,freq)
    return {k:(None if a[k] is None or b[k] is None else (1 if b[k]>a[k] else -1 if b[k]<a[k] else 0)) for k in b if k in a}
def risk_features(bars):
    c=[x["close"] for x in bars];v=[x["vol"] for x in bars]
    tr=[bars[0]["high"]-bars[0]["low"]]+[max(b["high"]-b["low"],abs(b["high"]-a["close"]),abs(b["low"]-a["close"])) for a,b in zip(bars,bars[1:])]
    a=wilder(tr,14)[-1] if len(tr)>=15 else None
    ret=[log(y/x) for x,y in zip(c,c[1:])]
    prior=mean_last(v[:-1],20)
    return {"atr14":a,"atr14_pct":a/c[-1]*100 if a is not None else None,
            "volatility20_annual_pct":pstdev(ret[-20:])*sqrt(252)*100 if len(ret)>=20 else None,
            "volume_vs_prior20":v[-1]/prior if prior else None,
            "distance_52w_high_pct":(c[-1]/max(x["high"] for x in bars[-252:])-1)*100 if len(bars)>=252 else None,
            "distance_52w_low_pct":(c[-1]/min(x["low"] for x in bars[-252:])-1)*100 if len(bars)>=252 else None}
def relative_strength(stock,benchmark,n):
    b={x["date"]:x["close"] for x in benchmark}
    # Match dates exactly, do not compare periods with different endpoints.
    s=[(x["close"],b[x["date"]]) for x in stock if x["date"] in b]
    if len(s)<=n or stock[-1]["date"]!=benchmark[-1]["date"]:return None
    a,z=s[-n-1],s[-1]
    return (z[0]/a[0]/(z[1]/a[1])-1)*100
