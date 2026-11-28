"""D: deterministic Chinese research report on the unchanged A/B/C-R1 engines.
No LLM narrative, no production mutation, no probability or automatic execution.
"""
from .model_a import analyze,finite,pos
from .model_b import attach,industry_context
from .model_c_r1 import analyze_r1
from .quality import QualityHistory
VERSION="technical-model-v1.0-D"
LABELS={"bullish":"多头","bearish":"空头","range":"震荡","unknown":"未知",
 "strong":"强势","weak":"弱势","mixed":"分歧或震荡","strong_positive":"强烈偏多","positive":"偏多",
 "strong_negative":"强烈偏空","negative":"偏空","conflicting_or_range":"周期分歧或震荡",
 "bullish_alignment":"多周期多头共振","bearish_alignment":"多周期空头共振",
 "rebound_in_downtrend":"下跌结构中的反弹","pullback_in_uptrend":"上涨结构中的回调",
 "outperforming":"相对强势","underperforming":"相对弱势","neutral":"相对中性",
 "ready":"可计算","ready_with_warning":"可计算（历史质量警告）","blocked":"质量准入阻断",
 "candidate":"候选突破","confirmed":"突破确认","retest":"回踩信号","false_breakout":"假突破",
 "invalidated":"突破失效","expired":"事件过期","none":"未识别","defensive":"防御",
 "context_ready":"环境证据齐备","incomplete":"环境证据不足",
 "defensive_no_new_exposure":"防御：暂缓新增风险敞口","evidence_insufficient_features":"特征不足，不提供完整交易判断",
 "evidence_insufficient_context_or_risk":"市场行业或实际风险权限未核实",
 "portfolio_permission_unverified_or_denied":"组合风险预算未核实或不允许",
 "observe_no_chasing":"观察，不追高","watch":"继续观察","conditional_opportunity":"条件式机会（非买入指令）",
 "review_risk":"复核现有持仓风险","hold_review":"复核持仓","holding_status_unknown":"实际持仓未知",
 "not_applicable":"无持仓复核需求","within_horizon":"存在周期内压力参考",
 "remote_only":"仅远期压力，不作目标","no_structural_resistance":"未识别结构压力",
 "unresolved_at_price":"现价处于未解决压力区","caution":"位置风险警戒",
 "bullish_candidate":"多头反转候选","bearish_candidate":"空头反转候选",
 "bullish_confirmed":"多头反转确认","bearish_confirmed":"空头反转确认",
 "bullish_provisional_candidate":"未完成周线多头反转候选","bearish_provisional_candidate":"未完成周线空头反转候选"}
RISK={"extension":"追高警戒","distance_risk":"失效距离≥8%","high_volatility":"日ATR/股价≥5%",
      "unfavorable_rr":"参考盈亏比不足2:1","missing_level":"有效目标或失效价不足","unresolved_obstacle":"现价压力障碍未解决"}
NAMES={"002475.SZ":"立讯精密","600000.SH":"浦发银行","300750.SZ":"宁德时代"}
FREQ={"day":"日线","week":"周线","month":"月线"}
def label(x):return LABELS.get(x,x if x is not None else "未知")
def num(x,d=2):return f"{x:.{d}f}" if finite(x) else "—"
def percent(x):return num(x)+"%" if finite(x) else "—"
def day(x):return f"{x[:4]}-{x[4:6]}-{x[6:]}" if x else "—"
def zone(z):
    if not z:return "未确认"
    return f'{num(z["low"])}–{num(z["high"])} ({z["grade"]}级，{z["touches"]}次反应)'
def fresh(x,asof):return x.get("asof")==asof and finite(x.get("score"))
def brief_zone(x):
    if x is None:return None
    return {k:x.get(k) for k in ("low","high","grade","touches","touch_dates","last_confirmation","frequencies","kinds","stop_anchor","evidence")}
def location_summary(l):
    x={k:l.get(k) for k in ("state","reason","price","atr14","atr_frequency","daily_atr14","distance_cap","invalidation","target_reference","reward_risk","risk_fraction","flags","risk_veto","target_status","completed_week_date","completed_week_trend")}
    for k in ("support","resistance","nearest_support_obstacle"):x[k]=brief_zone(l.get(k))
    for k in ("remote_support","remote_resistance"):x[k]=[brief_zone(z) for z in l.get(k,[])]
    x["dynamic_references"]=l.get("dynamic_references",[])
    x["at_price"]=l.get("at_price",[])
    return x

def compose(a,b,r,view,raw_close,holding=None,portfolio_permission=None,severe_risk=None):
    d=a["asof"];code=a["code"]
    if any(x.get("asof")!=d or x.get("code")!=code for x in (b,r)) or view["asof"]!=d:raise ValueError("report identity mismatch")
    if a["horizons"]!=b["horizons"] or a["horizons"]!=r["direction_scores"]:raise ValueError("direction score changed")
    if any(x.get("probability") is not None for x in (a,b,r)):raise ValueError("uncalibrated probability")
    ctx=b["market_industry_context"];plan=r["plan"];market=b["market"];industry=b["industry"]
    if plan["new_exposure"]=="conditional_opportunity":
        if not (ctx["state"]=="context_ready" and ctx["block_new_exposure"] is False and severe_risk is False and portfolio_permission is True and a["composite_ready"] and r["locations"]["short"]["risk_veto"] is False):
            raise ValueError("permission invariant")
    if ctx["block_new_exposure"] is True and plan["new_exposure"]=="conditional_opportunity":raise ValueError("defensive violation")
    gaps=[k for k in ("market_ready","breadth_ready","liquidity_ready","industry_ready") if not ctx[k]]
    if not a["composite_ready"]:gaps.append("stock_features")
    if severe_risk is None:gaps.append("user_risk_unverified")
    if portfolio_permission is not True:gaps.append("portfolio_permission_not_granted")
    cycles={}
    for f,c in a["cycles"].items():
        g=view["groups"][f]
        cycles[f]={**c,"indicators":g["indicators"],"signals":g["signals"],"clean_count":g["count"]}
    loc={h:location_summary(l) for h,l in r["locations"].items()}
    return {"version":VERSION,"code":code,"name":NAMES.get(code,code),"asof":d,"timezone":"Asia/Shanghai",
        "scope":"daily_weekly_monthly_close_only","price_basis":"asof_qfq_current_close_raw","close":raw_close,
        "quality":a["quality"],"composite_ready":a["composite_ready"],"market":market,"industry":industry,"context":ctx,
        "cycles":cycles,"horizons":a["horizons"],"alignment":a["alignment"],"medium_structure":a["medium_structure"],
        "weekly_reversal":a["weekly_reversal"],"locations":loc,"monthly_background":r["monthly_background"],
        "monthly_dynamic":r["monthly_dynamic"],"trend_tracking":r["trend_tracking"],
        "events":r["locations"]["medium"].get("breakouts",[]),
        "plan":plan,"permissions":{"holding":holding,"portfolio_permission":portfolio_permission,"severe_risk":severe_risk},
        "gaps":gaps,"probability":None,"coverage":r["coverage"],
        "limitations":["当前版本未接入分钟行情","历史行业与行情为当前数据商记录重建，非独立历史快照",
                       "技术评分和价位不是收益预测；交易阈值未完成样本外回测",
                       "中期交易位置仅供研究，不产生独立中期入场权限",
                       "实际成交受T+1、涨跌停、跳空、流动性和费用约束"]}

def build_report(q,asof,sessions,indices,market,breadth,activity,taxonomy,members,sectors,holding=None,portfolio_permission=None,severe_risk=None):
    if not isinstance(q,QualityHistory):raise TypeError("audited stock history required")
    a=analyze(q,asof,sessions,indices)
    i=industry_context(q,asof,sessions,indices,taxonomy,members,sectors)
    b=attach(a,market,breadth,activity,i,severe_risk)
    r=analyze_r1(q,b,sessions,holding,portfolio_permission)
    v=q.view(asof,sessions)
    raw=float(next(x["close"] for x in q.raw if x["trade_date"]==asof))
    return compose(a,b,r,v,raw,holding,portfolio_permission,severe_risk)

def render(r):
    d=r["asof"];c=r["context"];p=r["plan"];i=r["industry"];m=r["market"]
    # Every qualitative label is sourced from a typed engine result.
    out=[f'# {r["name"]}（{r["code"]}）综合技术分析',f'分析日：{day(d)}（北京时间收盘）｜收盘：{num(r["close"])}元｜D版研究报告',
         "", "## 1. 核心结论",
         f'短期1–5日：{label(r["horizons"]["short"]["direction"])}，D={num(r["horizons"]["short"]["D"])}；中期2–8周：{label(r["horizons"]["medium"]["direction"])}，D={num(r["horizons"]["medium"]["D"])}。',
         f'周期结构：{label(r["alignment"])}；中期结构：{label(r["medium_structure"])}；周线反转：{label(r["weekly_reversal"]["state"])}。',
         f'新增风险：{label(p["new_exposure"])}；现有持仓：{label(p["holding_review"])}。',"",
         "## 2. 市场与行业环境","|指标|评分/数值|状态|","|---|---:|---|"]
    for k,n in (("trend","四宽基趋势"),("breadth","市场广度"),("activity","成交活跃度")):
        x=m[k];ok=fresh(x,d)
        out.append(f'|{n}|{num(x.get("score")) if ok else "—"}/5|{label(x.get("state")) if ok else "缺失或日期不一致"}；覆盖 {percent(x.get("coverage")) if ok else "—"}|')
    it=i["trend"];mem=i["membership"];matched=mem.get("asof")==d and mem.get("state")=="matched"
    out.append(f'|申万一级行业|{mem.get("name") if matched else "未确认"}|{label(it.get("state")) if fresh(it,d) else "未知"} {num(it.get("score")) if fresh(it,d) else "—"}/5|')
    rel=i["industry_vs_market"]
    out.append(f'|行业相对市场RS20|{percent(rel.get("values",{}).get("20")) if matched else "—"}|{label(rel.get("relative_state")) if matched else "未知"}|')
    rs=i["stock_vs_industry"]
    out.append(f'|个股相对行业RS5/20/60|{" / ".join(percent(rs.get(str(n))) if matched else "—" for n in (5,20,60))}|相对收益，不是绝对涨跌|')
    out.extend([f'环境约束：{label(c["state"])}；行业及市场证据不重复计入D分数。',"",
                "## 3. 日周月技术结构","|周期|T趋势|M动量|MA5/10/20|MACD|RSI6/12/24|状态|","|---|---:|---:|---|---:|---|---|"])
    for f,x in r["cycles"].items():
        j=x["indicators"];status=label(x["trend"])
        if x["provisional"]:status+="（未收完）"
        out.append(f'|{FREQ[f]}|{num(x["T"])}|{num(x["M"])}|{" / ".join(num(j.get(k)) for k in ("ma5","ma10","ma20"))}|{num(j.get("macd"))}|{" / ".join(num(j.get(k)) for k in ("rsi6","rsi12","rsi24"))}|{status}；已完成至{day(x["latest_completed_date"])}|')
    out.extend(["","|周期|T|M|V量价|R相对强弱|D方向|","|---|---:|---:|---:|---:|---:|"])
    for h,n in (("short","短期"),("medium","中期")):
        x=r["horizons"][h];out.append(f'|{n}|{num(x["T"])}|{num(x["M"])}|{num(x["V"]["V"])}|{num(x["R"]["R"])}|{num(x["D"])}|')
    out.extend(["","## 4. 短中期关键价位（分析日前复权）","|周期|支撑|压力|失效参考价|参考盈亏比|风险距离|","|---|---|---|---:|---:|---:|"])
    for h,n in (("short","短期"),("medium","中期")):
        x=r["locations"][h];rr=x.get("reward_risk");risk=x.get("risk_fraction")
        out.append(f'|{n}|{zone(x["support"])}|{zone(x["resistance"])}|{num(x["invalidation"])}|{num(rr)+":1" if finite(rr) else "不可计算"}|{percent(risk*100) if finite(risk) else "—"}|')
        flags=x.get("flags") or {};active=[RISK[k] for k,v in flags.items() if v is True and k in RISK];unknown=[RISK[k] for k,v in flags.items() if v is None and k in RISK]
        out.append(f'|{n}位置警戒|{ "、".join(active) or "无明确触发" }|{"未知项："+ "、".join(unknown) if unknown else "—"}|{label(x.get("target_status"))}|ATR {num(x["atr14"])}|3ATR上限 {num(x["distance_cap"])}|')
    out.extend(["A级为多次反应证据；B级为潜在障碍或单次反应；动态均线仅参考。远期价位不参与当前盈亏比。中期不单独产生入场权限。","",
                "## 5. 技术事件与条件式计划"])
    # Include recent/active events, never describe old terminal event as a current signal.
    active=[e for e in r["events"] if e["state"] in ("candidate","confirmed","retest") or e["event_date"]==d]
    if active:
        for e in active:
            out.append(f'- {FREQ[e["frequency"]]}{e["lookback"]}周期{"向上" if e["direction"]=="up" else "向下"}：{label(e["state"])}，价位{num(e["level"])}，事件日{day(e["event_date"])}。')
    else:out.append("未识别当前活跃日周线突破信号（历史终止事件保留在结构化记录）。")
    out.extend([f'新增风险判断：{label(p["new_exposure"])}。',f'持仓复核：{label(p["holding_review"])}。'])
    if p["new_exposure"]=="conditional_opportunity":
        out.append(f'条件式研究入场参考：{num(p["reference_entry"])}；失效：{num(p["reference_invalidation"])}；压力参考：{num(p["reference_target"])}。非成交指令。')
    else:out.append("不提供实际买入价；观察下一次已确认的突破/回踩及对应周期的风险距离。")
    if r["trend_tracking"]:
        t=r["trend_tracking"];out.append(f'强趋势观察模式：前20日突破参考{num(t["breakout_reference"])}，动态失效参考{num(t["dynamic_invalidation_reference"])}；无目标、无盈亏比、无新增仓位权限。')
    out.extend(["","## 6. 数据与风险边界",
         f'质量：{label(r["quality"]["state"])}；历史异常数量：{r["quality"]["event_counts"]}。',f'实际持仓：{"未知" if r["permissions"]["holding"] is None else "已输入"}；实际风险权限及5×5组合预算：{"明确输入允许" if r["permissions"]["portfolio_permission"] is True and r["permissions"]["severe_risk"] is False else "未获完整允许"}。',
         "未来上涨概率：未建模、未校准，不输出。","；".join(r["limitations"])+"。"])
    return "\n".join(out)+"\n"
