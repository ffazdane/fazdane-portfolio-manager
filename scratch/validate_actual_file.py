import sys
import os
import pandas as pd
import io

sys.path.append(os.path.abspath('.'))

from src.ingestion.position_parser import parse_position_file
from src.engine.strategy_grouper import group_positions_into_trades

# Path to the actual file
file_path = r"C:\Users\ffazd\Downloads\Portfolio\2026-06-03-PositionStatement.csv"

print(f"Reading file: {file_path}")
with open(file_path, "r", encoding="utf-8", errors="replace") as f:
    raw_text = f.read()

# Pad rows to maximum column count to create a valid DataFrame, simulating views/imports.py
import csv
raw_lines = raw_text.splitlines()
parsed_rows = list(csv.reader(raw_lines))
max_cols = max(len(r) for r in parsed_rows) if parsed_rows else 0
padded_rows = [r + [''] * (max_cols - len(r)) for r in parsed_rows]
df = pd.DataFrame(padded_rows)

print("Parsing positions...")
positions, broker, account = parse_position_file(
    df,
    "2026-06-03-PositionStatement.csv",
    raw_text=raw_text
)

print(f"Successfully parsed {len(positions)} positions from broker: {broker}, account: {account}")

# Filter SPX positions
spx_positions = [p for p in positions if p['underlying'] == 'SPX']
print(f"Found {len(spx_positions)} SPX positions. Legs details:")
for p in spx_positions:
    print(f"  - Symbol: {p['symbol']}, Side: {p['side']}, Group: {p['broker_group']}")

print("\nGrouping positions into strategies...")
trades = group_positions_into_trades(positions)

print(f"Total strategies grouped across all underlyings: {len(trades)}")

spx_trades = trades
print(f"\nAll Grouped Strategies ({len(spx_trades)}):")
for i, t in enumerate(spx_trades, 1):
    print(f"\nStrategy {i}: {t['underlying']} {t['strategy_type']} (Status: {t['status']})")
    print(f"  Open Date: {t['open_date']}, Entry: {t['entry_credit_debit']:.2f}")
    for leg in t['legs']:
        print(f"    - {leg['symbol']} ({leg['side']}), Group: {leg['broker_group']}")

# Assertions
spx_strategies = [t['strategy_type'] for t in spx_trades]
assert 'IRON_CONDOR' in spx_strategies, "Error: SPX Iron Condor was not found!"
assert 'PUT_DEBIT_SPREAD' in spx_strategies, "Error: SPX Put Debit Spread was not found!"
print("\nValidation PASSED! SPX is correctly split into Iron Condor and Put Debit Spread.")
