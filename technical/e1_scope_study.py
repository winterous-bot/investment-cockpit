"""Scope research R3: full fixed Q1 four-arm coverage study, no realized outcomes."""
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
def scope_worker(task):
    code,q,raw,fs,diag,members,dates,weekly,group,daily,oracle,interval,baseline=task
    cal,market,tax,vols,regimes,date_meta=CTX
    prior.CTX=CTX
    ch=CachedHistory(q,cal) if q is not None else None
    bad=[] if diag["state"]=="ok" else invalid_dates(raw,fs,code) if diag["state"]=="data_quality" else None
    # All source fingerprints matched accepted R2 ledger. Per-row baseline recomputed
    # to enable true paired comparisons, with per-stock exact digest verification.
    cache={};stats=defaultdict(Counter);hashes=[];scope_hashes=[];checks=Counter();provenance={}
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
    return {"stats":{k:dict(v) for k,v in stats.items()},"baseline_digest":actual,"candidate_digest":digest(scope_hashes),"checks":dict(checks),"provenance":provenance}
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
    emit("TECH_SCOPE_PLAN",{"manifest":EXPECTED,"stocks":240,"daily_stocks":60,"unique":5700,"oracle_symbols":sorted(oracle)})
    tax,sw,ix,turn=context_sources(api,cal)
    lagdates=[cal[cal.index(d)-5] for d in qdates];contextdates=sorted(set(qdates+lagdates))
    needed=sorted({x for d in contextdates for x in cal[cal.index(d)-79:cal.index(d)+1]})
    prices={};factors={};changes={};issues={}
    for j in range(0,len(needed),10):
        p,f,c,e=cross_sections(api,needed[j:j+10],u);prices.update(p);factors.update(f);changes.update(c);issues.update(e)
        emit("TECH_SCOPE_PROGRESS",{"phase":"market_download","done":min(j+10,len(needed)),"total":len(needed)})
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
        outcomes[k]=out;atomic(Path("scope-ledger")/(k+".json"),out)
        emit("TECH_SCOPE_STOCK",{"code":k,"done":len(outcomes),"total":240,"A3":out["stats"]["unique"]["A3.scored"],"DW":out["stats"]["unique"]["DW.scored"],"A3-H":out["stats"]["unique"]["A3-H.scored"],"DW-H":out["stats"]["unique"]["DW-H.scored"],"checks":out["checks"]})
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
        emit("TECH_SCOPE_SHARD",{"shard":shard,"done":len(outcomes),"seconds":round(time.perf_counter()-start,2)})
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
    result={"manifest":EXPECTED,"baseline_digest":base,"candidate_digest":digest([[k,outcomes[k]["candidate_digest"]] for k in codes]),"stocks":240,"checks":dict(checks),"stats":{k:dict(v) for k,v in totals.items()},"provenance":{k:v["provenance"] for k,v in outcomes.items() if v["provenance"]},"api_counts":api.counts,"stock_download_seconds":download,"wall_seconds":time.perf_counter()-start,"no_outcomes":True,"no_full_feature_store":True}
    atomic(Path("scope-report")/"aggregate.json",result)
    # Keep full counters in artifact; compact key metrics for accessible logs.
    def compact(c):return {k:v for k,v in c.items() if ".reason." not in k and ".absdiff_bin_" not in k and ".baseline_bin_" not in k and ".candidate_bin_" not in k}
    emit("TECH_SCOPE_DIMENSIONS",{k:compact(v) for k,v in totals.items() if k.startswith("unique|")})
    emit("TECH_SCOPE_DONE",{**{k:v for k,v in result.items() if k!="stats"},"panels":{k:dict(totals[k]) for k in ("unique","core","daily","overlap")}})
if __name__=="__main__":main()
