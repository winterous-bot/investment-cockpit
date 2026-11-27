"""Read-only entitlement and coverage probe; no private pool, values, or secrets in logs."""
import json,os,urllib.request
from collections import Counter
DAY="20261127"
STOCK="600000.SH"
INDEX="000001.SH"
MIN_FIELDS="ts_code,trade_time,open,high,low,close,vol,amount"
DAY_FIELDS="ts_code,trade_date,open,high,low,close,vol,amount"
PROBES=[
 ("stock_1min","stk_mins",{"ts_code":STOCK,"freq":"1min","start_date":"2026-11-27 09:00:00","end_date":"2026-11-27 19:00:00"},MIN_FIELDS),
 ("stock_60min","stk_mins",{"ts_code":STOCK,"freq":"60min","start_date":"2026-08-01 09:00:00","end_date":"2026-11-27 19:00:00"},MIN_FIELDS),
 ("index_1min","idx_mins",{"ts_code":INDEX,"freq":"1min","start_date":"2026-11-27 09:00:00","end_date":"2026-11-27 19:00:00"},MIN_FIELDS),
 ("index_60min","idx_mins",{"ts_code":INDEX,"freq":"60min","start_date":"2026-08-01 09:00:00","end_date":"2026-11-27 19:00:00"},MIN_FIELDS),
 ("stock_60min_day","stk_mins",{"ts_code":STOCK,"freq":"60min","start_date":"2026-11-27 09:00:00","end_date":"2026-11-27 19:00:00"},MIN_FIELDS),
 ("stock_60min_week","stk_mins",{"ts_code":STOCK,"freq":"60min","start_date":"2026-11-23 09:00:00","end_date":"2026-11-27 19:00:00"},MIN_FIELDS),
 ("stock_60min_month","stk_mins",{"ts_code":STOCK,"freq":"60min","start_date":"2026-10-26 09:00:00","end_date":"2026-11-27 19:00:00"},MIN_FIELDS),
 ("stock_1min_week","stk_mins",{"ts_code":STOCK,"freq":"1min","start_date":"2026-11-23 09:00:00","end_date":"2026-11-27 19:00:00"},MIN_FIELDS),
 ("stock_1min_old_day","stk_mins",{"ts_code":STOCK,"freq":"1min","start_date":"2025-11-27 09:00:00","end_date":"2025-11-27 19:00:00"},MIN_FIELDS),
 ("stock_1min_other_symbol","stk_mins",{"ts_code":"000001.SZ","freq":"1min","start_date":"2026-11-27 09:00:00","end_date":"2026-11-27 19:00:00"},MIN_FIELDS),
 ("stock_daily","daily",{"ts_code":STOCK,"start_date":"20190101","end_date":DAY},DAY_FIELDS),
 ("adjustment","adj_factor",{"ts_code":STOCK,"start_date":"20190101","end_date":DAY},"ts_code,trade_date,adj_factor"),
 ("stock_daily_basic","daily_basic",{"ts_code":STOCK,"start_date":"20261101","end_date":DAY},"ts_code,trade_date,turnover_rate,volume_ratio"),
 ("index_daily","index_daily",{"ts_code":INDEX,"start_date":"20190101","end_date":DAY},DAY_FIELDS),
 ("moneyflow","moneyflow",{"ts_code":STOCK,"start_date":"20261101","end_date":DAY},"ts_code,trade_date,net_mf_amount"),
 ("margin_detail","margin_detail",{"ts_code":STOCK,"start_date":"20261101","end_date":"20261126"},"ts_code,trade_date,rzye,rzmre,rzche"),
 ("industry_members","index_member_all",{"ts_code":STOCK,"is_new":"Y"},"ts_code,l1_code,l2_code,in_date,out_date"),
 ("chip_cost","cyq_perf",{"ts_code":STOCK,"start_date":"20261101","end_date":DAY},"ts_code,trade_date,weight_avg,winner_rate"),
 ("price_limits","stk_limit",{"ts_code":STOCK,"trade_date":DAY},"ts_code,trade_date,up_limit,down_limit"),
]
def probe(token,label,endpoint,params,fields):
    req=urllib.request.Request("https://api.tushare.pro",data=json.dumps({"api_name":endpoint,"token":token,"params":params,"fields":fields}).encode(),headers={"Content-Type":"application/json"},method="POST")
    try:
        with urllib.request.urlopen(req,timeout=20) as r:
            p=json.loads(r.read(4_500_000))
        if p.get("code")!=0:
            msg=str(p.get("msg") or "")
            state="permission_denied" if any(w in msg for w in ("权限","积分","开通","permission")) else "api_rejected"
            return {"probe":label,"state":state,"code":p.get("code") if isinstance(p.get("code"),int) else None}
        data=p.get("data") or {}; head=data.get("fields") or []; rows=[dict(zip(head,x)) for x in data.get("items") or [] if len(x)==len(head)]
        dates=sorted(str(x.get("trade_time") or x.get("trade_date")) for x in rows if x.get("trade_time") or x.get("trade_date"))
        result={"probe":label,"state":"ok" if rows else "empty","rows":len(rows),"fields_present":all(k in head for k in fields.split(","))}
        if dates:result.update(first=dates[0],last=dates[-1],latest_day_rows=Counter(d[:10] for d in dates)[dates[-1][:10]])
        return result
    except Exception as e:
        return {"probe":label,"state":"transport_error","type":type(e).__name__}
if __name__=="__main__":
    token=os.environ.get("TUSHARE_TOKEN")
    if not token:raise SystemExit("Missing token")
    for item in PROBES[4:10]:print("TECH_PROBE "+json.dumps(probe(token,*item),ensure_ascii=False),flush=True)
