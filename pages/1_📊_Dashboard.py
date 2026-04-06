"""
Page 1: Dashboard
Portfolio overview with KPIs, charts, and alerts summary.
"""

import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
import pandas as pd
from datetime import datetime
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.database.schema import init_database
from src.database.queries import (
    get_portfolio_summary, get_active_trades, get_pnl_by_strategy,
    get_pnl_by_ticker, get_trades_expiring_soon, get_trade_legs
)
from src.risk.alert_engine import get_all_active_alerts, get_alert_summary
from src.utils.formatting import (
    format_currency, format_pnl, format_percentage, severity_badge,
    strategy_display_name, status_badge
)
from src.utils.option_symbols import calculate_dte

st.set_page_config(page_title="Dashboard | Portfolio Manager", page_icon="📊", layout="wide")
from src.utils.branding import setup_branding
setup_branding()
init_database()

# Check and transition expired trades to history log on load
from src.engine.lifecycle_manager import check_and_update_expired_trades
check_and_update_expired_trades()

# Apply custom CSS
st.markdown("""
<style>
    .kpi-card {
        background: linear-gradient(135deg, #1A1F2E 0%, #252B3B 100%);
        border: 1px solid rgba(0, 212, 170, 0.15);
        border-radius: 12px; padding: 20px; text-align: center;
        transition: all 0.3s ease;
    }
    .kpi-card:hover { border-color: rgba(0, 212, 170, 0.4); transform: translateY(-2px); }
    .kpi-value { font-size: 28px; font-weight: 700; margin: 8px 0; }
    .kpi-label { font-size: 12px; color: #888; text-transform: uppercase; letter-spacing: 1px; }
    .kpi-positive { color: #00D4AA; }
    .kpi-negative { color: #FF4B4B; }
    .kpi-neutral { color: #FAFAFA; }
    #MainMenu {visibility: hidden;} footer {visibility: hidden;}
</style>
""", unsafe_allow_html=True)

st.markdown("## 📊 Dashboard")

account = st.session_state.get('selected_account')

# Fetch data
summary = get_portfolio_summary(account)
active_trades = get_active_trades(account)
expiring_soon = get_trades_expiring_soon(7, account)
alert_summary = get_alert_summary()

# ============================================================
# KPI CARDS
# ============================================================
st.markdown('<div class="section-header">Portfolio KPIs</div>', unsafe_allow_html=True)

c1, c2, c3, c4, c5, c6 = st.columns(6)

with c1:
    st.metric("Open Trades", summary['active_count'])
with c2:
    val = summary['total_realized']
    st.metric("Realized P&L", format_currency(val), 
              delta=f"{'↑' if val >= 0 else '↓'} {format_currency(abs(val))}",
              delta_color="normal" if val >= 0 else "inverse")
with c3:
    val = summary['total_unrealized']
    st.metric("Unrealized P&L", format_currency(val),
              delta=f"{'↑' if val >= 0 else '↓'} {format_currency(abs(val))}",
              delta_color="normal" if val >= 0 else "inverse")
with c4:
    st.metric("Premium Collected", format_currency(summary['total_premium']))
with c5:
    st.metric("Max Portfolio Risk", format_currency(summary['total_risk']))
with c6:
    st.metric("Expiring This Week", len(expiring_soon))

# Second row of KPIs
c7, c8, c9, c10, c11, c12 = st.columns(6)

with c7:
    wins = summary.get('wins', 0) or 0
    losses = summary.get('losses', 0) or 0
    total = wins + losses
    win_rate = (wins / total * 100) if total > 0 else 0
    st.metric("Win Rate", f"{win_rate:.0f}%", delta=f"{wins}W / {losses}L")
with c8:
    st.metric("Total Closed", summary['historical_count'])
with c9:
    critical = alert_summary.get('CRITICAL', 0)
    st.metric("🔴 Critical Alerts", critical)
with c10:
    warning = alert_summary.get('WARNING', 0)
    st.metric("🟡 Warnings", warning)
with c11:
    info_count = alert_summary.get('INFO', 0)
    st.metric("🔵 Info", info_count)
with c12:
    total_pnl = (summary.get('total_realized', 0) or 0) + (summary.get('total_unrealized', 0) or 0)
    st.metric("Total P&L", format_currency(total_pnl))

st.divider()

# ============================================================
# CHARTS
# ============================================================
chart_col1, chart_col2 = st.columns(2)

with chart_col1:
    st.markdown("**P&L by Strategy**")
    strategy_data = get_pnl_by_strategy(account)
    if strategy_data:
        df = pd.DataFrame([dict(r) for r in strategy_data])
        df['strategy_name'] = df['strategy_type'].apply(strategy_display_name)
        fig = px.bar(
            df, x='strategy_name', y='total_pnl',
            color='total_pnl',
            color_continuous_scale=['#FF4B4B', '#FFA500', '#00D4AA'],
            labels={'total_pnl': 'P&L ($)', 'strategy_name': 'Strategy'},
        )
        fig.update_layout(
            plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)',
            font_color='#FAFAFA', showlegend=False, height=350,
            xaxis=dict(tickangle=-45), coloraxis_showscale=False,
        )
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No historical trade data yet.")

with chart_col2:
    st.markdown("**P&L by Ticker**")
    ticker_data = get_pnl_by_ticker(account)
    if ticker_data:
        df = pd.DataFrame([dict(r) for r in ticker_data])
        fig = px.bar(
            df, x='underlying', y='total_pnl',
            color='total_pnl',
            color_continuous_scale=['#FF4B4B', '#FFA500', '#00D4AA'],
            labels={'total_pnl': 'P&L ($)', 'underlying': 'Ticker'},
        )
        fig.update_layout(
            plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)',
            font_color='#FAFAFA', showlegend=False, height=350,
            coloraxis_showscale=False,
        )
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No historical trade data yet.")

# DTE Distribution and Strategy Mix
chart_col3, chart_col4 = st.columns(2)

with chart_col3:
    st.markdown("**DTE Distribution (Active Trades)**")
    if active_trades:
        dte_data = []
        for trade in active_trades:
            legs = get_trade_legs(trade['trade_id'])
            for leg in legs:
                dte = calculate_dte(leg['expiry'])
                if dte is not None:
                    dte_data.append({
                        'underlying': trade['underlying'],
                        'dte': dte,
                        'bucket': '0-7' if dte <= 7 else '8-21' if dte <= 21 else '22-45' if dte <= 45 else '45+'
                    })
        if dte_data:
            df = pd.DataFrame(dte_data)
            fig = px.histogram(
                df, x='dte', nbins=20,
                color_discrete_sequence=['#00D4AA'],
                labels={'dte': 'Days to Expiry', 'count': 'Count'},
            )
            fig.update_layout(
                plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)',
                font_color='#FAFAFA', height=300, showlegend=False,
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No expiry data available.")
    else:
        st.info("No active trades.")

with chart_col4:
    st.markdown("**Active Positions by Strategy**")
    if active_trades:
        strategy_counts = {}
        for t in active_trades:
            s = strategy_display_name(t['strategy_type'])
            strategy_counts[s] = strategy_counts.get(s, 0) + 1
        df = pd.DataFrame([
            {'Strategy': k, 'Count': v} for k, v in strategy_counts.items()
        ])
        fig = px.pie(
            df, values='Count', names='Strategy',
            color_discrete_sequence=['#00D4AA', '#4169E1', '#9370DB', '#FFA500', '#FF4B4B', '#FFD700'],
            hole=0.4,
        )
        fig.update_layout(
            plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)',
            font_color='#FAFAFA', height=300,
        )
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No active trades.")

# ============================================================
# RECENT ALERTS
# ============================================================
st.divider()
st.markdown("**Recent Alerts**")

alerts = get_all_active_alerts()
if alerts:
    for alert in alerts[:10]:
        alert = dict(alert)
        badge = severity_badge(alert['severity'])
        col1, col2, col3 = st.columns([1, 8, 2])
        with col1:
            st.write(badge)
        with col2:
            st.write(alert['alert_message'])
        with col3:
            st.caption(alert.get('alert_time', '')[:16])
else:
    st.success("✅ No active alerts. All positions look healthy!")

# Auto-refresh
refresh_interval = int(get_portfolio_summary().get('active_count', 0)) > 0
if refresh_interval:
    st.caption("💡 Dashboard auto-refreshes every 5 minutes when trades are active.")
