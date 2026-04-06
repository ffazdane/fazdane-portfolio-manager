"""
Page 3: Trade Detail
Detailed view of a single trade with legs, journal, and live metrics.
"""

import streamlit as st
import pandas as pd
from datetime import datetime
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.database.schema import init_database
from src.database.queries import get_trade_by_id, get_trade_legs, get_active_trades, get_all_trades
from src.utils.formatting import (
    format_currency, format_date, format_dte, format_delta, format_theta,
    status_badge, strategy_display_name, note_type_display
)
from src.utils.option_symbols import calculate_dte, build_display_symbol
from src.journal.journal_manager import (
    add_journal_entry, get_trade_journal, get_available_note_types
)

st.set_page_config(page_title="Trade Detail | Portfolio Manager", page_icon="🔍", layout="wide")
from src.utils.branding import setup_branding
setup_branding()
init_database()

st.markdown("""
<style>
    #MainMenu {visibility: hidden;} footer {visibility: hidden;}
    .leg-card {
        background: linear-gradient(135deg, #1A1F2E, #252B3B);
        border: 1px solid rgba(0, 212, 170, 0.1);
        border-radius: 8px; padding: 15px; margin: 5px 0;
    }
</style>
""", unsafe_allow_html=True)

st.markdown("## 🔍 Trade Detail")

# Trade selection
all_trades = get_all_trades()
if not all_trades:
    st.info("No trades found. Import data from the **Imports** page.")
    st.stop()

trade_options = {}
for t in all_trades:
    label = f"{status_badge(t['status'])} {t['underlying']} - {strategy_display_name(t['strategy_type'])} ({format_date(t['open_date'])})"
    trade_options[t['trade_id']] = label

# Use session state for pre-selected trade
default_trade_id = st.session_state.get('selected_trade_id', all_trades[0]['trade_id'])
if default_trade_id not in trade_options:
    default_trade_id = all_trades[0]['trade_id']

selected_id = st.selectbox(
    "Select Trade",
    options=list(trade_options.keys()),
    format_func=lambda x: trade_options[x],
    index=list(trade_options.keys()).index(default_trade_id) if default_trade_id in trade_options else 0
)

trade = get_trade_by_id(selected_id)
legs = get_trade_legs(selected_id)

if not trade:
    st.error("Trade not found.")
    st.stop()

with st.container():
    del_col1, del_col2 = st.columns([10, 2])
    with del_col2:
        if st.button("🗑️ Delete Trade", use_container_width=True):
            st.session_state['confirm_delete_id'] = selected_id

if st.session_state.get('confirm_delete_id') == selected_id:
    st.warning("⚠️ Are you sure? This will permanently delete the trade, its legs, and journal entries.")
    c_yes, c_no = st.columns([1, 1])
    with c_yes:
        if st.button("✔️ Yes, Delete Permanently", use_container_width=True):
            from src.database.queries import delete_trade
            delete_trade(selected_id)
            del st.session_state['confirm_delete_id']
            st.success("Trade deleted!")
            st.rerun()
    with c_no:
        if st.button("❌ Cancel", use_container_width=True):
            del st.session_state['confirm_delete_id']
            st.rerun()
    st.stop()


def _safe(row, key, default=None):
    try:
        val = row[key]
        return val if val is not None else default
    except (KeyError, IndexError):
        return default

# ============================================================
# TRADE SUMMARY HEADER
# ============================================================
st.divider()
h1, h2, h3, h4 = st.columns(4)

with h1:
    st.markdown(f"### {status_badge(trade['status'])} {trade['underlying']}")
    st.caption(f"Strategy: **{strategy_display_name(trade['strategy_type'])}**")

with h2:
    st.metric("Entry Credit/Debit", format_currency((trade['entry_credit_debit'] or 0) * 100))
    st.caption(f"Account: {trade['account']} | Broker: {trade['broker']}")

with h3:
    pnl_val = (_safe(trade, 'realized_pnl', 0) or 0) + (_safe(trade, 'unrealized_pnl', 0) or 0)
    color = "normal" if pnl_val >= 0 else "inverse"
    st.metric("Total P&L", format_currency(pnl_val), delta_color=color)
    st.caption(f"Realized: {format_currency(_safe(trade, 'realized_pnl'))} | Unrealized: {format_currency(_safe(trade, 'unrealized_pnl'))}")

with h4:
    st.metric("Days Held", _safe(trade, 'days_held', 0))
    close_date = _safe(trade, 'close_date')
    st.caption(f"Open: {format_date(trade['open_date'])} → {format_date(close_date) if close_date else 'Open'}")

# ============================================================
# TRADE LEGS
# ============================================================
st.divider()
st.markdown("### Option Legs")

if legs:
    leg_data = []
    for leg in legs:
        dte = calculate_dte(leg['expiry'])
        dte_str, _ = format_dte(dte)
        display_sym = build_display_symbol(
            leg['underlying'], leg['expiry'], leg['strike'], _safe(leg, 'option_type', '')
        ) if leg['strike'] else leg['symbol']

        option_type = _safe(leg, 'option_type')
        leg_data.append({
            'Symbol': display_sym,
            'Side': '🔴 SHORT' if leg['side'] == 'SHORT' else '🟢 LONG',
            'Strike': f"${leg['strike']:.0f}" if leg['strike'] else '—',
            'Type': 'Put' if option_type == 'P' else 'Call' if option_type == 'C' else '—',
            'Expiry': format_date(leg['expiry']),
            'DTE': dte_str,
            'Qty Open': int(leg['qty_open']),
            'Qty Closed': int(leg['qty_closed']),
            'Entry Price': format_currency(leg['entry_price']),
            'Exit Price': format_currency(_safe(leg, 'exit_price')),
            'Mark': format_currency(_safe(leg, 'current_mark')),
            'Status': leg['status'],
        })

    df = pd.DataFrame(leg_data)
    st.dataframe(df, use_container_width=True, hide_index=True)
    
    with st.expander("✏️ Manual Edit / Fix Trade & Legs"):
        st.caption("Fix improperly parsed strategies, missing Strikes, Types, or Expiries.")
        
        # 1. Strategy Edit
        st.write("#### Trade Strategy")
        from src.engine.strategy_grouper import STRATEGY_TYPES
        current_strategy = _safe(trade, 'strategy_type', 'unknown')
        strat_options = list(STRATEGY_TYPES.keys())
        if current_strategy not in strat_options:
            strat_options.append(current_strategy)
            
        scol1, scol2 = st.columns([3, 1], vertical_alignment="bottom")
        with scol1:
            n_strat = st.selectbox("Strategy Type", strat_options, index=strat_options.index(current_strategy))
        with scol2:
            st.write("") # spacer
            if st.button("Update Strategy", use_container_width=True):
                from src.database.queries import update_trade
                update_trade(selected_id, {'strategy_type': n_strat})
                st.success("Strategy updated!")
                st.rerun()

        st.divider()
        st.write("#### Option Legs")
        
        from src.database.queries import update_trade_leg
        import datetime
        for leg in legs:
            lid = leg['leg_id']
            cols = st.columns([2, 1, 1, 1, 2, 2])
            with cols[0]:
                st.write(f"**{leg['symbol']}**")
            with cols[1]:
                current_side = _safe(leg, 'side', 'LONG')
                s_idx = 0 if current_side == 'LONG' else 1
                n_sid = st.selectbox("Side", ["LONG", "SHORT"], index=s_idx, key=f"sid_{lid}", label_visibility="collapsed")
            with cols[2]:
                n_str = st.text_input("Strike", value=str(leg['strike'] if leg['strike'] else ''), key=f"str_{lid}", label_visibility="collapsed", placeholder="Strike")
            with cols[3]:
                current_type = _safe(leg, 'option_type', '')
                type_idx = 0 if current_type == 'P' else 1 if current_type == 'C' else 2
                n_typ = st.selectbox("Type", ["P", "C", ""], index=type_idx, key=f"typ_{lid}", label_visibility="collapsed")
            with cols[4]:
                exp_str = _safe(leg, 'expiry', '')
                try:
                    def_date = datetime.datetime.strptime(exp_str, '%Y-%m-%d').date() if exp_str else datetime.date.today()
                except ValueError:
                    def_date = datetime.date.today()
                    
                n_exp = st.date_input("Expiry", value=def_date, key=f"exp_{lid}", label_visibility="collapsed")
            with cols[5]:
                l_dict = dict(leg)
                leg_status = l_dict.get('status', 'OPEN')
                is_closed = leg_status != 'OPEN'
                
                b_cols = st.columns([2, 1, 1])
                with b_cols[0]:
                    if st.button("Save", key=f"save_{lid}", use_container_width=True):
                        try:
                            update_trade_leg(lid, {
                                'side': n_sid,
                                'strike': float(n_str) if n_str else None,
                                'option_type': n_typ if n_typ else None,
                                'expiry': n_exp.strftime('%Y-%m-%d') if isinstance(n_exp, datetime.date) else None
                            })
                            st.success("Leg updated!")
                            st.rerun()
                        except ValueError:
                            st.error("Invalid strike.")
                with b_cols[1]:
                    if is_closed:
                        if st.button("📦", key=f"arch_{lid}", use_container_width=True, help="Transfer leg to isolated History trade"):
                            from src.database.queries import insert_trade
                            import datetime
                            
                            exit_px = l_dict.get('exit_price', 0) or 0
                            entry_px = l_dict.get('entry_price', 0) or 0
                            qty_closed = l_dict.get('qty_closed', 1) or 1
                            is_short = l_dict.get('side') == 'SHORT'
                            
                            realized = ((entry_px - exit_px) * 100 * qty_closed) if is_short else ((exit_px - entry_px) * 100 * qty_closed)
                                    
                            t_dict = dict(trade)
                            new_trade = {
                                'account': t_dict.get('account', 'Default'),
                                'broker': t_dict.get('broker', 'Manual'),
                                'underlying': t_dict.get('underlying', l_dict.get('symbol')),
                                'strategy_type': 'SINGLE_LEG',
                                'open_date': t_dict.get('open_date', datetime.date.today().strftime('%Y-%m-%d')),
                                'close_date': datetime.date.today().strftime('%Y-%m-%d'),
                                'status': 'CLOSED_WIN' if realized >= 0 else 'CLOSED_LOSS',
                                'realized_pnl': realized,
                                'entry_credit_debit': (entry_px * qty_closed) if is_short else -(entry_px * qty_closed)
                            }
                            
                            try:
                                n_tid = insert_trade(new_trade)
                                update_trade_leg(lid, {'trade_id': n_tid, 'status': 'CLOSED'})
                                st.success("Leg transferred to History log!")
                                st.rerun()
                            except Exception as e:
                                st.error(f"Error archiving: {e}")
                    else:
                        if st.button("🔄", key=f"reac_{lid}", use_container_width=True, help="Re-activate leg to Active Portfolio"):
                            from src.database.queries import update_trade
                            try:
                                update_trade_leg(lid, {'status': 'OPEN'})
                                update_trade(trade['trade_id'], {'status': 'ACTIVE', 'close_date': None})
                                st.success("Leg reactivated! You can now link it back to other strategies.")
                                st.rerun()
                            except Exception as e:
                                st.error(f"Error reactivating: {e}")
                    
                with b_cols[2]:
                    if st.button("🗑️", key=f"del_{lid}", use_container_width=True, help="Permanently delete leg"):
                        from src.database.queries import delete_trade_leg
                        delete_trade_leg(lid)
                        st.success("Leg deleted!")
                        st.rerun()
else:
    st.info("No legs found for this trade.")

with st.expander("➕ Add / Link Option Legs"):
    st.caption("Add a new leg to this trade manually, or link an existing active leg from your portfolio (useful for rolling).")
    tab1, tab2 = st.tabs(["Create Manually", "Link Existing Active Leg"])
    
    with tab1:
        st.write("#### Create New Leg")
        import datetime
        c1, c2, c3, c4 = st.columns(4)
        n_symbol = c1.text_input("Underlying Symbol", value=_safe(trade, 'underlying', ''), key="new_u_sym")
        n_qty = c2.number_input("Qty", value=1, min_value=1, key="new_u_qty")
        n_side = c3.selectbox("Side", ["LONG", "SHORT"], key="new_u_side")
        n_type = c4.selectbox("Type", ["P", "C"], key="new_u_type")
        
        c5, c6, c7, c8 = st.columns(4)
        n_strike = c5.number_input("Strike", value=0.0, step=0.5, key="new_u_str")
        n_exp = c6.date_input("Expiry", value=datetime.date.today(), key="new_u_exp")
        n_price = c7.number_input("Entry Price", value=0.0, step=0.05, key="new_u_pr")
        n_status = c8.selectbox("Status", ["OPEN", "CLOSED", "EXPIRED"], key="new_u_stat")
        
        if st.button("Add New Leg to Trade", key="add_new_leg_btn", use_container_width=True):
            from src.database.queries import insert_trade_leg
            new_leg_data = {
                'trade_id': selected_id,
                'symbol': n_symbol.upper(),
                'underlying': n_symbol.upper(),
                'expiry': n_exp.strftime('%Y-%m-%d') if n_exp else None,
                'strike': float(n_strike) if n_strike else None,
                'option_type': n_type,
                'side': n_side,
                'qty_open': int(n_qty) if n_status == "OPEN" else 0,
                'qty_closed': int(n_qty) if n_status != "OPEN" else 0,
                'entry_price': float(n_price),
                'status': n_status,
            }
            insert_trade_leg(new_leg_data)
            st.success("Leg successfully added.")
            st.rerun()

    with tab2:
        st.write("#### Transfer from Portfolio")
        from src.database.queries import get_active_trades, get_trade_legs, update_trade_leg
        
        # Find open legs from other trades sharing the same underlying
        active_trades_matching = [t for t in get_active_trades() if t['underlying'] == _safe(trade, 'underlying', '') and t['trade_id'] != selected_id]
        
        linkable_legs = {}
        for t_match in active_trades_matching:
            m_legs = get_trade_legs(t_match['trade_id'])
            for ml in m_legs:
                if ml['status'] == "OPEN":
                    label = f"{ml['side']} {ml['strike']} {ml['option_type']} | Exp: {ml['expiry']} | Qty: {ml['qty_open']} | From Trade #{t_match['trade_id']}"
                    linkable_legs[ml['leg_id']] = label
        
        if not linkable_legs:
            st.info("No open legs found in other active trades with this underlying.")
        else:
            sel_leg = st.selectbox("Select Leg to Transfer", options=list(linkable_legs.keys()), format_func=lambda x: linkable_legs[x], key="sel_link_leg")
            if st.button("Transfer Leg to This Trade", key="transfer_leg_btn", use_container_width=True):
                update_trade_leg(sel_leg, {'trade_id': selected_id})
                st.success("Leg successfully transferred!")
                st.rerun()

# P&L Breakdown
m1, m2, m3, m4 = st.columns(4)
with m1:
    st.metric("Max Profit", format_currency(_safe(trade, 'max_profit')))
with m2:
    st.metric("Max Loss", format_currency(_safe(trade, 'max_loss')))
with m3:
    max_p = _safe(trade, 'max_profit')
    total_pnl = (_safe(trade, 'realized_pnl', 0) or 0) + (_safe(trade, 'unrealized_pnl', 0) or 0)
    pct = (total_pnl / max_p * 100) if max_p and max_p > 0 else None
    st.metric("% Max Profit", f"{pct:.1f}%" if pct is not None else "—")
with m4:
    if _safe(trade, 'parent_trade_id'):
        st.metric("Roll Source", f"Trade #{trade['parent_trade_id']}")
    elif _safe(trade, 'roll_group_id'):
        st.metric("Roll Group", trade['roll_group_id'])
    else:
        st.metric("Roll Status", "Not Rolled")

# ============================================================
# JOURNAL TIMELINE
# ============================================================
st.divider()
st.markdown("### 📝 Trade Journal")

journal_entries = get_trade_journal(selected_id)

# Add new entry form
with st.expander("➕ Add Journal Entry", expanded=False):
    note_types = get_available_note_types()
    j1, j2 = st.columns([1, 3])
    with j1:
        note_type = st.selectbox(
            "Note Type",
            options=[nt[0] for nt in note_types],
            format_func=lambda x: dict(note_types)[x],
            key="journal_note_type"
        )
    with j2:
        note_text = st.text_area("Note", placeholder="Write your journal entry here...", key="journal_note_text")

    if st.button("💾 Save Journal Entry", key="save_journal"):
        if note_text:
            add_journal_entry(selected_id, note_text, note_type)
            st.success("Journal entry saved!")
            st.rerun()
        else:
            st.warning("Please enter a note.")

# Display timeline
if journal_entries:
    for entry in journal_entries:
        label, color = note_type_display(entry['note_type'])
        st.markdown(f"""
        <div style="border-left: 3px solid {color}; padding: 10px 15px; margin: 8px 0;
                    background: rgba(255,255,255,0.02); border-radius: 0 8px 8px 0;">
            <div style="display: flex; justify-content: space-between; align-items: center;">
                <span style="color: {color}; font-weight: 600; font-size: 13px;">{label}</span>
                <span style="color: #666; font-size: 12px;">{entry['timestamp'][:16]}</span>
            </div>
            <div style="margin-top: 6px; color: #CCC; font-size: 14px;">{entry['note_text']}</div>
        </div>
        """, unsafe_allow_html=True)
else:
    st.caption("No journal entries yet. Add your first entry above!")
