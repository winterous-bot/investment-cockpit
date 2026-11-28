# Technical Foundation V1.0 — frozen research baseline

Status: **frozen** for Stage 2 research; not deployed to production. Data as of 2026-11-27. Validated code commit: `547ee8aae925bfdc55bc273c27133d367d7bc49c`. Acceptance run: https://github.com/winterous-bot/investment-cockpit/actions/runs/46088045838 (success).

## Results
- 12 unit tests; 6,480/6,480 signal-oracle comparisons; 47/47 screenshot directions; 43/50 screenshot numeric comparisons (unchanged tolerances and seven outstanding source deviations).
- 90/90 completed week/month periods for each provider path; 720/720 raw OHLC fields, 360/360 reanchored adjusted OHLC fields; volume/amount after verified unit conversion all pass.
- 12,391/12,393 raw continuity pairs pass; both exceptions automatically classified. SPD Bank 2006-05-12: major, 28.20856 pp discrepancy, feature series segmented and crossing label rejected. CATL 2021-07-05: minor, 0.003613 pp discrepancy, warning retained; no re-anchoring repair. All three current sample reports have combined features ready.

## Frozen policy
The canonical daily + adj_factor pipeline, R1 indicators, R2 signal primitives and R2.1 quality checks remain unchanged. QualityHistory is integrated into build(). Major events exclude the event day and entire containing week/month from clean post-event history; all raw records are retained. Recursive indicators need 120 completed clean bars, recursive directions and MACD crossing 121. Complete combined features require 253 day bars and 61 week/month bars, plus post-major warmup. Minor is allowed only on factor change with price discrepancy <=0.05 CNY and <=1 bp relative plus return checks. Ordinary precision tolerances remain unchanged. Label and training admission must be used in Stage 2/3; verified exchange sessions are required, and missing/suspended label dates and crossing major events are rejected.

## Boundaries
- External vendor screenshot validation limited to one stock/date; seven numeric mismatches remain under original tolerance rule.
- Provider cross-checks are between Tushare endpoints, not independently sourced market records.
- Historical provider revisions and full-market corporate-action coverage have not been independently validated.
- Major-event 120/121-bar warmup and minor thresholds are conservative engineering policy, not optimized or proven predictive.
- Training admission requires verified full exchange calendar; feature/label gate must be called by future probability model. Historical data is not certified as point-in-time vintage.
- Minute data excluded; no production integration or probability model training.

Do not change frozen definitions without a new version and documented validation. Freeze record is separate from validated executable code; production main remains untouched. Earlier validation attempt failed because an assertion incorrectly expected no weekly bar after a Friday event; the corrected assertion derives the next period from dates. A young listing can also lack sufficient monthly bars independently of minor warnings. Final run validates both cases without changing quality thresholds.
