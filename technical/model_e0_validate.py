"""Real E0 source checks and batch pilot; aggregate-only outputs, no labels/returns."""
import os,sys,time,resource
from collections import Counter
from datetime import datetime,timedelta
from .model_e0 import *
from .data import Tushare
from .model_b_data import universe_history,taxonomy,membership_rows,sector_series,close_series,prefix,turnover_series,cross_sections
from .model_b import market_trend,stock_breadth,sector_breadth,participation,combine_breadth,activity,point_membership,industry_context,attach
from .model_c_r1 import analyze_r1
from .diagnostics import emit

def context_sources(api,sessions):
    tax=taxonomy(api);sw=sector_series(api,tax,"20210101",END)
    ix={}
    for k in ("000300.SH","000905.SH","000852.SH","932000.CSI","000001.SH"):
        try:ix[k]=normalize(series(api,"index_daily",k,"20210101",END,FIELDS),None,k,END)
        except Exception:ix[k]=None
    turn=turnover_series(api,"20210101",END)
    # full study interval, plus explicit 260-session prehistory at first 2023 session
    first=next(d for d in sessions if d>="20230101");start=[d for d in sessions if d<=first][-260]
    cov={"indices":{k:calendar_coverage(v,sessions,start,END) for k,v in ix.items()},
         "sectors":{k:calendar_coverage(v,sessions,start,END) for k,v in sw.items()},
         "turnover":{k:calendar_coverage(v,sessions,start,END) for k,v in turn.items()}}
    emit("TECH_E0_CONTEXT_COVERAGE",{"start":start,"end":END,**cov})
    return tax,sw,ix,turn

def source(api,u,cal):
    tax,sw,ix,turn=context_sources(api,cal)
    # Monthly last-session stratified probe, not full daily cross-section audit.
    anchors={}
    for d in cal:
        if "20230101"<=d<=END:anchors[d[:6]]=d
    stats=[];issues={}
    for d in anchors.values():
        p,f,c,err=cross_sections(api,[d],u);eligible=eligible_at(u,d);n=len(eligible)
        stats.append({"date":d,"eligible":n,"daily":len(set(p.get(d,{}))&eligible),"factor":len(set(f.get(d,{}))&eligible)})
        issues.update(err)
    emit("TECH_E0_CROSS_SECTION",{"sampled_month_end_dates":len(stats),"rows":stats,"issues":issues})
    # Diagnostic delist cohorts chosen by fixed hash, not future performance.
    de=[k for k,(a,b) in u.items() if b and "20230101"<=b<=END and board(k)]
    cohort=sorted(de,key=lambda k:digest([SEED,"delist",k]))[:6]
    for k in cohort:
        try:
            q,meta=historical_history(api,k,u[k],END)
            # No terminal price assumption. Historical feature before actual last day.
            before=[d for d in q.dates if "20230101"<=d<q.asof]
            d=before[-1] if before else None
            m=membership_rows(api,k)
            emit("TECH_E0_DELIST",{"code":k,"delist_date":u[k][1],"state":"readable","history":meta,"membership_rows":len(m),
                "last_prior_feature":d,"label_gate40":q.label_admission(d,40,cal) if d else None})
        except Exception as e:emit("TECH_E0_DELIST",{"code":k,"delist_date":u[k][1],"state":"incomplete","error_type":type(e).__name__})
    # Historical execution endpoints; check exact dates/keys, not just non-empty response.
    for d in ("20230428","20240430","20250430",END):
        eligible=eligible_at(u,d)
        probes={}
        def date_rows(rs,keys):
            codes=[x.get("ts_code") for x in rs]
            return len(codes)==len(set(codes)) and all(x.get("trade_date")==d and all(x.get(k) is not None for k in keys) for x in rs)
        probes["stk_limit"]=safe_probe(api,"stk_limit",{"trade_date":d},"ts_code,trade_date,up_limit,down_limit",lambda r:date_rows(r,("up_limit","down_limit")) and len({x["ts_code"] for x in r}&eligible)/len(eligible)>=.85)
        probes["stock_st"]=safe_probe(api,"stock_st",{"trade_date":d},"ts_code,trade_date,name,type,type_name",lambda r:date_rows(r,("name",)))
        probes["suspend_d"]=safe_probe(api,"suspend_d",{"trade_date":d},"ts_code,trade_date,suspend_type,suspend_timing",lambda r:all(x.get("trade_date")==d and x.get("ts_code") for x in r))
        emit("TECH_E0_EXECUTION_PROBE",{"date":d,"probes":probes})
    for k in ["600000.SH","300750.SZ"]+cohort[:2]:
        probes={"namechange":safe_probe(api,"namechange",{"ts_code":k},"ts_code,name,start_date,end_date,ann_date,change_reason",lambda r:all(x.get("ts_code")==k and x.get("start_date") for x in r)),
                "dividend":safe_probe(api,"dividend",{"ts_code":k},"ts_code,ann_date,record_date,ex_date,div_proc,stk_div,cash_div_tax",lambda r:all(x.get("ts_code")==k for x in r))}
        emit("TECH_E0_CORPORATE_PROBE",{"code":k,"probes":probes})
    emit("TECH_E0_SOURCE_DONE",{"cross_section_probe_only":True,"full_execution_admission":False,"reason":"daily observations cannot independently establish intraday fill availability; historical fees and event semantics still require validation","api_counts":api.counts})

def pilot(api,u,cal):
    tax,sw,ix,turn=context_sources(api,cal)
    qdates=[d for d in cal if "20230101"<=d<="20230331"];first=qdates[0]
    w={}
    for d in qdates:w[period(d,"week")]=d
    weekly=list(w.values())[:12]
    prior=[d for d in cal if d<first][-20:];amounts={}
    for d in prior:
        rows=api.ask("daily",{"trade_date":d},"ts_code,trade_date,amount")
        from .model_b_data import cross_section
        amounts[d]={k:v[0] for k,v in cross_section(rows,d,("amount",)).items() if v[0]>0}
        if len(set(amounts[d])&eligible_at(u,d))/len(eligible_at(u,d))<.85:raise ValueError("liquidity source coverage")
    groups=strata(u,first,amounts,"2023Q1");selected=draw(groups,30,"2023Q1|pilot")
    daily=draw(selected,10,"2023Q1|pilot|daily")
    codes=sorted(k for v in selected.values() for k in v);daily_codes={k for v in daily.values() for k in v}
    emit("TECH_E0_PILOT_MANIFEST",{"quarter":"2023Q1","first":first,"weekly":weekly,"daily_sessions":len(qdates),"stratum_sizes":{k:len(v) for k,v in groups.items()},"selected":selected,"daily":daily,"digest":digest([selected,daily,weekly,qdates])})
    needed=sorted({x for d in qdates for x in [z for z in cal if z<=d][-80:]})
    prices,factors,changes,issues=cross_sections(api,needed,u)
    market={}
    for d in qdates:
        i={k:prefix(v,d) for k,v in ix.items()};s={k:prefix(v,d) for k,v in sw.items()}
        mt=market_trend(i,cal,d);br=combine_breadth([stock_breadth(u,prices,factors,cal,d),sector_breadth(s,cal,d),participation(u,changes,cal,d)],d)
        li=activity(prefix(turn["000001.SH"],d),prefix(turn["399107.SZ"],d),cal,d)
        market[d]=(i,s,mt,br,li)
    emit("TECH_E0_PILOT_MARKET",{"dates":len(market),"cached_sessions":len(needed),"daily_sessions":len(prices),"factor_sessions":len(factors),"issues":issues,
        "trend_ready":sum(x[2]["score"] is not None for x in market.values()),"breadth_ready":sum(x[3]["score"] is not None for x in market.values()),"activity_ready":sum(x[4]["score"] is not None for x in market.values())})
    total=Counter();timing=[];oracle=0
    for k in codes:
        dates=sorted(set(weekly+(qdates if k in daily_codes else [])));cnt=Counter();elapsed=0;start=time.perf_counter()
        try:
            # Only pilot-period data plus 40 session label eligibility, no return computation.
            label_end=cal[cal.index(qdates[-1])+40]
            q,meta=historical_history(api,k,u[k],label_end);ch=CachedHistory(q,cal)
            try:members=membership_rows(api,k)
            except Exception:members=[];cnt["membership_source_error"]+=1
            for d in dates:
                cnt["planned"]+=1
                if d not in q.dates:cnt["not_observed"]+=1;continue
                t=time.perf_counter();i,s,mt,br,li=market[d]
                v=ch.view(d,cal);a=analyze(ch,d,cal,i)
                ind=industry_context(ch,d,cal,i,tax,members,s)
                b=attach(a,mt,br,li,ind);r=analyze_r1(ch,b,cal)
                elapsed+=time.perf_counter()-t;cnt["computed"]+=1
                cnt["composite_ready"]+=int(a["composite_ready"])
                cnt["context_ready"]+=int(all(b["market_industry_context"][z] for z in ("market_ready","breadth_ready","liquidity_ready","industry_ready")))
                for f,x in feature_calendar_diagnostics(q,v,cal).items():cnt["feature_"+f+"_"+x["state"]]+=1
                for h,x in admission_counts(ch,d,cal).items():cnt["label_"+h+"_"+x["reason"]]+=1
                if d==weekly[0] or d==weekly[-1]:
                    # Frozen full-calendar result vs optimized bounded cache; independent actual prefix object.
                    assert q.view(d,cal)==v
                    assert analyze(q,d,cal,i)==a
                    qt=QualityHistory([x for x in q.raw if x["trade_date"]<=d],[x for x in q.factors if x["trade_date"]<=d],k,d)
                    assert analyze(qt,d,cal,i)==a
                    assert analyze_r1(qt,b,cal)==r
                    oracle+=1
            cnt["cache_hits"]=ch.hits;cnt["cache_misses"]=ch.misses
            emit("TECH_E0_PILOT_STOCK",{"code":k,"daily_panel":k in daily_codes,"counts":dict(cnt),"seconds_compute":round(elapsed,3),"seconds_total":round(time.perf_counter()-start,3),"history":meta})
        except AssertionError:raise
        except Exception as e:
            cnt["stock_failure"]+=1
            cnt["unprocessed"]=len(dates)-cnt["planned"]
            emit("TECH_E0_PILOT_STOCK",{"code":k,"counts":dict(cnt),"error_type":type(e).__name__})
        total.update(cnt);timing.append(elapsed)
    emit("TECH_E0_PILOT_DONE",{"planned_unique":sum(len(set(weekly+(qdates if k in daily_codes else []))) for k in codes),"counts":dict(total),"oracle_checks":oracle,
        "compute_seconds":round(sum(timing),3),"max_rss_kib":resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,"api_counts":api.counts,"no_returns_computed":True})
    if total["stock_failure"] or total["computed"]==0 or oracle==0:raise RuntimeError("pilot incomplete")

def main():
    api=Tushare(os.environ["TUSHARE_TOKEN"]);u=universe_history(api)
    earliest=min(a for a,b in u.values())
    cal=full_calendar(api,earliest,"20261231")
    emit("TECH_E0_CALENDAR",{"first_listing":earliest,"first_open":cal[0],"last_open":cal[-1],"sessions":len(cal),"study_sessions":sum("20230101"<=d<=END for d in cal),"universe":len(u),"delisted":sum(b is not None for a,b in u.values()),"digest":digest(cal)})
    if sys.argv[1]=="source":source(api,u,cal)
    elif sys.argv[1]=="pilot":pilot(api,u,cal)
    else:raise ValueError("unknown mode")
if __name__=="__main__":main()
