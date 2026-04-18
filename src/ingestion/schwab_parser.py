"""
Schwab CSV/Excel Parser
Parses transaction history exports from Charles Schwab.
"""

import pandas as pd
import re
from src.ingestion.base_parser import BrokerParser
from src.utils.option_symbols import parse_schwab_description, parse_occ_symbol


class SchwabParser(BrokerParser):
    """Parser for Schwab transaction files."""

    EXPECTED_COLUMNS = [
        'Date', 'Action', 'Symbol', 'Description', 'Quantity', 'Price',
        'Fees & Comm', 'Amount'
    ]

    SKIP_ACTIONS = [
        'Wire Funds', 'MoneyLink Transfer', 'Cash Dividend',
        'Qualified Dividend', 'Bank Interest', 'Journal',
        'Misc Cash Entry', 'Service Fee', 'ADR Mgmt Fee'
    ]

    def get_broker_name(self):
        return 'schwab'

    def detect(self, df):
        """Check if DataFrame has Schwab column signatures."""
        cols = [c.strip() for c in df.columns.tolist()]
        # Schwab files often have 'Fees & Comm' or 'Fees & Commission'
        has_fees_comm = any('fees' in c.lower() and 'comm' in c.lower() for c in cols)
        has_action = any('action' in c.lower() for c in cols)
        has_date = any('date' in c.lower() for c in cols)
        # Schwab doesn't have 'Type' or 'Instrument Type' like tastytrade
        has_no_type = not any('instrument type' in c.lower() for c in cols)
        return has_fees_comm and has_action and has_date and has_no_type

    def get_expected_columns(self):
        return self.EXPECTED_COLUMNS

    def parse(self, df):
        """Parse Schwab DataFrame into raw transaction dicts."""
        # Skip preamble rows (Schwab CSVs often have metadata at top)
        df = self._skip_preamble(df)

        # Normalize column names
        df.columns = [c.strip() for c in df.columns]

        # Build column map
        col_map = {}
        for expected in self.EXPECTED_COLUMNS:
            for actual in df.columns:
                if expected.lower() in actual.lower() or actual.lower() in expected.lower():
                    col_map[expected] = actual
                    break

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

    def _skip_preamble(self, df):
        """Skip metadata rows at top of Schwab CSV files."""
        # Look for the actual header row by checking for known column names
        for i in range(min(10, len(df))):
            row_values = [str(v).strip().lower() for v in df.iloc[i].values if pd.notna(v)]
            if any('action' in v for v in row_values) and any('date' in v for v in row_values):
                # This row looks like the header
                new_df = df.iloc[i+1:].copy()
                new_df.columns = [str(v).strip() for v in df.iloc[i].values]
                return new_df.reset_index(drop=True)
        return df

    def _parse_row(self, row, col_map, row_idx):
        """Parse a single Schwab row."""
        action = str(row.get(col_map.get('Action', 'Action'), '')).strip()

        # Skip non-trade actions
        if not action or action in self.SKIP_ACTIONS:
            return None
        if any(skip.lower() in action.lower() for skip in self.SKIP_ACTIONS):
            return None

        # Get basic fields
        date_str = str(row.get(col_map.get('Date', 'Date'), '')).strip()
        symbol = str(row.get(col_map.get('Symbol', 'Symbol'), '')).strip()
        description = str(row.get(col_map.get('Description', 'Description'), '')).strip()
        quantity = self._parse_number(row.get(col_map.get('Quantity', 'Quantity'), 0))
        price = self._parse_number(row.get(col_map.get('Price', 'Price'), 0))
        fees = self._parse_number(row.get(col_map.get('Fees & Comm', 'Fees & Comm'), 0))
        amount = self._parse_number(row.get(col_map.get('Amount', 'Amount'), 0))

        if not symbol or symbol == 'nan':
            return None

        # Determine if this is an option trade
        option_details = parse_schwab_description(description)
        if not option_details:
            option_details = parse_occ_symbol(symbol)
            
        if not option_details:
            from src.utils.option_symbols import parse_tastytrade_description, parse_generic_option_symbol
            option_details = parse_tastytrade_description(symbol) or parse_generic_option_symbol(symbol)

        is_option = option_details is not None or self._looks_like_option(action, description)

        # Get underlying
        if option_details:
            underlying = option_details.get('underlying', symbol)
        else:
            underlying = symbol.split()[0] if ' ' in symbol else symbol

        # Parse action into side and open/close
        side, open_close = self._parse_action(action)

        # Determine transaction type
        action_lower = action.lower()
        if 'expir' in action_lower:
            normalized_type = 'EXPIRATION'
        elif 'assign' in action_lower:
            normalized_type = 'ASSIGNMENT'
        elif 'exercis' in action_lower:
            normalized_type = 'EXERCISE'
        else:
            normalized_type = 'TRADE'

        return {
            'broker': 'schwab',
            'account': 'default',
            'date': date_str,
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
            'fees': abs(fees),
            'normalized_type': normalized_type,
            'row_index': row_idx,
        }

    def _parse_action(self, action):
        """Parse Schwab action to side and open/close."""
        action_lower = action.lower().strip()

        if 'buy to open' in action_lower:
            return 'BUY', 'OPEN'
        elif 'buy to close' in action_lower:
            return 'BUY', 'CLOSE'
        elif 'sell to open' in action_lower:
            return 'SELL', 'OPEN'
        elif 'sell to close' in action_lower:
            return 'SELL', 'CLOSE'
        elif 'buy' in action_lower:
            return 'BUY', None
        elif 'sell' in action_lower:
            return 'SELL', None
        elif 'expir' in action_lower:
            return 'SELL', 'CLOSE'  # Expired
        elif 'assign' in action_lower:
            return 'SELL', 'CLOSE'
        else:
            return action_lower.upper(), None

    def _looks_like_option(self, action, description):
        """Heuristic check if a transaction looks like an option trade."""
        combined = f"{action} {description}".lower()
        option_keywords = ['call', 'put', 'option', 'strike', 'expir']
        return any(kw in combined for kw in option_keywords)

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
