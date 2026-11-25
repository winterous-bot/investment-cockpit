#!/usr/bin/env python3
"""Frozen V2.0b forward-risk validation. Inputs: ephemeral prior annual aggregate
artifacts and licensed index/sector closes in runner memory. Only summary output.
No transaction return simulation, tuning, or production changes."""
from __future__ import annotations
from collections import Counter,defaultdict
from datetime import date
from pathlib import Path
import json, math, statistics, sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"v2"))
from v2_backfill import Tushare,dt,num
from v2_model import index_trend,INDEX_WEIGHTS,LAUNCH_CSI2000
STATES=("bull","structural","range","bottoming","bear")
RANK={s:i for i,s in enumerate(STATES)}
SPLITS={"2015_2020":("2015-01-01","2020-12-31"),"2021_2023":("2021-01-01","2023-12-31"),
        "2024_holdout":("2024-01-01","9999-12-31"),"2022_plus":("2022-01-01","9999-12-31"),
        "all":("2015-01-01","9999-12-31")}
def mean(x): return statistics.mean(x) if x else None
def window(a,i,n): return a[i-n+1:i+1] if i>=n-1 and all(v is not None for v in a[i-n+1:i+1]) else None
def ret(a,i,n): return a[i]/a[i-n]-1 if i>=n and a[i] is not None and a[i-n] is not None and a[i-n]>0 else None
def drawdown(a):
    if not a or any(x is None for x in a): return None
    peak=a[0]; dd=0.
    for x in a:
        peak=max(peak,x); dd=max(dd,1-x/peak)
    return dd
def count_valid(a): return sum(x is not None for x in a)
def active(d): return {k:w for k,w in INDEX_WEIGHTS.items() if k!="932000.CSI" or d>=LAUNCH_CSI2000}
def source_series(api,endpoint,code,days):
    out={}
    for lo,hi in (("20130101","20191231"),("20200101",days[-1].replace("-",""))):
        for r in api.ask(endpoint,{"ts_code":code,"start_date":lo,"end_date":hi},"ts_code,trade_date,close"):
            c=num(r.get("close"))
            if c is not None and c>0: out[dt(str(r["trade_date"]))]=c
    return [out.get(d) for d in days]
def load_prices(api,end):
    records=api.ask("trade_cal",{"exchange":"SSE","start_date":"20130101","end_date":end.replace("-",""),"is_open":"1"},"cal_date,is_open")
    days=sorted({dt(str(x["cal_date"])) for x in records if str(x.get("is_open"))=="1"})
    if len(days)<250: raise RuntimeError("historical calendar too short")
    idx={k:source_series(api,"index_daily",k,days) for k in INDEX_WEIGHTS}
    rows=api.ask("index_classify",{"level":"L1","src":"SW2021"},"index_code,industry_name,level,src")
    codes=sorted({str(x["index_code"]) for x in rows if x.get("index_code")})
    if len(codes)<25: raise RuntimeError("SW2021 classification incomplete")
    sec={}
    for k in codes: sec[k]=source_series(api,"sw_daily",k,days)
    return days,idx,sec
def features(days,idx,sec,shards):
    N=len(days); C=[None]*N; T=[None]*N; P=[None]*N; I=[None]*N; A=[None]*N; B=[None]*N; votes=[None]*N
    min_ind=max(25,math.ceil(.85*len(sec)))
    for i,d in enumerate(days):
        weights=active(d)
        if i==0: C[i]=1.
        else:
            use=active(days[i-1]) # newly launched index contributes only after first published close
            if C[i-1] is not None and all(idx[k][i] is not None and idx[k][i-1] is not None for k in use):
                C[i]=C[i-1]*(1+sum(w*(idx[k][i]/idx[k][i-1]-1) for k,w in use.items())/sum(use.values()))
        tv={}
        for k in weights:
            hist=window(idx[k],i,250)
            if hist is not None: tv[k]=index_trend(hist)
        if len(tv)==len(weights) and all(v is not None for v in tv.values()):
            T[i]=sum(tv[k]*w for k,w in weights.items())/sum(weights.values())
            votes[i]=(sum(v>=25 for v in tv.values()),sum(v<=-25 for v in tv.values()))
        # P60/A5 from prior historical daily snapshots; no current-stock-list filter.
        old=shards.get(d,{})
        P[i]=old.get("P60"); A[i]=old.get("A5")
        flags=[v[i]>mean(w) for v in sec.values() if (w:=window(v,i,60)) is not None]
        if len(flags)>=min_ind: I[i]=sum(flags)/len(flags)
        if all(x is not None for x in (P[i],I[i],A[i])): B[i]=.4*P[i]+.35*I[i]+.25*A[i]
    result=[]
    for i,d in enumerate(days):
        t,b,p,j,a=T[i],B[i],P[i],I[i],A[i]
        c=C[i]; prior=None; dd=None
        if (w:=window(C,i,120)) is not None: dd=1-c/max(w)
        if i>=179 and window(C,i,180) is not None:
            prior=any(C[k]/max(C[k-120:k])-1<=-.12 for k in range(i-59,i+1))
        repairs=[]
        if window(C,i,30) is not None:
            repairs.append(min(C[i-9:i+1])>=min(C[i-29:i-9]) and mean(C[i-19:i+1])/mean(C[i-24:i-4])-1>=-.003)
        if i>=15 and t is not None and T[i-15] is not None and ret(C,i,10) is not None:
            repairs.append(ret(C,i,10)>0 and t-T[i-15]>=20)
        if i>=20 and b is not None and B[i-20] is not None and (bw:=window(B,i,20)) is not None:
            repairs.append(b-B[i-20]>=.08 or b-min(bw)>=.10)
        repair_count=sum(repairs) if len(repairs)==3 else None
        leaders=None
        if i>=90 and window(C,i,32) is not None:
            count=valid=0
            for s in sec.values():
                fl=[]
                for k in range(i-11,i+1):
                    w=window(s,k,60); sr=ret(s,k,20); cr=ret(C,k,20)
                    if w is None or sr is None or cr is None: break
                    fl.append(s[k]>mean(w) and sr-cr>=.03)
                if len(fl)==12: valid+=1; count+=bool(fl[-1] and sum(fl)>=10)
            if valid>=min_ind: leaders=count
        cand="unknown"
        if all(x is not None for x in (t,b,p,j,a,votes[i])):
            up,down=votes[i]; broad=b>=.60 and p>=.55 and j>=.55
            weak=b<=.40 and p<.45 and j<.45
            if (t<=-55 and down>=3 and weak) or (t<=-25 and down>=3 and weak and dd is not None and dd>=.12): cand="bear"
            elif t>=55 and up>=3 and broad and a>=.52: cand="bull"
            elif prior is None or (prior and t>-55 and b<.60 and repair_count is None): cand="unknown"
            elif prior and repair_count is not None and repair_count>=2 and t>-55 and b<.60: cand="bottoming"
            elif t>=-25 and b>=.40 and not broad and leaders is None: cand="unknown"
            elif t>=-25 and b>=.40 and not broad and leaders>=3: cand="structural"
            else: cand="range"
        week=date.fromisoformat(d).isocalendar()[:2]
        week_end=(i+1<len(days) and date.fromisoformat(days[i+1]).isocalendar()[:2]!=week) or (i+1==len(days) and date.fromisoformat(d).weekday()==4)
        drop5=ret(C,i,5);drop20=ret(C,i,20)
        warning=(drop5 is not None and drop5<=-.07 and b is not None and b<=.40) or (drop20 is not None and drop20<=-.10) or (i>0 and cand=="bear" and result[-1]["candidate"]=="bear")
        bench=idx["000300.SH"]; ma=window(bench,i,120)
        baseline=("bull" if bench[i]>=mean(ma) else "bear") if ma else "unknown"
        result.append({"date":d,"candidate":cand,"week_end":week_end,"warning_trigger":bool(warning),
                       "baseline":baseline,"T":t,"B":b,"shard":d in shards})
    return C,result
def signals(rows,mode):
    state=pending="unknown"; streak=0; latch=False; prev="unknown"; out=[]
    for x in rows:
        c=x["candidate"]; w=x["week_end"]; warning=x["warning_trigger"]
        if warning: latch=True
        # Unknown evidence is not carried as permission to increase risk.
        if mode=="MA120":
            out.append({"state":x["baseline"],"alert":False,"high":x["baseline"]=="bull","new_high":x["baseline"]=="bull"})
            continue
        evaluate=(mode=="B1" or w)
        if evaluate:
            if c=="unknown" or c==state: pending="unknown";streak=0
            else:
                if pending==c: streak+=1
                else: pending=c;streak=1
                required={"B1":5,"B2":2,"B3":3}[mode]
                if streak>=required: state=c;pending="unknown";streak=0
        elif c=="unknown" and mode=="B1": pending="unknown";streak=0
        valid=c!="unknown"
        high=state=="bull" and not latch and valid
        freeze=(pending!="unknown" and state!="unknown" and RANK[pending]>RANK[state])
        out.append({"state":state if valid else "unknown","confirmed":state,"alert":latch,
                    "pending":pending,"high":high,"new_high":high and not freeze})
        if w and latch and not warning and c not in ("unknown","bear"): latch=False
    return out
def objective(days,idx,sec,C,i,H):
    z=i+H
    if z>=len(days) or (w:=window(C,z,H+1)) is None: return None
    long=H==120; lim=.15 if long else .10; parts=H//20; required=4 if long else 2
    # Use only index series available on signal day for direction vote; composite
    # includes newly launched index only after launch (policy above).
    rr=[ret(idx[k],z,H) for k in active(days[i])]
    if any(v is None for v in rr): return None
    r=w[-1]/w[0]-1; seg=[w[j]/w[j-20]-1 for j in range(20,H+1,20)]
    mdd=drawdown(w); adverse=max(0.,1-min(w)/w[0])
    risk=(mdd>(.15 if long else .12) or adverse>(.12 if long else .08))
    label=None
    if r<=-lim and sum(x<0 for x in seg)>=required and sum(x<0 for x in rr)>=3: label="bear"
    elif r>=lim and sum(x>0 for x in seg)>=required and sum(x>0 for x in rr)>=3: label="bull"
    else:
        past=window(C,i,120); p60=window(C,i,60)
        if past is None or p60 is None: return None
        low=min(w[1:])
        if (drawdown(past)>=.15 and low>=min(p60)*.97 and w[-1]/low-1>=(.12 if long else .08)
            and r>=(.05 if long else 0) and w[-1]/w[H//2]-1>0): label="bottoming"
        else:
            leaders=valid=0
            for a in sec.values():
                s=window(a,z,H+1)
                if s is None: continue
                valid+=1
                excess=[s[j]/s[0]-1-(w[j]/w[0]-1) for j in range(20,H+1,20)]
                if s[-1]/s[0]-1>=(.12 if long else .08) and excess[-1]>=(.08 if long else .05) and sum(x>0 for x in excess)>=required:
                    leaders+=1
            if valid<max(25,math.ceil(.85*len(sec))): return None
            label="structural" if leaders>=3 else "range"
    return {"label":label,"risk":risk,"return":r,"drawdown":mdd,"adverse":adverse}
def fraction(a,b): return {"n":int(a),"N":int(b),"pct":round(a/b*100,2) if b else None}
def metrics(samples):
    # samples = (prediction, objective); every denominator explicitly reported.
    usable=[(p,y) for p,y in samples if y is not None and p["state"]!="unknown"]
    high=[(p,y) for p,y in usable if p["high"]]
    new=[(p,y) for p,y in usable if p["new_high"]]
    actual_bull=[(p,y) for p,y in usable if y["label"]=="bull"]
    bull=[(p,y) for p,y in usable if p["state"]=="bull"]
    bear=[(p,y) for p,y in usable if p["state"]=="bear"]
    conf={a:{b:0 for b in STATES} for a in STATES}
    for p,y in usable: conf[p["state"]][y["label"]]+=1
    return {"signals":len(samples),"scored":len(usable),"objective_missing":sum(y is None for p,y in samples),
            "prediction_missing":sum(p["state"]=="unknown" for p,y in samples),
            "dangerous_high_cap":fraction(sum(y["risk"] for p,y in high),len(high)),
            "dangerous_new_permission":fraction(sum(y["risk"] for p,y in new),len(new)),
            "bull_direction":fraction(sum(y["label"]=="bull" for p,y in bull),len(bull)),
            "bear_direction":fraction(sum(y["label"]=="bear" for p,y in bear),len(bear)),
            "bull_opportunity_missed":fraction(sum(not p["high"] for p,y in actual_bull),len(actual_bull)),
            "all_direction":fraction(sum(p["state"]==y["label"] for p,y in usable),len(usable)),
            "high_cap_share":fraction(len(high),len(usable)),
            "confusion":conf}
def risk_episodes(days,C,lo,hi):
    # Independent broad risk episodes: 60-day peak-to-current breach >12%.
    # Episode ends when rolling drawdown <=6%; these are operational definitions,
    # not exchange conventions. Start before breach; never count same-day as early.
    events=[]; in_event=False
    for i,d in enumerate(days):
        w=window(C,i,60)
        if w is None: in_event=False;continue
        dd=1-C[i]/max(w)
        if in_event and dd<=.06: in_event=False
        if dd>.12 and not in_event:
            in_event=True
            k=max(range(i-59,i+1),key=lambda q:C[q])
            if lo<=days[k] and d<=hi: events.append((k,i))
    return events
def evaluate(days,idx,sec,C,rows,signals_by_mode):
    report={"spec":"V2.0b-frozen-2026-11-25","mode_definitions":{"B1":"5 consecutive trading days","B2":"2 consecutive week-end closes","B3":"3 consecutive week-end closes","MA120":"CSI300 close >= MA120"},
            "end":days[-1],"observations":{},"models":{}}
    objectives={H:[objective(days,idx,sec,C,i,H) if d>="2015-01-01" else None for i,d in enumerate(days)] for H in (60,120)}
    for name,(lo,hi) in SPLITS.items():
        positions=[i for i,d in enumerate(days) if lo<=d<=hi and d>="2015-01-01"]
        weekly=[i for i in positions if rows[i]["week_end"]]
        report["observations"][name]={"days":len(positions),"weeks":len(weekly),"shard_days":sum(rows[i]["shard"] for i in positions),
                "valid_candidate_days":sum(rows[i]["candidate"]!="unknown" for i in positions),
                "known_breadth_days":sum(rows[i]["B"] is not None for i in positions)}
        eps=risk_episodes(days,C,lo,hi)
        for mode,ss in signals_by_mode.items():
            sub=report["models"].setdefault(mode,{}).setdefault(name,{})
            state_entries=[i for i in positions if i>0 and ss[i]["state"]!="unknown" and ss[i]["state"]!=ss[i-1]["state"]]
            permission_entries=[i for i in positions if i>0 and ss[i]["high"] and not ss[i-1]["high"]]
            # Distinguish real confirmed-state changes from re-appearing valid observations.
            known=[ss[i].get("confirmed",ss[i]["state"]) for i in positions]
            switches=sum(a!=b and a!="unknown" and b!="unknown" for a,b in zip(known,known[1:]))
            sub["switches"]=switches
            sub["switches_per_252_days"]=round(switches*252/len(positions),2) if positions else None
            sub["alert_days"]=sum(ss[i]["alert"] for i in positions)
            sub["candidate_unknown_days"]=sum(rows[i]["candidate"]=="unknown" for i in positions)
            for H in (60,120):
                # A split must contain both signal and full outcome horizon.
                eligible=lambda i: i+H<len(days) and days[i+H]<=hi
                sub[str(H)]={}
                for sample,indices in (("weekly",weekly),("stage_entries",state_entries),("high_permission_entries",permission_entries)):
                    sub[str(H)][sample]=metrics([(ss[i],objectives[H][i]) for i in indices if eligible(i)])
            # Only evaluate independent major-risk events with adequate prediction
            # evidence throughout peak-to-breach; report excluded, and early/same-day.
            ev=[]; excluded=0
            for k,i in eps:
                valid=sum(ss[j]["state"]!="unknown" for j in range(k,i+1))
                if valid < math.ceil(.8*(i-k+1)): excluded+=1;continue
                alerts=[j for j in range(k,i+1) if ss[j]["alert"] or ss[j]["state"]=="bear"]
                first=alerts[0] if alerts else None
                ev.append({"peak":days[k],"breach":days[i],"first_restriction":days[first] if first is not None else None,
                           "lead_sessions":i-first if first is not None else None})
            leads=[v["lead_sessions"] for v in ev if v["lead_sessions"] is not None and v["lead_sessions"]>0]
            sub["major_risk_events"]={"all_events":len(eps),"excluded_missing":excluded,"early_detection":fraction(len(leads),len(ev)),
                        "same_day":sum(v["lead_sessions"]==0 for v in ev),"median_early_lead":statistics.median(leads) if leads else None,"events":ev}
    return report
def main():
    import argparse
    p=argparse.ArgumentParser();p.add_argument("--shards",required=True);p.add_argument("--output",required=True);args=p.parse_args()
    shards={}; metadata={}
    for path in sorted(Path(args.shards).rglob("year_*.json")):
        raw=json.loads(path.read_text())
        if raw.get("version")!="V2.0a-frozen-2026-11-17" or raw.get("raw_paid_data_committed") is not False:
            raise RuntimeError("unexpected input shard")
        y=str(raw["year"])
        if y in metadata: raise RuntimeError("duplicate year artifact")
        r=raw["rows"]; metadata[y]={"rows":len(r),"prior_complete":sum(x.get("B") is not None and x.get("T") is not None for x in r)}
        for x in r:
            if x["date"] in shards: raise RuntimeError("duplicate date")
            shards[x["date"]]=x
    if not shards: raise RuntimeError("no historical aggregate inputs available")
    end=max(shards)
    api=Tushare();days,idx,sec=load_prices(api,end)
    C,rows=features(days,idx,sec,shards)
    modes={k:signals(rows,k) for k in ("B1","B2","B3","MA120")}
    report=evaluate(days,idx,sec,C,rows,modes)
    report["input_shards"]=metadata
    report["missing_years"]=[y for y in range(2015,int(end[:4])+1) if str(y) not in metadata]
    report["api_calls"]=dict(api.calls)
    report["scope_notes"]=["Historical SW2021 sector data before 2021-12-13 are backcast; 2022+ separate.",
         "2015 prior backfill only 73/244 valid; excluded unknown dates, no interpolation.",
         "Weekly samples overlap; not independent. Stage/high-cap entries separately reported.",
         "Signals and labels distinct; forward labels do not claim objective contemporaneous stages.",
         "2024+ holdout not blinded; no parameter search performed.",
         "CSI2000 excluded before launch; first weighted return after first publication close.",
         "Stock breadth from prior historical traded-stock artifacts; source coverage and revisions remain limitations.",
         "High-cap excludes missing daily evidence; lower pending stage blocks new permission, not existing cap.",
         "Simple baseline is binary and uses no breadth; compare common risk metrics only."]
    output=Path(args.output);output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(report,ensure_ascii=False,indent=2))
    print(json.dumps({"end":end,"missing_years":report["missing_years"],"observations":report["observations"],
        "B2_holdout_60":report["models"]["B2"]["2024_holdout"]["60"]["weekly"],
        "B2_holdout_120":report["models"]["B2"]["2024_holdout"]["120"]["weekly"]},ensure_ascii=False))
if __name__=="__main__":main()
