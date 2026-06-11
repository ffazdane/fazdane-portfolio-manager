import sys
import os
import time
import json
import warnings
import urllib3
import requests
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import Wedge
from datetime import datetime, timedelta

# Disable SSL verification warnings to handle corporate inspection proxies safely
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Create requests session with SSL verification disabled
_SESSION = requests.Session()
_SESSION.verify = False

# Constants
TICKERS = ["SPY", "QQQ", "IWM"]
VIX_TICK = "^VIX"
DRAWDOWN_THRESHOLD = 0.03  # 3% minimum drop
MA_PERIODS = [9, 20, 50, 200]
PRE_SIGNAL_WINDOWS = [5, 10, 20]

# Standard Zone Colors
C_RED = "FCE4D6"
C_YELLOW = "FFF2CC"
C_GREEN = "E2EFDA"
C_ORANGE = "F4B183"


def fetch_close(ticker, start, end):
    """
    Fetch daily adjusted closing prices via Yahoo Finance v8 chart API.
    Bypasses yfinance SSL cert issues through corporate proxies.
    """
    yf_symbol = ticker.replace("^", "%5E")
    p1 = int(pd.Timestamp(start).timestamp())
    p2 = int(pd.Timestamp(end).timestamp())
    url = (f"https://query2.finance.yahoo.com/v8/finance/chart/{yf_symbol}"
           f"?interval=1d&period1={p1}&period2={p2}&includePrePost=false")
    headers = {
        "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/124.0.0.0 Safari/537.36"),
    }
    for attempt in range(3):
        try:
            resp = _SESSION.get(url, headers=headers, timeout=30)
            if resp.status_code == 200:
                data = resp.json()
                result = data["chart"]["result"][0]
                timestamps = result["timestamp"]
                try:
                    closes = result["indicators"]["adjclose"][0]["adjclose"]
                except (KeyError, IndexError):
                    closes = result["indicators"]["quote"][0]["close"]
                dates = pd.to_datetime(timestamps, unit="s").normalize()
                s = pd.Series(closes, index=dates, name=ticker, dtype=float).dropna()
                if len(s) == 0:
                    raise ValueError(f"Empty price series for {ticker}")
                return s
            elif resp.status_code == 429:
                time.sleep(20 * (attempt + 1))
            else:
                raise ValueError(f"HTTP {resp.status_code} for {ticker}: {resp.text[:200]}")
        except Exception as e:
            if attempt == 2:
                raise ValueError(f"Failed to fetch {ticker}: {e}") from e
            time.sleep(5 * (attempt + 1))


def _rsi(series: pd.Series, n: int = 14) -> pd.Series:
    """Wilder RSI."""
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = gain.ewm(com=n - 1, min_periods=n).mean()
    avg_loss = loss.ewm(com=n - 1, min_periods=n).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return (100 - 100 / (1 + rs)).rename("RSI14")


def _consec_up(ret: pd.Series) -> pd.Series:
    """Count of consecutive positive-return days ending on each date."""
    out, count = [], 0
    for v in ret:
        count = count + 1 if (pd.notna(v) and v > 0) else 0
        out.append(count)
    return pd.Series(out, index=ret.index, name="ConsecUp")


def build_indicators(price: pd.Series, vix_series: pd.Series) -> pd.DataFrame:
    """Calculate MAs, deviations, realized vol, RSI, Bollinger Bands, ROC, ConsecUp."""
    d = pd.DataFrame({"Close": price})
    ret = price.pct_change()

    for n in MA_PERIODS:
        d[f"SMA{n}"] = price.rolling(n).mean()
        d[f"EMA{n}"] = price.ewm(span=n, adjust=False).mean()
        d[f"DevSMA{n}"] = (price - d[f"SMA{n}"]) / d[f"SMA{n}"]
        d[f"DevEMA{n}"] = (price - d[f"EMA{n}"]) / d[f"EMA{n}"]

    d["RealVol20"] = ret.rolling(20).std() * np.sqrt(252)
    d["Above_SMA50"] = (price > d["SMA50"]).astype(int)
    d["Above_SMA200"] = (price > d["SMA200"]).astype(int)
    d["BullTrend"] = (d["SMA50"] > d["SMA200"]).astype(int)
    d["RSI14"] = _rsi(price, 14)

    rm20 = price.rolling(20).mean()
    rs20 = price.rolling(20).std()
    d["ZScore20"] = (price - rm20) / rs20.replace(0, np.nan)
    d["BB_upper"] = rm20 + 2 * rs20
    d["BB_lower"] = rm20 - 2 * rs20
    band_width = (d["BB_upper"] - d["BB_lower"]).replace(0, np.nan)
    d["BB_pct"] = (price - d["BB_lower"]) / band_width
    d["BB_width_pct"] = band_width / rm20

    d["ROC5"] = ret.rolling(5).sum()
    d["ROC20"] = ret.rolling(20).sum()
    d["ConsecUp"] = _consec_up(ret)
    d["High252"] = price.rolling(252, min_periods=20).max()
    d["FromHigh252"] = (price - d["High252"]) / d["High252"]

    d["VIX"] = vix_series.reindex(d.index, method="ffill")
    return d


def detect_drawdowns(price: pd.Series, threshold: float = DRAWDOWN_THRESHOLD, analysis_start=None) -> list:
    """Returns list of drawdown events."""
    p = price.dropna()
    n = len(p)
    if n == 0:
        return []

    drawdowns = []
    i = 0
    while i < n:
        roll_max = p.iloc[i]
        roll_max_idx = i
        found = False

        j = i + 1
        while j < n:
            if p.iloc[j] > roll_max:
                roll_max = p.iloc[j]
                roll_max_idx = j

            drop_pct = (roll_max - p.iloc[j]) / roll_max
            if drop_pct >= threshold:
                found = True
                pk_date = p.index[roll_max_idx]
                pk_price = roll_max

                tr_val = p.iloc[j]
                tr_idx = j
                k = j
                recovered = False
                while k < n:
                    if p.iloc[k] < tr_val:
                        tr_val = p.iloc[k]
                        tr_idx = k
                    if p.iloc[k] >= pk_price:
                        recovered = True
                        break
                    k += 1

                tr_date = p.index[tr_idx]
                tr_price = tr_val
                dd_pct = (pk_price - tr_price) / pk_price
                rec_date = p.index[k] if recovered else None
                dur_p2t = (tr_date - pk_date).days
                dur_t2r = (rec_date - tr_date).days if recovered else None
                dur_total = (rec_date - pk_date).days if recovered else (p.index[-1] - pk_date).days

                if analysis_start is None or pk_date >= pd.Timestamp(analysis_start) or tr_date >= pd.Timestamp(analysis_start):
                    drawdowns.append({
                        "peak_date": pk_date,
                        "peak_price": round(float(pk_price), 4),
                        "trough_date": tr_date,
                        "trough_price": round(float(tr_price), 4),
                        "recovery_date": rec_date,
                        "drawdown_pct": round(float(dd_pct), 6),
                        "dur_peak_to_trough": dur_p2t,
                        "dur_trough_to_rec": dur_t2r,
                        "dur_total": dur_total,
                        "recovered": recovered,
                    })

                i = k + 1 if recovered else tr_idx + 1
                break
            j += 1

        if not found:
            break

    return drawdowns


def enrich_with_next_high(dd_list: list, price: pd.Series) -> list:
    """Enriches drawdowns with next high data."""
    enriched = []
    for i, dd in enumerate(dd_list):
        e = dict(dd)
        if dd["recovered"] and dd["recovery_date"] is not None:
            rec_ts = pd.Timestamp(dd["recovery_date"])
            if i + 1 < len(dd_list):
                next_pk_ts = pd.Timestamp(dd_list[i + 1]["peak_date"])
                window = price.loc[rec_ts:next_pk_ts]
            else:
                window = price.loc[rec_ts:]

            if len(window) > 0:
                e["next_high_price"] = round(float(window.max()), 4)
                e["next_high_date"] = window.idxmax()
                e["gain_from_trough_pct"] = round((e["next_high_price"] - dd["trough_price"]) / dd["trough_price"], 6)
                e["gain_from_trough_pts"] = round(e["next_high_price"] - dd["trough_price"], 4)
                e["days_to_next_high"] = (e["next_high_date"] - rec_ts).days
            else:
                e["next_high_price"] = e["next_high_date"] = None
                e["gain_from_trough_pct"] = e["gain_from_trough_pts"] = None
                e["days_to_next_high"] = None
        else:
            e["next_high_price"] = e["next_high_date"] = None
            e["gain_from_trough_pct"] = e["gain_from_trough_pts"] = None
            e["days_to_next_high"] = None
        enriched.append(e)
    return enriched


def pre_drawdown_snapshot(dd_list: list, df_ind: pd.DataFrame, windows=PRE_SIGNAL_WINDOWS) -> pd.DataFrame:
    """Averages indicators in windows before drawdown peaks."""
    rows = []
    for dd in dd_list:
        pk_ts = pd.Timestamp(dd["peak_date"])
        before = df_ind[df_ind.index < pk_ts]
        row = {"peak_date": pk_ts, "drawdown_pct": dd["drawdown_pct"]}

        for w in windows:
            seg = before.tail(w)
            if len(seg) == 0:
                continue
            row[f"VIX_avg_{w}d"] = seg["VIX"].mean()
            row[f"VIX_max_{w}d"] = seg["VIX"].max()
            row[f"VIX_chg_{w}d"] = ((seg["VIX"].iloc[-1] - seg["VIX"].iloc[0]) / max(seg["VIX"].iloc[0], 0.01))
            row[f"RealVol_{w}d"] = seg["RealVol20"].mean()
            for n in MA_PERIODS:
                row[f"DevSMA{n}_{w}d"] = seg[f"DevSMA{n}"].mean()
                row[f"DevEMA{n}_{w}d"] = seg[f"DevEMA{n}"].mean()
            row[f"AboveSMA50_{w}d"] = seg["Above_SMA50"].mean()
            row[f"AboveSMA200_{w}d"] = seg["Above_SMA200"].mean()
            row[f"BullTrend_{w}d"] = seg["BullTrend"].mean()
        rows.append(row)
    return pd.DataFrame(rows)


def pattern_avg(snap_df: pd.DataFrame) -> dict:
    if snap_df.empty:
        return {}
    num = snap_df.select_dtypes(include=np.number)
    return num.mean().to_dict()


def compute_historical_context(dd_list: list, snap_df: pd.DataFrame,
                               current_dev50: float, current_rsi: float,
                               current_dev200: float) -> dict:
    """Calculates average/max/min expected drawdown based on extension level."""
    if snap_df.empty or len(dd_list) == 0:
        return {"analogues": [], "exp_dd_avg": None, "exp_dd_max": None, "exp_dd_min": None,
                "bucket_label": "Insufficient history"}

    rows = []
    for i, dd in enumerate(dd_list):
        if i < len(snap_df):
            row = snap_df.iloc[i]
            rows.append({
                "drawdown_pct": dd["drawdown_pct"],
                "peak_date": dd["peak_date"],
                "dev50_at_peak": row.get("DevSMA50_10d", np.nan),
                "dev200_at_peak": row.get("DevSMA200_10d", np.nan),
                "rsi_proxy": row.get("VIX_avg_10d", np.nan),
            })

    if not rows:
        return {"analogues": [], "exp_dd_avg": None, "exp_dd_max": None, "exp_dd_min": None,
                "bucket_label": "Insufficient history"}

    df_h = pd.DataFrame(rows)

    def bucket(v):
        if pd.isna(v): return "Unknown"
        if v < 0.02: return "< 2% above SMA50 (low extension)"
        if v < 0.05: return "2–5% above SMA50 (moderate extension)"
        if v < 0.10: return "5–10% above SMA50 (high extension)"
        return "> 10% above SMA50 (extreme extension)"

    cur_bucket = bucket(current_dev50)
    df_h["bucket"] = df_h["dev50_at_peak"].apply(bucket)
    matching = df_h[df_h["bucket"] == cur_bucket]

    if len(matching) == 0:
        matching = df_h

    exp_dd_avg = matching["drawdown_pct"].mean()
    exp_dd_max = matching["drawdown_pct"].max()
    exp_dd_min = matching["drawdown_pct"].min()

    analogues = []
    for _, ev in matching.iterrows():
        analogues.append({
            "peak_date": ev["peak_date"],
            "dev50": ev["dev50_at_peak"],
            "drawdown_pct": ev["drawdown_pct"],
        })

    return {
        "analogues": analogues,
        "exp_dd_avg": round(float(exp_dd_avg), 6) if pd.notna(exp_dd_avg) else None,
        "exp_dd_max": round(float(exp_dd_max), 6) if pd.notna(exp_dd_max) else None,
        "exp_dd_min": round(float(exp_dd_min), 6) if pd.notna(exp_dd_min) else None,
        "bucket_label": cur_bucket,
        "n_events": len(matching),
    }


def build_warning(ticker: str, df_ind: pd.DataFrame, pat: dict,
                  dd_list: list = None, snap_df: pd.DataFrame = None) -> dict:
    """Calculates Portfolio Mean-Reversion Risk warning score (0-100) and signals."""
    if dd_list is None: dd_list = []
    if snap_df is None: snap_df = pd.DataFrame()

    df_valid = df_ind.dropna(subset=["Close"])
    if df_valid.empty:
        return {"ticker": ticker, "score": 0, "level": "BASING", "signals": []}
    latest = df_valid.iloc[-1]

    signals = []
    score = 0

    def sg(key, default=np.nan):
        return float(latest[key]) if key in latest.index and pd.notna(latest[key]) else default

    close_now = sg("Close")
    vix_now = sg("VIX")
    rvol = sg("RealVol20")
    dev50 = sg("DevSMA50")
    dev200 = sg("DevSMA200")
    rsi = sg("RSI14")
    zscore = sg("ZScore20")
    bb_pct = sg("BB_pct")
    roc20 = sg("ROC20")
    roc5 = sg("ROC5")
    consec = sg("ConsecUp", 0)
    from_h252 = sg("FromHigh252", -0.05)

    # 1. Z-Score
    if pd.notna(zscore):
        if zscore >= 2.5:
            signals.append(f"Z-Score={zscore:.2f} — Price {zscore:.1f}σ above 20d mean (EXTREME stretch)")
            score += 28
        elif zscore >= 2.0:
            signals.append(f"Z-Score={zscore:.2f} — Price 2σ+ above 20d mean (very overextended)")
            score += 20
        elif zscore >= 1.5:
            signals.append(f"Z-Score={zscore:.2f} — Price 1.5σ above mean (elevated stretch)")
            score += 12
        elif zscore >= 1.0:
            score += 6
        elif zscore <= -2.0:
            signals.append(f"Z-Score={zscore:.2f} — Price {abs(zscore):.1f}σ BELOW mean (basing)")
            score -= 20
        elif zscore <= -1.5:
            signals.append(f"Z-Score={zscore:.2f} — Price well below 20d mean (compression)")
            score -= 13
        elif zscore <= -1.0:
            score -= 8

    # 2. RSI
    if pd.notna(rsi):
        if rsi >= 80:
            signals.append(f"RSI(14)={rsi:.1f} — EXTREMELY overbought (≥80)")
            score += 24
        elif rsi >= 75:
            signals.append(f"RSI(14)={rsi:.1f} — Strongly overbought (≥75)")
            score += 18
        elif rsi >= 70:
            signals.append(f"RSI(14)={rsi:.1f} — Overbought zone (≥70)")
            score += 12
        elif rsi >= 65:
            score += 6
        elif rsi <= 25:
            signals.append(f"RSI(14)={rsi:.1f} — DEEPLY oversold (≤25)")
            score -= 20
        elif rsi <= 30:
            signals.append(f"RSI(14)={rsi:.1f} — Oversold (≤30)")
            score -= 14
        elif rsi <= 40:
            score -= 8

    # 3. DevSMA50
    if pd.notna(dev50):
        if dev50 >= 0.12:
            signals.append(f"Price +{dev50*100:.1f}% above SMA50 — severe overextension")
            score += 22
        elif dev50 >= 0.08:
            signals.append(f"Price +{dev50*100:.1f}% above SMA50 — high overextension")
            score += 16
        elif dev50 >= 0.05:
            signals.append(f"Price +{dev50*100:.1f}% above SMA50 — moderate stretch")
            score += 10
        elif dev50 >= 0.03:
            score += 5
        elif dev50 <= -0.08:
            signals.append(f"Price {dev50*100:.1f}% BELOW SMA50 — deep compression")
            score -= 18
        elif dev50 <= -0.04:
            signals.append(f"Price {dev50*100:.1f}% below SMA50 — below support")
            score -= 10
        elif dev50 <= -0.02:
            score -= 5

    # 4. DevSMA200
    if pd.notna(dev200):
        if dev200 >= 0.20:
            signals.append(f"Price +{dev200*100:.1f}% above SMA200 — extreme structural stretch")
            score += 20
        elif dev200 >= 0.12:
            signals.append(f"Price +{dev200*100:.1f}% above SMA200 — significant structural stretch")
            score += 13
        elif dev200 >= 0.06:
            score += 7
        elif dev200 <= -0.08:
            signals.append(f"Price {dev200*100:.1f}% below SMA200 — structural damage")
            score -= 15
        elif dev200 <= -0.04:
            score -= 8

    # 5. VIX Complacency
    if pd.notna(vix_now):
        if dev50 > 0.04 and vix_now < 14:
            signals.append(f"⚠ DANGER: VIX={vix_now:.1f} (extreme complacency) + market overextended")
            score += 20
        elif dev50 > 0.02 and vix_now < 16:
            signals.append(f"VIX={vix_now:.1f} (low fear) while market extended")
            score += 13
        elif dev50 > 0.01 and vix_now < 18:
            score += 7
        elif vix_now >= 30:
            signals.append(f"VIX={vix_now:.1f} — Extreme fear already present (downside priced in)")
            score -= 18
        elif vix_now >= 25:
            signals.append(f"VIX={vix_now:.1f} — Elevated fear")
            score -= 10
        elif vix_now >= 20 and dev50 < 0:
            score -= 5

    # 6. ROC
    if pd.notna(roc20):
        if roc20 >= 0.15:
            signals.append(f"20-day return +{roc20*100:.1f}% — parabolic rise")
            score += 16
        elif roc20 >= 0.10:
            signals.append(f"20-day return +{roc20*100:.1f}% — rapid ascent")
            score += 11
        elif roc20 >= 0.05:
            score += 6
        elif roc20 <= -0.12:
            signals.append(f"20-day return {roc20*100:.1f}% — sharp decline")
            score -= 15
        elif roc20 <= -0.06:
            score -= 8

    # 7. Bollinger Bands
    if pd.notna(bb_pct):
        if bb_pct >= 1.10:
            signals.append(f"BB position={bb_pct*100:.0f}% — Price ABOVE upper Bollinger Band")
            score += 12
        elif bb_pct >= 0.90:
            signals.append(f"BB position={bb_pct*100:.0f}% — Price near upper Bollinger Band")
            score += 7
        elif bb_pct <= 0.05:
            signals.append(f"BB position={bb_pct*100:.0f}% — Price at/below lower Bollinger Band")
            score -= 10
        elif bb_pct <= 0.15:
            score -= 5

    # 8. Distance to 52w High
    if pd.notna(from_h252):
        if from_h252 >= -0.005:
            signals.append(f"Price within 0.5% of 52-week high")
            score += 10
        elif from_h252 >= -0.02:
            score += 6
        elif from_h252 <= -0.15:
            signals.append(f"Price {abs(from_h252)*100:.1f}% below 52w high")
            score -= 12
        elif from_h252 <= -0.07:
            score -= 6

    # 9. Consecutive Up Days
    if pd.notna(consec):
        if consec >= 8:
            signals.append(f"{int(consec)} consecutive up days — momentum exhaustion zone")
            score += 10
        elif consec >= 5:
            signals.append(f"{int(consec)} consecutive up days — extended run")
            score += 6
        elif consec >= 3:
            score += 3

    score = max(0, min(100, score))

    if score >= 65:
        level, color = "OVEREXTENDED", "C_RED"
    elif score >= 40:
        level, color = "STRETCHED", "C_YELLOW"
    elif score >= 20:
        level, color = "MODERATE", "C_ORANGE"
    else:
        level, color = "BASING", "C_GREEN"

    hist_ctx = compute_historical_context(dd_list, snap_df, dev50, rsi, dev200)

    above50_str = f"+{dev50*100:.1f}%" if dev50 > 0 else f"{dev50*100:.1f}%"
    above200_str = f"+{dev200*100:.1f}%" if dev200 > 0 else f"{dev200*100:.1f}%"
    narrative = (f"{ticker} is {above50_str} vs SMA50, {above200_str} vs SMA200, "
                 f"RSI {rsi:.0f}, Z-Score {zscore:.2f} — "
                 f"{level} zone (score {score}/100)")

    return {
        "ticker": ticker,
        "as_of_date": latest.name.strftime("%Y-%m-%d") if isinstance(latest.name, datetime) else str(latest.name)[:10],
        "close": round(close_now, 2),
        "vix": round(vix_now, 2) if pd.notna(vix_now) else None,
        "score": score,
        "level": level,
        "color": color,
        "signals": signals,
        "narrative": narrative,
        "rsi": round(rsi, 2) if pd.notna(rsi) else None,
        "zscore": round(zscore, 3) if pd.notna(zscore) else None,
        "bb_pct": round(bb_pct, 3) if pd.notna(bb_pct) else None,
        "roc20": round(roc20, 4) if pd.notna(roc20) else None,
        "roc5": round(roc5, 4) if pd.notna(roc5) else None,
        "consec_up": int(consec),
        "from_h252": round(from_h252, 4) if pd.notna(from_h252) else None,
        "dev_sma9": round(sg("DevSMA9"), 6),
        "dev_sma20": round(sg("DevSMA20"), 6),
        "dev_sma50": round(dev50, 6),
        "dev_sma200": round(dev200, 6),
        "rvol": round(rvol, 6) if pd.notna(rvol) else None,
        "above_sma50": bool(dev50 >= 0),
        "above_sma200": bool(dev200 >= 0),
        "bull_trend": bool(sg("BullTrend", 0) >= 0.5),
        "sma9": round(sg("SMA9"), 4),
        "sma20": round(sg("SMA20"), 4),
        "sma50": round(sg("SMA50"), 4),
        "sma200": round(sg("SMA200"), 4),
        # Historical stats
        "hist_exp_dd_avg": hist_ctx.get("exp_dd_avg"),
        "hist_exp_dd_max": hist_ctx.get("exp_dd_max"),
        "hist_n_events": hist_ctx.get("n_events", 0),
        "hist_bucket": hist_ctx.get("bucket_label", ""),
        "hist_analogues": hist_ctx.get("analogues", []),
    }


def generate_gauge_figure(score: int, level: str, ticker: str, bg_color="#1A1F2E"):
    """
    Renders a semicircular speedometer gauge figure using Matplotlib.
    Outputs a transparent-backed dark figure matching Streamlit card background.
    """
    ZONES = [
        (0, 15, "#70AD47", "NORMAL"),
        (15, 35, "#ED7D31", "CAUTION"),
        (35, 60, "#FFC000", "ELEVATED"),
        (60, 100, "#C00000", "HIGH RISK"),
    ]

    def s2deg(s): return 180.0 - (s / 100.0) * 180.0
    def s2rad(s): return np.radians(s2deg(s))

    # Dark Theme specific styling constants
    text_color = "#E0E0E0"
    tick_mark_color = "#B0B0B0"
    needle_color = "#6366F1"  # Indigo accent

    fig, ax = plt.subplots(figsize=(4.0, 2.6), dpi=130)
    fig.patch.set_facecolor("none")  # Transparent outer figure
    ax.set_facecolor("none")

    ax.set_xlim(-1.55, 1.55)
    ax.set_ylim(-0.72, 1.55)
    ax.set_aspect("equal")
    ax.axis("off")

    # 1. Background ring (light grey/darker grey for dark theme)
    bg = Wedge((0, 0), 1.08, 0, 180, width=0.32,
               facecolor="#2A2F3D", edgecolor="none", zorder=1)
    ax.add_patch(bg)

    # 2. Colored zone wedges
    for z_start, z_end, z_color, _ in ZONES:
        w_patch = Wedge((0, 0), 1.08, s2deg(z_end), s2deg(z_start),
                        width=0.30, facecolor=z_color, edgecolor="none", zorder=2)
        ax.add_patch(w_patch)

    # 3. Thin white separators between zones
    for boundary in [15, 35, 60]:
        ang = s2rad(boundary)
        ax.plot([0.76 * np.cos(ang), 1.10 * np.cos(ang)],
                [0.76 * np.sin(ang), 1.10 * np.sin(ang)],
                color="#1A1F2E", lw=1.5, zorder=3)

    # 4. Inner masking ring to match Card background
    inner = Wedge((0, 0), 0.76, 0, 180, width=0.0,
                  facecolor=bg_color, edgecolor=bg_color, linewidth=0, zorder=3)
    ax.add_patch(inner)
    inner_fill = plt.Circle((0, 0), 0.76, color=bg_color, zorder=3)
    ax.add_patch(inner_fill)

    # 5. Tick marks & scale numbers
    for tick_s in [0, 15, 35, 60, 100]:
        ang = s2rad(tick_s)
        ax.plot([0.72 * np.cos(ang), 1.12 * np.cos(ang)],
                [0.72 * np.sin(ang), 1.12 * np.sin(ang)],
                color=tick_mark_color, lw=2.0, zorder=5)
        ax.text(1.28 * np.cos(ang), 1.28 * np.sin(ang),
                str(tick_s), ha="center", va="center",
                fontsize=7.5, color=text_color, fontweight="bold", zorder=5)

    # 6. Zone labels (inside colored ring)
    for z_start, z_end, _, z_label in ZONES:
        mid_s = (z_start + z_end) / 2
        ang_mid = s2rad(mid_s)
        lx = 0.92 * np.cos(ang_mid)
        ly = 0.92 * np.sin(ang_mid)
        deg_mid = np.degrees(ang_mid)
        rot = deg_mid - 90
        ax.text(lx, ly, z_label, ha="center", va="center",
                fontsize=5.5, color="white", fontweight="bold",
                rotation=rot, zorder=6)

    # 7. Needle pointer
    needle_ang = s2rad(score)
    needle_len = 0.70
    nx = needle_len * np.cos(needle_ang)
    ny = needle_len * np.sin(needle_ang)
    ax.annotate("",
                xy=(nx, ny), xytext=(0.0, 0.0),
                arrowprops=dict(arrowstyle="-|>", color=needle_color,
                                lw=2.5, mutation_scale=16),
                zorder=8)
    bx = -0.10 * np.cos(needle_ang)
    by = -0.10 * np.sin(needle_ang)
    ax.plot([0, bx], [0, by], color=needle_color, lw=2.5, zorder=8)

    # 8. Centre hub
    ax.add_patch(plt.Circle((0, 0), 0.10, color=needle_color, zorder=9))
    ax.add_patch(plt.Circle((0, 0), 0.10, fill=False,
                             edgecolor="white", lw=2.0, zorder=10))

    # 9. Score number text in center
    score_color = {"OVEREXTENDED": "#FF4B4B", "STRETCHED": "#FFA500",
                   "MODERATE": "#FFA500", "BASING": "#00D4AA"}.get(level, text_color)
    ax.text(0, -0.16, str(score), ha="center", va="center",
            fontsize=32, fontweight="bold", color=score_color, zorder=7)
    ax.text(0, -0.40, "/ 100", ha="center", va="center",
            fontsize=9, color="#888888", zorder=7)

    # 10. Risk level badge
    badge_rect = mpatches.FancyBboxPatch((-0.58, -0.62), 1.16, 0.24,
                                         boxstyle="round,pad=0.02",
                                         facecolor=score_color, edgecolor="none",
                                         zorder=7)
    ax.add_patch(badge_rect)
    ax.text(0, -0.50, level, ha="center", va="center",
            fontsize=9.5, fontweight="bold", color="white", zorder=8)

    # 11. Ticker title
    ax.text(0, 1.44, ticker, ha="center", va="center",
            fontsize=18, fontweight="bold", color=text_color, zorder=7)

    plt.tight_layout(pad=0.1)
    return fig


def recalculate_and_cache_market_risk():
    """
    Downloads historical data for SPY, QQQ, IWM, VIX,
    calculates warning scores and drawdowns, and saves to database.
    """
    from src.database.queries import upsert_market_risk_warning

    end_date = datetime.today()
    start_date = end_date - timedelta(days=550)
    analysis_start = end_date - timedelta(days=365)

    # Fetch closes
    price_series = {}
    for tk in TICKERS:
        price_series[tk] = fetch_close(tk, start_date, end_date)

    vix = fetch_close(VIX_TICK, start_date, end_date)
    vix.name = "VIX"

    # Compute indicators
    indicators = {tk: build_indicators(price_series[tk], vix) for tk in TICKERS}

    # Detect drawdowns
    drawdown_map = {tk: detect_drawdowns(price_series[tk], analysis_start=analysis_start) for tk in TICKERS}

    # Enrich drawdowns
    for tk in TICKERS:
        drawdown_map[tk] = enrich_with_next_high(drawdown_map[tk], price_series[tk])

    # Pre-drawdown behavior
    snap_map = {tk: pre_drawdown_snapshot(drawdown_map[tk], indicators[tk]) for tk in TICKERS}
    pattern_map = {tk: pattern_avg(snap_map[tk]) for tk in TICKERS}

    # Calculate warnings and save to DB
    for tk in TICKERS:
        w = build_warning(tk, indicators[tk], pattern_map[tk],
                          dd_list=drawdown_map[tk], snap_df=snap_map[tk])
        # Save to database
        upsert_market_risk_warning(w)


def clear_market_risk_cache():
    """Clears any Streamlit cache for market risk functions."""
    import streamlit as st
    # Just to clear if we use st.cache_data on views loading queries
    try:
        st.cache_data.clear()
    except Exception:
        pass
