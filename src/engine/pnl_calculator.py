"""
P&L Calculator
Calculates realized P&L, unrealized P&L, max profit/loss, and return on risk.
"""

from src.database.queries import get_trade_legs, get_latest_quote
from src.utils.option_symbols import calculate_dte


def calculate_trade_pnl(trade, legs=None, quotes=None):
    """
    Calculate comprehensive P&L for a trade.
    Returns dict with all P&L metrics.
    """
    if legs is None:
        legs = get_trade_legs(trade['trade_id'])

    multiplier = 100
    result = {
        'realized_pnl': 0,
        'unrealized_pnl': 0,
        'total_pnl': 0,
        'max_profit': trade.get('max_profit'),
        'max_loss': trade.get('max_loss'),
        'pct_max_profit': None,
        'return_on_risk': None,
        'current_value': 0,
        'entry_value': 0,
    }

    total_realized = 0
    total_unrealized = 0
    total_entry_value = 0
    total_current_value = 0

    for leg in legs:
        leg = dict(leg) if not isinstance(leg, dict) else leg
        entry_price = leg.get('entry_price', 0) or 0
        exit_price = leg.get('exit_price')
        current_mark = leg.get('current_mark')
        qty_open = abs(leg.get('qty_open', 0))
        qty_closed = abs(leg.get('qty_closed', 0))
        side = leg.get('side', 'LONG')

        # Get live quote if available
        if current_mark is None and quotes:
            quote = quotes.get(leg.get('symbol'))
            if quote:
                bid = quote.get('bid', 0) or 0
                ask = quote.get('ask', 0) or 0
                current_mark = (bid + ask) / 2 if bid and ask else quote.get('option_mark', 0)

        # Realized P&L (from closed portions)
        if qty_closed > 0 and exit_price is not None:
            if side == 'SHORT':
                realized = (entry_price - exit_price) * qty_closed * multiplier
            else:
                realized = (exit_price - entry_price) * qty_closed * multiplier
            total_realized += realized

        # Unrealized P&L (from open portions)
        remaining_qty = qty_open - qty_closed
        if remaining_qty > 0 and current_mark is not None:
            if side == 'SHORT':
                unrealized = (entry_price - current_mark) * remaining_qty * multiplier
            else:
                unrealized = (current_mark - entry_price) * remaining_qty * multiplier
            total_unrealized += unrealized
            total_current_value += current_mark * remaining_qty * multiplier

        total_entry_value += entry_price * qty_open * multiplier

    result['realized_pnl'] = total_realized
    result['unrealized_pnl'] = total_unrealized
    result['total_pnl'] = total_realized + total_unrealized
    result['entry_value'] = total_entry_value
    result['current_value'] = total_current_value

    # Calculate % of max profit captured
    if result['max_profit'] and result['max_profit'] > 0:
        result['pct_max_profit'] = (result['total_pnl'] / result['max_profit']) * 100

    # Return on risk
    if result['max_loss'] and result['max_loss'] > 0:
        result['return_on_risk'] = (result['total_pnl'] / result['max_loss']) * 100

    return result


def calculate_portfolio_pnl(trades, quotes=None):
    """Calculate aggregate P&L across all trades."""
    total_realized = 0
    total_unrealized = 0
    total_premium = 0
    total_risk = 0

    for trade in trades:
        trade = dict(trade) if not isinstance(trade, dict) else trade
        total_realized += trade.get('realized_pnl', 0) or 0
        total_unrealized += trade.get('unrealized_pnl', 0) or 0
        entry = trade.get('entry_credit_debit', 0) or 0
        if entry > 0:
            total_premium += entry * 100
        total_risk += abs(trade.get('max_loss', 0) or 0)

    return {
        'total_realized': total_realized,
        'total_unrealized': total_unrealized,
        'total_pnl': total_realized + total_unrealized,
        'total_premium_sold': total_premium,
        'total_risk': total_risk,
    }
