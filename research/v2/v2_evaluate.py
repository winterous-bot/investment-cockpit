#!/usr/bin/env python3
"""Evaluate historical year shards. NOT a parameter optimizer.
2024-01-01 onward is a chronological holdout (not blindly preregistered).
"""
from __future__ import annotations
import json, argparse
from pathlib import Path
from collections import Counter
from v2_model import evaluate,state_sequence,summarize

BASE=Path(__file__).resolve().parent
def read_years(folder,require_complete=True):
    files=sorted(folder.glob("year_*.json"))
    years=[int(x.stem.split("_")[1]) for x in files]
    if require_complete and years!=list(range(2015,2027)):
        raise RuntimeError(f"Historical shards incomplete: {years}; expected 2015..2026")
    rows=[];metadata={}
    for fn in files:
        x=json.loads(fn.read_text(encoding="utf8"))
        if x.get("version")!="V2.0a-frozen-2026-11-17" or x.get("raw_paid_data_committed") is not False:
            raise RuntimeError(f"Bad historical shard version or license boundary: {fn.name}")
        yr=int(x["year"])
        metadata[str(yr)]={"calendar_days":len(x["rows"]),
           "data_complete":sum(r["T"] is not None and r["B"] is not None for r in x["rows"]),
           "taxonomy_backcast":sum(r.get("historical_taxonomy_backcast",False) for r in x["rows"]),
           "date_range":[x["rows"][0]["date"],x["rows"][-1]["date"]] if x["rows"] else []}
        rows.extend(x["rows"])
    return rows,metadata,years

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--shards",default=str(BASE/"results"))
    ap.add_argument("--split",default="2024-01-01")
    ap.add_argument("--partial",action="store_true",help="Smoke test only; marks results as partial")
    args=ap.parse_args()
    rows,metadata,years=read_years(Path(args.shards),not args.partial)
    report=evaluate(rows,args.split)
    report["provenance"]={"source":"Tushare Pro by GitHub Actions; derived aggregates only",
      "years_present":years,"complete_2015_2026":years==list(range(2015,2027)),
      "data_by_year":metadata,
      "look_ahead_controls":[
        "Historical daily stock snapshots, no 2026 listed-universe filter",
        "No CSI2000 backcast before 2023-08-11",
        "No future technical candles or breadth input, close(t) executed close(t+1)",
        "Cost 10 bps of changed exposure",
        "SW2021 index backcast before Dec-2021 is research-only; NOT PIT industry membership",
        "2024+ time holdout, but parameters were formed after observing this era; NOT blinded"] }
    # Evaluate strict post-SW2021 era using same frozen thresholds; 2024+ holdout separate.
    late=[r for r in rows if r["date"]>="2022-01-01"]
    if late:
        report["post_2021_taxonomy"] = summarize(state_sequence(late))
    allrows=state_sequence(sorted(rows,key=lambda x:x["date"]))
    report["diagnostics"]={
      "by_year":{y:{"unknown":sum(r["candidate"]=="unknown" for r in allrows if r["date"].startswith(y)),
                    "leadership_data_missing":sum(r.get("leaders") is None for r in allrows if r["date"].startswith(y)),
                    "state_switches":sum(i>0 and r["date"].startswith(y) and allrows[i-1]["state"]!=r["state"] for i,r in enumerate(allrows))}
                 for y in metadata},
      "candidate_counts":dict(Counter(r["candidate"] for r in allrows))}
    out=BASE/"results"/"backtest_report.json"
    out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf8")
    print(json.dumps({"status":"complete" if report["provenance"]["complete_2015_2026"] else "PARTIAL",
      "years":years,"full":report["result"]["full"],"time_holdout":report["result"]["time_holdout"]},
      ensure_ascii=False),flush=True)

if __name__=="__main__":main()
