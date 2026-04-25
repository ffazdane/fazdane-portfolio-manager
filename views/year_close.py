"""
Page 12: Year Close & Archive
Lock/unlock years for end-of-year archiving and compliance freeze.
"""

import streamlit as st
import pandas as pd
from datetime import datetime
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.utils.auth import check_password
if not check_password():
    st.stop()

from src.database.queries import get_year_close_status, archive_year, get_broker_transactions


# ─── CSS ────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
    #MainMenu {visibility: hidden;} footer {visibility: hidden;}
    .status-open   { color: #00D4AA; font-weight: 700; }
    .status-closed { color: #FF4B4B; font-weight: 700; }
    .rule-card {
        background: linear-gradient(135deg, #1A1F2E 0%, #252B3B 100%);
        border: 1px solid rgba(0, 212, 170, 0.15);
        border-radius: 12px; padding: 16px 20px; margin-bottom: 8px;
    }
</style>
""", unsafe_allow_html=True)

st.markdown("## 🔒 Year Close & Archive")
st.caption("Lock prior years to finalize reporting and prevent further uploads or modifications.")

# ─── Load state ──────────────────────────────────────────────────────────────
year_statuses = get_year_close_status()
status_map    = {y['year']: dict(y) for y in year_statuses}
current_year  = datetime.now().year

years_with_data = set()
try:
    from src.database.connection import get_db_readonly
    with get_db_readonly() as conn:
        rows = conn.execute(
            "SELECT DISTINCT transaction_year FROM broker_transactions"
        ).fetchall()
        years_with_data = {r['transaction_year'] for r in rows}
except Exception:
    pass

all_years = sorted(
    list(set(list(status_map.keys()) + [current_year, current_year - 1, current_year - 2] + list(years_with_data))),
    reverse=True
)

# ─── Layout ──────────────────────────────────────────────────────────────────
col_action, col_overview = st.columns([3, 2])

with col_overview:
    st.markdown("### Year Status Overview")
    status_rows = []
    for y in all_years:
        s = status_map.get(y)
        locked    = bool(s and s.get("is_locked"))
        has_data  = y in years_with_data
        txn_count = 0
        if has_data:
            txns = get_broker_transactions(year=y)
            txn_count = len(txns)

        status_rows.append({
            "Year":        y,
            "Status":      "🔒 Closed" if locked else "🟢 Open",
            "Has Data":    "✅" if has_data else "—",
            "Transactions": txn_count if has_data else 0,
            "Closed By":   s.get("closed_by", "—") if s and locked else "—",
            "Date Closed": str(s.get("closed_datetime", "—"))[:16] if s and locked else "—",
        })

    status_df = pd.DataFrame(status_rows)
    st.dataframe(status_df, hide_index=True, use_container_width=True)

with col_action:
    st.markdown("### Manage Year")
    year_to_manage = st.selectbox("Select Year", options=all_years, key="yc_year_sel")

    s = status_map.get(year_to_manage)
    is_locked = bool(s and s.get("is_locked"))
    has_data  = year_to_manage in years_with_data

    st.divider()

    if is_locked:
        # ── LOCKED STATE ──────────────────────────────────────────────────
        st.markdown(f"""
        <div class="rule-card">
        🔒 <b>Year {year_to_manage} is CLOSED</b><br>
        Closed by: <code>{s.get('closed_by', 'N/A')}</code><br>
        Date: {str(s.get('closed_datetime', ''))[:16]}
        </div>
        """, unsafe_allow_html=True)

        st.markdown("#### 🔓 Unlock Year")
        st.warning(
            "Unlocking allows new uploads and edits. Only do this if you need to correct data. "
            "Re-close the year when done."
        )
        unlock_reason = st.text_input("Reason for unlock", placeholder="e.g. Amended tax data from Schwab")
        if st.button(f"🔓 Unlock Year {year_to_manage}", disabled=not unlock_reason):
            try:
                from src.database.connection import get_db
                with get_db() as conn:
                    conn.execute(
                        "UPDATE year_close_status SET is_locked = 0, status = 'Open', notes = ? WHERE year = ?",
                        (f"Unlocked by admin: {unlock_reason}", year_to_manage)
                    )
                try:
                    from src.database.persistence import backup_database
                    backup_database(reason=f"Unlocked year {year_to_manage}: {unlock_reason}")
                except Exception:
                    pass
                st.success(f"✅ Year {year_to_manage} is now OPEN.")
                st.rerun()
            except Exception as e:
                st.error(f"Failed to unlock: {e}")

    else:
        # ── OPEN STATE ────────────────────────────────────────────────────
        st.markdown(f"<span class='status-open'>🟢 Year {year_to_manage} is OPEN</span>", unsafe_allow_html=True)
        st.markdown("#### 🔒 Close & Archive Year")

        # Checklist
        st.markdown("**Pre-close Checklist:**")

        check1 = has_data
        check2 = year_to_manage < current_year
        check3 = not (year_to_manage == current_year and datetime.now().month < 12)

        st.write(f"{'✅' if check1 else '⬜'} Transaction data uploaded ({len(get_broker_transactions(year=year_to_manage)) if has_data else 0} records)")
        st.write(f"{'✅' if check2 else '⬜'} Year has ended (past December 31st)")
        st.write(f"{'✅' if check3 else '⬜'} Not the current active year")

        natural_ok = check1 and check2 and check3

        admin_override = st.checkbox(
            "⚠️ Admin Override — force close regardless of checklist",
            help="Use only when you are certain all data is finalized."
        )

        close_notes = st.text_area(
            "Notes (optional)",
            placeholder="e.g. All 2025 Schwab and TastyTrade data confirmed complete."
        )

        can_close = natural_ok or admin_override

        if st.button(f"🔒 Close & Archive Year {year_to_manage}", type="primary", disabled=not can_close):
            try:
                from src.database.connection import get_db
                with get_db() as conn:
                    conn.execute(
                        """INSERT OR REPLACE INTO year_close_status
                           (year, status, closed_datetime, closed_by, notes, is_locked)
                           VALUES (?, 'Closed', datetime('now'), 'admin', ?, 1)""",
                        (year_to_manage, close_notes or None)
                    )
                try:
                    from src.database.persistence import backup_database
                    backup_database(reason=f"Closed year {year_to_manage}")
                except Exception:
                    pass
                st.success(f"✅ Year {year_to_manage} is now CLOSED and LOCKED.")
                st.rerun()
            except Exception as e:
                st.error(f"Failed to close year: {e}")

        if not can_close:
            st.info("Complete the checklist above or enable Admin Override to proceed.")

# ─── Full audit trail ────────────────────────────────────────────────────────
st.divider()
st.markdown("### 📜 Full Year-Close Audit Trail")

if year_statuses:
    audit_df = pd.DataFrame([dict(y) for y in year_statuses])
    st.dataframe(audit_df, hide_index=True, use_container_width=True)
else:
    st.info("No years have been closed yet.")
