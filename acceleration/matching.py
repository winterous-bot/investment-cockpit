"""Frozen V1.1 matching design; V1.0 signal unchanged. No outcomes in matching."""
import math,statistics
from collections import Counter
from acceleration_model import num,valid_date
GROWTH_LOG=math.log(1.2)
SIZE_LOG=math.log(2)
PE_LOG=math.log(2)
MIN_PAIRS=5
MIN_OBS=.8
def industry_at(rows,day):
    active={}
    for r in rows:
        k=r.get("ts_code");g=r.get("l1_code");start=valid_date(r.get("in_date"));stop=valid_date(r.get("out_date"))
        if not k or not g or not start or start>day or (stop and stop<=day):continue
        if r.get("is_new")=="N" and not stop:continue
        active.setdefault(k,set()).add(str(g).split(".")[0])
    return {k:next(iter(v)) for k,v in active.items() if len(v)==1}
def attributes(x,quotes,industries):
    q=quotes.get(x["code"],{})
    cap=num(q.get("total_mv"));pe=num(q.get("pe_ttm"))
    return {**x,"industry":industries.get(x["code"]),"cap":cap if cap is not None and cap>0 else None,
            "pe":pe if pe is not None and pe>0 else None}
def distance(a,b,strict):
    # Compare gross growth factors, not log of growth itself (both may be negative).
    g=abs(math.log1p(a["growth"])-math.log1p(b["growth"]))
    if g>GROWTH_LOG+1e-12:return None
    if not strict:return g/GROWTH_LOG
    if not a["industry"] or a["industry"]!=b["industry"]:return None
    if any(x[k] is None for x in (a,b) for k in ("cap","pe")):return None
    s=abs(math.log(a["cap"]/b["cap"]));p=abs(math.log(a["pe"]/b["pe"]))
    if s>SIZE_LOG+1e-12 or p>PE_LOG+1e-12:return None
    return g/GROWTH_LOG+s/SIZE_LOG+p/PE_LOG
def assignment(cost):
    """Rectangular Hungarian algorithm: maximize pair count, then minimize cost.
    Dummy columns cost 10000, forbidden edges 1e6. Each control used once per cohort/group.
    """
    n=len(cost)
    if not n:return []
    m=len(cost[0])
    if n>m:raise ValueError("rows > columns")
    u=[0.]*(n+1);v=[0.]*(m+1);p=[0]*(m+1);way=[0]*(m+1)
    for i in range(1,n+1):
        p[0]=i;j0=0;minv=[float("inf")]*(m+1);used=[False]*(m+1)
        while True:
            used[j0]=True;i0=p[j0];delta=float("inf");j1=0
            for j in range(1,m+1):
                if used[j]:continue
                cur=cost[i0-1][j-1]-u[i0]-v[j]
                if cur<minv[j]:minv[j]=cur;way[j]=j0
                if minv[j]<delta:delta=minv[j];j1=j
            for j in range(m+1):
                if used[j]:u[p[j]]+=delta;v[j]-=delta
                else:minv[j]-=delta
            j0=j1
            if p[j0]==0:break
        while True:
            j1=way[j0];p[j0]=p[j1];j0=j1
            if j0==0:break
    return sorted((p[j]-1,j-1) for j in range(1,m+1) if p[j])
def match(rows,group,strict=True):
    treated=sorted((x for x in rows if x["signal"] and (group=="union" or x["signal"]==group)),key=lambda x:x["code"])
    controls=sorted((x for x in rows if x["signal"] is None),key=lambda x:x["code"])
    assert not ({x["code"] for x in treated}&{x["code"] for x in controls})
    edges=[[distance(a,b,strict) for b in controls] for a in treated]
    costs=[[1e6 if d is None else d for d in r]+[10000.]*len(treated) for r in edges]
    pairs=[(treated[i],controls[j]) for i,j in assignment(costs) if j<len(controls) and edges[i][j] is not None]
    def available(x):return bool(x["industry"] and x["cap"] is not None and x["pe"] is not None)
    med=lambda a:statistics.median(a) if a else None
    def balance(k,log=False):
        a=[math.log(x[k]) if log else x[k] for x,y in pairs if x.get(k) is not None and y.get(k) is not None]
        b=[math.log(y[k]) if log else y[k] for x,y in pairs if x.get(k) is not None and y.get(k) is not None]
        if not a:return {"n":0,"median_abs_gap":None,"mean_gap":None,"smd":None}
        sd=math.sqrt((statistics.pvariance(a)+statistics.pvariance(b))/2)
        gap=statistics.mean(a)-statistics.mean(b)
        return {"n":len(a),"median_abs_gap":med([abs(x-y) for x,y in zip(a,b)]),"mean_gap":gap,"smd":gap/sd if sd>0 else (0. if abs(gap)<1e-12 else None)}
    report={"signals":len(treated),"controls":len(controls),"matched":len(pairs),"match_rate":len(pairs)/len(treated) if treated else None,
      "missing_attributes":sum(not available(x) for x in treated),"no_admissible_control":sum(not any(d is not None for d in r) for r in edges),
      "competition_unmatched":sum(any(d is not None for d in r) for r in edges)-len(pairs),
      "same_industry":sum(a["industry"] is not None and a["industry"]==b["industry"] for a,b in pairs),
      "growth_balance":balance("growth"),"log_cap_balance":balance("cap",True),"log_pe_balance":balance("pe",True),
      "median_signal_growth":med([a["growth"] for a,b in pairs]),"median_control_growth":med([b["growth"] for a,b in pairs])}
    return pairs,report
def paired(pairs,values,kind):
    # Pairwise complete-case. For growth outcomes also compute change relative to current.
    obs=[(a,b,values[a["code"]],values[b["code"]]) for a,b in pairs if values.get(a["code"]) is not None and values.get(b["code"]) is not None]
    n=len(pairs);m=len(obs);valid=n>=MIN_PAIRS and m>=MIN_PAIRS and m>=MIN_OBS*n
    med=lambda a:statistics.median(a) if a else None
    av=[x for a,b,x,y in obs];bv=[y for a,b,x,y in obs]
    gaps=[x-y for x,y in zip(av,bv)]
    r={"pairs":n,"observed_pairs":m,"coverage_pass":valid,"signal_median":med(av),"control_median":med(bv),
       "median_pair_gap":med(gaps) if valid else None,"mean_pair_gap":statistics.mean(gaps) if valid else None,
       "positive_pair_share":sum(g>0 for g in gaps)/m if valid else None}
    if kind=="growth":
        delta=[(x-a["growth"])-(y-b["growth"]) for a,b,x,y in obs]
        r.update(median_change_gap=med(delta) if valid else None,
          persistence_gap=statistics.mean([int(x>=a["growth"])-int(y>=b["growth"]) for a,b,x,y in obs]) if valid else None,
          positive_growth_gap=statistics.mean([int(x>0)-int(y>0) for x,y in zip(av,bv)]) if valid else None)
    return r
def sampled_drawdown(prices):
    if not prices or any(x is None or x<=0 for x in prices):return None
    peak=prices[0];worst=0.
    for p in prices:
        peak=max(peak,p);worst=max(worst,1-p/peak)
    return worst
def summarize(cohorts,design,group):
    seq=[c["designs"][design][group] for c in cohorts]
    med=lambda a:statistics.median(a) if a else None
    n=sum(x["match"]["signals"] for x in seq);m=sum(x["match"]["matched"] for x in seq)
    r={"signals":n,"matched":m,"match_rate":m/n if n else None,"cohorts":len(seq),
       "matched_cohorts_ge5":sum(x["match"]["matched"]>=MIN_PAIRS for x in seq),
       "missing_attributes":sum(x["match"]["missing_attributes"] for x in seq),
       "no_admissible_control":sum(x["match"]["no_admissible_control"] for x in seq),
       "competition_unmatched":sum(x["match"]["competition_unmatched"] for x in seq),
       "same_industry":sum(x["match"]["same_industry"] for x in seq)}
    for k in ("growth_balance","log_cap_balance","log_pe_balance"):
        r[k]={"median_cohort_abs_gap":med([x["match"][k]["median_abs_gap"] for x in seq if x["match"][k]["median_abs_gap"] is not None]),
              "median_abs_smd":med([abs(x["match"][k]["smd"]) for x in seq if x["match"][k]["smd"] is not None])}
    r["outcomes"]={}
    for k in ("next_q_growth","second_q_growth","return20","return60","sampled_mdd20","sampled_mdd60"):
        allx=[x["outcomes"][k] for x in seq if k in x["outcomes"]];ok=[z for z in allx if z["coverage_pass"]]
        def metric(field):return med([z[field] for z in ok if z.get(field) is not None])
        r["outcomes"][k]={"cohorts_total":len(allx),"cohorts_valid":len(ok),"pairs":sum(z["pairs"] for z in allx),
          "observed_pairs":sum(z["observed_pairs"] for z in allx),"median_cohort_pair_gap":metric("median_pair_gap"),
          "median_signal":metric("signal_median"),"median_control":metric("control_median"),
          "median_cohort_positive_pair_share":metric("positive_pair_share"),
          "positive_cohorts":sum(z["median_pair_gap"]>0 for z in ok),
          "equal_cohort_mean_gap":statistics.mean([z["mean_pair_gap"] for z in ok]) if ok else None,
          "median_change_gap":metric("median_change_gap"),"median_persistence_gap":metric("persistence_gap"),
          "median_positive_growth_gap":metric("positive_growth_gap")}
    return r
def decision(full,recent):
    # Predeclared evidence rule, not statistical proof. Only primary union decides.
    def sufficient(s,minimum):
        return (s["match_rate"] or 0)>=.5 and all(s["outcomes"][k]["cohorts_valid"]>=minimum for k in ("next_q_growth","second_q_growth","return20","return60"))
    def robust(s,k,mean=False):
        x=s["outcomes"][k];n=x["cohorts_valid"]
        return n>0 and x["median_cohort_pair_gap"]>0 and x["positive_cohorts"]/n>=.6 and (not mean or x["equal_cohort_mean_gap"]>0)
    enough=sufficient(full,8) and sufficient(recent,5)
    fundamental=enough and all(robust(s,k) for s in (full,recent) for k in ("next_q_growth","second_q_growth"))
    returns=enough and all(robust(s,k,True) for s in (full,recent) for k in ("return20","return60"))
    return {"sufficient":enough,"fundamental_advantage":fundamental,"return_advantage":returns,
      "recommendation":"retain_independent" if fundamental and returns else "retain_auxiliary" if fundamental else "stop_independent",
      "interpretation":"Insufficient matches means inconclusive, not evidence of no effect. No subgroup overrides the primary union decision."}
