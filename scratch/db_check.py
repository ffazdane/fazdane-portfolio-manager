import sys
import os
sys.path.append(os.path.abspath('.'))

from src.database.queries import get_active_trades, get_all_normalized_transactions, get_option_transactions

print("--- Normalized Transactions for NFLX ---")
txns = get_all_normalized_transactions(underlying='NFLX')
print(f"Count: {len(txns)}")
for t in txns:
    print(dict(t))

print("\n--- Active Trades for NFLX ---")
trades = get_active_trades()
nflx_trades = [t for t in trades if t['underlying'] == 'NFLX']
print(f"Count: {len(nflx_trades)}")
for t in nflx_trades:
    print(dict(t))

print("\n--- Option Transactions ---")
opt_txns = get_option_transactions()
nflx_opts = [t for t in opt_txns if t['underlying'] == 'NFLX']
print(f"Count: {len(nflx_opts)}")
for t in nflx_opts:
    print(dict(t))
