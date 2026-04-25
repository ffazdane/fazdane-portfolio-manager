"""
Page 10: YTD Transaction Upload
Supports both single-year (gain/loss worksheets) and multi-year
(full transaction history) uploads for TastyTrade and Schwab.

Multi-year mode: file covers 2024–2025 → both years are deleted and
reloaded atomically for the detected account.
"""

import streamlit as st
import pandas as pd
import io
import os
import sys
from datetime import datetime
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.utils.auth import check_password
if not check_password():
    st.stop()

from src.database.queries import (
    get_account_master,
    insert_transaction_upload_batch,
    delete_broker_transactions,
    insert_broker_transactions_bulk,
    is_year_locked,
    get_broker_transactions,
)
from src.ingestion.tastytrade_parser import TastytradeParser
from src.ingestion.tastytrade_gain_loss_parser import TastytradeGainLossParser
from src.ingestion.tastytrade_history_parser import TastytradeHistoryParser
from src.ingestion.schwab_parser import SchwabParser
from src.ingestion.ytd_validator import (
    detect_year_from_filename,
    detect_year_range_from_filename,
    detect_account_from_filename,
    detect_file_type,
    validate_tastytrade_filename,
    validate_schwab_filename,
    validate_parsed_transactions,
)


# ─── CSS ─────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
    #MainMenu {visibility: hidden;} footer {visibility: hidden;}
    .validation-ok   { color: #00D4AA; font-weight: 600; }
    .validation-fail { color: #FF4B4B; font-weight: 600; }
    .info-box {
        background: linear-gradient(135deg, #1A1F2E 0%, #252B3B 100%);
        border: 1px solid rgba(0, 212, 170, 0.15);
        border-radius: 12px; padding: 16px 20px; margin-bottom: 16px;
    }
    .year-pill {
        display: inline-block; background: rgba(0,212,170,0.15);
        border: 1px solid #00D4AA; border-radius: 20px;
        padding: 2px 12px; margin: 2px; font-size: 13px; color: #00D4AA;
    }
</style>
""", unsafe_allow_html=True)

st.markdown("## 📁 Broker Data Upload")
st.caption("Upload broker transaction files — single-year worksheets or full multi-year history. Years are detected automatically from the data.")

# ─── Load accounts ────────────────────────────────────────────────────────────
account_rows = get_account_master()
accounts     = [dict(a) for a in account_rows]
account_nums = [a['account_number'] for a in accounts]
account_map  = {a['account_number']: a for a in accounts}

if not accounts:
    st.error("No account mappings found. Add accounts in the Account Mappings tab.")
    st.stop()

# ─── Tabs ─────────────────────────────────────────────────────────────────────
tab_upload, tab_history, tab_accounts = st.tabs(
    ["📤 Upload File", "📋 Upload History", "🗂️ Account Mappings"]
)

# ══════════════════════════════════════════════════════════════════════════════
# TAB 1 — File Upload
# ══════════════════════════════════════════════════════════════════════════════
with tab_upload:

    # ── Naming rules ──────────────────────────────────────────────────────
    with st.expander("ℹ️ File Naming Rules & Supported Formats", expanded=False):
        st.markdown("""
        <div class="info-box">
        <b>TastyTrade — Full Transaction History (multi-year)</b><br>
        Pattern: <code>tastytrade_transactions_history_x{AccountNumber}_{YYMMDD}_to_{YYMMDD}.csv</code><br>
        Example: <code>tastytrade_transactions_history_x5WT12803_240101_to_251231.csv</code>
        <br><br>
        <b>TastyTrade — Gain/Loss Tax Worksheet (single year)</b><br>
        Pattern: <code>YYYY-AccountNumber-gain_loss_tax_worksheet.csv</code><br>
        Example: <code>2026-5WT12803-gain_loss_tax_worksheet.csv</code>
        <br><br>
        <b>Schwab — Transaction History (multi-year)</b><br>
        Pattern: <code>Individual_{AccountNumber}_Transactions_YYYYMMDD-HHMMSS.csv</code><br>
        Example: <code>Individual_XXX177_Transactions_20260425-142924.csv</code>
        </div>
        """, unsafe_allow_html=True)

    # ── Broker override (only control needed) ────────────────────────────
    broker_override = st.selectbox(
        "Broker (auto-detected from filename — override if needed)",
        ["Auto-detect", "TastyTrade", "Schwab"],
        help="Leave on Auto-detect unless the system misidentifies your file."
    )

    st.divider()

    uploaded_file = st.file_uploader(
        "Drop your broker transaction file here",
        type=['csv', 'xlsx', 'xls'],
        help="Full transaction history (multi-year) or gain/loss worksheet (single year)"
    )

    if not uploaded_file:
        st.stop()

    file_bytes = uploaded_file.getvalue()
    filename   = uploaded_file.name

    st.markdown("### 🔍 Validation Checks")
    errors   = []
    warnings = []

    # ── 1. Account detection ──────────────────────────────────────────────
    detected_account = detect_account_from_filename(filename, account_nums)
    if detected_account:
        acc_info = account_map[detected_account]
        st.markdown(f"✅ **Account detected:** `{detected_account}` — {acc_info['broker_name']} ({acc_info['platform_name']})")
    else:
        errors.append(f"Could not detect account number in filename. Known accounts: {', '.join(account_nums)}")
        st.markdown(f"❌ **Account detection failed** — filename must contain one of: `{'`, `'.join(account_nums)}`")

    # ── 2. Broker detection ───────────────────────────────────────────────
    if detected_account:
        detected_broker = acc_info['broker_name']
    else:
        detected_broker = None

    if broker_override != "Auto-detect":
        if detected_broker and broker_override != detected_broker:
            errors.append(f"Broker mismatch: file maps to `{detected_broker}` but override is `{broker_override}`.")
        else:
            detected_broker = broker_override
        st.markdown(f"✅ **Broker override:** `{detected_broker}`")
    else:
        if detected_broker:
            st.markdown(f"✅ **Broker detected:** `{detected_broker}`")
        else:
            warnings.append("Could not auto-detect broker.")
            st.markdown("⚠️ **Broker:** Could not auto-detect — please select manually.")

    # ── 3. Filename pattern validation ───────────────────────────────────
    if detected_account and detected_broker and not errors:
        if detected_broker == "TastyTrade":
            ok, msg = validate_tastytrade_filename(filename, detected_account)
        else:
            ok, msg = validate_schwab_filename(filename, detected_account)
        if ok:
            st.markdown("✅ **Filename pattern:** Valid")
        else:
            errors.append(msg)
            st.markdown(f"❌ **Filename pattern invalid:** {msg}")

    # ── Note: years & lock check deferred until after parsing ─────────────
    st.info("📋 Years will be detected automatically from the data after parsing.")

    # ── Stop on hard errors ───────────────────────────────────────────────
    if errors:
        st.error("**Upload blocked** — fix the errors above before proceeding.")
        st.stop()

    # ── Read the file ─────────────────────────────────────────────────────
    st.divider()
    st.markdown("### 📊 File Preview")

    try:
        if filename.endswith('.csv'):
            df = pd.read_csv(io.BytesIO(file_bytes))
        else:
            df = pd.read_excel(io.BytesIO(file_bytes))
    except Exception as e:
        st.error(f"Could not read file: {e}")
        st.stop()

    st.caption(f"File has **{len(df):,}** rows × {len(df.columns)} columns")

    with st.expander("🔬 Detected Columns (expand to debug)", expanded=False):
        st.code(', '.join([str(c) for c in df.columns]))
        st.dataframe(df.head(3), use_container_width=True)

    # ── Smart parser selection ────────────────────────────────────────────
    if detected_broker == "TastyTrade":
        hist_parser = TastytradeHistoryParser()
        gl_parser   = TastytradeGainLossParser()
        tt_parser   = TastytradeParser()
        if hist_parser.detect(df):
            parser = hist_parser
            st.info("📋 Detected: **TastyTrade Transaction History** (multi-year supported)")
        elif gl_parser.detect(df):
            parser = gl_parser
            st.info("📋 Detected: **TastyTrade Gain/Loss Tax Worksheet**")
        elif tt_parser.detect(df):
            parser = tt_parser
            st.info("📋 Detected: **TastyTrade Legacy Transaction History**")
        else:
            parser = hist_parser
            st.warning("⚠️ Could not auto-detect TastyTrade format — attempting History parser")
    else:
        parser = SchwabParser()
        st.info("📋 Using: **Schwab Transaction History** parser")

    # ── Parse ─────────────────────────────────────────────────────────────
    try:
        raw_txns = parser.parse(df)
    except Exception as e:
        st.error(f"Parser failed: {e}")
        import traceback
        st.code(traceback.format_exc())
        st.stop()

    ok, msg = validate_parsed_transactions(raw_txns)
    if not ok:
        st.error(
            f"Parsed data validation failed: {msg}\n\n"
            "Expand 'Detected Columns' above to verify the file format."
        )
        st.stop()

    # Tag metadata
    for t in raw_txns:
        t['source_file_name'] = filename
        t['broker']           = detected_broker
        if 'account' not in t or t['account'] == 'default':
            t['account'] = detected_account

    # ── Detect years FROM THE DATA (source of truth) ──────────────────────
    def _extract_year(txn):
        """Safely extract year from any date format in a transaction dict."""
        if txn.get('year'):
            return int(txn['year'])
        d = str(txn.get('date', '') or '').strip()
        if not d:
            return None
        # YYYY-MM-DD  (TastyTrade ISO)
        if len(d) >= 4 and d[4:5] == '-':
            return int(d[:4])
        # MM/DD/YYYY  (Schwab)
        if '/' in d:
            parts = d.split('/')
            if len(parts) == 3 and len(parts[2]) >= 4:
                return int(parts[2][:4])
        # Last resort — any 4-digit 20xx
        import re as _re
        m = _re.search(r'(20\d{2})', d)
        return int(m.group(1)) if m else None

    txn_by_year = defaultdict(list)
    for t in raw_txns:
        y = _extract_year(t)
        if y:
            txn_by_year[y].append(t)

    data_years = sorted(txn_by_year.keys())   # years actually in the data

    # ── Year pills ────────────────────────────────────────────────────────
    if len(data_years) > 1:
        pills = " ".join([f'<span class="year-pill">{y}</span>' for y in data_years])
        st.markdown(f"📅 **Years detected from data:** {pills}", unsafe_allow_html=True)
    elif data_years:
        st.markdown(f"✅ **Year detected from data:** `{data_years[0]}`")

    # ── Year-lock check (against actual data years) ───────────────────────
    locked_years = [y for y in data_years if is_year_locked(y)]
    if locked_years:
        st.error(f"❌ Year(s) **{locked_years}** are locked. Unlock via Year Close page before uploading.")
        st.stop()
    else:
        st.markdown(f"✅ **All years open** — uploads allowed.")

    # ── Existing data summary (against actual data years) ─────────────────
    existing_by_year = {}
    if detected_account:
        for y in data_years:
            existing = get_broker_transactions(year=y, account=detected_account)
            if existing:
                existing_by_year[y] = len(existing)

    if existing_by_year:
        total_existing = sum(existing_by_year.values())
        detail = ", ".join([f"{y}: {n:,}" for y, n in sorted(existing_by_year.items())])
        st.warning(
            f"⚠️ **{total_existing:,} existing transactions** will be replaced — "
            f"({detail})."
        )

    st.success(f"✅ Parsed **{len(raw_txns):,}** transactions — "
               f"{len(data_years)} year(s): {', '.join(str(y) for y in data_years)}")

    # ── Year breakdown table ──────────────────────────────────────────────
    breakdown_rows = []
    for y in data_years:
        yt = txn_by_year[y]
        amounts = [float(t.get('amount', 0) or 0) for t in yt]
        fees    = [float(t.get('fees',   0) or 0) for t in yt]
        breakdown_rows.append({
            "Year":             y,
            "Transactions":     len(yt),
            "Gross Flow":       f"${sum(amounts):,.2f}",
            "Total Fees":       f"${sum(fees):,.2f}",
            "Existing Records": existing_by_year.get(y, 0),
            "Action":           "🔄 Replace" if y in existing_by_year else "➕ New Load",
        })

    if breakdown_rows:
        st.markdown("**Year-by-Year Breakdown:**")
        st.dataframe(pd.DataFrame(breakdown_rows), hide_index=True, use_container_width=True)

    # Preview first 10 rows
    preview_df = pd.DataFrame(raw_txns[:10])
    pref_cols = ['date', 'underlying', 'symbol', 'side', 'open_close',
                 'quantity', 'price', 'amount', 'fees', 'normalized_type']
    show_cols = [c for c in pref_cols if c in preview_df.columns]
    if show_cols:
        st.dataframe(preview_df[show_cols], use_container_width=True, hide_index=True)
    if len(raw_txns) > 10:
        st.caption(f"Showing first 10 of {len(raw_txns):,} rows")

    # Summary metrics
    amounts = [float(t.get('amount', 0) or 0) for t in raw_txns]
    fees    = [float(t.get('fees', 0) or 0) for t in raw_txns]
    sc1, sc2, sc3, sc4 = st.columns(4)
    sc1.metric("Total Transactions",  f"{len(raw_txns):,}")
    sc2.metric("Total Gross Flow",    f"${sum(amounts):,.2f}")
    sc3.metric("Total Fees",          f"${sum(fees):,.2f}")
    sc4.metric("Years Covered",       len(txn_by_year))

    # ── Confirm & Load ────────────────────────────────────────────────────
    st.divider()

    years_label = ', '.join(str(y) for y in data_years)
    replace_note = (
        f"Replace & Load {len(raw_txns):,} Transactions ({years_label})"
        if existing_by_year
        else
        f"Load {len(raw_txns):,} Transactions ({years_label})"
    )

    col_btn, col_note = st.columns([1, 3], vertical_alignment="center")
    with col_btn:
        do_load = st.button(f"💾 {replace_note}", type="primary", use_container_width=True)
    with col_note:
        if existing_by_year:
            st.warning("This will **permanently replace** all existing records for the years above.")

    if do_load:
        with st.spinner("Processing upload..."):
            for y in data_years:
                year_txns = txn_by_year[y]

                # 1. Delete existing records for this year+account
                delete_broker_transactions(detected_account, y)

                # 2. Register upload batch
                batch_id = insert_transaction_upload_batch(
                    broker_name=detected_broker,
                    platform_name=acc_info['platform_name'],
                    account_number=detected_account,
                    upload_year=y,
                    file_name=filename,
                    file_path=f"uploaded/{filename}",
                    record_count=len(year_txns)
                )

                # 3. Insert transactions for this year
                insert_broker_transactions_bulk(batch_id, detected_account, y, year_txns)

            # 4. Backup
            try:
                from src.database.persistence import backup_database
                backup_database(reason=f"History Upload {filename}")
            except Exception:
                pass

        action_word = "replaced and loaded" if existing_by_year else "loaded"
        st.success(
            f"✅ Successfully {action_word} **{len(raw_txns):,} transactions** "
            f"for account `{detected_account}` / year(s) `{years_label}`.\n\n"
            f"View them on the **📁 Broker Data Upload Page**."
        )
        st.balloons()

# ══════════════════════════════════════════════════════════════════════════════
# TAB 2 — Upload History
# ══════════════════════════════════════════════════════════════════════════════
with tab_history:
    st.markdown("### Upload History")
    st.caption("All YTD upload batches recorded in the system.")

    try:
        from src.database.connection import get_db_readonly
        with get_db_readonly() as conn:
            batches = conn.execute(
                "SELECT * FROM transaction_upload_batches ORDER BY upload_datetime DESC"
            ).fetchall()

        if batches:
            batch_df = pd.DataFrame([dict(b) for b in batches])
            show = [c for c in ['batch_id', 'broker_name', 'account_number', 'upload_year',
                                  'file_name', 'record_count', 'upload_datetime', 'status']
                    if c in batch_df.columns]
            st.dataframe(batch_df[show], use_container_width=True, hide_index=True)
        else:
            st.info("No uploads yet.")
    except Exception as e:
        st.error(f"Could not load history: {e}")

    st.divider()
    st.markdown("### Transaction Count by Account & Year")
    try:
        from src.database.connection import get_db_readonly
        with get_db_readonly() as conn:
            rows = conn.execute(
                """SELECT account_number, broker_name, transaction_year,
                          COUNT(*) as tx_count,
                          SUM(net_amount) as total_net,
                          MAX(upload_datetime) as last_upload
                   FROM broker_transactions bt
                   LEFT JOIN transaction_upload_batches tub
                          ON bt.batch_id = tub.batch_id
                   GROUP BY account_number, broker_name, transaction_year
                   ORDER BY transaction_year DESC, account_number"""
            ).fetchall()
        if rows:
            rdf = pd.DataFrame([dict(r) for r in rows])
            if 'total_net' in rdf.columns:
                rdf['total_net'] = rdf['total_net'].apply(lambda x: f"${x:,.2f}" if x else "$0.00")
            st.dataframe(rdf, use_container_width=True, hide_index=True)
        else:
            st.info("No broker transactions in database yet.")
    except Exception as e:
        st.info("No broker transactions yet.")

# ══════════════════════════════════════════════════════════════════════════════
# TAB 3 — Account Mappings
# ══════════════════════════════════════════════════════════════════════════════
with tab_accounts:
    st.markdown("### Account Master Mappings")
    st.caption("These mappings drive automatic account detection from filenames.")

    acct_df = pd.DataFrame(accounts)
    st.dataframe(acct_df, use_container_width=True, hide_index=True)

    st.divider()
    st.markdown("#### Add New Account Mapping")
    nc1, nc2, nc3 = st.columns(3)
    with nc1:
        new_acct_num = st.text_input("Account Number", placeholder="e.g. ABC12345")
    with nc2:
        new_broker = st.selectbox("Broker Name", ["TastyTrade", "Schwab", "IBKR", "TD Ameritrade", "Other"])
    with nc3:
        new_platform = st.text_input("Platform Name", placeholder="e.g. Tasty")

    if st.button("➕ Add Account", disabled=not new_acct_num):
        try:
            from src.database.connection import get_db
            with get_db() as conn:
                conn.execute(
                    "INSERT OR IGNORE INTO account_master (account_number, broker_name, platform_name) VALUES (?, ?, ?)",
                    (new_acct_num.strip(), new_broker, new_platform.strip())
                )
            st.success(f"✅ Added account `{new_acct_num}` → {new_broker}")
            st.rerun()
        except Exception as e:
            st.error(f"Failed to add account: {e}")
