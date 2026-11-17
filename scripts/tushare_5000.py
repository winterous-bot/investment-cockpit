#!/usr/bin/env python3
"""Tushare 5000-point unified market-data verifier and aggregate-only scorer.

Fetches paid API data ephemerally; persists ONLY compact derived scores and
safe API health metadata to a public GitHub Pages repository. Never logs or
commits the token, stock-by-stock adjusted factors, or SW raw daily histories.
No account holdings are read.
"""
from __future__ import annotations
import argparse
import json
import math
import os
import statistics
import sys
import time
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import breadth_model as bm

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/"data"
API="https://api.tushare.pro"
BEIJING=ZoneInfo("Asia/Shanghai")
INDEX_WEIGHTS=(("000300.SH","沪深300",0.30),
               ("000905.SH","中证500",0.25),
               ("000852.SH","中证1000",0.25),
               ("932000.CSI","中证2000",0.20))
API_LIST=("trade_cal","stock_basic","index_classify","sw_daily",
          "adj_factor","index_daily","daily_basic","daily")
POINTS={"trade_cal":2000,"stock_basic":2000,"index_classify":2000,
        "sw_daily":5000,"adj_factor":2000,"index_daily":2000,
        "daily_basic":2000,"daily":120}


def num(v):
    try:
        n=float(v)
        return n if math.isfinite(n) else None
    except (TypeError,ValueError):
        return None


def half(v):
    return max(0., min(5., round(float(v)*2)/2))


def iso(d):
    return d.strftime("%Y%m%d")


def load_json(path,default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError,ValueError):
        return default


def atomic(path,payload):
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix(path.suffix+".tmp")
    tmp.write_text(json.dumps(payload,ensure_ascii=False,separators=(",",":")),encoding="utf-8")
    os.replace(tmp,path)


class SafeAPIError(RuntimeError):
    """No response text or tokens in errors that reach public CI logs."""


class Tushare:
    def __init__(self,token,request=urllib.request.urlopen):
        if not token:
            raise SafeAPIError("GitHub Actions Secret TUSHARE_TOKEN 未配置")
        self.token=token
        self.request=request
        self.status={name:{"state":"not_checked","min_points":POINTS[name]}
                     for name in API_LIST}
        self.counts={name:0 for name in API_LIST}

    def ask(self,name,params=None,fields=None,*,retry=2):
        req_data={"api_name":name,"token":self.token,"params":params or {}}
        if fields:
            req_data["fields"]=fields
        body=json.dumps(req_data,separators=(",",":")).encode("utf-8")
        request=urllib.request.Request(API,data=body,
              headers={"Content-Type":"application/json","Accept":"application/json"},
              method="POST")
        last="connection_failure"
        for attempt in range(retry):
            self.counts[name]=self.counts.get(name,0)+1
            try:
                with self.request(request,timeout=28) as response:
                    payload=json.loads(response.read(4500000).decode("utf-8"))
                if not isinstance(payload,dict) or payload.get("code")!=0:
                    code=payload.get("code") if isinstance(payload,dict) else "invalid"
                    raise SafeAPIError(f"{name} API返回非零状态码 {str(code)[:16]}（权限/频率/接口需核查）")
                rows=(payload.get("data") or {}).get("items") or []
                header=(payload.get("data") or {}).get("fields") or []
                if not isinstance(rows,list) or not isinstance(header,list):
                    raise SafeAPIError(f"{name} API数据结构异常")
                result=[dict(zip(header,row)) for row in rows if isinstance(row,list) and len(row)==len(header)]
                self.status[name]={"state":"ok","min_points":POINTS[name],"rows":len(result)}
                return result
            except SafeAPIError as exc:
                self.status[name]={"state":"failed","min_points":POINTS[name],"reason":str(exc)}
                raise
            except (OSError,ValueError,TimeoutError,urllib.error.URLError) as exc:
                last=type(exc).__name__
                if attempt+1<retry:
                    time.sleep(.65*(attempt+1))
        self.status[name]={"state":"failed","min_points":POINTS.get(name,0),
                           "reason":f"API连接或解析异常 {last}"}
        raise SafeAPIError(f"{name} {last}")


def latest_dates(api,asof,days=150):
    x=api.ask("trade_cal",{"exchange":"SSE","start_date":iso(asof-timedelta(days=250)),
                             "end_date":iso(asof),"is_open":"1"},
                  "cal_date,is_open,pretrade_date")
    ds=sorted({str(row.get("cal_date")) for row in x
               if str(row.get("is_open"))=="1" and len(str(row.get("cal_date")))==8})
    if len(ds)<105:
        raise SafeAPIError(f"trade_cal交易日期不足: {len(ds)}")
    api.status["trade_cal"]["open_sessions"]=len(ds)
    return ds[-days:]


def stock_universe(api):
    rows=api.ask("stock_basic",{"list_status":"L"},
                "ts_code,name,exchange,market,list_date,list_status")
    shsz={str(r.get("ts_code")) for r in rows if str(r.get("ts_code","")).endswith((".SH",".SZ"))}
    if len(shsz)<4500:
        raise SafeAPIError(f"stock_basic沪深A股上市样本量不足: {len(shsz)}")
    api.status["stock_basic"]["sh_sz_listed"]=len(shsz)
    api.status["stock_basic"]["sample_only"]=True
    return shsz


def sw_level1(api):
    rows=api.ask("index_classify",{"level":"L1","src":"SW2021"},
                 "index_code,industry_name,level,is_pub,src")
    sectors={}
    for row in rows:
        code=str(row.get("index_code") or "").split(".")[0]
        if len(code)!=6 or not code.isdigit() or str(row.get("level"))!="L1":
            continue
        if str(row.get("is_pub","1")) in ("0","False"):
            continue
        sectors[code+".SI"]=str(row.get("industry_name") or code)
    if len(sectors)<29 or len(sectors)>35:
        raise SafeAPIError(f"申万2021一级行业数量异常: {len(sectors)}，预期31")
    api.status["index_classify"]["level1_count"]=len(sectors)
    api.status["index_classify"]["taxonomy"]="SW2021"
    return sectors


def sw_sector_breadth(api,sectors,dates,asof):
    start=dates[max(0,len(dates)-105)]
    end=asof
    above=0
    up20=0
    valid=0
    latest_day_counts={}
    verified=[]
    for code,name in sectors.items():
        try:
            rows=api.ask("sw_daily",{"ts_code":code,"start_date":start,
                         "end_date":end},"ts_code,trade_date,close,pct_change")
        except SafeAPIError:
            # A temporary missing sector must not be converted into a bullish/bearish vote.
            continue
        close_by_day={}
        for row in rows:
            d=str(row.get("trade_date") or "")
            c=num(row.get("close"))
            if len(d)==8 and c is not None and c>0:
                close_by_day[d]=c
        if asof not in close_by_day:
            continue
        latest_day_counts[asof]=latest_day_counts.get(asof,0)+1
        series=[close_by_day[d] for d in dates if d<=asof and d in close_by_day]
        # Full MA60 requires 60 consecutive valid market sessions for this sector.
        window=[close_by_day.get(d) for d in dates if d<=asof][-60:]
        recent=[close_by_day.get(d) for d in dates if d<=asof][-21:]
        if len(window)<60 or any(v is None for v in window) or len(recent)!=21 or any(v is None for v in recent):
            continue
        valid+=1
        above+=float(window[-1]>statistics.mean(window))
        up20+=float(recent[-1]>recent[0])
        verified.append(name)
    total=len(sectors)
    coverage=round(100*valid/total)
    min_required=max(27,math.ceil(total*.85))
    score=half(5*(.65*above/valid+.35*up20/valid)) if valid>=min_required else None
    result={"id":"industry_trend","name":"行业趋势扩散","weight":.35,
            "score":score,"coverage":coverage if score is not None else 0,
            "sample":valid,"sector_count":total,"asof":date_fmt(asof) if score is not None else None,
            "provider":"tushare_sw2021","taxonomy":"申万2021一级行业",
            "days":60,"need_days":60,
            "above_ma60":round(above/valid,4) if valid else None,
            "positive20":round(up20/valid,4) if valid else None,
            "method":"申万2021一级行业收盘价高于MA60占比65%＋近20交易日上涨行业占比35%；没有跨来源拼接"}
    if score is None:
        result["issue"]=f"申万一级行业有效日线仅{valid}/{total}，未达到85%有效覆盖门槛"
    api.status["sw_daily"].update({"state":"ok" if score is not None else "partial",
        "verified_sectors":valid,"level1_count":total,"valid_pct":coverage,"asof":date_fmt(asof),
        "history_min":60})
    return result


def date_fmt(d):
    return d[:4]+"-"+d[4:6]+"-"+d[6:8] if len(str(d))==8 else str(d)


def adjusted_stock_breadth(api,history,asof,valid_dates,listed):
    """Compute 60-session adjusted MA breadth in memory; never publish raw factors."""
    dates=history.get("stock_dates") or []
    if len(dates)<80 or dates[-1].replace("-","")!=asof:
        raise SafeAPIError("股价历史不足80交易日或与Tushare最新交易日不一致")
    ds=dates[-80:]
    if any(d.replace("-","") not in valid_dates for d in ds):
        raise SafeAPIError("全A历史和交易日历不一致")
    stock_data=history.get("stock_prices") or {}
    if not stock_data:
        raise SafeAPIError("未发现原始股票日线历史")
    series={code:[None]*len(ds) for code,arr in stock_data.items()
            if len(arr)>=80 and code+".SZ" in listed or len(arr)>=80 and code+".SH" in listed}
    latest_factors={}
    api.status["adj_factor"].update({"expected_days":len(ds),"completed_days":0})
    # Request a whole-market factor cross-section per trading date.
    for i,d in enumerate(ds):
        rows=api.ask("adj_factor",{"trade_date":d.replace("-","")},
                     "ts_code,trade_date,adj_factor")
        factors={}
        for row in rows:
            code=str(row.get("ts_code") or "")
            f=num(row.get("adj_factor"))
            if len(code)==9 and code.endswith((".SZ",".SH")) and f is not None and f>0:
                factors[code[:6]]=f
        if len(factors)<3500:
            raise SafeAPIError(f"adj_factor历史截面不足3500只：{d}, 有效{len(factors)}")
        latest_factors=factors
        for code,arr in series.items():
            raw=stock_data[code][-80+i]
            factor=factors.get(code)
            price=num(raw)
            if factor is not None and price is not None and price>0:
                arr[i]=round(price*factor,5)
        api.status["adj_factor"]["completed_days"]=i+1
    verified=0
    above=0
    past=0
    past_n=0
    for arr in series.values():
        if len(arr)<80 or any(v is None for v in arr[-60:]):
            continue
        verified+=1
        above+=float(arr[-1]>statistics.mean(arr[-60:]))
        if all(v is not None for v in arr[-80:-20]):
            past_n+=1
            past+=float(arr[-21]>statistics.mean(arr[-80:-20]))
    latest_count=sum(1 for code,arr in series.items() if arr[-1] is not None)
    if verified<max(2800,latest_count*.75) or past_n<verified*.75:
        raise SafeAPIError(f"复权MA60可用股票不足: {verified}，对照样本 {latest_count}")
    ratio=above/verified
    past_ratio=past/past_n
    improved=max(0,min(1,.5+(ratio-past_ratio)*2))
    score=half(5*(.70*ratio+.30*improved))
    api.status["adj_factor"].update({"state":"ok","sample_current":latest_count,
           "verified_ma60":verified,"last_day_factors":len(latest_factors),"first":ds[0],"last":ds[-1]})
    return {"id":"stock_trend","name":"个股趋势广度","weight":.40,
            "score":score,"coverage":100,"asof":date_fmt(asof),"sample":verified,
            "days":len(ds),"need_days":80,
            "above_ma60":round(ratio,4),"change_20d":round(ratio-past_ratio,4),
            "adjustment":"Tushare adj_factor 股价×复权因子（计算时只比较同一股票）",
            "method":"沪深A股复权价高于MA60占比70%＋该比例近20个交易日变化30%；本次计算使用80个交易日的复权因子，不公开原始因子"}


def index_scores(api,dates,asof):
    earliest=(datetime.strptime(asof,"%Y%m%d").date()-timedelta(days=470)).strftime("%Y%m%d")
    results=[]
    errors=[]
    for code,name,weight in INDEX_WEIGHTS:
        try:
            rows=api.ask("index_daily",{"ts_code":code,"start_date":earliest,
                                       "end_date":asof},"ts_code,trade_date,close,amount")
        except SafeAPIError:
            errors.append(name+"指数日线接口失败")
            continue
        by_day={str(x.get("trade_date")):num(x.get("close")) for x in rows}
        series=[by_day[d] for d in sorted(by_day) if by_day[d] is not None and by_day[d]>0]
        if len(series)<260 or asof not in by_day:
            errors.append(name+"历史不足260交易日或最新行情未发布")
            continue
        px=series[-1]; ma20=statistics.mean(series[-20:]); ma60=statistics.mean(series[-60:])
        ma250=statistics.mean(series[-250:])
        previous20=statistics.mean(series[-25:-5])
        score=float(sum((px>=ma20,px>=ma60,px>=ma250,ma20>previous20,px>series[-21])))
        results.append({"code":code,"name":name,"weight":weight,"score":score,
                        "close":round(px,2),"ma20":round(ma20,2),"ma60":round(ma60,2),
                        "ma250":round(ma250,2),"ma20_slope_5":round(ma20-previous20,2),
                        "asof":date_fmt(asof)})
    coverage=sum(x["weight"] for x in results)
    val=half(sum(x["weight"]*x["score"] for x in results)/coverage) if coverage>=.75 and len(results)>=3 else None
    api.status["index_daily"].update({"state":"ok" if val is not None else "partial",
        "verified_indices":len(results),"coverage_pct":round(coverage*100),
        "asof":date_fmt(asof),"notes":errors})
    return {"score":val,"coverage":round(coverage*100) if val is not None else 0,
            "asof":date_fmt(asof) if val is not None else None,
            "indices":results,
            "method":"Tushare指数日线，沪深300/中证500/中证1000/中证2000权重30/25/25/20；收盘价与MA20/60/250、MA20斜率、20日涨幅",
            "issues":errors}


def trading_activity(api,asof):
    from update_market_signals import turnover_activity
    earliest=(datetime.strptime(asof,"%Y%m%d").date()-timedelta(days=150)).strftime("%Y%m%d")
    paths=[]
    for code in ("000001.SH","399107.SZ"):
        rows=api.ask("index_daily",{"ts_code":code,"start_date":earliest,"end_date":asof},
                         "trade_date,amount,ts_code")
        data={str(x.get("trade_date")):num(x.get("amount")) for x in rows}
        data={date_fmt(d):amount*1000 for d,amount in data.items()
              if amount is not None and amount>0}
        paths.append(data)
    try:
        result=turnover_activity(paths,"Tushare 上证综合指数＋深证A指成交额（单位校验：千元×1000）",
                                1.0,[])
    except (ValueError,ZeroDivisionError) as e:
        raise SafeAPIError("index_daily 两市成交额无法计算交易活跃度") from None
    if result.get("asof")!=date_fmt(asof):
        raise SafeAPIError("成交额日期未对齐到最近交易日")
    result["provider"]="tushare_index_daily"
    return result


def daily_basic_check(api,asof):
    rows=api.ask("daily_basic",{"trade_date":asof},
                 "ts_code,trade_date,turnover_rate,volume_ratio")
    turnover=[num(x.get("turnover_rate")) for x in rows]
    turnover=[v for v in turnover if v is not None and 0<=v<=100]
    if len(rows)<3500:
        raise SafeAPIError(f"daily_basic当天样本不足3500: {len(rows)}")
    api.status["daily_basic"].update({"state":"ok","asof":date_fmt(asof),
       "valid_turnover":len(turnover),"avg_turnover_pct":round(statistics.mean(turnover),2) if turnover else None})
    return {"market_mean_turnover_pct":round(statistics.mean(turnover),2) if turnover else None,
            "sample":len(turnover)}


def daily_crosscheck(api,asof,listed):
    rows=api.ask("daily",{"trade_date":asof},
                 "ts_code,trade_date,close,pct_chg")
    sample=sum(1 for r in rows if str(r.get("ts_code")) in listed and num(r.get("close")) is not None)
    if sample<3500:
        raise SafeAPIError(f"daily当日样本不足3500: {sample}")
    api.status["daily"].update({"state":"ok","asof":date_fmt(asof),"sample":sample})
    return sample


def integrate_scores(saved,industry,stocks,technical,liquidity,participation,asof,api):
    components=[stocks,industry,participation]
    score,coverage=bm.combine(components)
    breadth=dict(saved.get("breadth") or {})
    breadth.update({"score":score,"coverage":coverage,
        "asof":date_fmt(asof) if score is not None else None,
        "components":components,
        "source_taxonomy":"申万2021一级行业","history_source":"Tushare Pro（个人权限，计算后仅公开汇总指标）",
        "method":"复权个股MA60趋势40%＋申万2021一级行业趋势35%＋近5日涨跌家数25%；真实有效覆盖率折算",
        "issues":[c.get("issue") for c in components if c.get("issue")]})
    saved["technical"]=technical
    saved["breadth"]=breadth
    saved["liquidity"]=liquidity
    saved["version"]=3
    saved["source"]="Tushare Pro 5000积分（沪深A股、宽基指数、申万2021一级行业）｜原始数据不公开"
    saved["updated_at"]=datetime.now(BEIJING).isoformat(timespec="seconds")
    saved["provider_health_file"]="data/tushare_5000_health.json"
    return saved


def run():
    token=os.environ.get("TUSHARE_TOKEN","").strip()
    api=Tushare(token)
    history,issues=bm.read_history(BASE/"breadth_history.json")
    if issues:raise SafeAPIError("已有全A历史JSON无法读取，停止覆盖")
    ds=history.get("stock_dates") or []
    if len(ds)<80:raise SafeAPIError("已保存的Tushare日线历史不足80个有效交易日")
    asof=ds[-1].replace("-","")
    day=datetime.strptime(asof,"%Y%m%d").date()
    if datetime.now(BEIJING).date()-day>timedelta(days=8):
        raise SafeAPIError("股价历史已过期超过8日，请先修复每日Tushare日线增量")
    health={"version":1,"mode":"5000_point_market_data","created_at":datetime.now(BEIJING).isoformat(timespec="seconds"),
        "asof":date_fmt(asof),"access_verified":False,"source":"Tushare Pro",
        "raw_paid_data_committed":False,"api":api.status,"warnings":[]}
    saved=load_json(BASE/"market_signals.json",{})
    try:
        valid_dates=latest_dates(api,day)
        if asof not in valid_dates:
            raise SafeAPIError("全A归档最新日期不是交易日历有效交易日")
        listed=stock_universe(api)
        sectors=sw_level1(api)
        industry=sw_sector_breadth(api,sectors,valid_dates,asof)
        # Verify daily and fundamentals separately. Missing optional endpoints are reported.
        for fn in (lambda:daily_crosscheck(api,asof,listed),
                   lambda:daily_basic_check(api,asof)):
            try:fn()
            except SafeAPIError as exc:health["warnings"].append(str(exc))
        adjusted=adjusted_stock_breadth(api,history,asof,valid_dates,listed)
        try:
            technical=index_scores(api,valid_dates,asof)
        except SafeAPIError as exc:
            health["warnings"].append(str(exc))
            technical=saved.get("technical",{})
        try:
            liquidity=trading_activity(api,asof)
        except SafeAPIError as exc:
            health["warnings"].append(str(exc))
            liquidity=saved.get("liquidity",{})
        participation=bm.participation(history,date_fmt(asof))
        if participation.get("score") is None:
            raise SafeAPIError("最近5个有效交易日的参与度仍不可计算")
        if industry.get("score") is None:
            raise SafeAPIError("申万行业历史不足以完成趋势评分；保留旧指标")
        if technical.get("score") is None:
            health["warnings"].append("Tushare指数日线未覆盖足够宽基，保留此前技术分数")
            technical=saved.get("technical",technical)
        if liquidity.get("score") is None:
            health["warnings"].append("Tushare交易活跃度数据未齐全，保留此前流动性分数")
            liquidity=saved.get("liquidity",liquidity)
        health["access_verified"]=all(api.status[name].get("state")=="ok" for name in API_LIST)
        health["scoring_ready"]=True
        health["breadth_coverage"]=bm.combine([adjusted,industry,participation])[1]
        if not health["access_verified"]:
            health["warnings"].append("部分可选接口或指数子项未达完整标准，请查看每项状态")
        health["api"]=api.status
        health["api_calls"]=api.counts
        health["market_date"]=date_fmt(asof)
        health["latest_sector_count"]=industry["sample"]
        health["adjusted_stock_count"]=adjusted["sample"]
        atomic(BASE/"market_signals.json",
               integrate_scores(saved,industry,adjusted,technical,liquidity,participation,asof,api))
    except SafeAPIError as exc:
        health["warnings"].append(str(exc))
        health["api"]=api.status
        health["api_calls"]=api.counts
        health["access_verified"]=False
        atomic(BASE/"tushare_5000_health.json",health)
        print("FAIL: Tushare5000 integrity or permission check: "+str(exc),flush=True)
        return 1
    atomic(BASE/"tushare_5000_health.json",health)
    print(("PASS: all eight APIs verified. " if health["access_verified"] else "PARTIAL: inspect API health. ")+
          "Tushare5000 aggregate scores updated; "
          f"SW industry {industry['sample']}/{industry['sector_count']}, "
          f"adjusted stocks {adjusted['sample']}; asof {date_fmt(asof)}.",flush=True)
    return 0 if health["access_verified"] else 2


if __name__=="__main__":
    raise SystemExit(run())
