"""Build V1.4 from the existing encrypted V1.3 research snapshot.
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
from financial_engine import FIELDS,CORE,pick,reconstruct
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
    if r["version"]!="growth-scanner-v1.3" or not r.get("data_coverage_pass") or len(x["rows"])!=r["complete_metrics"]:raise RuntimeError("Base snapshot invalid")
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
    def subset(ep,k):return {t:v.get(k) for (e,t),v in data.items() if e==ep}
    for z in x["rows"]:
        k=z["code"];z["reverse_dcf"]=reconstruct(z,subset("income_vip",k),subset("cashflow_vip",k),subset("balancesheet_vip",k),years,latest,prior)
    stats={"all":summarize(x["rows"]),"unique_presets":summarize([z for z in x["rows"] if z["code"] in candidates]),
      "presets":{t["id"]:summarize([z for z in x["rows"] if passes(z,t["limits"])]) for t in PRESETS}}
    r["reverse_dcf_v13_statistics"]=r.get("reverse_dcf_statistics")
    r.update(version="growth-scanner-v1.4",reverse_dcf_statistics=stats,
      reverse_dcf_health={"annual_periods":years,"opening":opening,"latest":latest,"prior":prior,"api_batches":health,"failed_batches":errors},
      reverse_dcf_method={"income":"Operating profit + expensed interest - interest income - disclosed investment, fair value, disposal and other income; retain FX/impairment; annual actual effective tax median with >=2 in [0%,35%].",
      "cash":"CFO minus gross cash capex minus estimated interest tax shield and after-tax interest income. PRC industrial financing interest classification; cash/accrual differences, grants and lease effects not fully adjusted. Independent NOPAT + D&A + indirect working capital cash movements - capex diagnostic only if all fields reported.",
      "capital":"Average opening/closing consolidated book equity + reconstructed debt - cash proxy (min money_cap and cash equivalents) - separately identified investments. ROIC = NOPAT / average invested capital. Optional individual statement blanks assumed absent explicitly, core fields required.",
      "ev":"Market cap + reconstructed debt - cash proxy - identified investments + book minority and other equity tools; current portion of noncurrent liabilities treated as debt, unclassified debt and book/market investment gaps remain.",
      "solver":"Same V1.3 bounds and 18 scenarios; no relaxation of positive and stability gates; separate data, model eligibility, and root coverage."})
    p.write_text(json.dumps(x,ensure_ascii=False,separators=(",",":"),allow_nan=False),encoding="utf8")
    (d/"validation.json").write_text(json.dumps(r,ensure_ascii=False,indent=2),encoding="utf8")
    print(json.dumps({"v14_statistics":stats,"v14_health":r["reverse_dcf_health"]},ensure_ascii=False))
if __name__=="__main__":main()
