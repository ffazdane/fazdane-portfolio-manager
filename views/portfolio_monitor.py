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
    
    .kpi-warning { color: #FFA421; }
    
    .strat-chip {
        background: var(--chip-bg, rgba(255, 255, 255, 0.03));
        border: 1px solid var(--chip-border, rgba(255, 255, 255, 0.08));
        border-radius: 8px;
        padding: 6px 12px;
        display: flex;
        align-items: center;
        gap: 8px;
        transition: all 0.2s ease;
    }
    .strat-chip:hover {
        filter: brightness(1.25);
        transform: translateY(-1px);
        box-shadow: 0 4px 12px var(--chip-border, rgba(255, 255, 255, 0.08));
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
account = st.session_state.get('selected_account')
active_trades = get_active_trades(account)
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
            quotes[u]['atr'] = d.get('atr')

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
raw_positions = []

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
    atr = quote.get('atr')
    
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

    import math
    days_to_put = None
    if pts_to_put is not None and atr is not None and atr > 0:
        ratio = pts_to_put / atr
        days_to_put = math.ceil(ratio) if ratio >= 0 else math.floor(ratio)

    days_to_call = None
    if pts_to_call is not None and atr is not None and atr > 0:
        ratio = pts_to_call / atr
        days_to_call = math.ceil(ratio) if ratio >= 0 else math.floor(ratio)
    
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
        'ATR':           f"{atr:.2f}" if atr is not None else '—',
        'Pts to Put':    f"{pts_to_put:.2f}"  if pts_to_put  is not None else '—',
        'Days to Put':   f"{int(days_to_put)}" if days_to_put is not None else '—',
        'Pts to Call':   f"{pts_to_call:.2f}" if pts_to_call is not None else '—',
        'Days to Call':  f"{int(days_to_call)}" if days_to_call is not None else '—',
        'Credit Recv':   format_currency(data['credit']),
        'P&L $':         format_currency(total_pnl),
        '% Max Profit':  f"{pct_max_profit:.1f}%" if pct_max_profit is not None else '—',
        'Status':        status_label
    })

    raw_positions.append({
        'strategy': strat_name,
        'credit': data['credit'],
        'pnl': total_pnl,
        'dte': dte if dte is not None else 0,
        'status': status_label,
        'underlying': underlying
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

    # ─── KPIs and Strategy Analysis ─────────────────────────────────────────
    import plotly.express as px
    import plotly.graph_objects as go
    import collections

    # Draw KPI cards
    def draw_kpi_card(label, value, is_currency=False, is_neutral=False, invert_color=False):
        if is_currency:
            formatted = f"${value:,.2f}" if value >= 0 else f"-${abs(value):,.2f}"
        else:
            if isinstance(value, float):
                formatted = f"{value:.1f}"
            else:
                formatted = str(value)
                
        color_class = "kpi-neutral"
        if not is_neutral:
            if is_currency:
                if value > 0:
                    color_class = "kpi-positive"
                elif value < 0:
                    color_class = "kpi-negative"
            else:
                try:
                    val_int = int(value)
                    if val_int > 0:
                        if label == "Breached":
                            color_class = "kpi-negative"
                        elif label == "Warnings":
                            color_class = "kpi-warning"
                        else:
                            color_class = "kpi-neutral"
                    else:
                        color_class = "kpi-positive"
                except ValueError:
                    pass
                    
        st.markdown(f"""
            <div class="kpi-card">
                <div class="kpi-label">{label}</div>
                <div class="kpi-value {color_class}">{formatted}</div>
            </div>
        """, unsafe_allow_html=True)

    total_positions = len(raw_positions)
    total_open_pnl = sum(p['pnl'] for p in raw_positions)
    total_credit = sum(p['credit'] for p in raw_positions)
    breached_count = sum(1 for p in raw_positions if 'Breached' in p['status'])
    warning_count = sum(1 for p in raw_positions if 'Warning' in p['status'])
    avg_dte = sum(p['dte'] for p in raw_positions) / total_positions if total_positions > 0 else 0

    st.markdown('<div class="section-header">Portfolio Monitor Overview</div>', unsafe_allow_html=True)
    c1, c2, c3, c4, c5, c6 = st.columns(6)
    with c1:
        draw_kpi_card("Total Positions", total_positions, is_neutral=True)
    with c2:
        draw_kpi_card("Total Open P&L", total_open_pnl, is_currency=True)
    with c3:
        draw_kpi_card("Credit Collected", total_credit, is_currency=True, is_neutral=True)
    with c4:
        draw_kpi_card("Breached", breached_count)
    with c5:
        draw_kpi_card("Warnings", warning_count)
    with c6:
        dte_color_class = "kpi-negative" if avg_dte < 7 else ("kpi-warning" if avg_dte < 21 else "kpi-positive")
        st.markdown(f"""
            <div class="kpi-card">
                <div class="kpi-label">Avg DTE</div>
                <div class="kpi-value {dte_color_class}">{avg_dte:.1f}</div>
            </div>
        """, unsafe_allow_html=True)

    # Strategy Counts Chips
    strat_counts = collections.Counter(p['strategy'] for p in raw_positions)
    if strat_counts:
        chips_html = "<div style='display:flex; flex-wrap:wrap; gap:10px; margin-top:15px; margin-bottom:10px;'>"
        for strat, count in strat_counts.items():
            display_name = strat
            if "Calendar" in strat:
                display_name = "Calendars"
            elif "Diagonal" in strat:
                display_name = "Diagonals"
            elif "Put Credit Spread" in strat:
                display_name = "Put Spreads"
            elif "Call Credit Spread" in strat:
                display_name = "Call Spreads"
            elif "Iron Condor" in strat:
                display_name = "Iron Condors"
            elif "Single Put" in strat:
                display_name = "Single Puts"
            elif "Single Call" in strat:
                display_name = "Single Calls"
                
            color = strategy_color_map.get(strat, "rgba(255,255,255,0.08)")
            parts = color.rsplit(',', 1)
            solid_color = parts[0] + ', 1.0)' if len(parts) > 1 else color
            border_color = parts[0] + ', 0.35)' if len(parts) > 1 else color
            
            chips_html += f'<div class="strat-chip" style="--chip-bg: {color}; --chip-border: {border_color};"><span style="font-weight: 700; color: {solid_color}; font-size: 16px;">{count}</span><span style="font-size: 12px; color: #aaa; text-transform: uppercase; letter-spacing: 0.5px;">{display_name}</span></div>'
        chips_html += "</div>"
        st.markdown(chips_html, unsafe_allow_html=True)

    # Strategy breakdown expander
    with st.expander("📊 Strategy Breakdown & Analytics", expanded=False):
        strategy_groups = collections.defaultdict(list)
        for pos in raw_positions:
            strategy_groups[pos['strategy']].append(pos)
            
        strategy_summary_rows = []
        for strat, pos_list in strategy_groups.items():
            s_pnl = sum(p['pnl'] for p in pos_list)
            s_credit = sum(p['credit'] for p in pos_list)
            s_dte = sum(p['dte'] for p in pos_list) / len(pos_list)
            
            breached = sum(1 for p in pos_list if 'Breached' in p['status'])
            warnings = sum(1 for p in pos_list if 'Warning' in p['status'])
            healthy = len(pos_list) - breached - warnings
            
            status_parts = []
            if breached > 0:
                status_parts.append(f"🔴 {breached} Breached")
            if warnings > 0:
                status_parts.append(f"🟡 {warnings} Warning")
            if healthy > 0:
                status_parts.append(f"🟢 {healthy} Healthy")
            status_summary = ", ".join(status_parts)
            
            strategy_summary_rows.append({
                'Strategy': strat,
                'Positions': len(pos_list),
                'Open P&L': s_pnl,
                'Credit Collected': s_credit,
                'Avg DTE': round(s_dte, 1),
                'Status Summary': status_summary
            })
            
        df_strat = pd.DataFrame(strategy_summary_rows)
        df_strat = df_strat.sort_values(by='Positions', ascending=False).reset_index(drop=True)
        
        st.markdown("#### Strategy Metrics")
        
        def style_strat_df(styler):
            return styler.format({
                'Open P&L': lambda v: f"${v:,.2f}" if v >= 0 else f"-${abs(v):,.2f}",
                'Credit Collected': lambda v: f"${v:,.2f}"
            }).map(
                lambda val: 'color: #00D4AA; font-weight: bold;' if isinstance(val, (int, float)) and val > 0 else (
                    'color: #FF4B4B; font-weight: bold;' if isinstance(val, (int, float)) and val < 0 else ''
                ),
                subset=['Open P&L']
            )
            
        st.dataframe(
            df_strat.style.pipe(style_strat_df),
            use_container_width=True,
            hide_index=True
        )
        
        st.markdown("#### Strategy Visualizations")
        col_chart1, col_chart2 = st.columns(2)
        
        with col_chart1:
            fig_pie = px.pie(
                df_strat, values='Positions', names='Strategy',
                title="Active Positions by Strategy",
                hole=0.4,
                color_discrete_sequence=['#00D4AA', '#6366F1', '#F59E0B', '#EC4899', '#10B981', '#EF4444', '#3B82F6', '#A855F7']
            )
            fig_pie.update_layout(
                plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)',
                font_color='#FAFAFA', height=300,
                margin=dict(t=40, b=10, l=10, r=10)
            )
            st.plotly_chart(fig_pie, use_container_width=True)
            
        with col_chart2:
            fig_bar = go.Figure()
            fig_bar.add_trace(go.Bar(
                y=df_strat['Strategy'],
                x=df_strat['Credit Collected'],
                name='Credit Collected',
                orientation='h',
                marker_color='#00D4AA'
            ))
            fig_bar.add_trace(go.Bar(
                y=df_strat['Strategy'],
                x=df_strat['Open P&L'],
                name='Open P&L',
                orientation='h',
                marker_color='#6366F1'
            ))
            fig_bar.update_layout(
                title="Open P&L vs Credit Collected",
                barmode='group',
                plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)',
                font_color='#FAFAFA', height=300,
                margin=dict(t=40, b=10, l=10, r=10),
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
            )
            st.plotly_chart(fig_bar, use_container_width=True)

    st.markdown('<div class="section-header">Position Monitor Grid</div>', unsafe_allow_html=True)



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

    def highlight_earnings(val):
        if not val or val == '—':
            return ''
        try:
            earn_date = datetime.strptime(val, '%Y-%m-%d').date()
            today = datetime.today().date()
            delta_days = (earn_date - today).days
            if -1 <= delta_days <= 7:
                return 'background-color: rgba(255, 75, 75, 0.35); color: #ff4b4b; font-weight: bold; border: 1px solid #ff4b4b;'
        except Exception:
            pass
        return ''

    def highlight_days_to_pc(val):
        try:
            v = float(val)
            if v < 0:
                return 'color: #ff4b4b; font-weight: bold;'
            elif v < 2:
                return 'color: #ffa421; font-weight: bold;'
            return 'color: #9dff9d;'
        except ValueError:
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
            .map(highlight_earnings, subset=['Earnings'])
            .map(highlight_days_to_pc, subset=['Days to Put', 'Days to Call'])
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
