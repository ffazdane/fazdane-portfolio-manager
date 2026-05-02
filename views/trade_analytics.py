"""
Trade Analytics Dashboard
Multi-year trading P&L analytics dashboard from transaction-level data.
"""

import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.utils.auth import check_password
if not check_password():
    st.stop()

from src.database.queries import get_broker_transactions, get_account_master

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
    .kpi-positive { color: #00D4AA; }
    .kpi-negative { color: #FF4B4B; }
</style>
""", unsafe_allow_html=True)

st.title("📊 Trade Analytics")
st.caption("Multi-year comprehensive trading performance dashboard.")

# ─── Account Metadata ────────────────────────────────────────────────
accounts    = get_account_master()
account_map = {a['account_number']: a['broker_name'] for a in accounts}

# ─── Data Loading & Preparation ──────────────────────────────────────────────
@st.cache_data(ttl=300)
def load_and_prepare_data():
    transactions = get_broker_transactions() # get all
    if not transactions:
        return pd.DataFrame()
        
    df = pd.DataFrame([dict(t) for t in transactions])
    
    # Safe numeric coerce
    for col in ['fees', 'gross_amount', 'net_amount', 'quantity', 'price', 'realized_pl']:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
            
    if 'open_close_flag' in df.columns:
        df['open_close_flag'] = df['open_close_flag'].fillna('').str.upper()
    else:
        df['open_close_flag'] = ''
        
    # Date handling
    if 'transaction_date' in df.columns:
        df['transaction_date'] = pd.to_datetime(df['transaction_date'], errors='coerce', format='mixed')
        # Drop rows where date couldn't be parsed
        df = df.dropna(subset=['transaction_date']).copy()
        
        df['year'] = df['transaction_date'].dt.year
        df['quarter'] = df['transaction_date'].dt.quarter
        df['month'] = df['transaction_date'].dt.to_period('M').astype(str)
        df['month_num'] = df['transaction_date'].dt.month
        df['week'] = df['transaction_date'].dt.to_period('W').astype(str)
        df['day'] = df['transaction_date'].dt.date
    else:
        st.error("No transaction_date column found in data.")
        return pd.DataFrame()

    # Standardization
    df['underlying'] = df.get('underlying', df.get('ticker', '')).fillna('UNKNOWN').astype(str).str.upper()
    # Asset Type Classification
    def categorize_asset(row):
        desc = str(row.get('description', '')).upper()
        sym = str(row.get('underlying', '')).upper()
        txn_type = str(row.get('transaction_type', '')).upper()
        
        if 'DIVIDEND' in txn_type or 'DIVIDEND' in desc:
            return 'Dividend'
        elif 'FEE' in txn_type or 'FEE' in desc:
            return 'Fee'
        elif 'INTEREST' in txn_type or 'INTEREST' in desc:
            return 'Interest'
        elif any(x in sym for x in ['SPX', 'NDX', 'RUT', 'VIX', 'XSP']) and ('CALL' in desc or 'PUT' in desc or 'OPT' in desc or len(str(row.get('ticker',''))) > 6):
            return 'Index Option'
        elif '/' in sym or 'FUT' in desc:
            return 'Future'
        elif 'CALL' in desc or 'PUT' in desc or 'OPT' in txn_type or len(str(row.get('ticker',''))) > 6:
            return 'Option'
        elif sym in ['SPY', 'QQQ', 'IWM', 'DIA', 'TLT', 'GLD']:
            return 'ETF'
        elif 'CASH' in txn_type or 'DEPOSIT' in txn_type or 'WITHDRAWAL' in txn_type:
            return 'Cash'
        else:
            return 'Stock'
            
    df['asset_type'] = df.apply(categorize_asset, axis=1)
    
    return df

with st.spinner("Loading transaction data..."):
    df_raw = load_and_prepare_data()

if df_raw.empty:
    st.info("📭 No transaction data found. Upload data in Broker Data Upload page first.")
    st.stop()

# ─── Global Filters ─────────────────────────────────────────────────────────
st.sidebar.markdown("### 🔍 Global Filters")

# Sidebar filters
all_years = sorted(df_raw['year'].dropna().unique().tolist(), reverse=True)
selected_years = st.sidebar.multiselect("Years", options=all_years, default=all_years)

all_brokers = sorted(df_raw['broker_name'].dropna().unique().tolist())
selected_brokers = st.sidebar.multiselect("Brokers", options=all_brokers, default=all_brokers)

all_accounts = sorted(df_raw['account_number'].dropna().unique().tolist())
selected_accounts = st.sidebar.multiselect("Accounts", options=all_accounts, default=all_accounts)

# Apply global filters
df = df_raw.copy()
if selected_years:
    df = df[df['year'].isin(selected_years)]
if selected_brokers:
    df = df[df['broker_name'].isin(selected_brokers)]
if selected_accounts:
    df = df[df['account_number'].isin(selected_accounts)]

if df.empty:
    st.warning("No data matches the selected filters.")
    st.stop()


# ─── Helper Functions ───────────────────────────────────────────────────────
def calc_kpis(data):
    total_net = data['net_amount'].sum()
    total_gross = data['gross_amount'].sum()
    total_fees = data['fees'].sum()
    
    # trades count based on closing transactions if possible, else all txns
    closed_txns = data[data['open_close_flag'] == 'CLOSE']
    if closed_txns.empty:
        closed_txns = data
        
    num_trades = len(closed_txns)
    wins = len(closed_txns[closed_txns['net_amount'] > 0])
    losses = len(closed_txns[closed_txns['net_amount'] < 0])
    
    win_rate = (wins / num_trades) if num_trades > 0 else 0
    
    avg_win = closed_txns[closed_txns['net_amount'] > 0]['net_amount'].mean()
    avg_loss = closed_txns[closed_txns['net_amount'] < 0]['net_amount'].mean()
    
    gross_profit = closed_txns[closed_txns['net_amount'] > 0]['net_amount'].sum()
    gross_loss = abs(closed_txns[closed_txns['net_amount'] < 0]['net_amount'].sum())
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else (999 if gross_profit > 0 else 0)
    
    largest_win = closed_txns['net_amount'].max() if num_trades > 0 else 0
    largest_loss = closed_txns['net_amount'].min() if num_trades > 0 else 0
    
    return {
        'total_net': total_net,
        'total_gross': total_gross,
        'total_fees': total_fees,
        'num_trades': num_trades,
        'wins': wins,
        'losses': losses,
        'win_rate': win_rate,
        'avg_win': avg_win if pd.notna(avg_win) else 0,
        'avg_loss': avg_loss if pd.notna(avg_loss) else 0,
        'profit_factor': profit_factor,
        'largest_win': largest_win,
        'largest_loss': largest_loss
    }

def draw_kpi_card(label, value, is_currency=False, is_percent=False, invert_color=False):
    if is_currency:
        formatted = f"${value:,.2f}"
    elif is_percent:
        formatted = f"{value * 100:.1f}%"
    else:
        if isinstance(value, float):
            formatted = f"{value:.2f}"
        else:
            formatted = str(value)
            
    color_class = ""
    if is_currency or is_percent or label in ['Profit Factor']:
        if value > 0:
            color_class = "kpi-negative" if invert_color else "kpi-positive"
        elif value < 0:
            color_class = "kpi-positive" if invert_color else "kpi-negative"
            
    st.markdown(f"""
        <div class="kpi-card">
            <div class="kpi-label">{label}</div>
            <div class="kpi-value {color_class}">{formatted}</div>
        </div>
    """, unsafe_allow_html=True)


_LAYOUT = dict(
    plot_bgcolor='rgba(0,0,0,0)',
    paper_bgcolor='rgba(0,0,0,0)',
    font_color='#FAFAFA',
    margin=dict(t=30, b=20, l=0, r=0),
)

# ─── Navigation Tabs ────────────────────────────────────────────────────────
tabs = st.tabs([
    "Executive Summary", "Year Analysis", "Month Analysis", 
    "Week Analysis", "Daily Analysis", "Ticker Analysis", 
    "Risk & Drawdown", "Trade Explorer"
])

# ============================================================================
# 1. Executive Summary
# ============================================================================
with tabs[0]:
    st.subheader("Executive Trading Summary")
    
    kpis = calc_kpis(df)
    
    c1, c2, c3, c4 = st.columns(4)
    with c1: draw_kpi_card("Total Net P&L", kpis['total_net'], is_currency=True)
    with c2: draw_kpi_card("Total Gross P&L", kpis['total_gross'], is_currency=True)
    with c3: draw_kpi_card("Total Fees", kpis['total_fees'], is_currency=True, invert_color=True)
    with c4: draw_kpi_card("Number of Trades", kpis['num_trades'])
    
    st.write("")
    c5, c6, c7, c8 = st.columns(4)
    with c5: draw_kpi_card("Win Rate", kpis['win_rate'], is_percent=True)
    with c6: draw_kpi_card("Profit Factor", kpis['profit_factor'])
    with c7: draw_kpi_card("Average Win", kpis['avg_win'], is_currency=True)
    with c8: draw_kpi_card("Average Loss", kpis['avg_loss'], is_currency=True)
    
    st.divider()
    
    col1, col2 = st.columns(2)
    with col1:
        st.markdown("**Year-by-Year Net P&L**")
        yearly_pnl = df.groupby('year')['net_amount'].sum().reset_index()
        fig = px.bar(yearly_pnl, x='year', y='net_amount', color='net_amount',
                     color_continuous_scale=['#FF4B4B', '#FFA500', '#00D4AA'])
        fig.update_layout(**_LAYOUT, coloraxis_showscale=False)
        fig.update_xaxes(type='category')
        st.plotly_chart(fig, use_container_width=True)
        
    with col2:
        st.markdown("**Cumulative Net P&L**")
        cum_df = df.sort_values('transaction_date').copy()
        cum_df['cum_pnl'] = cum_df['net_amount'].cumsum()
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=cum_df['transaction_date'], y=cum_df['cum_pnl'],
            mode='lines', fill='tozeroy',
            line=dict(color='#00D4AA', width=2),
            fillcolor='rgba(0, 212, 170, 0.12)'
        ))
        fig.update_layout(**_LAYOUT)
        st.plotly_chart(fig, use_container_width=True)
        
    col3, col4 = st.columns(2)
    with col3:
        st.markdown("**Top 10 Winning Tickers**")
        ticker_pnl = df.groupby('underlying')['net_amount'].sum().reset_index()
        winners = ticker_pnl[ticker_pnl['net_amount'] > 0].sort_values('net_amount', ascending=False).head(10)
        fig = px.bar(winners, y='underlying', x='net_amount', orientation='h', color_discrete_sequence=['#00D4AA'])
        fig.update_layout(**_LAYOUT, yaxis={'categoryorder':'total ascending'})
        st.plotly_chart(fig, use_container_width=True)
        
    with col4:
        st.markdown("**Top 10 Losing Tickers**")
        losers = ticker_pnl[ticker_pnl['net_amount'] < 0].sort_values('net_amount', ascending=True).head(10)
        fig = px.bar(losers, y='underlying', x='net_amount', orientation='h', color_discrete_sequence=['#FF4B4B'])
        fig.update_layout(**_LAYOUT, yaxis={'categoryorder':'total descending'})
        st.plotly_chart(fig, use_container_width=True)
        
    col5, col6 = st.columns(2)
    with col5:
        st.markdown("**P&L by Asset Type**")
        asset_pnl = df.groupby('asset_type')['net_amount'].sum().reset_index()
        fig = px.bar(asset_pnl, x='asset_type', y='net_amount', color='net_amount',
                     color_continuous_scale=['#FF4B4B', '#FFA500', '#00D4AA'])
        fig.update_layout(**_LAYOUT, coloraxis_showscale=False)
        st.plotly_chart(fig, use_container_width=True)
    with col6:
        st.markdown("**Win Rate by Year**")
        # Calculate win rate per year
        yr_stats = df[df['open_close_flag'] == 'CLOSE'].groupby('year').apply(
            lambda x: pd.Series({'win_rate': len(x[x['net_amount'] > 0]) / len(x) if len(x) > 0 else 0})
        ).reset_index()
        if not yr_stats.empty:
            fig = px.bar(yr_stats, x='year', y='win_rate', color_discrete_sequence=['#00D4AA'])
            fig.update_layout(**_LAYOUT, yaxis_tickformat='.0%')
            fig.update_xaxes(type='category')
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No closed trades to compute win rate by year.")

# ============================================================================
# 2. Year Analysis
# ============================================================================
with tabs[1]:
    st.subheader("Year-Level Analysis")
    
    available_years = sorted(df['year'].unique().tolist(), reverse=True)
    if available_years:
        selected_year = st.selectbox("Select Year", available_years, key="year_analysis_sel")
        
        df_year = df[df['year'] == selected_year]
        ykpis = calc_kpis(df_year)
        
        c1, c2, c3, c4 = st.columns(4)
        with c1: draw_kpi_card(f"{int(selected_year)} Net P&L", ykpis['total_net'], is_currency=True)
        with c2: draw_kpi_card(f"{int(selected_year)} Fees", ykpis['total_fees'], is_currency=True, invert_color=True)
        with c3: draw_kpi_card("Win Rate", ykpis['win_rate'], is_percent=True)
        with c4: draw_kpi_card("Profit Factor", ykpis['profit_factor'])
        
        col1, col2 = st.columns(2)
        with col1:
            st.markdown("**Monthly P&L**")
            monthly_pnl = df_year.groupby('month')['net_amount'].sum().reset_index()
            fig = px.bar(monthly_pnl, x='month', y='net_amount', color='net_amount',
                         color_continuous_scale=['#FF4B4B', '#00D4AA'])
            fig.update_layout(**_LAYOUT, coloraxis_showscale=False)
            st.plotly_chart(fig, use_container_width=True)
            
        with col2:
            st.markdown("**Cumulative P&L for Year**")
            cum_y = df_year.sort_values('transaction_date').copy()
            cum_y['cum_pnl'] = cum_y['net_amount'].cumsum()
            fig = px.line(cum_y, x='transaction_date', y='cum_pnl')
            fig.update_traces(line_color='#00D4AA', fill='tozeroy', fillcolor='rgba(0, 212, 170, 0.12)')
            fig.update_layout(**_LAYOUT)
            st.plotly_chart(fig, use_container_width=True)

# ============================================================================
# 3. Month Analysis
# ============================================================================
with tabs[2]:
    st.subheader("Month-Level Analysis")
    available_months = sorted(df['month'].unique().tolist(), reverse=True)
    if available_months:
        selected_month = st.selectbox("Select Month", available_months, key="month_analysis_sel")
        
        df_month = df[df['month'] == selected_month]
        mkpis = calc_kpis(df_month)
        
        c1, c2, c3, c4 = st.columns(4)
        with c1: draw_kpi_card(f"{selected_month} Net P&L", mkpis['total_net'], is_currency=True)
        with c2: draw_kpi_card(f"Trades", mkpis['num_trades'])
        with c3: draw_kpi_card("Win Rate", mkpis['win_rate'], is_percent=True)
        
        num_days = df_month['day'].nunique()
        avg_daily = mkpis['total_net'] / num_days if num_days > 0 else 0
        with c4: draw_kpi_card("Avg Daily P&L", avg_daily, is_currency=True)
        
        col1, col2 = st.columns(2)
        with col1:
            st.markdown("**Weekly P&L**")
            weekly_pnl = df_month.groupby('week')['net_amount'].sum().reset_index()
            fig = px.bar(weekly_pnl, x='week', y='net_amount', color='net_amount',
                         color_continuous_scale=['#FF4B4B', '#00D4AA'])
            fig.update_layout(**_LAYOUT, coloraxis_showscale=False)
            fig.update_xaxes(type='category')
            st.plotly_chart(fig, use_container_width=True)
            
        with col2:
            st.markdown("**Daily P&L**")
            daily_pnl = df_month.groupby('day')['net_amount'].sum().reset_index()
            fig = px.bar(daily_pnl, x='day', y='net_amount', color='net_amount',
                         color_continuous_scale=['#FF4B4B', '#00D4AA'])
            fig.update_layout(**_LAYOUT, coloraxis_showscale=False)
            st.plotly_chart(fig, use_container_width=True)
            
        st.markdown("**Monthly Cumulative P&L**")
        cum_m = df_month.sort_values('transaction_date').copy()
        cum_m['cum_pnl'] = cum_m['net_amount'].cumsum()
        fig = px.line(cum_m, x='transaction_date', y='cum_pnl')
        fig.update_traces(line_color='#00D4AA', fill='tozeroy', fillcolor='rgba(0, 212, 170, 0.12)')
        fig.update_layout(**_LAYOUT)
        st.plotly_chart(fig, use_container_width=True)

# ============================================================================
# 4. Week Analysis
# ============================================================================
with tabs[3]:
    st.subheader("Week-Level Analysis")
    available_weeks = sorted(df['week'].unique().tolist(), reverse=True)
    if available_weeks:
        selected_week = st.selectbox("Select Week", available_weeks, key="week_analysis_sel")
        
        df_week = df[df['week'] == selected_week]
        wkpis = calc_kpis(df_week)
        
        c1, c2, c3, c4 = st.columns(4)
        with c1: draw_kpi_card(f"Week Net P&L", wkpis['total_net'], is_currency=True)
        with c2: draw_kpi_card(f"Trades", wkpis['num_trades'])
        with c3: draw_kpi_card("Win Rate", wkpis['win_rate'], is_percent=True)
        with c4: draw_kpi_card("Fees", wkpis['total_fees'], is_currency=True, invert_color=True)
        
        col1, col2 = st.columns(2)
        with col1:
            st.markdown("**Daily P&L in Week**")
            daily_w_pnl = df_week.groupby('day')['net_amount'].sum().reset_index()
            fig = px.bar(daily_w_pnl, x='day', y='net_amount', color='net_amount',
                         color_continuous_scale=['#FF4B4B', '#00D4AA'])
            fig.update_layout(**_LAYOUT, coloraxis_showscale=False)
            st.plotly_chart(fig, use_container_width=True)
            
        with col2:
            st.markdown("**Ticker Contribution (Week)**")
            tick_w = df_week.groupby('underlying')['net_amount'].sum().reset_index()
            fig = px.pie(tick_w, values=tick_w['net_amount'].abs(), names='underlying',
                         color='net_amount', color_discrete_sequence=px.colors.qualitative.Pastel)
            fig.update_layout(**_LAYOUT)
            st.plotly_chart(fig, use_container_width=True)

# ============================================================================
# 5. Daily Analysis
# ============================================================================
with tabs[4]:
    st.subheader("Daily Analysis")
    available_days = sorted(df['day'].unique().tolist(), reverse=True)
    if available_days:
        selected_day = st.selectbox("Select Day", available_days, key="day_analysis_sel")
        
        df_day = df[df['day'] == selected_day]
        dkpis = calc_kpis(df_day)
        
        c1, c2, c3, c4 = st.columns(4)
        with c1: draw_kpi_card(f"Daily Net P&L", dkpis['total_net'], is_currency=True)
        with c2: draw_kpi_card(f"Trades", dkpis['num_trades'])
        with c3: draw_kpi_card("Win Rate", dkpis['win_rate'], is_percent=True)
        with c4: draw_kpi_card("Best Trade", dkpis['largest_win'], is_currency=True)
        
        st.markdown("**Transactions on this Day**")
        st.dataframe(
            df_day[['transaction_date', 'underlying', 'description', 'transaction_type', 'quantity', 'price', 'fees', 'net_amount']].sort_values('transaction_date'),
            use_container_width=True, hide_index=True
        )

# ============================================================================
# 6. Ticker Analysis
# ============================================================================
with tabs[5]:
    st.subheader("Ticker-Level Analysis")
    available_tickers = sorted(df['underlying'].unique().tolist())
    if available_tickers:
        selected_ticker = st.selectbox("Select Ticker", available_tickers, key="ticker_analysis_sel")
        
        df_tick = df[df['underlying'] == selected_ticker]
        tkpis = calc_kpis(df_tick)
        
        c1, c2, c3, c4 = st.columns(4)
        with c1: draw_kpi_card(f"Total Ticker P&L", tkpis['total_net'], is_currency=True)
        with c2: draw_kpi_card(f"Trades", tkpis['num_trades'])
        with c3: draw_kpi_card("Win Rate", tkpis['win_rate'], is_percent=True)
        with c4: draw_kpi_card("Fees", tkpis['total_fees'], is_currency=True, invert_color=True)
        
        col1, col2 = st.columns(2)
        with col1:
            st.markdown("**Ticker P&L by Year**")
            ty_pnl = df_tick.groupby('year')['net_amount'].sum().reset_index()
            fig = px.bar(ty_pnl, x='year', y='net_amount', color='net_amount',
                         color_continuous_scale=['#FF4B4B', '#00D4AA'])
            fig.update_layout(**_LAYOUT, coloraxis_showscale=False)
            fig.update_xaxes(type='category')
            st.plotly_chart(fig, use_container_width=True)
            
        with col2:
            st.markdown("**Cumulative P&L for Ticker**")
            cum_t = df_tick.sort_values('transaction_date').copy()
            cum_t['cum_pnl'] = cum_t['net_amount'].cumsum()
            fig = px.line(cum_t, x='transaction_date', y='cum_pnl')
            fig.update_traces(line_color='#00D4AA', fill='tozeroy', fillcolor='rgba(0, 212, 170, 0.12)')
            fig.update_layout(**_LAYOUT)
            st.plotly_chart(fig, use_container_width=True)

# ============================================================================
# 7. Risk & Drawdown
# ============================================================================
with tabs[6]:
    st.subheader("Risk & Drawdown Analysis")
    
    # Calculate Drawdown
    cum_df = df.sort_values('transaction_date').copy()
    cum_df['cum_pnl'] = cum_df['net_amount'].cumsum()
    cum_df['peak'] = cum_df['cum_pnl'].cummax()
    cum_df['drawdown'] = cum_df['cum_pnl'] - cum_df['peak']
    
    max_dd = cum_df['drawdown'].min()
    
    daily_pnl = df.groupby('day')['net_amount'].sum()
    worst_day = daily_pnl.min() if not daily_pnl.empty else 0
    
    c1, c2, c3, c4 = st.columns(4)
    with c1: draw_kpi_card("Max Drawdown", max_dd, is_currency=True, invert_color=True)
    with c2: draw_kpi_card("Worst Day", worst_day, is_currency=True, invert_color=True)
    
    total_gross = df[df['net_amount']>0]['net_amount'].sum()
    fee_drag = abs(df['fees'].sum() / total_gross) if total_gross > 0 else 0
    with c3: draw_kpi_card("Fee Drag %", fee_drag, is_percent=True, invert_color=True)
    with c4: draw_kpi_card("Avg Losing Day", daily_pnl[daily_pnl < 0].mean() if not daily_pnl[daily_pnl < 0].empty else 0, is_currency=True, invert_color=True)
    
    st.markdown("**Drawdown Curve**")
    fig = px.area(cum_df, x='transaction_date', y='drawdown')
    fig.update_traces(line_color='#FF4B4B', fillcolor='rgba(255, 75, 75, 0.2)')
    fig.update_layout(**_LAYOUT)
    st.plotly_chart(fig, use_container_width=True)
    
    col1, col2 = st.columns(2)
    with col1:
        st.markdown("**Worst 10 Trading Days**")
        w_days = daily_pnl.reset_index().sort_values('net_amount').head(10)
        fig = px.bar(w_days, x='day', y='net_amount', color_discrete_sequence=['#FF4B4B'])
        fig.update_layout(**_LAYOUT)
        fig.update_xaxes(type='category')
        st.plotly_chart(fig, use_container_width=True)
        
    with col2:
        st.markdown("**Monthly Loss Heatmap**")
        monthly_hm = df.groupby(['year', 'month_num'])['net_amount'].sum().reset_index()
        monthly_hm = monthly_hm[monthly_hm['net_amount'] < 0]
        if not monthly_hm.empty:
            hm = monthly_hm.pivot(index='year', columns='month_num', values='net_amount').fillna(0)
            fig = px.imshow(hm, text_auto=".2s", color_continuous_scale='Reds_r')
            fig.update_layout(**_LAYOUT)
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No losing months to display.")

# ============================================================================
# 8. Trade Explorer
# ============================================================================
with tabs[7]:
    st.subheader("Trade Detail Explorer")
    
    sc1, sc2, sc3, sc4 = st.columns(4)
    with sc1:
        search_ticker = st.text_input("Search Ticker/Underlying")
    with sc2:
        search_type = st.multiselect("Transaction Type", options=df['transaction_type'].unique().tolist())
    with sc3:
        asset_types = st.multiselect("Asset Type", options=df['asset_type'].unique().tolist())
    with sc4:
        min_pnl = st.number_input("Min Net P&L", value=0.0, step=100.0)
        
    exp_df = df.copy()
    if search_ticker:
        exp_df = exp_df[exp_df['underlying'].str.contains(search_ticker.upper(), na=False)]
    if search_type:
        exp_df = exp_df[exp_df['transaction_type'].isin(search_type)]
    if asset_types:
        exp_df = exp_df[exp_df['asset_type'].isin(asset_types)]
    if min_pnl > 0 or min_pnl < 0:
        exp_df = exp_df[exp_df['net_amount'] >= min_pnl]
        
    st.dataframe(
        exp_df[['transaction_date', 'broker_name', 'account_number', 'underlying', 
                'asset_type', 'transaction_type', 'quantity', 'price', 'gross_amount', 'fees', 
                'net_amount', 'open_close_flag']].sort_values('transaction_date', ascending=False),
        use_container_width=True, hide_index=True
    )
    
    st.caption(f"Showing {len(exp_df)} transactions.")
    
    # Export
    csv = exp_df.to_csv(index=False).encode('utf-8')
    st.download_button(
        "Download Filtered Data as CSV",
        csv,
        "exported_trades.csv",
        "text/csv",
        key='download-csv'
    )
