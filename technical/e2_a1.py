"""E2-A1 private evidence runner, frozen R3 feature path."""
import os,sys,time,math,multiprocessing
from collections import Counter,defaultdict
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from .model_e0 import *
from .e1_freeze_manifest import verify,EXPECTED
from .e1_manifest import schedule
from .model_e0_validate import context_sources
from .model_b_data import universe_history,membership_rows,cross_sections,prefix
from .model_b import market_trend,stock_breadth,sector_breadth,participation,combine_breadth,activity,point_membership
from .e0_r2_acceleration import acceleration,evaluate
from .e0_r3_index import CalendarIndex,indexed
from .e0_r3_store import atomic
from .e1_q1_r1 import AuditLedger
from .e1_q1_r2 import checkpoint_hit
from .e1_q1_audit import population_vol
from . import e1_q1_audit as prior
from .e1_scope_candidates import *
from .data import Tushare
from .diagnostics import emit
CTX=None
BASE="f5e69c6b311172dbd9cf2553fee19de27978d92f"
BASE_DIGEST="eeced4bcb3da90059d2cd8d1cffda2b19f50f93db947f55002949087bbd8a916"
EXTRA={"600615.SH","600653.SH","600660.SH","600676.SH","600690.SH","600612.SH"}
def evalrow(q,d,cal,context,tax,members,index):
    if q is None or d not in q.dates:return None
    with indexed(index):r,_=evaluate(q,d,cal,context,tax,members)
    return r
def add_stats(c,arms):
    c["planned"]+=1
    for name,a in arms.items():
        for k in ("ready","scored","strict","context"):c[name+"."+k]+=int(a[k])
        for h in HORIZONS:
            ad=a["labels"].get(str(h),{})
            c[f"{name}.label{h}"]+=int(bool(ad.get("eligible")))
            c[f"{name}.scored_label{h}"]+=int(a["scored"] and bool(ad.get("eligible")))
            c[f"{name}.strict_label{h}"]+=int(a["strict"] and bool(ad.get("eligible")))
            c[f"{name}.label{h}.reason."+ad.get("reason","no_valid_history")]+=1
        c[name+".risk_veto"]+=int(a.get("risk_veto") is True)
    a=arms["A3"]
    for name,b in arms.items():
        if name=="A3":continue
        for state in ("scored","strict"):
            p="paired" if a[state] and b[state] else "baseline_only" if a[state] else "candidate_only" if b[state] else "neither"
            c[f"{name}.{state}.{p}"]+=1
        if a["scored"] and b["scored"]:
            for h in ("short","medium"):
                x,y=a["D"][h],b["D"][h];k=f"{name}.{h}."
                c[k+"sign_flip"]+=int((x>0>y) or (y>0>x))
                c[k+"direction_flip"]+=int((x>=20 and y<=-20) or (x<=-20 and y>=20))
                c[k+"strong_to_weak"]+=int(abs(x)>=50 and abs(y)<50)
                c[k+"absdiff_bin_"+str(min(5,int(abs(x-y)//10)))]+=1
                c[k+"baseline_bin_"+direction_state(x)]+=1;c[k+"candidate_bin_"+direction_state(y)]+=1
def oracle_check(q,r,d,cal,context,tax,members,mode,restart,bad):
    if r is None:return 0
    qt=QualityHistory([x for x in q.raw if x["trade_date"]<=d],[x for x in q.factors if x["trade_date"]<=d],q.code,d)
    i,s,mt,br,li=context
    from .model_b import industry_context,attach
    from .model_c_r1 import analyze_r1
    v=qt.view(d,cal);a=analyze(qt,d,cal,i);b=attach(a,mt,br,li,industry_context(qt,d,cal,i,tax,members,s));c=analyze_r1(qt,b,cal)
    assert (v,a,b,c)==(r["view"],r["A"],r["B"],r["C"]),"scope prefix mismatch"
    assert independent_dw(qt,d,cal,i)==dw_scores(r["A"],r["view"]),"DW independent score mismatch"
    if restart:assert restart_checks(qt,v,cal,("day","week","month"))==restart_checks(q,r["view"],cal,("day","week","month"))
    return 1

from .e2_evidence import H,verify_window,outcome,benchmark,simple,metrics,require
import json

def private_guard():
    # Refuse before API use. Private/local personal research only.
    if os.environ.get("E2_PRIVATE_RESEARCH_AUTHORIZED")!="1":
        raise RuntimeError("E2 private research authorization/output not confirmed")
    if os.environ.get("GITHUB_ACTIONS")=="true" and os.environ.get("E2_REPOSITORY_PRIVATE")!="true":
        raise RuntimeError("E2 real outcomes blocked in public Actions")
def scope_worker(task):
    code,q,raw,fs,diag,members,dates,weekly,group,daily,oracle,interval,baseline=task
    cal,market,tax,vols,regimes,date_meta=CTX
    prior.CTX=CTX
    ch=CachedHistory(q,cal) if q is not None else None
    bad=[] if diag["state"]=="ok" else invalid_dates(raw,fs,code) if diag["state"]=="data_quality" else None
    # All source fingerprints matched accepted R2 ledger. Per-row baseline recomputed
    # to enable true paired comparisons, with per-stock exact digest verification.
    cache={};stats=defaultdict(Counter);hashes=[];scope_hashes=[];checks=Counter();provenance={}
    feature_rows=[]
    chosen={weekly[0],weekly[-1]} if oracle or code in EXTRA else set()
    with acceleration():
        index=CalendarIndex(cal)
        for d in dates:
            base=evalrow(ch,d,cal,market[d],tax,members,index)
            if base is not None:hashes.append([d,digest(base)])
            a=arm_result(base,ch,d,cal,"A3");dw=arm_result(base,ch,d,cal,"DW")
            if diag["state"]=="ok":
                ha,hd=a,dw;hr=base;hq=ch;meta={"boundary":None}
            else:
                hq,meta=h_history(raw,fs,code,d,cal,bad,cache)
                hr=evalrow(hq,d,cal,market[d],tax,members,index)
                restart=meta.get("boundary") is not None
                ha=arm_result(hr,hq,d,cal,"A3",restart,bad);hd=arm_result(hr,hq,d,cal,"DW",restart,bad)
                # For a pre-error clean prefix, label window must not cross the bad date.
                if not restart and hr is not None:
                    for h in HORIZONS:
                        if any(d<=x<=date_meta[d]["label_end_by_horizon"][str(h)] for x in (bad or [])):
                            ha["labels"][str(h)]={"eligible":False,"reason":"invalid_source_in_label_window"}
                if meta.get("boundary"):provenance[meta["boundary"]]={k:v for k,v in meta.items() if k!="next_invalid"}
                # Independent source prefix with bad rows only through t (never use future boundary).
                if d in chosen and hr is not None:
                    rp=[x for x in raw if x["trade_date"]<=d];fp=[x for x in fs if x["trade_date"]<=d]
                    bdp=invalid_dates(rp,fp,code)
                    qp,mp=h_history(rp,fp,code,d,cal,bdp)
                    assert qp is not None and qp.view(d,cal)==hr["view"],"H asof source prefix mismatch"
                    assert mp.get("boundary")==meta.get("boundary") and mp.get("start")==meta.get("start")
                    checks["H_source_prefix"]+=1
            arms={"A3":a,"DW":dw,"A3-H":ha,"DW-H":hd}
            for name,x in arms.items():
                assert not x["strict"] or x["scored"]
                assert not x["scored"] or x["ready"]
                for h in HORIZONS:
                    if x["labels"].get(str(h),{}).get("eligible"):
                        assert date_meta[d]["label_end_by_horizon"][str(h)] is not None
            if d in chosen:
                checks["baseline_prefix"]+=oracle_check(ch,base,d,cal,market[d],tax,members,"DW",False,bad)
                if diag["state"]!="ok":checks["H_prefix"]+=oracle_check(hq,hr,d,cal,market[d],tax,members,"DW",bool(meta.get("boundary")),bad)
                else:checks["H_clean_alias"]+=int(base is not None)
            scope_hashes.append([d,digest(arms)])
            # Keep only t-known features and eligibility, not a forward return.
            rec={"date":d,"core":d in weekly,"daily":daily,"board":group.split("/")[0],
                 "regime":regimes[d],"age":(datetime.strptime(d,"%Y%m%d")-datetime.strptime(interval[0],"%Y%m%d")).days,
                 "arms":arms,"evidence":{}}
            for name,x in arms.items():
                if not x["scored"]:continue
                rr=base if name in ("A3","DW") else hr
                rec["evidence"][name]={str(h):{"indices":rr["A"]["horizons"]["short" if h==5 else "medium"]["R"].get("indices",[]),
                       "simple":simple(rr,h,cal,d)} for h in H}
            feature_rows.append(rec)
            names=["unique"]+(["core"] if d in weekly else [])+(["daily"] if daily else [])+(["overlap"] if daily and d in weekly else [])
            industry=point_membership(members,code,d,tax).get("code","unclassified")
            age=(datetime.strptime(d,"%Y%m%d")-datetime.strptime(interval[0],"%Y%m%d")).days
            age_band="<1y" if age<365 else "1-3y" if age<1095 else "3-5y" if age<1825 else "5y+"
            for n in names:
                add_stats(stats[n],arms)
                for k,v in (("board",group.split("/")[0]),("liquidity",group.split("/")[1]),("industry",industry),("volatility",vols[d].get(code,"unknown")),("regime",regimes[d]),("listing_age",age_band)):
                    add_stats(stats[n+"|"+k+"|"+v],arms)
    if diag["state"]=="ok":actual=digest(hashes)
    else:
        # Reuse exact prior isolated worker path for its special hash semantics.
        actual=prior.isolated_worker((q,members,dates,weekly,group,daily,oracle,interval,{**diag,"code":code}))["output_digest"]
    assert actual==baseline["output_digest"],"baseline output drift "+code
    assert stats["unique"]["A3.scored"]==baseline["counts"].get("composite_ready",0)
    assert stats["unique"]["A3.strict"]==baseline["counts"].get("scored_among_strict_ready",0)
    # Independent forward-window gate runs before any return arithmetic, for every admitted arm.
    # Use source slices in memory; never write row-level data.
    rm=sorted(raw,key=lambda x:x["trade_date"]);prev=max((x["trade_date"] for x in rm if x["trade_date"]<dates[0]),default=dates[0])
    end=max(date_meta[d]["label_end_by_horizon"][str(h)] for d in dates for h in H)
    rr=[x for x in raw if prev<=x["trade_date"]<=end];ff=[x for x in fs if prev<=x["trade_date"]<=end]
    return {"stats":{k:dict(v) for k,v in stats.items()},"baseline_digest":actual,"candidate_digest":digest(scope_hashes),"checks":dict(checks),"provenance":provenance,
        "feature_digest":digest([{**r,"arms":{k:{a:b for a,b in x.items() if a!="labels"} for k,x in r["arms"].items()}} for r in feature_rows]),"rows":feature_rows,"raw":rr,"factors":ff}
def main():
    global CTX
    private_guard()
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
    emit("TECH_E2_PLAN",{"manifest":EXPECTED,"stocks":240,"daily_stocks":60,"unique":5700,"oracle_symbols":sorted(oracle)})
    tax,sw,ix,turn=context_sources(api,cal)
    lagdates=[cal[cal.index(d)-5] for d in qdates];contextdates=sorted(set(qdates+lagdates))
    needed=sorted({x for d in contextdates for x in cal[cal.index(d)-79:cal.index(d)+1]})
    prices={};factors={};changes={};issues={}
    for j in range(0,len(needed),10):
        p,f,c,e=cross_sections(api,needed[j:j+10],u);prices.update(p);factors.update(f);changes.update(c);issues.update(e)
        emit("TECH_E2_PROGRESS",{"phase":"market_download","done":min(j+10,len(needed)),"total":len(needed)})
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
    baseline_identity=digest([BASE,EXPECTED,digest([cal,market,tax,vols,regimes])])
    assert baseline_identity=="0e2c29c2a1cc8e77400bcddc68f5dbe493e0e817b27ef84e68243518a3a2e329","shared input drift; do not silently compare"
    legacy=AuditLedger("scope-baseline/e1-q1-ledger",baseline_identity)
    assert len(list(legacy.path.glob("*.json")))==240
    label_end=cal[cal.index(qdates[-1])+40];outcomes={};download=0.
    def save(k,out):
        outcomes[k]=out
        emit("TECH_E2_FEATURE_PROGRESS",{"done":len(outcomes),"total":240})
    for shard in range(8):
        pending=[]
        with ProcessPoolExecutor(max_workers=2,mp_context=multiprocessing.get_context("fork")) as pool:
            for k in codes[shard::8]:
                t=time.perf_counter();q,raw,fs,diag=fetch_inputs(api,k,u[k],label_end)
                members=membership_rows(api,k);download+=time.perf_counter()-t
                if diag["state"]=="ok":source=digest([diag["source"],members,tasks[k],u[k],group[k],k in daily,k in oracle])
                else:source=digest([diag["source"],diag["state"],members,tasks[k],u[k],group[k],k in daily,k in oracle])
                hit=checkpoint_hit(legacy,k,source,tasks[k],weekly,k in daily,diag["state"],diag.get("first_invalid"))
                assert hit is not None,"source drift or invalid prior checkpoint "+k
                pending.append((k,pool.submit(scope_worker,(k,q,raw,fs,diag,members,tasks[k],weekly,group[k],k in daily,k in oracle,u[k],hit))))
                if len(pending)>=2:
                    k,f=pending.pop(0);save(k,f.result())
            for k,f in pending:save(k,f.result())
        emit("TECH_E2_SHARD",{"shard":shard,"done":len(outcomes),"seconds":round(time.perf_counter()-start,2)})
    assert set(outcomes)==set(codes)
    totals=defaultdict(Counter);checks=Counter()
    for o in outcomes.values():
        for k,v in o["stats"].items():totals[k].update(v)
        checks.update(o["checks"])
    base=digest([[k,outcomes[k]["baseline_digest"]] for k in codes]);assert base==BASE_DIGEST
    for n,count in (("core",2880),("daily",3540),("overlap",720),("unique",5700)):
        c=totals[n];assert c["planned"]==count
        for a in ARMS:
            assert c[a+".strict"]<=c[a+".scored"]<=c[a+".ready"]<=count
            for h in HORIZONS:
                assert sum(v for k,v in c.items() if k.startswith(f"{a}.label{h}.reason."))==count
        for a in ARMS[1:]:
            for state in ("scored","strict"):
                assert sum(c[f"{a}.{state}.{v}"] for v in ("paired","baseline_only","candidate_only","neither"))==count
        for kind in ("board","liquidity","industry","volatility","regime","listing_age"):
            part=Counter()
            for k,v in totals.items():
                if k.startswith(n+"|"+kind+"|"):part.update(v)
            assert part==c,"dimension accounting"
    assert totals["core"]+totals["daily"]==totals["unique"]+totals["overlap"]
    assert totals["unique"]["A3.scored"]==3750 and totals["unique"]["A3.strict"]==1887
    candidate=digest([[k,outcomes[k]["candidate_digest"]] for k in codes])
    assert candidate=="8b73b1045fdfa384b803e975f8de682667746342d6706ce22c21eef80ceaf836","candidate hash drift"
    emit("TECH_E2_FEATURE_ACCEPTED",{"stocks":240,"planned":5700,"baseline":base,"candidate":candidate,"checks":dict(checks)})
    # ALL 240 feature hashes accepted before calculating actual returns.
    # First preflight all admitted windows (no outcome arithmetic); fail closed.
    admitted={};funnel=Counter();disagreements=Counter()
    for k in codes:
        o=outcomes[k]
        for r in o["rows"]:
            d=r["date"]
            for h in H:
                eligible=[a for a,x in r["arms"].items() if x["scored"] and x["labels"].get(str(h),{}).get("eligible")]
                for a,x in r["arms"].items():
                    funnel[f"{a}|{h}|planned"]+=1
                    funnel[f"{a}|{h}|scored"]+=int(x["scored"])
                    funnel[f"{a}|{h}|admitted"]+=int(a in eligible)
                    funnel[f"{a}|{h}|reason|"+x["labels"].get(str(h),{}).get("reason","no_valid_history")]+=1
                if not eligible:continue
                w,reason=verify_window(o["raw"],o["factors"],k,d,h,cal,CTX[-1][d])
                if w is None:disagreements[reason]+=1;continue
                admitted[k,d,h]=w
    emit("TECH_E2_LABEL_PREFLIGHT",{"verified_windows":len(admitted),"disagreements":dict(disagreements)})
    assert not disagreements,"independent label gate disagrees; no returns computed"
    ixmap={k:{b["date"]:b["close"] for b in v or []} for k,v in ix.items()}
    cohorts=defaultdict(list);cohort_funnel=Counter();route=Counter()
    for k in codes:
        for r in outcomes[k]["rows"]:
            d=r["date"];aa=r["arms"];panels=[n for n in ("core","daily") if r[n]]
            chosen="A3" if aa["A3"]["scored"] else "A3-H" if aa["A3-H"]["strict"] else "DW" if aa["DW"]["strict"] else "DW-H" if aa["DW-H"]["strict"] else "none"
            route[chosen]+=1
            for h in H:
                ok={a:bool(x["scored"] and x["labels"].get(str(h),{}).get("eligible")) for a,x in aa.items()}
                for p in panels:
                    for label,yes in (("paired",ok["A3"] and ok["DW"]),("strict_paired",ok["A3"] and ok["DW"] and aa["A3"]["strict"] and aa["DW"]["strict"]),
                        ("DW_exclusive",ok["DW"] and not aa["A3"]["scored"]),("baseline_only",ok["A3"] and not ok["DW"]),("neither",not ok["A3"] and not ok["DW"])):
                        cohort_funnel[f"{p}|{h}|{label}"]+=int(yes)
                if (k,d,h) not in admitted:continue
                y=outcome(admitted[k,d,h]);i=cal.index(d);ds=cal[i:i+h+1]
                for a,x in aa.items():
                    if not ok[a]:continue
                    e=r["evidence"][a][str(h)];b=benchmark(ixmap,e["indices"],ds)
                    rr={**y,"excess":(1+y["r"])/b-1 if b else None,"date":d,"score":x["D"]["short" if h==5 else "medium"],"risk":x.get("risk_veto"),"regime":r["regime"]}
                    tags=["native"]
                    if a in ("A3","DW") and ok["A3"] and ok["DW"]:tags.append("paired")
                    if a in ("A3","DW") and ok["A3"] and ok["DW"] and aa["A3"]["strict"] and aa["DW"]["strict"]:tags.append("strict_paired")
                    if a=="DW" and not aa["A3"]["scored"]:
                        tags.extend(["DW_exclusive","DW_exclusive|board="+r["board"],"DW_exclusive|age="+("<1y" if r["age"]<365 else "1-3y" if r["age"]<1095 else "3-5y" if r["age"]<1825 else "5y+")])
                    if a.endswith("-H") and k in EXTRA:tags.append("H_recovered")
                    if a==chosen:tags.append("route")
                    for p in panels:
                        for tag in tags:
                            key=(p,h,tag,a);cohorts[key].append(rr)
                            # Comparisons use the same model/label cohort; explicit availability.
                            for name,s in e["simple"].items():
                                if s is not None:
                                    cohorts[(p,h,tag,a+"_"+name)].append({**rr,"score":s})
                                    cohorts[(p,h,tag,a+"_matched_"+name)].append(rr)
    report={}
    for (p,h,tag,a),rows in cohorts.items():
        m=a.split("_")[-1] if a.endswith(("_MA","_MOM")) and "_matched_" not in a else a
        report["|".join((p,str(h),tag,a))]=metrics(rows,h,m)
    result={"stocks":240,"planned":5700,"manifest":EXPECTED,"baseline_digest":base,"candidate_digest":candidate,
        "feature_only_digest":digest([[k,outcomes[k]["feature_digest"]] for k in codes]),"checks":dict(checks),
        "admission":dict(funnel),"cohort_funnel":dict(cohort_funnel),"route":dict(route),"metrics":report,
        "api_counts":api.counts,"wall_seconds":time.perf_counter()-start,"research_only":True,"no_executable_returns":True}
    out=Path(os.environ.get("E2_PRIVATE_OUTPUT","e2-private"))/"evidence.json"
    atomic(out,result)
    emit("TECH_E2_DONE",{"stocks":240,"planned":5700,"report_digest":digest(result),"private_report":True,"no_public_outcomes":True})
if __name__=="__main__":main()
