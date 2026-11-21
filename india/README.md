# India Bot (NSE + BSE, paper)

A port of the CX crypto bot to the Indian market, built 21 Nov 2026.

- **Phone app:** https://tpkr96.github.io/CX-MOBILE/india/
  - Runs the 360° scanner on Dhan's live market feed (WebSocket), with paper trades and full Indian charges.
  - Your access token stays in the tab's memory only.
  - The app contains no order code.
- **Dhan Cloud bot:** `dhan_cloud/main.py` + `requirements.txt`. Paste them into cloud.dhanhq.co/editor and schedule weekdays 09:10–15:35 IST.
  - Covers both engines (Breakout and 360° Scanner), NSE and BSE, cash and F&O.
  - Uses Super Orders with a trailing stop.
  - Paper only: `LIVE_LOCKED` is a constant.
- **Real-data backtest:** `INDIA_BOT_REPORT.md`, with the pass rules in `PREREGISTERED_CRITERIA.md` and the run in `backtest/`.
  - **No version passed.** The scanner lost −0.28 R per trade after charges, and the daily breakout was about break-even.
  - Live trading stays locked.
- **Tests:**
  - `node tests/app_test.js` (mock Dhan feed, fast clock) passes 12/12.
  - `python dhan_cloud/main.py --selftest` passes 11/11.
