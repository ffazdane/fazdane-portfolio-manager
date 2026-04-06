"""
Options Portfolio Management System
Main Streamlit Application Entry Point
"""

import streamlit as st
import os
import sys

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.database.schema import init_database
from src.database.queries import get_setting


def init_app():
    """Initialize the application on first load."""
    if 'db_initialized' not in st.session_state:
        init_database()
        st.session_state.db_initialized = True

    if 'tastytrade_session' not in st.session_state:
        st.session_state.tastytrade_session = None

    if 'selected_account' not in st.session_state:
        st.session_state.selected_account = None

    if 'last_refresh' not in st.session_state:
        st.session_state.last_refresh = None


def main():
    st.set_page_config(
        page_title="Options Portfolio Manager",
        page_icon="📊",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    init_app()

    # Custom CSS for premium look
    st.markdown("""
    <style>
        /* Global styling */
        .stApp {
            background: linear-gradient(135deg, #0E1117 0%, #1A1F2E 100%);
        }
        
        /* Sidebar */
        [data-testid="stSidebar"] {
            background: linear-gradient(180deg, #0E1117 0%, #151A26 100%);
            border-right: 1px solid rgba(0, 212, 170, 0.1);
        }
        
        /* KPI Cards */
        .kpi-card {
            background: linear-gradient(135deg, #1A1F2E 0%, #252B3B 100%);
            border: 1px solid rgba(0, 212, 170, 0.15);
            border-radius: 12px;
            padding: 20px;
            text-align: center;
            transition: all 0.3s ease;
        }
        .kpi-card:hover {
            border-color: rgba(0, 212, 170, 0.4);
            transform: translateY(-2px);
            box-shadow: 0 8px 25px rgba(0, 212, 170, 0.1);
        }
        .kpi-value {
            font-size: 28px;
            font-weight: 700;
            margin: 8px 0;
        }
        .kpi-label {
            font-size: 12px;
            color: #888;
            text-transform: uppercase;
            letter-spacing: 1px;
        }
        .kpi-positive { color: #00D4AA; }
        .kpi-negative { color: #FF4B4B; }
        .kpi-neutral { color: #FAFAFA; }
        
        /* Table styling */
        .dataframe {
            border: none !important;
        }
        
        /* Alert badges */
        .alert-critical {
            background: rgba(255, 75, 75, 0.2);
            color: #FF4B4B;
            padding: 4px 12px;
            border-radius: 20px;
            font-size: 12px;
            font-weight: 600;
        }
        .alert-warning {
            background: rgba(255, 165, 0, 0.2);
            color: #FFA500;
            padding: 4px 12px;
            border-radius: 20px;
            font-size: 12px;
            font-weight: 600;
        }
        .alert-info {
            background: rgba(65, 105, 225, 0.2);
            color: #4169E1;
            padding: 4px 12px;
            border-radius: 20px;
            font-size: 12px;
            font-weight: 600;
        }
        
        /* Status badges */
        .status-active { color: #00D4AA; }
        .status-warning { color: #FFA500; }
        .status-closed { color: #888; }
        
        /* Section headers */
        .section-header {
            font-size: 18px;
            font-weight: 600;
            color: #FAFAFA;
            margin: 20px 0 10px 0;
            padding-bottom: 8px;
            border-bottom: 2px solid rgba(0, 212, 170, 0.3);
        }
        
        /* Hide Streamlit branding */
        #MainMenu {visibility: hidden;}
        footer {visibility: hidden;}
        
        /* Tabs */
        .stTabs [data-baseweb="tab"] {
            font-weight: 600;
        }
        .stTabs [data-baseweb="tab-list"] {
            gap: 8px;
        }
        
        /* Metric cards */
        [data-testid="stMetricValue"] {
            font-size: 24px;
            font-weight: 700;
        }
        
        /* Button styling */
        .stButton > button {
            border: 1px solid rgba(0, 212, 170, 0.3);
            border-radius: 8px;
            transition: all 0.3s ease;
        }
        .stButton > button:hover {
            border-color: #00D4AA;
            box-shadow: 0 4px 15px rgba(0, 212, 170, 0.2);
        }
    </style>
    """, unsafe_allow_html=True)

    # Sidebar branding
    with st.sidebar:
        st.markdown("""
        <div style="text-align: center; padding: 20px 0;">
            <h1 style="font-size: 24px; font-weight: 700; 
                       background: linear-gradient(135deg, #00D4AA, #4169E1);
                       -webkit-background-clip: text;
                       -webkit-text-fill-color: transparent;
                       margin-bottom: 4px;">
                📊 Portfolio Manager
            </h1>
            <p style="color: #666; font-size: 12px; letter-spacing: 2px;">
                OPTIONS MONITOR
            </p>
        </div>
        """, unsafe_allow_html=True)

        st.divider()

        # Connection status
        if st.session_state.tastytrade_session:
            st.success("🟢 tastytrade Connected")
        else:
            st.warning("🟡 Not Connected")
            if st.button("Connect to tastytrade", key="sidebar_connect"):
                from src.market.tastytrade_client import get_tastytrade_session, get_accounts
                session, error = get_tastytrade_session()
                if error:
                    st.error(error)
                else:
                    st.session_state.tastytrade_session = session
                    accounts, _ = get_accounts(session)
                    st.session_state.accounts = accounts
                    st.rerun()

        # Account selector
        if st.session_state.get('accounts'):
            account_options = ["All Accounts"] + [
                f"{a['account_number']} ({a['nickname']})"
                for a in st.session_state.accounts
            ]
            selected = st.selectbox("Account", account_options, key="account_selector")
            if selected != "All Accounts":
                st.session_state.selected_account = selected.split(' ')[0]
            else:
                st.session_state.selected_account = None

        # Refresh info
        if st.session_state.last_refresh:
            st.caption(f"Last refresh: {st.session_state.last_refresh.strftime('%H:%M:%S')}")

    # Main page content
    st.markdown("""
    <div style="text-align: center; padding: 40px 0;">
        <h1 style="font-size: 42px; font-weight: 800;
                   background: linear-gradient(135deg, #00D4AA 0%, #4169E1 50%, #9370DB 100%);
                   -webkit-background-clip: text;
                   -webkit-text-fill-color: transparent;">
            Options Portfolio Manager
        </h1>
        <p style="color: #888; font-size: 16px; margin-top: 8px;">
            Monitor • Manage • Journal • Analyze
        </p>
    </div>
    """, unsafe_allow_html=True)

    # Quick navigation cards
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.markdown("""
        <div class="kpi-card">
            <div style="font-size: 36px;">📊</div>
            <div style="font-weight: 600; margin-top: 8px;">Dashboard</div>
            <div class="kpi-label">Portfolio overview & KPIs</div>
        </div>
        """, unsafe_allow_html=True)

    with col2:
        st.markdown("""
        <div class="kpi-card">
            <div style="font-size: 36px;">📈</div>
            <div style="font-weight: 600; margin-top: 8px;">Active Portfolio</div>
            <div class="kpi-label">Open trades & positions</div>
        </div>
        """, unsafe_allow_html=True)

    with col3:
        st.markdown("""
        <div class="kpi-card">
            <div style="font-size: 36px;">📥</div>
            <div style="font-weight: 600; margin-top: 8px;">Import</div>
            <div class="kpi-label">Upload broker files</div>
        </div>
        """, unsafe_allow_html=True)

    with col4:
        st.markdown("""
        <div class="kpi-card">
            <div style="font-size: 36px;">⚠️</div>
            <div style="font-weight: 600; margin-top: 8px;">Risk Monitor</div>
            <div class="kpi-label">Alerts & risk metrics</div>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)
    st.info("👈 Use the sidebar to navigate between pages. Start by going to **Settings** to configure your tastytrade API connection, then **Import** data from your broker files.")


if __name__ == "__main__":
    main()
