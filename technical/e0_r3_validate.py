"""R3 pilot: identical manifest, bounded worker processes, atomic digest checkpoints.
Raw provider data remains in memory. Aggregate checkpoint artifacts only.
"""
import os,time,resource,multiprocessing
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from .model_e0 import *
from .model_e0_validate import context_sources
from .model_b_data import universe_history,membership_rows,cross_section,cross_sections,prefix
from .model_b import market_trend,stock_breadth,sector_breadth,participation,combine_breadth,activity
from .data import Tushare
from .diagnostics import emit
from .e0_r2_acceleration import acceleration,evaluate
from .e0_r3_index import CalendarIndex,indexed
from .e0_r3_store import Ledger
CTX=None
def worker(task):
    q,members,dates,weekly=task
    cal,market,tax=CTX
    old=CachedHistory(q,cal);new=CachedHistory(q,cal);counts=Counter();times=Counter();checks=0;prefixes=0;old_seconds=0.;new_paired=0.;wall=0.;hashes=[]
    # Fixed per-stock comparisons: first/last weekly plus first observed date.
    observed=[d for d in dates if d in q.dates];chosen=set([weekly[0],weekly[-1]]+observed[:1])
    with acceleration() as stats:
        index=CalendarIndex(cal)
        for d in dates:
            counts["planned"]+=1
            if d not in q.dates:counts["not_observed"]+=1;continue
            if d in chosen:
                t=time.perf_counter();ref,_=evaluate(old,d,cal,market[d],tax,members);old_seconds+=time.perf_counter()-t
            t=time.perf_counter()
            with indexed(index):result,tt=evaluate(new,d,cal,market[d],tax,members)
            dt=time.perf_counter()-t;wall+=dt;times.update(tt)
            if d in chosen:
                new_paired+=dt
                assert ref==result and digest(ref)==digest(result),f"R2/R3 mismatch {q.code} {d}"
                checks+=1
                # Reference uses original C functions; R2 cache is separately accepted.
                if d in (weekly[0],weekly[-1]):
                    qt=QualityHistory([x for x in q.raw if x["trade_date"]<=d],[x for x in q.factors if x["trade_date"]<=d],q.code,d)
                    # Use exact same frozen feature/context logic, not future admission.
                    i,s,mt,br,li=market[d]
                    from .model_b import industry_context,attach
                    from .model_c_r1 import analyze_r1
                    v=qt.view(d,cal);a=analyze(qt,d,cal,i);b=attach(a,mt,br,li,industry_context(qt,d,cal,i,tax,members,s));r=analyze_r1(qt,b,cal)
                    assert (v,a,b,r)==(result["view"],result["A"],result["B"],result["C"]),f"prefix mismatch {q.code} {d}"
                    prefixes+=1
            hashes.append([d,digest(result)])
            counts["computed"]+=1;counts["composite_ready"]+=int(result["A"]["composite_ready"])
            ctx=result["B"]["market_industry_context"]
            counts["context_ready"]+=int(all(ctx[z] for z in ("market_ready","breadth_ready","liquidity_ready","industry_ready")))
            for f,x in result["coverage"].items():counts["feature_"+f+"_"+x["state"]]+=1
            for h,x in result["admission"].items():counts["label_"+h+"_"+x["reason"]]+=1
            if counts["computed"]%10==0:emit("TECH_E0_R3_WORKER_PROGRESS",{"code":q.code,"computed":counts["computed"],"total":len(dates)})
    return {"counts":dict(counts),"output_digest":digest(hashes),"paired_checks":checks,"prefix_checks":prefixes,
            "R2_paired_seconds":old_seconds,"R3_paired_seconds":new_paired,"R3_compute_seconds":wall,"stage_seconds":dict(times),
            "rss_kib":resource.getrusage(resource.RUSAGE_SELF).ru_maxrss}
def main():
    global CTX
    start=time.perf_counter();api=Tushare(os.environ["TUSHARE_TOKEN"])
    u=universe_history(api);cal=common_calendar(api);emit("TECH_E0_R3_PROGRESS",{"phase":"calendar","seconds":round(time.perf_counter()-start,2),"sessions":len(cal)})
    t=time.perf_counter();tax,sw,ix,turn=context_sources(api,cal)
    emit("TECH_E0_R3_PROGRESS",{"phase":"context_download","seconds":round(time.perf_counter()-t,2),"api_counts":api.counts})
    qdates=[d for d in cal if "20230101"<=d<="20230331"];first=qdates[0]
    w={}
    for d in qdates:w[period(d,"week")]=d
    weekly=list(w.values())[:12];prior=[d for d in cal if d<first][-20:]
    t=time.perf_counter();amounts={}
    for d in prior:
        rows=api.ask("daily",{"trade_date":d},"ts_code,trade_date,amount")
        amounts[d]={k:v[0] for k,v in cross_section(rows,d,("amount",)).items() if v[0]>0}
        if len(set(amounts[d])&eligible_at(u,d))/len(eligible_at(u,d))<.85:raise ValueError("liquidity coverage")
    groups=strata(u,first,amounts,"2023Q1");selected=draw(groups,30,"2023Q1|pilot");daily=draw(selected,10,"2023Q1|pilot|daily")
    codes=sorted(k for v in selected.values() for k in v);daily_codes={k for v in daily.values() for k in v}
    tasks={k:sorted(set(weekly+(qdates if k in daily_codes else []))) for k in codes}
    total_planned=sum(map(len,tasks.values()))
    emit("TECH_E0_R3_MANIFEST",{"selected":selected,"daily":daily,"weekly":weekly,"daily_sessions":len(qdates),"planned":total_planned,
        "digest":digest([selected,daily,weekly,qdates]),"seconds":round(time.perf_counter()-t,2)})
    needed=sorted({x for d in qdates for x in [z for z in cal if z<=d][-80:]})
    prices={};factors={};changes={};issues={};t=time.perf_counter()
    # Bounded chunks for heartbeat, same data and model.
    for i in range(0,len(needed),10):
        p,f,c,err=cross_sections(api,needed[i:i+10],u);prices.update(p);factors.update(f);changes.update(c);issues.update(err)
        emit("TECH_E0_R3_PROGRESS",{"phase":"market_download","done":min(i+10,len(needed)),"total":len(needed),"seconds":round(time.perf_counter()-t,2)})
    emit("TECH_E0_R3_PHASE",{"phase":"market_download","seconds":round(time.perf_counter()-t,2),"daily_sessions":len(prices),"factor_sessions":len(factors),"issues":issues})
    market={};t=time.perf_counter()
    for d in qdates:
        i={k:prefix(v,d) for k,v in ix.items()};s={k:prefix(v,d) for k,v in sw.items()}
        mt=market_trend(i,cal,d);br=combine_breadth([stock_breadth(u,prices,factors,cal,d),sector_breadth(s,cal,d),participation(u,changes,cal,d)],d)
        li=activity(prefix(turn["000001.SH"],d),prefix(turn["399107.SZ"],d),cal,d)
        market[d]=(i,s,mt,br,li)
        if len(market)%10==0:emit("TECH_E0_R3_PROGRESS",{"phase":"market_compute","done":len(market),"total":len(qdates),"seconds":round(time.perf_counter()-t,2)})
    emit("TECH_E0_R3_PHASE",{"phase":"market_compute","seconds":round(time.perf_counter()-t,2),"dates":len(market)})

    assert not issues and len(prices)==len(needed)==len(factors)
    assert digest([selected,daily,weekly,qdates])=="88faf02fd08c8062a9ae7e9e45bde1f108378b00ffcdbf6093951c54fe6f28b1","pilot manifest changed"
    CTX=(cal,market,tax)
    # Run identity binds exact code version, full shared inputs, selection, calendar.
    identity=digest([os.environ["GITHUB_SHA"],digest([selected,daily,weekly,qdates]),digest([cal,market,tax])])
    path=Path(os.environ.get("R3_LEDGER","r3-ledger"));ledger=Ledger(path,identity)
    label_end=cal[cal.index(qdates[-1])+40];total=Counter();summary=[];fresh=0;resumed=0;reopen_checks=0;download_seconds=0.
    # Three deterministic shards, two processes; all network requests in parent.
    # No threads inside scoped monkey patches. Linux fork shares read-only market context.
    for shard in range(3):
        batch=codes[shard::3];pending=[];sources={}
        with ProcessPoolExecutor(max_workers=2,mp_context=multiprocessing.get_context("fork")) as pool:
            for k in batch:
                t=time.perf_counter();q,meta=historical_history(api,k,u[k],label_end);members=membership_rows(api,k)
                download_seconds+=time.perf_counter()-t
                source=digest([meta["digest"],members,tasks[k],u[k]])
                sources[k]=source
                hit=ledger.read(k,source)
                if hit is not None:
                    resumed+=1;summary.append(hit);total.update(hit["counts"]);emit("TECH_E0_R3_RESUME",{"code":k,"shard":shard})
                else:
                    pending.append((k,source,pool.submit(worker,(q,members,tasks[k],weekly))))
                # Bounded number of outstanding stock histories.
                if len(pending)>=2:
                    k,source,future=pending.pop(0);out=future.result();ledger.write(k,source,out);fresh+=1;summary.append(out);total.update(out["counts"])
                    emit("TECH_E0_R3_STOCK",{"code":k,"shard":shard,"result":out,"done":fresh+resumed,"total":len(codes)})
            for k,source,future in pending:
                out=future.result();ledger.write(k,source,out);fresh+=1;summary.append(out);total.update(out["counts"])
                emit("TECH_E0_R3_STOCK",{"code":k,"shard":shard,"result":out,"done":fresh+resumed,"total":len(codes)})
        # Deliberate process-pool teardown and ledger reopen at each shard boundary.
        ledger=Ledger(path,identity)
        for k,source in sources.items():
            assert ledger.read(k,source) is not None
            assert ledger.read(k,"wrong_source") is None
            reopen_checks+=1
        emit("TECH_E0_R3_SHARD",{"shard":shard,"stock_count":len(batch),"computed":total["computed"],"reopen_checks":reopen_checks})
    pairs=sum(x["paired_checks"] for x in summary);prefixes=sum(x["prefix_checks"] for x in summary)
    # Same R2 counters, no silent drop. Timing sum is worker CPU-like elapsed, not parallel wall.
    assert total["planned"]==total_planned and total["computed"]==825 and total["composite_ready"]==358 and total["context_ready"]==689
    assert pairs>=60 and prefixes==60 and reopen_checks==30
    emit("TECH_E0_R3_DONE",{"counts":dict(total),"fresh":fresh,"resumed":resumed,"reopen_checks":reopen_checks,"exact_pairs":pairs,"prefix_checks":prefixes,
         "R2_paired_seconds":sum(x["R2_paired_seconds"] for x in summary),"R3_paired_seconds":sum(x["R3_paired_seconds"] for x in summary),
         "R3_compute_seconds":sum(x["R3_compute_seconds"] for x in summary),"stock_download_seconds":download_seconds,
         "wall_seconds":time.perf_counter()-start,"identity":identity,"api_counts":api.counts,"no_returns_computed":True,
         "resume_revalidates_source":True,"raw_cache_persisted":False})
if __name__=="__main__":main()
