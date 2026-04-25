import sys
import os
import sqlite3
sys.path.append(os.path.abspath('.'))

from src.database.connection import get_db
from src.utils.option_symbols import parse_generic_option_symbol, parse_schwab_description, parse_occ_symbol
from src.engine.position_engine import reconstruct_positions
from src.engine.strategy_grouper import group_positions_into_trades, save_trades_to_db

def fix_missing_option_details():
    with get_db() as conn:
        # Get all option transactions missing expiry or strike
        cursor = conn.execute("""
            SELECT txn_id, symbol, description 
            FROM normalized_transactions 
            WHERE instrument_type = 'EQUITY_OPTION' 
            AND (expiry IS NULL OR strike IS NULL OR put_call IS NULL)
        """)
        rows = cursor.fetchall()
        
        fixed_count = 0
        underlyings_to_rebuild = set()
        
        for row in rows:
            txn_id = row['txn_id']
            symbol = row['symbol']
            description = row['description']
            
            # Try to parse
            opt = parse_occ_symbol(symbol)
            if not opt:
                opt = parse_generic_option_symbol(symbol)
            if not opt:
                opt = parse_schwab_description(description)
                
            if opt and opt.get('expiry') and opt.get('strike'):
                print(f"Fixing txn {txn_id}: {symbol} -> {opt}")
                conn.execute("""
                    UPDATE normalized_transactions 
                    SET underlying = ?, expiry = ?, strike = ?, put_call = ? 
                    WHERE txn_id = ?
                """, (opt['underlying'], opt['expiry'], opt['strike'], opt['put_call'], txn_id))
                fixed_count += 1
                underlyings_to_rebuild.add(opt['underlying'])
                
        print(f"Fixed {fixed_count} transactions.")
        
    if underlyings_to_rebuild:
        print(f"Rebuilding trades for underlyings: {underlyings_to_rebuild}")
        from src.database.queries import delete_active_trades_by_underlying
        delete_active_trades_by_underlying(list(underlyings_to_rebuild))
        
        positions = reconstruct_positions()
        positions = [p for p in positions if p.get('underlying') in underlyings_to_rebuild]
        
        trades = group_positions_into_trades(positions)
        trade_ids = save_trades_to_db(trades)
        print(f"Recreated {len(trade_ids)} trades.")

if __name__ == '__main__':
    fix_missing_option_details()
