"""V1.4 consolidated statement reconstruction, amounts in CNY yuan.
CFO-based FCFF proxy under PRC industrial cash-flow classification.
Independent accrual bridge is diagnostic, not a substitute for missing CFO.
"""
from __future__ import annotations
import statistics
from growth_model import number,valid_date,ttm
from reverse_dcf import analyze
INCOME_CORE=("operate_profit","total_profit","income_tax","n_income","fin_exp_int_exp","fin_exp_int_inc","revenue")
INCOME_OPTIONAL=("invest_income","fv_value_chg_gain","asset_disp_income","oth_income","net_expo_hedging_benefits","amodcost_fin_assets")
CF_CORE=("n_cashflow_act","c_pay_acq_const_fiolta","c_cash_equ_end_period")
CF_OPTIONAL=("depr_fa_coga_dpba","amort_intang_assets","lt_amort_deferred_exp","use_right_asset_dep","decr_inventories","decr_oper_payable","incr_oper_payable","im_net_cashflow_oper_act")
BS_CORE=("total_assets","total_liab","total_hldr_eqy_inc_min_int","total_hldr_eqy_exc_min_int","money_cap")
DEBT_FIELDS=("st_borr","lt_borr","bond_payable","st_bonds_payable","st_fin_payable","non_cur_liab_due_1y","lease_liab")
INVEST_FIELDS=("trad_asset","debt_invest","oth_debt_invest","oth_eq_invest","oth_illiq_fin_assets","lt_eqt_invest")
BS_OPTIONAL=DEBT_FIELDS+INVEST_FIELDS+("minority_int","oth_eqt_tools","lt_payable","oth_ncl","oth_cur_liab")
FIELDS={"income_vip":INCOME_CORE+INCOME_OPTIONAL,"cashflow_vip":CF_CORE+CF_OPTIONAL,"balancesheet_vip":BS_CORE+BS_OPTIONAL}
CORE={"income_vip":INCOME_CORE,"cashflow_vip":CF_CORE,"balancesheet_vip":BS_CORE}
def pick(rows,period,asof,fields):
    """Only latest consolidated cumulative records; prefer explicit latest flag
    among same-announcement versions, accept a compatible superset; no cell splicing."""
    groups={};bad_date=0
    for r in rows:
        if str(r.get("end_date"))!=period or str(r.get("report_type"))!="1" or str(r.get("comp_type"))!="1" or not r.get("ts_code"):continue
        a=valid_date(r.get("ann_date"));f=valid_date(r.get("f_ann_date"))
        if not a or not f or max(a,f)>asof:bad_date+=1;continue
        # Missing schema field is NOT an optional blank.
        if any(k not in r for k in fields):continue
        z={k:number(r[k]) for k in fields}
        groups.setdefault(r["ts_code"],[]).append((max(a,f),str(r.get("update_flag"))=="1",z))
    out={};conflicts=0;superset=0
    for code,g in groups.items():
        date=max(v[0] for v in g);current=[v for v in g if v[0]==date]
        flagged=[v for v in current if v[1]]
        if flagged:current=flagged
        zs=[v[2] for v in current]
        if all(z==zs[0] for z in zs):out[code]=zs[0];continue
        best=[z for z in zs if all(all(other[k] is None or z[k]==other[k] for k in fields) for other in zs)]
        if best:out[code]=best[0];superset+=1
        else:conflicts+=1
    return out,{"conflicts":conflicts,"compatible_superset":superset,"invalid_or_future_dates":bad_date}
def require(row,fields):
    if row is None:raise ValueError("missing_statement")
    missing=[k for k in fields if number(row.get(k)) is None]
    if missing:raise ValueError("missing_"+missing[0])
    return {k:number(row[k]) for k in fields}
def optional(row,fields):
    # Only named line items in a verified schema. Blank optional items assumed
    # absent, counted and exposed; not used for core data.
    if any(k not in row for k in fields):raise ValueError("missing_optional_schema")
    return {k:number(row[k]) or 0. for k in fields},sum(number(row[k]) is None for k in fields)
def close(a,b,scale,tol=.005):
    return abs(a-b)<=max(1e5,tol*abs(scale))
def operating(i):
    r=require(i,INCOME_CORE);o,blanks=optional(i,INCOME_OPTIONAL)
    if r["revenue"]<=0 or r["fin_exp_int_exp"]<0 or r["fin_exp_int_inc"]<0:raise ValueError("invalid_income")
    if not close(r["total_profit"]-r["income_tax"],r["n_income"],max(abs(r["total_profit"]),abs(r["n_income"]))):raise ValueError("income_identity")
    # Exclude disclosed investment/fair-value/disposal/other income from operating
    # profit; remove net interest. Retain operating impairment and FX.
    noncore=sum(o.values())
    ebit=r["operate_profit"]+r["fin_exp_int_exp"]-r["fin_exp_int_inc"]-noncore
    return {**r,"ebit":ebit,"noncore_income":noncore,"optional_blanks":blanks}
def capital(b,c):
    r=require(b,BS_CORE);cf=require(c,CF_CORE)
    o,blanks=optional(b,BS_OPTIONAL)
    a,l,e=r["total_assets"],r["total_liab"],r["total_hldr_eqy_inc_min_int"]
    if min(a,e)<=0 or l<0 or not close(a,l+e,a,.002):raise ValueError("balance_identity")
    if r["money_cap"]<0 or cf["c_cash_equ_end_period"]<0:raise ValueError("invalid_cash")
    if any(o[k]<0 for k in DEBT_FIELDS+INVEST_FIELDS+("oth_eqt_tools",)):raise ValueError("invalid_debt_or_investments")
    minority=e-r["total_hldr_eqy_exc_min_int"]
    if minority<0 or (b.get("minority_int") is not None and not close(minority,o["minority_int"],e,.002)):raise ValueError("minority_equity_mismatch")
    debt=sum(o[k] for k in DEBT_FIELDS)
    if debt>l+max(1e5,.002*a):raise ValueError("debt_exceeds_liabilities")
    # Current portion of noncurrent liabilities is a conservative debt proxy.
    # Do not add long-term payables or other liabilities wholesale.
    cash=min(r["money_cap"],cf["c_cash_equ_end_period"])
    investments=sum(o[k] for k in INVEST_FIELDS)
    ic=e+debt-cash-investments
    if ic<=0:raise ValueError("nonpositive_invested_capital")
    return {"assets":a,"liab":l,"equity":e,"parent_equity":r["total_hldr_eqy_exc_min_int"],
            "debt":debt,"cash":cash,"money_cap":r["money_cap"],"cash_equivalents":cf["c_cash_equ_end_period"],
            "investments":investments,"ic":ic,"minority":minority,"other_equity":o["oth_eqt_tools"],
            "optional_blanks":blanks,"current_portion":o["non_cur_liab_due_1y"],"lease":o["lease_liab"],
            "other_liab_unclassified":o["lt_payable"]+o["oth_ncl"]+o["oth_cur_liab"]}
def flow(i,c,tax):
    r=require(c,CF_CORE)
    if r["c_pay_acq_const_fiolta"]<0:raise ValueError("invalid_capex")
    nopat=i["ebit"]*(1-tax)
    # PRC industrial CFO generally excludes financing interest payments. Remove
    # estimated interest income after tax and interest tax shield. These are
    # accrual proxies; do not claim exact cash taxes or exact interest receipts.
    adj=i["fin_exp_int_exp"]*tax+i["fin_exp_int_inc"]*(1-tax)
    fcff=r["n_cashflow_act"]-r["c_pay_acq_const_fiolta"]-adj
    # Indirect cash flow working-capital changes: vendor decr_oper_payable is
    # documented as decrease in operating receivables. Only if all fields exist.
    keys=("depr_fa_coga_dpba","amort_intang_assets","lt_amort_deferred_exp","decr_inventories","decr_oper_payable","incr_oper_payable")
    vals=[number(c.get(k)) for k in keys]
    accrual=None
    if all(v is not None for v in vals):
        accrual=nopat+sum(vals)-r["c_pay_acq_const_fiolta"]
        # Lease depreciation may already be included in fixed-asset depreciation;
        # do not add it a second time. Indirect bridge is diagnostic only.
    indirect=number(c.get("im_net_cashflow_oper_act"))
    if indirect is not None and not close(indirect,r["n_cashflow_act"],max(abs(indirect),abs(r["n_cashflow_act"])),.01):raise ValueError("cashflow_identity")
    return {"nopat":nopat,"fcff":fcff,"cfo":r["n_cashflow_act"],"capex":r["c_pay_acq_const_fiolta"],
            "interest_adjustment":adj,"accrual_fcff":accrual,"ebit":i["ebit"],"revenue":i["revenue"],"noncore_income":i["noncore_income"]}
def roll(a,c,p):
    # Flow amounts only; never annualize balance-sheet stock.
    return {k:ttm(a[k],c[k],p[k]) for k in a if k in c and k in p and k!="optional_blanks"}
def reconstruct(row,incomes,flows,balances,years,latest,prior):
    """Return full accounting diagnostics even when DCF domain is unsuitable."""
    result={"status":"unavailable","category":"data","reason":None}
    try:
        ip={t:operating(incomes.get(t)) for t in years+[latest,prior]}
        opening=str(int(years[0][:4])-1)+"1231"
        bp={t:capital(balances.get(t),flows.get(t)) for t in [opening]+years+[latest,prior]}
        taxrates=[ip[t]["income_tax"]/ip[t]["total_profit"] for t in years if ip[t]["total_profit"]>0 and 0<=ip[t]["income_tax"]/ip[t]["total_profit"]<=.35]
        if len(taxrates)<2:raise ValueError("unstable_or_missing_effective_tax")
        tax=statistics.median(taxrates)
        f={t:flow(ip[t],flows.get(t),tax) for t in years+[latest,prior]}
        tt=roll(f[years[-1]],f[latest],f[prior])
        roics=[f[t]["nopat"]/((bp[a]["ic"]+bp[t]["ic"])/2) for a,t in zip([opening]+years[:-1],years)]
        # Check that latest balance/profit/OCF align with the independent V1.1 scan.
        checks=[("ocf_ttm",tt["cfo"]/1e8),("revenue_ttm",tt["revenue"]/1e8),("debt_ratio",bp[latest]["liab"]/bp[latest]["assets"])]
        for k,v in checks:
            old=number(row.get(k))
            if old is None or abs(v-old)>max(.001,.01*abs(old)):raise ValueError("base_scan_mismatch_"+k)
        current=bp[latest]
        v=row.get("valuation") or {};mv=number(row.get("market_cap"));price=number(v.get("close"))
        if not mv or mv<=0 or not price or price<=0 or not v.get("share_verified"):raise ValueError("unverified_equity_value")
        bridge=(current["debt"]-current["cash"]-current["investments"]+current["minority"]+current["other_equity"])/1e8
        ev=mv+bridge
        diag={"annual_periods":years,"annual":[f[t] for t in years],"ttm":tt,
              "capital_periods":[opening]+years+[latest,prior],"capital":[bp[t] for t in [opening]+years+[latest,prior]],
              "roics":roics,"tax":tax,"tax_observations":taxrates,"bridge":bridge,"ev":ev,
              "vendor_roic_last":row.get("roic"),
              "optional_blank_income":sum(ip[t]["optional_blanks"] for t in ip),
              "optional_blank_balance":sum(bp[t]["optional_blanks"] for t in bp)}
        warnings=[]
        if any(abs(f[t]["noncore_income"])>max(1e5,.20*abs(f[t]["ebit"])) for t in years+[latest,prior]):warnings.append("material_noncore_income")
        if any(z["accrual_fcff"] is not None and abs(z["accrual_fcff"]-z["fcff"])>.5*max(abs(z["fcff"]),1e5) for z in [f[t] for t in years]+[tt]):warnings.append("accrual_cashflow_divergence")
        if current["other_liab_unclassified"]>.10*current["assets"]:warnings.append("material_unclassified_liabilities")
        diag["warnings"]=warnings
        result.update(accounting=diag,category="model")
        fs=[f[t]["fcff"] for t in years]+[tt["fcff"]];ns=[f[t]["nopat"] for t in years]+[tt["nopat"]]
        if min(fs+ns)<=0:raise ValueError("nonpositive_annual_or_ttm_fcff_ebit")
        if min(roics)<=0:raise ValueError("nonpositive_annual_roic")
        ratios=[a/b for a,b in zip(fs,ns)]
        if max(ratios)/min(ratios)>4 or max(ratios)>2:raise ValueError("unstable_cash_conversion")
        roic=statistics.median(roics)
        if not .05<=roic<=.60:raise ValueError("roic_outside_model_range")
        if ev<=0:raise ValueError("nonpositive_enterprise_value")
        conversion=.5*statistics.median(ratios[:3])+.5*ratios[-1]
        base={"nopat":ns[-1]/1e8,"fcff":ns[-1]*conversion/1e8,"ttm_fcff":fs[-1]/1e8,
              "annual_fcff":[z/1e8 for z in fs[:3]],"conversion":conversion,"roic":roic,"tax":tax,"equity":mv,"price":price,
              "netdebt":(current["debt"]-current["cash"])/1e8,"investments":current["investments"]/1e8,
              "minority":current["minority"]/1e8,"other_equity":current["other_equity"]/1e8,"bridge":bridge,"ev":ev,
              "historical_roic":roics,"warnings":warnings}
        result=analyze(base)
        result["assumptions"]["tax"]=tax
        result.update(category="solved",accounting=diag)
    except ValueError as exc:result["reason"]=str(exc)
    return result
