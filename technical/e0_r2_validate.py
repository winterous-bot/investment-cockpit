"""E0 R2: staged, same fixed pilot; profile old engine before optimizing.
No return labels, no raw data persisted, no production changes.
"""
import os,time,cProfile,pstats,resource
from collections import Counter
from .model_e0 import *
from .model_e0_validate import context_sources
from .model_b_data import universe_history,membership_rows,cross_section,cross_sections,prefix
from .model_b import market_trend,stock_breadth,sector_breadth,participation,combine_breadth,activity
from .data import Tushare
from .diagnostics import emit
from .e0_r2_acceleration import acceleration,evaluate

def add_times(tot,x):
    for k,v in x.items():tot[k]+=v
def profile_rows(p):
    st=pstats.Stats(p)
    return [{"function":k[2],"file":k[0].split("/")[-1],"line":k[1],"calls":v[1],"self_seconds":round(v[2],4),"cumulative_seconds":round(v[3],4)}
            for k,v in sorted(st.stats.items(),key=lambda kv:kv[1][2],reverse=True)[:15]]
def main():
    start=time.perf_counter();api=Tushare(os.environ["TUSHARE_TOKEN"])
    u=universe_history(api);cal=common_calendar(api);emit("TECH_E0_R2_PROGRESS",{"phase":"calendar","seconds":round(time.perf_counter()-start,2),"sessions":len(cal)})
    t=time.perf_counter();tax,sw,ix,turn=context_sources(api,cal)
    emit("TECH_E0_R2_PROGRESS",{"phase":"context_download","seconds":round(time.perf_counter()-t,2),"api_counts":api.counts})
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
    emit("TECH_E0_R2_MANIFEST",{"selected":selected,"daily":daily,"weekly":weekly,"daily_sessions":len(qdates),"planned":total_planned,
        "digest":digest([selected,daily,weekly,qdates]),"seconds":round(time.perf_counter()-t,2)})
    needed=sorted({x for d in qdates for x in [z for z in cal if z<=d][-80:]})
    prices={};factors={};changes={};issues={};t=time.perf_counter()
    # Bounded chunks for heartbeat, same data and model.
    for i in range(0,len(needed),10):
        p,f,c,err=cross_sections(api,needed[i:i+10],u);prices.update(p);factors.update(f);changes.update(c);issues.update(err)
        emit("TECH_E0_R2_PROGRESS",{"phase":"market_download","done":min(i+10,len(needed)),"total":len(needed),"seconds":round(time.perf_counter()-t,2)})
    emit("TECH_E0_R2_PHASE",{"phase":"market_download","seconds":round(time.perf_counter()-t,2),"daily_sessions":len(prices),"factor_sessions":len(factors),"issues":issues})
    market={};t=time.perf_counter()
    for d in qdates:
        i={k:prefix(v,d) for k,v in ix.items()};s={k:prefix(v,d) for k,v in sw.items()}
        mt=market_trend(i,cal,d);br=combine_breadth([stock_breadth(u,prices,factors,cal,d),sector_breadth(s,cal,d),participation(u,changes,cal,d)],d)
        li=activity(prefix(turn["000001.SH"],d),prefix(turn["399107.SZ"],d),cal,d)
        market[d]=(i,s,mt,br,li)
        if len(market)%10==0:emit("TECH_E0_R2_PROGRESS",{"phase":"market_compute","done":len(market),"total":len(qdates),"seconds":round(time.perf_counter()-t,2)})
    emit("TECH_E0_R2_PHASE",{"phase":"market_compute","seconds":round(time.perf_counter()-t,2),"dates":len(market)})
    # Run same observations: compare on first 10 observed and first/last weekly
    # per symbol; no outcome selection. Profile baseline only for first 3.
    count=Counter();fast_time=Counter();old_time=Counter();compares=0;prefix_checks=0
    download_time=0.;benchmark_old=0.;benchmark_new=0.;oracle_time=0.;profile=cProfile.Profile()
    checkpoints={10:None,100:None};label_end=cal[cal.index(qdates[-1])+40]
    for k in codes:
        t=time.perf_counter()
        emit("TECH_E0_R2_PROGRESS",{"phase":"stock_download","code":k,"done":count["planned"],"total":total_planned})
        try:q,meta=historical_history(api,k,u[k],label_end)
        except Exception as e:
            count["stock_failure"]+=1;count["planned"]+=len(tasks[k])
            emit("TECH_E0_R2_STOCK_ERROR",{"code":k,"error_type":type(e).__name__});continue
        try:members=membership_rows(api,k)
        except Exception:members=[];count["membership_source_error"]+=1
        download_time+=time.perf_counter()-t
        ch=CachedHistory(q,cal);oldch=CachedHistory(q,cal)
        for d in tasks[k]:
            count["planned"]+=1
            if d not in q.dates:count["not_observed"]+=1;continue
            micro=compares<10
            compare=micro or d in (weekly[0],weekly[-1])
            if compare:
                t=time.perf_counter()
                if compares<3:profile.enable()
                old,ot=evaluate(oldch,d,cal,market[d],tax,members)
                if compares<3:profile.disable()
                duration=time.perf_counter()-t;oracle_time+=duration
                add_times(old_time,ot)
                if micro:benchmark_old+=duration
            t=time.perf_counter()
            with acceleration() as stats:
                new,nt=evaluate(ch,d,cal,market[d],tax,members)
            duration=time.perf_counter()-t
            add_times(fast_time,nt);count["computed"]+=1
            count["optimized_wall_microseconds"]+=round(duration*1e6)
            for key,v in stats.items():count[key]+=v
            if compare:
                assert old==new and digest(old)==digest(new),f"R1 exact mismatch {k} {d}"
                compares+=1
                if micro:benchmark_new+=duration
                # independent frozen full-calendar oracle, not just R1 cache.
                t=time.perf_counter();full,_=evaluate(q,d,cal,market[d],tax,members)
                assert full==new and digest(full)==digest(new),f"frozen mismatch {k} {d}"
                if d in (weekly[0],weekly[-1]):
                    qt=QualityHistory([x for x in q.raw if x["trade_date"]<=d],[x for x in q.factors if x["trade_date"]<=d],k,d)
                    # future admission intentionally remains on full history;
                    # feature and context engines on independent truncated history.
                    pv=qt.view(d,cal);pa=analyze(qt,d,cal,market[d][0])
                    from .model_b import industry_context,attach
                    from .model_c_r1 import analyze_r1
                    i,s,mt,br,li=market[d];pb=attach(pa,mt,br,li,industry_context(qt,d,cal,i,tax,members,s))
                    pr=analyze_r1(qt,pb,cal)
                    assert pv==new["view"] and pa==new["A"] and pb==new["B"] and pr==new["C"],f"prefix mismatch {k} {d}"
                    prefix_checks+=1
                oracle_time+=time.perf_counter()-t
            count["composite_ready"]+=int(new["A"]["composite_ready"])
            ctx=new["B"]["market_industry_context"]
            count["context_ready"]+=int(all(ctx[z] for z in ("market_ready","breadth_ready","liquidity_ready","industry_ready")))
            for f,x in new["coverage"].items():count["feature_"+f+"_"+x["state"]]+=1
            for h,x in new["admission"].items():count["label_"+h+"_"+x["reason"]]+=1
            n=count["computed"]
            if n in checkpoints and checkpoints[n] is None:
                checkpoints[n]=count["optimized_wall_microseconds"]/1e6
                emit("TECH_E0_R2_CHECKPOINT",{"computed":n,"optimized_wall_seconds":checkpoints[n],"paired_checks":compares,"oracle_seconds":round(oracle_time,3),"stage_seconds":dict(fast_time)})
            if n%10==0:emit("TECH_E0_R2_PROGRESS",{"phase":"stock_compute","code":k,"computed":n,"planned_seen":count["planned"],"total":total_planned,"wall_seconds":round(time.perf_counter()-start,2)})
        emit("TECH_E0_R2_STOCK",{"code":k,"history_digest":meta["digest"],"planned_seen":count["planned"],"computed":count["computed"]})
    emit("TECH_E0_R2_PROFILE",{"first_profiled_pairs":min(3,compares),"baseline_top_self":profile_rows(profile)})
    emit("TECH_E0_R2_DONE",{"planned":total_planned,"counts":dict(count),"exact_pairs":compares,"prefix_checks":prefix_checks,
         "baseline_stage_seconds":dict(old_time),"optimized_stage_seconds":dict(fast_time),"first10_baseline_seconds_including_profile":benchmark_old,
         "first10_optimized_seconds":benchmark_new,"checkpoints":checkpoints,"oracle_seconds":oracle_time,"stock_download_seconds":download_time,
         "wall_seconds":time.perf_counter()-start,"max_rss_kib":resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,"api_counts":api.counts,"no_returns_computed":True})
    if count["stock_failure"] or count["planned"]!=total_planned or compares<10 or not prefix_checks or issues:raise RuntimeError("R2 pilot incomplete")
if __name__=="__main__":main()
