"""
Option Symbol Parsing Utilities
Handles OCC standard, tastytrade, and Schwab symbol formats.
"""

import re
from datetime import datetime, date


def parse_occ_symbol(symbol):
    """
    Parse OCC standard option symbol.
    Format: AAPL  251017C00150000
    Returns dict with underlying, expiry, put_call, strike or None if not an option.
    """
    symbol = symbol.strip()
    # OCC format: up to 6 char underlying + 6 digit date + P/C + 8 digit strike
    match = re.match(r'^([A-Z]{1,6})\s*(\d{6})([PC])(\d{8})$', symbol)
    if not match:
        return None

    underlying = match.group(1).strip()
    date_str = match.group(2)
    put_call = match.group(3)
    strike_raw = match.group(4)

    try:
        expiry = datetime.strptime(date_str, '%y%m%d').strftime('%Y-%m-%d')
    except ValueError:
        return None

    strike = int(strike_raw) / 1000.0

    return {
        'underlying': underlying,
        'expiry': expiry,
        'put_call': put_call,
        'strike': strike,
        'symbol': symbol.strip(),
    }


def parse_tastytrade_description(description):
    """
    Parse tastytrade-style option description.
    Examples:
        'AAPL 10/17/25 C150'
        'SPY 12/20/24 P430'
        'AAPL 01/17/2025 150.00 C'
    Returns dict or None.
    """
    if not description:
        return None

    description = description.strip()

    # Pattern 1: SYMBOL MM/DD/YY(YY) STRIKE P/C
    match = re.match(
        r'^([A-Z]{1,6})\s+(\d{1,2}/\d{1,2}/\d{2,4})\s+(\d+\.?\d*)\s+([PC])$',
        description
    )
    if match:
        return _build_from_match(match.group(1), match.group(2), match.group(4), match.group(3))

    # Pattern 2: SYMBOL MM/DD/YY(YY) P/C STRIKE
    match = re.match(
        r'^([A-Z]{1,6})\s+(\d{1,2}/\d{1,2}/\d{2,4})\s+([PC])(\d+\.?\d*)$',
        description
    )
    if match:
        return _build_from_match(match.group(1), match.group(2), match.group(3), match.group(4))

    # Pattern 3: More flexible - with spaces around P/C
    match = re.match(
        r'^([A-Z]{1,6})\s+(\d{1,2}/\d{1,2}/\d{2,4})\s+([PC])\s+(\d+\.?\d*)$',
        description
    )
    if match:
        return _build_from_match(match.group(1), match.group(2), match.group(3), match.group(4))

    return None


def parse_generic_option_symbol(symbol):
    """
    Parse a generic readable option symbol.
    Format: TICKER MM/DD/YYYY STRIKE P/C
    Examples:
        'NFLX 04/24/2026 107.00 CALL'
        'SPY 12/20/2024 450 P'
    """
    if not symbol:
        return None
    
    symbol = symbol.strip().upper()
    
    # Pattern 1: TICKER DATE STRIKE P/C (where P/C can be P, C, PUT, CALL)
    match = re.match(
        r'^([A-Z0-9]{1,6})\s+(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})\s+([\d\.]+)\s+(P|C|PUT|CALL)$',
        symbol
    )
    if match:
        pc = match.group(4)
        put_call = 'C' if pc in ['C', 'CALL'] else 'P'
        return _build_from_match(match.group(1), match.group(2).replace('-', '/'), put_call, match.group(3))
    
    # Pattern 2: TICKER DATE P/C STRIKE
    match = re.match(
        r'^([A-Z0-9]{1,6})\s+(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})\s+(P|C|PUT|CALL)\s*([\d\.]+)$',
        symbol
    )
    if match:
        pc = match.group(3)
        put_call = 'C' if pc in ['C', 'CALL'] else 'P'
        return _build_from_match(match.group(1), match.group(2).replace('-', '/'), put_call, match.group(4))

    return None


def parse_schwab_description(description):
    """
    Parse Schwab-style option description.
    Examples:
        'AAPL OCT 17 2025 150.00 C'
        'SPY DEC 20 2024 430.00 P'
        'CALL NETFLIX INC $107 EXP 04/24/26'
    Returns dict or None.
    """
    if not description:
        return None

    description = description.strip().upper()

    # Pattern 1: CALL/PUT UNDERLYING $STRIKE EXP MM/DD/YY
    match = re.search(
        r'^(CALL|PUT)\s+(.*?)\s+\$(\d+\.?\d*)\s+EXP\s+(\d{1,2}/\d{1,2}/\d{2,4})',
        description
    )
    if match:
        put_call = 'C' if match.group(1) == 'CALL' else 'P'
        # Underlying is tricky in this format, try to extract from description or just use symbol later
        # But we'll try to get the first word of the '.*? ' part
        underlying_desc = match.group(2).split()[0]
        strike = match.group(3)
        date_str = match.group(4)
        return _build_from_match(underlying_desc, date_str, put_call, strike)

    # Pattern 2: Standard Schwab format
    # Remove action prefix
    description = re.sub(
        r'^(BUY|SELL)\s+(TO\s+)?(OPEN|CLOSE)\s+\d+\s+',
        '',
        description
    ).strip()

    month_map = {
        'JAN': '01', 'FEB': '02', 'MAR': '03', 'APR': '04',
        'MAY': '05', 'JUN': '06', 'JUL': '07', 'AUG': '08',
        'SEP': '09', 'OCT': '10', 'NOV': '11', 'DEC': '12'
    }

    match = re.match(
        r'^([A-Z]{1,6})\s+([A-Z]{3})\s+(\d{1,2})\s+(\d{4})\s+(\d+\.?\d*)\s+([PC])$',
        description
    )
    if match:
        underlying = match.group(1)
        month = month_map.get(match.group(2))
        day = match.group(3).zfill(2)
        year = match.group(4)
        strike = float(match.group(5))
        put_call = match.group(6)

        if month:
            expiry = f"{year}-{month}-{day}"
            return {
                'underlying': underlying,
                'expiry': expiry,
                'put_call': put_call,
                'strike': strike,
            }

    return None


def parse_tastytrade_api_symbol(symbol):
    """
    Parse tastytrade API option symbol.
    Format: AAPL  251017C00150000 (same as OCC)
    The tastytrade API uses OCC symbology.
    """
    return parse_occ_symbol(symbol)


def build_display_symbol(underlying, expiry, strike, put_call):
    """Build a human-readable display string for an option."""
    try:
        expiry_dt = datetime.strptime(expiry, '%Y-%m-%d')
        expiry_str = expiry_dt.strftime('%m/%d/%y')
    except (ValueError, TypeError):
        expiry_str = expiry or '?'

    strike_str = f"{strike:.0f}" if strike == int(strike) else f"{strike:.2f}"
    pc_str = 'Call' if put_call == 'C' else 'Put'

    return f"{underlying} {expiry_str} {strike_str}{put_call}"


def build_occ_symbol(underlying, expiry, strike, put_call):
    """Build an OCC standard symbol."""
    try:
        expiry_dt = datetime.strptime(expiry, '%Y-%m-%d')
        date_str = expiry_dt.strftime('%y%m%d')
    except (ValueError, TypeError):
        return None

    underlying_padded = underlying.ljust(6)
    strike_int = int(strike * 1000)
    strike_str = str(strike_int).zfill(8)

    return f"{underlying_padded}{date_str}{put_call}{strike_str}"


def extract_underlying_from_symbol(symbol):
    """Extract the underlying ticker from any option symbol format."""
    parsed = parse_occ_symbol(symbol)
    if parsed:
        return parsed['underlying']

    # Try simple extraction - first word before space or numbers
    match = re.match(r'^([A-Z]{1,6})', symbol.strip())
    if match:
        return match.group(1)

    return symbol


def is_option_symbol(symbol):
    """Check if a symbol looks like an option contract."""
    if not symbol:
        return False
    return parse_occ_symbol(symbol) is not None


def calculate_dte(expiry):
    """Calculate days to expiration from an expiry date string."""
    if not expiry:
        return None
    try:
        expiry_dt = datetime.strptime(expiry, '%Y-%m-%d').date()
        today = date.today()
        dte = (expiry_dt - today).days
        return max(0, dte)
    except (ValueError, TypeError):
        return None


def _build_from_match(underlying, date_str, put_call, strike_str):
    """Helper to build result dict from regex match groups."""
    try:
        # Try multiple date formats
        for fmt in ['%m/%d/%Y', '%m/%d/%y']:
            try:
                expiry_dt = datetime.strptime(date_str, fmt)
                expiry = expiry_dt.strftime('%Y-%m-%d')
                break
            except ValueError:
                continue
        else:
            return None

        strike = float(strike_str)
        return {
            'underlying': underlying.strip(),
            'expiry': expiry,
            'put_call': put_call.strip(),
            'strike': strike,
        }
    except (ValueError, TypeError):
        return None
