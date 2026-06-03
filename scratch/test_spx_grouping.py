import sys
import os

sys.path.append(os.path.abspath('.'))

from src.engine.strategy_grouper import group_positions_into_trades

# Test Case 1: With broker_group (as parsed from thinkorswim Position Statement)
positions_with_groups = [
    # Iron Condor Legs (under Group "IC")
    {
        'account': 'XXX177', 'broker': 'schwab', 'underlying': 'SPX',
        'symbol': 'SPX 17 JUL 26 7900 CALL', 'instrument_type': 'OPTION',
        'expiry': '2026-07-17', 'strike': 7900.0, 'put_call': 'C', 'side': 'SHORT',
        'open_date': '2026-06-03 16:35:59', 'is_fully_closed': False, 'total_closed': 0, 'total_open': 1.0,
        'avg_open_price': 35.0, 'realized_pnl': 0, 'unrealized_pnl': 1300.0, 'broker_group': 'IC'
    },
    {
        'account': 'XXX177', 'broker': 'schwab', 'underlying': 'SPX',
        'symbol': 'SPX 17 JUL 26 7930 CALL', 'instrument_type': 'OPTION',
        'expiry': '2026-07-17', 'strike': 7930.0, 'put_call': 'C', 'side': 'LONG',
        'open_date': '2026-06-03 16:35:59', 'is_fully_closed': False, 'total_closed': 0, 'total_open': 1.0,
        'avg_open_price': 28.80, 'realized_pnl': 0, 'unrealized_pnl': -1120.0, 'broker_group': 'IC'
    },
    {
        'account': 'XXX177', 'broker': 'schwab', 'underlying': 'SPX',
        'symbol': 'SPX 17 JUL 26 7225 PUT', 'instrument_type': 'OPTION',
        'expiry': '2026-07-17', 'strike': 7225.0, 'put_call': 'P', 'side': 'SHORT',
        'open_date': '2026-06-03 16:35:59', 'is_fully_closed': False, 'total_closed': 0, 'total_open': 1.0,
        'avg_open_price': 49.55, 'realized_pnl': 0, 'unrealized_pnl': -795.0, 'broker_group': 'IC'
    },
    {
        'account': 'XXX177', 'broker': 'schwab', 'underlying': 'SPX',
        'symbol': 'SPX 17 JUL 26 7200 PUT', 'instrument_type': 'OPTION',
        'expiry': '2026-07-17', 'strike': 7200.0, 'put_call': 'P', 'side': 'LONG',
        'open_date': '2026-06-03 16:35:59', 'is_fully_closed': False, 'total_closed': 0, 'total_open': 1.0,
        'avg_open_price': 46.65, 'realized_pnl': 0, 'unrealized_pnl': 740.0, 'broker_group': 'IC'
    },
    # Vertical Legs (under Group "Unallocated")
    {
        'account': 'XXX177', 'broker': 'schwab', 'underlying': 'SPX',
        'symbol': 'SPX 17 JUL 26 7585 PUT', 'instrument_type': 'OPTION',
        'expiry': '2026-07-17', 'strike': 7585.0, 'put_call': 'P', 'side': 'LONG',
        'open_date': '2026-06-03 16:35:59', 'is_fully_closed': False, 'total_closed': 0, 'total_open': 1.0,
        'avg_open_price': 132.90, 'realized_pnl': 0, 'unrealized_pnl': 1765.0, 'broker_group': 'Unallocated'
    },
    {
        'account': 'XXX177', 'broker': 'schwab', 'underlying': 'SPX',
        'symbol': 'SPX 17 JUL 26 7455 PUT', 'instrument_type': 'OPTION',
        'expiry': '2026-07-17', 'strike': 7455.0, 'put_call': 'P', 'side': 'SHORT',
        'open_date': '2026-06-03 16:35:59', 'is_fully_closed': False, 'total_closed': 0, 'total_open': 1.0,
        'avg_open_price': 92.45, 'realized_pnl': 0, 'unrealized_pnl': -1235.0, 'broker_group': 'Unallocated'
    }
]

print("--- Testing Case 1: Grouping with broker_group ---")
trades_1 = group_positions_into_trades(positions_with_groups)
print(f"Total trades generated: {len(trades_1)}")
for t in trades_1:
    print(f"Strategy: {t['strategy_type']}, Legs: {len(t['legs'])}")
    for leg in t['legs']:
        print(f"  - {leg['symbol']} ({leg['side']})")

assert len(trades_1) == 2, f"Expected 2 trades, got {len(trades_1)}"
strategies_1 = {t['strategy_type'] for t in trades_1}
assert 'IRON_CONDOR' in strategies_1, "Expected IRON_CONDOR strategy"
assert 'PUT_DEBIT_SPREAD' in strategies_1, "Expected PUT_DEBIT_SPREAD strategy"

# Test Case 2: Without broker_group (simulating a unified custom group where we fall back to logic decomposition)
positions_no_groups = [dict(p, broker_group=None) for p in positions_with_groups]

print("\n--- Testing Case 2: Grouping WITHOUT broker_group (fallback priority decomposition) ---")
trades_2 = group_positions_into_trades(positions_no_groups)
print(f"Total trades generated: {len(trades_2)}")
for t in trades_2:
    print(f"Strategy: {t['strategy_type']}, Legs: {len(t['legs'])}")
    for leg in t['legs']:
        print(f"  - {leg['symbol']} ({leg['side']})")

assert len(trades_2) == 2, f"Expected 2 trades, got {len(trades_2)}"
strategies_2 = {t['strategy_type'] for t in trades_2}
assert 'IRON_CONDOR' in strategies_2, "Expected IRON_CONDOR strategy"
assert 'PUT_DEBIT_SPREAD' in strategies_2, "Expected PUT_DEBIT_SPREAD strategy"

print("\nALL TESTS PASSED SUCCESSFULLY!")
