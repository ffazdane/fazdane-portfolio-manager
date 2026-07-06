"""Check all active trades that have a SHORT PUT leg, show their DB option_type and side values."""
import sqlite3, sys
sys.path.insert(0, '.')
conn = sqlite3.connect('data/portfolio.db')
conn.row_factory = sqlite3.Row

print("=== Active trades with SHORT PUT legs ===")
rows = conn.execute("""
    SELECT t.trade_id, t.underlying, t.broker, t.account, t.strategy_type, t.status,
           tl.leg_id, tl.side, tl.option_type, tl.strike, tl.expiry, tl.status as leg_status, tl.qty_open
    FROM trades t
    JOIN trade_legs tl ON t.trade_id = tl.trade_id
    WHERE t.status IN ('ACTIVE','PARTIALLY_CLOSED','ADJUSTED','ROLLED_OPEN')
    AND tl.side = 'SHORT'
    AND tl.option_type = 'P'
    AND tl.status = 'OPEN'
    ORDER BY t.underlying, t.trade_id
""").fetchall()

if not rows:
    print("  No active SHORT PUT legs found!")
else:
    for r in rows:
        print(f"\n  trade_id={r['trade_id']}  {r['underlying']}  broker={r['broker']}  strategy={r['strategy_type']}")
        print(f"    leg_id={r['leg_id']}  side={r['side']}  type={r['option_type']}  strike={r['strike']}  exp={r['expiry']}  qty_open={r['qty_open']}")

print("\n=== Active trades with SHORT CALL legs ===")
rows2 = conn.execute("""
    SELECT t.trade_id, t.underlying, t.broker, t.account, t.strategy_type,
           tl.leg_id, tl.side, tl.option_type, tl.strike, tl.expiry, tl.qty_open
    FROM trades t
    JOIN trade_legs tl ON t.trade_id = tl.trade_id
    WHERE t.status IN ('ACTIVE','PARTIALLY_CLOSED','ADJUSTED','ROLLED_OPEN')
    AND tl.side = 'SHORT'
    AND tl.option_type = 'C'
    AND tl.status = 'OPEN'
    ORDER BY t.underlying, t.trade_id
""").fetchall()

if not rows2:
    print("  No active SHORT CALL legs found!")
else:
    for r in rows2:
        print(f"\n  trade_id={r['trade_id']}  {r['underlying']}  broker={r['broker']}  strategy={r['strategy_type']}")
        print(f"    leg_id={r['leg_id']}  side={r['side']}  type={r['option_type']}  strike={r['strike']}  exp={r['expiry']}  qty_open={r['qty_open']}")

print("\n=== Legs with NULL or empty option_type (data quality) ===")
rows3 = conn.execute("""
    SELECT t.trade_id, t.underlying, t.broker, t.strategy_type,
           tl.leg_id, tl.side, tl.option_type, tl.strike, tl.expiry
    FROM trades t
    JOIN trade_legs tl ON t.trade_id = tl.trade_id
    WHERE t.status IN ('ACTIVE','PARTIALLY_CLOSED','ADJUSTED','ROLLED_OPEN')
    AND tl.status = 'OPEN'
    AND (tl.option_type IS NULL OR tl.option_type = '')
    ORDER BY t.underlying
""").fetchall()

if not rows3:
    print("  All OPEN legs have valid option_type. ✅")
else:
    for r in rows3:
        print(f"\n  trade_id={r['trade_id']}  {r['underlying']}  broker={r['broker']}  strategy={r['strategy_type']}")
        print(f"    leg_id={r['leg_id']}  side={r['side']}  type='{r['option_type']}'  strike={r['strike']}  exp={r['expiry']}")

conn.close()
