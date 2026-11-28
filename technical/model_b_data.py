"""Read-only point-in-time market/sector input adapter; no raw licensed data saved."""
from .data import series,FIELDS
from .indicators import date,number,normalize
from .model_b import eligible_at
from tushare_5000 import POINTS
def membership_rows(api,code):
    POINTS.setdefault("index_member_all",2000)
    rows=[]
    for flag in ("Y","N"):
        r=api.ask("index_member_all",{"ts_code":code,"is_new":flag},"ts_code,l1_code,l1_name,l2_code,l3_code,in_date,out_date,is_new")
        if len(r)>=2000:raise ValueError("membership truncated")
        rows.extend(r)
    return rows
def taxonomy(api):
    rows=api.ask("index_classify",{"level":"L1","src":"SW2021"},"index_code,industry_name,level,is_pub,src")
    out={}
    for r in rows:
        if r.get("src")!="SW2021" or r.get("level")!="L1" or str(r.get("is_pub")) not in ("1","True"):continue
        k=str(r["index_code"]).split(".")[0]+".SI"
        if k in out:raise ValueError("duplicate sector")
        out[k]=r["industry_name"]
    if len(out)!=31:raise ValueError("SW2021 taxonomy coverage")
    return out
def close_series(rows,code,start,end):
    m={}
    for r in rows:
        d=date(str(r["trade_date"]));c=number(r["close"])
        if r.get("ts_code")!=code or not start<=d<=end or d in m or c<=0:raise ValueError("invalid index series")
        m[d]={"date":d,"close":c}
    return [m[d] for d in sorted(m)]
def sector_series(api,sectors,start,end):
    out={}
    for code in sectors:
        try:
            rows=series(api,"sw_daily",code,start,end,"ts_code,trade_date,close")
            out[code]=close_series(rows,code,start,end)
        except Exception:out[code]=None
    return out
def universe_history(api):
    # L, D and P separately; never substitute current L for historical universe.
    out={}
    for status in ("L","D","P"):
        rows=api.ask("stock_basic",{"list_status":status},"ts_code,list_date,delist_date,list_status")
        if (not rows and status in ("L","D")) or len(rows)>=6000:raise ValueError("universe query empty or truncated")
        for r in rows:
            k=str(r.get("ts_code",""))
            if not k.endswith((".SH",".SZ")):continue
            if r.get("list_status")!=status:raise ValueError("universe status mismatch")
            start=date(str(r["list_date"]));end=date(str(r["delist_date"])) if r.get("delist_date") not in (None,"") else None
            if status=="D" and not end:raise ValueError("delist date missing")
            if end and end<=start:raise ValueError("invalid list interval")
            if k in out and out[k]!=(start,end):raise ValueError("conflicting universe record")
            out[k]=(start,end)
    return out
def cross_section(rows,d,fields):
    out={}
    for r in rows:
        k=str(r.get("ts_code",""))
        if not k.endswith((".SH",".SZ")):continue
        if r.get("trade_date")!=d or k in out:raise ValueError("cross section date or duplicate")
        try:vals=tuple(number(r[f]) for f in fields)
        except (ValueError,TypeError,KeyError):continue
        out[k]=vals
    return out
def cross_sections(api,dates,universe):
    prices={};factors={};changes={};issues={}
    for d in dates:
        try:
            raw=api.ask("daily",{"trade_date":d},"ts_code,trade_date,close,pct_chg")
            fs=api.ask("adj_factor",{"trade_date":d},"ts_code,trade_date,adj_factor")
            # Coverage measured against reconstructed eligible universe, not returned row count.
            r=cross_section(raw,d,("close","pct_chg"));f=cross_section(fs,d,("adj_factor",))
            prices[d]={k:v[0] for k,v in r.items() if v[0]>0}
            changes[d]={k:v[1] for k,v in r.items()}
            factors[d]={k:v[0] for k,v in f.items() if v[0]>0}
        except Exception as e:issues[d]=type(e).__name__
    return prices,factors,changes,issues
def turnover_series(api,start,end):
    out={}
    for k in ("000001.SH","399107.SZ"):
        try:out[k]=normalize(series(api,"index_daily",k,start,end,FIELDS),None,k,end)
        except Exception:out[k]=None
    return out
def prefix(rows,d):return [r for r in rows if r["date"]<=d] if rows else None
