"""
Page 2: Active Portfolio
All open-risk trades with sortable/filterable table and quick note entry.
"""

import streamlit as st
import pandas as pd
from datetime import datetime
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.database.schema import init_database
from src.database.queries import get_active_trades, get_trade_legs
from src.utils.formatting import (
    format_currency, format_pnl_html, format_date, format_dte,
    status_badge, strategy_display_name, format_delta, format_percentage
)
from src.utils.option_symbols import calculate_dte
from src.journal.journal_manager import add_journal_entry

st.set_page_config(page_title="Active Portfolio | Portfolio Manager", page_icon="📈", layout="wide")
from src.utils.branding import setup_branding
setup_branding()
init_database()

# Check and transition expired trades to history log on load
from src.engine.lifecycle_manager import check_and_update_expired_trades
check_and_update_expired_trades()

st.markdown("""
<style>
    #MainMenu {visibility: hidden;} footer {visibility: hidden;}
    .trade-row { padding: 8px 0; border-bottom: 1px solid rgba(255,255,255,0.05); }
</style>
""", unsafe_allow_html=True)

st.markdown("## 📈 Active Portfolio")

account = st.session_state.get('selected_account')

# Filters
col1, col2, col3 = st.columns([2, 2, 2])
with col1:
    strategy_filter = st.selectbox(
        "Strategy",
        ["All"] + [
            'PUT_CREDIT_SPREAD', 'CALL_CREDIT_SPREAD', 'IRON_CONDOR',
            'CALENDAR_SPREAD', 'DIAGONAL_SPREAD', 'SINGLE_PUT', 'SINGLE_CALL', 'CUSTOM'
        ],
        format_func=lambda x: "All Strategies" if x == "All" else strategy_display_name(x)
    )
with col2:
    sort_by = st.selectbox("Sort By", [
        "Open Date (Newest)", "Open Date (Oldest)", "DTE (Nearest)",
        "Unrealized P&L", "Underlying (A-Z)"
    ])
with col3:
    search = st.text_input("Search Underlying", placeholder="e.g. SPY, AAPL")

# Get trades
trades = get_active_trades(account)

# Apply filters
if strategy_filter != "All":
    trades = [t for t in trades if t['strategy_type'] == strategy_filter]
if search:
    trades = [t for t in trades if search.upper() in (t['underlying'] or '').upper()]

# Build display data
trade_rows = []
for trade in trades:
    legs = get_trade_legs(trade['trade_id'])
    
    # Calculate DTE from nearest leg
    min_dte = None
    short_strike = None
    long_strike = None
    expiry = None
    
    for leg in legs:
        dte = calculate_dte(leg['expiry'])
        if dte is not None and (min_dte is None or dte < min_dte):
            min_dte = dte
            expiry = leg['expiry']
        if leg['side'] == 'SHORT' and leg['strike']:
            short_strike = leg['strike']
        if leg['side'] == 'LONG' and leg['strike']:
            long_strike = leg['strike']

    dte_str, dte_severity = format_dte(min_dte)

    # Safely access row fields (sqlite3.Row doesn't support .get())
    def _safe(row, key, default=None):
        try:
            val = row[key]
            return val if val is not None else default
        except (KeyError, IndexError):
            return default

    trade_rows.append({
        'trade_id': trade['trade_id'],
        'Status': status_badge(trade['status']),
        'Underlying': trade['underlying'],
        'Strategy': strategy_display_name(trade['strategy_type']),
        'Open Date': format_date(trade['open_date']),
        'Expiry': format_date(expiry) if expiry else '—',
        'DTE': min_dte if min_dte is not None else 999,
        'DTE_display': dte_str,
        'Entry': format_currency((trade['entry_credit_debit'] or 0) * 100),
        'Unrealized P&L': _safe(trade, 'unrealized_pnl', 0),
        'Max Profit': format_currency(_safe(trade, 'max_profit')),
        'Max Loss': format_currency(_safe(trade, 'max_loss')),
        'Short Strike': f"${short_strike:.0f}" if short_strike else '—',
        'Long Strike': f"${long_strike:.0f}" if long_strike else '—',
        'Legs': _safe(trade, 'leg_count', len(legs)),
        'Notes': f"📝{_safe(trade, 'note_count', 0)}" if _safe(trade, 'note_count', 0) > 0 else '—',
    })

# Sort
if sort_by == "Open Date (Newest)":
    trade_rows.sort(key=lambda x: x.get('Open Date', ''), reverse=True)
elif sort_by == "Open Date (Oldest)":
    trade_rows.sort(key=lambda x: x.get('Open Date', ''))
elif sort_by == "DTE (Nearest)":
    trade_rows.sort(key=lambda x: x['DTE'])
elif sort_by == "Unrealized P&L":
    trade_rows.sort(key=lambda x: x['Unrealized P&L'])
elif sort_by == "Underlying (A-Z)":
    trade_rows.sort(key=lambda x: x['Underlying'])

# Display count
st.caption(f"Showing {len(trade_rows)} active trades")

if trade_rows:
    # Display table
    for row in trade_rows:
        with st.container():
            cols = st.columns([0.5, 1.2, 1.5, 1, 1, 0.7, 1, 1, 1, 0.8, 0.5])
            
            with cols[0]:
                st.write(row['Status'])
            with cols[1]:
                st.markdown(f"**{row['Underlying']}**")
            with cols[2]:
                st.caption(row['Strategy'])
            with cols[3]:
                st.caption(f"Opened: {row['Open Date']}")
            with cols[4]:
                st.caption(f"Exp: {row['Expiry']}")
            with cols[5]:
                dte_color = "#FF4B4B" if row['DTE'] <= 7 else "#FFA500" if row['DTE'] <= 21 else "#00D4AA"
                st.markdown(f'<span style="color: {dte_color}; font-weight: 600;">{row["DTE_display"]}</span>', 
                           unsafe_allow_html=True)
            with cols[6]:
                st.caption(f"Entry: {row['Entry']}")
            with cols[7]:
                pnl = row['Unrealized P&L']
                color = "#00D4AA" if pnl >= 0 else "#FF4B4B"
                st.markdown(f'<span style="color: {color}; font-weight: 600;">${pnl:+,.2f}</span>',
                           unsafe_allow_html=True)
            with cols[8]:
                st.caption(f"S: {row['Short Strike']} | L: {row['Long Strike']}")
            with cols[9]:
                st.caption(row['Notes'])
            with cols[10]:
                if st.button("🔍", key=f"detail_{row['trade_id']}", help="View trade details"):
                    st.session_state.selected_trade_id = row['trade_id']
                    st.switch_page("pages/3_🔍_Trade_Detail.py")

        st.markdown('<hr style="margin: 2px 0; border-color: rgba(255,255,255,0.05);">', 
                   unsafe_allow_html=True)

    # Quick note entry
    st.divider()
    st.markdown("**Quick Journal Entry**")
    qn_col1, qn_col2, qn_col3 = st.columns([2, 4, 1])
    with qn_col1:
        trade_options = {row['trade_id']: f"{row['Underlying']} - {row['Strategy']}" for row in trade_rows}
        selected_trade = st.selectbox("Select Trade", options=trade_options.keys(),
                                       format_func=lambda x: trade_options[x], key="qn_trade_select")
    with qn_col2:
        if "qn_clear_ticker" not in st.session_state:
            st.session_state.qn_clear_ticker = 0
            
        note_text = st.text_input("Add a quick note", 
                                  placeholder="e.g. Monitoring closely, near profit target...", 
                                  key=f"qn_input_{selected_trade}_{st.session_state.qn_clear_ticker}")
    with qn_col3:
        st.write("")  # Spacer
        if st.button("💾 Save", key="save_quick_note"):
            if note_text:
                add_journal_entry(selected_trade, note_text, 'general')
                st.success("Note saved!")
                st.session_state.qn_clear_ticker += 1
                st.rerun()

    from src.journal.journal_manager import get_trade_journal
    notes = get_trade_journal(selected_trade)
    if notes:
        st.markdown(f"**Past Notes for {trade_options[selected_trade]}**")
        with st.container(height=200):
            for note in notes:
                n_dict = dict(note)
                timestamp = n_dict.get('timestamp', '')
                dt_str = str(timestamp).replace('T', ' ')[:16] if timestamp else 'Unknown Time'
                
                note_type = n_dict.get('note_type', 'general')
                note_text = n_dict.get('note_text', '')
                
                st.markdown(f"**{dt_str}**  &mdash;  *{str(note_type).capitalize()}*<br>{note_text}", unsafe_allow_html=True)
                st.markdown('<hr style="margin: 5px 0; border-color: rgba(255,255,255,0.05);">', unsafe_allow_html=True)
else:
    st.info("No active trades found. Import broker data from the **Imports** page to get started.")
