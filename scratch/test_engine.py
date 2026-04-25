import sys
import os

sys.path.append(os.path.abspath('.'))

from src.engine.strategy_grouper import group_positions_into_trades

positions = [
    {
        'account': 'default',
        'broker': 'schwab',
        'underlying': 'NFLX',
        'symbol': 'NFLX 04/24/2026 560.0 CALL',
        'instrument_type': 'EQUITY_OPTION',
        'expiry': '2026-04-24',
        'strike': 560.0,
        'put_call': 'C',
        'side': 'SHORT',
        'open_date': '2026-04-02',
        'is_fully_closed': False,
        'total_closed': 0,
        'total_open': 5,
        'avg_open_price': 1.21,
        'realized_pnl': 0
    },
    {
        'account': 'default',
        'broker': 'schwab',
        'underlying': 'NFLX',
        'symbol': 'NFLX 05/15/2026 580.0 CALL',
        'instrument_type': 'EQUITY_OPTION',
        'expiry': '2026-05-15',
        'strike': 580.0,
        'put_call': 'C',
        'side': 'LONG',
        'open_date': '2026-04-02',
        'is_fully_closed': False,
        'total_closed': 0,
        'total_open': 5,
        'avg_open_price': 2.02,
        'realized_pnl': 0
    }
]

trades = group_positions_into_trades(positions)
for t in trades:
    print("Trade Strategy:", t['strategy_type'])
    print("Trade Status:", t['status'])
    print("Legs:", len(t['legs']))
