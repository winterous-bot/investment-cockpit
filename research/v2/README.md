# V2.0a historical validation — frozen study specification

## Status
Research-only. The existing iPhone V1.7 app, risk-v2.js, user holdings, main-branch
workflows and 5x5 risk limits have NOT been changed.
No investment action is performed or recommended by the scripts.

## Frozen rules (from 2026-11-17 research design)
- CSI300/500/1000/2000: 30/25/25/20; technical component = 35% midtrend
  + 25% MA60 ten-day slope (+/-0.3%)
  + 25% volatility-adjusted 20-day return (+/-0.5 z)
  + 15% long-term trend; each component [-1,0,1].
- Three aligned available indices required. CSI2000 is excluded before official
  2023-08-11 launch, even where historical vendor series is back-calculated.
- Breadth B=40% of historical day's traded-stock MA60 participation
  +35% of SW2021 sector-index MA60 participation
  +25% of mean percentage of rising stocks over the latest 5 trade days.
- Broad: B >= 60%, stock/industry >=55%; weak: B<=40% and both <45%.
- Leadership: >=3 industry indices above MA60 and >=3 percentage points above
  weighted broad index over 20 sessions, meeting the condition on >=10 of last 12 sessions.
- Prior decline: minimum of trailing 60d composite versus maximum of previous
  120d at least -12%; repair: at least two among price, momentum, breadth.
- Candidate priority bear, bull, bottoming, structural, range; confirmation
  3,5,5,5,3 days respectively. Unknown days cancel confirmation.
- Close(t) signal is tradable at close(t+1), earns returns thereafter.
- Target stock exposure as midpoint of original allowed ranges:
  bull 100%, structural 80%, range 55%, bottoming 35%, bear 12.5%.
  No margin leverage; turnover cost 10 bps; index total-return dividends
  and cash interest are NOT included. Benchmarks: 100% and 50% in composite
  index. This is a risk-budget proxy, not an executable individual-stock
  portfolio or an endorsement of stock allocation.

## Data and point-in-time limitations
- Tushare Pro data retrieved in GitHub Actions using existing TUSHARE_TOKEN
  repository secret. Token is not fetched, printed, or committed.
- Historical trading-day universe is sampled directly from `daily(trade_date)`,
  including subsequently delisted stocks. NOT filtered using today's stock_basic.
- `adj_factor(trade_date)` and daily OHLC compute historical adjusted MA60
  *using no prices beyond the observation date*. Suspended stock observations
  are missing, not filled with synthetic trading prices.
- SW2021 sector indexes existed as a 2021 taxonomy, and historical 2015–2021
  histories are back-calculated. The historical constituent membership of the
  2021 taxonomy is not a strictly contemporaneously published 2015 classification;
  these rows carry `historical_taxonomy_backcast:true`. Therefore 2015–2021
  is retrospective *illustration*, not a verified full point-in-time backtest.
  Strict post-2021 validation is reported separately.
- CSI2000 historical back-calculation is explicitly excluded before release.
- No raw licensed market price history, stock-level adjusted factors, stock lists,
  or personal portfolio data are committed to the public repo. Only aggregated
  research output is committed. Year shards are short-lived Actions artifacts.
  Confirm Tushare license terms independently before redistributing derived series.
- Missing/undated index, sector, and stock evidence produces unknown; it does
  NOT produce scores of zero. Each year logs sample coverage.
- Non-publication/revisions of any vendor historical series may still create
  vendor lookahead not detected by these scripts; do not claim perfect PIT.

## Temporal evaluation
Frozen (NOT optimized on historical outcomes). Report:
1. Full available years 2015–2026 (2026 through latest completed session).
2. Earlier chronology before 2024-01-01.
3. 2024-01-01 onward time-held-out window.
4. Independent post-2021 SW2021-taxonomy window (2022 onward).
5. Per-year returns and drawdowns, transitions, unknowns, active breadth counts.

The '2024+' window is chronologically withheld from parameter fitting, but
the original V2.0a thresholds were drafted in 2026 with historical knowledge:
this is NOT blinded or preregistered out-of-sample validation. Future 2027+
records can establish genuine forward holdout.

## Execution
GitHub Actions on branch `research/v2-historical-backtest-20261122`:
`.github/workflows/v2-historical-validation.yml`
- Runs regression tests; fans out 2015..2026 with one simultaneous year to respect
  API use and avoid concurrent credentials/resource exhaustion.
- Uploads aggregate daily year shards as ephemeral artifacts, merges and evaluates,
  uploads full report and commits only small report to research branch.
- If any year lacks 75% fully scored trading days, fail that year's job. The
  final evaluation explicitly labels result partial, never invents absent periods.
- No production main changes; PR remains draft until validation has been reviewed.

This is an execution plan and code implementation. A full historical result exists
only AFTER a successful Actions execution and independently examined outputs.
