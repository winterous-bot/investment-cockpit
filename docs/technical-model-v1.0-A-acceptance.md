# V1.0-A engineering acceptance
Approved 2026-11-28 (Beijing). Tested commit 0da94f9c8393bc298b83ec8aeb322f4947281229, run https://github.com/winterous-bot/investment-cockpit/actions/runs/46088686806. 20/20 unit tests, 9/9 public sample/date reports, 9/9 exact prefix checks, 3/3 stale benchmark guards, full four-index coverage. No predictive validation. Directional weights T/M/V/R=55/20/10/15; short D/W/M=65/25/10, medium=25/50/25; preserve all A code/thresholds.
Backlog (not fixes in B):
1. Discrete trend saturation (e.g. CATL -100): compare continuous ATR/volatility-normalized variant in E, keep baseline.
2. Mechanical level selection: C must validate touch/rejection, age, confluence, role reversal and extreme near-price RR (SPD 0.04, CATL 0.03).
3. Reversal coverage: all nine samples no confirmation; investigate gradual bearish-range-bullish, V bottoms, false breaks and top reversals; explicit actual event and negative cases before D/E acceptance.
4. Fixed RS thresholds vs heterogeneous volatility: compare normalized alternative in E; no tuning on nine samples.
All nine action results remained evidence insufficient context. A's acceptance is computational and qualitative, not forecast efficacy.
