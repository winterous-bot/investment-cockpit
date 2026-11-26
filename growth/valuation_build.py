"""Add relative valuation to a validated financial snapshot in a temporary directory."""
from __future__ import annotations
import sys,os,json,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"scripts"))
from tushare_5000 import Tushare,SafeAPIError
from valuation_model import completed_month_ends,enrich
def main():
    d=Path(sys.argv[1]);p=d/"snapshot.json";x=json.loads(p.read_text());r=x["report"]
    if not r.get("data_coverage_pass") or len(x["rows"])!=r["complete_metrics"]:raise RuntimeError("Base snapshot incomplete")
    day=r["quote_date"];api=Tushare(os.environ.get("TUSHARE_TOKEN"))
    universe={v["code"] for v in x["rows"]}
    def ask_day(t,fields):
        rows=api.ask("daily_basic",{"trade_date":t},fields)
        rows=[v for v in rows if str(v.get("trade_date"))==t]
        # Deduplicate only identical rows; conflicting values must not be used.
        by={};bad=set()
        for z in rows:
            k=z.get("ts_code")
            if k in by and by[k]!=z:bad.add(k)
            by[k]=z
        return {k:z for k,z in by.items() if k not in bad and k in universe},len(by)
    q,n=ask_day(day,"ts_code,trade_date,close,pe_ttm,total_mv,total_share")
    if len(q)<.95*len(universe):raise RuntimeError("Latest daily_basic coverage insufficient")
    start=str(int(day[:4])-3)+day[4:6]+"01"
    cal=api.ask("trade_cal",{"exchange":"SSE","start_date":start,"end_date":day,"is_open":"1"},"cal_date,is_open")
    dates=completed_month_ends(cal,day)
    histories={k:{} for k in universe};health=[]
    for t in dates:
        try:
            rows,total=ask_day(t,"ts_code,trade_date,pe_ttm")
            # Older months may have fewer listings; avoid trusting clearly truncated responses.
            ok=total>=3500
            health.append({"date":t,"rows":total,"sample":len(rows),"ok":ok})
            if ok:
                for k,z in rows.items():histories[k][t]=z.get("pe_ttm")
        except SafeAPIError:
            health.append({"date":t,"rows":0,"sample":0,"ok":False})
        time.sleep(.25)
    if sum(h["ok"] for h in health)<32:raise RuntimeError("Historical valuation cross-section coverage insufficient")
    stats=enrich(x["rows"],q,histories,dates,day)
    r.update(version="growth-scanner-v1.2",valuation_statistics=stats,
             valuation_health={"quote_date":day,"quote_rows":n,"history_months":len(dates),"history_ok":sum(h["ok"] for h in health),"monthly_checks":health},
             valuation_method={"history":"36 completed calendar month-end vendor reported PE-TTM; positive PE only; at least 24 valid observations and 6 per 12-month block; current reported EPS = close/current PE; P25/P50/P75 price reference, not target price",
              "peer":"Same Tushare stock_basic industry; other companies in complete positive-profit scanner universe; 3y revenue CAGR +/-15pp, TTM deducted profit growth +/-30pp, annual ROIC +/-7pp; at least 8 matched peers; deducted PE P25/P50/P75 times current deducted EPS implied by close/deducted PE; broad industry median context only",
              "limits":"Reported and deducted earnings bases are separate. Current quote and market cap cross-check; implied prices only when close times total shares matches market cap within 2%. Vendor data can be revised; historical positive multiples exclude loss periods. No intrinsic value, no automatic recommendation."})
    p.write_text(json.dumps(x,ensure_ascii=False,separators=(",",":"),allow_nan=False),encoding="utf8")
    (d/"validation.json").write_text(json.dumps(r,ensure_ascii=False,indent=2),encoding="utf8")
    print(json.dumps({"valuation_statistics":stats,"valuation_health":r["valuation_health"]},ensure_ascii=False))
if __name__=="__main__":main()
