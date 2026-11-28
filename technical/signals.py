"""R2 deterministic signal primitives, not trading recommendations or probabilities."""
from .indicators import indicators
def crossing(old,new):
    if old is None or new is None:return None
    if old<=0 and new>0:return 1
    if old>=0 and new<0:return -1
    return 0
def signal_snapshot(bars,freq):
    if len(bars)<2:return {}
    prev,cur=indicators(bars[:-1],freq),indicators(bars,freq)
    def gap(x,a,b):return x[a]-x[b] if x.get(a) is not None and x.get(b) is not None else None
    out={"ma5_ma10_cross":crossing(gap(prev,"ma5","ma10"),gap(cur,"ma5","ma10")),
         "ma10_ma20_cross":crossing(gap(prev,"ma10","ma20"),gap(cur,"ma10","ma20")),
         "macd_cross":crossing(gap(prev,"dif","dea"),gap(cur,"dif","dea")),
         "close_ma20_cross":crossing(gap(prev,"close","ma20"),gap(cur,"close","ma20"))}
    for n in (20,60):
        prior=bars[-n-1:-1]
        hi=max(x["high"] for x in prior) if len(prior)==n else None
        lo=min(x["low"] for x in prior) if len(prior)==n else None
        out["prior_high"+str(n)]=hi
        out["prior_low"+str(n)]=lo
        out["breakout"+str(n)]=None if hi is None else 1 if bars[-1]["close"]>hi else -1 if bars[-1]["close"]<lo else 0
    return out
