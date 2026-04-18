"""
Page 6: Risk Monitor
Trades needing attention with alerts, DTE warnings, and concentration analysis.
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

from app import init_app
from src.database.queries import get_active_trades, get_trade_legs, get_setting
from src.risk.alert_engine import get_all_active_alerts, acknowledge_alert
from src.risk.risk_metrics import calculate_trade_risk_metrics, calculate_portfolio_risk
from src.utils.formatting import (
    format_currency, format_dte, status_badge, strategy_display_name,
    severity_badge, format_delta, format_date
)
from src.utils.option_symbols import calculate_dte

st.set_page_config(page_title="Risk Monitor | Portfolio Manager", page_icon="⚠️", layout="wide")
from src.utils.branding import setup_branding
setup_branding()
init_app()

st.markdown("""
<style> #MainMenu {visibility: hidden;} footer {visibility: hidden;} </style>
""", unsafe_allow_html=True)

st.markdown("## ⚠️ Risk Monitor")

account = st.session_state.get('selected_account')
active_trades = get_active_trades(account)

# ============================================================
# PORTFOLIO RISK SUMMARY
# ============================================================
st.markdown("### Portfolio Risk Overview")

if active_trades:
    trades_with_metrics = []
    for trade in active_trades:
        trade = dict(trade)
        legs = get_trade_legs(trade['trade_id'])
        metrics = calculate_trade_risk_metrics(trade, legs)
        trades_with_metrics.append((trade, metrics))

    portfolio_risk = calculate_portfolio_risk(trades_with_metrics)

    r1, r2, r3, r4, r5, r6 = st.columns(6)
    with r1:
        st.metric("Total Risk", format_currency(portfolio_risk['total_risk']))
    with r2:
        st.metric("Net Delta", f"{portfolio_risk['total_delta']:+.1f}")
    with r3:
        st.metric("Net Theta", f"{portfolio_risk['total_theta']:+.4f}")
    with r4:
        st.metric("Expiring ≤7d", portfolio_risk['expiring_this_week'])
    with r5:
        st.metric("🔴 Breached", portfolio_risk['breached_count'])
    with r6:
        st.metric("🟡 Warnings", portfolio_risk['warning_count'])

    st.divider()

    # ============================================================
    # ACTIVE ALERTS
    # ============================================================
    st.markdown("### Active Alerts")
    alerts = get_all_active_alerts()

    if alerts:
        for alert in alerts:
            alert = dict(alert)
            badge = severity_badge(alert['severity'])
            with st.container():
                ac1, ac2, ac3, ac4 = st.columns([0.5, 6, 2, 1.5])
                with ac1:
                    st.write(badge)
                with ac2:
                    st.markdown(f"**{alert['alert_message']}**")
                    st.caption(f"Type: {alert['alert_type']} | Trade: {alert.get('underlying', '?')} ({strategy_display_name(alert.get('strategy_type', ''))})")
                with ac3:
                    st.caption(alert.get('alert_time', '')[:16])
                with ac4:
                    if st.button("✅ Ack", key=f"ack_{alert['alert_id']}"):
                        acknowledge_alert(alert['alert_id'], "Acknowledged from Risk Monitor")
                        st.success("Alert acknowledged")
                        st.rerun()
            st.markdown('<hr style="margin: 2px 0; border-color: rgba(255,255,255,0.05);">', unsafe_allow_html=True)
    else:
        st.success("✅ No active alerts!")

    st.divider()

    # ============================================================
    # TRADES NEEDING ATTENTION
    # ============================================================
    st.markdown("### Trades Needing Attention")

    # Sort by risk (nearest DTE, closest strike breach)
    attention_trades = []
    for trade, metrics in trades_with_metrics:
        dte = metrics.get('min_dte')
        dist = metrics.get('short_strike_distance_pct')
        priority = 0
        reasons = []

        if dte is not None and dte <= 7:
            priority += 30
            reasons.append(f"⏰ {dte} DTE")
        if dist is not None and abs(dist) <= float(get_setting('strike_proximity_pct', '2')):
            priority += 50
            reasons.append(f"🎯 Strike at {dist:.1f}%")
        if dist is not None and abs(dist) <= float(get_setting('strike_proximity_pct', '2')) * 2.5:
            priority += 20
            reasons.append(f"⚠️ Strike at {dist:.1f}%")
        if dte is not None and dte <= 21:
            priority += 10
            reasons.append(f"📅 {dte} DTE")

        if priority > 0:
            attention_trades.append((trade, metrics, priority, reasons))

    attention_trades.sort(key=lambda x: x[2], reverse=True)

    if attention_trades:
        for trade, metrics, priority, reasons in attention_trades:
            dte_str, _ = format_dte(metrics.get('min_dte'))
            with st.container():
                tc1, tc2, tc3, tc4, tc5 = st.columns([1.5, 2, 1, 1.5, 3])
                with tc1:
                    st.markdown(f"**{trade['underlying']}**")
                with tc2:
                    st.caption(strategy_display_name(trade['strategy_type']))
                with tc3:
                    dte = metrics.get('min_dte')
                    color = "#FF4B4B" if dte and dte <= 7 else "#FFA500" if dte and dte <= 21 else "#00D4AA"
                    st.markdown(f'<span style="color:{color}; font-weight:600;">{dte_str}</span>', unsafe_allow_html=True)
                with tc4:
                    dist = metrics.get('short_strike_distance_pct')
                    if dist is not None:
                        d_color = "#FF4B4B" if abs(dist) <= 2 else "#FFA500" if abs(dist) <= 5 else "#00D4AA"
                        st.markdown(f'<span style="color:{d_color};">{dist:+.1f}%</span>', unsafe_allow_html=True)
                    else:
                        st.write("—")
                with tc5:
                    st.caption(" | ".join(reasons))
            st.markdown('<hr style="margin: 2px 0; border-color: rgba(255,255,255,0.05);">', unsafe_allow_html=True)
    else:
        st.success("✅ No trades need immediate attention.")

    # ============================================================
    # CONCENTRATION ANALYSIS
    # ============================================================
    st.divider()
    st.markdown("### 📊 Concentration Analysis")

    conc = portfolio_risk.get('concentration_by_ticker', {})
    if conc:
        total_risk = sum(conc.values()) or 1
        conc_data = [{'Ticker': k, 'Risk': v, 'Pct': v/total_risk*100} for k, v in conc.items()]
        conc_data.sort(key=lambda x: x['Risk'], reverse=True)

        c1, c2 = st.columns(2)
        with c1:
            df = pd.DataFrame(conc_data)
            fig = px.pie(df, values='Risk', names='Ticker',
                        color_discrete_sequence=['#00D4AA', '#4169E1', '#9370DB', '#FFA500', '#FF4B4B', '#FFD700'],
                        hole=0.4, title="Risk by Ticker")
            fig.update_layout(plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)',
                            font_color='#FAFAFA', height=350)
            st.plotly_chart(fig, use_container_width=True)

        with c2:
            limit = float(get_setting('concentration_limit_pct', '25'))
            for item in conc_data:
                color = "#FF4B4B" if item['Pct'] > limit else "#FFA500" if item['Pct'] > limit * 0.7 else "#00D4AA"
                st.markdown(
                    f"**{item['Ticker']}**: {format_currency(item['Risk'])} "
                    f"(<span style='color:{color}'>{item['Pct']:.1f}%</span>)"
                    f" {'⚠️ Over limit!' if item['Pct'] > limit else ''}",
                    unsafe_allow_html=True
                )
else:
    st.info("No active trades to monitor. Import data from the **Imports** page.")
