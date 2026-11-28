"""Read-only calendar boundary diagnosis. No model outputs or raw stock rows."""
import os
from collections import Counter
from datetime import datetime,timedelta
from .data import Tushare
from .model_b_data import universe_history
from .diagnostics import emit

def inspect(api,exchange,lo,hi):
    a=datetime.strptime(lo,"%Y%m%d");b=datetime.strptime(hi,"%Y%m%d")
    exp={(a+timedelta(days=i)).strftime("%Y%m%d") for i in range((b-a).days+1)}
    try:
        rows=api.ask("trade_cal",{"exchange":exchange,"start_date":lo,"end_date":hi},"cal_date,is_open")
        ds=Counter(str(r.get("cal_date","")) for r in rows)
        missing=sorted(exp-set(ds));extra=sorted(set(ds)-exp)
        bad=sum(str(r.get("is_open")) not in ("0","1") for r in rows)
        dup=sum(n-1 for n in ds.values())
        info={"exchange":exchange,"start":lo,"end":hi,"expected":len(exp),"returned":len(rows),"unique":len(ds),"first":min(ds) if ds else None,"last":max(ds) if ds else None,"missing":len(missing),"missing_first":missing[:5],"missing_last":missing[-5:],"extra":len(extra),"extra_examples":extra[:5],"duplicates":dup,"invalid_status":bad}
        info["complete"]=not(missing or extra or dup or bad)
        return info,{str(r["cal_date"]) for r in rows if str(r.get("is_open"))=="1" and str(r.get("cal_date")) in exp}
    except Exception as e:return {"exchange":exchange,"start":lo,"end":hi,"complete":False,"error_type":type(e).__name__},set()

def main():
    api=Tushare(os.environ["TUSHARE_TOKEN"]);u=universe_history(api)
    earliest=min(a for a,b in u.values())
    emit("TECH_E0_CAL_DIAG_START",{"earliest_listing":earliest,"universe_count":len(u)})
    bad=[];opens={}
    for exchange in ("SSE","SZSE"):
        opens[exchange]=set()
        for y in range(int(earliest[:4]),2027):
            lo=max(earliest,str(y)+"0101");hi=str(y)+"1231"
            r,ds=inspect(api,exchange,lo,hi);opens[exchange].update(ds)
            emit("TECH_E0_CAL_DIAG_YEAR",r)
            if not r["complete"]:bad.append(r)
    # Last 121 completed months for post-major warmup and full preceding
    # period boundaries may extend to 2012. This is a diagnostic slice only.
    recent_bad=[r for r in bad if r["end"]>="20120101"]
    dif=sorted((opens["SSE"]^opens["SZSE"]) & {d for x in opens.values() for d in x if "20120101"<=d<="20261231"})
    emit("TECH_E0_CAL_DIAG_SUMMARY",{"bad_years":bad,"bad_since_2012":recent_bad,"exchange_open_date_differences_since_2012":len(dif),"difference_examples":dif[:10],"api_counts":api.counts,"diagnostic_only":True})
if __name__=="__main__":main()
