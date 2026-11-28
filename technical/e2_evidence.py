"""E2 evidence-only metrics. No model modifications, no executable strategy."""
import math
from bisect import bisect_left
from collections import Counter,defaultdict
from statistics import fmean,median
from .quality import classify
from .indicators import date,number
from .model_a import direction_state,INDEX_WEIGHTS
from .e1_scope_candidates import ARMS
H=(5,20)
BINS=("strong_negative","negative","mixed","positive","strong_positive")
def require(ok,reason):
    if not ok:raise ValueError(reason)
def verify_window(raw,fs,code,d,h,cal,meta):
    """Independent strict source gate, only actual t..end and previous observation."""
    if d not in cal or h not in H:return None,"invalid_date_or_horizon"
    i=bisect_left(cal,d);ds=cal[i:i+h+1]
    if len(ds)!=h+1 or meta.get("purged") or meta["label_end_by_horizon"].get(str(h))!=ds[-1]:
        return None,"calendar_or_split"
    # Index only relevant prefix; malformed unknown date cannot be safely localized.
    rm=defaultdict(list);fm=defaultdict(list)
    for rows,m in ((raw,rm),(fs,fm)):
        for x in rows:
            try:t=date(x.get("trade_date"))
            except (ValueError,TypeError,KeyError):return None,"unlocalizable_date"
            if t<=ds[-1]:m[t].append(x)
    prev=max((t for t in rm if t<d),default=None)
    if prev is None:return None,"previous_reference_missing"
    values=[]
    for t in [prev]+ds:
        if len(rm[t])!=1 or len(fm[t])!=1:return None,"missing_or_duplicate_source"
        r,f=rm[t][0],fm[t][0]
        if r.get("ts_code")!=code or f.get("ts_code")!=code:return None,"identity"
        try:
            o,hi,lo,c,v,a,p=[number(r[k]) for k in ("open","high","low","close","vol","amount","pre_close")]
            x=number(f["adj_factor"]);pct=number(r["pct_chg"])
            if not all(math.isfinite(z) for z in (o,hi,lo,c,v,a,p,x,pct)) or min(o,hi,lo,c,p,x)<=0 or lo>min(o,c) or hi<max(o,c) or v<0 or a<0:return None,"invalid_source"
        except (ValueError,TypeError,KeyError,OverflowError):return None,"invalid_source"
        values.append((r,x,c,lo,hi))
    for a,b in zip(values,values[1:]):
        ev=classify(a[0],b[0],a[1],b[1])
        if ev and ev["severity"]=="major":return None,"major_continuity"
    return values[1:],"ok"
def outcome(values):
    base=values[0][1]*values[0][2];cl=[x[1]*x[2]/base for x in values];peak=1.;dd=0.
    for p in cl:
        peak=max(peak,p);dd=min(dd,p/peak-1)
    return {"r":cl[-1]-1,"mae":min(0.,min(x[1]*x[3]/base-1 for x in values[1:])),
            "mfe":max(0.,max(x[1]*x[4]/base-1 for x in values[1:])),"dd":dd}
def benchmark(ix,codes,ds):
    ws=sum(INDEX_WEIGHTS.get(k,0) for k in codes)
    if len(set(codes))!=len(codes) or len(codes)<3 or ws<.75-1e-12:return None
    wealth=0.
    for k in codes:
        rows=ix.get(k) or {};v=[rows.get(d) for d in ds]
        if any(x is None or not math.isfinite(x) or x<=0 for x in v):return None
        wealth+=INDEX_WEIGHTS[k]/ws*v[-1]/v[0]
    return wealth if wealth>0 else None
def simple(r,h,cal,d):
    bars=r["view"]["groups"]["day"]["bars"];ind=r["view"]["groups"]["day"]["indicators"]
    n=20 if h==5 else 60
    i=cal.index(d);need=cal[i-n:i+1] if i>=n else []
    mom=None
    if len(need)==n+1 and [x["date"] for x in bars[-n-1:]]==need:
        mom=bars[-1]["close"]/bars[-n-1]["close"]-1
    ma=ind.get("ma"+str(n));c=ind.get("close")
    return {"MA":c/ma-1 if c and ma else None,"MOM":mom}
def ranks(xs):
    order=sorted(range(len(xs)),key=xs.__getitem__);out=[0.]*len(xs);i=0
    while i<len(order):
        j=i+1
        while j<len(order) and xs[order[j]]==xs[order[i]]:j+=1
        for k in order[i:j]:out[k]=(i+j-1)/2+1
        i=j
    return out
def ic(xs,ys):
    if len(xs)<10 or len(set(xs))<2 or len(set(ys))<2:return None
    a,b=ranks(xs),ranks(ys);x,y=fmean(a),fmean(b)
    den=math.sqrt(sum((v-x)**2 for v in a)*sum((v-y)**2 for v in b))
    return sum((v-x)*(w-y) for v,w in zip(a,b))/den if den else None
def mean(xs):return fmean(xs) if xs else None
def quant(xs,q):
    if not xs:return None
    s=sorted(xs);p=(len(s)-1)*q;i=int(p);return s[i]+(s[min(i+1,len(s)-1)]-s[i])*(p-i)
def tail(xs):
    n=math.ceil(.05*len(xs));return {"n":n,"mean":mean(sorted(xs)[:n])}
def sign(x):return "up" if x>0 else "down" if x<0 else "zero"
def prediction(x,model):
    return ("up" if x>=20 else "down" if x<=-20 else "mixed") if model not in ("MA","MOM") else ("up" if x>0 else "down" if x<0 else "mixed")
def summarize(rows,h):
    """Inputs are private in-memory rows. Public report is not authorized by default."""
    n=len(rows);rs=[r["r"] for r in rows];mae=[r["mae"] for r in rows];mfe=[r["mfe"] for r in rows];dd=[r["dd"] for r in rows]
    q=lambda v:{str(int(x*100)):quant(v,x) for x in (.05,.25,.5,.75,.95)}
    ex=[r["excess"] for r in rows if r["excess"] is not None]
    return {"n":n,"dates":len({r["date"] for r in rows}),"return_mean":mean(rs),"return_quantiles":q(rs),"return_tail5":tail(rs),"direction":dict(Counter(sign(x) for x in rs)),
            "excess_n":len(ex),"excess_mean":mean(ex),"mae_quantiles":q(mae),"mae_tail5":tail(mae),"downside_n":sum(x<=(-.05 if h==5 else -.10) for x in mae),
            "mfe_quantiles":q(mfe),"drawdown_quantiles":q(dd),"positive_return_n":sum(x>0 for x in rs)}
def metrics(rows,h,model):
    per=defaultdict(list);conf=Counter();bins=defaultdict(list)
    for r in rows:
        per[r["date"]].append(r);p=prediction(r["score"],model);a=sign(r["r"])
        conf[p+"|"+a]+=1
        if model not in ("MA","MOM"):bins[direction_state(r["score"])].append(r)
    dates={}
    for d,rr in sorted(per.items()):
        up=[r["r"] for r in rr if prediction(r["score"],model)=="up"];dn=[r["r"] for r in rr if prediction(r["score"],model)=="down"]
        good=len(up)>=5 and len(dn)>=5
        dates[d]={"n":len(rr),"up":len(up),"down":len(dn),"ic":ic([x["score"] for x in rr],[x["r"] for x in rr]),
                  "spread":mean(up)-mean(dn) if good else None,"median_spread":median(up)-median(dn) if good else None,
                  "equal_weight":mean([x["r"] for x in rr]),
                  "bins":{k:{"n":len(b),"mean":mean([x["r"] for x in b])} for k in BINS for b in [[x for x in rr if model not in ("MA","MOM") and direction_state(x["score"])==k]]}}
    up=conf["up|up"]+conf["down|up"];dn=conf["up|down"]+conf["down|down"]
    tpr=conf["up|up"]/up if up else None;tnr=conf["down|down"]/dn if dn else None
    v={k:[x[k] for x in dates.values() if x[k] is not None] for k in ("ic","spread","median_spread")}
    return {**summarize(rows,h),"equal_date":{k:{"mean":mean(a),"valid_dates":len(a),"positive_dates":sum(x>0 for x in a)} for k,a in v.items()},
            "direction_confusion":dict(conf),"directional_actual_up":up,"directional_actual_down":dn,
            "balanced_accuracy":(tpr+tnr)/2 if tpr is not None and tnr is not None else None,
            "directional_accuracy":(conf["up|up"]+conf["down|down"])/(up+dn) if up+dn else None,
            "directional_calls":sum(v for k,v in conf.items() if not k.startswith("mixed|")),"mixed":sum(v for k,v in conf.items() if k.startswith("mixed|")),
            "bins":{k:summarize(bins[k],h) for k in BINS} if model not in ("MA","MOM") else {},
            "risk":{str(v):summarize([r for r in rows if r["risk"] is v],h) for v in (True,False,None)},
            "risk_by_bin_regime":{str(v)+"|"+b+"|"+g:summarize([r for r in rows if r["risk"] is v and direction_state(r["score"])==b and r["regime"]==g],h)
                 for v in (True,False,None) for b in BINS for g in sorted({r["regime"] for r in rows})} if model not in ("MA","MOM") else {},
            "per_date":dates}
