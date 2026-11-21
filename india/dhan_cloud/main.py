"""
India Bot for Dhan Cloud: NSE + BSE port of the CX crypto bot (v7).
Version in1.0 (21 Nov 2026).

WHAT IT DOES
  Engine A  "Breakout"   : Donchian 55-bar breakout, stop 2 x ATR(14), trailing stop 5 x ATR, max hold 30 days.
                           Daily bars. Signals from yesterday's close, entry at today's open. Index futures, stock futures or
                           cash delivery (long only). Open positions are rebuilt every morning by replaying the rules over
                           the last 200 daily bars, so nothing needs to be saved between runs.
  Engine B  "360 Scanner": 5-minute multi-factor score (momentum, volume spike, breakout/VWAP), entry at |score| >= 60 when
                           the Nifty mood agrees, stop 2 x ATR (0.3-3%), charges lock at 2 x costs, trail gives back 40%,
                           EMA9 fade, 30-min time stop, flat by 15:15 IST. Equity intraday.

SAFETY
  * PAPER MODE ONLY. LIVE_LOCKED is a constant in this file. No setting, environment variable or argument can switch it off.
    The Dhan order payloads are built and logged ("PAPER would send ...") but never sent.
  * Access token: read at run time from Dhan Cloud's own client or from environment variables. Never written to disk or logs.
  * Order throttle matches Dhan's limits with headroom: 8 orders/s, 200/min, 900/h, 5000/day.

RUN
  Dhan Cloud : upload main.py + requirements.txt, schedule weekdays 09:10 -> 15:35 IST.  `python main.py`
  Backtest   : `python main.py --backtest dhan`  (5 yrs of Dhan 5-min + daily history, needs the Data API)
               `python main.py --backtest csv <dir>` (CSV folders 1d/ and 5m/ as made by tools/download_india.js)
  Self-test  : `python main.py --selftest`  (no network)
"""
import os, sys, time, json, math, io, datetime as dt
from collections import deque

import numpy as np
import pandas as pd

VERSION = "in1.0"
LIVE_LOCKED = True          # hard lock: real orders are impossible in this build
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
API = "https://api.dhan.co/v2"
SCRIP_MASTER = "https://images.dhan.co/api-data/api-scrip-master.csv"

# ----------------------------------------------------------------------------------------------------------------------
# SETTINGS (edit here)
# ----------------------------------------------------------------------------------------------------------------------
CFG = dict(
    capital=100000,            # paper capital in rupees
    risk_pct=0.5,              # % of equity at risk per trade (both engines)
    max_open=3,                # max open positions per engine
    daily_loss_pct=3.0,        # stop new entries for the day after this loss
    kill_pct=20.0,             # stop the bot entirely below this drawdown
    engines=["breakout", "scanner"],
    breakout_route="futures",  # "futures" (long+short, needs F&O margin) or "cnc" (cash delivery, long only)
    # universe
    index_futures=[("NSE", "NIFTY"), ("NSE", "BANKNIFTY"), ("NSE", "FINNIFTY"), ("NSE", "MIDCPNIFTY"),
                   ("BSE", "SENSEX"), ("BSE", "BANKEX")],
    stocks=["RELIANCE", "HDFCBANK", "ICICIBANK", "INFY", "TCS", "BHARTIARTL", "ITC", "LT", "SBIN", "AXISBANK", "KOTAKBANK",
            "HINDUNILVR", "BAJFINANCE", "M&M", "MARUTI", "SUNPHARMA", "HCLTECH", "NTPC", "TITAN", "ULTRACEMCO", "POWERGRID",
            "ASIANPAINT", "ONGC", "TATASTEEL", "ADANIENT", "ADANIPORTS", "COALINDIA", "BAJAJFINSV", "JSWSTEEL", "WIPRO",
            "TECHM", "HINDALCO", "CIPLA", "DRREDDY", "EICHERMOT", "BEL", "TRENT", "HEROMOTOCO", "APOLLOHOSP", "BPCL",
            "TATAPOWER", "DLF", "HAL", "BANKBARODA", "VEDL", "TVSMOTOR", "INDIGO", "PFC", "RECLTD", "GAIL"],
    stock_exchange="NSE",      # "NSE" or "BSE" for the cash leg; F&O follows the exchange that lists the contract
    min_turnover_cr=50.0,      # liquidity filter: 20-day average daily turnover in crore rupees
    max_spread_pct=0.10,       # scanner skips a stock if the live bid-ask spread is wider than this
    # scanner (same numbers as the crypto bot where they exist)
    scan=dict(scanMin=60, look=3, atrN=14, atrK=2, minStopPct=0.3, maxStopPct=3, lockMult=2, lockBuf=0.02, giveBack=40,
              fadeEma=9, timeStop=30, maxHold=120, cooldown=10, maxPerDay=4, chaseZ=2.5, edgeMult=2, moodBrHi=60,
              moodBrLo=40, volPause=3, wMom=30, wVol=15, wBrk=20, tf=5, start="09:45", cutoff="14:45", exitBy="15:15"),
    breakout=dict(N=55, ks=2.0, kt=5.0, maxHoldDays=30),
    slippage=dict(fut_idx=0.0002, fut_stk=0.0005, cnc=0.0005, mis=0.0003),
)

# ----------------------------------------------------------------------------------------------------------------------
# CHARGES (Dhan, Nov 2026). Returns rupees for one round trip of `notional` rupees on each side.
# ----------------------------------------------------------------------------------------------------------------------
def charges(kind, buy_val, sell_val, exch="NSE"):
    """kind: 'mis' equity intraday, 'cnc' equity delivery, 'fut' futures, 'opt' options (values = premium turnover)"""
    if kind == "mis":
        brok = min(20, 0.0003 * buy_val) + min(20, 0.0003 * sell_val); stt = 0.00025 * sell_val
        ex = 0.0000297 * (buy_val + sell_val) if exch == "NSE" else 0.0000375 * (buy_val + sell_val); stamp = 0.00003 * buy_val; dp = 0
    elif kind == "cnc":
        brok = 0; stt = 0.001 * (buy_val + sell_val)
        ex = 0.0000297 * (buy_val + sell_val) if exch == "NSE" else 0.0000375 * (buy_val + sell_val); stamp = 0.00015 * buy_val; dp = 16
    elif kind == "fut":
        brok = min(20, 0.0003 * buy_val) + min(20, 0.0003 * sell_val); stt = 0.0005 * sell_val
        ex = 0.0000173 * (buy_val + sell_val) if exch == "NSE" else 0.0; stamp = 0.00002 * buy_val; dp = 0
    elif kind == "opt":
        brok = 40; stt = 0.0015 * sell_val
        ex = 0.0003503 * (buy_val + sell_val) if exch == "NSE" else 0.000325 * (buy_val + sell_val); stamp = 0.00003 * buy_val; dp = 0
    else:
        raise ValueError(kind)
    sebi = 1e-6 * (buy_val + sell_val)
    gst = 0.18 * (brok + ex + sebi)
    return dict(brokerage=brok, stt=stt, exchange=ex, sebi=sebi, stamp=stamp, dp=dp, gst=gst,
                total=brok + stt + ex + sebi + stamp + dp + gst)

def cost_frac(kind, notional, slip, exch="NSE"):
    """round-trip charges + slippage as a fraction of notional"""
    return charges(kind, notional, notional, exch)["total"] / notional + 2 * slip

# ----------------------------------------------------------------------------------------------------------------------
# ENGINES (pure functions on OHLCV DataFrames indexed by IST time; same code is used live, in paper and in backtests)
# ----------------------------------------------------------------------------------------------------------------------
def atr(b, n=14):
    pc = b.c.shift()
    return pd.concat([b.h - b.l, (b.h - pc).abs(), (b.l - pc).abs()], axis=1).max(axis=1).rolling(n).mean()

def breakout_trades(b, cf, N=55, ks=2.0, kt=5.0, maxhold=pd.Timedelta("30D"), late=0, longonly=False, keep_open=False):
    """Donchian breakout. Returns closed trades; with keep_open=True the last still-open trade is returned with exit=None."""
    a = atr(b); up = b.h.rolling(N).max().shift(); dn = b.l.rolling(N).min().shift()
    idx = b.index; O, H, L, C = b.o.values, b.h.values, b.l.values, b.c.values; A = a.values; U = up.values; Dn = dn.values
    out = []; n = len(b); busy = -1
    for t in range(n - 1):
        if t <= busy or np.isnan(A[t]) or np.isnan(U[t]): continue
        d = 1 if C[t] > U[t] else (-1 if C[t] < Dn[t] else 0)
        if d == 0 or (longonly and d < 0): continue
        e = t + 1 + late
        if e >= n: break
        px = O[e]; stop = C[t] - d * ks * A[t]; k = kt * A[t]
        if (d > 0 and px <= stop) or (d < 0 and px >= stop): continue
        risk = abs(px - stop); hi = lo = px; ex = None; j = e; why = None
        tend = idx[e] + maxhold if maxhold is not None else None
        while j < n:
            if d > 0 and L[j] <= stop: ex = min(O[j], stop); why = "trail" if stop > px - risk + 1e-12 else "stop"; break
            if d < 0 and H[j] >= stop: ex = max(O[j], stop); why = "trail" if stop < px + risk - 1e-12 else "stop"; break
            if tend is not None and j + 1 < n and idx[j + 1] >= tend: ex = C[j]; why = "time"; break
            hi = max(hi, H[j]); lo = min(lo, L[j])
            stop = max(stop, hi - k) if d > 0 else min(stop, lo + k)
            j += 1
        if ex is None:
            if keep_open:
                out.append(dict(tin=idx[e], tout=None, d=d, entry=px, exit=None, stop=stop, init_stop=C[t] - d * ks * A[t],
                                risk=risk, trail_k=k, hi=hi, lo=lo, why="open"))
            break
        g = d * (ex - px)
        out.append(dict(tin=idx[e], tout=idx[j], d=d, entry=px, exit=ex, risk=risk, risk_pct=risk / px * 100,
                        gross_R=g / risk, R=(g - cf * px) / risk, cost_R=cf * px / risk, why=why))
        busy = j
    return out

def session_vwap(b, use_volume=True):
    tp = (b.h + b.l + b.c) / 3; day = b.index.normalize()
    if use_volume and b.v.sum() > 0:
        return (tp * b.v).groupby(day).cumsum() / b.v.groupby(day).cumsum().replace(0, np.nan)
    return tp.groupby(day).cumsum() / tp.groupby(day).cumcount().add(1)

def scan_features(b, S):
    """vectorised port of the crypto scanFeat + scanScore (flow, book and funding are unavailable on NSE history: weights re-normalised)"""
    vw = session_vwap(b); k = S["look"]; lr = np.log(b.c / b.c.shift())
    sd = lr.rolling(59, min_periods=20).std()
    ret = np.log(b.c / b.c.shift(k)); z = ret / (sd * math.sqrt(k))
    rv = b.v.rolling(k).mean() / b.v.shift(k).rolling(60 - k + 1, min_periods=10).mean().replace(0, np.nan)
    hi = b.h.shift().rolling(60, min_periods=20).max(); lo = b.l.shift().rolling(60, min_periods=20).min()
    pc = b.c.shift(); tr = pd.concat([b.h - b.l, (b.h - pc).abs(), (b.l - pc).abs()], axis=1).max(axis=1)
    at = tr.rolling(S["atrN"] - 1).mean()
    ema = b.c.ewm(span=S["fadeEma"], adjust=False).mean(); c = b.c
    brk = np.where((c > hi) & (c > vw), 1.0, np.where((c < lo) & (c < vw), -1.0, np.where(c > vw, 0.3, np.where(c < vw, -0.3, 0.0))))
    mom = (z / 3).clip(-1, 1); vol = np.sign(ret) * ((rv - 1) / 2).clip(0, 1)
    F = pd.DataFrame(dict(c=c, sd=sd, mom=mom, vol=vol, brk=brk, atr=at, ema=ema, vw=vw), index=b.index)
    F["score"] = 100 * (S["wMom"] * F.mom + S["wVol"] * F.vol.fillna(0) + S["wBrk"] * F.brk) / \
                 (S["wMom"] + S["wVol"] * F.vol.notna() + S["wBrk"])
    F.loc[F.vw.isna() | F.mom.isna() | F.atr.isna(), "score"] = np.nan
    return F

def nifty_mood(nifty, breadth, S):
    vw = session_vwap(nifty, use_volume=False)
    tV = np.sign(nifty.c - vw).fillna(0); tR = np.sign(nifty.c - nifty.c.shift(12)).fillna(0)
    br = breadth.reindex(nifty.index)
    tB = pd.Series(np.where(br >= S["moodBrHi"], 1, np.where(br <= S["moodBrLo"], -1, 0)), index=nifty.index)
    rng5 = nifty.h.rolling(5).max() - nifty.l.rolling(5).min()
    med = rng5.shift(5).rolling(60, min_periods=6).apply(lambda x: np.median(x[::5]), raw=True)
    spike = rng5 / med
    return pd.DataFrame(dict(bias=tV + tR + tB, pause=(spike > S["volPause"]).fillna(False), spike=spike, breadth=br))

def scan_gates(f, d, cost_pct, S):
    """entry safety gates from the crypto bot that apply on NSE (chase, edge). Returns the reason or None."""
    if f.vw > 0 and f.sd > 0:
        zc = math.log(f.c / f.vw) * d / (f.sd * math.sqrt(60 / S["tf"]))
        if zc > S["chaseZ"]: return "chase %.1f sigma beyond VWAP" % zc
    exp = f.atr / f.c * 100 * math.sqrt(max(1, S["timeStop"] / S["tf"]))
    if exp < S["edgeMult"] * cost_pct: return "expected move %.3f%% < %sx charges" % (exp, S["edgeMult"])
    return None

def scan_stop_dist(entry, atr_v, S):
    return min(max(S["atrK"] * atr_v, entry * S["minStopPct"] / 100), entry * S["maxStopPct"] / 100)

def scan_step(s, bar, cost_pct, S):
    """one completed 5-min bar for an open scanner trade (port of crypto scanStep). s: dict state. Returns (exit_px, why) or None."""
    d = s["d"]
    if (d > 0 and bar["l"] <= s["stop"]) or (d < 0 and bar["h"] >= s["stop"]):
        px = min(bar["o"], s["stop"]) if d > 0 else max(bar["o"], s["stop"])
        return px, ("trail" if s["trailed"] else "lock" if s["locked"] else "stop")
    s["peak"] = max(s["peak"], bar["h"]) if d > 0 else min(s["peak"], bar["l"]); s["n"] += 1
    fav = (s["peak"] / s["entry"] - 1) * d * 100
    if not s["locked"] and fav >= S["lockMult"] * cost_pct:
        s["locked"] = True; lv = s["entry"] * (1 + d * (cost_pct + S["lockBuf"]) / 100)
        if (d > 0 and lv > s["stop"]) or (d < 0 and lv < s["stop"]): s["stop"] = lv
    if s["locked"]:
        tr = s["peak"] - d * abs(s["peak"] - s["entry"]) * S["giveBack"] / 100
        if (d > 0 and tr > s["stop"]) or (d < 0 and tr < s["stop"]): s["stop"] = tr; s["trailed"] = True
    a = 2 / (S["fadeEma"] + 1); s["ema"] = s["ema"] + a * (bar["c"] - s["ema"])
    if s["locked"] and s["n"] >= 2 and ((d > 0 and bar["c"] < s["ema"]) or (d < 0 and bar["c"] > s["ema"])): return bar["c"], "fade"
    held = s["n"] * S["tf"]
    if not s["locked"] and held >= S["timeStop"]: return bar["c"], "time"
    if held >= S["maxHold"]: return bar["c"], "maxhold"
    return None

def hhmm(s): h, m = s.split(":"); return int(h) * 60 + int(m)

def scanner_trades(B, nifty, S, cf, late=0):
    """backtest of the scanner over a dict of 5-min DataFrames (IST index). Same decisions as the live loop."""
    FS = {s: scan_features(b, S) for s, b in B.items()}
    above = pd.concat({s: (F.c > F.vw).astype(float).where(F.vw.notna()) for s, F in FS.items()}, axis=1)
    M = nifty_mood(nifty, above.mean(axis=1) * 100, S)
    cost_pct = cf * 100; out = []; blocked = {}
    t0, t1, tx = hhmm(S["start"]), hhmm(S["cutoff"]), hhmm(S["exitBy"])
    for s, b in B.items():
        F = FS[s]; idx = b.index; O, H, L, C = b.o.values, b.h.values, b.l.values, b.c.values; n = len(b)
        tmin = idx.hour * 60 + idx.minute; i = 0; last = None; cnt = {}
        while i < n - 1 - late:
            t = idx[i]; endm = tmin[i] + S["tf"]; sc = F.score.iat[i]
            if np.isnan(sc) or endm < t0 or endm > t1: i += 1; continue
            if last is not None and last.normalize() == t.normalize() and (t - last).total_seconds() < S["cooldown"] * 60: i += 1; continue
            d = 1 if sc >= S["scanMin"] else (-1 if sc <= -S["scanMin"] else 0)
            if not d: i += 1; continue
            last = t; f = F.iloc[i]; why = None
            m = M.loc[t] if t in M.index else None
            if m is None or np.isnan(m.bias): why = "mood_na"
            elif m.pause: why = "vol_pause"
            elif not ((d > 0 and m.bias >= 1) or (d < 0 and m.bias <= -1)): why = "mood"
            if why is None:
                g = scan_gates(f, d, cost_pct, S)
                if g: why = "chase" if g.startswith("chase") else "edge"
            dk = t.normalize()
            if why is None and cnt.get(dk, 0) >= S["maxPerDay"]: why = "per_day"
            if why: blocked[why] = blocked.get(why, 0) + 1; i += 1; continue
            cnt[dk] = cnt.get(dk, 0) + 1; e = i + 1 + late
            if idx[e].normalize() != dk: i += 1; continue
            px = O[e]; R = scan_stop_dist(C[i], f.atr, S); stop = C[i] - d * R
            if (d > 0 and px <= stop) or (d < 0 and px >= stop): i += 1; continue
            st = dict(d=d, entry=px, stop=stop, peak=px, locked=False, trailed=False, ema=f.ema, n=0); risk = abs(px - stop)
            j = e; ex = None
            while j < n:
                if idx[j].normalize() != dk: j -= 1; ex, wx = C[j], "eod"; break
                r = scan_step(st, dict(o=O[j], h=H[j], l=L[j], c=C[j]), cost_pct, S)
                if r: ex, wx = r; break
                if tmin[j] + S["tf"] >= tx: ex, wx = C[j], "exitby"; break
                j += 1
            if ex is None: break
            g = d * (ex - px)
            out.append(dict(sym=s, tin=idx[e], tout=idx[j], d=d, entry=px, exit=ex, risk_pct=risk / px * 100, gross_R=g / risk,
                            R=(g - cf * px) / risk, cost_R=cf * px / risk, why=wx, score=round(float(sc), 1)))
            i = j + 1
    return pd.DataFrame(out), blocked

# ----------------------------------------------------------------------------------------------------------------------
# DHAN CONNECTION (data + order payloads). Token from Dhan Cloud's client or env vars; never stored.
# ----------------------------------------------------------------------------------------------------------------------
class RateLimiter:
    def __init__(self, limits):  # limits: list of (count, seconds)
        self.limits = limits; self.q = deque()
    def wait(self):
        while True:
            now = time.time()
            while self.q and now - self.q[0] > max(s for _, s in self.limits): self.q.popleft()
            ok = all(sum(1 for t in self.q if now - t < sec) < cnt for cnt, sec in self.limits)
            if ok: self.q.append(now); return
            time.sleep(0.05)

class Dhan:
    def __init__(self):
        self.client_id, self.token = self._creds()
        import requests
        self.http = requests.Session()
        self.data_rl = RateLimiter([(4, 1.0)])                                         # Dhan data APIs: 5/s
        self.quote_rl = RateLimiter([(1, 1.05)])                                       # quote APIs: 1/s
        self.order_rl = RateLimiter([(8, 1.0), (200, 60.0), (900, 3600.0), (5000, 86400.0)])  # Dhan: 10/s, 250/min, 1000/h, 7000/day

    @staticmethod
    def _creds():
        try:  # Dhan Cloud runtime: credentials are already in scope
            from dhan_client import DhanClient  # type: ignore
            c = DhanClient()
            cid = getattr(c, "client_id", None) or getattr(c, "dhan_client_id", None)
            tok = getattr(c, "access_token", None) or getattr(c, "token", None)
            if cid and tok: return str(cid), str(tok)
        except Exception:
            pass
        cid = os.environ.get("DHAN_CLIENT_ID"); tok = os.environ.get("DHAN_ACCESS_TOKEN")
        if not cid or not tok:
            raise SystemExit("No Dhan credentials: on Dhan Cloud they are provided automatically; elsewhere set DHAN_CLIENT_ID "
                             "and DHAN_ACCESS_TOKEN as environment variables (never in this file).")
        return cid, tok

    def _post(self, path, body, rl):
        rl.wait()
        for a in range(4):
            r = self.http.post(API + path, json=body, timeout=20,
                               headers={"access-token": self.token, "client-id": self.client_id, "Content-Type": "application/json"})
            if r.status_code == 429 or (r.status_code >= 500): time.sleep(1.5 * (a + 1)); continue
            if r.status_code != 200: raise RuntimeError("Dhan %s -> %s %s" % (path, r.status_code, r.text[:200]))
            return r.json()
        raise RuntimeError("Dhan %s: retries exhausted" % path)

    @staticmethod
    def _frame(j):
        if not j or not j.get("timestamp"): return None
        t = pd.to_datetime(j["timestamp"], unit="s", utc=True).tz_convert("Asia/Kolkata").tz_localize(None)
        return pd.DataFrame(dict(o=j["open"], h=j["high"], l=j["low"], c=j["close"], v=j["volume"]), index=t).sort_index()

    def daily(self, sid, seg, instr, frm, to, expiry_code=None):
        body = dict(securityId=str(sid), exchangeSegment=seg, instrument=instr, oi=False, fromDate=frm, toDate=to)
        if expiry_code is not None: body["expiryCode"] = expiry_code
        f = self._frame(self._post("/charts/historical", body, self.data_rl))
        if f is not None: f.index = f.index.normalize()
        return f

    def intraday(self, sid, seg, instr, frm, to, interval=5):
        """frm/to 'YYYY-MM-DD HH:MM:SS'; Dhan returns at most 90 days per call, so longer spans are chunked"""
        a = pd.Timestamp(frm); z = pd.Timestamp(to); parts = []
        while a < z:
            b = min(a + pd.Timedelta(days=89), z)
            f = self._frame(self._post("/charts/intraday", dict(securityId=str(sid), exchangeSegment=seg, instrument=instr,
                                                                 interval=str(interval), oi=False,
                                                                 fromDate=a.strftime("%Y-%m-%d %H:%M:%S"),
                                                                 toDate=b.strftime("%Y-%m-%d %H:%M:%S")), self.data_rl))
            if f is not None: parts.append(f)
            a = b
        if not parts: return None
        f = pd.concat(parts); return f[~f.index.duplicated(keep="last")]

    def quotes(self, by_seg):
        """by_seg: {'NSE_EQ': [sid,...]} -> {(seg,sid): {last_price, depth...}} via /marketfeed/quote (1 request/second)"""
        j = self._post("/marketfeed/quote", {k: [int(x) for x in v] for k, v in by_seg.items()}, self.quote_rl)
        out = {}
        for seg, d in (j.get("data") or {}).items():
            for sid, q in d.items(): out[(seg, str(sid))] = q
        return out

# Order payloads exactly as documented for DhanHQ v2 (super order = entry + target + stop-loss with trailing jump)
def super_order_payload(client_id, sec_id, seg, side, qty, product, price, target, stop, trail_jump, tag):
    return {"dhanClientId": client_id, "correlationId": tag[:30], "transactionType": side, "exchangeSegment": seg,
            "productType": product, "orderType": "MARKET" if price is None else "LIMIT", "securityId": str(sec_id),
            "quantity": int(qty), "price": float(price or 0), "targetPrice": round(float(target), 2),
            "stopLossPrice": round(float(stop), 2), "trailingJump": round(float(trail_jump), 2)}

def modify_sl_payload(client_id, order_id, stop, trail_jump=0):
    return {"dhanClientId": client_id, "orderId": str(order_id), "legName": "STOP_LOSS_LEG", "stopLossPrice": round(float(stop), 2),
            "trailingJump": round(float(trail_jump), 2)}

class Broker:
    """Paper broker. Real orders are impossible: LIVE_LOCKED is a constant and send() refuses unconditionally."""
    def __init__(self, dhan, log):
        self.dhan = dhan; self.log = log; self.sent_today = 0
    def send(self, method, path, payload):
        if self.dhan: self.dhan.order_rl.wait()  # keep paper pacing identical to what live would need
        self.sent_today += 1
        if LIVE_LOCKED:
            self.log("PAPER would send %s %s %s" % (method, path, json.dumps(payload)))
            return {"orderId": "PAPER-%d" % self.sent_today, "orderStatus": "PAPER"}
        raise RuntimeError("live trading is locked in this build")

# ----------------------------------------------------------------------------------------------------------------------
# INSTRUMENTS (Dhan scrip master: lot sizes, security ids, expiries)
# ----------------------------------------------------------------------------------------------------------------------
def load_master(path_or_url=SCRIP_MASTER):
    m = pd.read_csv(path_or_url, low_memory=False)
    m.columns = [c.strip() for c in m.columns]
    return m

def pick_instruments(m, cfg, today):
    """returns list of dicts: sym, exch, seg, sid, instr, lot, kind ('idx_fut'|'stk_fut'|'eq'|'idx')"""
    col = lambda *names: next((c for c in names if c in m.columns), None)
    EX, SEG, SID, INS, SYM, LOT, EXP, UND = (col("SEM_EXM_EXCH_ID"), col("SEM_SEGMENT"), col("SEM_SMST_SECURITY_ID"),
                                             col("SEM_INSTRUMENT_NAME"), col("SEM_TRADING_SYMBOL"), col("SEM_LOT_UNITS"),
                                             col("SEM_EXPIRY_DATE"), col("SM_SYMBOL_NAME"))
    out = []
    segmap = {("NSE", "E"): "NSE_EQ", ("BSE", "E"): "BSE_EQ", ("NSE", "D"): "NSE_FNO", ("BSE", "D"): "BSE_FNO", ("NSE", "I"): "IDX_I", ("BSE", "I"): "IDX_I"}
    exp = pd.to_datetime(m[EXP], errors="coerce") if EXP else None
    # index futures: nearest expiry on/after today
    for ex, name in cfg["index_futures"]:
        f = m[(m[EX] == ex) & (m[INS] == "FUTIDX") & (m[SYM].astype(str).str.startswith(name + "-"))].copy()
        if EXP: f = f[exp.loc[f.index] >= pd.Timestamp(today)]; f = f.assign(_e=exp.loc[f.index]).sort_values("_e")
        if len(f):
            r = f.iloc[0]; out.append(dict(sym=name, exch=ex, seg=segmap[(ex, "D")], sid=str(r[SID]), instr="FUTIDX", lot=int(float(r[LOT])),
                                           kind="idx_fut", tsym=str(r[SYM])))
    # stocks: cash leg and nearest stock future
    for s in cfg["stocks"]:
        ex = cfg["stock_exchange"]
        e = m[(m[EX] == ex) & (m[INS] == "EQUITY") & (m[SYM].astype(str) == s)]
        if len(e):
            out.append(dict(sym=s, exch=ex, seg=segmap[(ex, "E")], sid=str(e.iloc[0][SID]), instr="EQUITY", lot=1, kind="eq", tsym=s))
        f = m[(m[EX] == "NSE") & (m[INS] == "FUTSTK") & (m[SYM].astype(str).str.startswith(s + "-"))].copy()
        if EXP and len(f):
            f = f[exp.loc[f.index] >= pd.Timestamp(today)]; f = f.assign(_e=exp.loc[f.index]).sort_values("_e")
        if len(f):
            r = f.iloc[0]; out.append(dict(sym=s, exch="NSE", seg="NSE_FNO", sid=str(r[SID]), instr="FUTSTK", lot=int(float(r[LOT])),
                                           kind="stk_fut", tsym=str(r[SYM])))
    # Nifty index for the mood
    n = m[(m[INS] == "INDEX") & (m[SYM].astype(str).isin(["NIFTY", "Nifty 50", "NIFTY 50"]))]
    if len(n): out.append(dict(sym="NIFTY_INDEX", exch="NSE", seg="IDX_I", sid=str(n.iloc[0][SID]), instr="INDEX", lot=1, kind="idx", tsym="NIFTY"))
    return out

# ----------------------------------------------------------------------------------------------------------------------
# LIVE PAPER LOOP
# ----------------------------------------------------------------------------------------------------------------------
def now_ist(): return dt.datetime.now(IST).replace(tzinfo=None)

class Bot:
    def __init__(self, cfg):
        self.cfg = cfg; self.dhan = Dhan(); self.broker = Broker(self.dhan, self.log)
        self.equity = float(cfg["capital"]); self.day_pnl = 0.0; self.peak = self.equity
        self.open = {}; self.journal = []; self.halted = None

    def log(self, msg): print(now_ist().strftime("%H:%M:%S"), msg, flush=True)

    def size(self, entry, stop, lot):
        risk_rs = self.equity * self.cfg["risk_pct"] / 100
        per_lot = abs(entry - stop) * lot
        return int(risk_rs // per_lot) if per_lot > 0 else 0

    def book(self, key, px, why):
        p = self.open.pop(key); bv = (p["entry"] if p["d"] > 0 else px) * p["qty"]; sv = (px if p["d"] > 0 else p["entry"]) * p["qty"]
        ch = charges(p["kind"], bv, sv, p["exch"])["total"]
        pnl = p["d"] * (px - p["entry"]) * p["qty"] - ch
        self.equity += pnl; self.day_pnl += pnl; self.peak = max(self.peak, self.equity)
        self.journal.append(dict(key=key, engine=p["engine"], d=p["d"], qty=p["qty"], entry=p["entry"], exit=px, why=why, charges=round(ch, 2), pnl=round(pnl, 2)))
        self.log("PAPER EXIT %s %s qty %d @ %.2f (%s) net %.2f after charges %.2f | equity %.0f" % (key, "LONG" if p["d"] > 0 else "SHORT", p["qty"], px, why, pnl, ch, self.equity))
        if self.equity < self.peak * (1 - self.cfg["kill_pct"] / 100): self.halted = "kill switch"
        if self.day_pnl < -self.cfg["capital"] * self.cfg["daily_loss_pct"] / 100: self.halted = self.halted or "daily loss limit"

    def run(self):
        c = self.cfg; S = c["scan"]; today = now_ist().date()
        self.log("India Bot %s | PAPER (live locked) | engines %s | capital %.0f" % (VERSION, c["engines"], c["capital"]))
        m = load_master(); ins = pick_instruments(m, c, today)
        self.log("instruments: %d (%d index futures, %d stock futures, %d cash)" % (len(ins), sum(i["kind"] == "idx_fut" for i in ins),
                 sum(i["kind"] == "stk_fut" for i in ins), sum(i["kind"] == "eq" for i in ins)))
        frm = (today - dt.timedelta(days=420)).isoformat(); to = (today + dt.timedelta(days=1)).isoformat()
        daily = {}
        for i in ins:
            try:
                d = self.dhan.daily(i["sid"], i["seg"], i["instr"], frm, to, 0 if i["instr"].startswith("FUT") else None)
                if d is not None and len(d) > 60: daily[(i["kind"], i["sym"])] = (i, d[d.index.date < today])
            except Exception as ex: self.log("daily %s: %s" % (i["sym"], ex))
        # liquidity filter (20-day average turnover of the cash leg)
        liquid = set()
        for (k, s), (i, d) in daily.items():
            if k == "eq" and (d.c * d.v).tail(20).mean() / 1e7 >= c["min_turnover_cr"]: liquid.add(s)
        self.log("liquid stocks (>= Rs %.0f cr/day): %d" % (c["min_turnover_cr"], len(liquid)))
        if "breakout" in c["engines"]: self.morning_breakout(daily, liquid)
        if "scanner" in c["engines"]: self.scanner_loop(ins, liquid)
        self.log("session end | trades %d | day P&L %.2f | equity %.2f" % (len(self.journal), self.day_pnl, self.equity))
        print("JOURNAL_JSON " + json.dumps(self.journal), flush=True)

    def morning_breakout(self, daily, liquid):
        c = self.cfg; P = c["breakout"]; route = c["breakout_route"]; found = 0
        for (k, s), (i, d) in daily.items():
            if route == "futures" and k not in ("idx_fut", "stk_fut"): continue
            if route == "cnc" and k != "eq": continue
            if k != "idx_fut" and s not in liquid: continue
            # replay: positions still open as of yesterday's close, plus a fresh signal on yesterday's bar
            tr = breakout_trades(d, 0.0, P["N"], P["ks"], P["kt"], pd.Timedelta(days=P["maxHoldDays"]), longonly=(route == "cnc"), keep_open=True)
            op = [t for t in tr if t["exit"] is None]
            a = atr(d).iloc[-1]; up = d.h.rolling(P["N"]).max().shift().iloc[-1]; dn = d.l.rolling(P["N"]).min().shift().iloc[-1]; cl = d.c.iloc[-1]
            sig = 1 if cl > up else (-1 if cl < dn and route != "cnc" else 0)
            if op:
                t = op[0]; found += 1
                self.log("BREAKOUT holding %s %s since %s entry %.2f, stop now %.2f (trail %.2f)" % (s, "LONG" if t["d"] > 0 else "SHORT", str(t["tin"])[:10], t["entry"], t["stop"], t["trail_k"]))
            elif sig:
                stop = cl - sig * P["ks"] * a; qty_lots = self.size(cl, stop, i["lot"]); found += 1
                if qty_lots < 1:
                    self.log("BREAKOUT signal %s %s but 1 lot (%d) risks more than %.1f%% of capital: skipped" % (s, "LONG" if sig > 0 else "SHORT", i["lot"], c["risk_pct"])); continue
                product = "MARGIN" if k != "eq" else "CNC"
                pay = super_order_payload(self.dhan.client_id, i["sid"], i["seg"], "BUY" if sig > 0 else "SELL", qty_lots * i["lot"], product, None,
                                          cl + sig * 10 * P["ks"] * a, stop, 0, "BRK-%s" % s)
                self.broker.send("POST", "/super/orders", pay)
                self.log("BREAKOUT new %s %s %d lot(s) at open, stop %.2f, trail %.1f x ATR = %.2f" % (s, "LONG" if sig > 0 else "SHORT", qty_lots, stop, P["kt"], P["kt"] * a))
        self.log("breakout: %d positions / signals today" % found)

    def scanner_loop(self, ins, liquid):
        c = self.cfg; S = c["scan"]; eq = [i for i in ins if i["kind"] == "eq" and i["sym"] in liquid]; nif = next((i for i in ins if i["kind"] == "idx"), None)
        if not eq or not nif: self.log("scanner: no liquid stocks or no Nifty index: scanner off"); return
        cf = cost_frac("mis", 1e5, c["slippage"]["mis"]); cost_pct = cf * 100
        t_exit = hhmm(S["exitBy"]); last_bar = None; state = {}; cnt = {}; lastsig = {}
        while True:
            n = now_ist(); mins = n.hour * 60 + n.minute
            if mins >= 15 * 60 + 25 or self.halted == "kill switch": break
            if mins < 9 * 60 + 16 or n.minute % S["tf"] != 0 or n.second < 3 or last_bar == (n.hour, n.minute):
                time.sleep(1); continue
            last_bar = (n.hour, n.minute)
            frm = (n - dt.timedelta(days=5)).strftime("%Y-%m-%d 09:15:00"); to = n.strftime("%Y-%m-%d %H:%M:%S")
            B = {}
            for i in eq:
                try:
                    b = self.dhan.intraday(i["sid"], i["seg"], i["instr"], frm, to, S["tf"])
                    if b is not None: B[i["sym"]] = b[b.index + pd.Timedelta(minutes=S["tf"]) <= n]  # completed bars only
                except Exception as ex: self.log("5m %s: %s" % (i["sym"], ex))
            try: nb = self.dhan.intraday(nif["sid"], "IDX_I", "INDEX", frm, to, S["tf"]); nb = nb[nb.index + pd.Timedelta(minutes=S["tf"]) <= n]
            except Exception as ex: self.log("nifty 5m: %s" % ex); continue
            FS = {s: scan_features(b, S) for s, b in B.items() if len(b) > 30}
            if not FS: continue
            br = pd.concat({s: (F.c > F.vw).astype(float).where(F.vw.notna()) for s, F in FS.items()}, axis=1).mean(axis=1) * 100
            M = nifty_mood(nb, br, S); mood = M.iloc[-1]
            # manage open trades on the newest completed bar
            for s in list(state):
                b = B.get(s)
                if b is None or not len(b): continue
                bar = b.iloc[-1]; r = scan_step(state[s], dict(o=bar.o, h=bar.h, l=bar.l, c=bar.c), cost_pct, S)
                if r is None and mins >= t_exit: r = (bar.c, "exitby")
                if r: self.book(("scan", s), r[0], r[1]); state.pop(s)
                elif self.open[("scan", s)]["stop"] != state[s]["stop"]:
                    self.open[("scan", s)]["stop"] = state[s]["stop"]
                    self.broker.send("PUT", "/super/orders/{id}", modify_sl_payload(self.dhan.client_id, self.open[("scan", s)]["oid"], state[s]["stop"]))
            if self.halted or mins >= hhmm(S["cutoff"]) or mins < hhmm(S["start"]): continue
            ranked = sorted(((F.score.iat[-1], s) for s, F in FS.items() if not np.isnan(F.score.iat[-1])), key=lambda x: -abs(x[0]))
            for sc, s in ranked:
                if len([k for k in self.open if k[0] == "scan"]) >= c["max_open"]: break
                d = 1 if sc >= S["scanMin"] else (-1 if sc <= -S["scanMin"] else 0)
                if not d or s in state: continue
                if s in lastsig and (n - lastsig[s]).total_seconds() < S["cooldown"] * 60: continue
                lastsig[s] = n; F = FS[s]; f = F.iloc[-1]
                why = None
                if np.isnan(mood.bias): why = "mood unavailable"
                elif mood.pause: why = "Nifty volatility spike"
                elif not ((d > 0 and mood.bias >= 1) or (d < 0 and mood.bias <= -1)): why = "mood %+d does not allow %s" % (mood.bias, "longs" if d > 0 else "shorts")
                why = why or scan_gates(f, d, cost_pct, S)
                if not why and cnt.get(s, 0) >= S["maxPerDay"]: why = "per-stock daily limit"
                i = next(x for x in eq if x["sym"] == s)
                if not why:
                    try:
                        q = self.dhan.quotes({i["seg"]: [i["sid"]]}).get((i["seg"], i["sid"]), {})
                        dp = q.get("depth") or {}; bid = (dp.get("buy") or [{}])[0].get("price"); ask = (dp.get("sell") or [{}])[0].get("price")
                        if bid and ask and (ask - bid) / ((ask + bid) / 2) * 100 > c["max_spread_pct"]: why = "spread too wide"
                    except Exception as ex: self.log("quote %s: %s" % (s, ex))
                if why: self.log("SCAN blocked %s %s score %+.0f: %s" % (s, "long" if d > 0 else "short", sc, why)); continue
                entry = f.c; R = scan_stop_dist(entry, f.atr, S); stop = entry - d * R; qty = self.size(entry, stop, 1)
                qty = min(qty, int(self.equity * 5 // entry))  # MIS leverage cap 5x
                if qty < 1: continue
                cnt[s] = cnt.get(s, 0) + 1
                pay = super_order_payload(self.dhan.client_id, i["sid"], i["seg"], "BUY" if d > 0 else "SELL", qty, "INTRADAY", None,
                                          entry + d * 10 * R, stop, 0, "SCAN-%s" % s)
                res = self.broker.send("POST", "/super/orders", pay)
                state[s] = dict(d=d, entry=entry, stop=stop, peak=entry, locked=False, trailed=False, ema=f.ema, n=0)
                self.open[("scan", s)] = dict(engine="scan", d=d, qty=qty, entry=entry, stop=stop, kind="mis", exch=i["exch"], oid=res["orderId"])
                self.log("PAPER ENTRY 360 %s %s qty %d @ %.2f stop %.2f score %+.0f mood %+d" % (s, "LONG" if d > 0 else "SHORT", qty, entry, stop, sc, mood.bias))
        for k in [k for k in self.open if k[0] == "scan"]:
            self.book(k, self.open[k]["entry"], "session end (no fresh price)")

# ----------------------------------------------------------------------------------------------------------------------
# BACKTEST + SELF-TEST
# ----------------------------------------------------------------------------------------------------------------------
def summarise(df, label):
    if df is None or not len(df): return dict(label=label, n=0)
    R = df.R.values; w = R[R > 0].sum(); l = -R[R < 0].sum(); rng = np.random.default_rng(7)
    boot = [rng.choice(R, len(R)).mean() for _ in range(2000)]
    return dict(label=label, n=int(len(R)), win_pct=round(float((R > 0).mean() * 100), 1), expR=round(float(R.mean()), 3),
                pf=round(float(w / l), 2) if l > 0 else None, ci95=[round(float(np.percentile(boot, 2.5)), 3), round(float(np.percentile(boot, 97.5)), 3)],
                gross_expR=round(float(df.gross_R.mean()), 3), cost_R=round(float(df.cost_R.mean()), 3))

def backtest(source, folder=None, years=5):
    c = CFG; S = c["scan"]; P = c["breakout"]; res = {}
    if source == "csv":
        def rd(iv, f):
            d = pd.read_csv(os.path.join(folder, iv, f))
            d.index = pd.DatetimeIndex(pd.to_datetime(d.ts_utc.values, unit="s", utc=True)).tz_convert("Asia/Kolkata").tz_localize(None)
            d = d.rename(columns={"open": "o", "high": "h", "low": "l", "close": "c", "volume": "v"})[["o", "h", "l", "c", "v"]]
            d = d[(d.c > 0) & (d.h >= d.l)]
            if iv == "1d": d.index = d.index.normalize()
            return d[~d.index.duplicated(keep="last")].sort_index()
        files = sorted(os.listdir(os.path.join(folder, "1d")))
        D = {f[:-4]: rd("1d", f) for f in files}
        B5 = {f[:-4]: rd("5m", f) for f in sorted(os.listdir(os.path.join(folder, "5m"))) if f.endswith(".NS.csv")}
        nifty5 = rd("5m", "_NSEI.csv")
    else:
        dh = Dhan(); m = load_master(); ins = pick_instruments(m, c, dt.date.today()); today = dt.date.today()
        D = {}; B5 = {}
        for i in ins:
            if i["kind"] in ("eq", "idx_fut"):
                d = dh.daily(i["sid"], i["seg"], i["instr"], "2005-01-01", today.isoformat(), 0 if i["kind"] == "idx_fut" else None)
                if d is not None: D[i["sym"]] = d
            if i["kind"] == "eq":
                b = dh.intraday(i["sid"], i["seg"], i["instr"], (today - dt.timedelta(days=365 * years)).strftime("%Y-%m-%d 09:15:00"), today.strftime("%Y-%m-%d 15:30:00"), 5)
                if b is not None: B5[i["sym"]] = b
        nif = next(i for i in ins if i["kind"] == "idx")
        nifty5 = dh.intraday(nif["sid"], "IDX_I", "INDEX", (today - dt.timedelta(days=365 * years)).strftime("%Y-%m-%d 09:15:00"), today.strftime("%Y-%m-%d 15:30:00"), 5)
    cf_f = cost_frac("fut", 1e6, c["slippage"]["fut_stk"]); cf_c = cost_frac("cnc", 1e5, c["slippage"]["cnc"]); cf_m = cost_frac("mis", 1e5, c["slippage"]["mis"])
    allf = []; allc = []
    for s, d in D.items():
        if len(d) < 200: continue
        allf += breakout_trades(d, cf_f, P["N"], P["ks"], P["kt"], pd.Timedelta(days=P["maxHoldDays"]))
        allc += breakout_trades(d, cf_c, P["N"], P["ks"], P["kt"], pd.Timedelta(days=P["maxHoldDays"]), longonly=True)
    res["breakout_futures"] = summarise(pd.DataFrame(allf), "breakout daily, futures costs, long+short")
    res["breakout_cnc"] = summarise(pd.DataFrame(allc), "breakout daily, delivery costs, long only")
    B5 = {s: b[(b.index.hour * 60 + b.index.minute >= 555) & (b.index.hour * 60 + b.index.minute <= 925)] for s, b in B5.items() if b is not None and len(b) > 500}
    sc, blk = scanner_trades(B5, nifty5, S, cf_m)
    res["scanner"] = summarise(sc, "360 scanner 5m, intraday costs"); res["scanner"]["blocked"] = blk
    print(json.dumps(res, indent=1, default=str)); return res

def selftest():
    ok = 0
    ch = charges("fut", 1e6, 1e6); assert abs(ch["stt"] - 500) < 1e-6 and ch["brokerage"] == 40; ok += 1
    ch = charges("mis", 1e5, 1e5); assert abs(ch["stt"] - 25) < 1e-6 and ch["brokerage"] == 40; ok += 1
    ch = charges("cnc", 1e5, 1e5); assert ch["brokerage"] == 0 and abs(ch["stt"] - 200) < 1e-6; ok += 1
    ch = charges("opt", 1e4, 1e4); assert abs(ch["stt"] - 15) < 1e-6; ok += 1
    # breakout on a clean up-trend: one long, exits on trail when trend breaks
    idx = pd.bdate_range("2024-01-01", periods=200)
    p = np.r_[np.full(80, 100.0) + np.sin(np.arange(80)) * 0.5, 100 + np.arange(1, 81) * 0.8, np.linspace(164, 120, 40)]
    b = pd.DataFrame(dict(o=p, h=p + 0.6, l=p - 0.6, c=p, v=1000), index=idx)
    tr = breakout_trades(b, 0.001); assert tr and tr[0]["d"] == 1 and tr[0]["R"] > 2, tr; ok += 1
    tr = breakout_trades(b, 0.001, longonly=True, keep_open=True); assert all(t["d"] == 1 for t in tr); ok += 1
    # scanner step: lock then trail then exit
    S = CFG["scan"]; s = dict(d=1, entry=100.0, stop=99.0, peak=100.0, locked=False, trailed=False, ema=100.0, n=0)
    assert scan_step(s, dict(o=100, h=100.4, l=99.9, c=100.35), 0.14, S) is None and s["locked"] and s["stop"] > 100; ok += 1
    r = scan_step(s, dict(o=100.3, h=100.3, l=99.0, c=99.2), 0.14, S); assert r and r[1] in ("trail", "lock") and r[0] > 100; ok += 1
    # rate limiter: 8 per second
    rl = RateLimiter([(8, 1.0)]); t0 = time.time(); [rl.wait() for _ in range(17)]; assert time.time() - t0 >= 2.0; ok += 1
    # lock: broker never sends
    br = Broker(None, lambda m: None); assert br.send("POST", "/super/orders", {})["orderStatus"] == "PAPER"; ok += 1
    assert LIVE_LOCKED is True; ok += 1
    print("selftest: %d/11 passed" % ok); return ok

if __name__ == "__main__":
    a = sys.argv[1:]
    if a[:1] == ["--selftest"]: selftest()
    elif a[:1] == ["--backtest"]: backtest(a[1] if len(a) > 1 else "dhan", a[2] if len(a) > 2 else None)
    else: Bot(CFG).run()
