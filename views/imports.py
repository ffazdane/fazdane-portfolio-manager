"""
Page 5: Portfolio Imports
Upload broker files – both transaction history and live position snapshots.

Portfolio Import tab:
  - Accepts Schwab (Individual-Positions-*) and Tastytrade (tastytrade_positions_x*) CSVs
  - Auto-detects the broker and account number from the filename
  - REPLACES all active trades for that broker with the contents of the file
  - This gives an exact mirror of the broker's current position list

Transaction Import tab (unchanged):
  - Accepts transaction history files and normalises/deduplicates them
"""

import streamlit as st
import pandas as pd
import io
from datetime import datetime
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.utils.auth import check_password
if not check_password():
    st.stop()

from src.database.queries import (
    get_import_history, insert_normalized_transactions_bulk,
    delete_active_trades_by_broker,
)
from src.ingestion.file_manager import compute_file_hash, is_duplicate_file, archive_file, register_import
from src.ingestion.tastytrade_parser import TastytradeParser
from src.ingestion.schwab_parser import SchwabParser
from src.ingestion.excel_leg_parser import ExcelLegParser
from src.ingestion.normalizer import normalize_transactions
from src.ingestion.position_parser import (
    parse_position_file, detect_position_broker, is_position_file,
)
from src.engine.position_engine import reconstruct_positions
from src.engine.strategy_grouper import group_positions_into_trades, save_trades_to_db


st.markdown("""
<style> #MainMenu {visibility: hidden;} footer {visibility: hidden;} </style>
""", unsafe_allow_html=True)

st.markdown("## 📥 Portfolio Imports")

# ============================================================
# TABS
# ============================================================
tab_pos, tab_txn, tab_api, tab_hist = st.tabs([
    "📊 Portfolio Import",
    "📁 Transaction File",
    "🔌 API Import",
    "📋 Import History",
])


# ============================================================
# TAB 1 – PORTFOLIO POSITION IMPORT
# ============================================================
with tab_pos:
    st.markdown("### Import Current Positions from Broker")
    st.markdown("""
    Upload your broker's **current positions export** to sync your portfolio.

    > ⚡ **This will REPLACE all active trades for the detected broker account.**
    > Historical (closed) trades are never deleted.

    **Supported files:**
    | Broker | Filename pattern | How to export |
    |---|---|---|
    | **Schwab** | `Individual-Positions-YYYY-MM-DD-*.csv` | Positions page → Export |
    | **Tastytrade** | `tastytrade_positions_x{ACCT}_*.csv` | Positions page → Export |
    """)

    pos_file = st.file_uploader(
        "Drop your position file here",
        type=['csv'],
        key="pos_file_uploader",
        help="Schwab: Individual-Positions-*.csv  |  Tastytrade: tastytrade_positions_x*.csv",
    )

    if pos_file:
        file_bytes = pos_file.getvalue()
        raw_text = file_bytes.decode('utf-8', errors='replace')

        # ── Detect broker from filename ──────────────────────────────────────
        info = detect_position_broker(pos_file.name, raw_text)
        detected_broker  = info.get('broker')   # 'schwab' | 'tastytrade' | None
        detected_account = info.get('account')  # account number or None

        if not is_position_file(pos_file.name) and not detected_broker:
            st.warning(
                "⚠️ This file doesn't look like a position-snapshot export. "
                "Expected `Individual-Positions-*.csv` (Schwab) or "
                "`tastytrade_positions_x*.csv` (Tastytrade)."
            )

        # Detection summary
        broker_display = (detected_broker or 'unknown').capitalize()
        acct_display   = detected_account or 'unknown (will be extracted from file content)'

        st.info(
            f"🔍 **Detected:** Broker = `{broker_display}` | Account = `{acct_display}`"
        )

        # Manual overrides (rarely needed)
        with st.expander("Override broker / account (optional)", expanded=False):
            oc1, oc2 = st.columns(2)
            with oc1:
                broker_override = st.selectbox(
                    "Broker override",
                    ['(auto)', 'tastytrade', 'schwab'],
                    key="pos_broker_override",
                )
            with oc2:
                account_override = st.text_input(
                    "Account override",
                    placeholder="e.g. 5WT12803",
                    key="pos_account_override",
                )

        final_broker  = None if broker_override  == '(auto)' else broker_override
        final_account = None if not account_override.strip() else account_override.strip()

        # ── Parse the file ───────────────────────────────────────────────────
        try:
            df = pd.read_csv(io.BytesIO(file_bytes), header=None)
        except Exception as e:
            st.error(f"Failed to read CSV: {e}")
            st.stop()

        try:
            positions, used_broker, used_account = parse_position_file(
                df,
                pos_file.name,
                raw_text=raw_text,
                broker_override=final_broker,
                account_override=final_account,
            )
        except Exception as e:
            st.error(f"❌ Parse error: {e}")
            import traceback
            st.code(traceback.format_exc())
            st.stop()

        if not positions:
            st.warning("⚠️ No option positions found in this file. Check that the file is a valid positions export.")
        else:
            st.success(f"✅ Parsed **{len(positions)}** positions | Broker: `{used_broker}` | Account: `{used_account}`")

            # Preview
            preview_df = pd.DataFrame(positions)
            display_cols = [c for c in [
                'underlying', 'expiry', 'strike', 'put_call', 'side', 'total_open', 'avg_open_price', 'account'
            ] if c in preview_df.columns]
            st.dataframe(preview_df[display_cols], use_container_width=True, hide_index=True)

            # ── Confirm import ───────────────────────────────────────────────
            st.divider()
            st.markdown("#### Confirm Import")

            # Show current active trade count for this broker
            from src.database.queries import get_active_trades
            current_trades = [
                t for t in get_active_trades()
                if (t['broker'] or '').lower() == (used_broker or '').lower()
            ]
            if current_trades:
                st.warning(
                    f"⚠️ **{len(current_trades)} active trade(s)** currently exist for broker "
                    f"`{used_broker}`. They will be **permanently deleted** and replaced with the "
                    f"{len(positions)} positions from this file."
                )
            else:
                st.info(f"No existing active trades for broker `{used_broker}`. Positions will be added fresh.")

            if st.button(
                f"🔄 Replace `{used_broker}` Portfolio",
                type="primary",
                key="confirm_pos_import",
            ):
                with st.spinner("Importing positions…"):
                    # 1. Delete all active trades for this broker
                    deleted = delete_active_trades_by_broker(used_broker)

                    # 2. Group positions into strategy trades
                    trades = group_positions_into_trades(positions)
                    trade_ids = save_trades_to_db(trades)

                    # 3. Backup
                    from src.database.persistence import backup_database
                    backup_database(reason=f"position import {pos_file.name}")

                st.success(f"""
✅ **Portfolio Import Complete!**
- 🗑️ {deleted} old active trade(s) removed for broker `{used_broker}`
- 📥 {len(positions)} positions imported
- 🗂️ {len(trade_ids)} strategy group(s) created
                """)
                st.balloons()
                st.rerun()


# ============================================================
# TAB 2 – TRANSACTION FILE UPLOAD (original flow, preserved)
# ============================================================
with tab_txn:
    st.markdown("### Upload Broker Transaction File")
    st.caption("Supported formats: CSV, XLSX | Supported brokers: tastytrade, Schwab, or custom Excel")

    uploaded_file = st.file_uploader(
        "Drop your file here",
        type=['csv', 'xlsx', 'xls'],
        key="txn_file_uploader",
        help="Upload a transaction history export from your broker",
    )

    if uploaded_file:
        file_bytes = uploaded_file.getvalue()

        # Reject position files uploaded here
        if is_position_file(uploaded_file.name):
            st.warning(
                "⚠️ This looks like a **position snapshot** file, not a transaction history file. "
                "Please use the **📊 Portfolio Import** tab instead."
            )
            st.stop()

        # Check for duplicates
        is_dup, file_hash = is_duplicate_file(file_bytes)
        if is_dup:
            st.warning("⚠️ This file has already been imported (same file hash detected). You can proceed to review and re-import if necessary.")

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

        # ── Broker & Account Detection ────────────────────────────────────────
        st.markdown("### Broker & Account Detection")
        from src.ingestion.ytd_validator import detect_broker_and_account_from_filename
        fn_detect = detect_broker_and_account_from_filename(uploaded_file.name)

        filename_broker  = fn_detect['broker']
        filename_account = fn_detect['account']
        detect_method    = fn_detect['method']

        BROKER_PARSER_MAP = {
            'tastytrade':   TastytradeParser(),
            'schwab':       SchwabParser(),
            'excel_import': ExcelLegParser(),
        }
        broker_key_map = {
            'TastyTrade': 'tastytrade',
            'Schwab':     'schwab',
        }

        if filename_broker:
            method_label = "filename pattern" if detect_method == 'filename_pattern' else "account master"
            st.success(f"🔍 **Filename detected:** Broker = `{filename_broker}` | Account = `{filename_account or 'unknown'}` *(via {method_label})*")
        if filename_account and not filename_broker:
            st.warning(f"⚠️ Account `{filename_account}` found in filename but no matching broker rule — select manually below.")

        # Content-based parser detection
        parsers = [TastytradeParser(), SchwabParser(), ExcelLegParser()]
        content_parser = None
        for parser in parsers:
            if parser.detect(df):
                content_parser = parser
                break

        broker_options = ['Auto-detect', 'tastytrade', 'schwab', 'excel_import']
        col1, col2 = st.columns([1, 2])
        with col1:
            if content_parser and not filename_broker:
                st.info(f"🔬 Content-detected: **{content_parser.get_broker_name()}**")
            broker_override = st.selectbox("Broker (override if wrong)", broker_options, key="txn_broker_override")

        # Final parser selection
        if broker_override != 'Auto-detect':
            detected_parser = BROKER_PARSER_MAP.get(broker_override)
        elif filename_broker:
            broker_key = broker_key_map.get(filename_broker, filename_broker.lower())
            detected_parser = BROKER_PARSER_MAP.get(broker_key, content_parser)
        else:
            detected_parser = content_parser

        if not detected_parser:
            st.error("Could not detect broker format. Please select manually.")
            st.stop()

        st.info(f"✅ Using parser: **{detected_parser.get_broker_name()}**"
                + (f" | Account: `{filename_account}`" if filename_account else ""))

        # Parse
        st.markdown("### Preview Parsed Data")
        try:
            raw_transactions = detected_parser.parse(df)
            st.info(f"📊 Parsed {len(raw_transactions)} transactions")

            if raw_transactions:
                preview_df = pd.DataFrame(raw_transactions[:20])
                display_cols = [c for c in ['date', 'action', 'underlying', 'symbol', 'side',
                                             'quantity', 'price', 'amount', 'expiry', 'strike',
                                             'put_call', 'open_close', 'normalized_type']
                                if c in preview_df.columns]
                st.dataframe(preview_df[display_cols], use_container_width=True, hide_index=True)

                if len(raw_transactions) > 20:
                    st.caption(f"Showing first 20 of {len(raw_transactions)} rows")

                # Normalize & import
                st.markdown("### Normalize & Import")
                normalized = normalize_transactions(raw_transactions, detected_parser.get_broker_name())
                st.info(f"📋 {len(normalized)} transactions ready for import")

                if st.button("✅ Confirm Import", type="primary", key="confirm_txn_import"):
                    with st.spinner("Processing import..."):
                        archive_file(uploaded_file.name, file_bytes, detected_parser.get_broker_name())
                        import_id = register_import(
                            uploaded_file.name,
                            detected_parser.get_broker_name(),
                            file_hash,
                            len(raw_transactions),
                        )
                        new_count = insert_normalized_transactions_bulk(normalized)

                        all_positions = reconstruct_positions()
                        imported_underlyings = set(txn['underlying'] for txn in normalized if txn.get('underlying'))
                        imported_broker = detected_parser.get_broker_name().lower()

                        positions = [
                            p for p in all_positions
                            if p.get('underlying') in imported_underlyings
                            and (imported_broker in (p.get('broker') or '').lower())
                        ]

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

                        from src.database.persistence import backup_database
                        backup_database(reason=f"file import {uploaded_file.name}")

                        st.rerun()
        except Exception as e:
            st.error(f"Failed to parse file: {e}")
            import traceback
            st.code(traceback.format_exc())


# ============================================================
# TAB 3 – API IMPORT (unchanged)
# ============================================================
with tab_api:
    st.markdown("### Import from tastytrade API")
    st.caption("Pull transactions directly from your tastytrade account via API")

    from src.utils.session_helper import ensure_session
    from src.market.tastytrade_client import get_accounts, get_transactions, get_positions, get_balances

    session, accounts = ensure_session()

    if not session:
        st.warning("⚠️ Not connected to tastytrade. Go to **Settings** to configure your API connection.")
    else:
        st.success(f"🟢 Connected — {len(accounts)} account(s) available")

        acct_options = {a['account_number']: f"{a['account_number']} ({a['nickname']})" for a in accounts}
        selected_acct = st.selectbox(
            "Account", options=list(acct_options.keys()),
            format_func=lambda x: acct_options[x], key="api_import_account",
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
                fetch_disabled = selected_acct is None
                if st.button("🔄 Fetch Current Positions (Append)", key="fetch_positions", type="primary", disabled=fetch_disabled):
                    if not selected_acct:
                        st.error("No account selected.")
                    else:
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
                st.warning("⚠️ This will map your live positions into strategies and inject them directly into your Active Portfolio. Only do this once per new account to avoid duplicates!")
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
                                        'symbol': p['symbol'],
                                    }
                                    mapped_positions.append(mapped)

                        if not mapped_positions:
                            st.error("No valid positions to import.")
                        else:
                            trades = group_positions_into_trades(mapped_positions)
                            trade_ids = save_trades_to_db(trades)
                            st.success(f"✅ Imported {len(trade_ids)} strategy groups into your Active Portfolio!")
                            st.info("Head over to the **Active Portfolio** tab to see your live grouped trades.")

                            from src.database.persistence import backup_database
                            backup_database(reason="api import live positions")

        else:
            c1, c2 = st.columns(2)
            with c1:
                start_date = st.date_input("Start Date", value=None, key="api_start")
            with c2:
                end_date = st.date_input("End Date", value=None, key="api_end")

            if st.button("🔄 Fetch Transactions", key="fetch_api_txns", type="primary", disabled=(selected_acct is None)):
                if not selected_acct:
                    st.error("No account selected.")
                else:
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
                    st.success("API import feature ready for your real transactions!")


# ============================================================
# TAB 4 – IMPORT HISTORY
# ============================================================
with tab_hist:
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
