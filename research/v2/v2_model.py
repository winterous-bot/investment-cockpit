"""V2.0a frozen five-state market classifier. Pure, deterministic; no API calls.
All inputs are daily point-in-time aggregates, NEVER raw portfolio information.
Do not tune frozen thresholds based on the 2024+ evaluation window.
"""
from __future__ import annotations
from dataclasses import dataclass
from collections import Counter
import math

INDEX_WEIGHTS = {"000300.SH": .30, "000905.SH": .25, "000852.SH": .25, "932000.CSI": .20}
LAUNCH_CSI2000 = "2023-08-11"  # publication; exclude the prior back-calculated series
STATES = ("bull", "structural", "range", "bottoming", "bear")
CONFIRM = {"bull": 5, "structural": 5, "range": 3, "bottoming": 5, "bear": 3}
TARGET = {"bull": 1., "structural": .8, "range": .55, "bottoming": .35, "bear": .125}
# Recovered original weights: 35/25/25/15 and 40/35/25; thresholds frozen from V2.0a.
def mean(a):
    return sum(a)/len(a) if a else None

def stdev(a):
    if not a: return None
    m = mean(a)
    return math.sqrt(mean([(x-m)**2 for x in a]))

def index_trend(px):
    """Return [-100,+100] for the LAST date of a series of >=250 daily closes."""
    if len(px) < 250 or any(x is None or x <= 0 for x in px[-250:]): return None
    p = px[-1]
    m20, m60, m250 = mean(px[-20:]), mean(px[-60:]), mean(px[-250:])
    m60prior = mean(px[-70:-10])
    middle = 1 if p > m60 and m20 > m60 else (-1 if p < m60 and m20 < m60 else 0)
    slope_pct = m60/m60prior-1
    slope = 1 if slope_pct >= .003 else (-1 if slope_pct <= -.003 else 0)
    ret = [math.log(px[i]/px[i-1]) for i in range(len(px)-20,len(px))]
    sd = stdev(ret)
    z = math.log(p/px[-21])/(math.sqrt(20)*sd) if sd and sd > 1e-12 else 0.
    momentum = 1 if z >= .5 else (-1 if z <= -.5 else 0)
    longterm = 1 if p > m250 and m60 > m250 else (-1 if p < m250 and m60 < m250 else 0)
    return 35*middle + 25*slope + 25*momentum + 15*longterm

def classify_candidate(row):
    """Return five-state candidate or unknown, evaluated ONLY from this date or earlier."""
    t, b = row.get("T"), row.get("B")
    p, industry, a5 = row.get("P60"), row.get("I60"), row.get("A5")
    if any(x is None for x in (t,b,p,industry,a5)): return "unknown"
    up = row.get("up_votes",0) >= 3
    down = row.get("down_votes",0) >= 3
    broad = b >= .60 and p >= .55 and industry >= .55
    weak = b <= .40 and p < .45 and industry < .45
    if (t <= -55 and down and weak) or (t <= -25 and down and weak and row.get("drawdown120",0) <= -.12):
        return "bear"
    if t >= 55 and up and broad and a5 >= .52:
        return "bull"
    if (row.get("prior_decline") and row.get("repair_count",0) >= 2
            and t > -55 and b < .60):
        return "bottoming"
    if (row.get("leaders",0) >= 3 and b >= .40 and t >= -25 and not broad):
        return "structural"
    return "range"

def state_sequence(rows):
    """No state change before a persistent candidate qualifies; unknown freezes state."""
    active = "unknown"
    pending, count = None, 0
    results = []
    for row in rows:
        candidate = classify_candidate(row)
        if candidate == "unknown":
            pending, count = None, 0
        elif active == "unknown":
            if candidate == pending: count += 1
            else: pending, count = candidate, 1
            if count >= CONFIRM[candidate]: active, pending, count = candidate, None, 0
        elif candidate == active:
            pending, count = None, 0
        else:
            if candidate == pending: count += 1
            else: pending, count = candidate, 1
            if count >= CONFIRM[candidate]: active, pending, count = candidate, None, 0
        results.append({**row, "candidate": candidate, "state": active})
    return results

def summarize(xs):
    """Net-of-turnover-cost, no leverage: signal at t close, execute t+1 close,
    effective in close-to-close return t+1 -> t+2. No hindsight trades."""
    if len(xs) < 3: return {"n": 0, "status":"insufficient"}
    strategy, benchmark, fixed50 = 1., 1., 1.
    peak_s = peak_b = peak_f = 1.
    dd_s = dd_b = dd_f = 0.
    turnover = 0.
    state_counts = Counter()
    valid = 0
    missing = 0
    last_pos = 0.
    for i in range(2,len(xs)):
        row = xs[i]
        previous = xs[i-1]
        close, close_prior = row.get("benchmark"), previous.get("benchmark")
        if close is None or close_prior is None or close_prior <= 0:
            missing += 1; continue
        s = xs[i-2]["state"]
        # The new position becomes tradable after the following close. Unknown holds cash.
        pos = TARGET.get(s, 0.)
        dr = close/close_prior-1
        trade = abs(pos-last_pos)
        strategy *= 1 + pos*dr - .001*trade
        benchmark *= 1 + dr
        fixed50 *= 1 + .5*dr
        turnover += trade
        last_pos = pos
        peak_s = max(peak_s, strategy); peak_b = max(peak_b, benchmark); peak_f = max(peak_f,fixed50)
        dd_s = min(dd_s,strategy/peak_s-1)
        dd_b = min(dd_b,benchmark/peak_b-1)
        dd_f = min(dd_f,fixed50/peak_f-1)
        state_counts[s] += 1
        valid += 1
    if not valid: return {"n":0,"status":"insufficient"}
    annual = lambda nav: round(nav**(252/valid)-1,6)
    return {"n":valid,"from":xs[2]["date"],"to":xs[-1]["date"],
       "annual_return":annual(strategy),"benchmark_annual":annual(benchmark),
       "fixed50_annual":annual(fixed50),"max_drawdown":round(dd_s,6),
       "benchmark_max_drawdown":round(dd_b,6),"fixed50_max_drawdown":round(dd_f,6),
       "turnover":round(turnover,3),"state_counts":dict(state_counts),"missing":missing}

def evaluate(rows, split="2024-01-01"):
    from collections import defaultdict
    rows = sorted(rows,key=lambda x:x["date"])
    if len({x["date"] for x in rows}) != len(rows): raise ValueError("Duplicate dates across year files")
    classified = state_sequence(rows)
    segments = {
        "train": [x for x in classified if x["date"] < split],
        "time_holdout": [x for x in classified if x["date"] >= split],
        "full": classified}
    changes = [{"date":x["date"],"state":x["state"],"candidate":x["candidate"]}
               for i,x in enumerate(classified) if x["state"] != "unknown"
               and (i==0 or classified[i-1]["state"] != x["state"])]
    by_year = defaultdict(list)
    for x in classified: by_year[x["date"][:4]].append(x)
    return {"parameter_version":"V2.0a-frozen-2026-11-17",
       "data_quality":"2021 SW2021 historical index is back-calculated; no claim of historical contemporaneous taxonomy.",
       "temporal_split":split,"result":{k:summarize(v) for k,v in segments.items()},
       "yearly":{k:summarize(v) for k,v in by_year.items()},
       "transitions":changes,
       "counts":dict(Counter(x["candidate"] for x in classified)),
       "coverage":{"days":len(classified),"unknown":sum(x["candidate"]=="unknown" for x in classified),
                   "valid_states":sum(x["state"]!="unknown" for x in classified)}}
