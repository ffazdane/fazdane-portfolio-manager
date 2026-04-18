"""
Strategy Grouper
Groups option legs into trade/strategy records.
Detects spreads, condors, calendars, diagonals, and custom structures.
"""

from collections import defaultdict
from datetime import datetime, timedelta
from src.database.queries import insert_trade, insert_trade_leg


# Strategy type constants
STRATEGY_TYPES = {
    'PUT_CREDIT_SPREAD': 'Put Credit Spread',
    'CALL_CREDIT_SPREAD': 'Call Credit Spread',
    'PUT_DEBIT_SPREAD': 'Put Debit Spread',
    'CALL_DEBIT_SPREAD': 'Call Debit Spread',
    'IRON_CONDOR': 'Iron Condor',
    'IRON_BUTTERFLY': 'Iron Butterfly',
    'CALENDAR_SPREAD': 'Calendar Spread',
    'DIAGONAL_SPREAD': 'Diagonal Spread',
    'SINGLE_PUT': 'Single Put',
    'SINGLE_CALL': 'Single Call',
    'CUSTOM': 'Custom Multi-Leg',
    'EQUITY': 'Stock/ETF',
}


def group_positions_into_trades(positions):
    """
    Group a list of position dicts into trade/strategy records.
    Returns list of trade dicts with nested legs.
    """
    # Group positions by account + underlying + approximate open date
    groups = defaultdict(list)

    for pos in positions:
        # Only group option positions
        if pos.get('instrument_type') in ('EQUITY',) and not pos.get('expiry'):
            key = (pos['account'], pos['broker'], pos['underlying'], pos['open_date'], 'EQUITY')
            groups[key].append(pos)
            continue

        # Group by account + broker + underlying + trade date (±1 day)
        base_date = pos.get('open_date', '')
        key = (pos['account'], pos['broker'], pos['underlying'], base_date[:10] if base_date else '')
        groups[key].append(pos)

    trades = []
    for (account, broker, underlying, base_date), group_positions in groups.items():
        # Further sub-group by date proximity
        date_groups = _group_by_date_proximity(group_positions)

        for sub_group in date_groups:
            # Separate fully closed legs from open/partially-closed legs
            closed_legs = [p for p in sub_group if p.get('is_fully_closed')]
            open_legs = [p for p in sub_group if not p.get('is_fully_closed')]

            # Create historical trade for closed legs
            if closed_legs:
                closed_trade = _identify_strategy(closed_legs, account, broker, underlying)
                if closed_trade:
                    # Ensure status reflects closed state regardless of identification
                    realized = closed_trade.get('realized_pnl', 0)
                    closed_trade['status'] = 'CLOSED_WIN' if realized >= 0 else 'CLOSED_LOSS'
                    trades.append(closed_trade)

            # Create active trade for remaining open legs
            if open_legs:
                open_trade = _identify_strategy(open_legs, account, broker, underlying)
                if open_trade:
                    trades.append(open_trade)

    return trades


def _group_by_date_proximity(positions, max_days=1):
    """Group positions that were opened within max_days of each other."""
    if not positions:
        return []

    sorted_pos = sorted(positions, key=lambda p: p.get('open_date', ''))
    groups = []
    current_group = [sorted_pos[0]]

    for pos in sorted_pos[1:]:
        prev_date = current_group[-1].get('open_date', '')
        curr_date = pos.get('open_date', '')

        try:
            prev_dt = datetime.strptime(prev_date[:10], '%Y-%m-%d')
            curr_dt = datetime.strptime(curr_date[:10], '%Y-%m-%d')
            if abs((curr_dt - prev_dt).days) <= max_days:
                current_group.append(pos)
            else:
                groups.append(current_group)
                current_group = [pos]
        except (ValueError, TypeError):
            current_group.append(pos)

    if current_group:
        groups.append(current_group)

    return groups


def _identify_strategy(positions, account, broker, underlying):
    """Identify the strategy type from a group of positions."""
    if not positions:
        return None

    # Check for equity position
    if all(not p.get('expiry') for p in positions):
        return _build_trade('EQUITY', positions, account, broker, underlying)

    # Filter to option positions only
    option_positions = [p for p in positions if p.get('expiry')]
    if not option_positions:
        return _build_trade('EQUITY', positions, account, broker, underlying)

    legs = option_positions
    num_legs = len(legs)

    # Categorize legs
    puts = [l for l in legs if l.get('put_call') == 'P']
    calls = [l for l in legs if l.get('put_call') == 'C']
    shorts = [l for l in legs if l.get('side') == 'SHORT']
    longs = [l for l in legs if l.get('side') == 'LONG']

    # Get unique expiries
    expiries = set(l.get('expiry') for l in legs if l.get('expiry'))

    if num_legs == 1:
        return _identify_single_leg(legs[0], account, broker, underlying)

    elif num_legs == 2:
        return _identify_two_leg(legs, puts, calls, shorts, longs, expiries,
                                 account, broker, underlying)

    elif num_legs == 4:
        return _identify_four_leg(legs, puts, calls, shorts, longs, expiries,
                                  account, broker, underlying)

    else:
        return _build_trade('CUSTOM', positions, account, broker, underlying)


def _identify_single_leg(leg, account, broker, underlying):
    """Identify a single-leg strategy."""
    pc = leg.get('put_call', '')
    side = leg.get('side', '')

    if pc == 'P':
        strategy = 'SINGLE_PUT'
    elif pc == 'C':
        strategy = 'SINGLE_CALL'
    else:
        strategy = 'CUSTOM'

    return _build_trade(strategy, [leg], account, broker, underlying)


def _identify_two_leg(legs, puts, calls, shorts, longs, expiries, account, broker, underlying):
    """Identify a two-leg strategy."""
    # Calendar spread: same type, same strike, different expiry
    if len(expiries) == 2 and len(puts) == 2 or len(calls) == 2:
        same_type_legs = puts if len(puts) == 2 else calls
        if len(same_type_legs) == 2:
            strikes = [l.get('strike') for l in same_type_legs]
            if strikes[0] == strikes[1]:
                return _build_trade('CALENDAR_SPREAD', legs, account, broker, underlying)

    # Diagonal spread: same type, different strike, different expiry
    if len(expiries) == 2 and (len(puts) == 2 or len(calls) == 2):
        same_type_legs = puts if len(puts) == 2 else calls
        if len(same_type_legs) == 2:
            strikes = [l.get('strike') for l in same_type_legs]
            if strikes[0] != strikes[1]:
                return _build_trade('DIAGONAL_SPREAD', legs, account, broker, underlying)

    # Vertical spread: same expiry, same type, different strikes
    if len(expiries) == 1:
        if len(puts) == 2 and len(shorts) == 1:
            # Put spread
            short_leg = [l for l in puts if l.get('side') == 'SHORT'][0]
            long_leg = [l for l in puts if l.get('side') == 'LONG'][0]
            if short_leg.get('strike', 0) > long_leg.get('strike', 0):
                return _build_trade('PUT_CREDIT_SPREAD', legs, account, broker, underlying)
            else:
                return _build_trade('PUT_DEBIT_SPREAD', legs, account, broker, underlying)

        elif len(calls) == 2 and len(shorts) == 1:
            # Call spread
            short_leg = [l for l in calls if l.get('side') == 'SHORT'][0]
            long_leg = [l for l in calls if l.get('side') == 'LONG'][0]
            if short_leg.get('strike', 0) < long_leg.get('strike', 0):
                return _build_trade('CALL_CREDIT_SPREAD', legs, account, broker, underlying)
            else:
                return _build_trade('CALL_DEBIT_SPREAD', legs, account, broker, underlying)

    return _build_trade('CUSTOM', legs, account, broker, underlying)


def _identify_four_leg(legs, puts, calls, shorts, longs, expiries, account, broker, underlying):
    """Identify a four-leg strategy."""
    # Iron Condor: 2 puts + 2 calls, same expiry, 2 short + 2 long
    if len(puts) == 2 and len(calls) == 2 and len(expiries) == 1 and len(shorts) == 2:
        short_put = [l for l in puts if l.get('side') == 'SHORT']
        long_put = [l for l in puts if l.get('side') == 'LONG']
        short_call = [l for l in calls if l.get('side') == 'SHORT']
        long_call = [l for l in calls if l.get('side') == 'LONG']

        if short_put and long_put and short_call and long_call:
            # Check if it's an iron butterfly (short strikes are the same)
            short_put_strike = short_put[0].get('strike', 0)
            short_call_strike = short_call[0].get('strike', 0)
            if short_put_strike == short_call_strike:
                return _build_trade('IRON_BUTTERFLY', legs, account, broker, underlying)
            else:
                return _build_trade('IRON_CONDOR', legs, account, broker, underlying)

    return _build_trade('CUSTOM', legs, account, broker, underlying)


def _build_trade(strategy_type, positions, account, broker, underlying):
    """Build a trade dict from positions."""
    open_dates = [p.get('open_date', '') for p in positions if p.get('open_date')]
    close_dates = [p.get('close_date', '') for p in positions if p.get('close_date')]

    # Determine if fully closed
    all_closed = all(p.get('is_fully_closed', False) for p in positions)
    any_closed = any(p.get('total_closed', 0) > 0 for p in positions)

    # Calculate entry credit/debit
    entry_total = 0
    for pos in positions:
        if pos.get('side') == 'SHORT':
            entry_total += pos.get('avg_open_price', 0) * pos.get('total_open', 0)
        else:
            entry_total -= pos.get('avg_open_price', 0) * pos.get('total_open', 0)

    # Calculate total realized P&L
    realized = sum(p.get('realized_pnl', 0) for p in positions)

    # Determine status
    if all_closed:
        status = 'CLOSED_WIN' if realized >= 0 else 'CLOSED_LOSS'
    elif any_closed:
        status = 'PARTIALLY_CLOSED'
    else:
        status = 'ACTIVE'

    # Calculate max profit/loss for defined-risk strategies
    max_profit, max_loss = _calculate_max_pnl(strategy_type, positions, entry_total)

    trade = {
        'account': account,
        'broker': broker,
        'underlying': underlying,
        'strategy_type': strategy_type,
        'open_date': min(open_dates) if open_dates else '',
        'close_date': max(close_dates) if close_dates and all_closed else None,
        'status': status,
        'entry_credit_debit': entry_total,
        'realized_pnl': realized,
        'unrealized_pnl': 0,
        'max_profit': max_profit,
        'max_loss': max_loss,
        'days_held': 0,
        'result_tag': 'WIN' if realized > 0 else 'LOSS' if realized < 0 else None,
        'legs': positions,
    }

    # Calculate days held
    if trade['open_date'] and (trade['close_date'] or not all_closed):
        try:
            open_dt = datetime.strptime(trade['open_date'][:10], '%Y-%m-%d')
            end_dt = datetime.strptime(trade['close_date'][:10], '%Y-%m-%d') if trade['close_date'] else datetime.now()
            trade['days_held'] = (end_dt - open_dt).days
        except (ValueError, TypeError):
            pass

    return trade


def _calculate_max_pnl(strategy_type, positions, entry_total):
    """Calculate max profit and max loss for a strategy."""
    multiplier = 100

    if strategy_type in ('PUT_CREDIT_SPREAD', 'CALL_CREDIT_SPREAD'):
        # Max profit = premium received
        max_profit = abs(entry_total) * multiplier if entry_total > 0 else 0
        # Max loss = spread width - premium
        strikes = sorted([p.get('strike', 0) for p in positions if p.get('strike')])
        if len(strikes) >= 2:
            spread_width = abs(strikes[-1] - strikes[0])
            qty = max(p.get('total_open', 1) for p in positions)
            max_loss = (spread_width * multiplier * qty) - max_profit
        else:
            max_loss = None
        return max_profit, max_loss

    elif strategy_type in ('PUT_DEBIT_SPREAD', 'CALL_DEBIT_SPREAD'):
        max_loss = abs(entry_total) * multiplier if entry_total < 0 else 0
        strikes = sorted([p.get('strike', 0) for p in positions if p.get('strike')])
        if len(strikes) >= 2:
            spread_width = abs(strikes[-1] - strikes[0])
            qty = max(p.get('total_open', 1) for p in positions)
            max_profit = (spread_width * multiplier * qty) - max_loss
        else:
            max_profit = None
        return max_profit, max_loss

    elif strategy_type == 'IRON_CONDOR':
        max_profit = abs(entry_total) * multiplier if entry_total > 0 else 0
        # Max loss = wider spread width - premium
        puts = [p for p in positions if p.get('put_call') == 'P']
        calls = [p for p in positions if p.get('put_call') == 'C']
        put_strikes = sorted([p.get('strike', 0) for p in puts if p.get('strike')])
        call_strikes = sorted([p.get('strike', 0) for p in calls if p.get('strike')])
        put_width = abs(put_strikes[-1] - put_strikes[0]) if len(put_strikes) >= 2 else 0
        call_width = abs(call_strikes[-1] - call_strikes[0]) if len(call_strikes) >= 2 else 0
        spread_width = max(put_width, call_width)
        qty = max(p.get('total_open', 1) for p in positions)
        max_loss = (spread_width * multiplier * qty) - max_profit
        return max_profit, max_loss

    else:
        return None, None


def save_trades_to_db(trades):
    """
    Save grouped trades and their legs to the database.
    Returns list of trade_ids created.
    """
    trade_ids = []

    for trade in trades:
        # Insert the trade record
        trade_data = {k: v for k, v in trade.items() if k != 'legs'}
        trade_id = insert_trade(trade_data)
        trade_ids.append(trade_id)

        # Insert legs
        for leg in trade.get('legs', []):
            leg_data = {
                'trade_id': trade_id,
                'symbol': leg.get('symbol', ''),
                'underlying': leg.get('underlying', ''),
                'expiry': leg.get('expiry'),
                'strike': leg.get('strike'),
                'option_type': leg.get('put_call'),
                'side': leg.get('side', 'LONG'),
                'qty_open': abs(leg.get('total_open', 0)),
                'qty_closed': abs(leg.get('total_closed', 0)),
                'entry_price': leg.get('avg_open_price', 0),
                'exit_price': leg.get('avg_close_price'),
                'status': 'CLOSED' if leg.get('is_fully_closed') else 'OPEN',
            }
            insert_trade_leg(leg_data)

    return trade_ids
