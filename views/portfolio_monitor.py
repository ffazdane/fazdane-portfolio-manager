"""
Page 9: Portfolio Monitor
A wide, specialized data table focusing on short leg deviations from the current price.
"""

import streamlit as st
import pandas as pd
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.utils.auth import check_password
if not check_password():
    st.stop()

from src.database.queries import get_active_trades, get_trade_legs, get_latest_quotes_batch
from src.utils.option_symbols import calculate_dte
from src.utils.formatting import format_currency


@st.cache_data(ttl=86400)
def fetch_earnings_dates(symbols):
    """Fetch next earnings dates for all equites and cache for 24h."""
    results = {}
    try:
        import yfinance as yf
        for sym in symbols:
            if sym in ['SPX', 'SPY', '^SPX', 'QQQ', 'RUT', 'NDX', 'IWM', 'DIA', 'VIX']:
                continue
            try:
                cal = yf.Ticker(sym).calendar
                if cal and isinstance(cal, dict) and 'Earnings Date' in cal:
                    dates = cal['Earnings Date']
                    if dates and len(dates) > 0:
                        results[sym] = dates[0].strftime('%Y-%m-%d')
            except Exception:
                pass
    except ImportError:
        pass
    return results
st.markdown("""
<style>
    #MainMenu {visibility: hidden;} footer {visibility: hidden;}
    .reportview-container .main .block-container{ padding-top: 2rem; }
    
    /* CSS to mimic the spreadsheet style slightly */
    div[data-testid="stDataFrame"] table {
        font-size: 13px !important;
    }
</style>
""", unsafe_allow_html=True)

st.markdown("## 🦅 FazDane Analytics | Portfolio Monitor <span style='font-size:14px; color:#888; font-weight:normal; margin-left:15px;'>(Source: 🔴 Tastytrade | 🔵 Schwab)</span>", unsafe_allow_html=True)
st.caption("Monitoring short strike safety and deviation distances across all active strategies.")

from datetime import datetime
col1, col2 = st.columns([9, 1], vertical_alignment="bottom")
with col2:
    if st.button("🔄 Refresh", use_container_width=True, help="Fetch latest market data"):
        with st.spinner("Fetching latest data..."):
            st.session_state.last_refresh = datetime.now()
            st.session_state.refresh_msg = "Data successfully refreshed!"
            fetch_earnings_dates.clear()
        st.rerun()

if "refresh_msg" in st.session_state:
    st.success(st.session_state.refresh_msg)
    del st.session_state.refresh_msg

# Fetch Data
active_trades = get_active_trades()
underlyings = list(set([t['underlying'] for t in active_trades])) if active_trades else []
quotes = get_latest_quotes_batch(underlyings)

if underlyings:
    with st.spinner("Fetching live market quotes..."):
        from src.market.tastytrade_client import get_tastytrade_session, get_market_quotes_batch
        from src.market.yahoo_provider import YahooProvider
        
        # 1. Try Tastytrade API
        tt_session, tt_error = get_tastytrade_session()
        fetched_tt = {}
        tt_prices = {}   # Track what TT actually returned
        if tt_session:
            fetched_tt, _ = get_market_quotes_batch(tt_session, underlyings)
            for u in underlyings:
                q = fetched_tt.get(u)
                if q and q.get('option_mark'):
                    if u not in quotes: quotes[u] = {}
                    quotes[u]['underlying_price'] = q['option_mark']
                    tt_prices[u] = q['option_mark']
        
        # 2. Add Yahoo Finance metrics (Current Px fallback + Net Change)
        yp = YahooProvider()
        daily_metrics = yp.get_daily_metrics_batch(underlyings)
        for u, d in daily_metrics.items():
            if u not in quotes: quotes[u] = {}
            if not quotes[u].get('underlying_price'):
                quotes[u]['underlying_price'] = d.get('price')
            quotes[u]['net_change'] = d.get('net_change')

    # ── Data Source Status Bar ──────────────────────────────────────────
    tt_count  = len(tt_prices)
    yah_count = sum(1 for u in underlyings
                    if u not in tt_prices and quotes.get(u, {}).get('underlying_price'))
    no_count  = len(underlyings) - tt_count - yah_count

    if tt_session:
        conn_badge = (
            '<span style="background:#00D4AA22;color:#00D4AA;border:1px solid #00D4AA55;'
            'padding:3px 12px;border-radius:20px;font-size:12px;font-weight:700;">'
            'LIVE &mdash; tastytrade</span>'
        )
    else:
        conn_badge = (
            '<span style="background:#FFA42122;color:#FFA421;border:1px solid #FFA42155;'
            'padding:3px 12px;border-radius:20px;font-size:12px;font-weight:700;">'
            'DELAYED &mdash; Yahoo Finance</span>'
        )

    src_pills = ""
    if tt_count:
        src_pills += (f'<span style="background:#00D4AA22;color:#00D4AA;border:1px solid '
                      f'#00D4AA44;padding:2px 10px;border-radius:14px;font-size:11px;'
                      f'margin-right:6px;">&#9679; {tt_count} live</span>')
    if yah_count:
        src_pills += (f'<span style="background:#FFA42122;color:#FFA421;border:1px solid '
                      f'#FFA42144;padding:2px 10px;border-radius:14px;font-size:11px;'
                      f'margin-right:6px;">&#9679; {yah_count} Yahoo</span>')
    if no_count:
        src_pills += (f'<span style="background:#FF4B4B22;color:#FF4B4B;border:1px solid '
                      f'#FF4B4B44;padding:2px 10px;border-radius:14px;font-size:11px;">'
                      f'&#10005; {no_count} missing</span>')

    st.markdown(f"""
    <div style="display:flex;align-items:center;gap:12px;
                background:#1A1F2E;border:1px solid rgba(255,255,255,0.07);
                border-radius:10px;padding:10px 18px;margin-bottom:16px;">
        <div style="font-size:12px;color:#888;margin-right:4px;">Data source:</div>
        {conn_badge}
        <div style="flex:1;"></div>
        {src_pills}
    </div>
    """, unsafe_allow_html=True)

    with st.expander("Per-symbol price sources", expanded=False):
        if tt_error and not tt_session:
            st.warning(f"Tastytrade: {tt_error}")
        rows = []
        for u in sorted(underlyings):
            q  = quotes.get(u, {})
            px = q.get('underlying_price')
            nc = q.get('net_change')
            if u in tt_prices:
                src = "Live (tastytrade)"
            elif px:
                src = "Delayed (Yahoo Finance)"
            else:
                src = "No price"
            rows.append({'Symbol': u, 'Source': src,
                         'Price': f"{px:.2f}" if px else 'n/a',
                         'Net Chg': f"{nc:+.2f}" if nc is not None else 'n/a'})
        if rows:
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    # ───────────────────────────────────────────────────────────────────────

# Fetch earnings for display
earnings_dates = fetch_earnings_dates(underlyings)

if not active_trades:
    st.info("No active trades found. Import data to populate the monitor.")
    st.stop()

def _safe(row, key, default=None):
    try:
        val = row[key]
        return val if val is not None else default
    except (KeyError, IndexError):
        return default

# Aggregate all open legs by (Underlying, TradeID) so calendar spreads
# — which have short + long legs at different expiries — appear on ONE row.
grouped_legs = {}

for trade in active_trades:
    tid = trade['trade_id']
    legs = get_trade_legs(tid)

    # Calculate this trade's pnl info
    realized   = _safe(trade, 'realized_pnl', 0) or 0
    unrealized = _safe(trade, 'unrealized_pnl', 0) or 0
    t_pnl  = realized + unrealized
    t_cred = (_safe(trade, 'entry_credit_debit', 0) or 0) * 100
    t_max  = _safe(trade, 'max_profit', 0) or 0

    for leg in legs:
        if leg['status'] != 'OPEN' or not leg['expiry']:
            continue

        key = (leg['underlying'], tid)          # ← group by trade, not by expiry
        if key not in grouped_legs:
            grouped_legs[key] = {
                'broker': _safe(trade, 'broker', ''),
                'legs': [],
                'pnl': 0,
                'credit': 0,
                'max_profit': 0,
                'strategies': set(),
                'processed_trades': set()
            }

        grouped_legs[key]['legs'].append(leg)
        grouped_legs[key]['strategies'].add(trade['strategy_type'].replace('_', ' ').title())

        # Only add trade-level PNL once per group
        if tid not in grouped_legs[key]['processed_trades']:
            grouped_legs[key]['pnl']        += t_pnl
            grouped_legs[key]['credit']     += t_cred
            grouped_legs[key]['max_profit'] += t_max
            grouped_legs[key]['processed_trades'].add(tid)

table_data = []

for (underlying, tid), data in grouped_legs.items():
    legs = data['legs']

    # ── Classify legs by option type + side ──────────────────────────────
    put_long_legs   = [l for l in legs if l['option_type'] == 'P' and l['side'] == 'LONG'  and l['strike']]
    put_short_legs  = [l for l in legs if l['option_type'] == 'P' and l['side'] == 'SHORT' and l['strike']]
    call_short_legs = [l for l in legs if l['option_type'] == 'C' and l['side'] == 'SHORT' and l['strike']]
    call_long_legs  = [l for l in legs if l['option_type'] == 'C' and l['side'] == 'LONG'  and l['strike']]

    put_longs   = [l['strike'] for l in put_long_legs]
    put_shorts  = [l['strike'] for l in put_short_legs]
    call_shorts = [l['strike'] for l in call_short_legs]
    call_longs  = [l['strike'] for l in call_long_legs]

    # ── Safe qty helper (sqlite3.Row has no .get()) ────────────────────────
    def _safe_qty(leg):
        try:
            v = leg['qty_open']
            return v if v is not None else 0
        except Exception:
            return 0

    qty_long_put   = sum(_safe_qty(l) for l in put_long_legs)
    qty_short_put  = sum(_safe_qty(l) for l in put_short_legs)
    qty_short_call = sum(_safe_qty(l) for l in call_short_legs)
    qty_long_call  = sum(_safe_qty(l) for l in call_long_legs)

    # ── Strikes ───────────────────────────────────────────────────────────
    put_short_strike  = max(put_shorts)  if put_shorts  else None
    put_long_strike   = min(put_longs)   if put_longs   else None
    call_short_strike = min(call_shorts) if call_shorts else None
    call_long_strike  = max(call_longs)  if call_longs  else None

    has_short = put_short_strike or call_short_strike
    has_long  = put_long_strike  or call_long_strike

    # Skip rows with absolutely no option legs
    if not has_short and not has_long:
        continue

    # ── Expiry logic: near = short leg expiry, far = long leg expiry ──────
    # For calendars the short and long legs have DIFFERENT expiries.
    # We use the nearest expiry for DTE (that's the at-risk leg).
    all_expiries = sorted(set(l['expiry'] for l in legs if l['expiry']))
    near_expiry  = all_expiries[0]  if all_expiries else None
    far_expiry   = all_expiries[-1] if len(all_expiries) > 1 else None   # None for same-expiry spreads
    expiry       = near_expiry      # used for DTE and display

    dte = calculate_dte(expiry)
    quote = quotes.get(underlying, {})
    current_price = quote.get('underlying_price')
    
    # ── Distance to strike ────────────────────────────────────────────────
    # Convention: positive = price hasn't reached the strike (OTM / safe)
    #             negative = price has passed the strike   (ITM / breached)
    #
    # PUT  distance: price - strike  (↑ positive when price is above put strike)
    # CALL distance: strike - price  (↑ positive when price is below call strike)
    #
    # For spreads   : use the SHORT (inner) strike — that's the at-risk level.
    # For single leg: fall back to the LONG strike so the column is never blank.
    if current_price and put_short_strike:
        pts_to_put = current_price - put_short_strike
    elif current_price and put_long_strike:
        pts_to_put = current_price - put_long_strike   # long put: OTM=+, ITM=-
    else:
        pts_to_put = None

    if current_price and call_short_strike:
        pts_to_call = call_short_strike - current_price
    elif current_price and call_long_strike:
        pts_to_call = call_long_strike - current_price  # long call: OTM=+, ITM=-
    else:
        pts_to_call = None
    
    total_pnl = data['pnl']
    max_p = data['max_profit']
    pct_max_profit = (total_pnl / max_p * 100) if (max_p and max_p > 0) else None
    
    # Status label
    if not has_short and has_long:
        status_label = "☑️ Active (Long)"
    elif has_short and has_long and far_expiry:
        # Both legs open at different expiries → full calendar position
        status_label = "☑️ Inside"
    else:
        status_label = "☑️ Inside"
    if current_price:
        if call_short_strike and current_price >= call_short_strike:
            status_label = "⚠️ Breached (Call)"
        elif put_short_strike and current_price <= put_short_strike:
            status_label = "⚠️ Breached (Put)"
        elif pts_to_call and pts_to_call > 0 and pts_to_call < (0.02 * current_price):
            status_label = "🟡 Warning (Call)"
        elif pts_to_put and pts_to_put > 0 and pts_to_put < (0.02 * current_price):
            status_label = "🟡 Warning (Put)"
            
    # Determine synthetic strategy name if multiple were combined
    strat_name = " / ".join(list(data['strategies']))
    if len(data['strategies']) > 1 and put_short_strike and call_short_strike:
        strat_name = "Iron Condor (Synthetic)"
        
    net_change = quote.get('net_change')

    raw_broker = data['broker'].lower()
    broker_dot = '🔴' if 'tasty' in raw_broker else ('🔵' if 'schwab' in raw_broker else '⚪')
    
    # Build qty strings — '0' when no contracts of that type
    def _qty(n): return str(int(n)) if n is not None else '0'
    def _strike(v): return f"{v:.2f}" if v else '—'

    table_data.append({
        'Source':        broker_dot,
        'Symbol':        underlying,
        'Strategy':      strat_name,
        'Expiry':        expiry,
        'Far Expiry':    far_expiry if far_expiry else '—',
        'DTE':           dte if dte is not None else 0,
        'Earnings':      earnings_dates.get(underlying, '—'),
        # ── PUT side ───────────────────────────────────────────
        'P Long Str':    _strike(put_long_strike),
        'P Long Qty':    _qty(qty_long_put),
        'P Short Str':   _strike(put_short_strike),
        'P Short Qty':   _qty(qty_short_put),
        # ── CALL side ──────────────────────────────────────────
        'C Short Str':   _strike(call_short_strike),
        'C Short Qty':   _qty(qty_short_call),
        'C Long Str':    _strike(call_long_strike),
        'C Long Qty':    _qty(qty_long_call),
        # ── Market / Risk ──────────────────────────────────────
        'Current Px':    f"{current_price:.2f}" if current_price else '—',
        'Net Change':    f"{net_change:+.2f}" if net_change is not None else '—',
        'Pts to Put':    f"{pts_to_put:.2f}"  if pts_to_put  is not None else '—',
        'Pts to Call':   f"{pts_to_call:.2f}" if pts_to_call is not None else '—',
        'Credit Recv':   format_currency(data['credit']),
        'P&L $':         format_currency(total_pnl),
        '% Max Profit':  f"{pct_max_profit:.1f}%" if pct_max_profit is not None else '—',
        'Status':        status_label
    })

if table_data:
    df = pd.DataFrame(table_data)
    if 'DTE' in df.columns:
        df = df.sort_values('DTE', ascending=True).reset_index(drop=True)

    # ── Strategy colour palette ─────────────────────────────────────────────
    # Each unique strategy gets a distinct semi-transparent background so rows
    # are visually grouped at a glance.
    STRATEGY_PALETTE = [
        "rgba(0, 212, 170, 0.12)",    # teal
        "rgba(99, 102, 241, 0.15)",   # indigo
        "rgba(245, 158, 11, 0.13)",   # amber
        "rgba(236, 72, 153, 0.13)",   # pink
        "rgba(16, 185, 129, 0.13)",   # emerald
        "rgba(239, 68, 68, 0.12)",    # red
        "rgba(59, 130, 246, 0.15)",   # blue
        "rgba(168, 85, 247, 0.14)",   # purple
        "rgba(251, 191, 36, 0.13)",   # yellow
        "rgba(20, 184, 166, 0.13)",   # cyan
    ]

    unique_strategies = list(dict.fromkeys(df['Strategy'].tolist()))
    strategy_color_map = {
        strat: STRATEGY_PALETTE[i % len(STRATEGY_PALETTE)]
        for i, strat in enumerate(unique_strategies)
    }

    def highlight_strategy_row(row):
        """Apply a per-strategy background colour to every cell in the row."""
        color = strategy_color_map.get(row['Strategy'], '')
        base = f'background-color: {color};' if color else ''
        return [base] * len(row)

    def highlight_status(val):
        if 'Breached' in str(val):
            return 'background-color: rgba(255, 75, 75, 0.35); color: #ff4b4b; font-weight:bold;'
        elif 'Warning' in str(val):
            return 'background-color: rgba(255, 164, 33, 0.30); color: #ffa421; font-weight:bold;'
        return ''

    def highlight_distances(val):
        try:
            v = float(val)
            if v < 0:
                return 'color: #ff4b4b; font-weight: bold;'
            elif v < 10:
                return 'color: #ffa421;'
            return 'color: #9dff9d;'
        except ValueError:
            return ''

    def highlight_daily(row):
        styles = [''] * len(row)
        try:
            nc = str(row['Net Change'])
            color = ''
            if nc.startswith('+'):
                color = 'color: #00D4AA; font-weight: bold;'
            elif nc.startswith('-'):
                color = 'color: #FF4B4B; font-weight: bold;'

            if color:
                px_idx = df.columns.get_loc('Current Px')
                nc_idx = df.columns.get_loc('Net Change')
                styles[px_idx] = color
                styles[nc_idx] = color
        except Exception:
            pass
        return styles

    def highlight_qty(val):
        """Dim zero-quantity cells so non-zero stands out."""
        try:
            if int(val) == 0:
                return 'color: #555; font-style: italic;'
            return 'color: #e0e0e0; font-weight: bold;'
        except (ValueError, TypeError):
            return ''

    def styling(styler):
        qty_cols = [c for c in df.columns if 'Qty' in c]
        return (
            styler
            .apply(highlight_strategy_row, axis=1)
            .apply(highlight_daily, axis=1)
            .map(highlight_status, subset=['Status'])
            .map(highlight_distances, subset=['Pts to Put', 'Pts to Call'])
            .map(highlight_qty, subset=qty_cols)
        )

    # ── Legend: strategy → colour ───────────────────────────────────────────
    legend_html = "<div style='display:flex;flex-wrap:wrap;gap:8px;margin-bottom:10px;'>"
    for strat, color in strategy_color_map.items():
        legend_html += (
            f"<span style='background:{color};border:1px solid rgba(255,255,255,0.15);"
            f"padding:3px 12px;border-radius:20px;font-size:12px;color:#ddd;'>"
            f"{strat}</span>"
        )
    legend_html += "</div>"
    st.markdown(legend_html, unsafe_allow_html=True)

    # ── Render grid — taller height so it fills the bottom of the page ──────
    num_rows = len(df)
    row_height = 35   # px per data row
    header_height = 38
    min_height = 600   # always fill a meaningful portion of the screen
    max_height = 1000
    computed_height = min(max_height, max(min_height, header_height + num_rows * row_height + 20))

    st.dataframe(
        df.style.pipe(styling),
        use_container_width=True,
        hide_index=True,
        height=computed_height,
    )
else:
    st.info("No active positions found. Import data to populate the monitor.")
