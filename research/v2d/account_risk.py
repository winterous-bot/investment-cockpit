"""Pure account pressure-test research prototype, currency amounts / decimal ratios.
Not an order engine. No IO, credentials, or private holdings.
Existing saved V1.7 limits remain authoritative; all extra limits can only tighten.
"""
from __future__ import annotations
import math
CATEGORY_SHOCK={"quality_growth":.35,"high_beta_growth":.50,"stable_leader":.30,
                "cyclical":.45,"thematic":.65}
def finite(x):return isinstance(x,(int,float)) and not isinstance(x,bool) and math.isfinite(x)
def account_risk(positions,cash,debt,rules,market_shock,collateral_min=None,fresh=True):
    """positions: [{id, value, category, group}]; rules are current SAVED row
    in V1.7 percent units. cash/debt/values same currency; debt = all included
    margin account liabilities. collateral_min is user/broker chosen ratio
    (e.g. 2.0), not a broker rule supplied by the program.
    Hypothetical joint caps assume unchanged equity, cash >=0, no costs, all
    assets eligible collateral. Does not solve for trade or repayment sequence."""
    if not finite(cash) or not finite(debt) or min(cash,debt)<0:
        return {"status":"invalid","allow_new_risk":False,"reason":"invalid cash or debt"}
    if any(not finite(x.get("value")) or x["value"]<0 for x in positions):
        return {"status":"invalid","allow_new_risk":False,"reason":"missing/invalid holding value"}
    if len({x.get("id") for x in positions})!=len(positions) or any(not x.get("id") for x in positions):
        return {"status":"invalid","allow_new_risk":False,"reason":"missing/duplicate holding identifier"}
    for k in ("totalCap","debtCap","drawdownCap","clusterCap","singleStressCap"):
        if not finite(rules.get(k)) or rules[k]<0:return {"status":"invalid","allow_new_risk":False,"reason":"invalid saved rule"}
    if not finite(market_shock) or not .20<=market_shock<1:
        return {"status":"invalid","allow_new_risk":False,"reason":"market stress must be >= existing 20% floor and <100%"}
    if collateral_min is not None and (not finite(collateral_min) or collateral_min<=1):
        return {"status":"invalid","allow_new_risk":False,"reason":"invalid collateral minimum"}
    if any(x.get("category") not in CATEGORY_SHOCK or not x.get("group") for x in positions):
        return {"status":"incomplete","allow_new_risk":False,"reason":"category or correlation group incomplete"}
    for k in CATEGORY_SHOCK:
        row=rules.get(k,{})
        if any(not finite(row.get(j)) or row[j]<0 for j in ("single","total")):
            return {"status":"invalid","allow_new_risk":False,"reason":"invalid category caps"}
    S=sum(x["value"] for x in positions); E=S+cash-debt
    if E<=0:return {"status":"invalid","allow_new_risk":False,"reason":"nonpositive equity"}
    s=S/E; d=debt/E; m=market_shock
    base_stock=rules["totalCap"]/100; base_debt=rules["debtCap"]/100; budget=rules["drawdownCap"]/100
    # A market shock is a uniform stock-price scenario, NOT an estimated beta.
    # Never weaken existing 20% shock or saved limits.
    stress_cap=budget/m
    cap=min(base_stock,stress_cap,1+base_debt)
    if collateral_min is not None:
        cap=min(cap,collateral_min/(collateral_min-1+m))
    # debt boundary at unchanged actual stock, and at prospective max stock.
    # Collateral >=k: (E+D-m*S)/D>=k => D/E <= (1-m*s)/(k-1)
    def debt_cap_at(stock_ratio):
        return min(base_debt,max(0,(1-m*stock_ratio)/(collateral_min-1))) if collateral_min is not None else None
    cats={k:0. for k in CATEGORY_SHOCK};groups={};single=[]
    for x in positions:
        k=x["category"]; w=x["value"]/E;g=x["group"]
        cats[k]+=w;groups[g]=groups.get(g,0)+w
        lim=min(rules[k]["single"]/100,rules["singleStressCap"]/100/CATEGORY_SHOCK[k])
        single.append({"id":x["id"],"actual":w,"cap":lim,"loss":w*CATEGORY_SHOCK[k],"over":w>lim+1e-10})
    severe_loss=sum(cats[k]*q for k,q in CATEGORY_SHOCK.items())
    gross_stress=S*(1-m)+cash
    dc=debt_cap_at(s)
    violations=[]
    if s>cap+1e-10:violations.append("stock_cap")
    if d>base_debt+1e-10:violations.append("debt_cap")
    if dc is not None and d>dc+1e-10:violations.append("collateral_stress")
    if s*m>budget+1e-10:violations.append("portfolio_stress")
    if any(x["over"] for x in single):violations.append("single_cap_or_stress")
    if any(v>rules[k]["total"]/100+1e-10 for k,v in cats.items()):violations.append("category_cap")
    if any(v>rules["clusterCap"]/100+1e-10 for v in groups.values()):violations.append("group_cap")
    return {"status":"ok" if fresh and collateral_min is not None else "incomplete",
        "allow_new_risk":bool(fresh and collateral_min is not None and not violations),
        "equity":E,"stock_ratio":s,"debt_ratio":d,"market_shock":m,
        "saved_stock_cap":base_stock,"saved_debt_cap":base_debt,"stress_stock_cap":stress_cap,
        "joint_stock_cap":cap,"debt_cap_at_actual_stock":dc,"debt_cap_at_stock_cap":debt_cap_at(cap),
        "uniform_stress_loss_ratio":s*m,"stressed_equity":E-S*m,
        "simplified_collateral_ratio":(S+cash)/debt if debt else None,
        "simplified_stressed_collateral_ratio":gross_stress/debt if debt else None,
        "category_severe_loss_ratio":severe_loss,"category_severe_stressed_equity":E*(1-severe_loss),
        "category_severe_stressed_collateral":(S+cash-E*severe_loss)/debt if debt else None,
        "category_weights":cats,"group_weights":groups,"single":single,"violations":violations,
        "notes":["Category simultaneous severe shock is disclosure only; existing single-stock caps still apply.",
                 "Collateral ratio is a simplified all-assets-eligible scenario, not brokerage margin liquidation calculation.",
                 "Joint stock cap assumes cash>=0 and feasible debt, not independent permission to raise either.",
                 "Missing/stale market data or unspecified collateral minimum freezes new risk in this prototype."]}
