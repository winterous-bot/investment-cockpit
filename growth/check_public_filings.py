"""Reconcile four public 2025 annual statement values for 5 industrial firms.
Not a full independent FCFF or DCF audit. No vendor raw numbers logged."""
import sys,json,os
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"scripts"))
from tushare_5000 import Tushare,SafeAPIError,POINTS
from financial_engine import FIELDS,pick
POINTS.update({k.removesuffix("_vip"):2000 for k in FIELDS})
def main():
    fixtures=json.loads((Path(__file__).parent/"public_filing_fixtures.json").read_text())
    api=Tushare(os.environ.get("TUSHARE_TOKEN"));results=[]
    for x in fixtures["companies"]:
        z={};errors=[]
        for ep,fields in FIELDS.items():
            field="ts_code,ann_date,f_ann_date,end_date,report_type,comp_type,update_flag,"+",".join(fields)
            try:
                rows=api.ask(ep.removesuffix("_vip"),{"period":fixtures["period"],"report_type":"1","ts_code":x["code"]},field)
                data,_=pick(rows,fixtures["period"],fixtures["asof"],fields)
                z[ep]=data.get(x["code"]) or {}
            except SafeAPIError:errors.append(ep);z[ep]={}
        pairs={"revenue":z["income_vip"].get("revenue"),"cfo":z["cashflow_vip"].get("n_cashflow_act"),"assets":z["balancesheet_vip"].get("total_assets"),"parent_equity":z["balancesheet_vip"].get("total_hldr_eqy_exc_min_int")}
        # 1 CNY tolerance for cent values; 1,000 CNY for rounded thousand-yuan filings.
        tol=max(1,x.get("rounding_unit",1))
        checks={k:"missing" if v is None else "match" if abs(v-x[k])<=tol else "mismatch" for k,v in pairs.items()}
        results.append({"code":x["code"],"name":x["name"],"checks":checks,"errors":errors,"pass":all(v=="match" for v in checks.values())})
    report={"public_filing_check":{"companies":len(results),"company_pass":sum(v["pass"] for v in results),"matched_fields":sum(s=="match" for v in results for s in v["checks"].values()),"total_fields":len(results)*4,"details":results}}
    print(json.dumps(report,ensure_ascii=False))
if __name__=="__main__":main()
