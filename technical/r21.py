"""R2.1 data quality acceptance: source diagnostics only, no changes to R1 indicators."""
from collections import Counter,defaultdict
from math import isclose
from statistics import median
from datetime import datetime,timedelta
from .indicators import normalize,aggregate,period,number,date,indicators
from .signals import signal_snapshot
from .data import series
from .diagnostics import emit
from tushare_5000 import POINTS

OHLC=("open","high","low","close")
PRICE_TOL=.02
VOL_TOL=1.0 # hands
AMT_TOL=.02 # thousand CNY
# Fixed candidate conversions: not fitted per row. Compare each candidate across all periods.
def unit_report(pairs,divisors,tol):
    # pair = remote, regular, after-hours (None if unavailable)
    out=[]
    for divisor in divisors:
        for scope in ("regular","including_afterhours"):
            e=[];ratios=[]
            for remote,regular,after in pairs:
                if scope=="including_afterhours" and after is None:continue
                local=regular+(after if scope=="including_afterhours" else 0.)
                e.append(abs(remote/divisor-local))
                if local>0:ratios.append(remote/local)
            out.append({"divisor":divisor,"scope":scope,"n":len(e),"passed":sum(x<=tol+1e-8 for x in e),"max_abs":round(max(e),6) if e else None,"median_raw_ratio":round(median(ratios),8) if ratios else None})
    return out

def pick_periods(rows,code,freq,asof,local,adjusted):
    """Use cycle labels; a later cutoff can be a snapshot vintage, never a future input.
    Completed periods only; raw OHLC cross-check is mandatory before accepting HFQ.
    """
    out={};stats=Counter();examples=defaultdict(list)
    for r in rows:
        try:
            if r.get("ts_code")!=code or (adjusted and str(r.get("freq","")).lower()!=freq):raise ValueError("symbol_or_freq")
            label=date(str(r["trade_date"]));k=period(label,freq);b=local.get(k)
            if b is None or not b["complete"]:stats["unavailable_or_incomplete_period"]+=1;continue
            cutoff=date(str(r["end_date"])) if adjusted else label
            if adjusted:
                kind="same_period_cutoff" if period(cutoff,freq)==k else "later_snapshot_cutoff" if cutoff>b["date"] else "earlier_cutoff"
                stats[kind]+=1
                if len(examples[kind])<3:examples[kind].append({"label":label,"cutoff":cutoff,"local_last":b["date"]})
                if cutoff>asof or cutoff<b["date"]:raise ValueError("invalid_cutoff")
            elif label>asof:raise ValueError("future_label")
            names=OHLC+("vol","amount")+(tuple(x+"_hfq" for x in OHLC)+tuple(x+"_qfq" for x in OHLC) if adjusted else ())
            vals={n:number(r[n]) for n in names}
            old=out.get(k)
            if old and old[0]==cutoff and old[1]!=vals:raise RuntimeError("conflicting_duplicate")
            if not old or cutoff>old[0]:out[k]=(cutoff,vals)
            else:stats["duplicate_or_older_snapshot"]+=1
        except (ValueError,TypeError,KeyError) as e:
            stats["rejected_"+str(e)[:50]]+=1
    return out,dict(stats),dict(examples)

def sums_optional(rows,key):
    vals=[r.get(key) for r in rows]
    if not vals or any(x is None or x=="" for x in vals):return None
    v=[number(x) for x in vals]
    if any(x<0 for x in v):raise ValueError("negative afterhours")
    return sum(v)

def period_checks(api,code,bars,raw,factors,asof,cal):
    for ep in ("weekly","monthly","stk_week_month_adj"):POINTS.setdefault(ep,2000)
    raw_bars=normalize(raw,None,code,asof)
    fm={r["trade_date"]:number(r["adj_factor"]) for r in factors}
    anchor=fm[asof];start=str(int(asof[:4])-2)+"0101"
    for freq in ("week","month"):
        adj={period(x["date"],freq):x for x in aggregate(bars,freq,asof,cal)}
        base={period(x["date"],freq):x for x in aggregate(raw_bars,freq,asof,cal)}
        daily=defaultdict(list)
        for x in sorted(raw,key=lambda r:r["trade_date"]):daily[period(x["trade_date"],freq)].append(x)
        for ep in ("weekly" if freq=="week" else "monthly","stk_week_month_adj"):
            adjusted=ep=="stk_week_month_adj"
            try:
                params={"ts_code":code,"start_date":start,"end_date":asof}
                fields="ts_code,trade_date,open,high,low,close,vol,amount"
                if adjusted:
                    params["freq"]=freq
                    fields+=",end_date,freq,"+",".join(x+"_"+s for s in ("hfq","qfq") for x in OHLC)
                rows=api.ask(ep,params,fields)
                matches,stats,examples=pick_periods(rows,code,freq,asof,adj,adjusted)
                # Fixed latest 12 completed periods plus up to 12 earlier periods with factor changes.
                # Verify newest period coverage instead of hiding missing rows.
                allkeys=sorted(k for k,b in adj.items() if b["complete"] and b["date"]>=start)
                recent=allkeys[-12:]
                action=[k for k in allkeys if len({fm[x["trade_date"]] for x in daily[k]})>1][-12:]
                keys=sorted(set(recent+action)&set(matches))
                errors=[];hfq=[];qfq=[];vp=[];ap=[];exceptions=[];action_fields=0
                for k in keys:
                    vals=matches[k][1];r=base[k];a=adj[k]
                    rawerr=[abs(vals[x]-r[x]) for x in OHLC]
                    errors.extend(rawerr)
                    vp.append((vals["vol"],r["vol"],sums_optional(daily[k],"ah_vol")))
                    ap.append((vals["amount"],r["amount"],sums_optional(daily[k],"ah_amount")))
                    if adjusted:
                        # Compare same-period raw OHLC first, then re-anchor provider HFQ
                        # using the analysis-day factor, not the row's QFQ anchor.
                        if max(rawerr)>PRICE_TOL:
                            exceptions.append({"date":a["date"],"reason":"raw_ohlc_mismatch"});continue
                        he=[abs(vals[x+"_hfq"]/anchor-a[x]) for x in OHLC]
                        qe=[abs(vals[x+"_qfq"]-a[x]) for x in OHLC]
                        hfq.extend(he);qfq.extend(qe);action_fields+=4*int(k in action)
                        if max(he)>PRICE_TOL:exceptions.append({"date":a["date"],"reason":"hfq_ohlc_mismatch","max_abs":round(max(he),6),"factor_change_in_period":k in action})
                emit("TECH_R21_PERIOD",{"code":code,"period":freq,"endpoint":ep,"state":"compared" if keys else "no_comparable_periods","rows":len(rows),"alignment":stats,"date_examples":examples,"expected_recent":len(recent),"matched_recent":sum(k in matches for k in recent),"expected_action":len(action),"matched_action":sum(k in matches for k in action),"periods":len(keys),
                  "raw_price_fields":len(errors),"raw_price_pass":sum(e<=PRICE_TOL+1e-8 for e in errors),"raw_price_max":round(max(errors),6) if errors else None,
                  "hfq_fields":len(hfq),"hfq_pass":sum(e<=PRICE_TOL+1e-8 for e in hfq),"hfq_max":round(max(hfq),6) if hfq else None,"hfq_action_fields":action_fields,"qfq_direct_max":round(max(qfq),6) if qfq else None,
                  "volume":unit_report(vp,(1,100),VOL_TOL),"amount":unit_report(ap,(1,1000),AMT_TOL),"exceptions":exceptions[:15]})
            except Exception as e:
                emit("TECH_R21_PERIOD",{"code":code,"period":freq,"endpoint":ep,"state":"unavailable","reason":type(e).__name__})

def continuity(raw,factors,code,asof):
    """Validate economic return continuity, not a zero return on ex-date.
    Compare prior raw close * Fprev/Fnow with provider ex-rights pre_close.
    A one-cent allowance covers quoted pre_close rounding; reported pct_chg
    gets 0.01 percentage-point allowance; neither tolerance is learned.
    """
    rows=sorted(raw,key=lambda x:x["trade_date"])
    fm={x["trade_date"]:number(x["adj_factor"]) for x in factors}
    normalized=normalize(rows,factors,code,asof)
    result=Counter();failures=[];events=[];max_pre=0.;max_pct=0.;max_ret=0.
    for i in range(1,len(rows)):
        a,b=rows[i-1],rows[i];d=b["trade_date"]
        fp,fc=fm[a["trade_date"]],fm[d];change=not isclose(fp,fc,rel_tol=1e-10,abs_tol=1e-12)
        group="factor_change" if change else "ordinary"
        result[group+"_pairs"]+=1
        try:
            prev=number(a["close"]);pre=number(b["pre_close"]);close=number(b["close"]);pct=number(b["pct_chg"])
            if min(prev,pre,close,fp,fc)<=0:raise ValueError("nonpositive")
            implied=prev*fp/fc
            pe=abs(implied-pre)
            pcterr=abs(100*(close/pre-1)-pct)
            returnerr=abs(100*(normalized[i]["close"]/normalized[i-1]["close"]-1)-pct)
            # Bound the return error implied by one tick of pre_close rounding.
            # Use both observed and implied denominators; do not assume constant percent tolerance.
            bound=100*close*.01/(pre*implied)+.01
            okp=pe<=.01000001;okpct=pcterr<=.01000001;okr=returnerr<=bound+1e-8
            result[group+"_pre_close_pass"]+=int(okp);result[group+"_pct_pass"]+=int(okpct);result[group+"_return_pass"]+=int(okr)
            max_pre=max(max_pre,pe);max_pct=max(max_pct,pcterr);max_ret=max(max_ret,returnerr)
            if not(okp and okpct and okr):
                result[group+"_failed_pairs"]+=1
                if len(failures)<25:failures.append({"date":d,"group":group,"pre_close_abs":round(pe,6),"pct_abs":round(pcterr,6),"adjusted_return_abs_pp":round(returnerr,6),"return_bound_pp":round(bound,6)})
            if change:events.append((i,pre/implied))
        except (ValueError,TypeError,KeyError):
            result[group+"_missing"]+=1
            if len(failures)<25:failures.append({"date":d,"group":group,"reason":"missing_or_invalid"})
    # Sensitivity on ex-date and the next trading day. Alternative anchor is independently
    # implied by the published ex-rights pre_close. Only data up to the evaluation date;
    # multiply pre-event history by a constant, preserving its existing prior actions.
    sig_n=0;sig_pass=0;direction_n=0;direction_pass=0;sig_fail=[];eligible_events=0
    for i,scale in events:
        if i<61:continue
        eligible_events+=1
        for end in (i,min(i+1,len(rows)-1)):
            if end==i and end==len(rows)-1:pass
            anchor=fm[rows[end]["trade_date"]]
            # Normalize prefix using its own analysis-date anchor, no future factor.
            prefix=[{**x,**{k:x[k]*fm[asof]/anchor for k in OHLC}} for x in normalized[:end+1]]
            alt=[{**x,**{k:x[k]*scale for k in OHLC}} if j<i else x for j,x in enumerate(prefix)]
            s1=signal_snapshot(prefix,"day");s2=signal_snapshot(alt,"day")
            for k in s1:
                if not(k.endswith("_cross") or k.startswith("breakout")):continue
                sig_n+=1;ok=s1[k]==s2[k];sig_pass+=int(ok)
                if not ok and len(sig_fail)<20:sig_fail.append({"event":rows[i]["trade_date"],"asof":rows[end]["trade_date"],"metric":k})
            x1,y1=indicators(prefix[:-1],"day"),indicators(prefix,"day")
            x2,y2=indicators(alt[:-1],"day"),indicators(alt,"day")
            for k in ("ma5","ma10","ma20","ma60","ma250","dif","dea","macd","rsi6","rsi12","rsi24","boll_upper","boll_lower"):
                if any(x[k] is None for x in (x1,y1,x2,y2)):continue
                def sign(d):return 1 if d>1e-9 else -1 if d< -1e-9 else 0
                direction_n+=1;ok=sign(y1[k]-x1[k])==sign(y2[k]-x2[k]);direction_pass+=int(ok)
                if not ok and len(sig_fail)<20:sig_fail.append({"event":rows[i]["trade_date"],"asof":rows[end]["trade_date"],"metric":k+"_direction"})
    return {"code":code,"first":rows[0]["trade_date"],"last":asof,"pairs":len(rows)-1,**dict(result),
            "max_pre_close_abs":round(max_pre,6),"max_pct_error_pp":round(max_pct,6),"max_adjusted_return_error_pp":round(max_ret,6),"exceptions":failures,
            "signal_event_count":eligible_events,"signals_checked":sig_n,"signals_consistent":sig_pass,"directions_checked":direction_n,"directions_consistent":direction_pass,"sensitivity_exceptions":sig_fail}
