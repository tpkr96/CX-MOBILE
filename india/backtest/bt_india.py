# India backtest of the crypto bot's two engines on real NSE/BSE history (Yahoo Finance chart API download, see tools/download_india.js).
# Rules and costs are fixed in ../PREREGISTERED_CRITERIA.md before any result. Read-only: no orders, no keys.
# Usage: python3 bt_india.py <data_india dir> <out dir>
import sys, os, glob, json, math
import numpy as np, pandas as pd

D = sys.argv[1]; OUT = sys.argv[2] if len(sys.argv) > 2 else '.'
os.makedirs(OUT, exist_ok=True)
rng = np.random.default_rng(7)

# ---------------- costs (fractions of notional, round trip) ----------------
def cost_frac(kind, notional, slip):
    sebi = 2 * 1e-6 * notional
    if kind == 'fut':
        brok = 2 * min(20, 0.0003 * notional); stt = 0.0005 * notional; exch = 2 * 0.0000173 * notional; stamp = 0.00002 * notional; dp = 0
    elif kind == 'cnc':
        brok = 0; stt = 0.001 * 2 * notional; exch = 2 * 0.0000297 * notional; stamp = 0.00015 * notional; dp = 16
    elif kind == 'mis':
        brok = 2 * min(20, 0.0003 * notional); stt = 0.00025 * notional; exch = 2 * 0.0000297 * notional; stamp = 0.00003 * notional; dp = 0
    gst = 0.18 * (brok + exch + sebi)
    return (brok + stt + exch + sebi + stamp + dp + gst) / notional + 2 * slip

COST = {
    'fut_idx': cost_frac('fut', 1.5e6, 0.0002),
    'fut_stk': cost_frac('fut', 1.0e6, 0.0005),
    'cnc':     cost_frac('cnc', 1.0e5, 0.0005),
    'mis':     cost_frac('mis', 1.0e5, 0.0003),
}

# ---------------- data ----------------
IDX_FUT = {'^NSEI': 'NIFTY', '^NSEBANK': 'BANKNIFTY', 'NIFTY_FIN_SERVICE.NS': 'FINNIFTY', '^NSEMDCP50': 'MIDCPNIFTY', '^BSESN': 'SENSEX', 'BSE-BANK.BO': 'BANKEX'}
def fname(s): return ''.join(c if (c.isalnum() or c in '.&-') else '_' for c in s) + '.csv'
def load(iv, s):
    f = os.path.join(D, iv, fname(s))
    if not os.path.exists(f): f = os.path.join(D, iv, s + '.csv')
    if not os.path.exists(f): return None
    df = pd.read_csv(f)
    if len(df) < 50: return None
    df['t'] = pd.to_datetime(df.ts_utc, unit='s', utc=True).dt.tz_convert('Asia/Kolkata').dt.tz_localize(None)
    df = df.rename(columns={'open': 'o', 'high': 'h', 'low': 'l', 'close': 'c', 'volume': 'v'})
    df = df[(df.c > 0) & (df.o > 0) & (df.h >= df.l)]
    if iv == '1d': df['t'] = df.t.dt.normalize()
    df = df.drop_duplicates('t', keep='last').set_index('t').sort_index()[['o', 'h', 'l', 'c', 'v']]
    df['h'] = df[['o', 'h', 'c']].max(axis=1); df['l'] = df[['o', 'l', 'c']].min(axis=1)
    return df

def symbols(iv):
    return sorted(os.path.basename(p)[:-4] for p in glob.glob(os.path.join(D, iv, '*.csv')))

def atr(b, n=14):
    pc = b.c.shift()
    return pd.concat([b.h - b.l, (b.h - pc).abs(), (b.l - pc).abs()], axis=1).max(axis=1).rolling(n).mean()

# Nifty regime by date: trailing 120-trading-day return
NIFTY_D = load('1d', '^NSEI')
REG = None
if NIFTY_D is not None:
    r120 = NIFTY_D.c / NIFTY_D.c.shift(120) - 1
    REG = pd.Series(np.where(r120 > 0.10, 'bull', np.where(r120 < -0.10, 'bear', 'sideways')), index=NIFTY_D.index)[r120.notna()]
def regime(t):
    if REG is None: return 'na'
    i = REG.index.searchsorted(t.normalize(), side='right') - 1
    return REG.iloc[i] if i >= 0 else 'na'

# ---------------- Engine A: Donchian breakout (port of crypto S1) ----------------
def breakout(b, cf, N=55, ks=2.0, kt=5.0, maxhold=None, late=0, longonly=False):
    a = atr(b); up = b.h.rolling(N).max().shift(); dn = b.l.rolling(N).min().shift()
    idx = b.index; O, H, L, C = b.o.values, b.h.values, b.l.values, b.c.values; A = a.values; U = up.values; Dn = dn.values
    out = []; i = 0; n = len(b)
    busy = -1
    for t in range(n - 1):
        if t <= busy or np.isnan(A[t]) or np.isnan(U[t]): continue
        d = 1 if C[t] > U[t] else (-1 if C[t] < Dn[t] else 0)
        if d == 0 or (longonly and d < 0): continue
        e = t + 1 + late
        if e >= n: break
        px = O[e]; stop = C[t] - d * ks * A[t]; k = kt * A[t]
        if (d > 0 and px <= stop) or (d < 0 and px >= stop): continue  # gapped through the stop
        risk = abs(px - stop); hi = lo = px; ex = None; j = e
        tend = idx[e] + maxhold if maxhold is not None else None
        while j < n:
            if d > 0 and L[j] <= stop: ex = min(O[j], stop); why = 'trail' if stop > px - risk + 1e-12 else 'stop'; break
            if d < 0 and H[j] >= stop: ex = max(O[j], stop); why = 'trail' if stop < px + risk - 1e-12 else 'stop'; break
            if tend is not None and j + 1 < n and idx[j + 1] >= tend: ex = C[j]; why = 'time'; break
            hi = max(hi, H[j]); lo = min(lo, L[j])
            stop = max(stop, hi - k) if d > 0 else min(stop, lo + k)
            j += 1
        if ex is None: break  # still open at the end of data: not counted
        g = d * (ex - px); R = (g - cf * px) / risk
        out.append(dict(tin=idx[e], tout=idx[j], d=d, entry=px, exit=ex, risk_pct=risk / px * 100, gross_R=g / risk, R=R,
                        cost_R=cf * px / risk, why=why))
        busy = j
    return out

# ---------------- stats ----------------
def stats(df, label):
    if df is None or len(df) == 0: return dict(label=label, n=0)
    R = df.R.values; w = R[R > 0].sum(); l = -R[R < 0].sum()
    boot = [rng.choice(R, len(R)).mean() for _ in range(2000)]
    srt = np.sort(R)[::-1]
    o = dict(label=label, n=int(len(R)), win=round(float((R > 0).mean() * 100), 1), expR=round(float(R.mean()), 3),
             pf=round(float(w / l), 2) if l > 0 else 99.0, ci95=[round(float(np.percentile(boot, 2.5)), 3), round(float(np.percentile(boot, 97.5)), 3)],
             grossR=round(float(df.gross_R.mean()), 3), costR=round(float(df.cost_R.mean()), 3),
             sumR=round(float(R.sum()), 1), sum_wo_top10=round(float(srt[10:].sum()), 1) if len(R) > 10 else None,
             first=str(df.tin.min())[:10], last=str(df.tin.max())[:10])
    return o

def portfolio(df, risk=0.005, maxpos=3, ppy=252):
    """0.5% of equity at risk per trade, at most maxpos open. Equity booked at exit (realised). Returns maxDD %, Sharpe, CAGR."""
    if len(df) == 0: return {}
    ev = df.sort_values('tin').reset_index(drop=True)
    eq = 1.0; open_ = []; book = []
    for _, r in ev.iterrows():
        # close trades that exited before this entry
        still = []
        for (tout, amt) in sorted(open_):
            if tout <= r.tin: eq += amt; book.append((tout, eq))
            else: still.append((tout, amt))
        open_ = still
        if len(open_) >= maxpos: continue
        open_.append((r.tout, eq * risk * r.R))
    for (tout, amt) in sorted(open_): eq += amt; book.append((tout, eq))
    s = pd.Series([e for _, e in book], index=pd.to_datetime([t for t, _ in book])).groupby(level=0).last()
    s = pd.concat([pd.Series([1.0], index=[ev.tin.min()]), s]).groupby(level=0).last()
    daily = s.resample('1D').last().ffill()
    if NIFTY_D is not None:  # trading days only
        daily = daily[daily.index.isin(NIFTY_D.index)] if daily.index.isin(NIFTY_D.index).sum() > 20 else daily
    ret = daily.pct_change().dropna()
    dd = (daily / daily.cummax() - 1).min()
    yrs = max((daily.index[-1] - daily.index[0]).days / 365.25, 1e-9)
    sh = float(ret.mean() / ret.std() * math.sqrt(ppy)) if ret.std() > 0 else 0.0
    return dict(final_equity=round(float(eq), 3), cagr_pct=round(float((eq ** (1 / yrs) - 1) * 100), 2), maxdd_pct=round(float(dd * 100), 1), sharpe=round(sh, 2))

def criteria(base, dbl, late, label):
    st = stats(base, label); c = {}
    if st['n'] == 0: return dict(stats=st, pass_all=False)
    c['C1_trades>=100'] = st['n'] >= 100
    c['C2_expR>0'] = st['expR'] > 0
    c['C3_PF>=1.15'] = st['pf'] >= 1.15
    c['C4_CI_low>0'] = st['ci95'][0] > 0
    c['C5_double_costs>0'] = float(dbl.R.mean()) > 0 if len(dbl) else False
    c['C6_late_entry>0'] = float(late.R.mean()) > 0 if len(late) else False
    mid = base.tin.min() + (base.tin.max() - base.tin.min()) / 2
    h1, h2 = base[base.tin < mid].R.mean(), base[base.tin >= mid].R.mean()
    c['C7_both_halves>0'] = bool(h1 > 0 and h2 > 0)
    rg = base.assign(rg=[regime(t) for t in base.tin]).groupby('rg').R.agg(['count', 'mean'])
    c['C8_regimes>=2of3'] = int(sum(1 for k in ['bull', 'bear', 'sideways'] if k in rg.index and rg.loc[k, 'mean'] > 0)) >= 2
    pf = portfolio(base)
    c['C9_maxDD<=30%'] = pf.get('maxdd_pct', -100) >= -30
    c['C10_Sharpe>=0.5'] = pf.get('sharpe', 0) >= 0.5
    extra = dict(halves=[round(float(h1), 3), round(float(h2), 3)], regimes={k: [int(v['count']), round(float(v['mean']), 3)] for k, v in rg.iterrows()},
                 double_costs_expR=round(float(dbl.R.mean()), 3) if len(dbl) else None, late_expR=round(float(late.R.mean()), 3) if len(late) else None,
                 portfolio=pf, by_year={int(k): [int(v['count']), round(float(v['mean']), 3)] for k, v in base.groupby(base.tin.dt.year).R.agg(['count', 'mean']).iterrows()})
    return dict(stats=st, checks=c, passed=int(sum(c.values())), pass_all=all(c.values()), **extra)

def run_breakout(iv, group, kind_idx, kind_stk, longonly, maxhold, label, syms_filter=None):
    rows = {'base': [], 'dbl': [], 'late': []}; per = {}
    for s in symbols(iv):
        is_idx = s in [fname(k)[:-4] for k in IDX_FUT]
        if group == 'idx' and not is_idx: continue
        if group == 'stk' and (is_idx or not s.endswith('.NS')): continue
        b = load(iv, s)
        if b is None or len(b) < 200: continue
        cf = COST[kind_idx] if is_idx else COST[kind_stk]
        for k, kw in [('base', {}), ('dbl', {'cf2': 2}), ('late', {'late': 1})]:
            c = cf * kw.get('cf2', 1)
            tr = breakout(b, c, maxhold=maxhold, late=kw.get('late', 0), longonly=longonly)
            for x in tr: x['sym'] = s
            rows[k] += tr
            if k == 'base' and tr: per[s] = [len(tr), round(float(np.mean([x['R'] for x in tr])), 3)]
    dfs = {k: pd.DataFrame(v) for k, v in rows.items()}
    res = criteria(dfs['base'], dfs['dbl'], dfs['late'], label)
    res['per_symbol'] = per
    if len(dfs['base']):
        dfs['base'].to_csv(os.path.join(OUT, f'trades_{label}.csv'), index=False)
        res['longs_expR'] = round(float(dfs['base'][dfs['base'].d > 0].R.mean()), 3) if (dfs['base'].d > 0).any() else None
        res['shorts_expR'] = round(float(dfs['base'][dfs['base'].d < 0].R.mean()), 3) if (dfs['base'].d < 0).any() else None
    print(label, json.dumps({k: res.get(k) for k in ['stats', 'passed', 'pass_all']}), flush=True)
    return res

# ---------------- Engine B: 360 scanner on 5-minute bars (port of scanFeat/scanScore/moodCore/scanStep) ----------------
SG = dict(scanMin=60, look=3, atrN=14, atrK=2, minStopPct=0.3, maxStopPct=3, lockMult=2, lockBuf=0.02, giveBack=40, fadeEma=9,
          timeStop=30, maxHold=120, cooldown=10, maxPerDay=4, chaseZ=2.5, edgeMult=2, moodBrHi=60, moodBrLo=40, volPause=3,
          wMom=30, wVol=15, wBrk=20, tf=5)
clamp = lambda x, a, b: max(a, min(b, x))

def session_vwap(b, use_volume=True):
    tp = (b.h + b.l + b.c) / 3; day = b.index.normalize()
    if use_volume and b.v.sum() > 0:
        pv = (tp * b.v).groupby(day).cumsum(); vv = b.v.groupby(day).cumsum()
        return (pv / vv.replace(0, np.nan))
    return tp.groupby(day).cumsum() / tp.groupby(day).cumcount().add(1)  # TWAP fallback (index has no volume)

def feats(b, vw):
    """vectorised scanFeat for every bar (uses only bars up to and including that bar)"""
    k = SG['look']; lr = np.log(b.c / b.c.shift())
    sd = lr.rolling(59, min_periods=20).std()
    ret = np.log(b.c / b.c.shift(k)); z = ret / (sd * math.sqrt(k))
    vr = b.v.rolling(k).mean(); vb = b.v.shift(k).rolling(60 - k + 1, min_periods=10).mean(); rv = vr / vb.replace(0, np.nan)
    hi = b.h.shift().rolling(60, min_periods=20).max(); lo = b.l.shift().rolling(60, min_periods=20).min()
    pc = b.c.shift(); tr = pd.concat([b.h - b.l, (b.h - pc).abs(), (b.l - pc).abs()], axis=1).max(axis=1)
    at = tr.rolling(SG['atrN'] - 1).mean()  # crypto code averages the TR of the last atrN-1 bars, current bar included
    ema = b.c.ewm(span=SG['fadeEma'], adjust=False).mean()
    c = b.c
    brk = np.where((c > hi) & (c > vw), 1.0, np.where((c < lo) & (c < vw), -1.0, np.where(c > vw, 0.3, np.where(c < vw, -0.3, 0.0))))
    mom = (z / 3).clip(-1, 1)
    vol = np.sign(ret) * ((rv - 1) / 2).clip(0, 1)
    F = pd.DataFrame(dict(c=c, z=z, sd=sd, mom=mom, vol=vol, rv=rv, brk=brk, atr=at, ema=ema, vw=vw), index=b.index)
    wsum = SG['wMom'] + SG['wVol'] + SG['wBrk']
    F['score'] = 100 * (SG['wMom'] * F.mom + SG['wVol'] * F.vol.fillna(0) * F.vol.notna() + SG['wBrk'] * F.brk) / \
                 (SG['wMom'] + SG['wVol'] * F.vol.notna() + SG['wBrk'])
    F.loc[F.vw.isna() | F.mom.isna() | F.atr.isna(), 'score'] = np.nan
    return F

def mood_series(nifty, breadth):
    """moodCore on the Nifty 5m series: VWAP(TWAP) side, 60-minute direction, breadth, 5-bar range spike"""
    vw = session_vwap(nifty, use_volume=False)
    tV = np.sign(nifty.c - vw).fillna(0)
    c60 = nifty.c.shift(12); tR = np.sign(nifty.c - c60).fillna(0)
    br = breadth.reindex(nifty.index)
    tB = pd.Series(np.where(br >= SG['moodBrHi'], 1, np.where(br <= SG['moodBrLo'], -1, 0)), index=nifty.index)
    rng5 = nifty.h.rolling(5).max() - nifty.l.rolling(5).min()
    med = rng5.shift(5).rolling(60, min_periods=6).apply(lambda x: np.median(x[::5]), raw=True)
    spike = rng5 / med
    pause = spike > SG['volPause']
    bias = tV + tR + tB
    return pd.DataFrame(dict(bias=bias, pause=pause.fillna(False), spike=spike, breadth=br))

def run_scanner(cost_mult=1.0, late=0, label='scanner'):
    syms = [s for s in symbols('5m') if s.endswith('.NS') and not s.startswith('NIFTY_')]
    nifty = load('5m', '^NSEI')
    if nifty is None: return dict(label=label, error='no Nifty 5m')
    B = {}; FS = {}
    for s in syms:
        b = load('5m', s)
        if b is None or len(b) < 500: continue
        b = b[(b.index.time >= pd.Timestamp('09:15').time()) & (b.index.time <= pd.Timestamp('15:25').time())]
        B[s] = b; FS[s] = feats(b, session_vwap(b))
    above = pd.concat({s: (FS[s].c > FS[s].vw).astype(float).where(FS[s].vw.notna()) for s in FS}, axis=1)
    breadth = above.mean(axis=1) * 100
    M = mood_series(nifty, breadth)
    cf = COST['mis'] * cost_mult; cost_pct = cf * 100
    trades = []; blocked = {}
    for s, b in B.items():
        F = FS[s]; idx = b.index; O, H, L, C = b.o.values, b.h.values, b.l.values, b.c.values
        n = len(b); i = 0; last_sig = None; day_cnt = {}
        tmin = idx.hour * 60 + idx.minute
        while i < n - 1 - late:
            t = idx[i]; end_min = tmin[i] + 5  # decision at bar close
            sc = F.score.iat[i]
            if np.isnan(sc) or end_min < 9 * 60 + 45 or end_min > 14 * 60 + 45: i += 1; continue
            if last_sig is not None and last_sig.normalize() == t.normalize() and (t - last_sig).total_seconds() < SG['cooldown'] * 60: i += 1; continue
            d = 1 if sc >= SG['scanMin'] else (-1 if sc <= -SG['scanMin'] else 0)
            if d == 0: i += 1; continue
            last_sig = t
            why = None
            m = M.loc[t] if t in M.index else None
            if m is None or np.isnan(m.bias): why = 'mood_na'
            elif m.pause: why = 'vol_pause'
            elif not ((d > 0 and m.bias >= 1) or (d < 0 and m.bias <= -1)): why = 'mood'
            f = F.iloc[i]; entry_ref = C[i]
            R = min(max(SG['atrK'] * f.atr, entry_ref * SG['minStopPct'] / 100), entry_ref * SG['maxStopPct'] / 100)
            if why is None and f.vw > 0 and f.sd > 0:
                ext = math.log(f.c / f.vw) * d; zc = ext / (f.sd * math.sqrt(60 / SG['tf']))
                if zc > SG['chaseZ']: why = 'chase'
            if why is None:
                hb = max(1, SG['timeStop'] / SG['tf']); exp = f.atr / f.c * 100 * math.sqrt(hb)
                if exp < SG['edgeMult'] * cost_pct: why = 'edge'
            dk = t.normalize()
            if why is None and day_cnt.get(dk, 0) >= SG['maxPerDay']: why = 'per_day'
            if why: blocked[why] = blocked.get(why, 0) + 1; i += 1; continue
            day_cnt[dk] = day_cnt.get(dk, 0) + 1
            e = i + 1 + late
            if idx[e].normalize() != dk: i += 1; continue
            px = O[e]; stop = entry_ref - d * R
            if (d > 0 and px <= stop) or (d < 0 and px >= stop): i += 1; continue
            risk = abs(px - stop); peak = px; locked = False; trailed = False; ema = f.ema; nb = 0; ex = None
            j = e
            while j < n:
                if idx[j].normalize() != dk: ex = C[j - 1]; whyx = 'eod'; j -= 1; break
                if (d > 0 and L[j] <= stop) or (d < 0 and H[j] >= stop):
                    ex = min(O[j], stop) if d > 0 else max(O[j], stop); whyx = 'trail' if trailed else ('lock' if locked else 'stop'); break
                peak = max(peak, H[j]) if d > 0 else min(peak, L[j]); nb += 1
                fav = (peak / px - 1) * d * 100
                if not locked and fav >= SG['lockMult'] * cost_pct:
                    locked = True; lv = px * (1 + d * (cost_pct + SG['lockBuf']) / 100)
                    if (d > 0 and lv > stop) or (d < 0 and lv < stop): stop = lv
                if locked:
                    trv = peak - d * abs(peak - px) * SG['giveBack'] / 100
                    if (d > 0 and trv > stop) or (d < 0 and trv < stop): stop = trv; trailed = True
                a = 2 / (SG['fadeEma'] + 1); ema = ema + a * (C[j] - ema)
                if locked and nb >= 2 and ((d > 0 and C[j] < ema) or (d < 0 and C[j] > ema)): ex = C[j]; whyx = 'fade'; break
                held = nb * 5
                if not locked and held >= SG['timeStop']: ex = C[j]; whyx = 'time'; break
                if held >= SG['maxHold']: ex = C[j]; whyx = 'maxhold'; break
                if tmin[j] + 5 >= 15 * 60 + 15: ex = C[j]; whyx = 'exitby'; break
                j += 1
            if ex is None: break
            g = d * (ex - px)
            trades.append(dict(sym=s, tin=idx[e], tout=idx[j], d=d, entry=px, exit=ex, risk_pct=risk / px * 100, gross_R=g / risk,
                               R=(g - cf * px) / risk, cost_R=cf * px / risk, why=whyx, score=round(float(sc), 1)))
            i = j + 1
    df = pd.DataFrame(trades)
    return df, blocked

def scanner_report():
    base, blk = run_scanner(label='scanner')
    if isinstance(base, dict): return base
    dbl, _ = run_scanner(cost_mult=2.0)
    late, _ = run_scanner(late=1)
    res = criteria(base, dbl, late, 'B_scanner_5m_MIS')
    res['blocked'] = blk
    if len(base):
        base.to_csv(os.path.join(OUT, 'trades_B_scanner_5m_MIS.csv'), index=False)
        res['exits'] = base.why.value_counts().to_dict()
        res['longs_expR'] = round(float(base[base.d > 0].R.mean()), 3) if (base.d > 0).any() else None
        res['shorts_expR'] = round(float(base[base.d < 0].R.mean()), 3) if (base.d < 0).any() else None
        res['avg_gross_pct'] = round(float((base.gross_R * base.risk_pct).mean()), 3)
        res['cost_pct'] = round(COST['mis'] * 100, 3)
        res['note'] = 'C10 Sharpe and C9 use realised equity; only ~60 trading days of 5m data exist on Yahoo, so C7/C8 have little meaning here.'
    print('B_scanner_5m_MIS', json.dumps({k: res.get(k) for k in ['stats', 'passed', 'pass_all']}), flush=True)
    return res

if __name__ == '__main__':
    R = dict(costs_round_trip_pct={k: round(v * 100, 4) for k, v in COST.items()})
    R['A1_daily_futures_index'] = run_breakout('1d', 'idx', 'fut_idx', 'fut_stk', False, pd.Timedelta('30D'), 'A1_daily_fut_index')
    R['A1_daily_futures_stocks'] = run_breakout('1d', 'stk', 'fut_idx', 'fut_stk', False, pd.Timedelta('30D'), 'A1_daily_fut_stocks')
    R['A1_daily_cnc_stocks_long'] = run_breakout('1d', 'stk', 'cnc', 'cnc', True, pd.Timedelta('30D'), 'A1_daily_cnc_stocks_long')
    R['A2_60m_futures_index'] = run_breakout('60m', 'idx', 'fut_idx', 'fut_stk', False, pd.Timedelta('30D'), 'A2_60m_fut_index')
    R['A2_60m_futures_stocks'] = run_breakout('60m', 'stk', 'fut_idx', 'fut_stk', False, pd.Timedelta('30D'), 'A2_60m_fut_stocks')
    R['A2_60m_cnc_stocks_long'] = run_breakout('60m', 'stk', 'cnc', 'cnc', True, pd.Timedelta('30D'), 'A2_60m_cnc_stocks_long')
    try:
        R['B_scanner_5m_MIS'] = scanner_report()
    except Exception as ex:
        import traceback; traceback.print_exc(); R['B_scanner_5m_MIS'] = dict(error=str(ex))
    json.dump(R, open(os.path.join(OUT, 'results.json'), 'w'), indent=1, default=str)
    print('DONE')
