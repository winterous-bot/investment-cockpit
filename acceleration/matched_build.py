"""V1.1: matched historical research, no model tuning or individual data output."""
import argparse,sys,os,json,bisect,time
from pathlib import Path
from collections import Counter
from build import fetch,market_day,Tushare,SafeAPIError,POINTS
from acceleration_model import *
from matching import industry_at,attributes,match,paired,sampled_drawdown,summarize,decision
POINTS["index_member_all"]=2000
DESIGNS=("strict","growth_only")
GROUPS=("early","sustained","union")
def memberships(api):
    cs=api.ask("index_classify",{"level":"L1","src":"SW2021"},"index_code,level,is_pub")
    codes=sorted({str(z["index_code"]) for z in cs if z.get("level")=="L1" and str(z.get("is_pub","1")) not in ("0","False")})
    if len(codes)!=31 or any(not k.endswith(".SI") or not k.split(".")[0].isdigit() for k in codes):raise RuntimeError("Historical industry taxonomy invalid: expected full SW2021 index codes")
    out=[];health=[]
    for k in codes:
        for flag in ("Y","N"):
            params={"l1_code":k,"is_new":flag}
            fields="l1_code,ts_code,in_date,out_date,is_new"
            rows=api.ask("index_member_all",params,fields)
            first=len(rows);offset=first;pages=1;complete=first<2000
            while not complete and pages<10:
                more=api.ask("index_member_all",{**params,"offset":offset,"limit":2000},fields)
                if not more:complete=True;break
                seen={json.dumps(v,sort_keys=True) for v in rows}
                fresh=[v for v in more if json.dumps(v,sort_keys=True) not in seen]
                if not fresh:break
                rows.extend(fresh);offset+=len(more);pages+=1
                if len(more)<2000:complete=True
            if not complete:raise RuntimeError("Industry membership pagination incomplete: "+k+" "+flag)
            if any(str(v.get("l1_code",""))!=k or v.get("is_new")!=flag for v in rows):raise RuntimeError("Industry membership filter mismatch")
            out.extend(rows);health.append({"industry":k,"flag":flag,"rows":len(rows),"pages":pages})
            time.sleep(.1)
    # A successful API status with empty payload is not successful data retrieval.
    if any(h["flag"]=="Y" and h["rows"]==0 for h in health) or not any(h["flag"]=="N" and h["rows"]>0 for h in health):raise RuntimeError("Missing current or historical SW2021 constituents")
    return out,health
def main():
    pa=argparse.ArgumentParser();pa.add_argument("--asof",required=True);pa.add_argument("--output",required=True);args=pa.parse_args()
    asof=valid_date(args.asof)
    if not asof:raise RuntimeError("invalid asof")
    first=qindex("20220331");last=latest_common(asof)
    api=Tushare(os.environ.get("TUSHARE_TOKEN"))
    member,member_health=memberships(api)
    print(json.dumps({"membership_batches":len(member_health),"membership_records":len(member),"historical_records":sum(r.get("is_new")=="N" for r in member)}),flush=True)
    industry_preflight=[{"period":period(q),"cutoff":cutoff(q),"active_unique":len(industry_at(member,cutoff(q)))} for q in range(first,last+1) if q%4!=3]
    print(json.dumps({"industry_preflight":industry_preflight}),flush=True)
    if any(v["active_unique"]<2500 for v in industry_preflight):raise RuntimeError("Historical SW2021 coverage too low; stop before paid financial scan")
    raw={};health=[]
    for q in range(first-7,last+1):
        for ep in FIELDS:
            if ep=="cashflow_vip" and q<first-4:continue
            a,h=fetch(api,ep,q);raw[(ep,q)]=a;health.append(h)
        time.sleep(.2)
    def get(q,known,signal=True):
        d={};info=[]
        for t in range(q-(7 if signal else 5),q+1):
            for ep in (FIELDS if signal else ("income_vip","fina_indicator_vip")):
                if (ep,t) not in raw:continue
                s,h=select(raw[(ep,t)],ep,period(t),known);d[(ep,t)]=s;info.append(h)
        return d,info
    cal=[]
    for y in range(2022,int(asof[:4])+1):
        cal.extend(api.ask("trade_cal",{"exchange":"SSE","start_date":str(y)+"0101","end_date":min(str(y)+"1231",asof),"is_open":"1"},"cal_date,is_open"))
    days=sorted({str(z["cal_date"]) for z in cal if str(z.get("is_open"))=="1"})
    if len(days)<900:raise RuntimeError("Trade calendar incomplete")
    cache={};market_health=[];market_errors=[]
    def market(day):
        if day not in cache:
            try:
                a,h,b=market_day(api,day);market_health.append(h)
                cache[day]=(a,b) if h["adjusted"]>=3000 and h["quotes"]>=3000 else ({},{})
            except SafeAPIError:
                market_errors.append(day);cache[day]=({}, {})
        return cache[day]
    cohorts=[]
    for q in range(first,last+1):
        if q%4==3:continue
        known=cutoff(q);data,h=get(q,known);rows,scan_h=scan(data,q)
        if any(t["selected"]<2500 for t in h) or scan_h["scope"]<3000:raise RuntimeError("Historical financial coverage insufficient: "+period(q))
        entry=bisect.bisect_right(days,known)
        if entry<1 or entry>=len(days):raise RuntimeError("No matching date")
        price_date=days[entry-1]
        _,quotes=market(price_date);industries=industry_at(member,known)
        rows=[attributes(x,quotes,industries) for x in rows]
        rec={"period":period(q),"asof":known,"matching_quote_date":price_date,"entry_date":days[entry],"scan":scan_h,
             "attribute_coverage":{"eligible":len(rows),"industry":sum(bool(x["industry"]) for x in rows),"cap":sum(x["cap"] is not None for x in rows),"positive_pe":sum(x["pe"] is not None for x in rows)},
             "designs":{}}
        pair_sets={};used=set()
        for design in DESIGNS:
            rec["designs"][design]={}
            for g in GROUPS:
                p,m=match(rows,g,design=="strict");pair_sets[(design,g)]=p
                rec["designs"][design][g]={"match":m,"outcomes":{}}
                used.update(x["code"] for a,b in p for x in (a,b))
        outcomes={}
        for step,label in ((1,"next_q_growth"),(2,"second_q_growth")):
            if q+step<=last and cutoff(q+step)<=asof:
                fut,_=get(q+step,cutoff(q+step),False)
                outcomes[label]={k:outcome(fut,k,q+step) for k in used}
        for step in (20,60):
            if entry+step>=len(days):continue
            # Endpoints and 5-session sampled path. Not daily maximum drawdown.
            path=[market(days[entry+j])[0] for j in range(0,step+1,5)]
            a,b=path[0],path[-1]
            outcomes["return"+str(step)]={k:b[k]/a[k]-1 for k in used if k in a and k in b}
            outcomes["sampled_mdd"+str(step)]={k:sampled_drawdown([m.get(k) for m in path]) for k in used}
        for (design,g),p in pair_sets.items():
            rec["designs"][design][g]["outcomes"]={label:paired(p,v,"growth" if label.endswith("growth") else "return") for label,v in outcomes.items()}
        cohorts.append(rec)
        print(json.dumps({"cohort":period(q),"signal_count":scan_h["signals"],"attributes":rec["attribute_coverage"],"strict_union":rec["designs"]["strict"]["union"]["match"],"growth_only_union":rec["designs"]["growth_only"]["union"]["match"]}),flush=True)
    summary={name:{d:{g:summarize(c,d,g) for g in GROUPS} for d in DESIGNS} for name,c in (("full",cohorts),("recent",[x for x in cohorts if x["period"]>="20240101"]))}
    verdict=decision(summary["full"]["strict"]["union"],summary["recent"]["strict"]["union"])
    report={"version":"earnings-acceleration-v1.1","asof":asof,"signal_params":PARAMS,"cohorts":cohorts,"summary":summary,"decision":verdict,
      "financial_batches":len(health),"membership_batches":len(member_health),"membership_records":len(member),
      "historical_membership_records":sum(x.get("is_new")=="N" for x in member),"industry_preflight":industry_preflight,"market_batches":len(market_health),"market_errors":market_errors,
      "notes":["V1.0 unchanged. Same cutoff, same quality gates. No current industry or survivor list used in history.",
       "Strict: contemporaneous SW2021 L1 membership, gross earnings growth factor ratio within 1.2, market cap and positive PE-TTM ratios within 2, one-to-one no replacement, max cardinality then minimum normalized log-distance. Growth-only sensitivity not a substitute for strict.",
       "Matching data last close on/before cutoff; outcome entry next close. No future data used in matching. Future revisions may remain in vendor history; no audited PIT, no historic ST screen.",
       "Only complete pairs. Per cohort at least five observed pairs and 80% matched outcome coverage. 5-session sampled stock drawdown understates true daily MDD; not portfolio MDD. Adjusted returns gross of cost, missing delisting proceeds and execution feasibility.",
       "Full and recent subsets overlap; no independent test set or formal causal inference. Coverage and direction decision thresholds are research rules, not universal evidence standards."]}
    out=Path(args.output);out.mkdir(parents=True,exist_ok=True)
    (out/"validation.json").write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False))
    # No individual stock codes or raw values in output.
    print(json.dumps({"matched_summary":summary,"decision":verdict,"financial_batches":len(health),"membership_batches":len(member_health),"market_batches":len(market_health),"market_errors":market_errors},ensure_ascii=False),flush=True)
if __name__=="__main__":main()
