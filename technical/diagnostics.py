"""Non-production sensitivity and provider cross-checks; never select variants by fit."""
from statistics import fmean
from .indicators import aggregate,indicators,period,number,directions,normalize
from .data import series,calendar
from tushare_5000 import POINTS
import json
def emit(label,value):print(label+" "+json.dumps(value,ensure_ascii=False),flush=True)
def groups(bars,asof,cal):
    return {"day":bars,"week":aggregate(bars,"week",asof,cal),"month":aggregate(bars,"month",asof,cal)}
def sensitivity(bars,asof,cal,ref):
    # Round each adjusted daily price only for a diagnostic. Canonical engine stays full precision.
    rounded=[{**x,**{k:round(x[k],2) for k in ("open","high","low","close")}} for x in bars]
    base,alt=groups(bars,asof,cal),groups(rounded,asof,cal)
    keys={"day":["ma250","boll_upper","boll_lower"],"week":["ma20","boll_upper","boll_lower"],"month":["ma10","dif","dea","macd","boll_upper","boll_lower"]}
    for p,ks in keys.items():
        c=indicators(base[p],p);r=indicators(alt[p],p)
        # EMA initialization sensitivity from truncation; not a candidate tuning rule.
        tails={str(n):indicators(base[p][-n:],p) for n in (60,120) if len(base[p])>=n}
        for k in ks:
            emit("TECH_SENSITIVITY",{"period":p,"metric":k,"reference":ref[p][k],"full":round(c[k],6),"rounded_daily":round(r[k],6),
                 "tail":{n:round(x[k],6) if x[k] is not None else None for n,x in tails.items()} if k in ("dif","dea","macd") else {}})
def provider_check(api,code,bars,asof,cal):
    # A separately generated Tushare endpoint, not independent vendor data.
    POINTS.setdefault("stk_week_month_adj",2000)
    start=str(int(asof[:4])-2)+"0101"
    for freq in ("week","month"):
        try:
            remote=api.ask("stk_week_month_adj",{"ts_code":code,"freq":freq,"start_date":start,"end_date":asof},"ts_code,trade_date,end_date,freq,close,close_qfq,close_hfq,vol")
            local={x["date"]:x for x in aggregate(bars,freq,asof,cal)}
            matches=[]
            for r in remote:
                # Reject ambiguous dates, future values and incomplete current periods.
                end=str(r.get("end_date") or r.get("trade_date") or "")
                if r.get("ts_code")!=code or r.get("freq")!=freq or end not in local or end>asof or not local[end]["complete"]:continue
                x=local[end];q=number(r["close_qfq"]);v=number(r["vol"])
                matches.append((end,x["close"],q,x["vol"],v))
            # Compare last 12 distinct completed periods, if provider dates match.
            if len({x[0] for x in matches})!=len(matches):raise ValueError("ambiguous duplicate period")
            matches=sorted(matches)[-12:]
            if not matches:
                emit("TECH_PROVIDER",{"code":code,"period":freq,"state":"no_comparable_periods","rows":len(remote)});continue
            p=[abs(a-b) for _,a,b,_,_ in matches];v=[abs(a-b) for _,_,_,a,b in matches]
            emit("TECH_PROVIDER",{"code":code,"period":freq,"state":"compared","count":len(matches),"first":matches[0][0],"last":matches[-1][0],"close_max_abs":round(max(p),6),"close_mean_abs":round(fmean(p),6),"close_within_002":sum(x<=.02000001 for x in p),"volume_max_abs_hands":round(max(v),3),"volume_within_one_hand":sum(x<=1 for x in v)})
        except Exception as e:emit("TECH_PROVIDER",{"code":code,"period":freq,"state":"unavailable","reason":type(e).__name__})
def historical_checks(api,code,raw,factors):
    # Two earlier as-of dates chosen in advance, with proper historical anchor.
    for asof in ("20261030","20261120"):
        try:
            cal=calendar(api,asof)
            hist=normalize([x for x in raw if x["trade_date"]<=asof],[x for x in factors if x["trade_date"]<=asof],code,asof)
            gs=groups(hist,asof,cal)
            emit("TECH_HISTORICAL",{"code":code,"asof":asof,"state":"ok","counts":{k:len(v) for k,v in gs.items()},"last_date":hist[-1]["date"],"raw_anchor_match":abs(hist[-1]["close"]-number(next(x["close"] for x in raw if x["trade_date"]==asof)))<1e-8,"week_complete":gs["week"][-1]["complete"],"month_complete":gs["month"][-1]["complete"],"indicator_coverage":{k:sum(x is not None for x in indicators(v,k).values()) for k,v in gs.items()}})
        except Exception as e:emit("TECH_HISTORICAL",{"code":code,"asof":asof,"state":"unavailable","reason":type(e).__name__})
