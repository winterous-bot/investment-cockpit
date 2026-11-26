"""Historical exploratory cohort study and current snapshot. Never write raw vendor rows to Git."""
from __future__ import annotations
import argparse,sys,os,json,time,statistics,bisect
from pathlib import Path
from collections import Counter
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/"scripts"))
from tushare_5000 import Tushare,SafeAPIError,POINTS
from acceleration_model import *
POINTS.update({k:5000 for k in FIELDS})
def fetch(api,ep,q):
    p=period(q);params={"period":p}
    statement=ep!="fina_indicator_vip"
    if statement:params["report_type"]="1"
    fields="ts_code,ann_date,end_date,"+("f_ann_date,report_type," if statement else "")+",".join(FIELDS[ep])
    raw=api.ask(ep,params,fields);first=len(raw);offset=first;pages=1;pagination="not_needed"
    if first>=3000:
        for _ in range(8):
            try:more=api.ask(ep,{**params,"offset":offset,"limit":min(first,5000)},fields)
            except SafeAPIError:pagination="unsupported";break
            if not more:pagination="end";break
            seen={json.dumps(v,sort_keys=True) for v in raw};new=[v for v in more if json.dumps(v,sort_keys=True) not in seen]
            if not new:pagination="repeated";break
            raw.extend(new);offset+=len(more);pages+=1;pagination="advanced"
            if len(more)<min(first,5000):break
    return raw,{"endpoint":ep,"period":p,"first":first,"rows":len(raw),"pages":pages,"pagination":pagination}
def market_day(api,day):
    # End-of-day actual price and vendor adjustment factors. No forward fill.
    q=api.ask("daily_basic",{"trade_date":day},"ts_code,trade_date,close,pe_ttm,total_mv")
    a=api.ask("adj_factor",{"trade_date":day},"ts_code,trade_date,adj_factor")
    def unique(rows):
        out={};bad=set()
        for x in rows:
            k=x.get("ts_code")
            if not isinstance(k,str) or not k.endswith((".SH",".SZ")) or str(x.get("trade_date"))!=day:continue
            if k in out and out[k]!=x:bad.add(k)
            out[k]=x
        return {k:v for k,v in out.items() if k not in bad}
    q,a=unique(q),unique(a)
    vals={}
    for k,x in q.items():
        c=num(x.get("close"));f=num(a.get(k,{}).get("adj_factor"))
        if c is not None and f is not None and c>0 and f>0:vals[k]=c*f
    return vals,{"day":day,"quotes":len(q),"adjusted":len(vals)},q
def summarize(cohorts):
    result={}
    for name in ("early","sustained","union"):
        result[name]={}
        for metric in ("next_q_growth","second_q_growth","return20","return60"):
            obs=[c["groups"][name][metric] for c in cohorts if metric in c["groups"][name]]
            ok=[z for z in obs if z["coverage_pass"]]
            def med(key):return statistics.median([z[key] for z in ok]) if ok else None
            result[name][metric]={"cohorts_total":len(obs),"cohorts_valid":len(ok),"signal_n":sum(z["n"] for z in obs),
              "observed":sum(z["observed"] for z in obs),"baseline_observed":sum(z["baseline_observed"] for z in obs),
              "overlap":sum(z["overlap"] for z in obs),"median_cohort_signal_median":med("signal_median"),
              "median_cohort_baseline_median":med("baseline_median"),
              "median_cohort_median_gap":med("median_gap"),"median_cohort_mean_gap":med("mean_gap"),
              "positive_median_gap_cohorts":sum(z["median_gap"]>0 for z in ok),
              "equal_cohort_mean_gap":statistics.mean([z["mean_gap"] for z in ok]) if ok else None}
    return result
def main():
    pa=argparse.ArgumentParser();pa.add_argument("--asof",required=True);pa.add_argument("--output",required=True);pa.add_argument("--first",default="20220331");args=pa.parse_args()
    asof=valid_date(args.asof)
    if not asof:raise RuntimeError("invalid asof")
    last=latest_common(asof);first=qindex(args.first)
    api=Tushare(os.environ.get("TUSHARE_TOKEN"));raw={};health=[];errors=[]
    # Cash flow only required since first signal minus 4 quarters; other data minus 7.
    for q in range(first-7,last+1):
        for ep in FIELDS:
            if ep=="cashflow_vip" and q<first-4:continue
            try:
                data,h=fetch(api,ep,q);raw[(ep,q)]=data;health.append(h)
            except SafeAPIError:errors.append({"endpoint":ep,"period":period(q)})
        time.sleep(.2)
    if errors:raise RuntimeError("Missing required financial batches: "+json.dumps(errors))
    def get(q,known,signal=True):
        d={};info=[]
        for t in range(q-(7 if signal else 5),q+1):
            for ep in (FIELDS if signal else ("income_vip","fina_indicator_vip")):
                if (ep,t) not in raw:continue
                s,h=select(raw[(ep,t)],ep,period(t),known);d[(ep,t)]=s
                info.append({"endpoint":ep,"period":period(t),**h})
        return d,info
    # Current metadata only used in the current screen, never historic membership.
    st=api.ask("stock_basic",{"list_status":"L"},"ts_code,name,industry,list_date")
    names={x["ts_code"]:x for x in st if str(x.get("ts_code","")).endswith((".SH",".SZ")) and "ST" not in str(x.get("name","")).upper() and "退" not in str(x.get("name",""))}
    if len(names)<4500:raise RuntimeError("Current listings incomplete")
    cal=api.ask("trade_cal",{"exchange":"SSE","start_date":cutoff(first),"end_date":asof,"is_open":"1"},"cal_date,is_open")
    days=sorted({str(z["cal_date"]) for z in cal if str(z.get("is_open"))=="1"})
    if len(days)<900 or not days:raise RuntimeError("Trade calendar incomplete")
    market_cache={};market_health=[];market_errors=[]
    def prices(day):
        if day not in market_cache:
            try:
                v,h,_=market_day(api,day);market_health.append(h)
                market_cache[day]=v if h["adjusted"]>=3000 else {}
            except SafeAPIError:
                market_errors.append(day);market_cache[day]={}
        return market_cache[day]
    cohorts=[]
    for q in range(first,last+1):
        if q%4==3:continue
        known=cutoff(q)
        d,h=get(q,known);rows,scan_h=scan(d,q)
        rec={"period":period(q),"asof":known,"scan":scan_h,"coverage":h,"groups":{}}
        # Common eligible universe and identical cohort size; price never drives selection.
        gr=groups(rows);entry=bisect.bisect_right(days,known)
        outcomes={}
        for step,label in ((1,"next_q_growth"),(2,"second_q_growth")):
            if q+step<=last and cutoff(q+step)<=asof:
                future,_=get(q+step,cutoff(q+step),False)
                outcomes[label]={x["code"]:outcome(future,x["code"],q+step) for x in rows}
        for step,label in ((20,"return20"),(60,"return60")):
            if entry+step<len(days):
                a,b=prices(days[entry]),prices(days[entry+step])
                outcomes[label]={x["code"]:b[x["code"]]/a[x["code"]]-1 for x in rows if x["code"] in a and x["code"] in b}
                rec[label+"_dates"]=[days[entry],days[entry+step]]
        for name,(sig,base) in gr.items():
            rec["groups"][name]={label:paired_stats(sig,base,v) for label,v in outcomes.items()}
            rec["groups"][name]["signals"]=len(sig)
        cohorts.append(rec)
        print(json.dumps({"cohort":period(q),"eligible":len(rows),"signals":scan_h["signals"]}),flush=True)
    d,h=get(last,asof);rows,cur=scan(d,last,names)
    if cur["scope"]<.85*len(names) or cur["quality_eligible"]<100 or any(t["selected"]<3000 for t in h):raise RuntimeError("Current financial coverage insufficient")
    _,mh,quotes=market_day(api,days[-1])
    if mh["quotes"]<.9*len(names):raise RuntimeError("Current quote coverage insufficient")
    current=[]
    for x in rows:
        if not x["signal"]:continue
        k=x["code"];z=names[k];v=quotes.get(k,{})
        current.append({**x,"name":z.get("name",k),"industry":z.get("industry") or "未分类",
          "close":num(v.get("close")),"pe":num(v.get("pe_ttm")),"market_cap":num(v.get("total_mv"))/10000 if num(v.get("total_mv")) is not None else None})
    current.sort(key=lambda x:(-x["acceleration"],x["code"]))
    report={"version":VERSION,"asof":asof,"quote_date":days[-1],"report_period":period(last),
       "params":PARAMS,"current_scan":cur,"current_financial_coverage":h,"current_quote_health":mh,
       "historical_first":period(first),"historical_last":period(last),"cohorts":cohorts,
       "summary":summarize(cohorts),"financial_batches":health,"market_batches":market_health,
       "market_errors":market_errors,"notes":["Exploratory historical cross-section; vendor revisions and backfills may remain even with announcement-date gating. Not audited PIT.",
       "Historical scope uses period financial records, not current listed survivors. Historical ST, IPO eligibility, price limits, suspensions, delisting proceeds and industry histories not independently reconstructed.",
       "Only positive-profit comparable quarters, prior-year profit >=10m and margin >=1%; cash and revenue/margin quality gates applied to both acceleration and growth baseline.",
       "Entry next trading day's close after common statutory cutoff; adjusted-close gross holding returns 20/60 trading sessions, no costs or trading feasibility claims. Missing endpoints not imputed; cohort statistics require >=80% observation in both groups.",
       "Future disclosed profit growth from next or second quarter; future losses retained. Q4 and Q1 may become known at same cutoff. No independent test split or calibrated predictive claim."]}
    out=Path(args.output);out.mkdir(parents=True,exist_ok=True)
    (out/"snapshot.json").write_text(json.dumps({"report":report,"rows":current},ensure_ascii=False,separators=(",",":"),allow_nan=False))
    (out/"validation.json").write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False))
    print(json.dumps({"acceleration_summary":report["summary"],"current_scan":cur,"financial_batches":len(health),"market_batches":len(market_health),"market_errors":market_errors,"current_signals":len(current)},ensure_ascii=False),flush=True)
if __name__=="__main__":main()
