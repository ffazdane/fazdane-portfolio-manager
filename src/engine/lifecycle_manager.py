"""
Trade Lifecycle Manager
Manages trade status transitions. Never deletes records.
"""

from datetime import datetime, date
from src.database.queries import (
    update_trade, get_trade_by_id, get_trade_legs,
    get_active_trades, update_trade_leg
)
from src.utils.option_symbols import calculate_dte

# Status categories
OPEN_RISK_STATUSES = ['ACTIVE', 'PARTIALLY_CLOSED', 'ADJUSTED', 'ROLLED_OPEN']
HISTORICAL_STATUSES = [
    'CLOSED_WIN', 'CLOSED_LOSS', 'EXPIRED_WORTHLESS',
    'ASSIGNED_RESOLVED', 'EXERCISED_RESOLVED', 'ROLLED_HISTORICAL'
]


def is_open_risk(status):
    """Check if a status indicates open risk."""
    return status in OPEN_RISK_STATUSES


def is_historical(status):
    """Check if a status is historical."""
    return status in HISTORICAL_STATUSES


def transition_trade_status(trade_id, new_status, realized_pnl=None):
    """
    Transition a trade to a new status.
    Validates the transition is allowed.
    """
    trade = get_trade_by_id(trade_id)
    if not trade:
        raise ValueError(f"Trade {trade_id} not found")

    current_status = trade['status']

    # Validate transition
    if not _is_valid_transition(current_status, new_status):
        raise ValueError(
            f"Invalid transition from {current_status} to {new_status}"
        )

    updates = {'status': new_status}

    # Set close date for historical transitions
    if is_historical(new_status) and not trade['close_date']:
        updates['close_date'] = datetime.now().strftime('%Y-%m-%d')

    # Calculate days held
    if updates.get('close_date') and trade['open_date']:
        try:
            open_dt = datetime.strptime(trade['open_date'][:10], '%Y-%m-%d')
            close_dt = datetime.strptime(updates['close_date'][:10], '%Y-%m-%d')
            updates['days_held'] = (close_dt - open_dt).days
        except (ValueError, TypeError):
            pass

    # Set realized P&L
    if realized_pnl is not None:
        updates['realized_pnl'] = realized_pnl

    # Set result tag
    if new_status in ('CLOSED_WIN', 'EXPIRED_WORTHLESS'):
        updates['result_tag'] = 'WIN'
    elif new_status == 'CLOSED_LOSS':
        updates['result_tag'] = 'LOSS'

    update_trade(trade_id, updates)
    return True


def _is_valid_transition(current, new):
    """Check if a status transition is valid."""
    # Can always go to the same status
    if current == new:
        return True

    # From open-risk statuses
    if current in OPEN_RISK_STATUSES:
        return True  # Can go to any status from open risk

    # From historical statuses - generally not allowed
    if current in HISTORICAL_STATUSES:
        # Allow reopening if needed (rare case)
        return new in OPEN_RISK_STATUSES

    return False


def check_and_update_expired_trades():
    """
    Check all active trades for expired legs and update statuses.
    Should be called periodically or after market data refresh.
    """
    active_trades = get_active_trades()
    updated = []

    for trade in active_trades:
        trade_id = trade['trade_id']
        legs = get_trade_legs(trade_id)

        all_expired = True
        all_closed = True
        any_expired = False
        any_closed = False

        for leg in legs:
            dte = calculate_dte(leg['expiry'])

            if dte is not None and dte <= 0 and leg['status'] == 'OPEN':
                # Leg has expired
                update_trade_leg(leg['leg_id'], {
                    'status': 'EXPIRED',
                    'qty_closed': leg['qty_open'],
                    'exit_price': 0
                })
                any_expired = True
            elif leg['status'] == 'OPEN':
                all_expired = False
                all_closed = False
            elif leg['status'] in ('CLOSED', 'EXPIRED', 'ASSIGNED'):
                any_closed = True
            else:
                all_expired = False
                all_closed = False

        # Update trade status based on leg states
        if all_expired:
            transition_trade_status(trade_id, 'EXPIRED_WORTHLESS')
            updated.append(trade_id)
        elif all_closed or (all_expired and any_closed):
            # Determine win/loss
            pnl = trade['realized_pnl'] or 0
            if pnl >= 0:
                transition_trade_status(trade_id, 'CLOSED_WIN', pnl)
            else:
                transition_trade_status(trade_id, 'CLOSED_LOSS', pnl)
            updated.append(trade_id)
        elif any_closed and not all_closed:
            if trade['status'] == 'ACTIVE':
                transition_trade_status(trade_id, 'PARTIALLY_CLOSED')
                updated.append(trade_id)

    return updated


def process_roll(original_trade_id, new_trade_id, roll_group_id=None):
    """
    Process a roll: mark original as ROLLED_HISTORICAL,
    link new trade as ROLLED_OPEN with parent reference.
    """
    # Mark original trade as rolled
    transition_trade_status(original_trade_id, 'ROLLED_HISTORICAL')

    # Link the new trade
    if not roll_group_id:
        roll_group_id = f"roll_{original_trade_id}"

    update_trade(new_trade_id, {
        'parent_trade_id': original_trade_id,
        'roll_group_id': roll_group_id,
        'status': 'ROLLED_OPEN',
    })

    update_trade(original_trade_id, {
        'roll_group_id': roll_group_id,
    })
