"""E1.2A full fixed 2023Q1 panel, admission audit only. R3 engine imports unchanged.
No price/return/features written to public artifacts; aggregate per-stock ledgers only.
"""
import os,time,multiprocessing,sys,math
from collections import Counter,defaultdict
from statistics import pstdev
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from .model_e0 import *
from .e1_freeze_manifest import verify,EXPECTED
from .e1_manifest import schedule
from .model_e0_validate import context_sources
from .model_b_data import universe_history,membership_rows,cross_sections,prefix
from .model_b import market_trend,stock_breadth,sector_breadth,participation,combine_breadth,activity
from .e0_r2_acceleration import acceleration,evaluate
from .e0_r3_index import CalendarIndex,indexed
from .e0_r3_store import Ledger,atomic
from .data import Tushare
from .diagnostics import emit
from .e1_q1_r2 import R1_SHA,validate_stock,validate_panels,checkpoint_hit,stock_event,report_dimensions
from .e1_q1_r1 import load_stock,AuditLedger,legacy_hit,OLD_SHA
from .model_b import point_membership
from tushare_5000 import SafeAPIError
CTX=None
def population_vol(u,prices,factors,cal,d):
    # Predeclared descriptive tertile: all then-eligible shares with exact 21 observed
    # adjusted daily closes; same 20 log returns and annualization as foundation.
    w=cal[cal.index(d)-20:cal.index(d)+1];vals=[]
    for k in sorted(eligible_at(u,d)):
        if len(w)!=21:continue
        x=[prices.get(t,{}).get(k) for t in w];f=[factors.get(t,{}).get(k) for t in w]
        if not all(v is not None and v>0 for v in x+f):continue
        p=[a*b/f[-1] for a,b in zip(x,f)]
        vals.append((pstdev([math.log(b/a) for a,b in zip(p,p[1:])])*math.sqrt(252)*100,k))
    return {k:("low","mid","high")[min(2,3*i//len(vals))] for i,(_,k) in enumerate(sorted(vals))}
def count_row(c,r=None,reason=None):
    c["planned"]+=1
    if r is None:c["not_observed"]+=1;c[reason]+=1;return
    c["computed"]+=1
    v,a,b,z=r["view"],r["A"],r["B"],r["C"]
    ready=v["combined_feature_ready"];scored=a["composite_ready"]
    strict=all(x["state"]=="complete" for x in r["coverage"].values())
    ctx=b["market_industry_context"]
    c["feature_ready"]+=int(ready);c["strict_calendar_ready"]+=int(ready and strict)
    c["composite_ready"]+=int(scored);c["scored_among_feature_ready"]+=int(ready and scored)
    c["scored_among_strict_ready"]+=int(ready and strict and scored)
    c["context_ready"]+=int(all(ctx[k] for k in ("market_ready","breadth_ready","liquidity_ready","industry_ready")))
    c["major_history"]+=int(bool(v["last_major"]))
    for f,x in r["coverage"].items():c["feature_"+f+"_"+x["state"]]+=1
    for h,x in r["admission"].items():
        c["label_"+h+"_"+x["reason"]]+=1
        c["label_"+h+"_eligible"]+=int(x["eligible"])
        c["scored_label_"+h]+=int(scored and x["eligible"])
        c["strict_scored_label_"+h]+=int(ready and strict and scored and x["eligible"])
def worker(task):
    q,members,dates,weekly,group,daily,oracle,interval=task
    cal,market,tax,vols,regimes,date_meta=CTX
    ch=CachedHistory(q,cal);old=CachedHistory(q,cal);counts=Counter();panels=defaultdict(Counter);dims=defaultdict(Counter);hashes=[];checks=0;prefixes=0;elapsed=0.;stage=Counter()
    observed=set(q.dates);chosen={weekly[0],weekly[-1]} if oracle else set()
    with acceleration():
        index=CalendarIndex(cal)
        for d in dates:
            r=None;reason=None
            if d not in observed:
                reason="delisted_or_after_exit" if interval[1] and d>=interval[1] else "missing_or_suspended_observation"
            else:
                if d in chosen:ref,_=evaluate(old,d,cal,market[d],tax,members)
                t=time.perf_counter()
                with indexed(index):r,tt=evaluate(ch,d,cal,market[d],tax,members)
                elapsed+=time.perf_counter()-t;stage.update(tt)
                assert r["view"]["asof"]==d and r["A"]["code"]==q.code and r["C"]["asof"]==d
                for h,x in r["admission"].items():
                    if x.get("label_end") is not None:assert x["label_end"]==date_meta[d]["label_end_by_horizon"][h]
                    if x["eligible"]:assert x["label_end"] is not None
                if d in chosen:
                    assert ref==r and digest(ref)==digest(r),"R3 exact oracle mismatch";checks+=1
                    qt=QualityHistory([x for x in q.raw if x["trade_date"]<=d],[x for x in q.factors if x["trade_date"]<=d],q.code,d)
                    i,s,mt,br,li=market[d]
                    from .model_b import industry_context,attach
                    from .model_c_r1 import analyze_r1
                    v=qt.view(d,cal);a=analyze(qt,d,cal,i);b=attach(a,mt,br,li,industry_context(qt,d,cal,i,tax,members,s));c=analyze_r1(qt,b,cal)
                    assert (v,a,b,c)==(r["view"],r["A"],r["B"],r["C"]),"prefix oracle mismatch";prefixes+=1
                hashes.append([d,digest(r)])
            count_row(counts,r,reason)
            names=[]
            if d in weekly:names.append("core")
            if daily:names.append("daily")
            if len(names)==2:names.append("overlap")
            names.append("unique")
            industry=r["B"]["industry"]["membership"].get("code","unclassified") if r else "unclassified"
            risk=str(r["C"]["locations"]["short"].get("risk_veto")) if r else "unknown"
            age=(datetime.strptime(d,"%Y%m%d")-datetime.strptime(interval[0],"%Y%m%d")).days
            age_band="<1y" if age<365 else "1-3y" if age<1095 else "3-5y" if age<1825 else "5y+"
            for name in names:
                count_row(panels[name],r,reason)
                for kind,key in (("board",group.split("/")[0]),("liquidity",group.split("/")[1]),("industry",industry),("volatility",vols[d].get(q.code,"unknown")),("regime",regimes[d]),("risk",risk),("listing_age",age_band),("date",d)):
                    count_row(dims[name+"|"+kind+"|"+str(key)],r,reason)
    return {"counts":dict(counts),"panels":{k:dict(v) for k,v in panels.items()},"dimensions":{k:dict(v) for k,v in dims.items()},
        "output_digest":digest(hashes),"paired_checks":checks,"prefix_checks":prefixes,"compute_seconds":elapsed,"stage_seconds":dict(stage)}
def isolated_worker(task):
    q,members,dates,weekly,group,daily,oracle,interval,diag=task
    cal,market,tax,vols,regimes,date_meta=CTX
    # Only dates strictly before first invalid source row may be evaluated.
    first=diag.get("first_invalid")
    good=[d for d in dates if q is not None and first is not None and d<first]
    if good:
        out=worker((q,members,good,weekly,group,daily,oracle,interval))
    else:
        out={"counts":{},"panels":{},"dimensions":{},"output_digest":digest([]),"paired_checks":0,"prefix_checks":0,"compute_seconds":0.,"stage_seconds":{}}
    counts=Counter(out["counts"]);panels=defaultdict(Counter,{k:Counter(v) for k,v in out["panels"].items()});dims=defaultdict(Counter,{k:Counter(v) for k,v in out["dimensions"].items()})
    observed=set(diag.get("observed_dates",[]));blocked=[]
    for d in dates:
        if d in good:continue
        reason="source_unavailable" if diag["state"]=="source_unavailable" else "data_quality_blocked"
        if reason=="data_quality_blocked" and first and d not in observed and interval[1] and d>=interval[1]:reason="not_observed"
        blocked.append([d,reason])
        def add(c):
            c["planned"]+=1;c[reason]+=1
            if reason=="not_observed":c["delisted_or_after_exit"]+=1
        add(counts)
        names=["unique"]+(["core"] if d in weekly else [])+(["daily"] if daily else [])+(["overlap"] if daily and d in weekly else [])
        industry=point_membership(members,diag["code"],d,tax).get("code","unclassified")
        age=(datetime.strptime(d,"%Y%m%d")-datetime.strptime(interval[0],"%Y%m%d")).days
        age_band="<1y" if age<365 else "1-3y" if age<1095 else "3-5y" if age<1825 else "5y+"
        for name in names:
            add(panels[name])
            for kind,key in (("board",group.split("/")[0]),("liquidity",group.split("/")[1]),("industry",industry),("volatility",vols[d].get(diag["code"],"unknown")),("regime",regimes[d]),("risk","unknown"),("listing_age",age_band),("date",d)):
                add(dims[name+"|"+kind+"|"+str(key)])
    # The original prefix label gate returns future_not_available when truncated.
    # No invalid-source or missing future label is admitted. Explicitly disclose cutoff.
    out.update(counts=dict(counts),panels={k:dict(v) for k,v in panels.items()},dimensions={k:dict(v) for k,v in dims.items()},
        output_digest=digest([out["output_digest"],blocked]),quality_state=diag["state"],first_invalid=first)
    return out

def main():
    global CTX
    start=time.perf_counter();m=verify(sys.argv[1]);qm=m["quarters"]["2023Q1"];api=Tushare(os.environ["TUSHARE_TOKEN"])
    u=universe_history(api);cal=common_calendar(api)
    assert digest(cal)==m["calendar_digest"] and digest(sorted(u.items()))==m["universe_snapshot_digest"],"source snapshot drift; do not redraw"
    qs,_=schedule(cal);assert qs["2023Q1"]==qm["dates"]
    assert all(not x["purged"] for x in qm["dates"])
    qdates=[x["date"] for x in qm["dates"]];weekly=[x["date"] for x in qm["dates"] if x["weekly"]]
    group={k:s for s,ks in qm["core"].items() for k in ks};codes=sorted(group);daily={k for xs in qm["daily"].values() for k in xs}
    tasks={k:qdates if k in daily else weekly for k in codes};assert sum(map(len,tasks.values()))==5700
    assert all(k in eligible_at(u,qdates[0]) for k in codes)
    # Fixed 30 oracle symbols by hash before results; no replacement for missing data.
    oracle=set(sorted(codes,key=lambda k:digest(["E1.2A-oracle-v1",k]))[:30])
    emit("TECH_E1_AUDIT_PLAN",{"manifest":EXPECTED,"stocks":240,"daily_stocks":60,"unique":5700,"oracle_symbols":sorted(oracle)})
    tax,sw,ix,turn=context_sources(api,cal)
    lagdates=[cal[cal.index(d)-5] for d in qdates];contextdates=sorted(set(qdates+lagdates))
    needed=sorted({x for d in contextdates for x in cal[cal.index(d)-79:cal.index(d)+1]})
    prices={};factors={};changes={};issues={}
    for j in range(0,len(needed),10):
        p,f,c,e=cross_sections(api,needed[j:j+10],u);prices.update(p);factors.update(f);changes.update(c);issues.update(e)
        emit("TECH_E1_AUDIT_PROGRESS",{"phase":"market_download","done":min(j+10,len(needed)),"total":len(needed)})
    assert not issues and len(prices)==len(factors)==len(needed)
    market={};vols={};regimes={};part={}
    for d in contextdates:
        i={k:prefix(v,d) for k,v in ix.items()};s={k:prefix(v,d) for k,v in sw.items()}
        pa=participation(u,changes,cal,d);part[d]=pa["score"]
        mt=market_trend(i,cal,d);br=combine_breadth([stock_breadth(u,prices,factors,cal,d),sector_breadth(s,cal,d),pa],d)
        li=activity(prefix(turn["000001.SH"],d),prefix(turn["399107.SZ"],d),cal,d)
        if d not in qdates:continue
        market[d]=(i,s,mt,br,li);vols[d]=population_vol(u,prices,factors,cal,d)
        lag=part.get(cal[cal.index(d)-5]);a,b,c=mt["score"],br["score"],li["score"]
        if a is None or b is None:regime="unknown"
        elif a<=1.5 and b<=1.5:regime="repair" if lag is not None and pa["score"] is not None and pa["score"]-lag>=.5 and c is not None and c>=3.5 else "defensive"
        else:regime="strong" if a>=3.5 else "weak" if a<=1.5 else "mixed"
        regimes[d]=regime
    CTX=(cal,market,tax,vols,regimes,{x["date"]:x for x in qm["dates"]})
    identity=digest([os.environ["GITHUB_SHA"],EXPECTED,digest([cal,market,tax,vols,regimes])])
    ledger=AuditLedger("e1-q1-ledger",identity);outcomes={};diagnostics={};reused=0;fresh=0
    legacy_identity=digest([R1_SHA,EXPECTED,digest([cal,market,tax,vols,regimes])])
    legacy=AuditLedger("e1-legacy/e1-q1-ledger",legacy_identity)
    emit("TECH_E1_R2_LEDGER",{"previous_commit":R1_SHA,"files":len(list(legacy.path.glob("*.json"))),"identity":legacy_identity})
    label_end=cal[cal.index(qdates[-1])+40]
    def save(k,source,out):
        nonlocal fresh
        validate_stock(out,tasks[k],weekly,k in daily,out.get("quality_state"),out.get("first_invalid"))
        ledger.write(k,source,out);outcomes[k]=out;fresh+=1
        emit("TECH_E1_AUDIT_STOCK",stock_event(k,out,len(outcomes),240))
    # Eight deterministic batches, serial API requests, bounded two-process queue.
    for shard in range(8):
        batch=codes[shard::8];pending=[]
        with ProcessPoolExecutor(max_workers=2,mp_context=multiprocessing.get_context("fork")) as pool:
            for k in batch:
                q,diag=load_stock(api,k,u[k],label_end);diag["code"]=k
                try:members=membership_rows(api,k)
                except SafeAPIError:
                    # Retry once; if unavailable, block source-dependent stock rather than fabricate membership.
                    try:members=membership_rows(api,k)
                    except SafeAPIError:
                        members=[];q=None;diag["state"]="source_unavailable";diag["membership_unavailable"]=True
                if diag["state"]!="ok" or diag.get("prior_errors") or k=="600460.SH":
                    public={a:b for a,b in diag.items() if a not in ("observed_dates","source")}
                    diagnostics[k]=public;emit("TECH_E1_AUDIT_INPUT",public)
                args=(q,members,tasks[k],weekly,group[k],k in daily,k in oracle,u[k])
                if diag["state"]=="ok":
                    source=digest([diag["source"],members,tasks[k],u[k],group[k],k in daily,k in oracle])
                else:
                    source=digest([diag["source"],diag["state"],members,tasks[k],u[k],group[k],k in daily,k in oracle])
                hit=checkpoint_hit(ledger,k,source,tasks[k],weekly,k in daily,diag["state"],diag.get("first_invalid"))
                if hit is None:
                    hit=checkpoint_hit(legacy,k,source,tasks[k],weekly,k in daily,diag["state"],diag.get("first_invalid"))
                if hit is not None:
                    ledger.write(k,source,hit);outcomes[k]=hit;reused+=1
                    emit("TECH_E1_AUDIT_RESUME",{"verified_source":True,**stock_event(k,hit,len(outcomes),240)})
                else:
                    pending.append((k,source,pool.submit(worker,args) if diag["state"]=="ok" else pool.submit(isolated_worker,args+(diag,))))
                if len(pending)>=2:
                    k,source,f=pending.pop(0);save(k,source,f.result())
            for k,source,f in pending:save(k,source,f.result())
        emit("TECH_E1_AUDIT_SHARD",{"shard":shard,"stocks_done":len(outcomes),"wall_seconds":round(time.perf_counter()-start,2)})
    assert set(outcomes)==set(codes)
    panels=defaultdict(Counter);dims=defaultdict(Counter)
    for o in outcomes.values():
        for k,v in o["panels"].items():panels[k].update(v)
        for k,v in o["dimensions"].items():dims[k].update(v)
    validate_panels({k:dict(v) for k,v in panels.items()},{k:dict(v) for k,v in dims.items()},{"core":2880,"daily":3540,"overlap":720,"unique":5700})
    pairs=sum(o["paired_checks"] for o in outcomes.values());prefixes=sum(o["prefix_checks"] for o in outcomes.values())
    assert pairs==prefixes and pairs>0
    result={"manifest":EXPECTED,"identity":identity,"panels":{k:dict(v) for k,v in panels.items()},"dimensions":{k:dict(v) for k,v in dims.items()},
        "stocks":240,"fresh":fresh,"reused":reused,"input_diagnostics":diagnostics,"oracle_pairs":pairs,"prefix_checks":prefixes,"oracle_planned":60,"stock_output_digest":digest([[k,outcomes[k]["output_digest"]] for k in codes]),
        "compute_seconds":sum(o["compute_seconds"] for o in outcomes.values()),"wall_seconds":time.perf_counter()-start,"api_counts":api.counts,
        "no_outcomes":True,"full_feature_store":False}
    atomic(Path("e1-q1-audit")/"aggregate-audit.json",result)
    emit("TECH_E1_AUDIT_DIMENSIONS",report_dimensions(result["dimensions"]))
    emit("TECH_E1_AUDIT_DONE",{k:v for k,v in result.items() if k not in ("dimensions","input_diagnostics")})
if __name__=="__main__":main()
