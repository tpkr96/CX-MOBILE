# India Bot (NSE + BSE on Dhan): build and real-data backtest

21 November 2026 · version in1.0 · paper mode only, live trading locked

## 1. Result first

**Neither engine of the crypto bot makes money on the Indian market after charges.** I tested 7 configurations on real NSE/BSE history. None passed the 10 pre-registered checks; the best passed 4 of 10.

| Configuration | Trades | Win % | Net per trade (R) | Profit factor | 95% range (R) | Checks passed |
|---|---|---|---|---|---|---|
| A1 Breakout, daily, index futures (2000–2026) | 593 | 35.9 | +0.013 | 1.02 | −0.126 to +0.159 | 3/10 |
| A1 Breakout, daily, stock futures | 9,213 | 38.6 | −0.001 | 1.00 | −0.060 to +0.077 | 1/10 |
| **A1 Breakout, daily, cash delivery, long only** | 5,865 | 41.0 | **+0.034** | 1.06 | −0.006 to +0.073 | **4/10** |
| A2 Breakout, 60-min, index futures (Dec 2023–Nov 2026) | 560 | 25.5 | −0.298 | 0.64 | −0.433 to −0.158 | 1/10 |
| A2 Breakout, 60-min, stock futures | 5,981 | 26.8 | −0.113 | 0.85 | −0.165 to −0.062 | 2/10 |
| A2 Breakout, 60-min, cash delivery, long only | 3,022 | 27.3 | −0.121 | 0.86 | −0.200 to −0.046 | 2/10 |
| B 360° Scanner, 5-min, equity intraday (25 Aug–20 Nov 2026) | 2,248 | 40.4 | **−0.282** | 0.35 | −0.315 to −0.252 | 1/10 |

R = the amount risked on a trade. +0.034 R means that, on average, a trade risking ₹100 made ₹3.40 after charges.

**What this means**
- **360° Scanner: no edge at all.** Before charges, the average trade made +0.019% of the price. Intraday charges plus slippage cost 0.142% per round trip, about 7 times the move it catches. It loses in every slice and gets worse with late entry or double costs. This matches the crypto result, where the scanner also lost.
- **Breakout: about break-even, not a winner.** The daily version made a little before charges (+0.03 to +0.10 R). Charges took most or all of it. Entering one day late or doubling costs makes every version negative, so the small plus is fragile.
- **Breakout on 60-minute bars loses clearly.** The crypto version worked on 4-hour bars that run 24×7. Indian sessions are 6¼ hours with an overnight gap, which breaks it.
- **The only slightly positive line, cash delivery long only, is flattered.** The stock list is today's large caps (survivorship bias), and on a portfolio it still lost money: −1.2% a year, with a 37% drawdown at 0.5% risk per trade.

**Decision:** live trading stays locked. Paper mode can run on Dhan Cloud so you can watch it work, but please don't put money behind either engine.

## 2. What was built

`stocks/india/dhan_cloud/main.py` + `requirements.txt` is a single-file Python 3.11 bot for **Dhan Cloud**.

- **Markets:** NSE and BSE cash, NSE stock futures, and index futures for Nifty, BankNifty, FinNifty and Midcap Nifty (NSE) and Sensex and Bankex (BSE). Security IDs, lot sizes and expiries come from Dhan's public scrip master each morning, so lot-size changes are picked up automatically.
- **Liquidity filter:** 20-day average turnover of at least ₹50 crore, and the scanner skips a stock when the live spread is above 0.10%.
- **Engine A, Breakout:** Donchian 55, stop 2 × ATR, trailing 5 × ATR, max 30 days. Open positions are rebuilt each morning by replaying the rules, so nothing has to be saved between Cloud runs.
- **Engine B, 360° Scanner:** the crypto score (momentum, volume spike, breakout/VWAP), Nifty mood (VWAP side, 60-min direction, breadth, volatility pause), chase and edge gates, the charges lock, 40% give-back trail, EMA9 fade, 30-min time stop, and flat by 15:15 IST.
- **Dhan specifics:**
  - Orders are built as v2 **Super Orders** (entry + target + stop-loss, with `trailingJump`), and stop moves as STOP_LOSS_LEG modifications.
  - The order throttle runs at 8/s, 200/min, 900/h and 5,000/day, under Dhan's limits of 10/s, 250/min, 1,000/h and 7,000/day.
  - Data calls are kept under 5/s and quotes under 1/s.
- **Charges:** full Indian charges (brokerage, STT at the April 2026 rates, exchange fee, SEBI fee, stamp duty, GST, DP charge) are applied to every paper trade.
- **Safety:**
  - `LIVE_LOCKED = True` is a constant, and the broker refuses to send. It only logs "PAPER would send …".
  - The access token comes from Dhan Cloud or from environment variables. It is never written to a file or a log.
  - Risk limits: 0.5% risk per trade, at most 3 open positions, a 3% daily loss stop and a 20% kill switch.
- **Extra modes:**
  - `python main.py --selftest` passes 11/11 offline.
  - `python main.py --backtest dhan` reruns the same tests on Dhan's own history (5 years of 5-minute data). On test data it gives the same scanner result as the separate backtest script.

### How to put it on Dhan Cloud (you do this; it needs your sign-in)
1. Open cloud.dhanhq.co/editor and create a Python project.
2. Paste `main.py` and add `requirements.txt`.
3. Schedule it for weekdays, starting 09:10 and auto-stopping 15:35 IST. Each run is under Dhan's 10-hour limit.
4. Read the Live logs. Every decision, blocked signal and paper trade is printed, and at the end there's a `JOURNAL_JSON` line with the day's trades.

Unverified until you run it there:
- how Dhan Cloud exposes credentials to the script (main.py tries Dhan's client first, then environment variables)
- the exact scrip-master column names on the day
- whether the Data API subscription is active on your account

## 3. How it was tested

- **Pass rules first:** `PREREGISTERED_CRITERIA.md` was written before any result. Every setting was carried over from the crypto bot unchanged, so all Indian history is unseen data for these settings.
- **Data:** Yahoo Finance's public chart data, downloaded on your PC (21 Nov 2026), with SHA-256 checksums in the manifests:
  - daily bars for 4 indices and about 70 large F&O stocks (from 2000, or from 2007 for indices)
  - 60-minute bars for 2 years
  - 5-minute bars for 60 days
- **Costs per round trip** (charges plus slippage): index futures 0.10%, stock futures 0.16%, delivery 0.34%, intraday 0.14%.
- **Fills:** entry at the next bar's open. A stop is filled at the stop price, or at the open if the price gapped past it.
- **Gaps and limits**, stated honestly:
  - Index futures were tested on index spot prices.
  - FinNifty and Bankex had no daily history.
  - BSE stock tickers duplicate NSE prices.
  - The scanner had only 60 days of 5-minute data, but its loss is so large and consistent that more data would not rescue it.
  - Portfolio drawdowns count closed trades only.

Run record: `backtest/results/RUN_RECORD.md`. Full trade files are on your PC in `CTT\india\results_india`.

## 4. What could actually work (suggestions, not tested)

1. **Lower the cost per trade relative to the move.** Indian intraday charges (about 0.14%) are bigger than the scanner's average move. Any intraday idea needs average moves of 0.5% or more per trade.
2. **Hold longer.** Only the daily breakout came near break-even. A weekly-bar trend system on index futures, or a monthly momentum rotation in delivery (where brokerage is ₹0), fits Indian costs better. Either one needs its own pre-registered test.
3. **Options selling** is the other common Indian approach. It has a different risk profile, with large rare losses, and would need option-chain history (Dhan has expired-options data).

If you want, I can pre-register and test option 2 next, on the same data.
