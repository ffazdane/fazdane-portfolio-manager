"""
Tax Center
==========
Process-only 1099-B / composite tax PDF workflow.

Rules:
  • No files are saved permanently.
  • No data is written to the database.
  • Active Portfolio is never touched.
  • Everything lives in st.session_state for the duration of the session.
"""

import streamlit as st
import pandas as pd
import sys, os
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.utils.auth import check_password
if not check_password():
    st.stop()

from src.tax.normalizer import (
    detect_broker_from_filename, SECTION_1256_TICKERS, NORMALISE_MAP
)
from src.tax.pdf_extractor import extract_from_pdf
from src.tax.excel_generator import build_excel_report

# ── Page styling ──────────────────────────────────────────────────────────────
st.markdown("""
<style>
    #MainMenu {visibility: hidden;} footer {visibility: hidden;}
    .tax-banner {
        background: linear-gradient(135deg, #1A1F2E 0%, #0E1117 100%);
        border: 1px solid rgba(0,212,170,0.2);
        border-radius: 12px;
        padding: 18px 24px;
        margin-bottom: 20px;
    }
    .warn-box {
        background: rgba(255,75,75,0.08);
        border: 1px solid rgba(255,75,75,0.3);
        border-radius: 8px;
        padding: 10px 16px;
        margin: 8px 0;
        color: #FF4B4B;
        font-size: 13px;
    }
    .sec1256-badge {
        background: rgba(255,164,33,0.15);
        border: 1px solid rgba(255,164,33,0.4);
        border-radius: 20px;
        padding: 2px 10px;
        font-size: 12px;
        color: #FFA421;
        font-weight: 700;
    }
</style>
""", unsafe_allow_html=True)

st.markdown("""
<div class="tax-banner">
  <h2 style="margin:0;color:#00D4AA;">🧾 Tax Center</h2>
  <p style="margin:4px 0 0 0;color:#888;font-size:13px;">
    Ad-hoc 1099-B processing — upload, extract, classify, download Excel.
    <strong style="color:#FF4B4B;">No data is saved to the database.</strong>
  </p>
</div>
""", unsafe_allow_html=True)

# ── Session state initialisation ──────────────────────────────────────────────
if "tax_transactions" not in st.session_state:
    st.session_state.tax_transactions = []
if "tax_warnings"     not in st.session_state:
    st.session_state.tax_warnings = []
if "tax_files_meta"   not in st.session_state:
    st.session_state.tax_files_meta = []

# ── Tabs ─────────────────────────────────────────────────────────────────────
tab_upload, tab_preview, tab_config = st.tabs([
    "📤 Upload & Process", "📊 Preview Results", "⚙️ Classification Config"
])

# ══════════════════════════════════════════════════════════════════════════════
# TAB 1 — Upload & Process
# ══════════════════════════════════════════════════════════════════════════════
with tab_upload:
    st.markdown("### Upload 1099-B / Broker Tax PDFs")
    st.caption(
        "Supported: 1099-B, 1099 Composite, TastyTrade tax forms, Schwab tax statements. "
        "Multiple files accepted. Broker/account detected from filename."
    )

    col_info, col_rules = st.columns([3, 2])
    with col_info:
        st.info(
            "📌 **Filename naming rules for auto-detection:**\n"
            "- TastyTrade: filename must contain `5WT12803`\n"
            "- Schwab: filename must contain `_177` or `XXX177`"
        )
    with col_rules:
        st.markdown("""
        <div style="background:#1A1F2E;border-radius:8px;padding:12px;font-size:12px;color:#aaa;">
        <b style="color:#00D4AA;">Section 1256 candidates:</b><br>
        SPX · SPXW · NDX · NDXP · RUT · VIX · XSP · DJX<br>
        ES · NQ · RTY · MES · MNQ · M2K (futures)
        </div>
        """, unsafe_allow_html=True)

    uploaded_files = st.file_uploader(
        "Drop your 1099 PDF files here",
        type=["pdf"],
        accept_multiple_files=True,
        help="1099-B, 1099 Composite, or full brokerage tax statement PDFs"
    )

    if uploaded_files:
        st.markdown("#### Detected Files")
        file_meta_rows = []
        for f in uploaded_files:
            det = detect_broker_from_filename(f.name)
            file_meta_rows.append({
                "Filename":       f.name,
                "Broker":         det.get("broker") or "❓ Unknown",
                "Account":        det.get("account") or "❓ Unknown",
                "Detection":      det.get("method") or "undetected",
                "Size":           f"{ f.size / 1024:.1f} KB",
            })

        meta_df = pd.DataFrame(file_meta_rows)
        st.dataframe(meta_df, use_container_width=True, hide_index=True)

        unknown_brokers = [r for r in file_meta_rows if "Unknown" in r["Broker"]]
        if unknown_brokers:
            st.warning(
                f"⚠️ {len(unknown_brokers)} file(s) have undetected broker/account. "
                "Rename files to include the account number and re-upload, or they will be "
                "processed as 'Unknown'."
            )

        st.divider()
        c1, c2 = st.columns([2, 1])
        with c1:
            tax_year_override = st.text_input(
                "Tax Year (optional override — auto-detected from file if blank)",
                placeholder="e.g. 2025",
                max_chars=4,
            )
        with c2:
            st.write("")
            process_btn = st.button(
                "🔬 Process Tax Files",
                type="primary",
                use_container_width=True,
                disabled=not uploaded_files
            )

        if process_btn:
            all_txns:     list[dict] = []
            all_warnings: list[str]  = []

            prog = st.progress(0, text="Starting extraction…")
            total = len(uploaded_files)

            for i, f in enumerate(uploaded_files):
                prog.progress((i) / total, text=f"Extracting: {f.name}")
                det    = detect_broker_from_filename(f.name)
                broker = det.get("broker") or "Unknown"
                acct   = det.get("account") or "Unknown"

                pdf_bytes = f.read()
                txns, warns = extract_from_pdf(
                    pdf_bytes,
                    filename=f.name,
                    broker=broker,
                    account=acct,
                )

                # Apply tax year override
                if tax_year_override:
                    for t in txns:
                        t["tax_year"] = tax_year_override

                all_txns.extend(txns)
                all_warnings.extend(warns)

            prog.progress(1.0, text="✅ Extraction complete!")

            st.session_state.tax_transactions = all_txns
            st.session_state.tax_warnings     = all_warnings
            st.session_state.tax_files_meta   = file_meta_rows

            st.success(
                f"✅ Extracted **{len(all_txns):,} transactions** from "
                f"{total} file(s). "
                f"{len(all_warnings)} warning(s)."
            )
            if all_warnings:
                with st.expander(f"⚠️ {len(all_warnings)} Extraction Warning(s)", expanded=False):
                    for w in all_warnings:
                        st.markdown(f'<div class="warn-box">⚠ {w}</div>', unsafe_allow_html=True)

            if not all_txns:
                st.error(
                    "No transactions were extracted. This usually means:\n"
                    "1. The PDF is scanned/image-based (not text-extractable)\n"
                    "2. The table format is non-standard\n"
                    "3. Try a different PDF export from your broker's portal"
                )
            else:
                # Build & offer Excel immediately
                year_label = tax_year_override or (all_txns[0].get("tax_year") if all_txns else "Unknown")
                excel_bytes = build_excel_report(all_txns, all_warnings, tax_year=year_label)
                st.download_button(
                    label="⬇️ Download Excel Report",
                    data=excel_bytes,
                    file_name=f"TaxCenter_{year_label}_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    type="primary",
                    use_container_width=True,
                )

    # ── Clear session ─────────────────────────────────────────────────────────
    if st.session_state.tax_transactions:
        st.divider()
        if st.button("🗑️ Clear Session Data", help="Remove all extracted data from this session"):
            st.session_state.tax_transactions = []
            st.session_state.tax_warnings     = []
            st.session_state.tax_files_meta   = []
            st.rerun()

# ══════════════════════════════════════════════════════════════════════════════
# TAB 2 — Preview Results
# ══════════════════════════════════════════════════════════════════════════════
with tab_preview:
    txns = st.session_state.tax_transactions

    if not txns:
        st.info("Upload and process PDF files in the **Upload & Process** tab to see results here.")
        st.stop()

    df = pd.DataFrame(txns)

    # ── Top-level KPIs ────────────────────────────────────────────────────────
    st.markdown("### 📊 Extraction Summary")
    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric("Transactions",    f"{len(txns):,}")
    k2.metric("Total Proceeds",  f"${sum(t.get('proceeds',0)  for t in txns):,.2f}")
    k3.metric("Total Cost Basis",f"${sum(t.get('cost_basis',0) for t in txns):,.2f}")
    total_gl = sum(t.get('gain_loss',0) for t in txns)
    gl_color = "normal" if total_gl >= 0 else "inverse"
    k4.metric("Total Realized P/L", f"${total_gl:+,.2f}", delta_color=gl_color)
    s1256_total = sum(t.get('gain_loss',0) for t in txns if t.get('section_1256'))
    k5.metric("Section 1256 P/L", f"${s1256_total:+,.2f}")

    st.divider()

    # ── Ticker Summary table ──────────────────────────────────────────────────
    st.markdown("### 🏷️ Ticker Summary")

    from src.tax.excel_generator import _aggregate_by_ticker
    ticker_rows = _aggregate_by_ticker(txns)
    if ticker_rows:
        tdf = pd.DataFrame(ticker_rows)

        def _color_gl(val):
            if isinstance(val, (int, float)):
                return "color: #00D4AA" if val >= 0 else "color: #FF4B4B"
            return ""

        money_cols = [c for c in tdf.columns if any(k in c for k in
                      ["Proceeds","Cost","P/L","Price","60%","40%","Sec"])]
        styled = tdf.style.map(_color_gl, subset=money_cols)
        st.dataframe(styled, use_container_width=True, hide_index=True)
    else:
        st.info("No ticker data to display.")

    # ── Section 1256 detail ───────────────────────────────────────────────────
    sec_txns = [t for t in txns if t.get("section_1256")]
    if sec_txns:
        st.divider()
        st.markdown(
            "### <span class='sec1256-badge'>§ 1256</span> Section 1256 Breakdown",
            unsafe_allow_html=True
        )
        st.caption(
            "⚠️ Preliminary classification only. Verify against Form 6781 and your tax advisor."
        )
        from src.tax.excel_generator import _sec1256_summary
        s_rows = _sec1256_summary(txns)
        if s_rows:
            st.dataframe(pd.DataFrame(s_rows), use_container_width=True, hide_index=True)

    # ── Warnings ──────────────────────────────────────────────────────────────
    warnings = st.session_state.tax_warnings
    if warnings:
        st.divider()
        with st.expander(f"⚠️ {len(warnings)} Extraction Warning(s)", expanded=False):
            for w in warnings:
                st.markdown(f'<div class="warn-box">⚠ {w}</div>', unsafe_allow_html=True)

    # ── Download button ───────────────────────────────────────────────────────
    st.divider()
    year_label = txns[0].get("tax_year", "Unknown") if txns else "Unknown"
    excel_bytes = build_excel_report(txns, warnings, tax_year=year_label)
    st.download_button(
        label="⬇️ Download Full Excel Report",
        data=excel_bytes,
        file_name=f"TaxCenter_{year_label}_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        type="primary",
        use_container_width=False,
    )

    # ── Raw transactions toggle ───────────────────────────────────────────────
    with st.expander("🔬 Raw Extracted Transactions (all fields)", expanded=False):
        st.dataframe(df, use_container_width=True, hide_index=True)

# ══════════════════════════════════════════════════════════════════════════════
# TAB 3 — Classification Config
# ══════════════════════════════════════════════════════════════════════════════
with tab_config:
    st.markdown("### Section 1256 Candidate Tickers")
    st.caption(
        "These tickers are automatically flagged for 60/40 treatment. "
        "Final tax treatment must be confirmed with your tax advisor and broker Form 6781."
    )

    col_sec, col_norm = st.columns(2)
    with col_sec:
        st.markdown("**Section 1256 Candidates (built-in)**")
        tickers_sorted = sorted(SECTION_1256_TICKERS)
        pills = " ".join(
            f'<span style="background:rgba(255,164,33,0.15);border:1px solid rgba(255,164,33,0.4);'
            f'border-radius:14px;padding:2px 10px;margin:2px;font-size:12px;color:#FFA421;">{t}</span>'
            for t in tickers_sorted
        )
        st.markdown(pills, unsafe_allow_html=True)

    with col_norm:
        st.markdown("**Symbol Normalisation Map**")
        norm_rows = [{"Original": k, "Normalised To": v} for k, v in sorted(NORMALISE_MAP.items())]
        st.dataframe(pd.DataFrame(norm_rows), use_container_width=True, hide_index=True)

    st.divider()
    st.markdown("### Broker Account Rules")
    rules_data = [
        {"Pattern in Filename": "5WT12803",  "Broker": "TastyTrade", "Account": "5WT12803"},
        {"Pattern in Filename": "_177",       "Broker": "Schwab",     "Account": "XXX177"},
        {"Pattern in Filename": "XXX177",     "Broker": "Schwab",     "Account": "XXX177"},
    ]
    st.dataframe(pd.DataFrame(rules_data), use_container_width=True, hide_index=True)
    st.caption(
        "These rules are also backed by the Account Master table. "
        "Add new accounts via **Broker Data Upload → Account Mappings** tab."
    )

    st.divider()
    st.markdown("### 60/40 Split Preview")
    test_gl = st.number_input("Test Gain/Loss amount ($)", value=-5000.0, step=100.0)
    from src.tax.normalizer import split_6040
    lt60, st40 = split_6040(test_gl)
    c1, c2 = st.columns(2)
    c1.metric("60% Long-Term", f"${lt60:,.2f}")
    c2.metric("40% Short-Term", f"${st40:,.2f}")
