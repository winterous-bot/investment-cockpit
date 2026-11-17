#!/usr/bin/env python3
"""Public A-share market-stage indicators for the local-only investment cockpit.

Inputs are public Eastmoney web endpoints, not an official/guaranteed data API.
Never read or upload users' portfolio data. Missing evidence stays missing.
"""
from __future__ import annotations
import json
import math
import os
import statistics
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from update_quotes import download_json, entries, finite_float
import breadth_model as bm

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "data" / "market_signals.json"
BEIJING = ZoneInfo("Asia/Shanghai")
KLINE = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
_KLINE_CACHE = {}
INDICES = (
    ("000300", "沪深300", "1.000300", 0.30),
    ("000905", "中证500", "1.000905", 0.25),
    ("000852", "中证1000", "1.000852", 0.25),
    ("932000", "中证2000", "2.932000", 0.20),
)


def half(value):
    return max(0.0, min(5.0, round(float(value) * 2) / 2))


def kline(secid, limit=285):
    cached = _KLINE_CACHE.get(secid)
    if cached and len(cached) >= limit:
        return cached[-limit:]
    response = download_json(KLINE, {
        "secid": secid, "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57",
        "klt": 101, "fqt": 0, "end": 20500101, "lmt": limit,
    })
    rows = (response.get("data") or {}).get("klines") or []
    valid = []
    for line in rows:
        x = str(line).split(",")
        if len(x) < 7:
            continue
        close, amount = finite_float(x[2]), finite_float(x[6])
        if close and close > 0:
            valid.append({"date": x[0], "close": close, "amount": amount})
    _KLINE_CACHE[secid] = valid
    return valid


def index_score(rows):
    """Five auditable bullish tests, each worth 1, mapped to 0-5."""
    prices = [r["close"] for r in rows]
    if len(prices) < 260:
        raise ValueError("指数日线不足260条")
    close = prices[-1]
    ma20 = statistics.mean(prices[-20:])
    ma60 = statistics.mean(prices[-60:])
    ma250 = statistics.mean(prices[-250:])
    prior20 = statistics.mean(prices[-25:-5])
    score = sum((
        close >= ma20,
        close >= ma60,
        close >= ma250,
        ma20 > prior20,
        close > prices[-21],
    ))
    return {"score": float(score), "close": round(close, 2),
            "ma20": round(ma20, 2), "ma60": round(ma60, 2),
            "ma250": round(ma250, 2), "ma20_slope_5": round(ma20 - prior20, 2),
            "return20_pct": round((close/prices[-21]-1)*100, 2),
            "asof": rows[-1]["date"]}


def technical():
    items, failures = [], []
    for code, name, secid, weight in INDICES:
        try:
            x = index_score(kline(secid))
            items.append({"code": code, "name": name, "weight": weight, **x})
        except Exception as exc:
            failures.append(f"{name}: {exc}")
    coverage = sum(item["weight"] for item in items)
    if coverage < .75 or len(items) < 3:
        return {"score": None, "coverage": round(coverage * 100), "indices": items,
                "issues": failures + ["宽基覆盖不足75%，不自动评分"]}
    dates = [datetime.fromisoformat(item["asof"]) for item in items]
    if (max(dates) - min(dates)).days > 2:
        return {"score": None, "coverage": round(coverage * 100),
                "indices": items, "issues": failures + ["各宽基指数交易日期不一致"]}
    score = half(sum(item["score"]*item["weight"] for item in items) / coverage)
    return {"score": score, "coverage": round(coverage * 100),
            "indices": items, "asof": max(item["asof"] for item in items),
            "method": "4个互补宽基指数，五项规则：收盘站上MA20/60/250、MA20五日抬升、20日收益为正",
            "issues": failures}


def industry_breadth():
    """Complete Eastmoney industry board list, not a hand-picked top-30."""
    url = "https://push2.eastmoney.com/api/qt/clist/get"
    params = {"pn": 1, "pz": 35, "po": 1, "np": 1,
              "fltt": 2, "invt": 2, "fid": "f3",
              "fs": "m:90+t:2+f:!50", "fields": "f12,f14,f3"}
    first = download_json(url, params)
    total = int((first.get("data") or {}).get("total") or 0)
    if total < 30 or total > 2000:
        raise ValueError(f"行业板块数量异常({total})")
    seen = {}
    for page in range(1, math.ceil(total/35)+1):
        obj = first if page == 1 else download_json(url, {**params, "pn": page})
        for entry in entries(obj):
            code = str(entry.get("f12") or "")
            change = finite_float(entry.get("f3"))
            if code and change is not None:
                seen[code] = change
    if len(seen) < total * .85:
        raise ValueError(f"行业数据覆盖不足: {len(seen)}/{total}")
    return {"rising": sum(v > 0 for v in seen.values()), "sample": len(seen)}


def exchange_index_breadth():
    """Fallback to SSE composite + SZSE A-share index index constituent counts.

    It excludes Beijing and should be labeled an exchange-index proxy, not 'all A'.
    """
    obj = download_json("https://push2.eastmoney.com/api/qt/ulist.np/get", {
        "fltt": 2, "invt": 2,
        "secids": "1.000001,0.399107",
        "fields": "f12,f14,f104,f105,f106,f124",
    })
    rows = entries(obj)
    matched = {str(x.get("f12")): x for x in rows}
    up, down, sample = 0, 0, 0
    for code in ("000001", "399107"):
        x = matched.get(code)
        if not x:
            raise ValueError("上证综指或深证A指缺失")
        pos, neg = finite_float(x.get("f104")), finite_float(x.get("f105"))
        flat = finite_float(x.get("f106"))
        if pos is None or neg is None or pos < 0 or neg < 0:
            raise ValueError(f"{code}涨跌家数字段缺失")
        flat = max(0, flat or 0)
        subtotal = pos + neg + flat
        if subtotal < 1000:
            raise ValueError(f"{code}成分涨跌家数不完整({subtotal})")
        up += pos
        down += neg
        sample += subtotal
    if sample < 3500:
        raise ValueError(f"沪深市场样本量不足({sample})")
    return {"rising": int(up), "falling": int(down), "sample": int(sample)}


def breadth():
    """Three subdimensions: stock MA60 trend 40%, sector trend 35%, five-day breadth 25%."""
    history_path = ROOT / "data" / "breadth_history.json"
    hist, issues = bm.read_history(history_path)
    try:
        q = json.loads((ROOT/"data"/"quotes.json").read_text(encoding="utf-8"))
    except (OSError,ValueError) as exc:
        q = {}
        issues.append("A股收盘快照读取失败："+str(exc))
    # The exchange index's actual trade_at is authoritative; a generated_at may be a holiday.
    quote_trade_date = str((q.get("index") or {}).get("trade_at") or "")[:10]
    historic_trade_date = (hist.get("stock_dates") or [None])[-1]
    # The independent Tushare archive is authoritative when the web quote index
    # is unavailable/stale. Never turn a snapshot creation time into a trading day.
    market_date = max(filter(None,[quote_trade_date,historic_trade_date]),default="")
    if not bm._valid_trade_date(market_date):
        issues.append("没有可信的最近交易日，历史数据暂停追加")
    snapshot = bm.get_industries(download_json, entries)
    issues.extend(snapshot.get("issues", []))
    stats = None
    try:
        stats = exchange_index_breadth()
    except Exception as exc:
        issues.append("沪深A指数涨跌家数暂不可用："+str(exc))
    if bm._valid_trade_date(market_date):
        # Do not append raw public webpage quotes onto Tushare history when its
        # index timestamp is missing or out of sync with the saved trading day.
        if stats is not None and quote_trade_date==market_date and market_date not in {x.get("date") for x in hist.get("participation", [])}:
            bm.update_participation(hist, market_date, stats["rising"]/stats["sample"],
                                    stats["sample"], "沪深A指数涨跌家数（不含北交所）")
        if q.get("coverage")=="full" and quote_trade_date==market_date:
            bm.update_stocks(hist, market_date, q.get("quotes") or {}, "full")
        elif (hist.get("stock_dates") or [None])[-1]!=market_date:
            issues.append("本日全市场行情源未验证，等待Tushare增量日线补充")
        if quote_trade_date==market_date and snapshot.get("sectors"):
            if not bm.update_industries(hist, market_date, snapshot):
                issues.append("行业行情未能写入相同交易日的历史")
        elif snapshot.get("sectors"):
            issues.append("行业数据缺少与当前交易日匹配的时间戳，本次不追加历史")
    # Only store public market aggregates/prices; no personal holdings.
    history_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = history_path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(hist,ensure_ascii=False,separators=(",",":")),encoding="utf-8")
    os.replace(tmp,history_path)

    current_stock_count = sum(1 for prices in (hist.get("stock_prices") or {}).values() if prices and prices[-1] is not None) if (hist.get("stock_dates") or [None])[-1] == market_date else 0
    components = [
        bm.stock_trend(hist, market_date, current_stock_count),
        bm.industry_trend(hist, market_date, snapshot),
        bm.participation(hist, market_date),
    ]
    issues.extend([c["issue"] for c in components if c.get("issue")])
    score,coverage = bm.combine(components)
    spot = {}
    if stats is not None:
        spot["rising_stock_ratio"] = round(stats["rising"]/stats["sample"], 4)
        spot["stock_count"] = stats["sample"]
        spot["stock_source"] = "沪深A指数（未含北交所）"
    if snapshot.get("sectors"):
        prices=[v["change_pct"] for v in snapshot["sectors"].values()]
        spot["rising_industry_ratio"] = round(sum(p>0 for p in prices)/len(prices),4)
        spot["industry_count"] = len(prices)
        spot["industry_source"] = snapshot.get("taxonomy")
        spot["industry_url"] = snapshot.get("url")
    return {
        "score":score,"coverage":coverage,
        "asof":market_date if score is not None else None,
        "components":components,
        "spot":spot,
        "issues":issues,
        "source_taxonomy":snapshot.get("taxonomy"),
        "history_days":{"stock":len(hist.get("stock_dates") or []),
                        "participation":len(hist.get("participation") or []),
                        "industries":len(((hist.get("industries") or {}).get(snapshot.get("provider")) or {}).get("dates") or [])},
        "method":"个股MA60趋势40%＋同源行业趋势35%＋近5交易日上涨家数参与度25%；仅对有效历史计算，缺失权重不计入覆盖率"
    }


def turnover_activity(series, label, coverage, issues):
    """Score relative trading activity from >=65 complete daily turnover observations."""
    dates = sorted(set.intersection(*[set(s) for s in series]))
    values = [sum(s[d] for s in series) for d in dates]
    if len(values) < 65:
        raise ValueError("交集成交金额历史不足65个交易日")
    recent20 = statistics.mean(values[-20:])
    prev20 = statistics.mean(values[-40:-20])
    ratio = recent20 / prev20 if prev20 > 0 else 0
    rank = sum(x <= values[-1] for x in values[-60:])/60
    trend = max(0, min(1, (ratio-0.70)/0.60))
    return {"score": half(5*(.55*rank + .45*trend)),
            "coverage": round(coverage*100), "asof": dates[-1],
            "turnover_today_yuan": round(values[-1], 0),
            "turnover20_yuan": round(recent20, 0),
            "turnover20_vs_previous20": round(ratio, 3),
            "turnover60_percentile": round(rank, 3),
            "method": label + "：近60日成交额分位55% + 20日成交变化45%；只是交易活跃度代理，不代表ETF/融资净流入",
            "issues": issues}


def amounts(rows):
    return {x["date"]: x["amount"] for x in rows
            if x["amount"] is not None and x["amount"] > 0}


def liquidity():
    """Prefer both entire exchanges; fallback to disjoint CSI size-index samples."""
    issues = []
    try:
        sh = kline("1.000001", 90)
        try:
            sz = kline("0.399107", 90)  # SZSE A-share index: all SZ A stocks
            if len(sz) < 65: raise ValueError("深证A指历史不足65条")
        except Exception:
            sz = kline("0.399106", 90)  # SZSE composite backup, includes B shares
        return turnover_activity([amounts(sh), amounts(sz)],
                    "上证综指 + 深证A指（必要时深证综指）成交额",
                    1.0, [])
    except Exception as exc:
        issues.append("沪深交易所成交额不可用，改用宽基样本代理: "+str(exc))
    series, weight = [], 0.
    for code, name, secid, w in INDICES:
        try:
            amounts_by_day = amounts(kline(secid))
            if len(amounts_by_day) < 65:
                raise ValueError("成交额历史不足65条")
            series.append(amounts_by_day)
            weight += w
        except Exception as exc:
            issues.append(name+"量能不可用: "+str(exc))
    if weight < .75 or len(series) < 3:
        return {"score": None, "coverage": round(weight*100),
                "issues": issues+["宽基成交样本覆盖不足75%"]}
    try:
        return turnover_activity(series,
                "沪深300/中证500/中证1000/中证2000等互补宽基样本成交额（非两市全量）",
                weight, issues)
    except Exception as exc:
        return {"score": None, "coverage": round(weight*100),
                "issues": issues+[str(exc)]}

def main():
    now = datetime.now(BEIJING).isoformat(timespec="seconds")
    blocks = {}
    for name, fn in (("technical", technical), ("breadth", breadth), ("liquidity", liquidity)):
        try:
            blocks[name] = fn()
        except Exception as exc:
            blocks[name] = {"score": None, "coverage": 0, "issues": [str(exc)]}
        print(f"{name}: {blocks[name].get('score')} /5, coverage {blocks[name].get('coverage')}%", flush=True)
    data = {"version": 3, "updated_at": now,
            "source": "公开网页行情（指数/量能：东方财富；行业：东方财富主源，新浪独立备用），来源均可能变化",
            "indices_policy": [{"code": code, "name": name, "weight": weight}
                               for code, name, _, weight in INDICES],
            **blocks}
    OUTPUT.parent.mkdir(exist_ok=True, parents=True)
    tmp = OUTPUT.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    os.replace(tmp, OUTPUT)
    print(f"Saved {OUTPUT} ({OUTPUT.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
