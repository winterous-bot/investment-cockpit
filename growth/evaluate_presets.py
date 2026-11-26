"""Evaluate frozen presets on existing validated current cross-section."""
import json,sys
from pathlib import Path
from growth_model import PRESETS,DEFAULT,preset_summary
def main():
    d=Path(sys.argv[1]);p=d/"snapshot.json";x=json.loads(p.read_text());r=x["report"]
    if not r["data_coverage_pass"] or r["asof"]!="20261125" or len(x["rows"])!=r["complete_metrics"]:raise RuntimeError("Source coverage or date invalid")
    stats=preset_summary(x["rows"])
    b=next(v for v in stats["scenarios"] if v["id"]=="balanced")
    if b["quality_count"]!=r["quality_pass"] or b["valuation_count"]!=r["quality_and_valuation_pass"]:raise RuntimeError("Balanced preset differs from original verified results")
    r.update(version="growth-scanner-v1.1",presets=PRESETS,default_limits=DEFAULT,preset_statistics=stats)
    r["notes"].append("Frozen scenario thresholds compare selection coverage on same snapshot, not expected returns or optimized historical cutoffs.")
    p.write_text(json.dumps(x,ensure_ascii=False,separators=(",",":")),encoding="utf8")
    (d/"validation.json").write_text(json.dumps(r,ensure_ascii=False,indent=2),encoding="utf8")
    print(json.dumps(stats,ensure_ascii=False))
if __name__=="__main__":main()
