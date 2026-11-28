"""E1 R1 isolated input handling. No frozen normalization changes, no fill/drop."""
import time,json
from pathlib import Path
from collections import Counter,defaultdict
from .model_e0 import digest,QualityHistory,date,series,FIELDS
from .e0_r3_store import Ledger,atomic
from .data import Tushare
from tushare_5000 import SafeAPIError

OLD_SHA="3e866811dc7517a6a015900bb5f54cfa62776a14"
DATA_ERRORS=(ValueError,TypeError,KeyError,OverflowError)

def fetch_raw(api,k,interval,cutoff):
    start,end=interval;stop=min(cutoff,end) if end else cutoff
    raw=series(api,"daily",k,start,stop,FIELDS+",pre_close,pct_chg,ah_vol,ah_amount")
    fs=series(api,"adj_factor",k,start,stop,"ts_code,trade_date,adj_factor")
    return raw,fs

def audited(raw,fs,k):
    if not raw:raise ValueError("no daily bars")
    last=max(date(r["trade_date"]) for r in raw)
    return QualityHistory(raw,[r for r in fs if r["trade_date"]<=last],k,last)

def diagnosis(raw,fs,k):
    # Only field names, dates and counts, not source prices/amounts.
    from .indicators import normalize
    problems=[];fm=defaultdict(list);rm=defaultdict(list)
    for r in fs:fm[r.get("trade_date")].append(r)
    for r in raw:rm[r.get("trade_date")].append(r)
    for d,rs in rm.items():
        if not isinstance(d,str):problems.append({"date":None,"reason":"invalid_date","fields":[]});continue
        fields=sorted(f for f in ("open","high","low","close","vol","amount") if rs[0].get(f) is None)
        try:normalize(rs,fm.get(d,[]),k,d)
        except DATA_ERRORS as e:
            problems.append({"date":d,"reason":type(e).__name__,"fields":fields})
    # Even unused factor records within prefix must pass frozen unique validation.
    for d,rs in fm.items():
        if len(rs)>1 or any(r.get("ts_code")!=k for r in rs):
            problems.append({"date":d if isinstance(d,str) else None,"reason":"factor_identity_or_duplicate","fields":["adj_factor"]})
    return sorted(problems,key=lambda x:(x["date"] or "",x["reason"]))

def load_stock(api,k,interval,cutoff):
    errors=[];raw=[];fs=[]
    for attempt in range(2):
        try:
            raw,fs=fetch_raw(api,k,interval,cutoff)
            q=audited(raw,fs,k)
            return q,{"state":"ok","attempts":attempt+1,"prior_errors":errors,"source":digest([q.raw,q.factors])}
        except SafeAPIError as e:
            errors.append({"type":type(e).__name__,"state":"source_unavailable"})
        except DATA_ERRORS as e:
            errors.append({"type":type(e).__name__,"state":"data_quality","problems":diagnosis(raw,fs,k)[:20]})
        if attempt==0:time.sleep(.65)
    if errors[-1]["state"]=="source_unavailable":
        return None,{"state":"source_unavailable","attempts":2,"prior_errors":errors,"source":None}
    problems=diagnosis(raw,fs,k)
    bad=[x["date"] for x in problems if x["date"] is not None]
    first=min(bad) if bad and all(x["date"] is not None for x in problems) else None
    prefix=None
    if first:
        try:prefix=audited([r for r in raw if r["trade_date"]<first],[r for r in fs if r["trade_date"]<first],k)
        except DATA_ERRORS:pass
    return prefix,{"state":"data_quality","attempts":2,"prior_errors":errors,"first_invalid":first,
        "problem_count":len(problems),"problems":problems[:20],"source":digest([raw,fs]),"observed_dates":sorted({r["trade_date"] for r in raw if isinstance(r.get("trade_date"),str)})}

class AuditLedger(Ledger):
    def read(self,code,source):
        f=self.file(code)
        if not f.exists():return None
        try:
            row=json.loads(f.read_text());r=row["result"];c=r["counts"]
            if row["schema"]!=1 or row["identity"]!=self.identity or row["source"]!=source or row["code"]!=code or digest(r)!=row["digest"]:return None
            if c["planned"]!=sum(c.get(k,0) for k in ("computed","not_observed","data_quality_blocked","source_unavailable")):return None
            return r
        except (ValueError,TypeError,KeyError,OSError):return None

def legacy_hit(ledger,k,source,dates,weekly,daily):
    r=ledger.read(k,source)
    if r is None:return None
    c=r["counts"]
    expected={"core":sum(d in weekly for d in dates),"daily":len(dates) if daily else 0,"overlap":sum(d in weekly for d in dates) if daily else 0,"unique":len(dates)}
    if c["planned"]!=len(dates) or any(r["panels"].get(p,{}).get("planned",0)!=n for p,n in expected.items()):return None
    if r["panels"]["unique"]!=c or r["paired_checks"]!=r["prefix_checks"]:return None
    return r

