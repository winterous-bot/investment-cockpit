"""R2 statistical boundaries and strict R1 checkpoint migration.
Missing count keys mean zero; never apply that convention to market data.
"""
import re
from collections import Counter,defaultdict
from .e1_q1_r1 import AuditLedger
R1_SHA="85c12dd8a11bc8b849373cae9cbbff7d1011c482"
STATES=("computed","not_observed","data_quality_blocked","source_unavailable")
PANELS=("core","daily","overlap","unique")
DIMENSIONS=("board","liquidity","industry","volatility","regime","risk","listing_age","date")
def require(ok,msg):
    if not ok:raise ValueError(msg)
def count(c,k):
    n=c.get(k,0)
    require(type(n) is int and n>=0,"invalid count "+k)
    return n
def validate_counts(c,n):
    require(isinstance(c,dict) and all(type(v) is int and v>=0 for v in c.values()),"invalid counter")
    require(count(c,"planned")==n==sum(count(c,k) for k in STATES),"sample denominator mismatch")
    computed=count(c,"computed")
    for k in ("feature_ready","strict_calendar_ready","composite_ready","scored_among_feature_ready","scored_among_strict_ready","context_ready","major_history"):
        require(count(c,k)<=computed,"feature count exceeds computed: "+k)
    require(count(c,"scored_among_feature_ready")<=min(count(c,"feature_ready"),count(c,"composite_ready")),"joint feature count")
    require(count(c,"scored_among_strict_ready")<=min(count(c,"strict_calendar_ready"),count(c,"composite_ready")),"joint strict count")
    for h in (1,5,10,20,40):
        eligible=count(c,f"label_{h}_eligible")
        scored=count(c,f"scored_label_{h}")
        strict=count(c,f"strict_scored_label_{h}")
        require(strict<=scored<=min(eligible,count(c,"composite_ready")) and eligible<=computed,"joint label count")
    return c
def expected_panels(dates,weekly,daily):
    n=sum(d in weekly for d in dates)
    return {"core":n,"daily":len(dates) if daily else 0,"overlap":n if daily else 0,"unique":len(dates)}
def validate_panels(panels,dims,expected):
    require(set(panels)<=set(PANELS),"unknown panel")
    for name in PANELS:
        c=panels.get(name,{})
        validate_counts(c,expected[name])
        for kind in DIMENSIONS:
            rows=[v for k,v in dims.items() if k.startswith(name+"|"+kind+"|")]
            total=Counter()
            for v in rows:
                validate_counts(v,count(v,"planned"));total.update(v)
            keys=set(total)|set(c)
            require(all(total[k]==count(c,k) for k in keys),"dimension totals mismatch "+name+" "+kind)
    require(all(len(k.split("|",2))==3 and k.split("|",2)[0] in PANELS and k.split("|",2)[1] in DIMENSIONS for k in dims),"unknown dimension")
    keys=set().union(*(set(c) for c in panels.values()))
    for k in keys:
        require(count(panels.get("core",{}),k)+count(panels.get("daily",{}),k)-count(panels.get("overlap",{}),k)==count(panels.get("unique",{}),k),"overlap mismatch "+k)
def validate_stock(r,dates,weekly,daily,quality_state=None,first_invalid=None):
    expected=expected_panels(dates,weekly,daily)
    validate_counts(r["counts"],len(dates))
    validate_panels(r["panels"],r["dimensions"],expected)
    require(Counter(r["counts"])==Counter(r["panels"].get("unique",{})),"stock unique mismatch")
    require(isinstance(r["output_digest"],str) and re.fullmatch("[0-9a-f]{64}",r["output_digest"]) is not None,"invalid result hash")
    require(type(r["paired_checks"]) is int and 0<=r["paired_checks"]==r["prefix_checks"]<=2,"invalid oracle count")
    if quality_state is None or quality_state=="ok":
        require(r.get("quality_state") is None and not count(r["counts"],"data_quality_blocked") and not count(r["counts"],"source_unavailable"),"normal stock status mismatch")
    else:
        require(r.get("quality_state")==quality_state and r.get("first_invalid")==first_invalid,"quality state mismatch")
    return r
def checkpoint_hit(ledger,k,source,dates,weekly,daily,state,first_invalid=None):
    # Source-unavailable records are retried; absence of data is not stable evidence.
    if state=="source_unavailable":return None
    r=ledger.read(k,source)
    if r is None:return None
    try:return validate_stock(r,dates,weekly,daily,state,first_invalid)
    except (ValueError,TypeError,KeyError,AttributeError):return None
def stock_event(k,out,done,total):
    c=out["counts"]
    validate_counts(c,count(c,"planned"))
    return {"code":k,"computed":count(c,"computed"),"not_observed":count(c,"not_observed"),
            "data_quality_blocked":count(c,"data_quality_blocked"),"source_unavailable":count(c,"source_unavailable"),"done":done,"total":total}
def report_dimensions(dims):
    # Compact public aggregate logging for inspection; no feature values.
    return {k:v for k,v in dims.items() if k.startswith("unique|") and "|date|" not in k}
