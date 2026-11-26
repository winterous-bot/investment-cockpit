"""Select the last eligible Shanghai trading day and time gates (no user data)."""
from datetime import datetime,timedelta
from zoneinfo import ZoneInfo
import json,os,sys
from tushare_5000 import Tushare

def plan(now,rows):
    today=now.strftime("%Y%m%d")
    clock=now.hour*100+now.minute
    eligible=today if clock>=1815 else (now.date()-timedelta(days=1)).strftime("%Y%m%d")
    dates=sorted({str(x["cal_date"]) for x in rows if str(x.get("is_open"))=="1" and str(x["cal_date"])<=eligible})
    if not dates:raise RuntimeError("No eligible trading date")
    target=dates[-1]
    due={k:target!=today or clock>=t for k,t in {"radar":1815,"growth":1845,"watchlist":2130}.items()}
    return {"target":target,"due":due}

if __name__=="__main__":
    now=datetime.now(ZoneInfo("Asia/Shanghai"))
    rows=Tushare(os.environ["TUSHARE_TOKEN"]).ask("trade_cal",{"exchange":"SSE","start_date":(now.date()-timedelta(days=30)).strftime("%Y%m%d"),"end_date":now.strftime("%Y%m%d")},"cal_date,is_open")
    if len({str(x["cal_date"]) for x in rows})<30:raise RuntimeError("Incomplete trading calendar")
    print(json.dumps(plan(now,rows)))
