"""
Page 8: Manual Entry
Allows users to manually create an option trade and bypass the CSV/Broker import process.
"""

import streamlit as st
from datetime import datetime
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.utils.auth import check_password
if not check_password():
    st.stop()

from app import init_app
from src.database.queries import insert_trade, insert_trade_leg
from src.engine.strategy_grouper import STRATEGY_TYPES

st.set_page_config(page_title="Manual Entry", page_icon="✍️", layout="wide")
from src.utils.branding import setup_branding
setup_branding()
init_app()

st.markdown("## ✍️ Manually Add Trade")
st.caption("Use this form to manually enter a new trade and its associated legs directly into the Portfolio Manager.")

with st.form("manual_trade_form"):
    st.markdown("### 1. Trade Summary")
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        account = st.text_input("Account Number", value="DEFAULT_ACC")
    with c2:
        broker = st.text_input("Broker", value="MANUAL")
    with c3:
        underlying = st.text_input("Underlying Ticker (e.g. AAPL)").upper()
    with c4:
        strategy_type = st.selectbox("Strategy Type", options=list(STRATEGY_TYPES.keys()), format_func=lambda x: STRATEGY_TYPES[x])

    c5, c6, c7, c8 = st.columns(4)
    with c5:
        open_date = st.date_input("Open Date", value=datetime.today())
    with c6:
        status = st.selectbox("Status", ["ACTIVE", "CLOSED_WIN", "CLOSED_LOSS", "EXPIRED_WORTHLESS"])
    with c7:
        entry_net = st.number_input("Entry Credit/Debit ($)", value=0.0, step=10.0, help="Positive = Credit (Received), Negative = Debit (Paid)")
    with c8:
        realized_pnl = st.number_input("Realized P&L ($)", value=0.0, step=10.0)

    st.divider()
    st.markdown("### 2. Option Legs (Fill up to 4)")
    st.caption("Only fill out the rows needed for your strategy. Leave 'Strike' blank to skip the leg.")
    
    legs_data = []
    
    for i in range(1, 5):
        st.markdown(f"**Leg {i}**")
        lc1, lc2, lc3, lc4, lc5, lc6_7 = st.columns([2, 2, 2, 2, 2, 3])
        with lc1:
            l_side = st.selectbox("Side", ["LONG", "SHORT"], key=f"side_{i}")
        with lc2:
            l_type = st.selectbox("Type", ["C", "P"], key=f"type_{i}")
        with lc3:
            l_qty = st.number_input("Qty", min_value=1, value=1, step=1, key=f"qty_{i}")
        with lc4:
            l_strike = st.text_input("Strike", value="", key=f"strike_{i}")
        with lc5:
            l_exp = st.date_input(f"Expiry", value=None, key=f"exp_{i}")
        with lc6_7:
            # Need a split for entry/exit prices
            ic1, ic2 = st.columns(2)
            with ic1:
                l_entry = st.number_input("Entry Px", value=0.0, format="%.2f", step=0.1, key=f"ent_px_{i}")
            with ic2:
                l_exit = st.number_input("Exit Px", value=0.0, format="%.2f", step=0.1, key=f"ex_px_{i}")

        legs_data.append({
            'side': l_side,
            'type': l_type,
            'qty': l_qty,
            'strike': l_strike,
            'expiry': l_exp,
            'entry_price': l_entry,
            'exit_price': l_exit,
        })
        st.markdown("<br>", unsafe_allow_html=True)
        
    submit = st.form_submit_button("🔨 Create Trade", use_container_width=True)
    
if submit:
    # Validation
    if not underlying:
        st.error("Underlying Ticker is required!")
        st.stop()
        
    # Check valid legs
    valid_legs = []
    for l in legs_data:
        str_val = l['strike'].strip()
        if str_val:
            try:
                strike_num = float(str_val)
                valid_legs.append({
                    **l,
                    'strike': strike_num,
                    'expiry': l['expiry'].strftime('%Y-%m-%d') if l['expiry'] else None
                })
            except ValueError:
                st.error(f"Invalid Strike price: '{str_val}'. Must be a number.")
                st.stop()
                
    if not valid_legs:
        st.warning("You must provide at least one valid leg with a strike price!")
        st.stop()
        
    # Generate Trade Data
    trade_data = {
        'account': account,
        'broker': broker,
        'underlying': underlying,
        'strategy_type': strategy_type,
        'open_date': open_date.strftime('%Y-%m-%d'),
        'close_date': datetime.today().strftime('%Y-%m-%d') if status != 'ACTIVE' else None,
        'status': status,
        'entry_credit_debit': entry_net,
        'realized_pnl': realized_pnl,
        'unrealized_pnl': 0,
        'result_tag': 'WIN' if realized_pnl > 0 else 'LOSS' if realized_pnl < 0 else None
    }
    
    trade_id = insert_trade(trade_data)
    
    # Generate Leg Data
    for l in valid_legs:
        # Formulate a pseudo OCC-like symbol
        dt_str = "XX"
        if l['expiry']:
            # attempt occ date
            try:
                dt_str = datetime.strptime(l['expiry'], '%Y-%m-%d').strftime('%y%m%d')
            except:
                pass
        
        pseudo_symbol = f"{underlying}{dt_str}{l['type']}{int(l['strike']*1000):08d}"
        
        leg_data = {
            'trade_id': trade_id,
            'symbol': pseudo_symbol,
            'underlying': underlying,
            'expiry': l['expiry'],
            'strike': l['strike'],
            'option_type': l['type'],
            'side': l['side'],
            'qty_open': l['qty'] if status == 'ACTIVE' else 0,
            'qty_closed': l['qty'] if status != 'ACTIVE' else 0,
            'entry_price': l['entry_price'],
            'exit_price': l['exit_price'] if status != 'ACTIVE' else None,
            'status': 'OPEN' if status == 'ACTIVE' else 'CLOSED'
        }
        insert_trade_leg(leg_data)
        
    st.success(f"**Success!** Hand-crafted trade for **{underlying}** has been added. View it in the Active Portfolio or Dashboard.")
    
    from src.database.persistence import backup_database
    backup_database(reason=f"manual entry {underlying}")
    
    st.balloons()
