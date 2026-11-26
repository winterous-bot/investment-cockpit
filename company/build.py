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
def load_company(api,k,asof,plan):
    # Calendar-year slices avoid per-request row caps. Statements use announcement
    # dates; fina_indicator uses report periods. Both get announcement-date gating.
    first=int(plan["annual"][:4])-5
    raw={};health=[]
    for ep in gm.FIELDS:
        f=fields(ep);is_statement=ep!="fina_indicator_vip"
        metadata="ts_code,ann_date,end_date,"+("f_ann_date,report_type,comp_type,update_flag," if is_statement else "")
        request_fields=",".join(dict.fromkeys((metadata+",".join(f)).split(",")))
        rows=[]
        for year in range(first,int(asof[:4])+1,2):
            params={"ts_code":k,"start_date":str(year)+"0101","end_date":min(str(year+1)+"1231",asof)}
            if is_statement:params["report_type"]="1"
            a=api.ask(ep.removesuffix("_vip"),params,request_fields)
            if len(a)>=100:raise RuntimeError("Single-company financial batch may be truncated")
            if any(x.get("ts_code")!=k for x in a):raise RuntimeError("Unexpected company in response")
            rows.extend(a);time.sleep(.1)
        raw[ep]=rows
        health.append({"endpoint":ep,"rows":len(rows)})
    # Use frozen growth selector for scanner metrics; separate conservative
    # same-day selection for profile and exact frozen accounting fields for DCF.
    data={};base={};accounting={}
    periods=[period(q) for q in range(first*4,qindex(plan["latest"])+1)]
    for ep,rows in raw.items():
        for p in periods:
            r=[x for x in rows if x.get("end_date")==p]
            d,h=gm.select(r,ep,p,asof)
            if k in d:base[(ep,p)]={k:d[k]}
            if ep in fe.FIELDS:
                f,h=fe.pick(r,p,asof,fe.FIELDS[ep])
                if k in f:accounting[(ep,p)]=f[k]
                ff,h=fe.pick(r,p,asof,fields(ep))
                if k in ff:data[(ep,p)]=ff[k]
            else:
                if k in d:data[(ep,p)]=d[k]
    # Retain exact core profile values when only an extra-field conflict exists,
    # never merge distinct records across dates. Fall back to the independently
    # selected frozen accounting row as a whole, with unavailable extras.
    for key,v in accounting.items():
        if key not in data:data[key]=v
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
            cohort=g["rows"];peer_date=day
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
        dcf=fe.reconstruct(row,{t:v for (ep,t),v in acc.items() if ep=="income_vip"},{t:v for (ep,t),v in acc.items() if ep=="cashflow_vip"},{t:v for (ep,t),v in acc.items() if ep=="balancesheet_vip"},years,plan["latest"],plan["prior"])
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
        print(json.dumps({"companies_processed":len(reports),"filing_fields_matched":sum(checks),"filing_fields_total":len(checks)},ensure_ascii=False),flush=True)
    validation={"version":VERSION,"asof":asof,"quote_date":day,"report_period":plan["latest"],"companies":len(reports),
        "filing_fields_matched":sum(checks),"filing_fields_total":len(checks),"peer_source_date":peer_date,
        "annual_revenue_complete":sum(x["annual_revenue_complete"]==5 for x in health),"quarter_deducted_complete":sum(x["quarter_deducted_complete"]==12 for x in health),
        "ttm_complete":sum(x["ttm_complete"]==4 for x in health),"historical_pe_available":sum(x["historical_pe"] for x in health),
        "peer_available":sum(x["peer"] for x in health),"dcf_eligible":sum(x["dcf_status"]=="ok" for x in health),"dcf_unique":sum(any(z["status"]=="ok" for z in r["reverse_dcf"].get("sensitivity",[])) for r in reports),
        "quotes_verified":sum(x["quote_verified"] for x in health),"dcf_reasons":dict(__import__("collections").Counter(x["dcf_reason"] or x["dcf_status"] for x in health)),
        "notes":["Five-company prototype, not market-wide. Latest common statutory report period; current revised financial statements, not point-in-time history.","Cash conversion uses consolidated net profit, FCF proxy is CFO minus capex. Missing and nonpositive denominators are not zero. Quarter flows are cumulative differences.","Descriptive acceleration label only; not V1.0 trading signal; risk flags are review prompts, not calibrated predictions.","Historical PE positive months only; peer reference from same-date growth snapshot if available; frozen V1.4.2 reverse DCF may be unavailable. Public filing fixture check only four raw values per company."]}
    out=Path(a.output);out.mkdir(parents=True,exist_ok=True)
    (out/"snapshot.json").write_text(json.dumps({"report":validation,"companies":reports},ensure_ascii=False,separators=(",",":"),allow_nan=False))
    (out/"validation.json").write_text(json.dumps(validation,ensure_ascii=False,indent=2,allow_nan=False))
    print(json.dumps({"company_validation":validation},ensure_ascii=False),flush=True)
    if sum(checks)!=len(checks) or validation["ttm_complete"]!=len(reports) or validation["quotes_verified"]!=len(reports):raise RuntimeError("Prototype headline reconciliation or TTM/quote coverage failed")
if __name__=="__main__":main()
