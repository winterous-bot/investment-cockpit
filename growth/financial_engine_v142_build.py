"""Build V1.4.2 from the existing encrypted V1.4.1 research snapshot.
No raw statement rows or individual names in public logs/artifacts.
"""
from __future__ import annotations
import sys,os,json,time,statistics
from pathlib import Path
from collections import Counter
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"scripts"))
from tushare_5000 import Tushare,SafeAPIError,POINTS
from growth_model import number,PRESETS,passes
from financial_engine_v142 import FIELDS,CORE,pick,reconstruct
from financial_engine_v141 import reconstruct as reconstruct_v141
POINTS.update({k:5000 for k in FIELDS})
POINTS.update({k.removesuffix("_vip"):2000 for k in FIELDS})
def fetch(api,endpoint,p,asof,universe,candidates):
    fields=FIELDS[endpoint];core=CORE[endpoint]
    params={"period":p,"report_type":"1"}
    field="ts_code,ann_date,f_ann_date,end_date,report_type,comp_type,update_flag,"+",".join(fields)
    raw=api.ask(endpoint,params,field)
    first=len(raw);pages=1;offset=first
    selected,stats=pick(raw,p,asof,fields)
    # Detect server row limits via offsets and exact duplicate detection.
    if first and (first>=4000 or len(universe&set(selected))<.98*len(universe)):
        for _ in range(8):
            try:more=api.ask(endpoint,{**params,"offset":offset,"limit":min(first,5000)},field)
            except SafeAPIError:break
            if not more:break
            seen={json.dumps(v,sort_keys=True) for v in raw}
            new=[v for v in more if json.dumps(v,sort_keys=True) not in seen]
            if not new:break
            raw.extend(new);pages+=1;offset+=len(more)
            if len(more)<min(first,5000):break
    selected,stats=pick(raw,p,asof,fields)
    def incomplete(k):return k not in selected or any(selected[k].get(f) is None for f in core)
    # Individually resolve incomplete candidate rows; never replace a conflicting
    # current record with an earlier date or combine fields across versions.
    fallback=0;fallback_errors=0
    for k in sorted(v for v in candidates if incomplete(v)):
        try:
            new=api.ask(endpoint.removesuffix("_vip"),{**params,"ts_code":k},field,retry=1)
            raw.extend(new);fallback+=1
        except SafeAPIError:fallback_errors+=1
        time.sleep(.2)
    selected,stats=pick(raw,p,asof,fields)
    stats.update(endpoint=endpoint,period=p,first_rows=first,pages=pages,
      covered=len(universe&set(selected)),candidate_covered=len(candidates&set(selected)),
      candidate_complete=sum(not incomplete(k) for k in candidates),
      candidate_missing_core={f:sum(k in selected and selected[k].get(f) is None for k in candidates) for f in core},
      candidate_missing_optional={f:sum(k in selected and selected[k].get(f) is None for k in candidates) for f in fields if f not in core},
      fallback=fallback,fallback_errors=fallback_errors)
    return selected,stats
def summarize(rows):
    v=[x["reverse_dcf"] for x in rows];acc=[x for x in v if x.get("accounting")];eligible=[x for x in v if x["status"]=="ok"]
    center=lambda x,n:next(z for z in x["sensitivity"] if z["years"]==n and z["wacc"]==.1 and z["terminal"]==.03)
    gaps=[abs(x["accounting"]["roics"][-1]-x["accounting"]["vendor_roic_last"]) for x in acc if x["accounting"]["vendor_roic_last"] is not None]
    checks=[x["accounting"]["ttm"] for x in acc]
    dual=[x for x in checks if x["accrual_fcff"] is not None]
    return {"n":len(v),"accounting_complete":len(acc),"model_eligible":len(eligible),
      "data_exclusions":dict(Counter(x["reason"] for x in v if x.get("category")=="data")),
      "model_exclusions":dict(Counter(x["reason"] for x in v if x.get("category")=="model")),
      "central_5y":dict(Counter(center(x,5)["status"] for x in eligible)),
      "central_10y":dict(Counter(center(x,10)["status"] for x in eligible)),
      "any_unique_solution":sum(any(z["status"]=="ok" for z in x["sensitivity"]) for x in eligible),
      "warnings":dict(Counter(w for x in acc for w in x["accounting"]["warnings"])),
      "dual_fcff_ttm_available":len(dual),
      "median_absolute_roic_gap_pp":statistics.median(gaps)*100 if gaps else None,
      "roic_gap_over_10pp":sum(g>.10 for g in gaps)}
def main():
    d=Path(sys.argv[1]);p=d/"snapshot.json";x=json.loads(p.read_text());r=x["report"]
    if r["version"] not in ("growth-scanner-v1.4.1","growth-scanner-v1.2") or not r.get("data_coverage_pass") or len(x["rows"])!=r["complete_metrics"]:raise RuntimeError("Base snapshot invalid")
    asof=r["asof"];plan=r["periods"];y=int(plan["annual"][:4])
    years=[f"{i}1231" for i in range(y-2,y+1)];opening=f"{y-3}1231"
    latest,prior=plan["latest"],plan["prior"];periods=years+[latest,prior]
    universe={z["code"] for z in x["rows"]}
    candidates={z["code"] for z in x["rows"] if any(passes(z,t["limits"]) for t in PRESETS)}
    api=Tushare(os.environ.get("TUSHARE_TOKEN"));data={};health=[];errors=[]
    for ep in FIELDS:
        for t in (periods if ep=="income_vip" else [opening]+periods):
            try:
                data[(ep,t)],h=fetch(api,ep,t,asof,universe,candidates);health.append(h)
            except SafeAPIError:
                errors.append({"endpoint":ep,"period":t})
    if errors or len(health)!=17 or any(h["covered"]<.9*len(universe) or h["candidate_covered"]<.9*len(candidates) for h in health):raise RuntimeError("Production raw financial coverage insufficient")
    def subset(ep,k):return {t:v.get(k) for (e,t),v in data.items() if e==ep}
    def compact(v):
        a=v.get("accounting");b=v.get("base")
        center={}
        for n in (5,10):
            q=next((t for t in v.get("sensitivity",[]) if t["years"]==n and t["wacc"]==.10 and t["terminal"]==.03),None)
            center[str(n)]={"status":q["status"],"growth":q.get("nopat_growth")} if q else None
        return {"category":v.get("category"),"reason":v.get("reason"),"status":v.get("status"),
          "accounting":bool(a),"roic_last":a["roics"][-1] if a else None,
          "roic_median":statistics.median(a["roics"]) if a else None,
          "ev":a["ev"] if a else None,"ttm_fcff":a["ttm"]["fcff"] if a else None,
          "ttm_nopat":a["ttm"]["nopat"] if a else None,
          "model_roic":b["roic"] if b else None,
          "center":center,"any_unique_solution":any(q["status"]=="ok" for q in v.get("sensitivity",[]))}
    for z in x["rows"]:
        old=compact(z["reverse_dcf"]) if "reverse_dcf" in z else None;k=z["code"]
        args=(z,subset("income_vip",k),subset("cashflow_vip",k),subset("balancesheet_vip",k),years,latest,prior)
        same=compact(reconstruct_v141(*args))
        new=reconstruct(*args)
        current=compact(new)
        z["v141_result"]=same
        z["v141_replay_matches_snapshot"]=same==old if old is not None else None
        if same["accounting"] and current["accounting"]:
            # Asset classification may change capital and EV only, never cash flows.
            if same["ttm_fcff"]!=current["ttm_fcff"] or same["ttm_nopat"]!=current["ttm_nopat"]:raise RuntimeError("Frozen cash flow changed")
            if current["roic_last"]>same["roic_last"]+1e-12 and current["ttm_nopat"]>0:
                # Annual NOPAT can differ in sign from TTM. Compare actual last-year sign.
                if new["accounting"]["annual"][-1]["nopat"]>0:raise RuntimeError("Positive ROIC rose after retaining assets")
            if current["ev"]+1e-8<same["ev"]:raise RuntimeError("EV moved against classification bridge")
        z["reverse_dcf"]=new
    stats={"all":summarize(x["rows"]),"unique_presets":summarize([z for z in x["rows"] if z["code"] in candidates]),
      "presets":{t["id"]:summarize([z for z in x["rows"] if passes(z,t["limits"])]) for t in PRESETS}}
    def classification_summary(rows):
        old=[z["v141_result"] for z in rows];new=[compact(z["reverse_dcf"]) for z in rows]
        paired=[(z,o,n) for z,o,n in zip(rows,old,new) if o["accounting"] and n["accounting"]]
        def med(a):return statistics.median(a) if a else None
        def roots(values,n):return sum(v["center"][str(n)] is not None and v["center"][str(n)]["status"]=="ok" for v in values)
        shifts=[(n["roic_last"]-o["roic_last"])*100 for z,o,n in paired]
        ev_delta=[(n["ev"]-o["ev"]) for z,o,n in paired]
        ret=[z["reverse_dcf"]["accounting"]["investment_classification"] for z,o,n in paired]
        changes={}
        for n in (5,10):
            t=str(n)
            p=[(o["center"][t],q["center"][t]) for o,q in zip(old,new) if o["center"][t] and q["center"][t] and o["center"][t]["status"]==q["center"][t]["status"]=="ok"]
            changes[t]={"both_unique":len(p),"median_change_pp":med([(b["growth"]-a["growth"])*100 for a,b in p]),
                        "median_absolute_change_pp":med([abs(b["growth"]-a["growth"])*100 for a,b in p])}
        def totals(v):return {"accounting_complete":sum(a["accounting"] for a in v),"model_eligible":sum(a["status"]=="ok" for a in v),
            "central_5y":roots(v,5),"central_10y":roots(v,10),"any_unique_solution":sum(a["any_unique_solution"] for a in v)}
        gap_old=[abs(o["roic_last"]-z["roic"])*100 for z,o,n in paired if z.get("roic") is not None]
        gap_new=[abs(n["roic_last"]-z["roic"])*100 for z,o,n in paired if z.get("roic") is not None]
        latest_items={k:sum(z["reverse_dcf"]["accounting"]["capital"][-2]["investment_items"][k]>0 for z,o,n in paired) for k in ("trad_asset","debt_invest","oth_debt_invest","oth_eq_invest","oth_illiq_fin_assets","lt_eqt_invest")}
        return {"n":len(rows),"v141_snapshot_replay_matches":sum(z["v141_replay_matches_snapshot"] is True for z in rows),
            "same_raw_v141":totals(old),"v142":totals(new),"paired_accounting":len(paired),
            "roic_last_median_change_pp":med(shifts),"roic_changed":sum(abs(d)>1e-7 for d in shifts),
            "roic_gap_old_median_pp":med(gap_old),"roic_gap_new_median_pp":med(gap_new),
            "roic_gap_old_over_10pp":sum(g>10 for g in gap_old),"roic_gap_new_over_10pp":sum(g>10 for g in gap_new),
            "ev_changed":sum(abs(d)>1e-7 for d in ev_delta),"ev_median_change_cny_100m":med(ev_delta),
            "latest_retained_positive":sum(v["latest_retained"]>0 for v in ret),"material_classification":sum(v["material"] for v in ret),
            "latest_positive_investment_items":latest_items,"growth_changes":changes,
            "lost_unique":sum(o["any_unique_solution"] and not n["any_unique_solution"] for o,n in zip(old,new)),
            "gained_unique":sum(n["any_unique_solution"] and not o["any_unique_solution"] for o,n in zip(old,new)),
            "transitions":dict(Counter(str(o["category"])+":"+str(o["reason"])+" -> "+str(n["category"])+":"+str(n["reason"]) for o,n in zip(old,new)))}
    comparisons={"all":classification_summary(x["rows"]),"unique_presets":classification_summary([z for z in x["rows"] if z["code"] in candidates]),
      "presets":{t["id"]:classification_summary([z for z in x["rows"] if passes(z,t["limits"])]) for t in PRESETS}}
    r["reverse_dcf_v141_statistics"]=r.get("reverse_dcf_statistics")
    r.update(version="growth-scanner-v1.4.2",reverse_dcf_statistics=stats,
      v142_classification_comparison=comparisons,model_frozen=True,
      reverse_dcf_health={"annual_periods":years,"opening":opening,"latest":latest,"prior":prior,"api_batches":health,"failed_batches":errors},
      reverse_dcf_method={**r.get("reverse_dcf_method",{}),
        "capital":"Equity + debt - cash proxy - debt_invest - oth_debt_invest. Retain mixed trading assets, equity instruments, other noncurrent financial assets and long-term equity investment pending notes. Book-value classification proxy, not proven asset usage; numerator still excludes noncore income.",
        "ev":"Same classification in EV bridge; retained mixed investments are not separately credited as nonoperating asset value. Sensitivity to classification shown by same-raw V1.4.1 comparison. Current negative minority remains blocked.",
        "freeze":"Research model V1.4.2 frozen; no further tuning for coverage. All V1.4.1 FCFF, tax, ROIC domain, reinvestment and solver gates unchanged. Conditional results only."})
    p.write_text(json.dumps(x,ensure_ascii=False,separators=(",",":"),allow_nan=False),encoding="utf8")
    (d/"validation.json").write_text(json.dumps(r,ensure_ascii=False,indent=2),encoding="utf8")
    print(json.dumps({"v142_statistics":stats,"v142_comparison":comparisons,"failed_batches":errors},ensure_ascii=False))
if __name__=="__main__":main()
