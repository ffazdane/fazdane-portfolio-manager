"""
TastyTrade Transaction History Parser
Handles the full account transaction history export:
  tastytrade_transactions_history_x{acct}_{from}_to_{to}.csv

21 columns — fully structured with option fields pre-parsed:
  Date, Type, Sub Type, Action, Symbol, Instrument Type, Description,
  Value, Quantity, Average Price, Commissions, Fees, Multiplier,
  Root Symbol, Underlying Symbol, Expiration Date, Strike Price,
  Call or Put, Order #, Total, Currency

Supports multi-year files — each row tagged with its calendar year
so the upload pipeline can split and store by year independently.
"""

import re
import pandas as pd
from src.ingestion.base_parser import BrokerParser

# Transaction types to skip (non-trade activity)
SKIP_TYPES = {'Money Movement', 'Receive Deliver'}
SKIP_SUB_TYPES = {
    'Balance Adjustment', 'Mark to Market', 'Deposit', 'Withdrawal',
    'Credit Interest', 'Debit Interest', 'Transfer', 'ACH',
    'Wire', 'Fee', 'Dividend', 'Interest Income',
}


class TastytradeHistoryParser(BrokerParser):
    """
    Parser for TastyTrade full transaction history CSV export.
    Detects via 'Underlying Symbol' + 'Commissions' + 'Multiplier' columns.
    """

    def get_broker_name(self):
        return 'tastytrade'

    def get_expected_columns(self):
        return ['Date', 'Type', 'Action', 'Symbol', 'Value',
                'Quantity', 'Commissions', 'Fees', 'Underlying Symbol']

    def detect(self, df):
        """Detect TastyTrade history format by unique column combination."""
        cols_lower = {str(c).strip().lower() for c in df.columns}
        return (
            'underlying symbol' in cols_lower
            and 'commissions' in cols_lower
            and 'multiplier' in cols_lower
            and 'call or put' in cols_lower
        )

    def parse(self, df):
        """Parse the history DataFrame into broker_transactions dicts."""
        df = df.copy()
        df.columns = [str(c).strip() for c in df.columns]

        transactions = []
        for idx, row in df.iterrows():
            try:
                txn = self._parse_row(row)
                if txn:
                    transactions.append(txn)
            except Exception as e:
                print(f"Warning: Skipping TT history row {idx}: {e}")
                continue

        return transactions

    def _parse_row(self, row):
        """Parse a single TastyTrade history row."""
        tx_type    = str(row.get('Type', '') or '').strip()
        sub_type   = str(row.get('Sub Type', '') or '').strip()

        # Skip non-trade records
        if tx_type in SKIP_TYPES:
            return None
        if sub_type in SKIP_SUB_TYPES:
            return None

        # ── Dates ─────────────────────────────────────────────────────────
        raw_date = str(row.get('Date', '') or '').strip()
        date_str = self._normalise_date(raw_date)
        if not date_str:
            return None

        year = int(date_str[:4])

        # ── Symbol & Instrument ───────────────────────────────────────────
        symbol     = str(row.get('Symbol', '') or '').strip()
        underlying = str(row.get('Underlying Symbol', '') or '').strip()
        inst_type  = str(row.get('Instrument Type', '') or '').strip()
        description= str(row.get('Description', '') or '').strip()

        if not symbol or symbol.lower() in ('nan', 'none', ''):
            return None
        if not underlying:
            underlying = symbol

        # ── Option fields (already parsed in TastyTrade export) ──────────
        expiry     = self._normalise_date(str(row.get('Expiration Date', '') or ''))
        strike     = self._parse_number(row.get('Strike Price', 0))
        put_call   = str(row.get('Call or Put', '') or '').strip().upper()
        multiplier = self._parse_number(row.get('Multiplier', 100))
        if not multiplier:
            multiplier = 100

        # ── Financials ────────────────────────────────────────────────────
        value      = self._parse_number(row.get('Value', 0))         # signed cash flow
        avg_price  = self._parse_number(row.get('Average Price', 0))
        commissions= self._parse_number(row.get('Commissions', 0))
        fees       = self._parse_number(row.get('Fees', 0))
        total      = self._parse_number(row.get('Total', 0))         # value + commissions + fees
        quantity   = self._parse_number(row.get('Quantity', 0))

        total_fees = abs(commissions) + abs(fees)

        # ── Action / side ─────────────────────────────────────────────────
        action = str(row.get('Action', sub_type) or sub_type).strip()
        side, open_close = self._parse_action(action)

        # ── Normalized type ───────────────────────────────────────────────
        action_lower = action.lower()
        sub_lower    = sub_type.lower()
        combined     = f"{action_lower} {sub_lower}"
        if 'expir' in combined:
            normalized_type = 'EXPIRATION'
        elif 'assign' in combined:
            normalized_type = 'ASSIGNMENT'
        elif 'exercis' in combined:
            normalized_type = 'EXERCISE'
        elif 'mark to market' in combined:
            normalized_type = 'MARK_TO_MARKET'
        else:
            normalized_type = 'TRADE'

        # ── Instrument type normalisation ─────────────────────────────────
        inst_upper = inst_type.upper()
        if 'OPTION' in inst_upper:
            norm_instrument = 'EQUITY_OPTION'
        elif 'FUTURE' in inst_upper and 'OPTION' not in inst_upper:
            norm_instrument = 'FUTURE'
        elif 'FUTURE' in inst_upper:
            norm_instrument = 'FUTURE_OPTION'
        elif 'EQUITY' in inst_upper:
            norm_instrument = 'EQUITY'
        else:
            norm_instrument = inst_type or 'EQUITY'

        return {
            'broker':          'tastytrade',
            'account':         'default',       # filled in by upload pipeline
            'date':            date_str,
            'year':            year,
            'symbol':          symbol,
            'underlying':      underlying,
            'description':     description,
            'instrument_type': norm_instrument,
            'expiry':          expiry or None,
            'strike':          strike or None,
            'put_call':        put_call or None,
            'multiplier':      multiplier,
            'action':          action,
            'side':            side,
            'open_close':      open_close or '',
            'quantity':        abs(quantity) if quantity else 0,
            'price':           avg_price,
            'amount':          value,            # signed cash impact (positive = received)
            'commissions':     commissions,
            'fees':            total_fees,
            'total':           total,            # net cash including all fees
            'normalized_type': normalized_type,
            'order_id':        str(row.get('Order #', '') or '').strip(),
            'type':            tx_type,
            'sub_type':        sub_type,
            'source_file_name': '',
        }

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _parse_action(self, action):
        a = action.lower().strip()
        if 'sell_to_open'   in a or 'sell to open'   in a: return 'SELL', 'OPEN'
        if 'sell_to_close'  in a or 'sell to close'  in a: return 'SELL', 'CLOSE'
        if 'buy_to_open'    in a or 'buy to open'    in a: return 'BUY',  'OPEN'
        if 'buy_to_close'   in a or 'buy to close'   in a: return 'BUY',  'CLOSE'
        if 'sell'           in a:                           return 'SELL', None
        if 'buy'            in a:                           return 'BUY',  None
        if 'expir'          in a:                           return 'SELL', 'CLOSE'
        if 'assign'         in a:                           return 'SELL', 'CLOSE'
        return a.upper(), None

    def _parse_number(self, value):
        """Parse any numeric string to float — never returns NaN."""
        import math
        if value is None:
            return 0.0
        try:
            if isinstance(value, float):
                return 0.0 if math.isnan(value) else value
            if isinstance(value, int):
                return float(value)
            if isinstance(value, str):
                s = value.replace(',', '').replace('$', '').replace('(', '-').replace(')', '').strip()
                if not s or s.lower() in ('nan', 'none', 'n/a', '--', ''):
                    return 0.0
                return float(s)
            import pandas as _pd
            if _pd.isna(value):
                return 0.0
            return float(value)
        except (ValueError, TypeError):
            return 0.0

    def _normalise_date(self, value):
        """Normalise any date string to YYYY-MM-DD."""
        if not value:
            return None
        s = str(value).strip()
        if not s or s.lower() in ('nan', 'none', ''):
            return None
        # ISO with timezone: 2025-12-31T10:33:58-0600
        if 'T' in s:
            s = s.split('T')[0]
        if len(s) >= 10 and s[4] == '-' and s[7] == '-':
            return s[:10]
        from datetime import datetime
        formats = ['%m/%d/%Y', '%m/%d/%y', '%Y-%m-%d', '%m-%d-%Y',
                   '%Y/%m/%d', '%d-%b-%Y', '%m/%d/%Y %H:%M:%S']
        for fmt in formats:
            try:
                return datetime.strptime(s[:19], fmt).strftime('%Y-%m-%d')
            except ValueError:
                continue
        return None
