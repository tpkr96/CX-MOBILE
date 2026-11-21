# India bot: pass rules, written before any NSE/BSE backtest result (21 Nov 2026)

These rules were written while the data download was still running, before a single result existed. They are not changed after seeing results. Every parameter is carried over from the crypto bot (v7 / m1.6). Nothing is tuned on Indian data, so the whole Indian history counts as out-of-sample for these settings.

## Strategies under test

**A. Breakout (the port of the crypto 4h Donchian, which passed m1.6).** Donchian N=55 on closes beyond the prior 55-bar high or low. Initial stop 2 × ATR(14), trailing stop 5 × ATR, max hold 30 days. Entry at the next bar's open. Tested on two bar sizes, because NSE has no 4h bar:
- **A1 daily bars**, about 20 years. This is the main test.
- **A2 60-minute bars**, about 2 years. 55 hourly bars is about 9 trading days, close to the crypto lookback in wall-clock time.

Two ways to trade it:
- **Futures (long and short).** Index futures (Nifty, BankNifty, FinNifty, Midcap Nifty, Sensex, Bankex, using index spot as a proxy) and stock futures. Positions are held overnight (NRML/MARGIN).
- **Cash delivery, long only (CNC).** The small-capital route, with zero brokerage on Dhan.

**B. 360° scanner (the port of the crypto scanner, which lost money on crypto).** 5-minute bars, 60 days. The scanner's own code paths are used for the score (momentum z over 3 bars, volume spike, breakout/VWAP). Taker flow, order book and funding are missing from the history, so those weights drop out and the rest are re-normalised, the same way the crypto backtest handled it. Settings: entry at |score| ≥ 60; mood from Nifty vs VWAP, Nifty 60-minute direction and breadth; stop 2 × ATR within a 0.3–3% band; charges lock at 2 × the cost; trail gives back 40%; EMA9 fade; time stop 30 min; max hold 120 min; cooldown 10 min; max 4 trades per stock per day; edge gate (expected move ≥ 2 × the cost). No entries before 09:45 or after 14:45, and every position is flat by 15:15 IST. Traded as equity intraday (MIS).

## Costs (Dhan, November 2026)

| Item | Equity intraday | Equity delivery | Futures | Options (app only) |
|---|---|---|---|---|
| Brokerage | min(₹20, 0.03%) per order | ₹0 | min(₹20, 0.03%) per order | ₹20 per order |
| STT | 0.025% on the sell side | 0.1% on both sides | 0.05% on the sell side (from 1 Apr 2026) | 0.15% of premium on the sell side (from 1 Apr 2026) |
| Exchange fee (NSE) | 0.00297% | 0.00297% | 0.00173% | 0.03503% of premium |
| SEBI fee | ₹10 per crore | ₹10 per crore | ₹10 per crore | ₹10 per crore |
| Stamp duty (buy side) | 0.003% | 0.015% | 0.002% | 0.003% |
| GST | 18% on brokerage + exchange + SEBI | same | same | same |
| Slippage per fill | 0.03% | 0.05% | index 0.02%, stock 0.05% | n/a |

Brokerage in R terms is computed on the notional of one lot (futures) or ₹1 lakh (cash). DP charges on delivery sells (about ₹13–20 per scrip) are added as ₹16 on ₹1 lakh notional.

## Pass rules (same ten as m1.6, adapted where crypto-specific)

| # | Rule |
|---|---|
| C1 | Trades ≥ 100 |
| C2 | Net expectancy > 0 R after all costs |
| C3 | Profit factor ≥ 1.15 |
| C4 | Bootstrap 95% lower bound of expectancy > 0 R |
| C5 | Still > 0 R with costs and slippage doubled |
| C6 | Still > 0 R with every entry one bar late |
| C7 | > 0 R in both halves of the period (replaces the crypto delisted-coin universe test; see the survivorship caveat) |
| C8 | > 0 R in at least 2 of 3 Nifty regimes (trailing 120-trading-day Nifty return above +10% = bull, below −10% = bear, otherwise sideways) |
| C9 | Max drawdown ≤ 30% at 0.5% risk per trade, max 3 open positions |
| C10 | Sharpe ratio ≥ 0.5 (daily equity, annualised) |

**PASS = all ten.** A strategy that passes still needs a forward paper run of at least 30 closed trades before any real-money discussion. Live trading stays locked in the code either way.

**Known bias, stated in advance:** the stock list is today's large caps. Stocks that fell out of the index in the past 20 years are missing, which flatters long-side results. Index futures results do not have this bias, so they are reported separately and given more weight.
