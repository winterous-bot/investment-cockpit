"""Live benchmark: print only limited derived sample comparison, not raw licensed data."""
import os,json
from pathlib import Path
from .data import Tushare,calendar,benchmarks,build,stock_history
from .diagnostics import sensitivity,provider_check,historical_checks,emit
REF=json.loads(Path(__file__).with_name("reference_20261127.json").read_text())
def compare(report):
    out=[]
    for period in ("day","week","month"):
        for key,expected in REF[period].items():
            value=report["indicators"][period].get(key)
            # Screenshot displays 0.01 yuan/indicator points; allow up to 0.02 for rounding.
            # Volume labels are rounded: 129.5万 = +/-500 hands, 1609万 = +/-5000.
            tol=(5000 if period=="month" else 500 if key=="vol" or period=="week" else 50) if key.startswith("vol") else .02
            out.append({"period":period,"metric":key,"reference":expected,"calculated":round(value,4) if value is not None else None,"difference":round(value-expected,4) if value is not None else None,"tolerance":tol,"match":value is not None and abs(value-expected)<=tol+1e-9})
    return out
def main():
    api=Tushare(os.environ["TUSHARE_TOKEN"]);asof=REF["asof"]
    cal=calendar(api,asof);idx=benchmarks(api,asof)
    for code in (REF["code"],"600000.SH","300750.SZ"):
        try:
            bars,start,raw,factors=stock_history(api,code,asof,details=True)
            r=build(api,code,asof,cal,idx,history=(bars,start))
            summary={"code":code,"status":"ok","asof":r["asof"],"first_bar":r["first_bar"],"listing_date":r["listing_date"],"counts":r["counts"],"completed":r["completed"],"missing_recent_sessions":r["missing_recent_sessions"],"feature_count":sum(v is not None for v in r["features"].values()),"daily_basic_complete":all(v is not None for v in r["daily_basic"].values()),"benchmark_count":sum(all(v is not None for v in x.values()) for x in r["relative_strength"].values())}
            if code==REF["code"]:
                c=compare(r);summary["matches"]=sum(x["match"] for x in c);summary["total"]=len(c)
                for x in c:print("TECH_COMPARE "+json.dumps(x,ensure_ascii=False),flush=True)
                sensitivity(bars,asof,cal,REF)
                # Screenshot arrows, not inferred from a fitted price series.
                arrows={"day":{"ma5":1,"ma10":1,"ma20":1,"ma60":-1,"ma250":-1,"dif":1,"dea":1,"macd":1,"rsi6":1,"rsi12":1,"rsi24":1,"vol":1,"vol_ma5":1,"vol_ma10":1,"boll_mid":1,"boll_upper":1,"boll_lower":1},"week":{"ma5":1,"ma10":-1,"ma20":-1,"dif":1,"dea":-1,"macd":1,"rsi6":1,"rsi12":1,"rsi24":1,"vol":1,"vol_ma5":-1,"vol_ma10":-1,"boll_mid":-1,"boll_upper":-1,"boll_lower":1},"month":{"ma5":-1,"ma10":-1,"ma20":1,"dif":-1,"dea":-1,"macd":-1,"rsi6":1,"rsi12":1,"rsi24":1,"vol":1,"vol_ma5":-1,"vol_ma10":-1,"boll_mid":1,"boll_upper":-1,"boll_lower":1}}
                for p,expected in arrows.items():
                    for k,sign in expected.items():emit("TECH_DIRECTION",{"period":p,"metric":k,"expected":sign,"actual":r["directions"][p].get(k),"match":r["directions"][p].get(k)==sign})
            print("TECH_FOUNDATION "+json.dumps(summary,ensure_ascii=False),flush=True)
            provider_check(api,code,bars,asof,cal)
            historical_checks(api,code,raw,factors)
        except Exception as e:
            print("TECH_FOUNDATION "+json.dumps({"code":code,"status":"failed","reason":type(e).__name__,"detail":str(e)[:120] if isinstance(e,ValueError) else "source unavailable"},ensure_ascii=False),flush=True)
            if code==REF["code"]:raise RuntimeError("Reference data validation unavailable") from None
if __name__=="__main__":main()
