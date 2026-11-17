#!/usr/bin/env python3
"""One-time historical A-share breadth backfill using Tushare Pro daily endpoint.

Reads TUSHARE_TOKEN only from GitHub Actions environment. Never prints token
or stores it in a committed file. Higher-tier trade_cal/stock_basic avoided.

This is not an industry-history or adjusted-close backfill.
"""
from __future__ import annotations
import argparse
import copy
import json
import math
import os
import re
import time
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import breadth_model as bm

ROOT = Path(__file__).resolve().parents[1]
HISTORY_FILE = ROOT / "data" / "breadth_history.json"
SIGNALS_FILE = ROOT / "data" / "market_signals.json"
STATUS_FILE = ROOT / "data" / "backfill_status.json"
ENDPOINT = "https://api.tushare.pro"
BEIJING = ZoneInfo("Asia/Shanghai")
TS_CODE = re.compile(r"^(\d{6})\.(SZ|SH)$")
MIN_SAMPLE = 3500
MAX_QUERIES = 180
MIN_SECONDS_BETWEEN_REQUESTS = 1.35
MIN_DAYS_TO_COMMIT = 80


class TushareError(RuntimeError):
    pass


def as_number(value):
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def tushare_daily(token: str, day: date, *, request=None):
    """Return standardized A-share daily closes/up ratio; never echo secret values."""
    request = request or urllib.request.urlopen
    body = json.dumps({
        "api_name": "daily",
        "token": token,
        "params": {"trade_date": day.strftime("%Y%m%d")},
        "fields": "ts_code,trade_date,close,pre_close,pct_chg",
    }, separators=(",", ":")).encode("utf-8")
    req = urllib.request.Request(
        ENDPOINT, data=body,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    try:
        with request(req, timeout=25) as response:
            payload = json.loads(response.read(2500000).decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, ValueError, OSError) as error:
        raise TushareError(f"API连接或解析失败（{type(error).__name__}）") from None
    if not isinstance(payload, dict) or payload.get("code") != 0:
        raise TushareError("Tushare daily 返回权限、限流或其他接口错误")
    data = payload.get("data") or {}
    if not data:
        # Holidays can return code=0 but no data table: not an API failure.
        return {"day":day.isoformat(),"prices":{},"sample":0,"measured":0,"up_ratio":None}
    fields, rows = data.get("fields") or [], data.get("items") or []
    if not rows:
        return {"day":day.isoformat(),"prices":{},"sample":0,"measured":0,"up_ratio":None}
    keys = {name: i for i, name in enumerate(fields)}
    required = {"ts_code", "trade_date", "close"}
    if not required.issubset(keys):
        raise TushareError("接口返回缺少必要字段")
    prices, rising, measured = {}, 0, 0
    for row in rows:
        if not isinstance(row, list) or len(row) < len(fields):
            continue
        code_info = TS_CODE.match(str(row[keys["ts_code"]]))
        if not code_info or str(row[keys["trade_date"]]) != day.strftime("%Y%m%d"):
            continue
        code = code_info.group(1)
        price = as_number(row[keys["close"]])
        if price is None or price <= 0:
            continue
        prices[code] = {"price": round(price, 3)}
        pct = as_number(row[keys["pct_chg"]]) if "pct_chg" in keys else None
        prev = as_number(row[keys["pre_close"]]) if "pre_close" in keys else None
        if pct is None and prev is not None and prev > 0:
            pct = (price / prev - 1) * 100
        if pct is not None:
            measured += 1
            rising += pct > 0
    ratio = round(rising/measured, 6) if measured >= MIN_SAMPLE else None
    return {"day": day.isoformat(), "prices": prices, "sample": len(prices),
            "measured": measured, "up_ratio": ratio}


def prior_weekdays(end: date, maximum: int = MAX_QUERIES):
    """Only weekday candidates. Valid daily results identify actual trading sessions."""
    d = end
    out = []
    while len(out) < maximum:
        if d.weekday() < 5:
            out.append(d)
        d -= timedelta(days=1)
    return out


def safe_end_date():
    now = datetime.now(BEIJING)
    return now.date() if now.hour >= 18 else now.date()-timedelta(days=1)


def load_old_history():
    history, issues = bm.read_history(HISTORY_FILE)
    for issue in issues:
        print("WARN previous history: " + issue)
    return history


def extend_with_old_newer(history, previous, newest: str):
    """Preserve later valid snapshots; never override them with stale backfill."""
    old_dates = previous.get("stock_dates") or []
    old_prices = previous.get("stock_prices") or {}
    for index, day in enumerate(old_dates):
        if day <= newest:
            continue
        quotes = {symbol: {"price": arr[index]} for symbol, arr in old_prices.items()
                  if len(arr) > index and as_number(arr[index]) is not None
                  and as_number(arr[index]) > 0}
        bm.update_stocks(history, day, quotes, "full")
    for row in previous.get("participation") or []:
        if row.get("date", "") > newest:
            bm.update_participation(history, row["date"], row["ratio"],
                                    row["sample"], row.get("source", "previous"))
    return history


def build_history(previous, daily_rows):
    result = bm.fresh_history()
    result["industries"] = copy.deepcopy(previous.get("industries") or {})
    for record in sorted(daily_rows, key=lambda r:r["day"]):
        bm.update_stocks(result, record["day"], record["prices"], "full")
        if record["up_ratio"] is not None:
            bm.update_participation(result, record["day"], record["up_ratio"],
                                    record["measured"], "Tushare daily涨跌幅（沪深A股）")
    if daily_rows:
        extend_with_old_newer(result, previous, max(r["day"] for r in daily_rows))
    return result


def build_breadth(history, existing, latest):
    """Change only two components supported by daily, preserving any current sector score."""
    old_components = {c.get("id"): c for c in ((existing.get("breadth") or {}).get("components") or [])}
    stock_sample = sum(1 for arr in (history.get("stock_prices") or {}).values()
                       if arr and arr[-1] is not None)
    stock = bm.stock_trend(history, latest, stock_sample)
    participation = bm.participation(history, latest)
    industry = old_components.get("industry_trend")
    if not industry or industry.get("asof") != latest:
        industry = {"id":"industry_trend","name":"行业趋势扩散","weight":.35,
                    "score":None,"coverage":0,"days":len(((history.get("industries") or {}).get("eastmoney") or {}).get("dates") or []),
                    "need_days":60,"issue":"120积分Tushare daily不提供行业历史，使用独立行业数据源继续采集"}
    comps = [stock, industry, participation]
    score, coverage = bm.combine(comps)
    out = dict(existing.get("breadth") or {})
    out.update({"score":score,"coverage":coverage,"asof":latest if score is not None else None,
                "components":comps,"history_days":{
                    "stock":len(history.get("stock_dates") or []),
                    "participation":len(history.get("participation") or []),
                    "industries":len(((history.get("industries") or {}).get("eastmoney") or {}).get("dates") or []),
                },"issues":[c.get("issue") for c in comps if c.get("issue")],
                "method":"个股MA60趋势40%＋行业趋势35%＋近5日涨跌家数25%，子维度按有效历史折算",
                "history_source":"Tushare Pro daily（未复权沪深股票日线）"})
    return out


def update_signals_file(history, latest):
    if not SIGNALS_FILE.exists():
        print("WARN no market_signals.json; daily workflow will calculate breadth")
        return
    try:
        existing=json.loads(SIGNALS_FILE.read_text(encoding="utf-8"))
        if not isinstance(existing,dict) or "technical" not in existing or "liquidity" not in existing:
            print("WARN signals file invalid; leave unchanged")
            return
    except (OSError,ValueError):
        print("WARN signals file unreadable; leave unchanged")
        return
    technical_date=str((existing.get("technical") or {}).get("asof") or "")[:10]
    if technical_date != latest:
        print(f"WARN signals date {technical_date} differs from backfill {latest}; history saved, signals unchanged")
        return
    existing["breadth"]=build_breadth(history,existing,latest)
    existing["version"]=3
    existing["updated_at"]=datetime.now(BEIJING).isoformat(timespec="seconds")
    existing["backfill_source"]="Tushare Pro daily（仅沪深A股原始未复权日线）"
    save_atomic(SIGNALS_FILE,existing)


def save_atomic(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix(path.suffix+".tmp")
    tmp.write_text(json.dumps(value,ensure_ascii=False,separators=(",",":")),encoding="utf-8")
    os.replace(tmp,path)


def run(days=100,delay=MIN_SECONDS_BETWEEN_REQUESTS,fetch=tushare_daily,end=None):
    token=os.environ.get("TUSHARE_TOKEN","").strip()
    if not token:
        raise TushareError("未找到GitHub Actions密钥TUSHARE_TOKEN")
    if not 80<=days<=110:
        raise ValueError("回补交易日必须为80—110")
    end=end or safe_end_date()
    found,counts=[],{"empty_or_undercount":0,"errors":0,"probed":0}
    for candidate in prior_weekdays(end,MAX_QUERIES):
        if len(found)>=days:
            break
        counts["probed"]+=1
        try:
            item=fetch(token,candidate)
            if item["sample"]>=MIN_SAMPLE:
                found.append(item)
                if len(found)%15==0:
                    print(f"Valid sessions={len(found)}/{days}; sampled date={candidate.isoformat()}; symbols={item['sample']}",flush=True)
            else:
                counts["empty_or_undercount"]+=1
        except TushareError as error:
            counts["errors"]+=1
            if counts["errors"]<=5:
                print(f"WARN {candidate.isoformat()}: {error}",flush=True)
            if counts["errors"]>=12 and len(found)<MIN_DAYS_TO_COMMIT:
                raise TushareError("历史请求失败过多；停止回补，原历史文件未修改") from None
        if delay:time.sleep(delay)
    if len(found)<MIN_DAYS_TO_COMMIT:
        raise TushareError(f"有效历史日仅{len(found)}天（至少需要{MIN_DAYS_TO_COMMIT}天）；原历史文件未修改")
    previous=load_old_history()
    history=build_history(previous,found)
    latest=history["stock_dates"][-1]
    if len(history["stock_dates"])<MIN_DAYS_TO_COMMIT:
        raise TushareError("历史合并后不足80个有效交易日，停止写入")
    save_atomic(HISTORY_FILE,history)
    update_signals_file(history,latest)
    status={"version":1,"source":"Tushare Pro daily","adjustment":"未复权（除权除息影响个别均线）",
            "completed_at":datetime.now(BEIJING).isoformat(timespec="seconds"),
            "latest":latest,"requested_sessions":days,"valid_sessions":len(found),
            "stored_sessions":len(history["stock_dates"]),
            "stock_symbols":len(history["stock_prices"]),
            "participation_sessions":len(history["participation"]),
            "metrics":{"stock":bm.stock_trend(history,latest,sum(1 for a in history["stock_prices"].values() if a[-1] is not None))["score"],
                       "participation":bm.participation(history,latest)["score"]},
            "request_counts":counts,"token_logged":False}
    save_atomic(STATUS_FILE,status)
    print(f"Backfill finished: {len(found)} valid days; {status['stored_sessions']} stored; "
          f"{status['stock_symbols']} symbols; last date {latest}; no secrets logged.",flush=True)
    return status


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--days",type=int,default=100)
    parser.add_argument("--end",type=str,help="Optional last date YYYYMMDD")
    args=parser.parse_args()
    end=datetime.strptime(args.end,"%Y%m%d").date() if args.end else None
    try:
        run(days=args.days,end=end)
    except (TushareError,ValueError) as e:
        print("ERROR: "+str(e),flush=True)
        raise SystemExit(1)
