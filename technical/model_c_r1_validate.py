"""Fixed nine historical samples, actual A/C baselines and exact prefix comparison."""
import os
from .data import Tushare,stock_history,benchmarks
from .quality import QualityHistory
from .model_a import analyze
from .model_b import attach
from .model_b_data import prefix
from .model_a_validate import sessions_for
from .model_c import location_c
from .model_c_r1 import analyze_r1
from .diagnostics import emit

def baseline(l):
    return {k:l.get(k) for k in ("support","resistance","invalidation","target_reference","reward_risk","risk_fraction","flags","risk_veto")}
def compact(l):
    out=baseline(l)
    out.update({k:l.get(k) for k in ("atr14","atr_frequency","distance_cap","target_status","state","nearest_support_obstacle","at_price")})
    for side in ("support","resistance"):
        out["remote_"+side]=[{k:x[k] for k in ("low","high","grade","last_confirmation","frequencies")} for x in l.get("remote_"+side,[])]
    return out
def main():
    api=Tushare(os.environ["TUSHARE_TOKEN"]);end="20261127";sessions=sessions_for(api,end);idx=benchmarks(api,end)
    snapshots={"20261030":(0,1,1.5,99.328),"20261120":(0,.5,1.5,99.361),"20261127":(1,1.5,3.5,99.386)}
    for code in ("002475.SZ","600000.SH","300750.SZ"):
        _,_,raw,fs=stock_history(api,code,end,details=True,audit_fields=True);q=QualityHistory(raw,fs,code,end)
        for d,ss in snapshots.items():
            a=analyze(q,d,sessions,{k:prefix(v,d) for k,v in idx.items()})
            ctx=[{"asof":d,"score":s,"coverage":ss[3] if i==1 else 100} for i,s in enumerate(ss[:3])]
            b=attach(a,*ctx,{"ready":False})
            c=location_c(q,d,sessions);r=analyze_r1(q,b,sessions)
            qt=QualityHistory([x for x in raw if x["trade_date"]<=d],[x for x in fs if x["trade_date"]<=d],code,d)
            assert r==analyze_r1(qt,b,sessions),"prefix mismatch"
            assert r["direction_scores"]==a["horizons"]
            assert r["plan"]["new_exposure"]=="defensive_no_new_exposure" and r["probability"] is None
            for h,l in r["locations"].items():
                if l.get("reward_risk") is not None:
                    assert 0<l["target_reference"]-l["price"]<=l["distance_cap"]+1e-8
                    assert 0<l["price"]-l["invalidation"]<=l["distance_cap"]+1e-8
                    assert abs(l["reward_risk"]-(l["target_reference"]-l["price"])/(l["price"]-l["invalidation"]))<1e-8
                assert l.get("target_reference") is None or l["resistance"]["grade"] in ("A","B")
                if l.get("invalidation") is not None:assert l["support"]["touches"]>=1
                assert all("month" not in z["frequencies"] for side in ("support","resistance") for z in l.get("zones",{}).get(side,[]))
            emit("TECH_MODEL_C_R1_SAMPLE",{"code":code,"asof":d,"price":a["location"]["price"],"A":baseline(a["location"]),"C":baseline(c),
                 "short":compact(r["locations"]["short"]),"medium":compact(r["locations"]["medium"]),
                 "tracking":r["trend_tracking"],"plan":r["plan"],"prefix_match":True,"scores_unchanged":True,
                 "context_source":"accepted_B_scores_veto_only","coverage":r["coverage"]})
if __name__=="__main__":main()
