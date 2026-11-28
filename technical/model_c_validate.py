"""Actual fixed samples and causal event scan; no raw licensed rows persisted."""
import os
from collections import Counter
from .data import Tushare,stock_history,benchmarks
from .quality import QualityHistory
from .model_a import analyze
from .model_b import attach
from .model_b_data import prefix
from .model_a_validate import sessions_for
from .model_c import attach_c,location_c,breakout_events,completed_bars,contiguous_tail,atr_series
from .diagnostics import emit

def main():
    api=Tushare(os.environ["TUSHARE_TOKEN"]);end="20261127";sessions=sessions_for(api,end);idx=benchmarks(api,end)
    # Reuse the exact accepted B historical market snapshot summaries only for
    # veto regression, not claim a new B source validation. No fabricated user permission.
    # Industry readiness is intentionally unknown here; full integration follows D.
    baseline={"20261030":(0,1,1.5,99.328),"20261120":(0,.5,1.5,99.361),"20261127":(1,1.5,3.5,99.386)}
    for code in ("002475.SZ","600000.SH","300750.SZ"):
        _,_,raw,fs=stock_history(api,code,end,details=True,audit_fields=True);q=QualityHistory(raw,fs,code,end)
        for d,ss in baseline.items():
            a=analyze(q,d,sessions,{k:prefix(v,d) for k,v in idx.items()})
            ctx=[{"asof":d,"score":s,"coverage":ss[3] if i==1 else 100} for i,s in enumerate(ss[:3])]
            b=attach(a,*ctx,{"ready":False})
            c=attach_c(q,b,sessions)
            qt=QualityHistory([r for r in raw if r["trade_date"]<=d],[r for r in fs if r["trade_date"]<=d],code,d)
            assert c["location"]==location_c(qt,d,sessions),"historical prefix mismatch"
            assert c["horizons"]==a["horizons"] and c["plan"]["new_exposure"]=="defensive_no_new_exposure"
            l=c["location"];z=l.get("zones",{})
            def compact(x):
                return {k:v for k,v in x.items() if k!="evidence"} if x else None
            emit("TECH_MODEL_C_SAMPLE",{"code":code,"asof":d,"short_D":c["horizons"]["short"]["D"],"medium_D":c["horizons"]["medium"]["D"],
                "baseline_rr":a["location"].get("reward_risk"),"price":l.get("price"),"atr":l.get("atr14"),"support":compact(l.get("support")),"resistance":compact(l.get("resistance")),
                "support_count":len(z.get("support",[])),"resistance_count":len(z.get("resistance",[])),"rejected":dict(Counter(x["reason"] for x in z.get("rejected",[]))),
                "rr":l.get("reward_risk"),"flags":l.get("flags"),"breakouts":l.get("breakouts"),"plan":c["plan"],"context_source":"accepted_B_scores_veto_only"})
        # Fixed latest 120 exchange sessions; use guarded prefixes for observed
        # event dates, not search future returns. This is coverage not prediction.
        # Use daily event state only to keep runtime bounded.
        counts=Counter();examples={};seen=set()
        for d in [x for x in sessions if x<=end][-120:]:
            if d not in q.dates:continue
            v=q.view(d,sessions);bs=contiguous_tail(completed_bars(v,"day",sessions),"day",sessions,d)
            full=v["groups"]["day"]["bars"];av=atr_series(full)
            for e in breakout_events(bs,"day",bool(v["last_major"]),av[-len(bs):] if bs else [],len(full)-len(bs)):
                if e["event_date"]!=d:continue
                key=(e["direction"],e["lookback"],e["formation_date"],e["state"],d)
                if key in seen:continue
                seen.add(key);counts[e["state"]]+=1;examples.setdefault(e["state"],e)
        emit("TECH_MODEL_C_EVENTS",{"code":code,"window":120,"counts":dict(counts),"examples":examples})
if __name__=="__main__":main()
