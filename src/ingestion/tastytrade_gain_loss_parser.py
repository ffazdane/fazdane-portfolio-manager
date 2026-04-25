"""
TastyTrade Gain/Loss Tax Worksheet Parser
Parses the 42-column tax worksheet export from TastyTrade (via Apex Clearing).

File naming: YYYY-AccountNumber-gain_loss_tax_worksheet.csv

Handles ANY column naming convention from Apex Clearing —
spaces, slashes, mixed-case are all normalised internally.

Examples of real column names we handle:
  "Gain/Loss"        → GAIN_LOSS
  "Date Sold"        → DATE_SOLD
  "Sales Price"      → SALES_PRICE
  "Cost Basis"       → COST_BASIS
  "Date Acquired"    → DATE_ACQUIRED
  "Wash Sale Disallowed" → WASH_SALE_DISALLOWED
"""

import re
import pandas as pd
from src.ingestion.base_parser import BrokerParser
from src.utils.option_symbols import parse_occ_symbol


def _normalise_col(name: str) -> str:
    """
    Normalise a column header to UPPER_SNAKE_CASE for robust matching.
    e.g.  "Gain/Loss"         → "GAIN_LOSS"
          "Date Sold"         → "DATE_SOLD"
          "Sales Price"       → "SALES_PRICE"
          "WASH_SALE"         → "WASH_SALE"
    """
    s = str(name).strip().upper()
    s = re.sub(r'[^A-Z0-9]+', '_', s)   # replace any non-alnum run with _
    s = s.strip('_')
    return s


class TastytradeGainLossParser(BrokerParser):
    """
    Parser for TastyTrade gain/loss tax worksheet (Apex Clearing format).
    Works regardless of column casing, spaces, or delimiter style.
    """

    def get_broker_name(self):
        return 'tastytrade'

    def get_expected_columns(self):
        return ['SYMBOL', 'QUANTITY', 'DATE_ACQUIRED', 'DATE_SOLD',
                'SALES_PRICE', 'COST_BASIS', 'GAIN_LOSS']

    # ── Detection ────────────────────────────────────────────────────────────
    def detect(self, df):
        """
        Detect the gain/loss worksheet format.
        After normalising column headers, look for the key financial fields.
        """
        norm_cols = {_normalise_col(c) for c in df.columns}

        # Must have at least a 'gain/loss' column and a 'date sold' / 'close date' column
        has_gain_loss = any(c in norm_cols for c in (
            'GAIN_LOSS', 'GAIN', 'NET_G_L', 'NET_GAIN_LOSS',
            'NO_WS_GAIN_LOSS', 'NO_WS_GL', 'NO_WS_G',           # Apex Clearing variants
        ) or any(c.startswith('NO_WS_G') for c in norm_cols))   # catch NO_WS_GAIN_LOSS etc.
        has_date_sold = any(c in norm_cols for c in (
            'DATE_SOLD', 'CLOSED', 'CLOSE_DATE', 'SALE_DATE',
            'DATE_OF_TRANSACTION', 'CLOSE_DT',
        ))
        has_symbol    = any(c in norm_cols for c in ('SYMBOL', 'TICKER', 'SECURITY', 'SECNO'))

        return has_date_sold and has_symbol  # gain_loss optional for detection

    # ── Main parse ───────────────────────────────────────────────────────────
    def parse(self, df):
        """Parse the gain/loss worksheet DataFrame into broker_transactions dicts."""
        df = df.copy()

        # Build normalised_col → original_col map so we can access by normalised name
        norm_to_orig = {}
        for col in df.columns:
            norm_to_orig[_normalise_col(col)] = col

        transactions = []
        for idx, row in df.iterrows():
            try:
                txn = self._parse_row(row, norm_to_orig)
                if txn:
                    transactions.append(txn)
            except Exception as e:
                print(f"Warning: Skipping gain/loss row {idx}: {e}")
                continue

        return transactions

    # ── Row parsing ──────────────────────────────────────────────────────────
    def _g(self, row, norm_to_orig, *norm_keys, default=None):
        """
        Get a value from a row using normalised column keys.
        Tries each key in order; returns first non-null match.
        """
        for nk in norm_keys:
            orig = norm_to_orig.get(nk)
            if orig is None:
                continue
            try:
                val = row[orig]
                if val is not None and str(val).strip().lower() not in ('', 'nan', 'none'):
                    return val
            except (KeyError, TypeError):
                continue
        return default

    def _parse_row(self, row, norm_to_orig):
        """Parse one row of the gain/loss worksheet using normalised column names."""

        # ── Core identifiers ──────────────────────────────────────────────
        symbol = str(self._g(row, norm_to_orig,
                              'SYMBOL', 'TICKER', 'SECURITY_SYMBOL', 'SECNO',
                              default='') or '').strip()
        if not symbol or symbol.upper() in ('NAN', 'NONE', ''):
            return None

        description = str(self._g(row, norm_to_orig,
                                   'DESCRIPTION', 'TRANS_DESCRIPTION', 'SECURITY_DESCRIPTION',
                                   default='') or '').strip()

        quantity = self._parse_number(self._g(row, norm_to_orig,
                                               'QUANTITY', 'QTY', 'SHARES', default=0))

        account_num = str(self._g(row, norm_to_orig,
                                   'ACCOUNT_NUMBER', 'ACCOUNT', 'ACCT_NO',
                                   default='default') or 'default').strip()

        # ── Dates ─────────────────────────────────────────────────────────
        date_sold = self._normalise_date(self._g(row, norm_to_orig,
                                                  'CLOSE_DATE', 'DATE_SOLD', 'CLOSED',
                                                  'SALE_DATE', 'CLOSE_DT',
                                                  'DATE_OF_TRANSACTION'))
        if not date_sold:
            return None   # Must have a close date to be meaningful

        date_acquired = self._normalise_date(self._g(row, norm_to_orig,
                                                      'OPEN_DATE', 'DATE_ACQUIRED',
                                                      'PURCHASE_DATE', 'LOT_DATE', 'OPEN_DT'))

        # ── Financials (Apex Clearing uses NO_WS_ prefix = "no wash sale" adjusted) ───
        # Try Apex NO_WS_ variants first, then fallback to generic names
        sales_price = self._parse_number(self._g(row, norm_to_orig,
                                                  'NO_WS_PROCEEDS', 'SALES_PRICE', 'PROCEEDS',
                                                  'GROSS_PROCEEDS', 'SALES_PROCEEDS',
                                                  'SALES', default=0))
        cost_basis  = self._parse_number(self._g(row, norm_to_orig,
                                                  'NO_WS_COST', 'COST_BASIS',
                                                  'ADJUSTED_COST_BASIS', 'COST', default=0))
        # For gain/loss: try every NO_WS_G* column dynamically
        gain_loss_raw = self._g(row, norm_to_orig,
                                'NO_WS_GAIN_LOSS', 'NO_WS_GL', 'NO_WS_G',
                                'GAIN_LOSS', 'GAIN', 'NET_GAIN_LOSS', 'NET_G_L',
                                'REALIZED_GAIN_LOSS', default=None)
        # Fallback: find any column starting with NO_WS_G
        if gain_loss_raw is None:
            for nk, orig in norm_to_orig.items():
                if nk.startswith('NO_WS_G'):
                    v = self._g(row, norm_to_orig, nk, default=None)
                    if v is not None:
                        gain_loss_raw = v
                        break
        gain_loss   = self._parse_number(gain_loss_raw)
        wash_sale   = self._parse_number(self._g(row, norm_to_orig,
                                                  'WS_DISALLOWED', 'WASH_SALE',
                                                  'WASH_SALE_DISALLOWED',
                                                  'WASH_SALE_LOSS_DISALLOWED', default=0))
        federal_wh  = self._parse_number(self._g(row, norm_to_orig,
                                                  'FEDERAL_TAX_WITHHELD',
                                                  'FED_WITHHOLDING', default=0))

        # ── Option parsing ─────────────────────────────────────────────────
        opt_details = parse_occ_symbol(symbol)
        if not opt_details:
            opt_details = self._parse_description_for_option(description)

        if opt_details:
            underlying = opt_details.get('underlying', symbol)
            expiry     = opt_details.get('expiry')
            put_call   = opt_details.get('put_call')
            strike     = opt_details.get('strike')
            instrument = 'EQUITY_OPTION'
        else:
            underlying = symbol
            expiry     = None
            put_call   = None
            strike     = None
            instrument = 'EQUITY'

        # ── Term / type ───────────────────────────────────────────────────
        term    = str(self._g(row, norm_to_orig,
                               'LONG_SHORT_IND', 'TERM', 'HOLDING_PERIOD',
                               default='') or '').strip().upper()
        tx_type = str(self._g(row, norm_to_orig,
                               'CLOSE_EVENT', 'TRANS_TYPE', 'TRANSACTION_TYPE',
                               'TYPE', 'REPORTING_CATEGORY', default='TRADE') or 'TRADE').strip()

        tx_lower = tx_type.lower()
        if 'expir' in tx_lower:
            normalized_type = 'EXPIRATION'
        elif 'assign' in tx_lower:
            normalized_type = 'ASSIGNMENT'
        elif 'exercis' in tx_lower:
            normalized_type = 'EXERCISE'
        else:
            normalized_type = 'TRADE'

        # ── Price per share/contract ───────────────────────────────────────
        qty = abs(quantity) if quantity else 0
        if qty > 0 and instrument == 'EQUITY_OPTION':
            unit_price = sales_price / (qty * 100)
        elif qty > 0:
            unit_price = sales_price / qty
        else:
            unit_price = 0.0

        return {
            'broker':          'tastytrade',
            'account':         account_num,
            'date':            date_sold,
            'date_acquired':   date_acquired,
            'symbol':          symbol,
            'underlying':      underlying,
            'description':     description,
            'expiry':          expiry,
            'strike':          strike,
            'put_call':        put_call,
            'instrument_type': instrument,
            'quantity':        qty,
            'price':           unit_price,
            'amount':          sales_price,
            'cost_basis':      cost_basis,
            'gain_loss':       gain_loss,
            'wash_sale':       wash_sale,
            'fees':            abs(federal_wh),
            'open_close':      'CLOSE',
            'normalized_type': normalized_type,
            'term':            term,
            'side':            'SELL',
            'type':            tx_type,
            'source_file_name': '',
        }

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _parse_number(self, value):
        """Parse a number from any format. Always returns float — never NaN or None."""
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
            # pandas NA / numpy NaN
            import pandas as pd
            if pd.isna(value):
                return 0.0
            return float(value)
        except (ValueError, TypeError):
            return 0.0

    def _normalise_date(self, value):
        """Normalise any date format to YYYY-MM-DD."""
        if not value:
            return None
        s = str(value).strip()
        if not s or s.lower() in ('nan', 'none', ''):
            return None
        # Already YYYY-MM-DD
        if len(s) >= 10 and s[4] == '-' and s[7] == '-':
            return s[:10]
        from datetime import datetime
        formats = [
            '%m/%d/%Y', '%m/%d/%y', '%Y-%m-%d', '%m-%d-%Y',
            '%Y/%m/%d', '%d-%b-%Y', '%b %d, %Y', '%B %d, %Y',
            '%m/%d/%Y %H:%M:%S', '%Y-%m-%d %H:%M:%S',
        ]
        for fmt in formats:
            try:
                return datetime.strptime(s[:19], fmt).strftime('%Y-%m-%d')
            except ValueError:
                continue
        return s[:10] if len(s) >= 10 else None

    def _parse_description_for_option(self, description):
        """Extract option details from a human-readable description string."""
        if not description:
            return None
        patterns = [
            r'(?P<sym>[A-Z]{1,6})\s+(?P<date>\d{1,2}/\d{1,2}/\d{4})\s+(?P<strike>[\d.]+)\s*(?P<pc>[CP])',
            r'(?P<sym>[A-Z]{1,6})\s+(?P<strike>[\d.]+)(?P<pc>[CP])\s+(?P<date>\d{1,2}/\d{1,2}/\d{4})',
        ]
        for pat in patterns:
            m = re.search(pat, description.upper())
            if m:
                from datetime import datetime
                try:
                    expiry = datetime.strptime(m.group('date'), '%m/%d/%Y').strftime('%Y-%m-%d')
                    return {
                        'underlying': m.group('sym'),
                        'expiry':     expiry,
                        'strike':     float(m.group('strike')),
                        'put_call':   m.group('pc'),
                    }
                except Exception:
                    pass
        return None

