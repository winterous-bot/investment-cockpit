"""Fresh market/industry actual data on fixed sample dates; no predictive claims."""
import os
from .data import Tushare,stock_history,benchmarks
from .quality import QualityHistory
from .model_a import analyze
from .model_a_validate import sessions_for
from .model_b import market_trend,industry_context,stock_breadth,sector_breadth,participation,combine_breadth,activity,attach
from .model_b_data import taxonomy,membership_rows,sector_series,universe_history,cross_sections,turnover_series,prefix
from .diagnostics import emit

def main():
    api=Tushare(os.environ["TUSHARE_TOKEN"]);asof="20261127";dates=("20261030","20261120",asof)
    sessions=sessions_for(api,asof);idx=benchmarks(api,asof)
    sectors=taxonomy(api);sw=sector_series(api,sectors,"20250101",asof)
    turnover=turnover_series(api,"20250101",asof)
    # Shared cross-section cache in memory, exact union of 80-session windows.
    needed=sorted({x for d in dates for x in [z for z in sessions if z<=d][-80:]})
    try:
        u=universe_history(api)
        prices,factors,changes,issues=cross_sections(api,needed,u)
        emit("TECH_MODEL_B_SOURCE",{"universe":len(u),"delisted":sum(e is not None for _,e in u.values()),"sessions_expected":len(needed),"daily_sessions":len(prices),"factor_sessions":len(factors),"issues":issues,"sector_series":sum(v is not None for v in sw.values()),"taxonomy":len(sectors)})
    except Exception as e:
        u={};prices={};factors={};changes={}
        emit("TECH_MODEL_B_SOURCE",{"state":"partial","reason":type(e).__name__,"sector_series":sum(v is not None for v in sw.values())})
    context={}
    for d in dates:
        ix={k:prefix(v,d) for k,v in idx.items()};sx={k:prefix(v,d) for k,v in sw.items()}
        mt=market_trend(ix,sessions,d)
        br=combine_breadth([stock_breadth(u,prices,factors,sessions,d),sector_breadth(sx,sessions,d),participation(u,changes,sessions,d)],d)
        li=activity(prefix(turnover["000001.SH"],d),prefix(turnover["399107.SZ"],d),sessions,d)
        # Market computations must ignore later cross-sections and reject stale index inputs.
        assert mt["score"] is not None
        assert market_trend({k:v[:-1] if v else None for k,v in ix.items()},sessions,d)["score"] is None
        assert br==combine_breadth([stock_breadth(u,{k:v for k,v in prices.items() if k<=d},{k:v for k,v in factors.items() if k<=d},sessions,d),sector_breadth(sx,sessions,d),participation(u,{k:v for k,v in changes.items() if k<=d},sessions,d)],d)
        context[d]=(ix,sx,mt,br,li)
        emit("TECH_MODEL_B_MARKET",{"asof":d,"trend":mt,"breadth":br,"activity":li})
    for code in ("002475.SZ","600000.SH","300750.SZ"):
        _,_,raw,fs=stock_history(api,code,asof,details=True,audit_fields=True);q=QualityHistory(raw,fs,code,asof)
        try:members=membership_rows(api,code)
        except Exception as e:
            members=[];emit("TECH_MODEL_B_MEMBERSHIP_ERROR",{"code":code,"reason":type(e).__name__})
        for d in dates:
            ix,sx,mt,br,li=context[d]
            a=analyze(q,d,sessions,ix);industry=industry_context(q,d,sessions,ix,sectors,members,sx)
            r=attach(a,mt,br,li,industry)
            assert r["horizons"]==a["horizons"] and r["probability"] is None
            assert attach(a,mt,br,li,industry,True)["market_industry_context"]["block_new_exposure"] is True
            # No future membership entries alter dated membership selection.
            past=[m for m in members if str(m.get("in_date",""))<=d]
            assert industry==industry_context(q,d,sessions,ix,sectors,past,sx)
            emit("TECH_MODEL_B_SAMPLE",{"code":code,"asof":d,"industry":industry,"context":r["market_industry_context"],"short_D":r["horizons"]["short"]["D"],"medium_D":r["horizons"]["medium"]["D"],"action":r["action"]})
if __name__=="__main__":main()
