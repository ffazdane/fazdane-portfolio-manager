"""
Shared session management for all Streamlit pages.
Auto-connects to tastytrade if credentials are available.
"""

import streamlit as st
from src.market.tastytrade_client import get_tastytrade_session, get_accounts


def ensure_session():
    """
    Ensure a tastytrade session is available in st.session_state.
    Auto-connects using .env credentials if not already connected.
    Returns (session, accounts) or (None, None).
    """
    # Already connected
    if st.session_state.get('tastytrade_session'):
        return st.session_state.tastytrade_session, st.session_state.get('accounts', [])

    # Try auto-connect
    session, error = get_tastytrade_session()
    if session:
        st.session_state.tastytrade_session = session
        accounts, _ = get_accounts(session)
        st.session_state.accounts = accounts or []
        return session, st.session_state.accounts

    return None, None
