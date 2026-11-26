"""Private five-company prototype; no raw data or company financials in CI logs."""
from __future__ import annotations
import sys,os,json,argparse,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT/"growth"),str(ROOT/"scripts")]
from tushare_5000 import Tushare,SafeAPIError,POINTS
import growth_model as gm
import financial_engine_v142 as fe
from valuation_model import completed_month_ends,verified_quote,historical,peer_reference
from company_model import *
POINTS.update({k.removesuffix("_vip"):2000 for k in gm.FIELDS})
EXTRA={"income_vip":("oper_cost","rd_exp"),"cashflow_vip":(),"balancesheet_vip":("accounts_receiv","inventories","total_cur_assets","total_cur_liab"),"fina_indicator_vip":()}
def fields(ep):return tuple(dict.fromkeys(gm.FIELDS[ep]+fe.FIELDS.get(ep,())+EXTRA[ep]))
def indicator_versions(rows,k,p,asof):
    """Latest disclosed period only. Tushare update_flag=1 revised, 0 original.
    Never use future announcements or an earlier report to resolve a conflict.
    Without reliable version flags, preserve all same-date alternatives.
    """
    eligible=[x for x in rows if x.get("ts_code")==k and str(x.get("end_date"))==p and gm.valid_date(x.get("ann_date")) and x["ann_date"]<=asof]
    if not eligible:return [],{"latest_rows":0,"revised_rows":0,"original_rows":0,"unknown_flags":0,"distinct_profit_values":0,"revision_selected":False}
    latest=max(x["ann_date"] for x in eligible)
    peers=[x for x in eligible if x["ann_date"]==latest]
    def flag(x):return str(x.get("update_flag",""))
    revised=[x for x in peers if flag(x)=="1"]
    original=[x for x in peers if flag(x)=="0"]
    unknown=len(peers)-len(revised)-len(original)
    use_revision=bool(revised and original and not unknown)
    selected=revised if use_revision else peers
    return selected,{"latest_rows":len(peers),"revised_rows":len(revised),"original_rows":len(original),"unknown_flags":unknown,
       "distinct_profit_values":len({gm.number(x.get("profit_dedt")) for x in selected}),"revision_selected":use_revision}
def selection(rows,ep,k,p,asof):
    r=[x for x in rows if str(x.get("end_date"))==p]
    version_health={}
    source=r
    if ep=="fina_indicator_vip":
        source,version_health=indicator_versions(r,k,p,asof)
    d,gh=gm.select(source,ep,p,asof)
    base=d.get(k)
    accounting=None;ah={}
    if ep in fe.FIELDS:
        f,ah=fe.pick(r,p,asof,fe.FIELDS[ep])
        accounting=f.get(k)
        ff,ph=fe.pick(r,p,asof,fields(ep))
        profile_row=ff.get(k) if k in ff else accounting
    else:
        profile_row=base;ph=gh
        # Profile only: a metric unanimous across ALL surviving complete
        # alternatives is independently known even if other metrics conflict.
        # No picking values from different versions; no invented value;
        # no partial row is passed into the frozen scanner/DCF.
        if base is None and source:
            agreed={}
            for key in gm.FIELDS[ep]:
                values={gm.number(x.get(key)) for x in source}
                if len(values)==1 and None not in values:agreed[key]=next(iter(values))
            if agreed:profile_row=agreed
            version_health["consensus_fields"]=sorted(agreed)
    return profile_row,base,accounting,{"raw":len(r),"growth_conflicts":gh.get("conflicts",0),"profile_conflicts":ph.get("conflicts",0),"accounting_conflicts":ah.get("conflicts",0),"indicator_version":version_health}
def required_fields(ep):
    # Only repair core flow inputs used for annual/quarter/TTM, plus the
    # core balance and frozen scanner fields. No demand for optional blanks.
    return {"income_vip":("revenue","n_income","n_income_attr_p"),
            "cashflow_vip":("n_cashflow_act","c_pay_acq_const_fiolta"),
            "balancesheet_vip":("total_assets","total_liab","total_hldr_eqy_exc_min_int"),
            "fina_indicator_vip":("profit_dedt",)}[ep]
def missing(row,keys):
    return [key for key in keys if row is None or gm.number(row.get(key)) is None]
def repair_period(api,ep,k,p,asof,rows,request_fields):
    keys=required_fields(ep)
    current,base,_,health=selection(rows,ep,k,p,asof)
    before=missing(current,keys)
    if not before and base is not None:return rows,None
    params={"ts_code":k,"period":p}
    if ep!="fina_indicator_vip":params["report_type"]="1"
    failed=False;extra=[]
    try:
        extra=api.ask(ep.removesuffix("_vip"),params,request_fields)
        if any(z.get("ts_code")!=k or str(z.get("end_date"))!=p for z in extra):
            raise RuntimeError("Exact-period endpoint returned wrong stock or period")
    except SafeAPIError:
        failed=True
    # Never silently discard contradictory rows or join fields from versions.
    # Add exact-period results and re-run the original full-row selectors.
    combined=rows+extra
    selected,_,_,after_health=selection(combined,ep,k,p,asof)
    return combined,{"endpoint":ep,"period":p,"before":before,"after":missing(selected,keys),"range_rows":health["raw"],"exact_rows":len(extra),"api_error":failed,"growth_conflicts":after_health["growth_conflicts"],"profile_conflicts":after_health["profile_conflicts"],"indicator_version":after_health["indicator_version"]}
def load_company(api,k,asof,plan):
    first=int(plan["annual"][:4])-5
    raw={};health=[];data={};base={};accounting={}
    periods=[period(q) for q in range(first*4,qindex(plan["latest"])+1)]
    for ep in gm.FIELDS:
        f=fields(ep);is_statement=ep!="fina_indicator_vip"
        metadata="ts_code,ann_date,end_date,"+("f_ann_date,report_type,comp_type,update_flag," if is_statement else "update_flag,")
        request_fields=",".join(dict.fromkeys((metadata+",".join(f)).split(",")))
        rows=[]
        for year in range(first,int(asof[:4])+1,2):
            params={"ts_code":k,"start_date":str(year)+"0101","end_date":min(str(year+1)+"1231",asof)}
            if is_statement:params["report_type"]="1"
            a=api.ask(ep.removesuffix("_vip"),params,request_fields)
            if len(a)>=100:raise RuntimeError("Single-company financial batch may be truncated")
            if any(x.get("ts_code")!=k for x in a):raise RuntimeError("Unexpected company in response")
            rows.extend(a);time.sleep(.1)
        # Bounded exact-report-period recovery; still only the five test stocks.
        y=int(plan["annual"][:4]);q=qindex(plan["latest"])
        annual={str(z)+"1231" for z in range(y-5,y+1)}
        relevant=annual|{period(z) for z in range(q-16,q+1)} if ep!="balancesheet_vip" else annual|{plan["latest"],plan["prior"]}
        repairs=[]
        for p in sorted(relevant):
            rows,event=repair_period(api,ep,k,p,asof,rows,request_fields)
            if event is not None:repairs.append(event);time.sleep(.15)
        version_events=[]
        for p in periods:
            d,g,f,h=selection(rows,ep,k,p,asof)
            if ep=="fina_indicator_vip" and h["indicator_version"].get("latest_rows",0)>1 and p in relevant:
                version_events.append({"period":p,**h["indicator_version"],"remaining_conflicts":h["growth_conflicts"]})
            if d is not None:data[(ep,p)]=d
            if g is not None:base[(ep,p)]={k:g}
            if f is not None:accounting[(ep,p)]=f
        health.append({"endpoint":ep,"rows":len(rows),"repairs":repairs,"indicator_versions":version_events})
    return data,base,accounting,health
def quote_for(api,k,day,start):
    rows=[]
    for y in range(int(start[:4]),int(day[:4])+1):
        a=api.ask("daily_basic",{"ts_code":k,"start_date":max(start,str(y)+"0101"),"end_date":min(day,str(y)+"1231")},"ts_code,trade_date,close,pe_ttm,pb,total_mv,total_share")
        if len(a)>300 or any(x.get("ts_code")!=k for x in a):raise RuntimeError("Unexpected quote rows")
        rows.extend(a)
    by={};bad=set()
    for v in rows:
        t=gm.valid_date(v.get("trade_date"))
        if not t or t>day:continue
        if t in by and by[t]!=v:bad.add(t)
        by[t]=v
    return {t:v for t,v in by.items() if t not in bad}
def main():
    pa=argparse.ArgumentParser();pa.add_argument("--asof",required=True);pa.add_argument("--output",required=True);pa.add_argument("--growth");a=pa.parse_args()
    asof=gm.valid_date(a.asof)
    if not asof:raise RuntimeError("invalid date")
    plan=gm.period_plan(asof);api=Tushare(os.environ.get("TUSHARE_TOKEN"))
    fixtures=json.loads((ROOT/"growth/public_filing_fixtures.json").read_text())
    start=str(int(asof[:4])-3)+asof[4:6]+"01"
    cal=[]
    for y in range(int(start[:4]),int(asof[:4])+1):
        cal.extend(api.ask("trade_cal",{"exchange":"SSE","start_date":max(start,str(y)+"0101"),"end_date":min(asof,str(y)+"1231"),"is_open":"1"},"cal_date,is_open"))
    day=max(str(x["cal_date"]) for x in cal if str(x.get("is_open"))=="1")
    dates=completed_month_ends(cal,day)
    listings=api.ask("stock_basic",{"list_status":"L"},"ts_code,name,industry,list_date")
    names={r["ts_code"]:r for r in listings}
    cohort=[];peer_date=None
    if a.growth:
        g=json.loads(Path(a.growth).read_text());r=g["report"]
        if r.get("version")=="growth-scanner-v1.4.2" and r.get("asof")==asof and r.get("quote_date")==day and r.get("periods")==plan and r.get("data_coverage_pass") and len(g["rows"])==r.get("complete_metrics"):
            cohort=[v for v in g["rows"] if v.get("valuation",{}).get("share_verified")];peer_date=day
    reports=[];checks=[];health=[]
    for f in fixtures["companies"]:
        k=f["code"];data,base,acc,h=load_company(api,k,asof,plan)
        if get(data,"income_vip",plan["latest"],"comp_type") not in (None,1) or base.get(("income_vip",plan["latest"]),{}).get(k,{}).get("comp_type")!=1:raise RuntimeError("Latest industrial statement unavailable")
        p=profile(data,plan)
        qs=quote_for(api,k,day,start);quote=qs.get(day,{})
        mv=gm.number(quote.get("total_mv"));pe=gm.number(quote.get("pe_ttm"));close=gm.number(quote.get("close"))
        dp=p["ttm"]["deducted_profit"]
        row={"code":k,"name":names.get(k,{}).get("name",f["name"]),"industry":names.get(k,{}).get("industry") or "未分类",
          "market_cap":mv/10000 if mv is not None and mv>0 else None,"pe":pe if pe is not None and pe>0 else None,
          "deducted_pe":mv/10000/dp if mv is not None and mv>0 and dp is not None and dp>0 else None,
          "ocf_ttm":p["ttm"]["cfo"],"revenue_ttm":p["ttm"]["revenue"],"debt_ratio":p["balance"]["debt_ratio"],"roic":p["annual"][-1]["roic"]}
        scan,reason=gm.metrics(k,plan,base,{k:quote})
        q=verified_quote(row,quote,day)
        history=historical(row,q,{t:z.get("pe_ttm") for t,z in qs.items()},dates)
        peers,context=(None,None)
        if scan and cohort:peers,context=peer_reference({**row,**scan},q,cohort)
        row["valuation"]={"close":close,"quote_date":day if quote else None,"share_verified":bool(q and q["share_ok"])}
        y=int(plan["annual"][:4]);years=[str(z)+"1231" for z in range(y-2,y+1)]
        dcf=fe.reconstruct({**row,**scan},{t:v for (ep,t),v in acc.items() if ep=="income_vip"},{t:v for (ep,t),v in acc.items() if ep=="cashflow_vip"},{t:v for (ep,t),v in acc.items() if ep=="balancesheet_vip"},years,plan["latest"],plan["prior"]) if scan else {"status":"unavailable","category":"data","reason":"base_scan_"+reason}
        v={"close":close,"quote_date":day if quote else None,"market_cap":row["market_cap"],"pe":row["pe"],"pb":gm.number(quote.get("pb")),"deducted_pe":row["deducted_pe"],"historical":history,"peer":peers,"industry_context":context,"peer_date":peer_date,"share_verified":row["valuation"]["share_verified"],"pe_history":[{"date":t,"pe":gm.number(qs.get(t,{}).get("pe_ttm"))} for t in dates]}
        # Compare raw FY2025 headline figures to independently sourced prior public filing fixtures.
        fy=next((x for x in p["annual"] if x["period"]==fixtures["period"]),None)
        cc=[]
        for field,key in (("revenue","revenue"),("cfo","cfo"),("assets","assets"),("parent_equity","parent_equity")):
            val=fy.get(field) if fy else None;target=f[key];tol=max(2*f.get("rounding_unit",1),abs(target)*1e-6)
            cc.append({"field":field,"match":val is not None and abs(val*1e8-target)<=tol})
        checks.extend(x["match"] for x in cc)
        report={"code":k,"name":row["name"],"industry":row["industry"],"asof":asof,"report_period":plan["latest"],"profile":p,"valuation":v,
          "growth_scan":{"metrics":scan,"reason":reason,"presets":[z["label"] for z in gm.PRESETS if scan and gm.passes(scan,z["limits"])]},
          "reverse_dcf":dcf,"filing_check":{"period":fixtures["period"],"source":f["source"],"checks":cc}}
        reports.append(report)
        health.append({"annual_revenue_complete":sum(x["revenue"] is not None for x in p["annual"]),"quarter_deducted_complete":sum(x["deducted_profit"] is not None for x in p["quarters"]),"ttm_complete":sum(p["ttm"][x] is not None for x in ("revenue","deducted_profit","cfo","capex")),"historical_pe":history is not None,"peer":peers is not None,"dcf_status":dcf["status"],"dcf_reason":dcf.get("reason"),"quote_verified":v["share_verified"],"raw_batches":h})
        print(json.dumps({"companies_processed":len(reports),"filing_fields_matched":sum(checks),"filing_fields_total":len(checks),"ttm_missing":[x for x in ("revenue","deducted_profit","cfo","capex") if p["ttm"][x] is None],"quarter_deducted_missing":[x["period"] for x in p["quarters"] if x["deducted_profit"] is None],"period_repair":[z for v in h for z in v["repairs"]],"indicator_versions":[z for v in h for z in v["indicator_versions"]],"dcf_status":dcf["status"],"dcf_reason":dcf.get("reason")},ensure_ascii=False),flush=True)
    validation={"version":VERSION,"asof":asof,"quote_date":day,"report_period":plan["latest"],"companies":len(reports),
        "filing_fields_matched":sum(checks),"filing_fields_total":len(checks),"peer_source_date":peer_date,
        "annual_revenue_complete":sum(x["annual_revenue_complete"]==5 for x in health),"quarter_deducted_complete":sum(x["quarter_deducted_complete"]==12 for x in health),
        "ttm_complete":sum(x["ttm_complete"]==4 for x in health),"historical_pe_available":sum(x["historical_pe"] for x in health),
        "peer_available":sum(x["peer"] for x in health),"dcf_eligible":sum(x["dcf_status"]=="ok" for x in health),"dcf_unique":sum(any(z["status"]=="ok" for z in r["reverse_dcf"].get("sensitivity",[])) for r in reports),
        "quotes_verified":sum(x["quote_verified"] for x in health),"dcf_reasons":dict(__import__("collections").Counter(x["dcf_reason"] or x["dcf_status"] for x in health)),
        "exact_period_repair_attempts":sum(len(v["repairs"]) for x in health for v in x["raw_batches"]),
        "exact_period_repairs_resolved":sum(bool(z["before"]) and not z["after"] for x in health for v in x["raw_batches"] for z in v["repairs"]),
        "indicator_revision_periods":sum(z["revision_selected"] for x in health for v in x["raw_batches"] for z in v["indicator_versions"]),
        "indicator_conflict_periods":sum(bool(z["remaining_conflicts"]) for x in health for v in x["raw_batches"] for z in v["indicator_versions"]),
        "unresolved_core_fields":dict(__import__("collections").Counter(z["endpoint"]+":"+f for x in health for v in x["raw_batches"] for z in v["repairs"] for f in z["after"])),
        "notes":["Five-company prototype, not market-wide. Latest common statutory report period; current revised financial statements, not point-in-time history.","Cash conversion uses consolidated net profit, FCF proxy is CFO minus capex. Missing and nonpositive denominators are not zero. Quarter flows are cumulative differences.","Descriptive acceleration label only; not V1.0 trading signal; risk flags are review prompts, not calibrated predictions.","Historical PE positive months only; peer reference from same-date growth snapshot if available; frozen V1.4.2 reverse DCF may be unavailable. Public filing fixture check only four raw values per company."]}
    out=Path(a.output);out.mkdir(parents=True,exist_ok=True)
    (out/"snapshot.json").write_text(json.dumps({"report":validation,"companies":reports},ensure_ascii=False,separators=(",",":"),allow_nan=False))
    (out/"validation.json").write_text(json.dumps(validation,ensure_ascii=False,indent=2,allow_nan=False))
    print(json.dumps({"company_validation":validation},ensure_ascii=False),flush=True)
    if sum(checks)!=len(checks) or validation["ttm_complete"]!=len(reports) or validation["quotes_verified"]!=len(reports):raise RuntimeError("Prototype headline reconciliation or TTM/quote coverage failed")
if __name__=="__main__":main()
