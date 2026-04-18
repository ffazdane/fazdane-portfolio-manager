"""
Excel Leg Detail Parser
Flexible parser for Excel files containing option leg details.
Auto-detects column mapping from headers.
"""

import pandas as pd
import re
from src.ingestion.base_parser import BrokerParser
from src.utils.option_symbols import parse_occ_symbol, parse_tastytrade_description, parse_schwab_description


class ExcelLegParser(BrokerParser):
    """
    Generic Excel parser that auto-detects column mappings.
    Handles leg-detail format files from any broker.
    """

    # Mapping of canonical field names to possible column header patterns
    COLUMN_PATTERNS = {
        'date': [r'date', r'trade.?date', r'execution.?date', r'trans.?date', r'time'],
        'account': [r'account', r'acct', r'account.?number', r'account.?#'],
        'symbol': [r'^symbol$', r'option.?symbol', r'contract', r'instrument'],
        'underlying': [r'underlying', r'root', r'ticker', r'stock'],
        'action': [r'action', r'side', r'buy.?sell', r'direction', r'type'],
        'quantity': [r'quantity', r'qty', r'contracts', r'size', r'count'],
        'price': [r'^price$', r'fill.?price', r'exec.?price', r'trade.?price', r'avg.?price'],
        'strike': [r'strike', r'strike.?price'],
        'expiry': [r'expir', r'exp.?date', r'expiration'],
        'put_call': [r'put.?call', r'option.?type', r'call.?put', r'^type$', r'^p/?c$'],
        'description': [r'desc', r'description', r'instrument.?desc'],
        'fees': [r'fee', r'commission', r'comm'],
        'amount': [r'amount', r'total', r'net.?amount', r'value', r'proceeds'],
        'open_close': [r'open.?close', r'opening.?closing', r'position.?effect'],
        'strategy': [r'strategy', r'spread', r'order.?type'],
        'broker': [r'broker', r'source', r'platform'],
    }

    def get_broker_name(self):
        return 'excel_import'

    def detect(self, df):
        """
        Excel leg parser is the fallback - detect if the file has
        recognizable option-related columns.
        """
        cols = [c.strip().lower() for c in df.columns.tolist()]
        option_indicators = ['strike', 'expir', 'put', 'call', 'option', 'spread', 'leg']
        return any(any(ind in c for ind in option_indicators) for c in cols)

    def get_expected_columns(self):
        return list(self.COLUMN_PATTERNS.keys())

    def parse(self, df):
        """Parse Excel DataFrame using auto-detected column mappings."""
        col_map = self._auto_map_columns(df)
        transactions = []

        for idx, row in df.iterrows():
            try:
                txn = self._parse_row(row, col_map, idx)
                if txn:
                    transactions.append(txn)
            except Exception as e:
                print(f"Warning: Skipping row {idx}: {e}")
                continue

        return transactions

    def _auto_map_columns(self, df):
        """Auto-detect column mappings using pattern matching."""
        col_map = {}
        df_cols = df.columns.tolist()

        for field, patterns in self.COLUMN_PATTERNS.items():
            for col in df_cols:
                col_lower = str(col).strip().lower()
                for pattern in patterns:
                    if re.search(pattern, col_lower):
                        col_map[field] = col
                        break
                if field in col_map:
                    break

        return col_map

    def _parse_row(self, row, col_map, row_idx):
        """Parse a single row using the detected column mapping."""
        # Get values using the mapped columns
        date_str = self._get_val(row, col_map, 'date', '')
        account = self._get_val(row, col_map, 'account', 'default')
        symbol = self._get_val(row, col_map, 'symbol', '')
        underlying = self._get_val(row, col_map, 'underlying', '')
        action = self._get_val(row, col_map, 'action', '')
        quantity = self._parse_number(self._get_val(row, col_map, 'quantity', 0))
        price = self._parse_number(self._get_val(row, col_map, 'price', 0))
        strike = self._parse_number(self._get_val(row, col_map, 'strike', None))
        expiry = self._get_val(row, col_map, 'expiry', None)
        put_call = self._get_val(row, col_map, 'put_call', None)
        description = self._get_val(row, col_map, 'description', '')
        fees = abs(self._parse_number(self._get_val(row, col_map, 'fees', 0)))
        amount = self._parse_number(self._get_val(row, col_map, 'amount', 0))
        open_close = self._get_val(row, col_map, 'open_close', None)
        broker = self._get_val(row, col_map, 'broker', 'excel_import')

        # Skip empty rows
        if not symbol and not underlying and not description:
            return None
        if not date_str:
            return None

        # Try to extract option details from description or symbol if not directly available
        if not strike or not expiry:
            from src.utils.option_symbols import parse_generic_option_symbol
            option_details = None
            if description:
                option_details = parse_tastytrade_description(description) or parse_schwab_description(description)
            if not option_details and symbol:
                option_details = parse_tastytrade_description(symbol) or parse_generic_option_symbol(symbol) or parse_schwab_description(symbol) or parse_occ_symbol(symbol)
                
            if option_details:
                strike = strike or option_details.get('strike')
                expiry = expiry or option_details.get('expiry')
                put_call = put_call or option_details.get('put_call')
                underlying = underlying or option_details.get('underlying')

        # Determine if option
        is_option = strike is not None and expiry is not None

        # Clean up underlying
        if not underlying and symbol:
            underlying = re.match(r'^([A-Z]{1,6})', str(symbol).strip())
            underlying = underlying.group(1) if underlying else symbol

        # Normalize expiry format
        if expiry:
            expiry = self._normalize_date(str(expiry))

        # Normalize put/call
        if put_call:
            pc = str(put_call).strip().upper()
            if pc in ['P', 'PUT']:
                put_call = 'P'
            elif pc in ['C', 'CALL']:
                put_call = 'C'

        # Parse action
        side, oc = self._parse_action(str(action))
        if not open_close and oc:
            open_close = oc

        return {
            'broker': broker if broker != 'nan' else 'excel_import',
            'account': str(account) if str(account) != 'nan' else 'default',
            'date': self._normalize_date(str(date_str)),
            'action': action,
            'symbol': symbol,
            'instrument_type': 'EQUITY_OPTION' if is_option else 'EQUITY',
            'description': description,
            'underlying': underlying or symbol,
            'expiry': expiry,
            'strike': strike,
            'put_call': put_call,
            'side': side,
            'open_close': open_close.upper() if open_close else None,
            'quantity': abs(quantity) if quantity else 0,
            'price': price,
            'amount': amount,
            'fees': fees,
            'normalized_type': 'TRADE',
            'row_index': row_idx,
        }

    def _get_val(self, row, col_map, field, default):
        """Get a value from the row using the column mapping."""
        col = col_map.get(field)
        if col is None:
            return default
        val = row.get(col, default)
        if pd.isna(val):
            return default
        return val

    def _parse_action(self, action):
        """Parse action into side and open/close."""
        action_lower = action.lower().strip()
        if 'buy' in action_lower and 'open' in action_lower:
            return 'BUY', 'OPEN'
        elif 'buy' in action_lower and 'close' in action_lower:
            return 'BUY', 'CLOSE'
        elif 'sell' in action_lower and 'open' in action_lower:
            return 'SELL', 'OPEN'
        elif 'sell' in action_lower and 'close' in action_lower:
            return 'SELL', 'CLOSE'
        elif 'buy' in action_lower or 'long' in action_lower:
            return 'BUY', None
        elif 'sell' in action_lower or 'short' in action_lower:
            return 'SELL', None
        return 'BUY', None

    def _normalize_date(self, date_str):
        """Normalize various date formats to YYYY-MM-DD."""
        if not date_str or date_str == 'None' or date_str == 'nan':
            return None
        from datetime import datetime
        formats = [
            '%Y-%m-%d', '%m/%d/%Y', '%m/%d/%y', '%m-%d-%Y',
            '%Y/%m/%d', '%d-%b-%Y', '%b %d, %Y', '%B %d, %Y',
            '%Y-%m-%d %H:%M:%S', '%m/%d/%Y %H:%M:%S',
        ]
        for fmt in formats:
            try:
                return datetime.strptime(date_str.strip()[:19], fmt).strftime('%Y-%m-%d')
            except ValueError:
                continue
        return date_str

    def _parse_number(self, value):
        """Parse a number from various formats."""
        if value is None or (isinstance(value, str) and value.strip() in ['', 'nan', 'None']):
            return None
        try:
            if isinstance(value, str):
                value = value.replace(',', '').replace('$', '').replace('(', '-').replace(')', '').strip()
            result = float(value)
            return result if not pd.isna(result) else None
        except (ValueError, TypeError):
            return None
