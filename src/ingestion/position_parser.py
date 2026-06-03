"""
Position File Parser
====================
Parses broker position-snapshot exports (NOT transaction history files).

Supported formats:
  Schwab:       Individual-Positions-YYYY-MM-DD-HHMMSS.csv
                  Symbol col format: "AAPL 06/18/2026 290.00 C"
  Tastytrade:   tastytrade_positions_x{ACCOUNT}_{YYMMDD}.csv
                  Columns: Account, Symbol (OCC), Type, Quantity, Exp Date,
                            Strike Price, Call/Put, Trade Price …

The output is a list of position dicts ready to be passed through
group_positions_into_trades() → save_trades_to_db().
"""

import re
import pandas as pd
from datetime import datetime, date
from typing import Optional


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_number(v) -> float:
    """Coerce broker-formatted numbers (e.g. '($1,234.56)') to float."""
    if v is None:
        return 0.0
    s = str(v).strip()
    if not s or s in ('--', 'n/a', 'N/A'):
        return 0.0
    # Remove currency symbols, thousands separators, whitespace
    s = s.replace('$', '').replace(',', '').replace(' ', '')
    # Parentheses → negative
    if s.startswith('(') and s.endswith(')'):
        s = '-' + s[1:-1]
    try:
        return float(s)
    except (ValueError, TypeError):
        return 0.0


def _parse_date(s: str) -> Optional[str]:
    """Return YYYY-MM-DD string from a variety of date formats, or None."""
    if not s or str(s).strip() in ('--', ''):
        return None
    s = str(s).strip()
    for fmt in ('%m/%d/%Y', '%Y-%m-%d', '%m-%d-%Y', '%d-%b-%Y',
                '%b %d %Y', '%d %b %Y'):
        try:
            return datetime.strptime(s, fmt).strftime('%Y-%m-%d')
        except ValueError:
            pass
    # YYMMDD used in tastytrade filenames
    if re.match(r'^\d{6}$', s):
        try:
            return datetime.strptime(s, '%y%m%d').strftime('%Y-%m-%d')
        except ValueError:
            pass
    return None


def normalize_account_number(acct_str: str) -> str:
    """Normalize the account number based on registered accounts in the database."""
    if not acct_str:
        return acct_str
    # Extract only digits and letters (clean up spaces/symbols)
    clean = re.sub(r'[^A-Z0-9]', '', acct_str.upper())
    
    try:
        from src.database.queries import get_account_master
        accounts = get_account_master()
        for acc in accounts:
            acc_num = acc['account_number']  # e.g., 'XXX177'
            acc_digits = re.sub(r'[^0-9]', '', acc_num)
            clean_digits = re.sub(r'[^0-9]', '', clean)
            if acc_digits and clean_digits.endswith(acc_digits):
                return acc_num
            if clean in acc_num or acc_num in clean:
                return acc_num
    except Exception:
        pass
    return clean


# ---------------------------------------------------------------------------
# Schwab position row  "AAPL 06/18/2026 290.00 C"
# ---------------------------------------------------------------------------

_SCHWAB_OPTION_RE = re.compile(
    r'^(?P<underlying>[A-Z^./]+)\s+'
    r'(?P<exp>\d{2}/\d{2}/\d{4})\s+'
    r'(?P<strike>\d+\.?\d*)\s+'
    r'(?P<pc>[CP])$',
    re.IGNORECASE
)


def _parse_schwab_symbol(symbol: str) -> Optional[dict]:
    """Parse Schwab option symbol string into components."""
    m = _SCHWAB_OPTION_RE.match(symbol.strip())
    if not m:
        return None
    exp_str = m.group('exp')   # MM/DD/YYYY
    try:
        exp_dt = datetime.strptime(exp_str, '%m/%d/%Y').strftime('%Y-%m-%d')
    except ValueError:
        return None
    return {
        'underlying': m.group('underlying').upper(),
        'expiry':     exp_dt,
        'strike':     float(m.group('strike')),
        'put_call':   m.group('pc').upper(),   # 'C' or 'P'
    }


# ---------------------------------------------------------------------------
# Tastytrade OCC symbol  "AAPL  260618C00285000"
# ---------------------------------------------------------------------------

_OCC_RE = re.compile(
    r'^(?P<underlying>[A-Z^./]{1,6})\s*'
    r'(?P<yy>\d{2})(?P<mm>\d{2})(?P<dd>\d{2})'
    r'(?P<pc>[CP])'
    r'(?P<strike_raw>\d{8})$',
    re.IGNORECASE
)


def _parse_occ_symbol(symbol: str) -> Optional[dict]:
    """Parse OCC/OSI option symbol into components."""
    s = symbol.strip().replace(' ', '')
    # Handle extra spaces inside the symbol (TT uses '  ' as spacer)
    s = re.sub(r'\s+', '', symbol.strip())
    m = _OCC_RE.match(s)
    if not m:
        return None
    yy = int(m.group('yy'))
    year = 2000 + yy
    mon = int(m.group('mm'))
    day = int(m.group('dd'))
    try:
        exp_dt = date(year, mon, day).strftime('%Y-%m-%d')
    except ValueError:
        return None
    strike = int(m.group('strike_raw')) / 1000.0
    return {
        'underlying': m.group('underlying').upper(),
        'expiry':     exp_dt,
        'strike':     strike,
        'put_call':   m.group('pc').upper(),
    }


# ---------------------------------------------------------------------------
# Broker detection
# ---------------------------------------------------------------------------

SCHWAB_POSITIONS_PATTERN = re.compile(
    r'Individual-Positions-\d{4}-\d{2}-\d{2}',
    re.IGNORECASE
)

TASTYTRADE_POSITIONS_PATTERN = re.compile(
    r'tastytrade_positions_x(?P<account>[A-Z0-9]+)_',
    re.IGNORECASE
)

# Schwab account number is embedded in the header row of the CSV
_SCHWAB_HEADER_ACCT_RE = re.compile(r'Individual\s+\.\.\.\s*(?P<suffix>\d+)')


def detect_position_broker(filename: str, raw_text: str = '') -> dict:
    """
    Detect broker and account number from a position file.

    Returns {'broker': str, 'account': str|None}
    """
    fn = filename.strip()
    fn_lower = fn.lower()

    # Tastytrade positions filename carries the account number
    m = TASTYTRADE_POSITIONS_PATTERN.search(fn)
    if m:
        return {'broker': 'tastytrade', 'account': m.group('account')}

    # Schwab Thinkorswim (Position Statement)
    if 'positionstatement' in fn_lower or 'position-statement' in fn_lower or (raw_text and 'position statement for' in raw_text.lower()[:500]):
        acct = None
        if raw_text:
            m_acct = re.search(r'Position\s+Statement\s+for\s+(?P<acct>[A-Z0-9]+)', raw_text, re.IGNORECASE)
            if m_acct:
                acct = m_acct.group('acct')
        return {'broker': 'schwab', 'account': acct}

    # Schwab — account extracted from first line of CSV content
    if SCHWAB_POSITIONS_PATTERN.search(fn) or fn_lower.startswith('individual-positions'):
        acct = None
        if raw_text:
            hm = _SCHWAB_HEADER_ACCT_RE.search(raw_text[:500])
            acct = hm.group('suffix') if hm else None
        return {'broker': 'schwab', 'account': acct}

    return {'broker': None, 'account': None}


def is_position_file(filename: str) -> bool:
    """Quick check: does the filename look like a position-snapshot export?"""
    fn = filename.lower()
    return (
        SCHWAB_POSITIONS_PATTERN.search(filename) is not None
        or TASTYTRADE_POSITIONS_PATTERN.search(filename) is not None
        or fn.startswith('individual-positions')
        or 'positionstatement' in fn
        or 'position-statement' in fn
    )


# ---------------------------------------------------------------------------
# Schwab position CSV parser
# ---------------------------------------------------------------------------

def parse_schwab_tos_positions(df: pd.DataFrame, account: str) -> list[dict]:
    """
    Parse a Schwab/thinkorswim Position Statement CSV into position dicts.
    """
    positions = []
    current_underlying = None
    today_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    # Convert the entire dataframe to a list of lists of strings
    rows = []
    for _, r in df.iterrows():
        rows.append([str(val).strip() if pd.notna(val) else '' for val in r.values])

    # Option pattern for thinkorswim instrument column
    # e.g., "100 18 JUN 26 325 CALL" or "100 (Weeklys) 5 JUN 26 290 CALL"
    option_re = re.compile(
        r'^(?P<mult>\d+)\s+'
        r'(?:\([^)]+\)\s+)?'
        r'(?P<day>\d{1,2})\s+'
        r'(?P<month>[A-Z]{3})\s+'
        r'(?P<year>\d{2})\s+'
        r'(?P<strike>\d+(?:\.\d+)?)\s+'
        r'(?P<pc>CALL|PUT)$',
        re.IGNORECASE
    )

    MONTHS = {'JAN': 1, 'FEB': 2, 'MAR': 3, 'APR': 4, 'MAY': 5, 'JUN': 6, 
              'JUL': 7, 'AUG': 8, 'SEP': 9, 'OCT': 10, 'NOV': 11, 'DEC': 12}

    # Find the header row to map column indexes
    header_row = None
    for row in rows:
        if 'Instrument' in row and 'Qty' in row and 'P/L Open' in row:
            header_row = row
            break

    if not header_row:
        # Fallback default thinkorswim headers
        header_row = ['Instrument', 'Qty', 'Days', 'Trade Price', 'Mark', 'Mrk Chng', 'Delta', 'Theta', 'Gamma', 'Vega', 'P/L Open', 'P/L Day', 'BP Effect']

    col_map = {name: i for i, name in enumerate(header_row)}

    for row in rows:
        if not row or len(row) < 3:
            continue
        first_val = row[0].strip()
        if not first_val or first_val == 'None' or first_val.startswith('Position Statement') or first_val.startswith('Group'):
            continue

        if any(kw in first_val.lower() for kw in ('subtotal', 'overall', 'cash & sweep', 'bp adjustment', 'available dollars', 'overnight')):
            continue

        m = option_re.match(first_val)
        if m:
            if not current_underlying:
                continue
            
            qty_idx = col_map.get('Qty', 1)
            trade_price_idx = col_map.get('Trade Price', 3)
            pl_open_idx = col_map.get('P/L Open', 10)
            
            raw_qty = _parse_number(row[qty_idx]) if qty_idx < len(row) else 0.0
            if raw_qty == 0:
                continue

            entry_price = abs(_parse_number(row[trade_price_idx])) if trade_price_idx < len(row) else 0.0
            pl_open = _parse_number(row[pl_open_idx]) if pl_open_idx < len(row) else 0.0
            side = 'SHORT' if raw_qty < 0 else 'LONG'
            
            day = int(m.group('day'))
            month_name = m.group('month').upper()
            month = MONTHS.get(month_name, 1)
            year = 2000 + int(m.group('year'))
            
            expiry_str = f"{year:04d}-{month:02d}-{day:02d}"
            expiry_slashes = f"{month:02d}/{day:02d}/{year:04d}"
            strike = float(m.group('strike'))
            pc = 'C' if m.group('pc').upper() == 'CALL' else 'P'
            
            schwab_symbol = f"{current_underlying} {expiry_slashes} {strike:.2f} {pc}"

            positions.append({
                'account':          account or 'schwab',
                'broker':           'schwab',
                'underlying':       current_underlying,
                'expiry':           expiry_str,
                'put_call':         pc,
                'strike':           strike,
                'open_date':        today_str,
                'instrument_type':  'OPTION',
                'side':             side,
                'total_open':       abs(raw_qty),
                'is_fully_closed':  False,
                'total_closed':     0,
                'avg_open_price':   entry_price,
                'avg_close_price':  0,
                'realized_pnl':     0,
                'unrealized_pnl':   pl_open,
                'symbol':           schwab_symbol,
            })
        else:
            qty_idx = col_map.get('Qty', 1)
            days_idx = col_map.get('Days', 2)
            trade_price_idx = col_map.get('Trade Price', 3)

            qty_val = row[qty_idx] if qty_idx < len(row) else ''
            days_val = row[days_idx] if days_idx < len(row) else ''
            tp_val = row[trade_price_idx] if trade_price_idx < len(row) else ''

            if qty_val == '' and days_val == '' and tp_val == '':
                if first_val and len(first_val) <= 6 and (first_val.isalnum() or first_val.startswith('/') or first_val.startswith('^')):
                    current_underlying = first_val.replace('/', '').replace('^', '').upper()

    return positions


def parse_schwab_positions(df: pd.DataFrame, account: str) -> list[dict]:
    """
    Parse a Schwab Individual Positions CSV into position dicts.

    Schwab CSV structure (after dropping header rows):
      Symbol | Description | Qty | Price | … | Asset Type

    Returns list of position dicts compatible with strategy_grouper.
    """
    # Check if this is a thinkorswim format Positions Statement
    first_val = str(df.iloc[0, 0]) if df.shape[0] > 0 and df.shape[1] > 0 else ''
    if 'position statement for' in first_val.lower() or 'overall totals' in str(df.values).lower():
        return parse_schwab_tos_positions(df, account)

    positions = []

    # Schwab has two metadata rows at the top; find the real header
    # The real header row contains "Symbol" as a column name
    header_row = None
    for i, row in df.iterrows():
        vals = [str(v).strip() for v in row.values]
        if 'Symbol' in vals:
            header_row = i
            break

    if header_row is None:
        # Assume first row is already the header (already read correctly)
        header_row = -1

    if header_row >= 0:
        # Re-read with correct header
        new_header = list(df.iloc[header_row])
        df = df.iloc[header_row + 1:].copy()
        df.columns = new_header
        df = df.reset_index(drop=True)

    # Normalise column names
    df.columns = [str(c).strip() for c in df.columns]

    col_symbol = next((c for c in df.columns if c.lower() == 'symbol'), None)
    col_qty    = next((c for c in df.columns if 'qty' in c.lower() and 'quantity' not in c.lower()), None)
    if col_qty is None:
        col_qty = next((c for c in df.columns if 'quantity' in c.lower()), None)
    col_price  = next((c for c in df.columns if c.lower() == 'price'), None)
    col_cost   = next((c for c in df.columns if 'cost' in c.lower() and 'basis' in c.lower()), None)
    col_type   = next((c for c in df.columns if 'asset type' in c.lower()), None)
    col_pl_open = next((c for c in df.columns if any(x in c.lower() for x in (
        'pl open', 'p/l open', 'unrealized p/l', 'unrealized p&l', 
        'unrealized gain/loss', 'gain/loss', 'p/l ($)', 'p&l ($)', 'unrealized'
    ))), None)

    if not col_symbol:
        raise ValueError("Cannot find 'Symbol' column in Schwab positions file.")

    today_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    for _, row in df.iterrows():
        symbol_val = str(row.get(col_symbol, '')).strip()
        if not symbol_val or symbol_val in ('--', 'nan', ''):
            continue

        asset_type = str(row.get(col_type, '')).strip().lower() if col_type else ''
        # Skip non-option rows (cash, futures, totals)
        if asset_type and 'option' not in asset_type:
            continue
        # Skip totals / summary rows
        if any(kw in symbol_val.lower() for kw in ('total', 'cash', 'futures', 'positions')):
            continue

        opt = _parse_schwab_symbol(symbol_val)
        if not opt:
            continue  # Skip rows that don't look like options

        raw_qty = _parse_number(row.get(col_qty, 0))
        if raw_qty == 0:
            continue

        entry_price = abs(_parse_number(row.get(col_price, 0)))
        cost_basis  = _parse_number(row.get(col_cost, 0))
        pl_open     = _parse_number(row.get(col_pl_open, 0)) if col_pl_open else 0.0

        side = 'SHORT' if raw_qty < 0 else 'LONG'

        positions.append({
            'account':          account or 'schwab',
            'broker':           'schwab',
            'underlying':       opt['underlying'],
            'expiry':           opt['expiry'],
            'put_call':         opt['put_call'],
            'strike':           opt['strike'],
            'open_date':        today_str,
            'instrument_type':  'OPTION',
            'side':             side,
            'total_open':       abs(raw_qty),
            'is_fully_closed':  False,
            'total_closed':     0,
            'avg_open_price':   entry_price,
            'avg_close_price':  0,
            'realized_pnl':     0,
            'unrealized_pnl':   pl_open,
            'symbol':           symbol_val,
        })

    return positions


# ---------------------------------------------------------------------------
# Tastytrade position CSV parser
# ---------------------------------------------------------------------------

def parse_tastytrade_positions(df: pd.DataFrame, account: str) -> list[dict]:
    """
    Parse a tastytrade positions CSV into position dicts.

    Expected columns:
      Account, Symbol, Type, Quantity, Exp Date, DTE, Strike Price,
      Call/Put, Underlying Last Price, Trade Price, …

    Works whether the DataFrame was read with header=None or header=0.
    """
    positions = []

    # ── Auto-detect header row ───────────────────────────────────────────────
    # If columns are numeric (0, 1, 2…) the file was read with header=None;
    # find the row that has 'Symbol' as one of its values.
    first_col = df.columns.tolist()[0] if len(df.columns) > 0 else None
    if first_col is not None and str(first_col).isdigit():
        header_row = None
        for i, row in df.iterrows():
            vals = [str(v).strip() for v in row.values]
            if 'Symbol' in vals:
                header_row = i
                break
        if header_row is not None:
            new_header = list(df.iloc[header_row])
            df = df.iloc[header_row + 1:].copy()
            df.columns = new_header
            df = df.reset_index(drop=True)


    # Normalise column names
    df.columns = [str(c).strip() for c in df.columns]

    col_acct    = next((c for c in df.columns if c.lower() == 'account'), None)
    col_symbol  = next((c for c in df.columns if c.lower() == 'symbol'), None)
    col_type    = next((c for c in df.columns if c.lower() == 'type'), None)
    col_qty     = next((c for c in df.columns if c.lower() == 'quantity'), None)
    col_exp     = next((c for c in df.columns if 'exp date' in c.lower()), None)
    col_strike  = next((c for c in df.columns if 'strike price' in c.lower()), None)
    col_pc      = next((c for c in df.columns if 'call/put' in c.lower()), None)
    col_price   = next((c for c in df.columns if 'trade price' in c.lower()), None)
    col_underly = next((c for c in df.columns
                        if 'underlying' in c.lower() and 'last' not in c.lower()), None)
    col_pl_open = next((c for c in df.columns if any(x in c.lower() for x in (
        'pl open', 'p/l open', 'unrealized p/l', 'unrealized p&l', 
        'unrealized gain/loss', 'gain/loss', 'p/l ($)', 'p&l ($)', 'unrealized'
    ))), None)

    if not col_symbol:
        raise ValueError("Cannot find 'Symbol' column in tastytrade positions file.")


    today_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    for _, row in df.iterrows():
        symbol_val = str(row.get(col_symbol, '')).strip()
        if not symbol_val or symbol_val in ('nan', ''):
            continue

        instr_type = str(row.get(col_type, '')).strip().upper() if col_type else ''
        # Only process options for now
        if instr_type and instr_type not in ('OPTION', 'EQUITY_OPTION'):
            continue

        raw_qty = _parse_number(row.get(col_qty, 0))
        if raw_qty == 0:
            continue

        # Try parsing from explicit columns first, then fallback to OCC symbol
        underlying = None
        expiry     = None
        strike     = None
        put_call   = None

        if col_exp and col_strike and col_pc:
            expiry   = _parse_date(str(row.get(col_exp, '')))
            strike   = _parse_number(row.get(col_strike, 0)) or None
            put_call = str(row.get(col_pc, '')).strip().upper()[:1] or None
            if col_underly:
                underlying = str(row.get(col_underly, '')).strip().upper() or None

        # If still missing underlying, try OCC symbol
        if not underlying or not expiry:
            opt = _parse_occ_symbol(symbol_val)
            if opt:
                underlying = opt['underlying']
                expiry     = opt['expiry']
                strike     = opt.get('strike') or strike
                put_call   = opt.get('put_call') or put_call

        if not underlying:
            continue

        entry_price = abs(_parse_number(row.get(col_price, 0))) if col_price else 0
        # TT trade price is per-share; multiply by -1 if it was originally negative
        # (TT shows negative trade price for shorts on the sell side)
        pl_open     = _parse_number(row.get(col_pl_open, 0)) if col_pl_open else 0.0

        side = 'SHORT' if raw_qty < 0 else 'LONG'

        # Account override: use per-row account if available
        row_acct = str(row.get(col_acct, '')).strip() if col_acct else ''
        final_acct = row_acct if row_acct and row_acct != 'nan' else (account or 'tastytrade')

        positions.append({
            'account':          final_acct,
            'broker':           'tastytrade',
            'underlying':       underlying,
            'expiry':           expiry,
            'put_call':         put_call,
            'strike':           strike,
            'open_date':        today_str,
            'instrument_type':  'OPTION',
            'side':             side,
            'total_open':       abs(raw_qty),
            'is_fully_closed':  False,
            'total_closed':     0,
            'avg_open_price':   entry_price,
            'avg_close_price':  0,
            'realized_pnl':     0,
            'unrealized_pnl':   pl_open,
            'symbol':           symbol_val,
        })

    return positions


# ---------------------------------------------------------------------------
# Unified entry point
# ---------------------------------------------------------------------------

def parse_position_file(
    df: pd.DataFrame,
    filename: str,
    raw_text: str = '',
    broker_override: str = None,
    account_override: str = None,
) -> tuple[list[dict], str, str]:
    """
    Auto-detect the broker from filename and parse the position file.

    Returns:
        (positions, broker, account)
    """
    info = detect_position_broker(filename, raw_text)
    broker  = broker_override  or info.get('broker')  or ''
    account = account_override or info.get('account') or ''

    # Normalize account number if not explicitly overridden
    if not account_override and account:
        account = normalize_account_number(account)

    if broker == 'schwab':
        positions = parse_schwab_positions(df, account)
    elif broker == 'tastytrade':
        positions = parse_tastytrade_positions(df, account)
    else:
        raise ValueError(
            f"Cannot determine broker for position file '{filename}'. "
            "Expected 'tastytrade_positions_x…' or 'Individual-Positions-…'."
        )

    return positions, broker, account
