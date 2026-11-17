#!/usr/bin/env python3
"""Idempotent weekday Tushare daily incremental updater for existing public breadth history.

Reads TUSHARE_TOKEN exclusively from the GitHub Actions environment; no token
is ever committed, printed, or copied to output artifacts.
"""
from __future__ import annotations
import os
from datetime import datetime, timedelta, date
from pathlib import Path
from zoneinfo import ZoneInfo

import breadth_model as bm
from backfill_tushare import tushare_daily, TushareError, HISTORY_FILE, safe_end_date, save_atomic

MIN_SAMPLE=3500
BEIJING=ZoneInfo("Asia/Shanghai")


def latest_candidates(end:date, lookback=5):
    days=[]
    d=end
    while len(days)<lookback:
        if d.weekday()<5:
            days.append(d)
        d-=timedelta(days=1)
    return days


def append_increment(token, fetch=tushare_daily, end=None, history_file=HISTORY_FILE):
    if not token:
        print("WARN TUSHARE_TOKEN unavailable; retain saved history without modification.")
        return {"updated":False,"reason":"token_missing"}
    hist, warnings=bm.read_history(Path(history_file))
    for msg in warnings:print("WARN market history: "+msg)
    dates=hist.get("stock_dates") or []
    current=dates[-1] if dates else None
    if not current:
        print("WARN no seeded history; initial 100-day backfill required first.")
        return {"updated":False,"reason":"history_missing"}
    candidates=[d for d in reversed(latest_candidates(end or safe_end_date()))
                if d.isoformat()>current]
    if not candidates:
        print(f"INFO Already up-to-date through {current}.")
        return {"updated":False,"reason":"up_to_date","asof":current}
    latest_added=None
    added_count=0
    for d in candidates:
        asof=d.isoformat()
        try:
            row=fetch(token,d)
        except TushareError as error:
            print(f"WARN Tushare {asof}: {error}. Stop to prevent gaps in MA60 history.")
            break
        if row["sample"]<MIN_SAMPLE:
            if row["sample"]==0:
                print(f"INFO {asof}: no close yet / exchange holiday.")
                continue
            print(f"WARN {asof}: partial trading-day data ({row['sample']} stocks); stop.")
            break
        if row["up_ratio"] is None:
            print(f"WARN {asof}: missing breadth count; stop to preserve sequential history.")
            break
        if not bm.update_stocks(hist,asof,row["prices"],"full"):
            print(f"WARN {asof}: invalid record; stop without advancing later dates.")
            break
        bm.update_participation(hist,asof,row["up_ratio"],row["measured"],
                                "Tushare Pro daily (SH/SZ A)")
        latest_added=asof
        added_count+=1
        print(f"OK Tushare daily increment: {asof}, {row['sample']} stocks.")
    if added_count:
        save_atomic(Path(history_file),hist)
        print(f"OK Persisted {added_count} sessions, latest {latest_added}.")
        return {"updated":True,"asof":latest_added,"sessions":added_count}
    print(f"INFO No newer Tushare daily close found (saved through {current}).")
    return {"updated":False,"reason":"no_newer_trade_date","asof":current}


def main():
    token=os.environ.get("TUSHARE_TOKEN","").strip()
    try:
        append_increment(token)
    except Exception as error:
        # Daily public snapshot must still run if the optional provider is down.
        print("WARN Tushare incremental update failed; preserved last valid archive: "+type(error).__name__)


if __name__=="__main__":
    main()
