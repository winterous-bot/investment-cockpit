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

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "data" / "market_signals.json"
BEIJING = ZoneInfo("Asia/Shanghai")
KLINE = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
_KLINE_CACHE = {}
INDICES = (
    ("000300", "沪深300", "1.000300", 0.30),
    ("000905", "中证500", "1.000905", 0.25),
    ("000852", "中证1000", "1.000852", 0.25),
    ("932000", "中证2000", "1.932000", 0.20),
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
    components, issues = [], []
    try:
        q = json.loads((ROOT/"data"/"quotes.json").read_text(encoding="utf-8"))
        quotes = q.get("quotes") or {}
        if q.get("coverage") != "full" or len(quotes) < 3500:
            raise ValueError("A股全市场行情不完整")
        changes = [float(v["change"]) for v in quotes.values()
                   if isinstance(v, dict) and v.get("change") is not None]
        if len(changes) < 3500:
            raise ValueError("可统计涨跌股票不足3500只")
        ratio = sum(v > 0 for v in changes)/len(changes)
        components.append({"name": "全A上涨家数比例", "ratio": round(ratio, 4),
                           "sample": len(changes), "weight": .60})
    except Exception as exc:
        issues.append("全A个股行情不可用: "+str(exc))
        try:
            stats = exchange_index_breadth()
            components.append({"name": "沪深A指数上涨家数代理（不含北交所）",
                               "ratio": round(stats["rising"]/stats["sample"], 4),
                               "sample": stats["sample"], "weight": .60})
        except Exception as fallback_exc:
            issues.append("沪深市场指数广度代理: "+str(fallback_exc))
    try:
        stats = industry_breadth()
        ratio = stats["rising"]/stats["sample"]
        components.append({"name": "上涨行业板块比例", "ratio": round(ratio, 4),
                           "sample": stats["sample"], "weight": .40})
    except Exception as exc:
        issues.append("行业扩散: "+str(exc))
    coverage = sum(c["weight"] for c in components)
    if coverage < .40:
        return {"score": None, "coverage": round(coverage*100),
                "components": components, "issues": issues}
    score = half(5 * sum(c["ratio"]*c["weight"] for c in components) / coverage)
    # Advance/decline is a one-session snapshot, NOT a persistent trend.
    return {"score": score, "coverage": round(coverage*100),
            "components": components, "issues": issues,
            "asof": json.loads((ROOT/"data"/"quotes.json").read_text(encoding="utf-8")).get("updated_at"),
            "method": "可用项按原预设权重归一：全市场/沪深A指数上涨家数代理60% + 上涨行业板块比例40%（未获取的数据不计分）；仅为单日广度，须结合趋势复核"}


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
    data = {"version": 2, "updated_at": now,
            "source": "东方财富公开网页接口（非官方保证、接口可能变化）",
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
