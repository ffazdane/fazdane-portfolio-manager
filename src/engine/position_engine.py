"""
Position Reconstruction Engine
Rebuilds open/closed positions from normalized transaction history.
"""

from collections import defaultdict
from datetime import datetime
from src.database.queries import get_option_transactions


def reconstruct_positions(account=None):
    """
    Reconstruct all positions from normalized transactions.
    Returns a list of position dicts grouped by symbol.
    """
    transactions = get_option_transactions(account)
    positions = defaultdict(lambda: {
        'symbol': '', 'underlying': '', 'expiry': None, 'strike': None,
        'put_call': None, 'broker': '', 'account': '',
        'net_quantity': 0, 'total_open': 0, 'total_closed': 0,
        'avg_open_price': 0, 'avg_close_price': 0,
        'open_cost': 0, 'close_proceeds': 0, 'realized_pnl': 0,
        'fees': 0, 'transactions': [], 'side': None,
    })

    for txn in transactions:
        txn = dict(txn)
        key = (txn['account'], txn['symbol'], txn.get('expiry'), txn.get('strike'), txn.get('put_call'))

        pos = positions[key]
        pos['symbol'] = txn['symbol']
        pos['underlying'] = txn['underlying']
        pos['expiry'] = txn.get('expiry')
        pos['strike'] = txn.get('strike')
        pos['put_call'] = txn.get('put_call')
        pos['broker'] = txn['broker']
        pos['account'] = txn['account']
        pos['fees'] += abs(txn.get('fees', 0))
        pos['transactions'].append(txn)

        qty = abs(txn['quantity'])
        price = txn['price']

        if txn['side'] == 'BUY':
            if txn.get('open_close_flag') == 'CLOSE':
                # Buying to close (closing a short position)
                pos['total_closed'] += qty
                pos['net_quantity'] += qty
                pos['close_proceeds'] += qty * price
            else:
                # Buying to open
                pos['total_open'] += qty
                pos['net_quantity'] += qty
                pos['open_cost'] += qty * price
        elif txn['side'] == 'SELL':
            if txn.get('open_close_flag') == 'CLOSE':
                # Selling to close (closing a long position)
                pos['total_closed'] += qty
                pos['net_quantity'] -= qty
                pos['close_proceeds'] += qty * price
            else:
                # Selling to open
                pos['total_open'] += qty
                pos['net_quantity'] -= qty
                pos['open_cost'] += qty * price

        # Handle expirations and assignments
        if txn['txn_type'] in ('EXPIRATION', 'ASSIGNMENT', 'EXERCISE'):
            pos['total_closed'] += qty
            if pos['net_quantity'] > 0:
                pos['net_quantity'] = max(0, pos['net_quantity'] - qty)
            else:
                pos['net_quantity'] = min(0, pos['net_quantity'] + qty)

    # Calculate derived fields
    result = []
    for key, pos in positions.items():
        pos['is_open'] = pos['net_quantity'] != 0
        pos['is_fully_closed'] = not pos['is_open']
        pos['is_partially_closed'] = pos['total_closed'] > 0 and pos['is_open']

        # Calculate average prices
        if pos['total_open'] > 0:
            pos['avg_open_price'] = pos['open_cost'] / pos['total_open']
        if pos['total_closed'] > 0:
            pos['avg_close_price'] = pos['close_proceeds'] / pos['total_closed']

        # Determine side (net direction)
        first_txn = pos['transactions'][0]
        if first_txn.get('open_close_flag') == 'OPEN':
            pos['side'] = 'SHORT' if first_txn['side'] == 'SELL' else 'LONG'
        else:
            pos['side'] = 'SHORT' if pos['net_quantity'] < 0 else 'LONG'

        # Calculate realized P&L for closed portions
        if pos['total_closed'] > 0:
            if pos['side'] == 'SHORT':
                # Short: profit = sell price - buy price
                pos['realized_pnl'] = (pos['avg_open_price'] - pos['avg_close_price']) * pos['total_closed'] * 100
            else:
                # Long: profit = sell price - buy price
                pos['realized_pnl'] = (pos['avg_close_price'] - pos['avg_open_price']) * pos['total_closed'] * 100
            pos['realized_pnl'] -= pos['fees']

        # Determine the trade date (first transaction date)
        pos['open_date'] = min(t['trade_date'] for t in pos['transactions'])
        if pos['is_fully_closed']:
            pos['close_date'] = max(t['trade_date'] for t in pos['transactions'])
        else:
            pos['close_date'] = None

        result.append(pos)

    return result


def get_open_positions(account=None):
    """Get only positions with open quantity."""
    all_positions = reconstruct_positions(account)
    return [p for p in all_positions if p['is_open']]


def get_closed_positions(account=None):
    """Get only fully closed positions."""
    all_positions = reconstruct_positions(account)
    return [p for p in all_positions if p['is_fully_closed']]


def get_positions_by_underlying(underlying, account=None):
    """Get all positions for a specific underlying."""
    all_positions = reconstruct_positions(account)
    return [p for p in all_positions if p['underlying'] == underlying]
