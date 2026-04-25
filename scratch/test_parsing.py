
import sys
import os

# Add src to path
sys.path.append(os.path.abspath('.'))

from src.utils.option_symbols import parse_generic_option_symbol, parse_schwab_description

def test_parsing():
    symbols = [
        "NFLX 04/24/2026 560.0 CALL",
        "NFLX 05/15/2026 580.0 CALL",
        "NFLX 04/24/2026 560.0 C",
        "NFLX 05/15/2026 580.0 P",
        "SPY 05/01/26 450.5 PUT",
        "AAPL 1/2/2026 150 CALL"
    ]
    
    print("Testing parse_generic_option_symbol:")
    for s in symbols:
        result = parse_generic_option_symbol(s)
        print(f"'{s}' -> {result}")

    descriptions = [
        "CALL NETFLIX INC $560 EXP 04/24/26",
        "PUT NETFLIX INC $580 EXP 05/15/26",
        "CALL NETFLIX INC",
        "NFLX APR 24 2026 560.0 C"
    ]
    
    print("\nTesting parse_schwab_description:")
    for d in descriptions:
        result = parse_schwab_description(d)
        print(f"'{d}' -> {result}")

if __name__ == "__main__":
    test_parsing()
