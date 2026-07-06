"""Debug: show all active NVDA trades and their legs across brokers."""
import sqlite3, sys
sys.path.insert(0, '.')
conn = sqlite3.connect('data/portfolio.db')
conn.row_factory = sqlite3.Row

SQL = """
    SELECT t.trade_id, t.underlying, t.broker, t.account, t.strategy_type, t.status,
           COUNT(tl.leg_id) as leg_count
    FROM trades t
    LEFT JOIN trade_legs tl ON t.trade_id = tl.trade_id
    WHERE t.underlying = 'NVDA'
    AND t.status IN ('ACTIVE','PARTIALLY_CLOSED','ADJUSTED','ROLLED_OPEN')
    GROUP BY t.trade_id
    ORDER BY t.broker, t.trade_id
"""

trades = conn.execute(SQL).fetchall()
print(f"=== {len(trades)} active NVDA trades ===")
for t in trades:
    print(f"\n  trade_id={t['trade_id']}  broker={t['broker']}  acct={t['account']}")
    print(f"  strategy={t['strategy_type']}  status={t['status']}  legs={t['leg_count']}")
    legs = conn.execute(
        "SELECT leg_id, side, option_type, strike, expiry, status, qty_open, qty_closed "
        "FROM trade_legs WHERE trade_id=? ORDER BY expiry, strike",
        (t['trade_id'],)
    ).fetchall()
    for l in legs:
        print(f"    leg_id={l['leg_id']}  {l['side']:5s}  {l['option_type']}  "
              f"strike={l['strike']}  exp={l['expiry']}  "
              f"status={l['status']}  qty_open={l['qty_open']}  qty_closed={l['qty_closed']}")

conn.close()
