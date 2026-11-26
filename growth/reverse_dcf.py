"""Reverse FCFF DCF scenario engine. Amounts in CNY 100m, rates decimal.
Conditional expectations, not a fair-value forecast or trading signal.
"""
from __future__ import annotations
import math,statistics
from growth_model import number,ttm

WACCS=(.08,.10,.12)
TERMINAL_GROWTH=(.02,.03,.04)
HORIZONS=(5,10)
GROWTH_MIN=-.20
GROWTH_MAX=.60
# At most 100% of NOPAT is reinvested in this initial nonnegative-FCFF model.
# A company can actually grow faster with external capital or different returns.
def finite(x):return isinstance(x,(int,float)) and math.isfinite(x)
def base_inputs(annual,current,previous,balance,row):
    """Annual 3 full years + current TTM. Missing values remain missing.
    Vendor FCFF and EBIT are proxies; vendor methodology not independently audited.
    """
    def reject(reason):return None,reason
    if len(annual)!=3 or any(x is None for x in [*annual,current,previous,balance]):return reject("missing_financials")
    def series(k):
        vals=[number(x.get(k)) for x in annual]
        return vals+[ttm(vals[-1],number(current.get(k)),number(previous.get(k)))]
    ebit=series("ebit");fcff=series("fcff")
    roics=[number(x.get("roic")) for x in annual]
    if any(v is None for v in ebit+fcff+roics):return reject("missing_fcff_ebit_roic")
    if min(ebit)<=0 or min(fcff)<=0:return reject("nonpositive_annual_or_ttm_fcff_ebit")
    if min(roics)<=0:return reject("nonpositive_annual_roic")
    # Scenario tax rate, not reported effective tax: avoid mixing tax benefits and nonoperating items.
    tax=.25
    nopat=[v*(1-tax) for v in ebit]
    ratios=[f/n for f,n in zip(fcff,nopat)]
    if max(ratios)/min(ratios)>4 or max(ratios)>2:return reject("unstable_cash_conversion")
    # Normalize cash conversion rather than dollar levels, retaining latest operating scale.
    conversion=.5*statistics.median(ratios[:3])+.5*ratios[-1]
    base_nopat=nopat[-1]/1e8
    base_fcff=base_nopat*conversion
    roic=statistics.median(roics)/100
    if not .05<=roic<=.60:return reject("roic_outside_model_range")
    mv=number(row.get("market_cap"));v=row.get("valuation") or {}
    price=number(v.get("close"))
    if not mv or mv<=0 or not price or price<=0 or not v.get("share_verified"):return reject("unverified_equity_value")
    debt=number(current.get("interestdebt"));netdebt=number(current.get("netdebt"))
    ei=number(balance.get("total_hldr_eqy_inc_min_int"));ee=number(balance.get("total_hldr_eqy_exc_min_int"))
    minority=number(balance.get("minority_int"))
    other=number(balance.get("oth_eqt_tools"))
    if any(z is None for z in (debt,netdebt,ei,ee)):return reject("missing_ev_bridge")
    if minority is None:minority=ei-ee
    if abs((ei-ee)-minority)>max(1e6,.01*abs(ei)):return reject("minority_equity_mismatch")
    if debt<0 or netdebt>debt+max(1e6,.01*debt) or minority<0:return reject("invalid_ev_bridge")
    # Blank other equity tools commonly means no disclosed amount; do not silently assign value if known positive.
    # Book values are approximations, not market values. Other nonoperating assets not separately added.
    other=other or 0.
    if other<0:return reject("invalid_other_equity")
    bridge=(netdebt+minority+other)/1e8
    ev=mv+bridge
    if ev<=0:return reject("nonpositive_enterprise_value")
    out={"nopat":base_nopat,"fcff":base_fcff,"ttm_fcff":fcff[-1]/1e8,
         "annual_fcff":[v/1e8 for v in fcff[:3]],"conversion":conversion,
         "roic":roic,"tax":tax,"equity":mv,"price":price,"netdebt":netdebt/1e8,
         "minority":minority/1e8,"other_equity":other/1e8,"bridge":bridge,"ev":ev,
         "historical_roic":[v/100 for v in roics]}
    return out,"ok"

def dcf(base,g,n,wacc,terminal):
    """NOPAT growth drives incremental capital need; terminal reinvestment reset.
    R_high = historical 3y median ROIC proxy for future incremental ROIC.
    High-stage reinvestment = max(g,0)/R; no assumed capital release on contraction.
    Terminal incremental ROIC = WACC (no perpetual excess return).
    """
    if n not in HORIZONS or not (0<terminal<wacc) or not finite(g) or not GROWTH_MIN<=g<=min(GROWTH_MAX,base["roic"])+1e-12:raise ValueError("scenario outside domain")
    if min(base["nopat"],base["fcff"],base["roic"],base["equity"],base["price"])<=0:raise ValueError("invalid base")
    rr=max(g,0)/base["roic"]
    if rr>1+1e-10:raise ValueError("reinvestment exceeds model domain")
    flows=[base["nopat"]*(1+g)**t*(1-rr) for t in range(1,n+1)]
    terminal_fcff=base["nopat"]*(1+g)**n*(1+terminal)*(1-terminal/wacc)
    tv=terminal_fcff/(wacc-terminal)
    pv_terminal=tv/(1+wacc)**n
    ev=sum(f/(1+wacc)**t for t,f in enumerate(flows,1))+pv_terminal
    equity=ev-base["bridge"]
    fcff_cagr=(max(0.,flows[-1])/base["fcff"])**(1/n)-1
    return {"ev":ev,"equity":equity,"price":equity/base["equity"]*base["price"] if equity>0 else None,
            "nopat_growth":g,"fcff_cagr":fcff_cagr,"reinvestment":rr,
            "terminal_share":pv_terminal/ev if ev>0 else None,"year_n_fcff":flows[-1]}

def solve(base,n,wacc,terminal):
    """Search full bounded domain and bracket ALL sign-changing roots.
    For positive growth, with terminal ROC=WACC, derivative simplifies:
    EV(g)=NOPAT0*[sum (1+g)^t/(1+w)^t*(1-g/R) + ((1+g)/(1+w))^n/w].
    EV is monotonic in g within this segment iff R>w; otherwise declining/flat.
    Negative-growth segment uses zero reinvestment, is increasing. Split at zero.
    """
    top=min(GROWTH_MAX,base["roic"])
    target=base["ev"]
    def f(g):return dcf(base,g,n,wacc,terminal)["ev"]-target
    # Split by structural turning point; no arbitrary root selection.
    bounds=[GROWTH_MIN,0.,top]
    vals=[f(g) for g in bounds]
    tol=max(1e-7,target*1e-9)
    roots=[];flat=False
    for lo,hi,fl,fh in zip(bounds,bounds[1:],vals,vals[1:]):
        if abs(fl)<=tol and abs(fh)<=tol:
            flat=True;continue
        if abs(fl)<=tol:roots.append(lo)
        if abs(fh)<=tol:roots.append(hi)
        if fl*fh<0:
            for _ in range(70):
                mid=(lo+hi)/2;fm=f(mid)
                if abs(fm)<=tol:lo=hi=mid;break
                if fl*fm<=0:hi=mid;fh=fm
                else:lo=mid;fl=fm
            roots.append((lo+hi)/2)
    unique=[]
    for g in sorted(roots):
        if not unique or abs(g-unique[-1])>1e-6:unique.append(g)
    if flat or len(unique)>1:return {"status":"ambiguous","roots":len(unique)}
    if not unique:
        return {"status":"price_above_model_range" if max(vals)<-tol else "price_below_model_range" if min(vals)>tol else "no_solution",
                "growth_bounds":[GROWTH_MIN,top]}
    o=dcf(base,unique[0],n,wacc,terminal)
    if abs(o["ev"]-target)>max(1e-5,target*1e-7):return {"status":"residual_error"}
    return {"status":"ok",**o}
def analyze(base):
    matrix=[]
    for n in HORIZONS:
        for w in WACCS:
            for t in TERMINAL_GROWTH:
                matrix.append({"years":n,"wacc":w,"terminal":t,**solve(base,n,w,t)})
    # User's proposed forward scenarios, not company forecasts. Infeasible scenarios visibly omitted.
    forward=[]
    for n in HORIZONS:
        for g in (.15,.25,.35):
            if g>min(GROWTH_MAX,base["roic"]):
                forward.append({"years":n,"growth":g,"status":"requires_more_than_100pct_reinvestment"});continue
            forward.append({"years":n,"growth":g,"status":"ok",**dcf(base,g,n,.10,.03)})
    return {"status":"ok","base":base,"sensitivity":matrix,"forward":forward,
            "assumptions":{"wacc":WACCS,"terminal_growth":TERMINAL_GROWTH,"horizons":HORIZONS,
              "terminal_roic":"WACC","tax":.25,"growth_domain":[GROWTH_MIN,min(GROWTH_MAX,base["roic"])],
              "terminal_growth_invariance":True}}
