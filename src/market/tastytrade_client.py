"""
tastytrade API Client
Uses the tastytrade Python SDK (v12+) for session management, positions, quotes, and Greeks.

Authentication: OAuth2 via client_secret + refresh_token
Generated at: tastytrade.com → My Profile → API → OAuth Applications → Manage → Create Grant

All SDK methods are async — we use threaded async runners for Streamlit compatibility.
"""

import os
import asyncio
import threading
from dotenv import load_dotenv

load_dotenv()

# Session cache
_session_cache = {}


def _run_async(coro):
    """Run an async coroutine synchronously via a dedicated thread."""
    result = [None]
    error = [None]

    def _thread_target():
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            result[0] = loop.run_until_complete(coro)
            loop.close()
        except Exception as e:
            error[0] = e

    thread = threading.Thread(target=_thread_target)
    thread.start()
    thread.join(timeout=30)

    if error[0]:
        raise error[0]
    return result[0]


# ============================================================
# SESSION MANAGEMENT
# ============================================================

def get_tastytrade_session(client_secret=None, refresh_token=None,
                           username=None, password=None, environment=None):
    """
    Create or retrieve a cached tastytrade session.
    
    Primary: OAuth2 via SDK Session(client_secret, refresh_token)
    Fallback: Username/Password via REST API (no 2FA only)
    """
    environment = environment or os.getenv('TASTYTRADE_ENVIRONMENT', 'production')
    is_test = environment.lower() == 'sandbox'

    client_id = os.getenv('TT_CLIENT_ID', '').strip()        # The UUID from OAuth App page
    client_secret = client_secret or os.getenv('TT_SECRET', '').strip()  # The secret key
    refresh_token = refresh_token or os.getenv('TT_REFRESH', '').strip()
    username = username or os.getenv('TASTYTRADE_USERNAME', '').strip()
    password = password or os.getenv('TASTYTRADE_PASSWORD', '').strip()

    # If no separate client_id, fall back to using client_secret as client_id (legacy)
    if not client_id:
        client_id = client_secret

    cache_key = f"{client_secret or username}_{environment}"
    if cache_key in _session_cache:
        return _session_cache[cache_key], None

    # ── Method 1: OAuth2 — synchronous token exchange via REST ──
    if client_secret and refresh_token:
        try:
            import httpx
            base_url = "https://api.cert.tastyworks.com" if is_test else "https://api.tastyworks.com"

            # Exchange refresh token for a session token immediately
            resp = httpx.post(
                f"{base_url}/oauth/token",
                json={
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                    "client_id": client_id,
                    "client_secret": client_secret,
                },
                headers={"Content-Type": "application/json"},
                timeout=15.0,
            )

            body = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}

            if resp.status_code not in (200, 201) or "error_code" in body:
                err_desc = body.get("error_description", body.get("error", resp.text[:200]))
                return None, (
                    f"❌ **OAuth2 failed:** {err_desc}\n\n"
                    "**To fix:**\n"
                    "1. Go to [my.tastytrade.com](https://my.tastytrade.com) → **My Profile → API**\n"
                    "2. Click **Manage** on your OAuth app\n"
                    "3. Click **Create Grant** to generate a fresh Refresh Token\n"
                    "4. Update `TT_SECRET` and `TT_REFRESH` in Settings (or Streamlit Secrets)"
                )

            session_token = body.get("access_token") or body.get("session-token")
            if not session_token:
                return None, f"OAuth2 succeeded but no token found in response: {body}"

            session = _DirectSession(session_token, base_url, is_test)
            _session_cache[cache_key] = session
            return session, None

        except Exception as e:
            return None, f"OAuth2 login failed: {str(e)}"


    # ── Method 2: Username/Password (no 2FA) ──
    if username and password:
        try:
            import httpx
            base_url = "https://api.cert.tastyworks.com" if is_test else "https://api.tastyworks.com"

            response = httpx.post(
                f"{base_url}/sessions",
                json={"login": username, "password": password, "remember-me": True},
                headers={"Content-Type": "application/json", "User-Agent": "PortfolioManager/1.0"},
                timeout=15.0,
            )

            if response.status_code == 403:
                return None, (
                    "🔐 **2FA is enabled** — username/password login blocked.\n\n"
                    "Switch to **OAuth2** method and use Client Secret + Refresh Token."
                )

            if response.status_code not in (200, 201):
                body = response.json() if 'json' in response.headers.get('content-type', '') else {}
                msg = body.get('error', {}).get('message', response.text[:200])
                return None, f"Login failed ({response.status_code}): {msg}"

            data = response.json().get('data', {})
            session_token = data.get('session-token')
            if not session_token:
                return None, "No session token received"

            session = _DirectSession(session_token, base_url, is_test)
            _session_cache[cache_key] = session
            return session, None
        except Exception as e:
            return None, f"Login failed: {str(e)}"

    # ── No credentials ──
    return None, (
        "No credentials configured.\n\n"
        "**Setup (one-time):**\n"
        "1. Go to [my.tastytrade.com](https://my.tastytrade.com) → **My Profile → API**\n"
        "2. Click **OAuth Applications** tab\n"
        "3. Create an app (or use existing) → copy **Client Secret**\n"
        "4. Click **Manage** → **Create Grant** → copy **Refresh Token**\n"
        "5. Enter both in the Settings page or `.env` file"
    )


class _DirectSession:
    """Lightweight REST API session for username/password auth."""

    def __init__(self, session_token, base_url, is_test=False):
        self.session_token = session_token
        self.base_url = base_url
        self.is_test = is_test
        self._headers = {
            "Authorization": session_token,
            "Content-Type": "application/json",
            "User-Agent": "PortfolioManager/1.0",
        }

    def _get(self, endpoint, params=None):
        import httpx
        response = httpx.get(
            f"{self.base_url}{endpoint}",
            headers=self._headers,
            params=params,
            timeout=15.0,
        )
        if response.status_code != 200:
            raise Exception(f"API error ({response.status_code}): {response.text[:200]}")
        return response.json()


def clear_session_cache():
    """Clear the cached session."""
    global _session_cache
    _session_cache = {}


# ============================================================
# ACCOUNT DATA
# ============================================================

def get_accounts(session):
    """Get all accounts."""
    try:
        if isinstance(session, _DirectSession):
            data = session._get("/customers/me/accounts")
            items = data.get('data', {}).get('items', [])
            return [
                {
                    'account_number': item.get('account', {}).get('account-number', ''),
                    'nickname': item.get('account', {}).get('nickname', '')
                                or item.get('account', {}).get('account-number', ''),
                }
                for item in items
            ], None
        else:
            from tastytrade import Account
            accounts = _run_async(Account.get(session))
            if not isinstance(accounts, list):
                accounts = [accounts]
            return [
                {
                    'account_number': str(a.account_number),
                    'nickname': getattr(a, 'nickname', '') or str(a.account_number),
                }
                for a in accounts
            ], None
    except Exception as e:
        return [], f"Failed to get accounts: {str(e)}"


def get_positions(session, account_number):
    """Get current positions."""
    try:
        if isinstance(session, _DirectSession):
            data = session._get(f"/accounts/{account_number}/positions")
            items = data.get('data', {}).get('items', [])
            result = []
            for pos in items:
                result.append({
                    'account_number': pos.get('account-number', account_number),
                    'symbol': pos.get('symbol', ''),
                    'instrument_type': pos.get('instrument-type', ''),
                    'underlying_symbol': pos.get('underlying-symbol', ''),
                    'quantity': float(pos.get('quantity', 0) or 0),
                    'quantity_direction': pos.get('quantity-direction', ''),
                    'close_price': float(pos.get('close-price', 0) or 0),
                    'average_open_price': float(pos.get('average-open-price', 0) or 0),
                    'multiplier': int(pos.get('multiplier', 100) or 100),
                    'mark': float(pos.get('mark', 0) or 0),
                    'mark_price': float(pos.get('mark-price', 0) or 0),
                })
            return result, None
        else:
            from tastytrade import Account
            account = _run_async(Account.get(session, account_number))
            positions = _run_async(account.get_positions(session))
            result = []
            for pos in positions:
                result.append({
                    'account_number': str(pos.account_number),
                    'symbol': str(pos.symbol),
                    'instrument_type': str(pos.instrument_type.value) if hasattr(pos.instrument_type, 'value') else str(pos.instrument_type),
                    'underlying_symbol': str(pos.underlying_symbol),
                    'quantity': float(pos.quantity),
                    'quantity_direction': str(pos.quantity_direction),
                    'close_price': float(pos.close_price) if pos.close_price else None,
                    'average_open_price': float(pos.average_open_price) if pos.average_open_price else None,
                    'multiplier': int(pos.multiplier) if pos.multiplier else 100,
                    'mark': float(pos.mark) if hasattr(pos, 'mark') and pos.mark else None,
                    'mark_price': float(pos.mark_price) if hasattr(pos, 'mark_price') and pos.mark_price else None,
                })
            return result, None
    except Exception as e:
        return [], f"Failed to get positions: {str(e)}"


def get_balances(session, account_number):
    """Get account balances."""
    try:
        if isinstance(session, _DirectSession):
            data = session._get(f"/accounts/{account_number}/balances")
            bal = data.get('data', {})
            return {
                'net_liquidating_value': float(bal.get('net-liquidating-value', 0) or 0),
                'cash_balance': float(bal.get('cash-balance', 0) or 0),
                'buying_power': float(bal.get('derivative-buying-power', 0) or 0),
                'maintenance_requirement': float(bal.get('maintenance-requirement', 0) or 0),
            }, None
        else:
            from tastytrade import Account
            account = _run_async(Account.get(session, account_number))
            balances = _run_async(account.get_balances(session))
            return {
                'net_liquidating_value': float(getattr(balances, 'net_liquidating_value', 0) or 0),
                'cash_balance': float(getattr(balances, 'cash_balance', 0) or 0),
                'buying_power': float(getattr(balances, 'derivative_buying_power', 0) or 0),
                'maintenance_requirement': float(getattr(balances, 'maintenance_requirement', 0) or 0),
            }, None
    except Exception as e:
        return {}, f"Failed to get balances: {str(e)}"


def get_transactions(session, account_number, start_date=None, end_date=None):
    """Get account transactions."""
    try:
        if isinstance(session, _DirectSession):
            params = {}
            if start_date:
                params['start-date'] = str(start_date)
            if end_date:
                params['end-date'] = str(end_date)
            data = session._get(f"/accounts/{account_number}/transactions", params=params)
            items = data.get('data', {}).get('items', [])
            result = []
            for txn in items:
                result.append({
                    'id': str(txn.get('id', '')),
                    'account_number': account_number,
                    'transaction_type': txn.get('transaction-type', ''),
                    'transaction_sub_type': txn.get('transaction-sub-type', ''),
                    'description': txn.get('description', ''),
                    'executed_at': txn.get('executed-at', ''),
                    'symbol': txn.get('symbol', ''),
                    'underlying_symbol': txn.get('underlying-symbol', ''),
                    'action': txn.get('action', ''),
                    'quantity': float(txn.get('quantity', 0) or 0),
                    'price': float(txn.get('price', 0) or 0),
                    'value': float(txn.get('value', 0) or 0),
                    'commission': float(txn.get('commission', 0) or 0),
                    'clearing_fees': float(txn.get('clearing-fees', 0) or 0),
                    'regulatory_fees': float(txn.get('regulatory-fees', 0) or 0),
                    'instrument_type': txn.get('instrument-type', ''),
                })
            return result, None
        else:
            from tastytrade import Account
            account = _run_async(Account.get(session, account_number))
            kwargs = {}
            if start_date:
                kwargs['start_date'] = start_date
            if end_date:
                kwargs['end_date'] = end_date
            transactions = _run_async(account.get_history(session, **kwargs))
            result = []
            for txn in transactions:
                result.append({
                    'id': str(getattr(txn, 'id', '')),
                    'account_number': account_number,
                    'transaction_type': str(getattr(txn, 'transaction_type', '')),
                    'transaction_sub_type': str(getattr(txn, 'transaction_sub_type', '')),
                    'description': str(getattr(txn, 'description', '')),
                    'executed_at': str(getattr(txn, 'executed_at', '')),
                    'symbol': str(getattr(txn, 'symbol', '')),
                    'underlying_symbol': str(getattr(txn, 'underlying_symbol', '')),
                    'action': str(getattr(txn, 'action', '')),
                    'quantity': float(getattr(txn, 'quantity', 0) or 0),
                    'price': float(getattr(txn, 'price', 0) or 0),
                    'value': float(getattr(txn, 'value', 0) or 0),
                    'commission': float(getattr(txn, 'commission', 0) or 0),
                    'clearing_fees': float(getattr(txn, 'clearing_fees', 0) or 0),
                    'regulatory_fees': float(getattr(txn, 'regulatory_fees', 0) or 0),
                    'instrument_type': str(getattr(txn, 'instrument_type', '')),
                })
            return result, None
    except Exception as e:
        return [], f"Failed to get transactions: {str(e)}"


def get_quote_for_symbol(session, symbol):
    """Get a market quote for a symbol."""
    try:
        from tastytrade import DXLinkStreamer
        from tastytrade.dxfeed import Quote

        async def _fetch():
            async with DXLinkStreamer(session) as streamer:
                await streamer.subscribe(Quote, [symbol])
                quote = await asyncio.wait_for(streamer.get_event(Quote), timeout=5.0)
                return quote

        quote = _run_async(_fetch())
        return {
            'symbol': symbol,
            'bid': float(quote.bid_price) if quote.bid_price else None,
            'ask': float(quote.ask_price) if quote.ask_price else None,
            'last': None,
            'option_mark': (float(quote.bid_price or 0) + float(quote.ask_price or 0)) / 2
            if quote.bid_price and quote.ask_price else None,
        }, None
    except Exception as e:
        return {}, f"Failed to get quote: {str(e)}"


def get_market_quotes_batch(session, symbols):
    """Get market quotes for multiple symbols rapidly via one websocket connection."""
    if not symbols:
        return {}, None
        
    try:
        from tastytrade import DXLinkStreamer
        from tastytrade.dxfeed import Quote

        async def _fetch():
            results = {}
            async with DXLinkStreamer(session) as streamer:
                await streamer.subscribe(Quote, symbols)
                # Wait for up to ~4 seconds for all quotes to stream in
                for _ in range(len(symbols) * 2):
                    try:
                        quote = await asyncio.wait_for(streamer.get_event(Quote), timeout=2.0)
                        sym = quote.event_symbol
                        if sym not in results:
                            results[sym] = {
                                'bid': float(quote.bid_price) if quote.bid_price else None,
                                'ask': float(quote.ask_price) if quote.ask_price else None,
                                'option_mark': (float(quote.bid_price or 0) + float(quote.ask_price or 0)) / 2
                                if quote.bid_price and quote.ask_price else None,
                            }
                        if len(results) >= len(symbols):
                            break
                    except asyncio.TimeoutError:
                        break
            return results

        return _run_async(_fetch()), None
    except Exception as e:
        return {}, f"Failed to get batch quotes: {str(e)}"


def get_greeks_for_symbols(session, symbols):
    """Get Greeks for a list of option symbols."""
    try:
        from tastytrade import DXLinkStreamer
        from tastytrade.dxfeed import Greeks

        async def _fetch():
            results = {}
            async with DXLinkStreamer(session) as streamer:
                await streamer.subscribe(Greeks, symbols)
                for _ in range(len(symbols)):
                    try:
                        greeks = await asyncio.wait_for(streamer.get_event(Greeks), timeout=5.0)
                        results[greeks.event_symbol] = {
                            'delta': float(greeks.delta) if greeks.delta else None,
                            'gamma': float(greeks.gamma) if greeks.gamma else None,
                            'theta': float(greeks.theta) if greeks.theta else None,
                            'vega': float(greeks.vega) if greeks.vega else None,
                            'iv': float(greeks.volatility) if greeks.volatility else None,
                            'price': float(greeks.price) if greeks.price else None,
                        }
                    except asyncio.TimeoutError:
                        break
            return results

        return _run_async(_fetch()), None
    except Exception as e:
        return {}, f"Failed to get greeks: {str(e)}"


def get_option_chain(session, underlying):
    """Get the option chain for an underlying."""
    try:
        from tastytrade.instruments import get_option_chain as _get_chain
        chain = _run_async(_get_chain(session, underlying))
        result = {}
        for exp, strikes in chain.items():
            exp_str = str(exp)
            result[exp_str] = []
            for strike_data in strikes:
                result[exp_str].append({
                    'symbol': str(strike_data.symbol),
                    'streamer_symbol': str(strike_data.streamer_symbol),
                    'strike_price': float(strike_data.strike_price),
                    'option_type': str(strike_data.option_type),
                    'expiration_date': str(strike_data.expiration_date),
                })
        return result, None
    except Exception as e:
        return {}, f"Failed to get option chain: {str(e)}"


def test_connection(client_secret=None, refresh_token=None,
                    username=None, password=None, environment=None):
    """Test the tastytrade API connection."""
    clear_session_cache()

    session, error = get_tastytrade_session(
        client_secret=client_secret,
        refresh_token=refresh_token,
        username=username,
        password=password,
        environment=environment,
    )
    if error:
        return False, error

    accounts, error = get_accounts(session)
    if error:
        return False, error
    if not accounts:
        return False, "Connected but no accounts found."

    account_list = ", ".join(a['account_number'] for a in accounts)
    return True, f"Connected successfully! Accounts: {account_list}"
