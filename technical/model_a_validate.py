"""Read-only actual samples, derived output only. No raw prices or private pool."""
import os,json
from datetime import datetime,timedelta
from .data import Tushare,stock_history,benchmarks
from .indicators import date
from .quality import QualityHistory
from .model_a import analyze
from .diagnostics import emit

def sessions_for(api,asof):
    t=datetime.strptime(asof,"%Y%m%d");lo=t-timedelta(days=730);hi=t+timedelta(days=35)
    rows=api.ask("trade_cal",{"exchange":"SSE","start_date":lo.strftime("%Y%m%d"),"end_date":hi.strftime("%Y%m%d")},"cal_date,is_open")
    days={date(r["cal_date"]):str(r["is_open"]) for r in rows}
    if len(rows)!=len(days) or len(days)!=(hi-lo).days+1 or min(days)!=lo.strftime("%Y%m%d") or max(days)!=hi.strftime("%Y%m%d") or any(v not in ("0","1") for v in days.values()) or days.get(asof)!="1":raise RuntimeError("calendar completeness")
    return sorted(d for d,v in days.items() if v=="1")
def summarize(r):
    return {"code":r["code"],"asof":r["asof"],"quality":r["quality"]["state"],"ready":r["composite_ready"],
      "cycles":{k:{x:y for x,y in v.items() if x in ("T","M","trend","provisional","latest_completed_date")} for k,v in r["cycles"].items()},
      "horizons":{k:{"T":v["T"],"M":v["M"],"V":v["V"]["V"],"R":v["R"]["R"],"coverage":v["R"]["coverage"],"D":v["D"],"direction":v["direction"],"volume_date":v["V"].get("date")} for k,v in r["horizons"].items()},
      "alignment":r["alignment"],"medium_structure":r["medium_structure"],"reversal":r["weekly_reversal"],
      "location":{"state":r["location"]["state"],"flags":r["location"].get("flags"),"rr":r["location"].get("reward_risk")},
      "action":r["action"],"probability":r["probability"]}
def check_report(r):
    assert r["probability"] is None and r["action"].startswith("evidence_insufficient")
    for h in r["horizons"].values():
        if h["D"] is not None:
            assert -100<=h["D"]<=100
            assert abs(h["D"]-(.55*h["T"]+.20*h["M"]+.10*h["V"]["V"]+.15*h["R"]["R"]))<1e-8
        else:assert h["direction"]=="unknown"
    for c in r["cycles"].values():
        assert c["latest_completed_date"] is None or c["latest_completed_date"]<=r["asof"]
    assert all(d<=r["asof"] for d in r["weekly_reversal"]["completed_dates"])
def main():
    api=Tushare(os.environ["TUSHARE_TOKEN"]);asof="20261127";sessions=sessions_for(api,asof);idx=benchmarks(api,asof)
    for code in ("002475.SZ","600000.SH","300750.SZ"):
        _,_,raw,factors=stock_history(api,code,asof,details=True,audit_fields=True)
        q=QualityHistory(raw,factors,code,asof)
        for d in ("20261030","20261120",asof):
            ix={k:[b for b in v if b["date"]<=d] if v else None for k,v in idx.items()}
            r=analyze(q,d,sessions,ix);check_report(r)
            # Rebuild an independent truncated object from source prefix, then exact
            # compare all derived outputs; future event or factor must not leak.
            qt=QualityHistory([x for x in raw if x["trade_date"]<=d],[x for x in factors if x["trade_date"]<=d],code,d)
            assert r==analyze(qt,d,sessions,ix),"prefix mismatch"
            emit("TECH_MODEL_A_SAMPLE",summarize(r))
            if not r["composite_ready"]:raise RuntimeError("sample composite unavailable")
        # Negative checks: stale broad benchmark and inadequate coverage must suppress composite.
        stale={k:v[:-1] if v else None for k,v in idx.items()}
        z=analyze(q,asof,sessions,stale);assert not z["composite_ready"] and all(h["D"] is None for h in z["horizons"].values())
        emit("TECH_MODEL_A_GUARDS",{"code":code,"prefix_checks":3,"stale_benchmark_rejected":True})
if __name__=="__main__":main()
