"""Read-only Tushare data layer, no raw data published."""
import sys
from pathlib import Path
from datetime import datetime,timedelta
from .indicators import normalize,aggregate,indicators,risk_features,relative_strength,number,date,directions
from .quality import QualityHistory,public_summary,WARMUP
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"scripts"))
from tushare_5000 import Tushare
FIELDS="ts_code,trade_date,open,high,low,close,vol,amount"
INDEXES={"000001.SH":"上证指数","000300.SH":"沪深300","000905.SH":"中证500","000852.SH":"中证1000","932000.CSI":"中证2000"}
def chunks(start,end,years=3):
    for y in range(int(start[:4]),int(end[:4])+1,years):
        yield max(start,str(y)+"0101"),min(end,str(y+years-1)+"1231")
def series(api,endpoint,code,start,end,fields):
    rows=[]
    for a,b in chunks(start,end):
        batch=api.ask(endpoint,{"ts_code":code,"start_date":a,"end_date":b},fields)
        # Boundaries and duplicate validation are separate from provider ordering.
        if any(not a<=str(r.get("trade_date",""))<=b for r in batch):raise ValueError("response outside requested window")
        rows.extend(batch)
    return rows
def calendar(api,asof):
    d=datetime.strptime(asof,"%Y%m%d")
    lo=d.replace(day=1)-timedelta(days=7);hi=d+timedelta(days=35)
    rows=api.ask("trade_cal",{"exchange":"SSE","start_date":lo.strftime("%Y%m%d"),"end_date":hi.strftime("%Y%m%d")},"cal_date,is_open")
    days={date(r["cal_date"]):str(r["is_open"]) for r in rows}
    if len(days)!=(hi-lo).days+1 or len(rows)!=len(days) or any(v not in ("0","1") for v in days.values()):raise ValueError("calendar incomplete")
    if days.get(asof)!="1":raise ValueError("target is not an exchange trading day")
    return [d for d,v in sorted(days.items()) if v=="1"]
def stock_history(api,code,asof,details=False,audit_fields=False):
    r=api.ask("stock_basic",{"ts_code":code,"list_status":"L"},"ts_code,list_date")
    exact=[x for x in r if x.get("ts_code")==code]
    if len(exact)!=1:raise ValueError("listing date unavailable")
    start=date(exact[0]["list_date"])
    bars=series(api,"daily",code,start,asof,FIELDS+(",pre_close,pct_chg,ah_vol,ah_amount" if audit_fields else ""))
    fs=series(api,"adj_factor",code,start,asof,"ts_code,trade_date,adj_factor")
    result=normalize(bars,fs,code,asof)
    return (result,start,bars,fs) if details else (result,start)
def benchmarks(api,asof):
    out={}
    for code in INDEXES:
        try:
            # Enough history for RS60 and daily MA250; keep requests bounded.
            rows=series(api,"index_daily",code,str(int(asof[:4])-2)+"0101",asof,FIELDS)
            out[code]=normalize(rows,None,code,asof)
        except Exception:
            # Missing index must never be silently replaced with a different benchmark.
            out[code]=None
    return out
def build(api,code,asof,cal,indices,history=None):
    if history is None:
        _,start,raw,factors=stock_history(api,code,asof,details=True,audit_fields=True)
    else:
        raw,factors,start=history
    q=QualityHistory(raw,factors,code,asof);view=q.view(asof,cal)
    groups={k:v["bars"] for k,v in view["groups"].items()};bars=groups["day"]
    features=risk_features(bars) if bars else {}
    if view["last_major"] and len(bars)<WARMUP:
        for k in ("atr14","atr14_pct"):
            if k in features:features[k]=None
    missing=len(set(d for d in cal if q.dates[0]<=d<=asof)-set(q.dates))
    daily_basic=api.ask("daily_basic",{"ts_code":code,"trade_date":asof},"ts_code,trade_date,turnover_rate,volume_ratio")
    exact=[r for r in daily_basic if r.get("ts_code")==code and r.get("trade_date")==asof]
    basic={k:number(exact[0][k]) if len(exact)==1 and exact[0].get(k) is not None else None for k in ("turnover_rate","volume_ratio")}
    return {"asof":asof,"code":code,"listing_date":start,"first_bar":q.dates[0],
            "counts":{k:len(v) for k,v in groups.items()},
            "completed":{"day":bool(bars),**{k:groups[k][-1]["complete"] if groups[k] else False for k in ("week","month")}},
            "indicators":{k:v["indicators"] for k,v in view["groups"].items()},
            "directions":{k:v["directions"] for k,v in view["groups"].items()},
            "signals":{k:v["signals"] for k,v in view["groups"].items()},
            "features":features,"daily_basic":basic,
            "relative_strength":{k:{str(n):relative_strength(bars,v,n) if v and bars else None for n in (5,20,60)} for k,v in indices.items()},
            "data_quality":public_summary(view),"missing_recent_sessions":missing,
            "minutes":{"state":"disabled_by_scope","reason":"no paid minute data"}}
