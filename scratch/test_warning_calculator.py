import os
import sys
import json

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.database.schema import init_database, migrate_database
from src.utils.market_risk import recalculate_and_cache_market_risk
from src.database.queries import get_market_risk_warnings

def main():
    print("Initializing and migrating database...")
    init_database()
    migrate_database()

    print("\nRunning recalculate_and_cache_market_risk()...")
    print("This fetches data for SPY, QQQ, IWM, VIX and calculates risk indicators...")
    try:
        recalculate_and_cache_market_risk()
        print("Success: Calculations complete and cached to database.")
    except Exception as e:
        print(f"Error during recalculation: {e}")
        import traceback
        traceback.print_exc()
        return

    print("\nRetrieving cached warnings from database:")
    warnings = get_market_risk_warnings()
    if not warnings:
        print("Error: No warnings retrieved from database!")
        return

    for row in warnings:
        row = dict(row)
        print(f"\nTicker: {row['ticker']}")
        print(f"  Score: {row['score']}/100 - {row['level']}")
        print(f"  Close Price: ${row['close_price']:.2f}")
        print(f"  VIX: {row['vix']}")
        print(f"  RSI: {row['rsi']}")
        print(f"  Z-Score: {row['zscore']}")
        print(f"  DevSMA50: {row['dev_sma50']*100:.2f}%")
        print(f"  DevSMA200: {row['dev_sma200']*100:.2f}%")
        print(f"  As of: {row['as_of_date']}")
        print(f"  Last updated: {row['updated_at']}")
        signals = json.loads(row['signals_json']) if row['signals_json'] else []
        print("  Signals:")
        for sig in signals:
            try:
                print(f"    - {sig}")
            except Exception:
                # Fallback in case signal text has unicode
                print(f"    - {sig.encode('ascii', errors='replace').decode('ascii')}")
        if not signals:
            print("    (No signals)")

    print("\nSuccess: Verification test successful!")

if __name__ == "__main__":
    main()
