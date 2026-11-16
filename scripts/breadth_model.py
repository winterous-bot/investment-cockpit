"""Industry vendor fallbacks and rolling A-share market-breadth model.

Source taxonomy is explicit. Sina industry classification must NEVER be mixed
with Eastmoney boards for moving averages. No portfolio data is accessed.
"""
from __future__ import annotations

import json
import math
import statistics
import time
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path

MIN_STOCK_SAMPLE = 3500
MAX_STOCK_DAYS = 86
MAX_PARTICIPATION_DAYS = 15
MAX_INDUSTRY_DAYS = 67
BREADTH_WEIGHTS = {"stock_trend": 0.40, "industry_trend": 0.35, "participation": 0.25}

def half(value):
    return max(0., min(5., round(float(value)*2)/2))

def _number(value):
    try:
        v = float(value)
        return v if math.isfinite(v) else None
    except (TypeError, ValueError):
        return None

def _request_text(url):
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_5) AppleWebKit/537.36 Chrome/126 Safari/537.36",
        "Referer": "https://finance.sina.com.cn/",
        "Accept": "*/*",
        "Accept-Language": "zh-CN,zh;q=0.9",
    }
    last = None
    for attempt in range(2):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=12) as reply:
                return reply.read(250000).decode("utf-8-sig", errors="replace")
        except (OSError, TimeoutError, urllib.error.URLError, ValueError) as exc:
            last = exc
            if attempt == 0:
                time.sleep(0.7)
    raise RuntimeError(f"Sina provider unavailable: {last}")

def parse_sina_industries(body):
    """Parse 13-field Sina sector strings; field 5 is daily change percent."""
    lo, hi = body.find("{"), body.rfind("}")
    if lo < 0 or hi < lo:
        raise ValueError("Sina industry payload has no JSON object")
    payload = json.loads(body[lo:hi+1])
    if not isinstance(payload, dict):
        raise ValueError("Sina industry payload is not a mapping")
    result = {}
    for key, raw in payload.items():
        if not isinstance(raw, str) or not key.startswith("new_"):
            continue
        cells = raw.split(",")
        if len(cells) < 7:
            continue
        sector_name = cells[1].strip()
        if sector_name in {"次新股", "其它行业", "其他行业", "开发区", "综合行业"}:
            continue
        count, pct = _number(cells[2]), _number(cells[5])
        if not sector_name or count is None or count < 5 or pct is None or abs(pct) > 35:
            continue
        result["sina:"+key] = {"name": sector_name, "change_pct": round(pct, 4)}
    if not 30 <= len(result) <= 140:
        raise ValueError(f"Sina industry list has only {len(result)} valid sectors")
    return result

def fetch_sina_industries(request_text=_request_text):
    url = "https://vip.stock.finance.sina.com.cn/q/view/newSinaHy.php"
    return {"provider": "sina", "taxonomy": "新浪行业分类（非申万）",
            "sectors": parse_sina_industries(request_text(url)),
            "url": url}

def fetch_em_industries(download_json, entries):
    """Same Eastmoney taxonomy across alternate gateway hosts."""
    errors = []
    params = {"pn": 1, "pz": 45, "po": 1, "np": 1,
              "fltt": 2, "invt": 2, "fid": "f3",
              "fs": "m:90+t:2+f:!50", "fields": "f12,f14,f3"}
    for host in ("https://push2.eastmoney.com", "https://17.push2.eastmoney.com",
                 "https://29.push2.eastmoney.com"):
        url = host + "/api/qt/clist/get"
        try:
            first = download_json(url, params, retries=1)
            total = int((first.get("data") or {}).get("total") or 0)
            if not 30 <= total <= 250:
                raise ValueError(f"invalid industry count {total}")
            result = {}
            for page in range(1, math.ceil(total/45)+1):
                block = first if page == 1 else download_json(url, {**params,"pn":page}, retries=1)
                for row in entries(block):
                    key = str(row.get("f12") or "")
                    value = _number(row.get("f3"))
                    if key.startswith("BK") and value is not None and abs(value)<=35:
                        result["em:"+key] = {"name":str(row.get("f14") or key)[:60],
                                              "change_pct":round(value, 4)}
            if len(result) < max(30, total*.80):
                raise ValueError(f"only {len(result)}/{total} industry rows")
            return {"provider":"eastmoney","taxonomy":"东方财富行业板块",
                    "sectors":result, "url":url}
        except Exception as e:
            errors.append(host+": "+str(e))
    raise RuntimeError("; ".join(errors))

def get_industries(download_json, entries, get_sina=fetch_sina_industries):
    errors = []
    try:
        result = fetch_em_industries(download_json, entries)
        result["issues"] = []
        return result
    except Exception as exc:
        errors.append("东方财富行业列表失败："+str(exc))
    try:
        result = get_sina()
        result["issues"] = errors
        return result
    except Exception as exc:
        errors.append("新浪独立行业源失败："+str(exc))
    return {"provider":None, "taxonomy":None, "sectors":{}, "issues":errors}

def fresh_history():
    return {"version":1,"stock_dates":[],"stock_prices":{},
            "participation":[],"industries":{}}

def read_history(path:Path):
    if not path.exists():
        return fresh_history(), []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if raw.get("version")!=1 or not isinstance(raw.get("stock_prices"),dict):
            raise ValueError("history schema mismatch")
        return raw, []
    except (ValueError, TypeError, OSError) as e:
        return fresh_history(), ["历史数据格式异常，未计入旧数据: "+str(e)]

def _valid_trade_date(asof):
    try:
        x = date.fromisoformat(str(asof)[:10])
        if x.year < 2020 or x > date.today():
            return False
        return True
    except (TypeError, ValueError):
        return False

def _same_day(old, asof):
    return bool(old and old[-1] == asof)

def update_participation(history, asof, ratio, sample, source):
    if not _valid_trade_date(asof) or ratio is None or sample < 3500:
        return False
    participation = history.setdefault("participation",[])
    row = {"date":asof,"ratio":round(float(ratio),5),"sample":int(sample),"source":source}
    if participation and participation[-1]["date"] > asof:
        return False
    if participation and participation[-1]["date"] == asof:
        participation[-1] = row
    else:
        participation.append(row)
    history["participation"] = participation[-MAX_PARTICIPATION_DAYS:]
    return True

def update_stocks(history, asof, quotes, coverage):
    """Only FULL market closes can advance the 60-session stock MA history."""
    if coverage != "full" or len(quotes) < MIN_STOCK_SAMPLE or not _valid_trade_date(asof):
        return False
    prices = {symbol: _number(q.get("price")) for symbol,q in quotes.items()
              if isinstance(q,dict) and isinstance(symbol,str) and len(symbol)==6}
    prices = {k:round(v,3) for k,v in prices.items() if v is not None and v>0}
    if len(prices)<MIN_STOCK_SAMPLE:
        return False
    dates = history.setdefault("stock_dates",[])
    data = history.setdefault("stock_prices",{})
    if dates and dates[-1] > asof:
        return False
    same = dates and dates[-1]==asof
    if not same:
        dates.append(asof)
        for arr in data.values():
            arr.append(None)
    n = len(dates)
    for symbol, price in prices.items():
        if symbol not in data:
            data[symbol] = [None]*(n-1)+[price]
        else:
            data[symbol][-1] = price
    if n>MAX_STOCK_DAYS:
        extra=n-MAX_STOCK_DAYS
        history["stock_dates"]=dates[extra:]
        data={key:arr[extra:] for key,arr in data.items()}
    history["stock_prices"]={key:arr for key,arr in data.items()
                             if any(x is not None for x in arr[-60:])}
    return True

def update_industries(history, asof, snapshot):
    if not _valid_trade_date(asof) or not snapshot.get("provider") or not snapshot.get("sectors"):
        return False
    vendor = snapshot["provider"]
    rec = history.setdefault("industries",{}).setdefault(vendor,{"dates":[],"returns":{}})
    dates, returns = rec["dates"],rec["returns"]
    if dates and dates[-1] > asof:
        return False
    same=bool(dates and dates[-1]==asof)
    if not same:
        dates.append(asof)
        for arr in returns.values():
            arr.append(None)
    n=len(dates)
    for key, sector in snapshot["sectors"].items():
        value=_number(sector.get("change_pct"))
        if value is None or abs(value)>35:
            continue
        if key not in returns:
            returns[key]=[None]*(n-1)+[value]
        else:
            returns[key][-1]=value
    if n>MAX_INDUSTRY_DAYS:
        extra=n-MAX_INDUSTRY_DAYS
        rec["dates"]=dates[extra:]
        returns={key:values[extra:] for key,values in returns.items()}
    rec["returns"]={key:values for key,values in returns.items()
                    if any(v is not None for v in values[-60:])}
    return True

def _above_ma_ratio(values, period=60):
    if len(values)<period or any(x is None for x in values[-period:]):
        return None
    return values[-1] > statistics.mean(values[-period:])

def stock_trend(history, today, current_total):
    dates=history.get("stock_dates") or []
    data=history.get("stock_prices") or {}
    count=len(dates)
    if count<60 or dates[-1]!=today or current_total<MIN_STOCK_SAMPLE:
        return {"id":"stock_trend","name":"个股趋势广度","weight":.40,"score":None,"coverage":0,
                "sample":0,"days":count,"need_days":60,
                "issue":"全A完整收盘价尚未累计60个交易日；不使用少数股票替代"}
    today_good=0; positive=0; past_good=0; past_pos=0
    for symbol, values in data.items():
        if len(values)!=count:
            continue
        b=_above_ma_ratio(values)
        if b is not None:
            today_good+=1
            positive+=b
        if count>=80:
            historic=_above_ma_ratio(values[:-20])
            if historic is not None:
                past_good+=1
                past_pos+=historic
    if today_good < max(2800,current_total*.75):
        return {"id":"stock_trend","name":"个股趋势广度","weight":.40,
                "score":None,"coverage":0,"sample":today_good,"days":count,
                "need_days":60,"issue":"具备60日均线的个股覆盖不足"}
    ratio=positive/today_good
    score=5*ratio
    subcoverage=.5
    prior_ratio=None
    if count>=80 and past_good>=today_good*.75:
        prior_ratio=past_pos/past_good
        improvement=max(0,min(1, .5+(ratio-prior_ratio)*2))
        score=5*(.7*ratio+.3*improvement)
        subcoverage=1.
    return {"id":"stock_trend","name":"个股趋势广度","weight":.40,
            "score":half(score),"coverage":round(subcoverage*100),"sample":today_good,
            "asof":today,"days":count,"need_days":80 if subcoverage<1 else 80,
            "above_ma60":round(ratio,4),
            "change_20d":round(ratio-prior_ratio,4) if prior_ratio is not None else None,
            "method":"高于MA60的个股比例（70%）＋该比例20日变化（30%）；历史不足80天时仅计算趋势比例，覆盖折减为50%"}

def _synthetic_prices(changes):
    result=[]
    last=100.
    for change in changes:
        if change is None or abs(change)>35:
            return None
        last*=1+change/100
        result.append(last)
    return result

def industry_trend(history, today, snapshot):
    provider=snapshot.get("provider")
    rec=(history.get("industries") or {}).get(provider) or {}
    dates=rec.get("dates") or []
    sectors=snapshot.get("sectors") or {}
    if not provider or not sectors or len(dates)<60 or dates[-1]!=today:
        return {"id":"industry_trend","name":"行业趋势扩散","weight":.35,
                "score":None,"coverage":0,"sample":0,"days":len(dates),
                "need_days":60,"provider":provider or "暂无",
                "issue":"当前行业分类的日收益历史不足60个交易日，或无当日有效行业行情"}
    good=0;above=0;up20=0
    for key in sectors:
        changes=(rec.get("returns") or {}).get(key) or []
        if len(changes)!=len(dates):
            continue
        closes=_synthetic_prices(changes[-60:])
        if closes is None:
            continue
        good+=1
        above+=closes[-1] > statistics.mean(closes)
        up20+=closes[-1]>closes[-21]
    if good<max(25,len(sectors)*.75):
        return {"id":"industry_trend","name":"行业趋势扩散","weight":.35,
                "score":None,"coverage":0,"sample":good,"days":len(dates),
                "need_days":60,"provider":provider,"issue":"具有完整行业历史的板块占比不足75%"}
    ratio=above/good
    positive20=up20/good
    return {"id":"industry_trend","name":"行业趋势扩散","weight":.35,
            "score":half(5*(.65*ratio+.35*positive20)),"coverage":100,
            "sample":good,"asof":today,"days":len(dates),"need_days":60,
            "provider":provider,"taxonomy":snapshot["taxonomy"],
            "above_ma60":round(ratio,4),"positive20":round(positive20,4),
            "method":"同一供应商行业分类（不可跨源拼接）：板块构造连续收益指数高于MA60比例65%＋近20日上涨行业比例35%"}

def participation(history, today):
    items=history.get("participation") or []
    valid=[x for x in items if x.get("ratio") is not None]
    if len(valid)<5 or valid[-1]["date"]!=today:
        return {"id":"participation","name":"短期市场参与度","weight":.25,
                "score":None,"coverage":0,"days":len(valid),"need_days":5,
                "issue":"尚未累计最近5个有效交易日的上涨家数"}
    latest=valid[-5:]
    if (date.fromisoformat(latest[-1]["date"])-date.fromisoformat(latest[0]["date"])).days > 16:
        return {"id":"participation","name":"短期市场参与度","weight":.25,
                "score":None,"coverage":0,"days":len(valid),"need_days":5,
                "issue":"最近5条记录跨越过长时间，无法代表连续交易日"}
    ratio=statistics.mean(x["ratio"] for x in latest)
    return {"id":"participation","name":"短期市场参与度","weight":.25,
            "score":half(5*ratio),"coverage":100,"sample":min(x["sample"] for x in latest),
            "asof":today,"days":len(valid),"need_days":5,
            "avg_rising_ratio":round(ratio,4),
            "method":"最近5个有效交易日沪深A股上涨家数比例的平均值（不含北交所）"}

def combine(components):
    covered=sum(c["weight"]*(c["coverage"]/100) for c in components
                if c.get("score") is not None)
    coverage=round(100*covered)
    score=half(sum(c["score"]*c["weight"]*c["coverage"]/100 for c in components
                   if c.get("score") is not None)/covered) if covered else None
    return score,coverage
