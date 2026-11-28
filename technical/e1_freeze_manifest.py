"""Independently validate the original artifact before freezing it; no resampling."""
import json,sys
from pathlib import Path
from collections import Counter
from .model_e0 import digest,EXCLUDED
from .e1_manifest import ENGINE,PLAN,SEED,HORIZONS,SPLITS,panel_counts,split,quarter
EXPECTED="355776bb03d2a3a5b45a5cec858bb885c9cbe83097b8d0b78a3e09523eca5d7d"
def verify(path):
    m=json.loads(Path(path).read_text(encoding="utf8"))
    checksum=m.pop("digest")
    if checksum!=EXPECTED or digest(m)!=EXPECTED:raise ValueError("manifest hash mismatch")
    m["digest"]=checksum
    assert m["schema"]==1 and m["engine"]==ENGINE and m["plan"]==PLAN and m["seed"]==SEED
    assert set(m["excluded"])==EXCLUDED and m["purge_sessions"]==40 and m["no_outcomes"] is True
    assert set(m["quarters"])=={f"{y}Q{q}" for y in range(2023,2027) for q in range(1,5)}
    totals={k:{p:Counter() for p in ("core","daily","overlap")} for k in SPLITS}
    all_dates=[]
    for key,q in sorted(m["quarters"].items()):
        a=[k for xs in q["core"].values() for k in xs];b=[k for xs in q["daily"].values() for k in xs]
        assert len(a)==len(set(a))==240 and len(b)==len(set(b))==60 and set(b)<=set(a) and not set(a)&EXCLUDED
        assert all(set(xs)<=set(q["core"][s]) for s,xs in q["daily"].items())
        ds=q["dates"];dates=[x["date"] for x in ds];assert dates==sorted(set(dates)) and dates[0]==q["first"]
        assert all(quarter(d)==key for d in dates);assert len(q["prior_sessions"])==20 and max(q["prior_sessions"])<dates[0]
        assert set(q["liquidity_coverage"])==set(q["prior_sessions"])
        assert all(v["eligible"]>0 and v["positive"]/v["eligible"]>=.85 for v in q["liquidity_coverage"].values())
        for x in ds:
            assert x["split"]==split(x["date"])
            assert set(x["label_end_by_horizon"])==set(map(str,HORIZONS))
            assert all(v is None or x["date"]<v<=m["split_last_sessions"][x["split"]] for v in x["label_end_by_horizon"].values())
        c=panel_counts(ds,240,60);assert c==q["counts"]
        for p,v in c.items():totals[ds[0]["split"]][p].update(v)
        all_dates.extend(ds)
    assert len(all_dates)==945 and len({x["date"] for x in all_dates})==945
    for s in SPLITS:
        dates=[x for x in all_dates if x["split"]==s]
        assert sum(x["purged"] for x in dates)==40
        for i,x in enumerate(dates):
            assert x["purged"]==(i+40>=len(dates))
            assert x["label_end_by_horizon"]=={str(h):dates[i+h]["date"] if i+h<len(dates) else None for h in HORIZONS}
    assert {s:{p:dict(c) for p,c in v.items()} for s,v in totals.items()}==m["totals_by_split"]
    return m
if __name__=="__main__":
    m=verify(sys.argv[1]);print("TECH_E1_FREEZE "+json.dumps({"digest":m["digest"],"quarters":16,"verified":True,"no_outcomes":True}),flush=True)
