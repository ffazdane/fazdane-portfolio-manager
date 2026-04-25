"""
Page 4: History Log
All closed/expired trades with realized results and journal review.
"""

import streamlit as st
import pandas as pd
import plotly.express as px
from datetime import datetime
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.utils.auth import check_password
if not check_password():
    st.stop()

from src.database.queries import get_historical_trades, get_pnl_by_strategy, get_pnl_by_ticker
from src.utils.formatting import (
    format_currency, format_date, status_badge, strategy_display_name, format_percentage
)
from src.journal.journal_manager import get_note_count


st.markdown("""
<style> #MainMenu {visibility: hidden;} footer {visibility: hidden;} </style>
""", unsafe_allow_html=True)

st.markdown("## 📜 History Log")

account = st.session_state.get('selected_account')

# Filters
f1, f2, f3, f4 = st.columns(4)
with f1:
    outcome_filter = st.selectbox("Outcome", ["All", "Wins", "Losses", "Expired Worthless"])
with f2:
    strategy_filter = st.selectbox(
        "Strategy", ["All"] + [
            'PUT_CREDIT_SPREAD', 'CALL_CREDIT_SPREAD', 'IRON_CONDOR',
            'CALENDAR_SPREAD', 'SINGLE_PUT', 'SINGLE_CALL', 'CUSTOM'
        ],
        format_func=lambda x: "All" if x == "All" else strategy_display_name(x),
        key="history_strategy"
    )
with f3:
    sort_option = st.selectbox("Sort By", [
        "Close Date (Newest)", "Close Date (Oldest)", "P&L (Best)", "P&L (Worst)",
        "Days Held", "Underlying (A-Z)"
    ])
with f4:
    search = st.text_input("Search", placeholder="Ticker...", key="history_search")

# Get trades
strategy = strategy_filter if strategy_filter != "All" else None
trades = get_historical_trades(account=account, strategy=strategy)

# Convert to dicts
trades = [dict(t) for t in trades]

# Apply outcome filter
if outcome_filter == "Wins":
    trades = [t for t in trades if t.get('result_tag') == 'WIN' or t.get('status') == 'EXPIRED_WORTHLESS']
elif outcome_filter == "Losses":
    trades = [t for t in trades if t.get('result_tag') == 'LOSS']
elif outcome_filter == "Expired Worthless":
    trades = [t for t in trades if t.get('status') == 'EXPIRED_WORTHLESS']

if search:
    trades = [t for t in trades if search.upper() in (t.get('underlying', '') or '').upper()]

# Sort
if sort_option == "Close Date (Newest)":
    trades.sort(key=lambda x: x.get('close_date', '') or '', reverse=True)
elif sort_option == "Close Date (Oldest)":
    trades.sort(key=lambda x: x.get('close_date', '') or '')
elif sort_option == "P&L (Best)":
    trades.sort(key=lambda x: x.get('realized_pnl', 0) or 0, reverse=True)
elif sort_option == "P&L (Worst)":
    trades.sort(key=lambda x: x.get('realized_pnl', 0) or 0)
elif sort_option == "Days Held":
    trades.sort(key=lambda x: x.get('days_held', 0) or 0, reverse=True)
elif sort_option == "Underlying (A-Z)":
    trades.sort(key=lambda x: x.get('underlying', ''))

# Summary stats
st.divider()
if trades:
    total_pnl = sum(t.get('realized_pnl', 0) or 0 for t in trades)
    wins = sum(1 for t in trades if (t.get('result_tag') == 'WIN' or t.get('status') == 'EXPIRED_WORTHLESS'))
    losses = sum(1 for t in trades if t.get('result_tag') == 'LOSS')
    avg_days = sum(t.get('days_held', 0) or 0 for t in trades) / len(trades) if trades else 0

    s1, s2, s3, s4, s5 = st.columns(5)
    with s1:
        st.metric("Total Trades", len(trades))
    with s2:
        color = "normal" if total_pnl >= 0 else "inverse"
        st.metric("Total Realized P&L", format_currency(total_pnl), delta_color=color)
    with s3:
        wr = (wins / (wins + losses) * 100) if (wins + losses) > 0 else 0
        st.metric("Win Rate", f"{wr:.0f}%", delta=f"{wins}W / {losses}L")
    with s4:
        st.metric("Avg Days Held", f"{avg_days:.0f}")
    with s5:
        avg_pnl = total_pnl / len(trades) if trades else 0
        st.metric("Avg P&L/Trade", format_currency(avg_pnl))

    st.divider()

    # Display table
    rows = []
    for t in trades:
        pnl = t.get('realized_pnl', 0) or 0
        max_loss = abs(t.get('max_loss', 0) or 0) or 1
        ror = (pnl / max_loss * 100) if max_loss > 0 else 0
        note_count = t.get('note_count', 0)

        rows.append({
            'ID': t['trade_id'],
            'Status': status_badge(t['status']),
            'Underlying': t['underlying'],
            'Strategy': strategy_display_name(t['strategy_type']),
            'Open': format_date(t['open_date']),
            'Close': format_date(t.get('close_date')),
            'Days': t.get('days_held', 0),
            'Realized P&L': pnl,
            'RoR': f"{ror:.1f}%",
            'Exit Type': t['status'].replace('_', ' ').title(),
            'Result': '✅' if t.get('result_tag') == 'WIN' else '❌' if t.get('result_tag') == 'LOSS' else '—',
            'Notes': f"📝{note_count}" if note_count else '—',
            'Rolled': '🔄' if t.get('parent_trade_id') or t.get('roll_group_id') else '—',
        })

    df = pd.DataFrame(rows)

    # Format P&L column with color
    st.dataframe(
        df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Realized P&L": st.column_config.NumberColumn(format="$%.2f"),
            "ID": st.column_config.NumberColumn(width="small"),
        }
    )

    # Click to view detail
    st.caption("💡 Select a trade ID and go to Trade Detail page for full journal review.")

    # Performance analytics
    st.divider()
    st.markdown("### 📊 Performance Analytics")

    pc1, pc2 = st.columns(2)
    with pc1:
        st.markdown("**P&L by Strategy**")
        strategy_pnl = get_pnl_by_strategy(account)
        if strategy_pnl:
            df_s = pd.DataFrame([dict(r) for r in strategy_pnl])
            df_s['Strategy'] = df_s['strategy_type'].apply(strategy_display_name)
            fig = px.bar(df_s, x='Strategy', y='total_pnl', color='total_pnl',
                        color_continuous_scale=['#FF4B4B', '#FFA500', '#00D4AA'])
            fig.update_layout(plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)',
                            font_color='#FAFAFA', height=300, showlegend=False, coloraxis_showscale=False)
            st.plotly_chart(fig, use_container_width=True)

    with pc2:
        st.markdown("**P&L by Ticker**")
        ticker_pnl = get_pnl_by_ticker(account)
        if ticker_pnl:
            df_t = pd.DataFrame([dict(r) for r in ticker_pnl])
            fig = px.bar(df_t, x='underlying', y='total_pnl', color='total_pnl',
                        color_continuous_scale=['#FF4B4B', '#FFA500', '#00D4AA'])
            fig.update_layout(plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)',
                            font_color='#FAFAFA', height=300, showlegend=False, coloraxis_showscale=False)
            st.plotly_chart(fig, use_container_width=True)

    # Quick Actions
    st.divider()
    st.markdown("### 🔄 Trade Recovery")
    st.caption("Accidentally archived a trade? Reactivate it to push it back to the Active Portfolio.")
    
    rc1, rc2 = st.columns([1, 4])
    with rc1:
        react_id = int(st.number_input("Trade ID", min_value=1, step=1, key="react_id_input"))
    with rc2:
        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("Reactivate Trade", use_container_width=False, key="btn_react_trade"):
            from src.database.queries import update_trade, get_trade_legs, update_trade_leg
            try:
                # 1. Open the Master Trade
                update_trade(react_id, {'status': 'ACTIVE', 'close_date': None, 'realized_pnl': 0})
                
                # 2. Iterate and open its legs
                legs = get_trade_legs(react_id)
                opened_legs = 0
                for l in legs:
                    update_trade_leg(l['leg_id'], {'status': 'OPEN', 'qty_closed': 0, 'exit_price': 0})
                    opened_legs += 1
                    
                st.success(f"Trade #{react_id} and {opened_legs} legs are now fully active again!")
            except Exception as e:
                st.error(f"Error reactivating: {e}")
else:
    st.info("No closed trades found yet. Trades will appear here when positions are fully closed, expired, or assigned.")
