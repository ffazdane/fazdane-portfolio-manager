"""
Page 11: YTD Analytics
Comprehensive realized-activity dashboard drawn from broker_transactions.
Global filters: Year / Broker / Account — no dependency on active portfolio.
"""

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.utils.auth import check_password
if not check_password():
    st.stop()

from src.database.queries import get_broker_transactions, get_account_master, get_year_close_status


# ─── CSS ────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
    #MainMenu {visibility: hidden;} footer {visibility: hidden;}
    .kpi-card {
        background: linear-gradient(135deg, #1A1F2E 0%, #252B3B 100%);
        border: 1px solid rgba(0, 212, 170, 0.15);
        border-radius: 12px; padding: 20px; text-align: center;
        transition: all 0.3s ease;
    }
    .kpi-card:hover { border-color: rgba(0, 212, 170, 0.4); transform: translateY(-2px); }
    .kpi-value { font-size: 28px; font-weight: 700; margin: 8px 0; }
    .kpi-label { font-size: 12px; color: #888; text-transform: uppercase; letter-spacing: 1px; }
</style>
""", unsafe_allow_html=True)

st.markdown("## 📈 YTD Analytics & Reporting")
st.caption("Realized transaction history — uploaded via YTD Upload, separate from the active portfolio.")

# ─── Account / Year metadata ────────────────────────────────────────────────
accounts    = get_account_master()
account_map = {a['account_number']: a['broker_name'] for a in accounts}

year_statuses = get_year_close_status()
status_map    = {y['year']: dict(y) for y in year_statuses}

current_year = datetime.now().year
# Always show current year + any years that have data
years_in_db_raw = []
try:
    from src.database.connection import get_db_readonly
    with get_db_readonly() as conn:
        rows = conn.execute(
            "SELECT DISTINCT transaction_year FROM broker_transactions ORDER BY transaction_year DESC"
        ).fetchall()
        years_in_db_raw = [r['transaction_year'] for r in rows]
except Exception:
    pass

years_to_show = sorted(
    list(set(years_in_db_raw + [current_year, current_year - 1])),
    reverse=True
)

# ─── Global Filters ─────────────────────────────────────────────────────────
st.markdown("### 🔍 Global Filters")
fc1, fc2, fc3, fc4 = st.columns([1, 1, 1, 1])
with fc1:
    selected_year = st.selectbox("Year", options=years_to_show, key="ytd_year")
with fc2:
    all_brokers   = list(set(account_map.values()))
    broker_opts   = ["All Brokers"] + sorted(all_brokers)
    selected_broker_label = st.selectbox("Broker", broker_opts, key="ytd_broker")
    selected_broker = None if selected_broker_label == "All Brokers" else selected_broker_label
with fc3:
    if selected_broker:
        acct_opts = ["All Accounts"] + [a for a, b in account_map.items() if b == selected_broker]
    else:
        acct_opts = ["All Accounts"] + list(account_map.keys())
    selected_account_label = st.selectbox("Account", acct_opts, key="ytd_acct")
    selected_account = None if selected_account_label == "All Accounts" else selected_account_label
with fc4:
    # Year lock status badge
    s = status_map.get(selected_year)
    if s and s.get("is_locked"):
        st.markdown(f"<br>🔒 **Year {selected_year} is CLOSED**", unsafe_allow_html=True)
    else:
        st.markdown(f"<br>🟢 **Year {selected_year} is OPEN**", unsafe_allow_html=True)

# ─── Fetch data ──────────────────────────────────────────────────────────────
transactions = get_broker_transactions(
    year=selected_year,
    broker=selected_broker,
    account=selected_account
)

if not transactions:
    st.divider()
    st.info(
        f"📭 No transaction data for **{selected_year}**"
        + (f" / {selected_broker_label}" if selected_broker else "")
        + (f" / {selected_account_label}" if selected_account else "")
        + ".\n\nUpload a YTD file on the **📁 YTD Upload** page first."
    )
    st.stop()

# ─── Build DataFrame ─────────────────────────────────────────────────────────
df = pd.DataFrame([dict(t) for t in transactions])

# Safe numeric coerce
for col in ['fees', 'gross_amount', 'net_amount', 'quantity', 'price']:
    if col in df.columns:
        df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)

# Normalise open/close flag
if 'open_close_flag' in df.columns:
    df['open_close_flag'] = df['open_close_flag'].fillna('').str.upper()
else:
    df['open_close_flag'] = ''

# Date handling
if 'transaction_date' in df.columns:
    df['transaction_date'] = pd.to_datetime(df['transaction_date'], errors='coerce', format='mixed')
    df['month'] = df['transaction_date'].dt.to_period('M').astype(str)
    df['week']  = df['transaction_date'].dt.to_period('W').astype(str)
else:
    df['month'] = 'Unknown'
    df['week']  = 'Unknown'

# ─── KPIs ────────────────────────────────────────────────────────────────────
st.divider()
st.markdown("### 📊 Yearly Performance Summary")

total_txns        = len(df)
total_fees        = df['fees'].sum()
total_gross       = df['gross_amount'].sum()
total_net         = df['net_amount'].sum()

# Open vs Closed
open_df   = df[df['open_close_flag'] == 'OPEN']
close_df  = df[df['open_close_flag'] == 'CLOSE']
open_cnt  = len(open_df)
close_cnt = len(close_df)

# Premium collected = net received on OPEN legs (selling premium → positive)
premium_collected = open_df[open_df['net_amount'] > 0]['net_amount'].sum()

# Win / Loss of closed legs
wins   = len(close_df[close_df['net_amount'] > 0])
losses = len(close_df[close_df['net_amount'] < 0])
win_rate = (wins / (wins + losses) * 100) if (wins + losses) > 0 else 0.0

k1, k2, k3, k4, k5, k6 = st.columns(6)
k1.metric("Transactions",   total_txns)
k2.metric("Net Cash Flow",  f"${total_net:,.2f}",          delta_color="normal" if total_net >= 0 else "inverse")
k3.metric("Premium Sold",   f"${premium_collected:,.2f}")
k4.metric("Total Fees",     f"${total_fees:,.2f}")
k5.metric("Open / Closed",  f"{open_cnt} / {close_cnt}")
k6.metric("Win Rate (Closed)", f"{win_rate:.0f}%", delta=f"{wins}W / {losses}L")

st.divider()

# ─── Charts Row 1 ────────────────────────────────────────────────────────────
c1, c2 = st.columns(2)

_LAYOUT = dict(
    plot_bgcolor='rgba(0,0,0,0)',
    paper_bgcolor='rgba(0,0,0,0)',
    font_color='#FAFAFA',
    margin=dict(t=30, b=20),
)

with c1:
    st.markdown("**Monthly Net Cash Flow**")
    monthly = df.groupby('month')['net_amount'].sum().reset_index().sort_values('month')
    fig = px.bar(
        monthly, x='month', y='net_amount', color='net_amount',
        color_continuous_scale=['#FF4B4B', '#FFA500', '#00D4AA'],
        labels={'net_amount': 'Net ($)', 'month': ''},
    )
    fig.update_layout(**_LAYOUT, height=300, coloraxis_showscale=False)
    fig.update_xaxes(tickangle=-45)
    st.plotly_chart(fig, use_container_width=True)

with c2:
    st.markdown("**Cumulative Net P&L**")
    cum = df.sort_values('transaction_date')['net_amount'].cumsum().reset_index(drop=True)
    dates = df.sort_values('transaction_date')['transaction_date'].reset_index(drop=True)
    fig2 = go.Figure()
    fig2.add_trace(go.Scatter(
        x=dates, y=cum,
        mode='lines',
        fill='tozeroy',
        line=dict(color='#00D4AA', width=2),
        fillcolor='rgba(0, 212, 170, 0.12)',
        name='Cumulative P&L'
    ))
    fig2.update_layout(**_LAYOUT, height=300)
    st.plotly_chart(fig2, use_container_width=True)

# ─── Charts Row 2 ────────────────────────────────────────────────────────────
c3, c4 = st.columns(2)

with c3:
    if 'broker_name' in df.columns and df['broker_name'].nunique() > 1:
        st.markdown("**Broker Reconciliation**")
        broker_smry = df.groupby('broker_name')['net_amount'].sum().reset_index()
        fig = px.pie(
            broker_smry, values='net_amount', names='broker_name', hole=0.42,
            color_discrete_sequence=['#00D4AA', '#FF4B4B', '#9370DB', '#4169E1'],
        )
        fig.update_layout(**_LAYOUT, height=300)
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.markdown("**Monthly Transaction Count**")
        mc = df.groupby('month').size().reset_index(name='count').sort_values('month')
        fig = px.bar(mc, x='month', y='count', color_discrete_sequence=['#4169E1'])
        fig.update_layout(**_LAYOUT, height=300)
        st.plotly_chart(fig, use_container_width=True)

with c4:
    if 'account_number' in df.columns and df['account_number'].nunique() > 1:
        st.markdown("**Performance by Account**")
        acct_smry = df.groupby('account_number')['net_amount'].sum().reset_index()
        fig = px.bar(
            acct_smry, x='account_number', y='net_amount', color='net_amount',
            color_continuous_scale=['#FF4B4B', '#00D4AA'],
        )
        fig.update_layout(**_LAYOUT, height=300, coloraxis_showscale=False)
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.markdown("**Fee Burn by Month**")
        fee_by_mo = df.groupby('month')['fees'].sum().reset_index().sort_values('month')
        fig = px.bar(fee_by_mo, x='month', y='fees', color_discrete_sequence=['#FFA500'])
        fig.update_layout(**_LAYOUT, height=300)
        fig.update_xaxes(tickangle=-45)
        st.plotly_chart(fig, use_container_width=True)

# ─── Charts Row 3 — Ticker & Type ────────────────────────────────────────────
c5, c6 = st.columns(2)

with c5:
    st.markdown("**Top 10 Tickers by Net P&L**")
    if 'underlying' in df.columns:
        ticker_smry = (
            df[df['underlying'].notna() & (df['underlying'] != '')]
            .groupby('underlying')['net_amount']
            .sum().reset_index()
            .sort_values('net_amount', ascending=False)
            .head(10)
        )
        fig = px.bar(
            ticker_smry, x='underlying', y='net_amount', color='net_amount',
            color_continuous_scale=['#FF4B4B', '#00D4AA'],
            labels={'net_amount': 'Net ($)', 'underlying': 'Ticker'},
        )
        fig.update_layout(**_LAYOUT, height=300, coloraxis_showscale=False)
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No underlying data.")

with c6:
    st.markdown("**Net P&L by Transaction Type**")
    if 'transaction_type' in df.columns:
        type_smry = (
            df[df['transaction_type'].notna()]
            .groupby('transaction_type')['net_amount']
            .sum().reset_index()
            .sort_values('net_amount', ascending=True)
        )
        fig = px.bar(
            type_smry, y='transaction_type', x='net_amount', orientation='h',
            color='net_amount',
            color_continuous_scale=['#FF4B4B', '#00D4AA'],
            labels={'net_amount': 'Net ($)', 'transaction_type': ''},
        )
        fig.update_layout(**_LAYOUT, height=300, coloraxis_showscale=False)
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No transaction type data.")

# ─── Drill-down table ────────────────────────────────────────────────────────
st.divider()
st.markdown("### 📋 Consolidated Transaction View")

display_cols_pref = [
    'transaction_date', 'broker_name', 'account_number', 'underlying', 'ticker',
    'transaction_type', 'quantity', 'price', 'gross_amount', 'fees',
    'net_amount', 'open_close_flag', 'source_file_name'
]
display_cols = [c for c in display_cols_pref if c in df.columns]

# Filter / search
search_ticker = st.text_input("Filter by Ticker / Underlying", placeholder="e.g. SPY, AAPL")
if search_ticker:
    mask = (
        df.get('underlying', pd.Series(dtype=str)).str.contains(search_ticker.upper(), na=False)
        | df.get('ticker', pd.Series(dtype=str)).str.contains(search_ticker.upper(), na=False)
    )
    display_df = df[mask]
else:
    display_df = df

# Format date as string to prevent Streamlit rendering bugs with NaT/datetime objects
display_df_sorted = display_df[display_cols].sort_values('transaction_date', ascending=False).copy()
if 'transaction_date' in display_df_sorted.columns:
    display_df_sorted['transaction_date'] = display_df_sorted['transaction_date'].dt.strftime('%Y-%m-%d').fillna('')

st.dataframe(
    display_df_sorted,
    use_container_width=True,
    hide_index=True,
    column_config={
        'transaction_date': st.column_config.TextColumn("Date"),
        'gross_amount': st.column_config.NumberColumn("Gross ($)", format="$%.2f"),
        'net_amount':   st.column_config.NumberColumn("Net ($)",   format="$%.2f"),
        'fees':         st.column_config.NumberColumn("Fees ($)",  format="$%.2f"),
        'price':        st.column_config.NumberColumn("Price",     format="%.4f"),
    }
)

st.caption(f"Showing {len(display_df)} of {len(df)} transactions")
