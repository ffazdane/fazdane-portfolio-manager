"""
YTD Upload Validator
Validates filenames and parsed content for broker transaction files.

Supported filename patterns:
  TastyTrade (gain/loss worksheet): YYYY-AccountNumber-gain_loss_tax_worksheet.*
  TastyTrade (transaction history):  tastytrade_transactions_history_x{acct}_{YYMMDD}_to_{YYMMDD}.*
  Schwab (transaction history):      Individual_AccountNumber_Transactions_YYYYMMDD-HHMMSS.*
"""

import re
from typing import Optional


# ── Filename patterns ─────────────────────────────────────────────────────────

# TastyTrade gain/loss worksheet: 2026-5WT12803-gain_loss_tax_worksheet.csv
TASTYTRADE_GAINLOSS_PATTERN = re.compile(
    r'(?P<year>\d{4})-(?P<account>[A-Z0-9]+)-', re.IGNORECASE
)

# TastyTrade transaction history: tastytrade_transactions_history_x5WT12803_240101_to_251231.csv
TASTYTRADE_HISTORY_PATTERN = re.compile(
    r'tastytrade_transactions_history_x(?P<account>[A-Z0-9]+)_(?P<from>\d{6})_to_(?P<to>\d{6})',
    re.IGNORECASE
)

# Schwab: Individual_XXX177_Transactions_20260425-142924.csv
SCHWAB_PATTERN = re.compile(
    r'Individual_(?P<account>[A-Z0-9]+)_Transactions_(?P<date>\d{8})', re.IGNORECASE
)


# ── Year helpers ──────────────────────────────────────────────────────────────

def _yymmdd_to_year(yymmdd: str) -> int:
    """Convert YYMMDD (240101) to full year (2024)."""
    yy = int(yymmdd[:2])
    return 2000 + yy if yy < 100 else yy


def detect_year_from_filename(filename: str) -> Optional[int]:
    """
    Extract the PRIMARY transaction year from a filename.
    For multi-year files, returns the EARLIEST year.
    For single-year files, returns the year embedded in the name.
    """
    m = TASTYTRADE_HISTORY_PATTERN.search(filename)
    if m:
        return _yymmdd_to_year(m.group('from'))

    m = TASTYTRADE_GAINLOSS_PATTERN.search(filename)
    if m:
        return int(m.group('year'))

    m = SCHWAB_PATTERN.search(filename)
    if m:
        return int(m.group('date')[:4])

    # Fallback: any 4-digit year
    years = re.findall(r'20[2-3]\d', filename)
    return int(years[0]) if years else None


def detect_year_range_from_filename(filename: str) -> list[int]:
    """
    Return ALL years covered by the file.
    For multi-year history files, returns [2024, 2025].
    For single-year files, returns [year].
    """
    m = TASTYTRADE_HISTORY_PATTERN.search(filename)
    if m:
        y_from = _yymmdd_to_year(m.group('from'))
        y_to   = _yymmdd_to_year(m.group('to'))
        return list(range(y_from, y_to + 1))

    y = detect_year_from_filename(filename)
    return [y] if y else []


def detect_account_from_filename(filename: str, known_accounts: list) -> Optional[str]:
    """
    Extract and validate account number from a filename.
    Returns account_number string or None.
    """
    for acct in known_accounts:
        if acct in filename:
            return acct
    return None


def detect_file_type(filename: str) -> str:
    """
    Return 'history' for multi-year transaction history files,
    'gainloss' for tax worksheet files,
    'schwab' for Schwab transaction files,
    'unknown' otherwise.
    """
    if TASTYTRADE_HISTORY_PATTERN.search(filename):
        return 'history'
    if TASTYTRADE_GAINLOSS_PATTERN.search(filename):
        return 'gainloss'
    if SCHWAB_PATTERN.search(filename):
        return 'schwab'
    return 'unknown'


# ── Filename validators ───────────────────────────────────────────────────────

def validate_tastytrade_filename(filename: str, account: str) -> tuple[bool, str]:
    """
    Validate TastyTrade filename — accepts BOTH:
    - Gain/loss worksheet: YYYY-AccountNumber-gain_loss_tax_worksheet.*
    - Transaction history: tastytrade_transactions_history_x{acct}_{from}_to_{to}.*
    """
    # History pattern (multi-year)
    m = TASTYTRADE_HISTORY_PATTERN.search(filename)
    if m:
        if account not in filename:
            return False, f"Account number '{account}' not found in filename."
        return True, ""

    # Gain/loss pattern (single year)
    m = TASTYTRADE_GAINLOSS_PATTERN.search(filename)
    if m:
        if account not in filename:
            return False, f"Account number '{account}' not found in filename."
        return True, ""

    return False, (
        f"TastyTrade filename must match one of:\n"
        f"  • YYYY-AccountNumber-gain_loss_tax_worksheet.csv\n"
        f"  • tastytrade_transactions_history_x{{account}}_YYMMDD_to_YYMMDD.csv\n"
        f"Got: '{filename}'"
    )


def validate_schwab_filename(filename: str, account: str) -> tuple[bool, str]:
    """Validate Schwab: Individual_AccountNumber_Transactions_YYYYMMDD-HHMMSS.*"""
    m = SCHWAB_PATTERN.search(filename)
    if not m:
        return False, (
            f"Schwab filename must match: Individual_AccountNumber_Transactions_YYYYMMDD-HHMMSS.csv\n"
            f"Got: '{filename}'"
        )
    if account not in filename:
        return False, f"Account number '{account}' not found in filename."
    return True, ""


def validate_parsed_transactions(transactions: list, min_rows: int = 1) -> tuple[bool, str]:
    """Validate parsed transaction list has data and required fields."""
    if len(transactions) < min_rows:
        return False, f"File contained no valid transactions (parsed 0 rows)."

    required_fields = ['date', 'symbol', 'quantity', 'amount']
    sample = transactions[0]
    missing = [f for f in required_fields if f not in sample]
    if missing:
        return False, f"Parsed transactions are missing required fields: {missing}"

    return True, ""
