"""Fresh joined B sources, fixed nine samples plus predeclared earlier regime date."""
import os,json
from pathlib import Path
from .data import Tushare,stock_history,benchmarks
from .quality import QualityHistory
from .model_a import analyze
from .model_a_validate import sessions_for
from .model_b import market_trend,stock_breadth,sector_breadth,participation,combine_breadth,activity
from .model_b_data import taxonomy,membership_rows,sector_series,universe_history,cross_sections,turnover_series,prefix
from .model_d import build_report,render
from .diagnostics import emit

def main():
    api=Tushare(os.environ["TUSHARE_TOKEN"]);end="20261127"
    # Extra date fixed before source retrieval, not selected by result.
    dates=("20260430","20261030","20261120",end)
    sessions=sessions_for(api,end);idx=benchmarks(api,end)
    tax=taxonomy(api);sw=sector_series(api,tax,"20250101",end);turn=turnover_series(api,"20250101",end)
    needed=sorted({x for d in dates for x in [z for z in sessions if z<=d][-80:]})
    u=universe_history(api);prices,factors,changes,issues=cross_sections(api,needed,u)
    emit("TECH_MODEL_D_SOURCE",{"dates":dates,"universe":len(u),"delisted":sum(e is not None for _,e in u.values()),"expected_sessions":len(needed),"price_sessions":len(prices),"factor_sessions":len(factors),"issues":issues,"sectors":len(tax),"sector_series":sum(v is not None for v in sw.values())})
    ctx={}
    for d in dates:
        ix={k:prefix(v,d) for k,v in idx.items()};sx={k:prefix(v,d) for k,v in sw.items()}
        mt=market_trend(ix,sessions,d)
        br=combine_breadth([stock_breadth(u,prices,factors,sessions,d),sector_breadth(sx,sessions,d),participation(u,changes,sessions,d)],d)
        li=activity(prefix(turn["000001.SH"],d),prefix(turn["399107.SZ"],d),sessions,d)
        ctx[d]=(ix,sx,mt,br,li)
        emit("TECH_MODEL_D_MARKET",{"asof":d,"trend":mt,"breadth":br,"activity":li})
    out=Path("research-reports-d");out.mkdir(exist_ok=True)
    n=0;full=0;prefixes=0;defensive=0
    for code in ("002475.SZ","600000.SH","300750.SZ"):
        _,_,raw,fs=stock_history(api,code,end,details=True,audit_fields=True)
        q=QualityHistory(raw,fs,code,end);members=membership_rows(api,code)
        for d in dates:
            ix,sx,mt,br,li=ctx[d]
            args=(d,sessions,ix,mt,br,li,tax,members,sx)
            r=build_report(q,*args)
            qt=QualityHistory([x for x in raw if x["trade_date"]<=d],[x for x in fs if x["trade_date"]<=d],code,d)
            past=[x for x in members if str(x.get("in_date",""))<=d]
            rp=build_report(qt,d,sessions,ix,mt,br,li,tax,past,sx)
            assert r==rp and render(r)==render(rp),"report prefix mismatch"
            assert r["probability"] is None and r["plan"]["new_exposure"]!="conditional_opportunity"
            assert r["horizons"]==analyze(q,d,sessions,ix)["horizons"]
            assert r["permissions"]=={"holding":None,"portfolio_permission":None,"severe_risk":None}
            text=render(r);assert all(f"## {i}." in text for i in range(1,7))
            # No actual holdings or private watchlist in validation. Only derived public sample results.
            (out/f"{code}-{d}.json").write_text(json.dumps(r,ensure_ascii=False,indent=2,allow_nan=False),encoding="utf-8")
            (out/f"{code}-{d}.md").write_text(text,encoding="utf-8")
            n+=1;prefixes+=1
            ready=all(r["context"][k] for k in ("market_ready","breadth_ready","liquidity_ready","industry_ready")) and r["composite_ready"]
            full+=int(ready);defensive+=int(r["context"]["state"]=="defensive")
            emit("TECH_MODEL_D_SAMPLE",{"code":code,"asof":d,"full_evidence":ready,"context":r["context"],"industry":r["industry"]["membership"],"D":[r["horizons"][h]["D"] for h in ("short","medium")],"locations":{h:{k:l[k] for k in ("support","resistance","invalidation","target_reference","reward_risk","risk_veto")} for h,l in r["locations"].items()},"plan":r["plan"],"gaps":r["gaps"],"prefix_match":True,"report":text})
    emit("TECH_MODEL_D_ACCEPTANCE",{"reports":n,"full_evidence":full,"prefix_match":prefixes,"defensive":defensive,"expected":12,"no_actual_entry_permission":True})
    if n!=12 or full!=12 or len(prices)!=len(needed) or len(factors)!=len(needed):raise RuntimeError("incomplete real evidence")
if __name__=="__main__":main()
