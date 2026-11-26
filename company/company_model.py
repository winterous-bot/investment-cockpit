"""Single-stock descriptive financial research. No ranking or return prediction.
Amounts CNY; display unit 100m. Quarterly flows derived from cumulative reports.
"""
from __future__ import annotations
import math
from growth_model import number,valid_date,ttm,yoy,ratio,cagr,period_plan
VERSION="company-fundamentals-v1.0"
FLOW={"revenue":("income_vip","revenue"),"parent_profit":("income_vip","n_income_attr_p"),"net_profit":("income_vip","n_income"),"deducted_profit":("fina_indicator_vip","profit_dedt"),"cfo":("cashflow_vip","n_cashflow_act"),"capex":("cashflow_vip","c_pay_acq_const_fiolta"),"cost":("income_vip","oper_cost"),"rd":("income_vip","rd_exp")}
BAL={"assets":"total_assets","liabilities":"total_liab","parent_equity":"total_hldr_eqy_exc_min_int","cash":"money_cap","receivables":"accounts_receiv","inventory":"inventories","current_assets":"total_cur_assets","current_liabilities":"total_cur_liab"}
QUARTERS=("0331","0630","0930","1231")
def qindex(p):return int(p[:4])*4+QUARTERS.index(p[4:])
def period(q):y,m=divmod(q,4);return str(y)+QUARTERS[m]
def get(data,ep,p,k):return number(data.get((ep,p),{}).get(k))
def cumulative(data,p):return {k:get(data,ep,p,f) for k,(ep,f) in FLOW.items()}
def subtract(a,b):return a-b if a is not None and b is not None else None
def quarter(data,q):
    a=cumulative(data,period(q))
    if q%4==0:return a
    b=cumulative(data,period(q-1));return {k:subtract(v,b[k]) for k,v in a.items()}
def annual_ratio(data,p,k):
    x=get(data,"fina_indicator_vip",p,k);return x/100 if x is not None else None
def money(v):return v/1e8 if v is not None else None
def describe_flow(x,old=None):
    old=old or {}
    r={k:money(v) for k,v in x.items()}
    r.update(revenue_yoy=yoy(x["revenue"],old.get("revenue")),deducted_yoy=yoy(x["deducted_profit"],old.get("deducted_profit")),
             gross_margin=ratio(subtract(x["revenue"],x["cost"]),x["revenue"]),deducted_margin=ratio(x["deducted_profit"],x["revenue"]),
             cash_conversion=ratio(x["cfo"],x["net_profit"]),rd_ratio=ratio(x["rd"],x["revenue"]),
             fcf_proxy=money(subtract(x["cfo"],x["capex"])) if x["capex"] is not None and x["capex"]>=0 else None)
    return r
def balance(data,p):
    b={k:get(data,"balancesheet_vip",p,f) for k,f in BAL.items()}
    return {**{k:money(v) for k,v in b.items()},"debt_ratio":ratio(b["liabilities"],b["assets"]),"current_ratio":ratio(b["current_assets"],b["current_liabilities"])}
def acceleration(qs):
    # Descriptive trend, NOT V1.0's full scanner signal. Use exact prior-year bases.
    tail=qs[-3:];g=[x["deducted_yoy"] for x in tail];bases=[x["base_profit"] for x in tail];margins=[x["base_margin"] for x in tail]
    if len(g)!=3 or any(x is None for x in g+bases+margins) or any(x["deducted_profit"] is None or x["deducted_profit"]<=0 for x in tail):
        return {"status":"unavailable","reason":"nonpositive_or_missing_comparable_profit"}
    if any(x<.1 for x in bases) or any(x<.01 for x in margins):
        return {"status":"low_base","reason":"prior_quarter_profit_below_10m_or_margin_below_1pct","growth":g}
    a,b=g[2]-g[1],g[1]-g[0]
    return {"status":"descriptive","growth":g,"latest_delta":a,"prior_delta":b,
            "label":"持续加速" if g[2]>=.30 and a>=.10-1e-10 and b>=.05-1e-10 else "增速改善" if a>0 else "增速放缓或持平"}
def risk_flags(t,prev,b,old,annual):
    # Explicit deterministic review flags, no composite score. Missing is not safe.
    def flag(key,value,condition,explanation):
        return {"key":key,"value":value,"status":"unknown" if value is None else "review" if condition(value) else "not_triggered","explanation":explanation}
    rv=t.get("revenue_yoy")
    rg=yoy(b.get("receivables"),old.get("receivables"));ig=yoy(b.get("inventory"),old.get("inventory"))
    pm=subtract(t.get("deducted_margin"),prev.get("deducted_margin"))
    f=annual[-3:]
    n=sum(x.get("fcf_proxy") is not None for x in f)
    neg=sum(x.get("fcf_proxy") is not None and x["fcf_proxy"]<0 for x in f)
    return [
      flag("cash_conversion",t.get("cash_conversion"),lambda v:v<.8,"TTM经营现金流/合并净利润低于80%；亏损或缺失时不适用"),
      flag("fcf_proxy",t.get("fcf_proxy"),lambda v:v<0,"TTM经营现金流减资本开支为负，不等同于FCFF"),
      flag("debt_ratio",b.get("debt_ratio"),lambda v:v>.6,"资产负债率超过60%，非有息债务比率"),
      flag("current_ratio",b.get("current_ratio"),lambda v:v<1,"流动比率低于1"),
      flag("margin_change",pm,lambda v:v<-.02,"TTM扣非利润率同比下降超过2个百分点"),
      flag("receivables_gap",subtract(rg,rv),lambda v:v>.15,"应收账款期末同比增速超过TTM营收增速15个百分点；非周转天数"),
      flag("inventory_gap",subtract(ig,rv),lambda v:v>.15,"存货期末同比增速超过TTM营收增速15个百分点"),
      flag("annual_negative_fcf",neg if n==3 else None,lambda v:v>=2,"最近三年中至少两年经营现金流减资本开支为负")]
def profile(data,plan):
    y=int(plan["annual"][:4]);q=qindex(plan["latest"])
    annual=[]
    for year in range(y-4,y+1):
        p=str(year)+"1231";a=cumulative(data,p);old=cumulative(data,str(year-1)+"1231")
        annual.append({"period":p,**describe_flow(a,old),**balance(data,p),"roic":annual_ratio(data,p,"roic"),"roe":annual_ratio(data,p,"roe_waa")})
    quarters=[]
    for k in range(q-11,q+1):
        a,b=quarter(data,k),quarter(data,k-4)
        quarters.append({"period":period(k),**describe_flow(a,b),"base_profit":money(b["deducted_profit"]),"base_margin":ratio(b["deducted_profit"],b["revenue"])})
    def trailing(a,p,old):
        x=cumulative(data,a);z=cumulative(data,p);w=cumulative(data,old)
        return {k:ttm(x[k],z[k],w[k]) for k in FLOW}
    t=trailing(plan["annual"],plan["latest"],plan["prior"]);old=trailing(plan["annual_prior"],plan["prior"],plan["prior2"])
    td=describe_flow(t,old);pd=describe_flow(old)
    b=balance(data,plan["latest"]);ob=balance(data,plan["prior"])
    return {"annual":annual,"quarters":quarters,"ttm":td,"prior_ttm":pd,"balance":b,
        "revenue_cagr3":cagr(annual[-1]["revenue"],annual[-4]["revenue"],3),
        "deducted_cagr3":cagr(annual[-1]["deducted_profit"],annual[-4]["deducted_profit"],3),
        "acceleration":acceleration(quarters),"risk_flags":risk_flags(td,pd,b,ob,annual)}
