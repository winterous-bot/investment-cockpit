#!/usr/bin/env python3
"""Generate a GitHub Pages A-share daily price snapshot.

Provider: Eastmoney public web quote endpoints (not a contracted or guaranteed API).
No holdings/watchlist/user private data are sent to the provider.
"""
from __future__ import annotations
import json
import http.client
import math
import os
import random
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "data" / "quotes.json"
BEIJING = ZoneInfo("Asia/Shanghai")
BASE = "https://push2.eastmoney.com/api/qt"
FIELDS = "f12,f13,f14,f2,f3,f4,f5,f6,f18,f124"
MARKETS = "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23"
FALLBACK = {
    "002475": "立讯精密", "002371": "北方华创", "300604": "长川科技",
    "600089": "特变电工", "600487": "亨通光电", "001248": "华润新能", "688333": "铂力特",
    "688111": "金山办公", "603039": "泛微网络",
}


def download_json(url: str, params: dict, retries: int = 3):
    query = urllib.parse.urlencode(params)
    full_url = f"{url}?{query}"
    last_error = None
    for attempt in range(retries):
        request = urllib.request.Request(
            full_url,
            headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/126.0 Safari/537.36",
                "Referer": "https://quote.eastmoney.com/",
                "Accept": "application/json,text/javascript,*/*;q=0.8",
                "Accept-Language": "zh-CN,zh;q=0.9",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=16) as response:
                raw = response.read(4_000_000).decode("utf-8-sig", "replace").strip()
            if raw.startswith("{"):
                return json.loads(raw)
            # Some web endpoints return a JSONP envelope.
            start, end = raw.find("{"), raw.rfind("}")
            if start >= 0 and end > start:
                return json.loads(raw[start:end+1])
            raise ValueError("Provider did not return JSON")
        except (ValueError, urllib.error.HTTPError, urllib.error.URLError, TimeoutError, json.JSONDecodeError, ConnectionError, OSError, http.client.HTTPException) as exc:
            last_error = exc
            time.sleep(0.8 * (attempt + 1))
    raise RuntimeError(f"Provider request failed after retries: {last_error}")


def finite_float(value):
    if value is None or value == "-" or value == "":
        return None
    try:
        value = float(value)
    except (ValueError, TypeError):
        return None
    return round(value, 4) if math.isfinite(value) else None


def entries(obj):
    if not isinstance(obj, dict) or not isinstance(obj.get("data"), dict):
        return []
    diff = obj["data"].get("diff")
    return list(diff.values()) if isinstance(diff, dict) else (diff if isinstance(diff, list) else [])


def as_iso(value):
    try:
        num = int(value)
        if 1577836800 <= num <= 2082758400:
            return datetime.fromtimestamp(num, tz=BEIJING).isoformat(timespec="seconds")
    except (ValueError, TypeError, OverflowError):
        pass
    return None


def quote_row(entry):
    if not isinstance(entry, dict):
        return None
    symbol = str(entry.get("f12", "")).strip()
    if len(symbol) != 6 or not symbol.isdigit():
        return None
    price = finite_float(entry.get("f2"))
    if price is None or price <= 0:
        return None
    return symbol, {
        "price": price,
        "change": finite_float(entry.get("f3")),
        "change_yuan": finite_float(entry.get("f4")),
        "name": str(entry.get("f14") or symbol)[:50],
        "volume_hands": finite_float(entry.get("f5")),
        "turnover_yuan": finite_float(entry.get("f6")),
        "trade_at": as_iso(entry.get("f124")),
    }


def fetch_all_a_shares():
    page_size = 35  # keep Eastmoney clist payload small; larger pages may be truncated
    common = {"pn": 1, "pz": page_size, "po": 0, "np": 1, "fltt": 2, "invt": 2,
              "fid": "f12", "fs": MARKETS, "fields": FIELDS}
    first = download_json(f"{BASE}/clist/get", common)
    if not isinstance(first.get("data"), dict):
        raise RuntimeError("Missing A-share market data")
    total = int(first["data"].get("total") or 0)
    if total < 4000:
        raise RuntimeError(f"Unexpected A-share market coverage: {total}")
    page_count = math.ceil(total / page_size)
    result = {}
    for page in range(1, page_count + 1):
        response = first if page == 1 else download_json(f"{BASE}/clist/get", {**common, "pn": page})
        batch = entries(response)
        if not batch:
            raise RuntimeError(f"A-share page {page}/{page_count} empty; preserving old snapshot")
        for item in batch:
            parsed = quote_row(item)
            if parsed:
                result[parsed[0]] = parsed[1]
        if page % 15 == 0:
            print(f"Retrieved {page}/{page_count} market pages, {len(result)} valid prices", flush=True)
        time.sleep(0.16)
    # Suspended/new listings may lack live price; not all 5,000 securities will have a quote.
    if len(result) < max(3200, round(total * 0.75)):
        raise RuntimeError(f"Insufficient priced securities {len(result)} / total {total}")
    return result, total


def fallback_quotes():
    secids = [f"{1 if symbol.startswith(('6', '5', '9')) else 0}.{symbol}" for symbol in FALLBACK]
    obj = download_json(f"{BASE}/ulist.np/get", {
        "fltt": 2, "invt": 2, "secids": ",".join(secids), "fields": FIELDS
    })
    result = {}
    for item in entries(obj):
        parsed = quote_row(item)
        if parsed:
            result[parsed[0]] = parsed[1]
    if len(result) < 3:
        raise RuntimeError("Fallback quote feed also unavailable")
    return result


def fetch_index():
    obj = download_json(f"{BASE}/ulist.np/get", {
        "fltt": 2, "invt": 2, "secids": "1.000001", "fields": "f2,f3,f4,f12,f14,f124"
    })
    rows = entries(obj)
    if not rows:
        raise RuntimeError("Index data unavailable")
    row = rows[0]
    price = finite_float(row.get("f2"))
    if price is None or price <= 0:
        raise RuntimeError("Invalid index quote")
    return {"name": "上证指数", "symbol": "000001", "price": price,
            "change": finite_float(row.get("f3")), "trade_at": as_iso(row.get("f124"))}


def fetch_index_technical():
    obj = download_json("https://push2his.eastmoney.com/api/qt/stock/kline/get", {
        "secid": "1.000001", "fields1": "f1,f2,f3,f4,f5,f6", "fields2": "f51,f52,f53,f54,f55,f56,f57",
        "klt": 101, "fqt": 0, "end": 20500101, "lmt": 290,
    })
    items = (obj.get("data") or {}).get("klines") or []
    closes = []
    for item in items:
        fields = str(item).split(",")
        if len(fields) >= 3:
            value = finite_float(fields[2])
            if value is not None:
                closes.append(value)
    if len(closes) < 260:
        raise RuntimeError(f"Insufficient SSE historical prices: {len(closes)}")
    mean = lambda periods: sum(closes[-periods:]) / periods
    ma20, ma60, ma250 = mean(20), mean(60), mean(250)
    slope20 = ma20 - (sum(closes[-25:-5]) / 20)
    close = closes[-1]
    if close >= ma20 >= ma60 >= ma250 and slope20 > 0:
        regime = "bull"
    elif close >= ma20 >= ma60 and slope20 > 0:
        regime = "structural"
    elif close < ma20 < ma60 < ma250 and close < ma60 * 0.94:
        regime = "bear"
    elif (close < ma60 and (slope20 > 0 or close >= ma20)):
        regime = "bottoming"
    else:
        regime = "range"
    return {"suggested": regime, "ma20": round(ma20, 2), "ma60": round(ma60, 2),
            "ma250": round(ma250, 2), "ma20_slope_5_sessions": round(slope20, 2),
            "last_history_close": close,
            "method": "SSE日线MA20/MA60/MA250及20日均线斜率的规则辅助判断；用户手动确认为准"}


def main():
    now = datetime.now(tz=BEIJING).isoformat(timespec="seconds")
    try:
        quotes, reported_total = fetch_all_a_shares()
        source = "东方财富网页行情 · A股全市场采集"
        coverage = "full"
        print(f"Fetched {len(quotes)} stock quotes / {reported_total} listed rows")
    except Exception as error:
        print(f"WARN: Eastmoney full-market feed failed: {error}; trying independent Sina full-market fallback", file=sys.stderr)
        try:
            from sina_a_share import fetch_all_sina
            quotes, reported_total = fetch_all_sina()
            source = "新浪财经公开网页行情 · 全市场备用采集"
            coverage = "full"
        except Exception as secondary:
            print(f"WARN: Sina full-market fallback unavailable: {secondary}; using named-stock fallback", file=sys.stderr)
            quotes = fallback_quotes()
            source = "东方财富网页行情 · 预置股票回退采集（部分行情）"
            coverage = "fallback"
    try:
        index = fetch_index()
    except Exception as error:
        print(f"WARN: SSE index unavailable: {error}", file=sys.stderr)
        index = None
    try:
        technical = fetch_index_technical()
    except Exception as error:
        print(f"WARN: SSE indicator unavailable: {error}", file=sys.stderr)
        technical = None
    # Sina's ticktime is not a full trade timestamp: align its snapshot with the
    # exchange index's actual last trade date rather than inventing today's close.
    if coverage == "full" and source.startswith("新浪"):
        if not index or not index.get("trade_at"):
            coverage = "unverified"
        else:
            for quote in quotes.values():
                quote["trade_at"] = index["trade_at"]
    data = {
        "updated_at": now, "source": source, "coverage": coverage,
        "count": len(quotes), "quotes": quotes,
        "index": index, "technical": technical,
    }
    OUTPUT.parent.mkdir(exist_ok=True, parents=True)
    tmp = OUTPUT.with_name("quotes.json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    os.replace(tmp, OUTPUT)
    print(f"Saved {OUTPUT} ({OUTPUT.stat().st_size/1024:.1f} KB) at {now}")


if __name__ == "__main__":
    main()
