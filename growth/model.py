"""Growth scanner V1.0: current disclosed financials, no historical return claims."""
from __future__ import annotations
import math
from datetime import date,datetime,timedelta
def number(x):
    try:
        a=float(x)
        return a if math.isfinite(a) else None
    except (TypeError,ValueError):return None
def valid_date(x):
    s=str(x or "")
    try:datetime.strptime(s,"%Y%m%d");return s if len(s)==8 else None
    except ValueError:return None
def period_plan(asof):
    """Latest common statutory reporting cutoff; do not compare different periods."""
    d=datetime.strptime(asof,"%Y%m%d").date();y=d.year
    if d>=date(y,10,31):p=f"{y}0930";annual=y-1
    elif d>=date(y,8,31):p=f"{y}0630";annual=y-1
    elif d>=date(y,4,30):p=f"{y}0331";annual=y-1
    else:p=f"{y-1}0930";annual=y-2
    # A common 9M/6M/Q1 period; TTM = last annual + current YTD - prior YTD.
    py=int(p[:4]);s=p[4:]
    return {"latest":p,"prior":f"{py-1}{s}","prior2":f"{py-2}{s}",
            "annual":f"{annual}1231","annual_prior":f"{annual-1}1231","annual_base":f"{annual-3}1231"}
FIELDS={
 "income_vip":("revenue","n_income","n_income_attr_p","comp_type"),
 "fina_indicator_vip":("profit_dedt","roic","roe_waa","grossprofit_margin"),
 "cashflow_vip":("n_cashflow_act","c_pay_acq_const_fiolta"),
 "balancesheet_vip":("total_assets","total_liab","total_hldr_eqy_exc_min_int")}
def select(rows,api,period,asof):
    """Choose latest known consolidated row. Reject same-day conflicts.
    Vendor may backfill revisions; this is NOT a point-in-time backtest database."""
    groups={};future=0;invalid=0
    for r in rows:
        k=r.get("ts_code")
        if not isinstance(k,str) or not k.endswith((".SH",".SZ")) or str(r.get("end_date"))!=period:continue
        if api!="fina_indicator_vip" and str(r.get("report_type"))!="1":continue
        a=valid_date(r.get("ann_date"));f=valid_date(r.get("f_ann_date"))
        if not a:invalid+=1;continue
        known=max(a,f or a)
        if known>asof:future+=1;continue
        payload={v:number(r.get(v)) for v in FIELDS[api]}
        payload["known_date"]=known
        groups.setdefault(k,[]).append(payload)
    out={};conflicts=0
    for k,g in groups.items():
        d=max(x["known_date"] for x in g);latest=[x for x in g if x["known_date"]==d]
        if any(x!=latest[0] for x in latest):conflicts+=1;continue
        out[k]=latest[0]
    return out,{"raw_rows":len(rows),"unique":len(out),"future_excluded":future,"invalid_date":invalid,"conflicts":conflicts}
def ttm(annual,current,previous):
    if any(v is None for v in (annual,current,previous)):return None
    return annual+current-previous
def yoy(a,b):return a/b-1 if a is not None and b is not None and b>0 else None
def ratio(a,b):return a/b if a is not None and b is not None and b>0 else None
def cagr(a,b,n):return (a/b)**(1/n)-1 if a is not None and b is not None and a>0 and b>0 else None
DEFAULT={"revenue_cagr":.20,"deducted_yoy":.25,"roic":.12,"cash_conversion":.80,"debt_ratio":.60,"pe":50.}
QUALITY=("revenue_cagr","deducted_yoy","roic","cash_conversion","debt_ratio")
def passes(x,limits=DEFAULT,valuation=False):
    if any(x.get(k) is None for k in QUALITY):return False
    if not all(x[k]>=limits[k] for k in QUALITY[:-1]) or x["debt_ratio"]>limits["debt_ratio"]:return False
    return not valuation or (x.get("pe") is not None and 0<x["pe"]<=limits["pe"])
def metrics(code,plan,data,quotes):
    def get(api,p,k):return data.get((api,p),{}).get(code,{}).get(k)
    p=plan["latest"];q=plan["prior"];q2=plan["prior2"];a=plan["annual"];a1=plan["annual_prior"];b=plan["annual_base"]
    inc=lambda d,k:get("income_vip",d,k);fin=lambda d,k:get("fina_indicator_vip",d,k)
    cf=lambda d,k:get("cashflow_vip",d,k);bs=lambda k:get("balancesheet_vip",p,k)
    if inc(p,"comp_type")!=1:return None,"non_industrial_or_missing_type"
    if bs("total_hldr_eqy_exc_min_int") is None or bs("total_hldr_eqy_exc_min_int")<=0:return None,"nonpositive_or_missing_equity"
    # Three-year CAGR compares full annual 2022 and 2025, three year intervals.
    rev=cagr(inc(a,"revenue"),inc(b,"revenue"),3)
    profit=ttm(fin(a,"profit_dedt"),fin(p,"profit_dedt"),fin(q,"profit_dedt"))
    prior_profit=ttm(fin(a1,"profit_dedt"),fin(q,"profit_dedt"),fin(q2,"profit_dedt"))
    net=ttm(inc(a,"n_income"),inc(p,"n_income"),inc(q,"n_income"))
    parent=ttm(inc(a,"n_income_attr_p"),inc(p,"n_income_attr_p"),inc(q,"n_income_attr_p"))
    ocf=ttm(cf(a,"n_cashflow_act"),cf(p,"n_cashflow_act"),cf(q,"n_cashflow_act"))
    capex=ttm(cf(a,"c_pay_acq_const_fiolta"),cf(p,"c_pay_acq_const_fiolta"),cf(q,"c_pay_acq_const_fiolta"))
    debt=ratio(bs("total_liab"),bs("total_assets"))
    roic=fin(a,"roic");roe=fin(a,"roe_waa")
    if profit is None or prior_profit is None or net is None or parent is None:return None,"profit_missing"
    if min(profit,prior_profit,net,parent)<=0:return None,"nonpositive_profit"
    if inc(a,"revenue") is None or inc(b,"revenue") is None:return None,"revenue_missing"
    x={"revenue_cagr":rev,"deducted_yoy":yoy(profit,prior_profit),"roic":roic/100 if roic is not None else None,
       "cash_conversion":ratio(ocf,net),"debt_ratio":debt,
       "roe":roe/100 if roe is not None else None,"deducted_ttm":profit/1e8,"ocf_ttm":ocf/1e8 if ocf is not None else None,
       "fcf_proxy":(ocf-capex)/1e8 if ocf is not None and capex is not None and capex>=0 else None,
       "revenue_ttm":None}
    rt=ttm(inc(a,"revenue"),inc(p,"revenue"),inc(q,"revenue"))
    x["revenue_ttm"]=rt/1e8 if rt is not None else None
    if any(x.get(k) is None for k in QUALITY) or not 0<=debt<1:return None,"quality_missing_or_invalid"
    z=quotes.get(code,{});pe=number(z.get("pe_ttm"));mv=number(z.get("total_mv"))
    x["pe"]=pe if pe is not None and pe>0 else None
    x["market_cap"]=mv/10000 if mv is not None and mv>0 else None
    x["deducted_pe"]=mv*10000/profit if mv is not None and mv>0 else None
    x["growth_to_pe"]=x["pe"]/(100*x["deducted_yoy"]) if x["pe"] is not None and x["deducted_yoy"]>0 else None
    x["report_date"]=p
    x["quality_pass"]=passes(x);x["valuation_pass"]=passes(x,valuation=True)
    return x,"ok"
