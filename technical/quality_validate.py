"""Acceptance fixtures use actual data, not hardcoded exception handling."""
from .quality import QualityHistory,public_summary
from .indicators import period
from .data import calendar
from .diagnostics import emit

def check_cases(api,code,raw,factors,asof,cal,report):
    q=QualityHistory(raw,factors,code,asof)
    expected={"002475.SZ":[],"600000.SH":[("20060512","major")],"300750.SZ":[("20210705","minor")]}[code]
    actual=[(e["date"],e["severity"]) for e in q.events]
    if actual!=expected:raise RuntimeError("unexpected quality classification")
    current=q.view(asof,cal)
    assert report["data_quality"]==public_summary(current)
    assert current["combined_feature_ready"],"current sample not recovered"
    out={"code":code,"events":q.events,"current":public_summary(current),"cases":[]}
    for event,severity in actual:
        i=q.dates.index(event);before=q.dates[i-1];after=q.dates[i+1]
        ec=calendar(api,event)
        # Exchange calendar obtained separately. Label horizon counts exchange sessions.
        vb=q.view(before,ec);ve=q.view(event,ec);va=q.view(after,ec)
        horizon=ec.index(event)-ec.index(before) if before in ec else None
        # Long suspension can put prior actual bar outside the short calendar.
        # Fetch the local interval explicitly if needed, no fabricated open days.
        if horizon is None:
            rows=api.ask("trade_cal",{"exchange":"SSE","start_date":before,"end_date":after},"cal_date,is_open")
            from datetime import datetime
            assert len({r["cal_date"] for r in rows})==(datetime.strptime(after,"%Y%m%d")-datetime.strptime(before,"%Y%m%d")).days+1
            ec=sorted(r["cal_date"] for r in rows if str(r["is_open"])=="1")
            horizon=ec.index(event)-ec.index(before)
        label=q.label_admission(before,horizon,ec)
        if severity=="major":
            assert vb["last_major"] is None,"future event leaked into feature view"
            assert ve["state"]=="blocked" and ve["last_major"]==event
            assert all(not z["bars"] for z in ve["groups"].values())
            assert va["groups"]["day"]["count"]==1
            for freq in ("week","month"):
                assert va["groups"][freq]["count"]==int(period(after,freq)>period(event,freq))
                assert all(period(b["date"],freq)>period(event,freq) for b in va["groups"][freq]["bars"])
            assert not label["eligible"] and label["reason"]=="major_event_in_label_window"
            assert not q.training_admission(event,1,ec)["eligible"]
        else:
            assert ve["last_major"] is None
            # A young listing may lack a full feature vector regardless of this warning.
            assert ve["groups"]["day"]["count"]==i+1
            assert label["eligible"] and label["reason"]=="minor_warning"
        out["cases"].append({"date":event,"severity":severity,"previous_date":before,"next_date":after,
             "before_state":vb["state"],"event_state":ve["state"],"after_state":va["state"],
             "event_clean_counts":{k:v["count"] for k,v in ve["groups"].items()},
             "next_clean_counts":{k:v["count"] for k,v in va["groups"].items()},"label":label})
    emit("TECH_QUALITY_ACCEPTANCE",out)
