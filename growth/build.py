#!/usr/bin/env python3
"""Personal current cross-section scanner. Never commit vendor rows or plaintext."""
from __future__ import annotations
import argparse,os,sys,json,time,math
from pathlib import Path
from collections import Counter
from datetime import datetime,timedelta
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"scripts"))
from tushare_5000 import Tushare,SafeAPIError,POINTS
from growth_model import period_plan,select,metrics,passes,DEFAULT,QUALITY,FIELDS,valid_date
POINTS.update({k:5000 for k in FIELDS})
def fetch_period(api,endpoint,p,asof,eligible):
    base={"period":p}
    # Explicit consolidated cumulative statements only.
    if endpoint!="fina_indicator_vip":base["report_type"]="1"
    fields="ts_code,ann_date,end_date,"+("f_ann_date,report_type," if endpoint!="fina_indicator_vip" else "")+",".join(FIELDS[endpoint])
    raw=api.ask(endpoint,base,fields)
    first=len(raw);selected,health=select(raw,endpoint,p,asof)
    pages=1; pagination="not_needed"
    # APIs vary in their batch limits. Test offset only if batch looks capped
    # or misses expected companies. Never assume unsupported pagination works.
    coverage=lambda s:len(eligible&set(s))/max(1,len(eligible))
    if first and (first>=4500 or coverage(selected)<.985):
        offset=first;pagination="attempted"
        for _ in range(6):
            try:more=api.ask(endpoint,{**base,"offset":offset,"limit":min(first,5000)},fields)
            except SafeAPIError:pagination="unsupported";break
            if not more:pagination="end";break
            before={json.dumps(r,sort_keys=True,ensure_ascii=False) for r in raw}
            new=[r for r in more if json.dumps(r,sort_keys=True,ensure_ascii=False) not in before]
            if not new:pagination="repeated_page";break
            raw.extend(new);pages+=1;offset+=len(more)
            selected,health=select(raw,endpoint,p,asof);pagination="progress"
            if len(more)<min(first,5000):break
    # Bounded, per-stock completion using the documented non-VIP API.
    # If coverage remains insufficient, report it instead of claiming full-market.
    miss=sorted(eligible-set(selected))
    fallback=0;fallback_errors=0
    if 0<len(miss)<=80:
        single=endpoint.removesuffix("_vip");POINTS[single]=2000
        for k in miss:
            try:
                x=api.ask(single,{**base,"ts_code":k},fields,retry=1);raw.extend(x);fallback+=1
            except SafeAPIError:fallback_errors+=1
            time.sleep(.25)
        selected,health=select(raw,endpoint,p,asof)
    health.update({"endpoint":endpoint,"period":p,"first_rows":first,"pages":pages,"pagination":pagination,"fallback_queries":fallback,"fallback_errors":fallback_errors,"eligible":len(eligible),"covered":len(eligible&set(selected)),"coverage":round(coverage(selected),4)})
    return selected,health
def main():
    p=argparse.ArgumentParser();p.add_argument("--asof",required=True);p.add_argument("--output",required=True);a=p.parse_args()
    asof=valid_date(a.asof)
    if not asof:raise RuntimeError("invalid date")
    api=Tushare(os.environ.get("TUSHARE_TOKEN"));plan=period_plan(asof)
    cal=api.ask("trade_cal",{"exchange":"SSE","start_date":(datetime.strptime(asof,"%Y%m%d")-timedelta(days=20)).strftime("%Y%m%d"),"end_date":asof,"is_open":"1"},"cal_date,is_open")
    dates=sorted({str(x["cal_date"]) for x in cal if str(x.get("is_open"))=="1"})
    if not dates:raise RuntimeError("no trading calendar")
    quote_day=dates[-1]
    listed=api.ask("stock_basic",{"list_status":"L"},"ts_code,name,industry,list_date,market")
    stocks={r["ts_code"]:r for r in listed if str(r.get("ts_code","")).endswith((".SH",".SZ"))}
    if len(stocks)<4500:raise RuntimeError("listed coverage insufficient")
    # Listed before first comparison fiscal year; excludes recent IPOs, ST and delisting names.
    start=plan["annual_base"][:4]+"0101"
    names={k:r for k,r in stocks.items() if valid_date(r.get("list_date")) and r["list_date"]<=start and "ST" not in str(r.get("name","")).upper() and "退" not in str(r.get("name",""))}
    q=api.ask("daily_basic",{"trade_date":quote_day},"ts_code,trade_date,pe_ttm,total_mv")
    quotes={r["ts_code"]:r for r in q if str(r.get("trade_date"))==quote_day and r.get("ts_code") in stocks}
    if len(quotes)<.90*len(stocks):raise RuntimeError("valuation cross section incomplete")
    # First fetch latest income; identify industrial/commercial businesses from report type.
    data={};health=[];failures=[]
    latest=plan["latest"]
    try:
        d,h=fetch_period(api,"income_vip",latest,asof,set(names));data[("income_vip",latest)]=d;health.append(h)
    except SafeAPIError:
        d={};failures.append({"endpoint":"income_vip","period":latest})
    eligible={k for k in names if d.get(k,{}).get("comp_type")==1}
    unknown_type=len([k for k in names if d.get(k,{}).get("comp_type") is None])
    # Test all four VIP interfaces independently even if one fails.
    target=eligible or set(names)
    req={
      "income_vip":{plan["annual"],plan["annual_base"],plan["prior"]},
      "fina_indicator_vip":{plan[k] for k in ("annual","annual_prior","latest","prior","prior2")},
      "cashflow_vip":{plan[k] for k in ("annual","latest","prior")},
      "balancesheet_vip":{latest}}
    for endpoint,periods in req.items():
        for p0 in sorted(periods):
            try:
                d,h=fetch_period(api,endpoint,p0,asof,target);data[(endpoint,p0)]=d;health.append(h)
            except SafeAPIError:failures.append({"endpoint":endpoint,"period":p0})
    rows=[];excluded=Counter()
    for code in sorted(eligible):
        x,reason=metrics(code,plan,data,quotes);excluded[reason]+=1
        if x is None:continue
        r=names[code]
        rows.append({"code":code,"name":str(r.get("name") or code),"industry":str(r.get("industry") or "未分类"),**x})
    # Separate calculable financial quality from scope completeness.
    completeness=bool(eligible and not failures and not unknown_type>len(names)*.03
        and all(h["coverage"]>=.90 for h in health))
    quality=[x for x in rows if passes(x)]
    valued=[x for x in quality if passes(x,valuation=True)]
    report={"version":"growth-scanner-v1.0","asof":asof,"quote_date":quote_day,"periods":plan,
      "listed_shsz":len(stocks),"eligible_by_list_date_and_name":len(names),"industrial_commercial":len(eligible),
      "company_type_missing":unknown_type,"eligible_financial_or_other":len(names)-len(eligible)-unknown_type,
      "quote_coverage":len(quotes),"complete_metrics":len(rows),"exclusions":dict(excluded),
      "quality_pass":len(quality),"quality_and_valuation_pass":len(valued),"default_limits":DEFAULT,
      "data_coverage_pass":completeness,"api_batches":health,"failed_batches":failures,
      "notes":["Current disclosed statements only; vendor revision and duplicate limitations; not a historical backtest.",
       "Shanghai/Shenzhen currently listed, excluding ST/delisting and IPOs after base-year start; financial businesses excluded.",
       "Latest common statutory period, not necessarily latest individual disclosure. Full annual ROIC, no annualization of cumulative quarterly ROIC.",
       "PE-TTM vendor reported, valuation optional; deducted PE shown separately. CFO denominator consolidated net profit.",
       "No positive alpha claim; thresholds exploratory; incomplete coverage not represented as complete market scan.",
       "Only aggregated health printed. All individual metrics encrypted; no raw statement rows retained."]}
    out=Path(a.output);out.mkdir(parents=True,exist_ok=True)
    (out/"validation.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf8")
    (out/"snapshot.json").write_text(json.dumps({"report":report,"rows":rows},ensure_ascii=False,separators=(",",":"),allow_nan=False),encoding="utf8")
    print(json.dumps(report,ensure_ascii=False,separators=(",",":")))
if __name__=="__main__":main()
