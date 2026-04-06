"""
Tastytrade CSV/Excel Parser
Parses transaction history exports from tastytrade platform.
"""

import pandas as pd
import re
from src.ingestion.base_parser import BrokerParser
from src.utils.option_symbols import parse_tastytrade_description, parse_occ_symbol


class TastytradeParser(BrokerParser):
    """Parser for tastytrade transaction files."""

    EXPECTED_COLUMNS = [
        'Date', 'Type', 'Action', 'Symbol', 'Instrument Type',
        'Description', 'Quantity', 'Price', 'Amount'
    ]

    TRADE_TYPES = ['Trade', 'Receive Deliver']
    EXPIRATION_TYPES = ['Expiration']
    ASSIGNMENT_TYPES = ['Assignment', 'Exercise']
    SKIP_TYPES = ['Money Movement', 'Dividend', 'Interest', 'Transfer', 'Fee']

    def get_broker_name(self):
        return 'tastytrade'

    def detect(self, df):
        """Check if DataFrame has tastytrade column signatures."""
        cols = [c.strip() for c in df.columns.tolist()]
        required = ['Date', 'Type', 'Action', 'Symbol']
        # Check if at least 3 of the required columns are present
        matches = sum(1 for r in required if any(r.lower() == c.lower() for c in cols))
        return matches >= 3

    def get_expected_columns(self):
        return self.EXPECTED_COLUMNS

    def parse(self, df):
        """Parse tastytrade DataFrame into raw transaction dicts."""
        # Normalize column names
        df.columns = [c.strip() for c in df.columns]

        # Column name mapping (case-insensitive)
        col_map = {}
        for expected in self.EXPECTED_COLUMNS:
            for actual in df.columns:
                if actual.lower() == expected.lower():
                    col_map[expected] = actual
                    break

        transactions = []

        for idx, row in df.iterrows():
            try:
                txn = self._parse_row(row, col_map, idx)
                if txn:
                    transactions.append(txn)
            except Exception as e:
                # Log but continue parsing
                print(f"Warning: Skipping row {idx}: {e}")
                continue

        return transactions

    def _parse_row(self, row, col_map, row_idx):
        """Parse a single row into a transaction dict."""
        # Get transaction type
        txn_type = str(row.get(col_map.get('Type', 'Type'), '')).strip()

        # Skip non-trade types
        if txn_type in self.SKIP_TYPES or not txn_type:
            return None

        # Get basic fields
        date_str = str(row.get(col_map.get('Date', 'Date'), '')).strip()
        action = str(row.get(col_map.get('Action', 'Action'), '')).strip()
        symbol = str(row.get(col_map.get('Symbol', 'Symbol'), '')).strip()
        instrument_type = str(row.get(col_map.get('Instrument Type', 'Instrument Type'), '')).strip()
        description = str(row.get(col_map.get('Description', 'Description'), '')).strip()
        quantity = self._parse_number(row.get(col_map.get('Quantity', 'Quantity'), 0))
        price = self._parse_number(row.get(col_map.get('Price', 'Price'), 0))
        amount = self._parse_number(row.get(col_map.get('Amount', 'Amount'), 0))

        # Get fees and commission
        fees = self._parse_number(row.get(col_map.get('Fees', 'Fees'), 0))
        commission = self._parse_number(row.get('Commission', 0))
        total_fees = abs(fees) + abs(commission)

        # Get account number if available
        account = str(row.get(col_map.get('Account Number', 'Account Number'), 
                     row.get('Account', ''))).strip()
        if not account or account == 'nan':
            account = 'default'

        # Parse option details
        option_details = None
        is_option = instrument_type.lower() in ['equity option', 'option', 'equity_option']

        if is_option:
            # Try parsing from description
            option_details = parse_tastytrade_description(description)
            if not option_details and symbol:
                option_details = parse_occ_symbol(symbol)

        # Determine underlying
        if option_details:
            underlying = option_details.get('underlying', symbol)
        elif is_option and symbol:
            # Try to extract underlying from symbol
            underlying = re.match(r'^([A-Z]{1,6})', symbol)
            underlying = underlying.group(1) if underlying else symbol
        else:
            underlying = symbol

        # Determine side and open/close
        side, open_close = self._parse_action(action)

        # Map transaction type
        if txn_type in self.TRADE_TYPES:
            normalized_type = 'TRADE'
        elif txn_type in self.EXPIRATION_TYPES:
            normalized_type = 'EXPIRATION'
        elif txn_type in self.ASSIGNMENT_TYPES:
            normalized_type = 'ASSIGNMENT' if 'assignment' in txn_type.lower() else 'EXERCISE'
        else:
            normalized_type = 'TRADE'

        return {
            'broker': 'tastytrade',
            'account': account,
            'date': date_str,
            'type': txn_type,
            'action': action,
            'symbol': symbol,
            'instrument_type': 'EQUITY_OPTION' if is_option else 'EQUITY',
            'description': description,
            'underlying': underlying,
            'expiry': option_details.get('expiry') if option_details else None,
            'strike': option_details.get('strike') if option_details else None,
            'put_call': option_details.get('put_call') if option_details else None,
            'side': side,
            'open_close': open_close,
            'quantity': abs(quantity) if quantity else 0,
            'price': price,
            'amount': amount,
            'fees': total_fees,
            'normalized_type': normalized_type,
            'row_index': row_idx,
        }

    def _parse_action(self, action):
        """Parse action string into side and open/close."""
        action_lower = action.lower().strip()

        if 'buy' in action_lower and 'open' in action_lower:
            return 'BUY', 'OPEN'
        elif 'buy' in action_lower and 'close' in action_lower:
            return 'BUY', 'CLOSE'
        elif 'sell' in action_lower and 'open' in action_lower:
            return 'SELL', 'OPEN'
        elif 'sell' in action_lower and 'close' in action_lower:
            return 'SELL', 'CLOSE'
        elif 'buy' in action_lower:
            return 'BUY', None
        elif 'sell' in action_lower:
            return 'SELL', None
        else:
            return action.upper(), None

    def _parse_number(self, value):
        """Parse a number from various formats."""
        if value is None or (isinstance(value, str) and value.strip() == ''):
            return 0
        try:
            if isinstance(value, str):
                value = value.replace(',', '').replace('$', '').replace('(', '-').replace(')', '').strip()
            return float(value)
        except (ValueError, TypeError):
            return 0
