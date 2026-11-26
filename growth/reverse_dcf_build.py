"""Read actual vendor financial fields for all calculable growth-scanner rows.
Retain aggregate coverage in logs, encrypted model inputs/outputs only.
"""
from __future__ import annotations
import sys,os,json,time
from pathlib import Path
from collections import Counter
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"scripts"))
from tushare_5000 import Tushare,SafeAPIError,POINTS
from growth_model import number,valid_date,PRESETS,passes
from reverse_dcf import base_inputs,analyze
POINTS.update({"fina_indicator_vip":5000,"balancesheet_vip":5000,"fina_indicator":2000,"balancesheet":2000})
def pick(rows,period,asof,fields,consolidated):
    groups={}
    for r in rows:
        if str(r.get("end_date"))!=period or not r.get("ts_code"):continue
        if consolidated and str(r.get("report_type"))!="1":continue
        a=valid_date(r.get("ann_date"));f=valid_date(r.get("f_ann_date"))
        if not a or max(a,f or a)>asof:continue
        z={k:number(r.get(k)) for k in fields}
        groups.setdefault(r["ts_code"],[]).append((max(a,f or a),z))
    out={};conflicts=0
    for k,g in groups.items():
        newest=max(t for t,_ in g)
        zs=[z for t,z in g if t==newest]
        if any(z!=zs[0] for z in zs):conflicts+=1;continue
        out[k]=zs[0]
    return out,conflicts
def fetch(api,endpoint,p,asof,fields,universe,candidates):
    con=endpoint=="balancesheet_vip"
    params={"period":p,**({"report_type":"1"} if con else {})}
    field="ts_code,ann_date,end_date,"+("f_ann_date,report_type," if con else "")+",".join(fields)
    raw=api.ask(endpoint,params,field)
    first=len(raw);pages=1
    d,c=pick(raw,p,asof,fields,con)
    offset=first
    for _ in range(6):
        if not first or (first<4000 and len(set(d)&universe)>=.985*len(universe)):break
        try:more=api.ask(endpoint,{**params,"offset":offset,"limit":min(first,5000)},field)
        except SafeAPIError:break
        if not more:break
        old={json.dumps(z,sort_keys=True) for z in raw}
        add=[z for z in more if json.dumps(z,sort_keys=True) not in old]
        if not add:break
        raw.extend(add);offset+=len(more);pages+=1
        if len(more)<min(first,5000):break
    d,c=pick(raw,p,asof,fields,con)
    # Prioritize resolving missing candidate records without repeatedly downloading the market.
    missing=sorted(candidates-set(d));fallback=0
    for k in missing:
        try:raw.extend(api.ask(endpoint.removesuffix("_vip"),{**params,"ts_code":k},field,retry=1));fallback+=1
        except SafeAPIError:pass
        time.sleep(.25)
    d,c=pick(raw,p,asof,fields,con)
    return d,{"endpoint":endpoint,"period":p,"first_rows":first,"pages":pages,"conflicts":c,
       "covered":len(universe&set(d)),"candidate_covered":len(candidates&set(d)),"candidate_fallback":fallback}
def main():
    d=Path(sys.argv[1]);p=d/"snapshot.json";x=json.loads(p.read_text());r=x["report"]
    if r["version"]!="growth-scanner-v1.2" or not r.get("data_coverage_pass") or len(x["rows"])!=r["complete_metrics"]:raise RuntimeError("Base snapshot invalid")
    asof=r["asof"];plan=r["periods"];y=int(plan["annual"][:4])
    years=[f"{i}1231" for i in range(y-2,y+1)]
    latest,prior=plan["latest"],plan["prior"]
    universe={v["code"] for v in x["rows"]}
    candidates={v["code"] for v in x["rows"] if any(passes(v,p["limits"]) for p in PRESETS)}
    api=Tushare(os.environ.get("TUSHARE_TOKEN"));data={};health=[];errors=[]
    tasks=[("fina_indicator_vip",t,["ebit","fcff","roic"]) for t in years]
    tasks.extend([("fina_indicator_vip",prior,["ebit","fcff"]),("fina_indicator_vip",latest,["ebit","fcff","interestdebt","netdebt"]),
        ("balancesheet_vip",latest,["total_hldr_eqy_inc_min_int","total_hldr_eqy_exc_min_int","minority_int","oth_eqt_tools"])])
    for ep,t,fields in tasks:
        try:
            z,h=fetch(api,ep,t,asof,fields,universe,candidates);data[(ep,t)]=z;health.append(h)
        except SafeAPIError:
            errors.append({"endpoint":ep,"period":t})
    def get(ep,t,k):return data.get((ep,t),{}).get(k)
    for row in x["rows"]:
        k=row["code"]
        b,reason=base_inputs([get("fina_indicator_vip",t,k) for t in years],
            get("fina_indicator_vip",latest,k),get("fina_indicator_vip",prior,k),get("balancesheet_vip",latest,k),row)
        row["reverse_dcf"]=analyze(b) if b is not None else {"status":"unavailable","reason":reason}
    def counts(group):
        v=[z["reverse_dcf"] for z in group]
        ok=[z for z in v if z["status"]=="ok"]
        center=lambda z,n:next(k for k in z["sensitivity"] if k["years"]==n and k["wacc"]==.1 and k["terminal"]==.03)
        return {"n":len(v),"input_eligible":len(ok),"input_exclusions":dict(Counter(z["reason"] for z in v if z["status"]!="ok")),
            "central_5y":dict(Counter(center(z,5)["status"] for z in ok)),
            "central_10y":dict(Counter(center(z,10)["status"] for z in ok)),
            "any_unique_solution":sum(any(s["status"]=="ok" for s in z["sensitivity"]) for z in ok)}
    stats={"all":counts(x["rows"]),"unique_presets":counts([v for v in x["rows"] if v["code"] in candidates]),
           "presets":{p["id"]:counts([v for v in x["rows"] if passes(v,p["limits"])]) for p in PRESETS}}
    r.update(version="growth-scanner-v1.3",reverse_dcf_statistics=stats,reverse_dcf_health={"annual_periods":years,"latest":latest,"prior":prior,"api_batches":health,"failed_batches":errors},
       reverse_dcf_method={"base":"TTM vendor EBIT x 75%; normalized FCFF = TTM NOPAT x (50% median 3 annual FCFF/NOPAT ratios + 50% TTM ratio); vendor FCFF unverified formula",
         "ev":"equity market cap + vendor net debt + book minority + other equity instruments; no separate nonoperating asset adjustment, simplified bridge",
         "growth":"solve constant NOPAT growth -20% to min(60%, 3y median ROIC) with positive growth reinvestment=g/ROIC; no capital release at negative growth; implied year-N FCFF CAGR versus normalized FCFF separately",
         "terminal":"terminal incremental ROIC=WACC, recalculate terminal FCFF from next-year NOPAT and terminal reinvestment; WACC and terminal rates are scenario assumptions",
         "guard":"3 positive annual EBIT and FCFF and positive TTM; FCFF/NOPAT max/min<=4 and max<=2; missing fields, inconsistent EV, multiple/no roots explicitly unavailable; not company-specific valuation"})
    p.write_text(json.dumps(x,ensure_ascii=False,separators=(",",":"),allow_nan=False),encoding="utf8")
    (d/"validation.json").write_text(json.dumps(r,ensure_ascii=False,indent=2),encoding="utf8")
    print(json.dumps({"reverse_dcf_statistics":stats,"reverse_dcf_health":r["reverse_dcf_health"]},ensure_ascii=False))
if __name__=="__main__":main()
