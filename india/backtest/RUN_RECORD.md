# Run record, 21 Nov 2026

- Script: backtest/bt_india.py (identical copy written to C:\Users\thavi\Desktop\CTT\india\bt_india.py and run there).
- Python 3 on Prashanth's PC, pandas 3.1.0, numpy 2.5.4. Command: `python bt_india.py data_india results_india`.
- Data: CTT\india\data_india (Yahoo Finance chart API, downloaded 21 Nov 2026; MANIFEST.txt and MANIFEST_DAILY.txt hold SHA-256 per file).
  Daily: 78 files (indices from 2007, stocks from 2000 or listing). 60m: ~2 years (Dec 2023 to Nov 2026). 5m: 25 Aug to 20 Nov 2026.
  Missing: FINNIFTY and BANKEX daily (no Yahoo daily history), TATAMOTORS (renamed), BSE (.BO) stock tickers (no daily history; same prices as .NS).
- Full results.json and trades_*.csv stay on the PC in CTT\india\results_india (too large to copy; the cloud cannot pull files from the PC).
- Console output and the summary numbers below were copied back verbatim.

## Console
A1_daily_fut_index        n 593   win 35.9%  expR +0.013  PF 1.02  CI95 [-0.126, +0.159]  passed 3/10
A1_daily_fut_stocks       n 9213  win 38.6%  expR -0.001  PF 1.00  CI95 [-0.060, +0.077]  passed 1/10
A1_daily_cnc_stocks_long  n 5865  win 41.0%  expR +0.034  PF 1.06  CI95 [-0.006, +0.073]  passed 4/10
A2_60m_fut_index          n 560   win 25.5%  expR -0.298  PF 0.64  CI95 [-0.433, -0.158]  passed 1/10
A2_60m_fut_stocks         n 5981  win 26.8%  expR -0.113  PF 0.85  CI95 [-0.165, -0.062]  passed 2/10
A2_60m_cnc_stocks_long    n 3022  win 27.3%  expR -0.121  PF 0.86  CI95 [-0.200, -0.046]  passed 2/10
B_scanner_5m_MIS          n 2248  win 40.4%  expR -0.282  PF 0.35  CI95 [-0.315, -0.252]  passed 1/10

## Per index (A1 daily, index futures): trades, net R per trade
Sensex 191 +0.044 · BankNifty 129 +0.057 · Nifty 141 −0.171 · Midcap Nifty 132 +0.120
## Per index (A2 60-min, index futures)
Bankex 92 −0.367 · FinNifty 93 −0.301 · Sensex 94 −0.365 · BankNifty 91 −0.258 · Nifty 99 −0.420 · Midcap Nifty 91 −0.062
## Stocks (A1 daily, futures): 33 of 75 positive; best BEL +1.664 (136), TVSMOTOR +0.594, ADANIENT +0.431; worst POWERGRID −0.482, IOC −0.471.
## Other detail
Scanner exits: time 969, trail 873, stop 364, fade 25, maxhold 9, exitby 8. Blocked: mood 1005, vol_pause 220, chase 120, edge 89. Avg gross move +0.019% vs cost 0.142%.
Daily delivery long-only portfolio (0.5% risk, max 3 open): final equity 0.79×, CAGR −1.22%, max DD −36.9%, Sharpe −0.31.
Daily index futures portfolio: 0.97×, CAGR −0.16%, max DD −23.4%. Longs +0.125 R, shorts −0.202 R.
