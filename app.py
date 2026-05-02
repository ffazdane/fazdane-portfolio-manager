"""
Options Portfolio Management System
Main Streamlit Application Entry Point
"""

import streamlit as st
import os
import sys

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.database.schema import init_database, migrate_database
from src.database.queries import get_setting
from src.database.persistence import db_exists_and_has_data, restore_database
from src.utils.branding import _inject_sidebar_brand


def init_app():
    """Initialize the application on first load."""
    if 'db_initialized' not in st.session_state:

        if not db_exists_and_has_data():
            success, message = restore_database()
            st.session_state.db_restore_status = ("success" if success else "info", message)
        else:
            st.session_state.db_restore_status = None

        init_database()
        migrate_database()
        st.session_state.db_initialized = True

    if 'selected_account' not in st.session_state:
        st.session_state.selected_account = None

    if 'last_refresh' not in st.session_state:
        st.session_state.last_refresh = None

    if 'tastytrade_session' not in st.session_state:
        st.session_state.tastytrade_session = None
        # Attempt auto-connect on load
        try:
            from src.market.tastytrade_client import get_tastytrade_session, get_accounts
            env = get_setting('tastytrade_environment', 'production')
            
            session = None
            if os.getenv('TT_SECRET') and os.getenv('TT_REFRESH'):
                session, _ = get_tastytrade_session(environment=env)
            elif os.getenv('TASTYTRADE_USERNAME') and os.getenv('TASTYTRADE_PASSWORD'):
                session, _ = get_tastytrade_session(environment=env)
                
            if session:
                st.session_state.tastytrade_session = session
                st.session_state.accounts, _ = get_accounts(session)
        except Exception:
            pass


from src.utils.auth import check_password

def main():
    st.set_page_config(
        page_title="Options Portfolio Manager",
        page_icon="📊",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    if not check_password():
        st.stop()

    init_app()

    # Define Navigation
    pages = {
        "Overview": [
            st.Page("views/dashboard.py", title="Dashboard", icon="📊", default=True),
            st.Page("views/active_portfolio.py", title="Active Portfolio", icon="📈"),
            st.Page("views/portfolio_monitor.py", title="Portfolio Monitor", icon="🦅"),
            st.Page("views/risk_monitor.py", title="Risk Monitor", icon="⚠️"),
        ],
        "Trades & Activity": [
            st.Page("views/trade_detail.py", title="Trade Detail", icon="🔍"),
            st.Page("views/history_log.py", title="History Log", icon="📜"),
            st.Page("views/manual_entry.py", title="Manual Entry", icon="✍️"),
        ],
        "Data Management": [
            st.Page("views/imports.py", title="Imports", icon="📥"),
            st.Page("views/broker_data_upload.py", title="Broker Data Upload", icon="📁"),
        ],
        "Analytics": [
            st.Page("views/trade_analytics.py", title="Trade Analytics", icon="📈"),
            st.Page("views/tax_center.py",    title="Tax Center",    icon="🧾"),
        ],
        "Year-End Controls": [
            st.Page("views/year_close.py", title="Year Close", icon="🔒"),
        ],
        "System": [
            st.Page("views/settings.py", title="Settings", icon="⚙️"),
        ]
    }

    pg = st.navigation(pages)

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

    # Sidebar branding — logo + FAZDANE ANALYTICS text block
    logo_path = os.path.join(os.path.dirname(__file__), "logo.png")
    _inject_sidebar_brand(logo_path)

    with st.sidebar:
        st.divider()

        # Show restore status once on first load
        restore = st.session_state.get("db_restore_status")
        if restore:
            level, msg = restore
            if level == "success":
                st.success(f"🗄️ DB restored: {msg}", icon="✅")
            else:
                st.info(f"🗄️ {msg}", icon="ℹ️")

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

    # Run the selected page
    pg.run()

if __name__ == "__main__":
    main()
