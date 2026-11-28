"""Research-only scoped memoization; frozen function bodies remain untouched."""
from contextlib import contextmanager
from functools import lru_cache
from collections import OrderedDict
from . import indicators as I,quality,signals,model_a,model_b,model_c,model_c_r1,model_e0,data
from .model_e0 import CachedHistory,feature_calendar_diagnostics,admission_counts
import time

MODULES=(I,quality,signals,model_a,model_b,model_c,model_c_r1,model_e0,data)
@contextmanager
def acceleration(max_indicators=32):
    """Single-threaded offline process only. Cache exact pure input results.
    No global permanent patches, no cached stock views across symbols, no
    approximate arithmetic or changed historical windows. Restore on exceptions.
    """
    originals={k:getattr(I,k) for k in ("date","period","indicators")}
    ds=lru_cache(maxsize=40000)(originals["date"])
    ps=lru_cache(maxsize=80000)(originals["period"])
    cache=OrderedDict();stats={"indicator_hits":0,"indicator_misses":0}
    def date(v):return ds(v) if type(v) is str else originals["date"](v)
    def period(d,f):return ps(d,f) if type(d) is str and type(f) is str else originals["period"](d,f)
    def indicators(bars,f):
        if not bars:return originals["indicators"](bars,f)
        # Frozen indicator function consumes only ordered close/vol and frequency.
        # Exact input tuples, not rounded values or probabilistic hashes.
        key=(f,tuple((b["close"],b["vol"]) for b in bars))
        if key in cache:
            stats["indicator_hits"]+=1;cache.move_to_end(key);return dict(cache[key])
        stats["indicator_misses"]+=1
        result=originals["indicators"](bars,f);cache[key]=dict(result)
        while len(cache)>max_indicators:cache.popitem(last=False)
        return result
    patches=[];wrappers={"date":date,"period":period,"indicators":indicators}
    try:
        for mod in MODULES:
            for k,old in originals.items():
                if getattr(mod,k,None) is old:
                    patches.append((mod,k,old));setattr(mod,k,wrappers[k])
        yield stats
    finally:
        stats.update(date_hits=ds.cache_info().hits,date_misses=ds.cache_info().misses,
                     period_hits=ps.cache_info().hits,period_misses=ps.cache_info().misses)
        for mod,k,old in reversed(patches):setattr(mod,k,old)
        cache.clear();ds.cache_clear();ps.cache_clear()

def evaluate(q,d,cal,context,tax,members):
    """Same frozen engines and E0 diagnostics; time every stage, including gates."""
    timings={};t=time.perf_counter()
    def mark(k):
        nonlocal t
        now=time.perf_counter();timings[k]=now-t;t=now
    i,s,mt,br,li=context
    v=q.view(d,cal);mark("view")
    a=model_a.analyze(q,d,cal,i);mark("A")
    ind=model_b.industry_context(q,d,cal,i,tax,members,s)
    b=model_b.attach(a,mt,br,li,ind);mark("B")
    r=model_c_r1.analyze_r1(q,b,cal);mark("C_R1")
    coverage=feature_calendar_diagnostics(q,v,cal);mark("feature_calendar")
    admission=admission_counts(q,d,cal);mark("label_admission")
    return {"view":v,"A":a,"B":b,"C":r,"coverage":coverage,"admission":admission},timings

def exact_equal(a,b):
    # Dict equality plus strict canonical serialization is checked by caller.
    return a==b
