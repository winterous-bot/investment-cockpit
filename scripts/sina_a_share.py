"""Independent Sina Finance full A-share quote fallback for daily breadth archives.

Public webpage data, no trading account information. Use only on primary feed failure.
Avoid repeated frequent calls: provider may restrict automated clients.
"""
from __future__ import annotations
import json
import math
import time
import urllib.parse
import urllib.request

BASE="https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php"
HEADERS={
 "User-Agent":"Mozilla/5.0 (Macintosh; Intel Mac OS X 13_5) AppleWebKit/537.36 Chrome/126 Safari/537.36",
 "Referer":"https://vip.stock.finance.sina.com.cn/mkt/",
 "Accept":"application/json,text/javascript,*/*",
}

def request_text(endpoint,params,retries=2):
    url=BASE+"/"+endpoint+"?"+urllib.parse.urlencode(params)
    last=None
    for attempt in range(retries):
        try:
            req=urllib.request.Request(url,headers=HEADERS)
            with urllib.request.urlopen(req,timeout=14) as reply:
                return reply.read(500000).decode("utf-8-sig",errors="replace").strip()
        except (OSError,ValueError) as exc:
            last=exc
            if attempt<retries-1:time.sleep(.8*(attempt+1))
    raise RuntimeError("Sina listing request failed: "+str(last))

def parse_page(text):
    raw=json.loads(text)
    if raw is None:return []
    if not isinstance(raw,list):raise ValueError("Sina stock listing is not an array")
    return raw

def to_float(x):
    try:
        result=float(str(x).replace("%",""))
        return result if math.isfinite(result) else None
    except (ValueError,TypeError):
        return None

def parse_stock(row):
    if not isinstance(row,dict):return None
    code=str(row.get("code") or "").strip()
    name=str(row.get("name") or code)[:50].strip()
    trade=to_float(row.get("trade"))
    change=to_float(row.get("changepercent"))
    amount=to_float(row.get("amount"))
    volume=to_float(row.get("volume"))
    if len(code)!=6 or not code.isdigit() or trade is None or trade<=0:
        return None
    return code,{"price":round(trade,4),"change":change,
       "change_yuan":to_float(row.get("pricechange")),
       "name":name,"turnover_yuan":amount,
       "volume_hands":volume/100 if volume is not None else None,
       "trade_at":None}

def fetch_all_sina(page_size=80):
    from math import ceil
    count_text=request_text("Market_Center.getHQNodeStockCount",{"node":"hs_a"})
    reported=int(json.loads(count_text))
    if not 3500<=reported<=7500:
        raise ValueError("Sina market universe count invalid: "+str(reported))
    quotes={}
    for page in range(1,ceil(reported/page_size)+1):
        rows=parse_page(request_text("Market_Center.getHQNodeData",{
            "page":page,"num":page_size,"sort":"symbol","asc":1,
            "node":"hs_a","symbol":"","_s_r_a":"page",
        }))
        if not rows:raise RuntimeError("Sina A-share page "+str(page)+" empty")
        for row in rows:
            parsed=parse_stock(row)
            if parsed:quotes[parsed[0]]=parsed[1]
        if page%20==0:print("Sina fallback: "+str(page)+" pages, "+str(len(quotes))+" valid quotes",flush=True)
        time.sleep(.15)
    if len(quotes)<max(3500,round(reported*.72)):
        raise RuntimeError("Sina valid quote sample too small: "+str(len(quotes))+"/"+str(reported))
    return quotes,reported

import math
