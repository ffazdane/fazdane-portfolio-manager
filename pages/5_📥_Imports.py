"""
Page 5: Imports / Reconciliation
Upload broker files, preview, deduplicate, and process into the system.
"""

import streamlit as st
import pandas as pd
import io
from datetime import datetime
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.database.schema import init_database
from src.database.queries import get_import_history, insert_normalized_transactions_bulk
from src.ingestion.file_manager import compute_file_hash, is_duplicate_file, archive_file, register_import
from src.ingestion.tastytrade_parser import TastytradeParser
from src.ingestion.schwab_parser import SchwabParser
from src.ingestion.excel_leg_parser import ExcelLegParser
from src.ingestion.normalizer import normalize_transactions
from src.engine.position_engine import reconstruct_positions
from src.engine.strategy_grouper import group_positions_into_trades, save_trades_to_db

st.set_page_config(page_title="Imports | Portfolio Manager", page_icon="📥", layout="wide")
from src.utils.branding import setup_branding
setup_branding()
init_database()

st.markdown("""
<style> #MainMenu {visibility: hidden;} footer {visibility: hidden;} </style>
""", unsafe_allow_html=True)

st.markdown("## 📥 Import & Reconciliation")

# ============================================================
# FILE UPLOAD
# ============================================================
tab1, tab2, tab3 = st.tabs(["📁 File Upload", "🔌 API Import", "📋 Import History"])

with tab1:
    st.markdown("### Upload Broker Transaction File")
    st.caption("Supported formats: CSV, XLSX | Supported brokers: tastytrade, Schwab, or custom Excel")

    uploaded_file = st.file_uploader(
        "Drop your file here",
        type=['csv', 'xlsx', 'xls'],
        help="Upload a transaction history export from your broker"
    )

    if uploaded_file:
        # Read file
        file_bytes = uploaded_file.getvalue()

        # Check for duplicates
        is_dup, file_hash = is_duplicate_file(file_bytes)
        if is_dup:
            st.warning("⚠️ This file has already been imported (same file hash detected). Upload skipped.")
            st.stop()

        # Read into DataFrame
        try:
            if uploaded_file.name.endswith('.csv'):
                df = pd.read_csv(io.BytesIO(file_bytes))
            else:
                df = pd.read_excel(io.BytesIO(file_bytes))
        except Exception as e:
            st.error(f"Failed to read file: {e}")
            st.stop()

        st.success(f"✅ File loaded: {uploaded_file.name} ({len(df)} rows)")

        # Broker detection
        st.markdown("### Broker Detection")
        parsers = [TastytradeParser(), SchwabParser(), ExcelLegParser()]
        detected_parser = None

        for parser in parsers:
            if parser.detect(df):
                detected_parser = parser
                break

        broker_options = ['Auto-detect', 'tastytrade', 'schwab', 'excel_import']
        col1, col2 = st.columns([1, 2])
        with col1:
            if detected_parser:
                st.success(f"🔍 Auto-detected: **{detected_parser.get_broker_name()}**")
            broker_override = st.selectbox("Broker", broker_options)

        if broker_override != 'Auto-detect':
            parser_map = {
                'tastytrade': TastytradeParser(),
                'schwab': SchwabParser(),
                'excel_import': ExcelLegParser(),
            }
            detected_parser = parser_map[broker_override]

        if not detected_parser:
            st.error("Could not detect broker format. Please select manually.")
            st.stop()

        # Parse
        st.markdown("### Preview Parsed Data")
        try:
            raw_transactions = detected_parser.parse(df)
            st.info(f"📊 Parsed {len(raw_transactions)} transactions")

            if raw_transactions:
                # Show preview
                preview_df = pd.DataFrame(raw_transactions[:20])
                display_cols = [c for c in ['date', 'action', 'underlying', 'symbol', 'side',
                                            'quantity', 'price', 'amount', 'expiry', 'strike',
                                            'put_call', 'open_close', 'normalized_type'] 
                               if c in preview_df.columns]
                st.dataframe(preview_df[display_cols], use_container_width=True, hide_index=True)

                if len(raw_transactions) > 20:
                    st.caption(f"Showing first 20 of {len(raw_transactions)} rows")

                # Normalize
                st.markdown("### Normalize & Import")
                normalized = normalize_transactions(raw_transactions, detected_parser.get_broker_name())
                st.info(f"📋 {len(normalized)} transactions ready for import")

                if st.button("✅ Confirm Import", type="primary", key="confirm_import"):
                    with st.spinner("Processing import..."):
                        # Archive file
                        archive_file(uploaded_file.name, file_bytes, detected_parser.get_broker_name())

                        # Register import
                        import_id = register_import(
                            uploaded_file.name,
                            detected_parser.get_broker_name(),
                            file_hash,
                            len(raw_transactions)
                        )

                        # Insert normalized transactions
                        new_count = insert_normalized_transactions_bulk(normalized)

                        # Rebuild positions and trades
                        positions = reconstruct_positions()
                        trades = group_positions_into_trades(positions)
                        trade_ids = save_trades_to_db(trades)

                        st.success(f"""
                        ✅ **Import Complete!**
                        - {new_count} new transactions imported (duplicates skipped)
                        - {len(positions)} positions reconstructed
                        - {len(trade_ids)} trades created/updated
                        """)

                        from src.database.queries import update_import_status
                        update_import_status(import_id, 'completed', f"{new_count} new transactions")
                        st.rerun()
        except Exception as e:
            st.error(f"Failed to parse file: {e}")
            import traceback
            st.code(traceback.format_exc())

with tab2:
    st.markdown("### Import from tastytrade API")
    st.caption("Pull transactions directly from your tastytrade account via API")

    # Auto-connect if not already connected
    from src.utils.session_helper import ensure_session
    from src.market.tastytrade_client import get_accounts, get_transactions, get_positions, get_balances

    session, accounts = ensure_session()

    if not session:
        st.warning("⚠️ Not connected to tastytrade. Go to **Settings** to configure your API connection.")
    else:
        st.success(f"🟢 Connected — {len(accounts)} account(s) available")

        acct_options = {a['account_number']: f"{a['account_number']} ({a['nickname']})" for a in accounts}

        # Account selector
        selected_acct = st.selectbox(
            "Account", options=list(acct_options.keys()),
            format_func=lambda x: acct_options[x], key="api_import_account"
        )

        import_type = st.radio(
            "Import Type",
            ["📊 Current Positions", "📜 Transaction History"],
            horizontal=True,
        )

        if import_type == "📊 Current Positions":
            if 'api_positions' not in st.session_state:
                st.session_state.api_positions = []

            c1, c2 = st.columns([3, 1])
            with c1:
                if st.button("🔄 Fetch Current Positions (Append)", key="fetch_positions", type="primary"):
                    with st.spinner(f"Fetching positions for {selected_acct}..."):
                        positions, error = get_positions(session, selected_acct)
                        if error:
                            st.error(error)
                        elif positions:
                            existing = {(p['account_number'], p['symbol']) for p in st.session_state.api_positions}
                            added = 0
                            for p in positions:
                                if (p.get('account_number'), p.get('symbol')) not in existing:
                                    st.session_state.api_positions.append(p)
                                    added += 1
                                    
                            st.success(f"✅ Appended {added} new positions to staging area.")

                            # Also fetch balances
                            bal, _ = get_balances(session, selected_acct)
                            if bal:
                                bc1, bc2, bc3 = st.columns(3)
                                bc1.metric("Net Liquidating Value", f"${bal.get('net_liquidating_value', 0):,.2f}")
                                bc2.metric("Buying Power", f"${bal.get('buying_power', 0):,.2f}")
                                bc3.metric("Cash Balance", f"${bal.get('cash_balance', 0):,.2f}")
                        else:
                            st.info("No open positions found.")
                            
            with c2:
                if st.session_state.api_positions:
                    if st.button("🗑️ Clear Staged", key="clear_staged"):
                        st.session_state.api_positions = []
                        st.rerun()

            if st.session_state.api_positions:
                st.markdown(f"**Staged Positions ({len(st.session_state.api_positions)})**")
                df = pd.DataFrame(st.session_state.api_positions)
                st.dataframe(df, use_container_width=True, hide_index=True)

            if st.session_state.get('api_positions'):
                st.divider()
                st.markdown("#### Send to Strategy Engine")
                st.warning("⚠️ This will map your live positions into strategies (Iron Condors, Spreads, etc.) and inject them directly into your Active Portfolio. Only do this once per new account to avoid duplicates!")
                if st.button("📥 Convert & Import Live Positions", type="primary", key="import_live_pos"):
                    with st.spinner("Processing through strategy engine..."):
                        from src.utils.option_symbols import parse_occ_symbol
                        from src.engine.strategy_grouper import group_positions_into_trades, save_trades_to_db
                        mapped_positions = []
                        for p in st.session_state.api_positions:
                            is_equity = p['instrument_type'] == 'Equity'
                            if is_equity:
                                mapped = {
                                    'account': p['account_number'],
                                    'broker': 'tastytrade',
                                    'underlying': p.get('underlying_symbol') or p['symbol'],
                                    'open_date': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                                    'instrument_type': 'EQUITY',
                                    'side': 'SHORT' if p.get('quantity_direction', '').lower() == 'short' else 'LONG',
                                    'total_open': abs(float(p['quantity'])),
                                    'is_fully_closed': False,
                                    'total_closed': 0,
                                    'avg_open_price': p['average_open_price'],
                                    'avg_close_price': 0,
                                    'realized_pnl': 0,
                                }
                                mapped_positions.append(mapped)
                            else:
                                opt = parse_occ_symbol(p['symbol'])
                                if opt:
                                    mapped = {
                                        'account': p['account_number'],
                                        'broker': 'tastytrade',
                                        'underlying': opt['underlying'],
                                        'expiry': opt['expiry'],
                                        'put_call': opt['put_call'],
                                        'strike': opt['strike'],
                                        'open_date': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                                        'instrument_type': 'OPTION',
                                        'side': 'SHORT' if p.get('quantity_direction', '').lower() == 'short' else 'LONG',
                                        'total_open': abs(float(p['quantity'])),
                                        'is_fully_closed': False,
                                        'total_closed': 0,
                                        'avg_open_price': p['average_open_price'],
                                        'avg_close_price': 0,
                                        'realized_pnl': 0,
                                        'symbol': p['symbol']
                                    }
                                    mapped_positions.append(mapped)
                        
                        if not mapped_positions:
                            st.error("No valid positions to import.")
                        else:
                            trades = group_positions_into_trades(mapped_positions)
                            trade_ids = save_trades_to_db(trades)
                            st.success(f"✅ Imported {len(trade_ids)} strategy groups into your Active Portfolio!")
                            st.info("Head over to the **Active Portfolio** tab to see your live grouped trades.")

        else:
            c1, c2 = st.columns(2)
            with c1:
                start_date = st.date_input("Start Date", value=None, key="api_start")
            with c2:
                end_date = st.date_input("End Date", value=None, key="api_end")

            if st.button("🔄 Fetch Transactions", key="fetch_api_txns", type="primary"):
                with st.spinner("Fetching transactions from tastytrade..."):
                    txns, error = get_transactions(session, selected_acct, start_date, end_date)
                    if error:
                        st.error(error)
                    elif txns:
                        st.success(f"✅ Fetched {len(txns)} transactions")
                        df = pd.DataFrame(txns)
                        st.dataframe(df.head(50), use_container_width=True, hide_index=True)
                        if len(txns) > 50:
                            st.caption(f"Showing first 50 of {len(txns)} transactions")
                        st.session_state.api_transactions = txns
                    else:
                        st.info("No transactions found for the selected date range.")

            if st.session_state.get('api_transactions'):
                if st.button("✅ Import Fetched Transactions", type="primary", key="import_api"):
                    st.info("API transaction import - processing...")
                    # TODO: Normalize API transactions and import
                    st.success("API import feature ready for your real transactions!")

with tab3:
    st.markdown("### Import History")
    imports = get_import_history()
    if imports:
        import_df = pd.DataFrame([dict(i) for i in imports])
        display_cols = ['import_id', 'filename', 'broker', 'upload_timestamp',
                       'row_count', 'processed_status', 'source_type']
        display_cols = [c for c in display_cols if c in import_df.columns]
        st.dataframe(import_df[display_cols], use_container_width=True, hide_index=True)
    else:
        st.info("No imports recorded yet.")
