"""Watchlist-only orchestration of the validated V1.0 financial engine.
All input/output private in runner temp; only encrypted files may be published.
"""
from __future__ import annotations
import sys,os,json,argparse
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/"company")]
from company.build import (gm,fe,Tushare,SafeAPIError,load_company,quote_for,completed_month_ends,verified_quote,historical,peer_reference,profile,get)
from datetime import datetime,timedelta
from collections import Counter
import re
MAX_STOCKS=20
CODE=re.compile(r"^[0-9]{6}\.(SH|SZ)$")
def valid_codes(codes):
    if not isinstance(codes,list) or len(codes)>MAX_STOCKS or any(not isinstance(k,str) or not CODE.fullmatch(k) for k in codes) or len(set(codes))!=len(codes):raise ValueError("Invalid watchlist codes")
    return codes
def company_report(api,f,asof,plan,day,start,dates,names,cohort,peer_date,fixtures,fixture):
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
    fy=next((x for x in p["annual"] if x["period"]==fixtures["period"]),None) if fixture else None
    cc=[]
    for field,key in (("revenue","revenue"),("cfo","cfo"),("assets","assets"),("parent_equity","parent_equity")) if fixture else ():
        val=fy.get(field) if fy else None;target=fixture[key];tol=max(2*fixture.get("rounding_unit",1),abs(target)*1e-6)
        cc.append({"field":field,"match":val is not None and abs(val*1e8-target)<=tol})
    report={"code":k,"name":row["name"],"industry":row["industry"],"asof":asof,"report_period":plan["latest"],"profile":p,"valuation":v,
      "growth_scan":{"metrics":scan,"reason":reason,"presets":[z["label"] for z in gm.PRESETS if scan and gm.passes(scan,z["limits"])]},
      "reverse_dcf":dcf,"filing_check":{"period":fixtures["period"],"source":fixture["source"],"checks":cc} if fixture else None}

    return report
def main():
    p=argparse.ArgumentParser();p.add_argument("--asof",required=True);p.add_argument("--request",required=True);p.add_argument("--output",required=True);p.add_argument("--growth");a=p.parse_args()
    codes=valid_codes(json.loads(Path(a.request).read_text())["codes"])
    asof=gm.valid_date(a.asof)
    if not asof:raise RuntimeError("Invalid asof")
    api=Tushare(os.environ.get("TUSHARE_TOKEN"));plan=gm.period_plan(asof)
    # Full-market name lookup only; no full-market company statement requests.
    listings=api.ask("stock_basic",{"list_status":"L"},"ts_code,name,industry,list_date")
    names={r["ts_code"]:r for r in listings if CODE.fullmatch(str(r.get("ts_code",""))) and isinstance(r.get("name"),str) and r["name"]}
    if len(names)<4500:raise RuntimeError("Stock directory coverage inadequate")
    directory=[{"code":k,"name":r["name"],"industry":r.get("industry") or "未分类"} for k,r in sorted(names.items())]
    fixtures=json.loads((ROOT/"growth/public_filing_fixtures.json").read_text())
    fixture_by={f["code"]:f for f in fixtures["companies"]}
    out=Path(a.output);out.mkdir(parents=True,exist_ok=True)
    (out/"directory.json").write_text(json.dumps(directory,ensure_ascii=False))
    if not codes:
        (out/"results.json").write_text(json.dumps({"asof":asof,"quote_date":None,"entries":[]}))
        print(json.dumps({"requested":0,"ready":0,"directory_count":len(directory)}));return
    start=str(int(asof[:4])-3)+asof[4:6]+"01"
    cal=[]
    for y in range(int(start[:4]),int(asof[:4])+1):
        cal.extend(api.ask("trade_cal",{"exchange":"SSE","start_date":max(start,str(y)+"0101"),"end_date":min(asof,str(y)+"1231"),"is_open":"1"},"cal_date,is_open"))
    day=max(str(x["cal_date"]) for x in cal if str(x.get("is_open"))=="1")
    dates=completed_month_ends(cal,day);cohort=[];peer_date=None
    if a.growth:
        g=json.loads(Path(a.growth).read_text());r=g["report"]
        if r.get("version")=="growth-scanner-v1.4.2" and r.get("asof")==asof and r.get("quote_date")==day and r.get("periods")==plan and r.get("data_coverage_pass") and len(g["rows"])==r.get("complete_metrics"):
            cohort=[v for v in g["rows"] if v.get("valuation",{}).get("share_verified")];peer_date=day
    results=[]
    for i,k in enumerate(codes):
        f={"code":k,"name":names.get(k,{}).get("name",k)}
        if k not in names:
            results.append({"code":k,"status":"unsupported","reason":"not_currently_listed_shsz"});continue
        try:
            x=company_report(api,f,asof,plan,day,start,dates,names,cohort,peer_date,fixtures,fixture_by.get(k))
            core=x["profile"]["ttm"];quote=x["valuation"]
            if any(core.get(v) is None for v in ("revenue","deducted_profit","cfo","capex")):
                results.append({"code":k,"status":"incomplete","reason":"ttm_core_missing"});continue
            if not quote.get("share_verified"):
                results.append({"code":k,"status":"incomplete","reason":"same_day_quote_unverified"});continue
            # V1.0 cross-checks remain hard gates for known sample companies.
            if x["filing_check"] and not all(v["match"] for v in x["filing_check"]["checks"]):
                results.append({"code":k,"status":"incomplete","reason":"public_filing_check_failed"});continue
            (out/("company-"+str(i)+".json")).write_text(json.dumps(x,ensure_ascii=False,allow_nan=False,separators=(",",":")))
            results.append({"code":k,"status":"ready","file":"company-"+str(i)+".json","asof":asof,"quote_date":day})
        except SafeAPIError:
            results.append({"code":k,"status":"failed","reason":"vendor_api_error"})
        except (ValueError,RuntimeError,KeyError,TypeError,ArithmeticError):
            results.append({"code":k,"status":"failed","reason":"statement_or_calculation_unavailable"})
        # No stock codes, names, raw data or financial figures in public logs.
        print(json.dumps({"processed":i+1,"requested":len(codes),"ready":sum(z["status"]=="ready" for z in results)}),flush=True)
    (out/"results.json").write_text(json.dumps({"asof":asof,"quote_date":day,"entries":results},ensure_ascii=False))
    print(json.dumps({"requested":len(codes),"ready":sum(z["status"]=="ready" for z in results),"status_counts":dict(Counter(z["status"] for z in results)),"directory_count":len(directory),"peer_available":peer_date is not None}),flush=True)
if __name__=="__main__":main()
