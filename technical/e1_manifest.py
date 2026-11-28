"""E1 phase 1: deterministic pre-outcome sampling manifest, no returns or scoring."""
import os,time,json
from collections import Counter,defaultdict
from pathlib import Path
from .model_e0 import END,SEED,EXCLUDED,common_calendar,board,strata,draw,digest
from .model_b_data import universe_history,eligible_at,cross_section
from .indicators import period
from .data import Tushare
from .diagnostics import emit
from .e0_r3_store import atomic

START="20230101"
HORIZONS=(1,5,10,20,40)
SPLITS={"development":("20230101","20241231"),"validation":("20250101","20251231"),"test":("20260101",END)}
ENGINE="a4e103d5e29c76636fe68c91c433455ff9c45c88"
PLAN="4ac5be7eed2761dc0f5839d828904c69fda270b2"
def quarter(d):return d[:4]+"Q"+str((int(d[4:6])-1)//3+1)
def split(d):
    matches=[k for k,(a,b) in SPLITS.items() if a<=d<=b]
    if len(matches)!=1:raise ValueError("outside research partitions")
    return matches[0]
def schedule(cal):
    if not cal or cal!=sorted(set(cal)):raise ValueError("invalid calendar")
    study=[d for d in cal if START<=d<=END]
    if not study or study[-1]!=END:raise ValueError("missing study cutoff")
    ix={d:i for i,d in enumerate(cal)}
    last={k:max(d for d in study if split(d)==k) for k in SPLITS}
    # Full actual exchange weeks, never use a quarter-end partial week.
    week_ends={period(d,"week"):d for d in cal}
    q=defaultdict(list)
    for d in study:
        name=split(d);i=ix[d];boundary=ix[last[name]]
        labels={str(h):cal[i+h] if i+h<=boundary else None for h in HORIZONS}
        q[quarter(d)].append({"date":d,"split":name,"weekly":week_ends[period(d,"week")]==d,
             "purged":i+40>boundary,"label_end_by_horizon":labels})
    return dict(q),last
def sampling(universe,first,amounts,key):
    eligible=eligible_at(universe,first)
    groups=strata(universe,first,amounts,key)
    core=draw(groups,240,key);daily=draw(core,60,key+"|daily")
    a={c for v in core.values() for c in v};b={c for v in daily.values() for c in v}
    expected={c for c in eligible-EXCLUDED if board(c)}
    if a&EXCLUDED or not b<=a or not a<=expected or len(a)!=min(240,len(expected)) or len(b)!=min(60,len(a)):raise ValueError("sampling invariant")
    if {c for v in groups.values() for c in v}!=expected:raise ValueError("stratum denominator mismatch")
    return {"eligible_sh_sz_count":len(eligible),"board_scope_count":len(expected),
            "excluded_engineering_count":len(eligible&EXCLUDED),"unsupported_board_count":len(eligible-EXCLUDED-expected),
            "universe_digest":digest(sorted(expected)),"stratum_sizes":{k:len(v) for k,v in sorted(groups.items())},
            "core":core,"daily":daily}
def panel_counts(rows,ncore,ndaily):
    out={}
    for name,n,dates in (("core",ncore,[r for r in rows if r["weekly"]]),("daily",ndaily,rows)):
        out[name]={"planned":n*len(dates),"purged":n*sum(r["purged"] for r in dates),
                   "after_purge":n*sum(not r["purged"] for r in dates)}
    # Daily panel is strictly nested in core on all weekly observation dates.
    out["overlap"]={"planned":ndaily*sum(r["weekly"] for r in rows),
                    "after_purge":ndaily*sum(r["weekly"] and not r["purged"] for r in rows)}
    return out
def main():
    start=time.perf_counter();api=Tushare(os.environ["TUSHARE_TOKEN"])
    universe=universe_history(api);cal=common_calendar(api);qs,last=schedule(cal)
    if len(qs)!=16 or sum(map(len,qs.values()))!=945:raise ValueError("study calendar changed")
    manifest={"schema":1,"engine":ENGINE,"plan":PLAN,"seed":SEED,"start":START,"end":END,"splits":SPLITS,
              "split_last_sessions":last,"purge_sessions":40,"excluded":sorted(EXCLUDED),"calendar_digest":digest(cal),
              "reconstructed_universe_count":len(universe),"universe_snapshot_digest":digest(sorted(universe.items())),
              "quarters":{},"provider_reconstructed_not_vintage":True,"no_outcomes":True}
    totals={k:{p:Counter() for p in ("core","daily","overlap")} for k in SPLITS}
    for key,rows in qs.items():
        first=rows[0]["date"];prior=[d for d in cal if d<first][-20:]
        if len(prior)!=20:raise ValueError("missing trailing window")
        amounts={};coverage={}
        for d in prior:
            eligible=eligible_at(universe,d)
            raw=api.ask("daily",{"trade_date":d},"ts_code,trade_date,amount")
            vals={k:v[0] for k,v in cross_section(raw,d,("amount",)).items() if v[0]>0}
            ratio=len(set(vals)&eligible)/len(eligible) if eligible else 0
            if ratio<.85:raise ValueError("liquidity coverage below frozen threshold "+d)
            amounts[d]=vals;coverage[d]={"eligible":len(eligible),"positive":len(set(vals)&eligible)}
        m=sampling(universe,first,amounts,key)
        # Independent deterministic replay under reversed dictionary insertion order.
        replay=sampling(dict(reversed(list(universe.items()))),first,dict(reversed(list(amounts.items()))),key)
        if digest(m)!=digest(replay):raise ValueError("sampling replay mismatch")
        ncore=sum(map(len,m["core"].values()));ndaily=sum(map(len,m["daily"].values()))
        counts=panel_counts(rows,ncore,ndaily)
        for p,c in counts.items():totals[rows[0]["split"]][p].update(c)
        m.update(first=first,prior_sessions=prior,liquidity_coverage=coverage,liquidity_input_digest=digest(amounts),dates=rows,counts=counts)
        manifest["quarters"][key]=m
        emit("TECH_E1_QUARTER",{"quarter":key,"first":first,"core":ncore,"daily":ndaily,"strata":m["stratum_sizes"],
             "counts":counts,"digest":digest(m),"min_liquidity_coverage":min(v["positive"]/v["eligible"] for v in coverage.values()),"elapsed_seconds":round(time.perf_counter()-start,2)})
    manifest["totals_by_split"]={k:{p:dict(c) for p,c in x.items()} for k,x in totals.items()}
    manifest["digest"]=digest(manifest)
    atomic(Path("e1-manifest")/"sample-manifest.json",manifest)
    emit("TECH_E1_MANIFEST_DONE",{"quarters":len(qs),"study_sessions":sum(map(len,qs.values())),"totals_by_split":manifest["totals_by_split"],
         "digest":manifest["digest"],"api_counts":api.counts,"elapsed_seconds":round(time.perf_counter()-start,2),
         "feature_compute_started":False,"no_outcomes":True,"raw_market_rows_persisted":False})
if __name__=="__main__":main()
