#!/usr/bin/env python3
"""Historical V2 research backfill, one calendar year per independent job.
Only aggregated daily breadth/trend features leave runner; paid raw prices/factors
stay in process memory and NEVER enter public git history or workflow artifacts.
TUSHARE_TOKEN is read only from Actions secrets.
"""
from __future__ import annotations
import argparse
from collections import defaultdict
from datetime import datetime,date,timedelta
import json, math, os, statistics, time, urllib.request, urllib.error
from pathlib import Path
from zoneinfo import ZoneInfo
from v2_model import INDEX_WEIGHTS,LAUNCH_CSI2000,index_trend,mean,stdev

API="https://api.tushare.pro"
ROOT=Path(__file__).resolve().parent

class TushareError(RuntimeError): pass

class Tushare:
    def __init__(self):
        token=os.getenv("TUSHARE_TOKEN","").strip()
        if not token: raise TushareError("Missing TUSHARE_TOKEN secret")
        self.token=token
        self.calls=defaultdict(int)
    def ask(self, endpoint,params,fields):
        payload=json.dumps({"api_name":endpoint,"token":self.token,"params":params,"fields":fields}).encode()
        req=urllib.request.Request(API,data=payload,headers={"Content-Type":"application/json"},method="POST")
        for attempt in range(4):
            self.calls[endpoint]+=1
            try:
                with urllib.request.urlopen(req,timeout=35) as h:
                    response=json.loads(h.read(9000000))
                if response.get("code")!=0:
                    # Tushare messages can reflect credentials: never print raw API body.
                    raise TushareError(f"{endpoint} returned API code {response.get('code')}")
                data=response.get("data") or {}
                fields=data.get("fields") or []
                return [dict(zip(fields,x)) for x in (data.get("items") or [])]
            except (urllib.error.URLError,TimeoutError,ValueError) as exc:
                if attempt==3: raise TushareError(f"{endpoint} network/parse failure") from None
                time.sleep(2**attempt)
        raise TushareError("unreachable")

def iso(s): return date.fromisoformat(s).strftime("%Y%m%d")
def dt(s): return s[:4]+"-"+s[4:6]+"-"+s[6:8]
def num(v):
    try:
        n=float(v); return n if math.isfinite(n) else None
    except (ValueError,TypeError): return None
def sma(a): return sum(a)/len(a) if a and all(x is not None for x in a) else None
def trailing(a,i,n):
    if i+1 < n: return None
    return a[i-n+1:i+1]

def load_index(api,code,begin,end,dates):
    rows=api.ask("index_daily",{"ts_code":code,"start_date":begin,"end_date":end},
                 "ts_code,trade_date,close,amount")
    lookup={str(r["trade_date"]):r for r in rows}
    closes=[num(lookup.get(d,{}).get("close")) for d in dates]
    amounts=[num(lookup.get(d,{}).get("amount")) for d in dates]
    return closes,amounts

def load_sector(api,code,begin,end,dates):
    rows=api.ask("sw_daily",{"ts_code":code,"start_date":begin,"end_date":end},
                 "ts_code,trade_date,close")
    lookup={str(r["trade_date"]):num(r.get("close")) for r in rows}
    return [lookup.get(d) for d in dates]

def build_year(year,api):
    today=datetime.now(ZoneInfo("Asia/Shanghai")).date()
    first=date(year,1,1)
    last=min(date(year,12,31),today-timedelta(days=1))
    if last<first: raise ValueError("requested year is in the future")
    # ~280 prior trading sessions for a 250-day trend and 80-day stock breadth.
    early=first-timedelta(days=430)
    rows=api.ask("trade_cal",{"exchange":"SSE","start_date":early.strftime("%Y%m%d"),
                              "end_date":last.strftime("%Y%m%d"),"is_open":"1"},
                 "cal_date,is_open")
    all_days=sorted({str(x["cal_date"]) for x in rows if str(x.get("is_open"))=="1"})
    days=[d for d in all_days if d<=last.strftime("%Y%m%d")]
    if len(days)<270: raise TushareError("fewer than 270 valid sessions")
    start,end=days[0],days[-1]
    N=len(days)
    indexes={};turnover={}
    for code in list(INDEX_WEIGHTS)+["000001.SH","399107.SZ"]:
        px,amount=load_index(api,code,start,end,days)
        indexes[code]=px;turnover[code]=amount
    sectors=api.ask("index_classify",{"level":"L1","src":"SW2021"},"index_code,industry_name,level,src")
    codes=sorted({str(r.get("index_code")) for r in sectors if r.get("index_code")})
    if len(codes)<25: raise TushareError("SW2021 level-1 classification incomplete")
    industry={}
    for code in codes:
        industry[code]=load_sector(api,code,start,end,days)
    # The full historical trading-day universe is reconstructed from DAILY rows,
    # rather than the 2026 stock_basic current-list filter (survivorship bias).
    stock_arrays={}
    participation=[None]*N
    quality=[]
    for i,d in enumerate(days):
        q=api.ask("daily",{"trade_date":d},"ts_code,trade_date,close,pct_chg")
        adj=api.ask("adj_factor",{"trade_date":d},"ts_code,trade_date,adj_factor")
        factors={str(x.get("ts_code")):num(x.get("adj_factor")) for x in adj}
        total=rise=priced=0
        for x in q:
            code=str(x.get("ts_code",""))
            if not code.endswith((".SH",".SZ")): continue
            close=num(x.get("close"))
            if close is None or close<=0: continue
            priced+=1
            ret=num(x.get("pct_chg"))
            if ret is not None: total+=1;rise+=ret>0
            factor=factors.get(code)
            if factor is None or factor<=0: continue
            a=stock_arrays.get(code)
            if a is None: a=[None]*N;stock_arrays[code]=a
            a[i]=close*factor
        participation[i]=rise/total if total>=max(1000,int(priced*.70)) else None
        quality.append({"date":dt(d),"daily_count":priced,"with_factor":sum(v[i] is not None for v in stock_arrays.values()),
                        "rise_count":rise,"participation_sample":total})
        if i%40==0: print(f"{year}: {i+1}/{N} trading days (token masked)",flush=True)
    ratio=[None]*N
    stock_n=[0]*N
    for i in range(59,N):
        present=above=0
        for a in stock_arrays.values():
            seg=trailing(a,i,60)
            if seg is None or a[i] is None: continue
            v=sma(seg)
            if v is None: continue
            present+=1
            above+= a[i]>v
        live=quality[i]["with_factor"]
        if present>=1000 and present>=live*.75:
            ratio[i]=above/present
            stock_n[i]=present
    sector_above=[None]*N
    sector_n=[0]*N
    for i in range(59,N):
        good=above=0
        for s in industry.values():
            v=sma(trailing(s,i,60))
            if v is None: continue
            good+=1; above+=s[i]>v
        if good>=max(25,math.ceil(len(industry)*.85)):
            sector_above[i]=above/good
            sector_n[i]=good
    benchmark=[None]*N
    tech=[None]*N
    up_votes=[0]*N
    down_votes=[0]*N
    for i,d in enumerate(days):
        dformatted=dt(d)
        active={code:wt for code,wt in INDEX_WEIGHTS.items()
                if code!="932000.CSI" or dformatted>=LAUNCH_CSI2000}
        effective={code:wt for code,wt in active.items() if indexes[code][i] is not None
                   and (i==0 or indexes[code][i-1] is not None)}
        if len(effective)<3 or sum(effective.values())<.75: continue
        wsum=sum(effective.values())
        if i==0: benchmark[i]=1.
        elif benchmark[i-1] is not None:
            r=sum((indexes[code][i]/indexes[code][i-1]-1)*wt for code,wt in effective.items())/wsum
            benchmark[i]=benchmark[i-1]*(1+r)
        vals={}
        if i>=249:
            for code,wt in effective.items():
                hist=trailing(indexes[code],i,250)
                if hist and all(v is not None and v>0 for v in hist):
                    vals[code]=index_trend(indexes[code][:i+1])
        if len(vals)>=3 and sum(active[c] for c in vals)>=.75:
            sw=sum(active[c] for c in vals)
            tech[i]=sum(vals[c]*active[c] for c in vals)/sw
            up_votes[i]=sum(v>=25 for v in vals.values())
            down_votes[i]=sum(v<=-25 for v in vals.values())
    def closes_above(src,i,n=60):
        window=trailing(src,i,n)
        return None if not window else sma(window)
    recent_amounts=[None]*N
    for i in range(N):
        sh,sz=turnover["000001.SH"][i],turnover["399107.SZ"][i]
        if sh is not None and sz is not None:
            recent_amounts[i]=(sh+sz)*1000
    out=[]
    for i,d in enumerate(days):
        if d < first.strftime("%Y%m%d"): continue
        a5=mean(participation[i-4:i+1]) if i>=4 and all(x is not None for x in participation[i-4:i+1]) else None
        p,ind=ratio[i],sector_above[i]
        b=.4*p+.35*ind+.25*a5 if all(x is not None for x in (p,ind,a5)) else None
        # Leading sectors: >=10 of the past 12 days above MA60 AND 20d
        # outperformance >=3 percentage points versus weighted broad basket.
        leaders=None
        if i>=92 and benchmark[i] is not None:
            count=0;valid=0
            for sec in industry.values():
                flags=[]
                for j in range(i-11,i+1):
                    m=sma(trailing(sec,j,60))
                    if m is None or sec[j] is None or sec[j-20] is None or benchmark[j] is None or benchmark[j-20] is None:
                        flags=[];break
                    lead=sec[j]>m and (sec[j]/sec[j-20]-1 - (benchmark[j]/benchmark[j-20]-1))>=.03
                    flags.append(lead)
                if flags:
                    valid+=1
                    count+=sum(flags)>=10
            if valid>=max(25,math.ceil(len(industry)*.85)): leaders=count
        # Previous significant decline: recent 60d minimum vs prior 120d high.
        dd=None;prior_decline=False
        if i>=179 and all(v is not None for v in benchmark[i-179:i+1]):
            dd=benchmark[i]/max(benchmark[i-119:i+1])-1
            prior_decline=(min(benchmark[i-59:i+1])/max(benchmark[i-179:i-59])-1)<=-.12
        repairs=[]
        if i>=30 and all(x is not None for x in benchmark[i-30:i+1]):
            last10=benchmark[i-9:i+1];old20=benchmark[i-29:i-9]
            ma20=sma(benchmark[i-19:i+1]);ma20prev=sma(benchmark[i-24:i-4])
            repairs.append(min(last10)>=min(old20) and ma20/ma20prev-1>=-.003)
        if i>=15 and tech[i] is not None and tech[i-15] is not None and benchmark[i] is not None and benchmark[i-10] is not None:
            repairs.append(benchmark[i]/benchmark[i-10]-1>0 and tech[i]-tech[i-15]>=20)
        if i>=20 and b is not None:
            b20 = None
            if ratio[i-20] is not None and sector_above[i-20] is not None and all(x is not None for x in participation[i-24:i-19]):
                prevA5=mean(participation[i-24:i-19])
                b20=.4*ratio[i-20]+.35*sector_above[i-20]+.25*prevA5
            histB=[]
            for j in range(i-19,i+1):
                aj=mean(participation[j-4:j+1]) if j>=4 and all(x is not None for x in participation[j-4:j+1]) else None
                if all(x is not None for x in (ratio[j],sector_above[j],aj)):
                    histB.append(.4*ratio[j]+.35*sector_above[j]+.25*aj)
            if b20 is not None and len(histB)>=15:
                repairs.append(b-b20>=.08 or b-min(histB)>=.10)
        repair_count=sum(repairs) if len(repairs)==3 else None
        out.append({"date":dt(d),"T":round(tech[i],3) if tech[i] is not None else None,
                    "B":round(b,5) if b is not None else None,"P60":round(p,5) if p is not None else None,
                    "I60":round(ind,5) if ind is not None else None,
                    "A5":round(a5,5) if a5 is not None else None,
                    "up_votes":up_votes[i],"down_votes":down_votes[i],
                    "leaders":leaders,"drawdown120":round(dd,5) if dd is not None else None,
                    "prior_decline":prior_decline,"repair_count":repair_count,
                    "benchmark":round(benchmark[i],9) if benchmark[i] is not None else None,
                    "stock_samples":stock_n[i],"sector_samples":sector_n[i],
                    "historical_taxonomy_backcast":dt(d)<"2021-12-13"})
    # Year-level results contain only daily aggregate features; never raw stock prices.
    return {"version":"V2.0a-frozen-2026-11-17","year":year,"source":"Tushare Pro, aggregated in GitHub Actions",
            "universe":"all traded .SH/.SZ codes in each historical daily snapshot; includes later-delisted stocks",
            "sector_taxonomy":"SW2021 historical index (backcast before 2021-12-13)",
            "csi2000_policy":"excluded before 2023-08-11 launch to avoid index hindsight",
            "raw_paid_data_committed":False,"dates":len(days),"first_trade_date":dt(start),
            "last_trade_date":dt(end),"api_calls":dict(api.calls),"rows":out}

if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--year",type=int,required=True)
    args=parser.parse_args()
    if not 2015<=args.year<=2026: raise SystemExit("Year must be 2015..2026")
    result=build_year(args.year,Tushare())
    dest=ROOT/"results"/f"year_{args.year}.json"
    dest.parent.mkdir(parents=True,exist_ok=True)
    dest.write_text(json.dumps(result,ensure_ascii=False,separators=(",",":")),encoding="utf8")
    good=sum(r["B"] is not None and r["T"] is not None for r in result["rows"])
    print(json.dumps({"year":args.year,"rows":len(result["rows"]),"fully_scored":good,
                     "api_calls":result["api_calls"],"file":str(dest)},ensure_ascii=False),flush=True)
    if good<max(5,int(.75*len(result["rows"]))):
        raise SystemExit("Insufficient complete V2 historical metrics; do not claim validation")
