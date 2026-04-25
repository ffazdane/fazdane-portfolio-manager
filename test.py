from src.database.connection import get_db_readonly
with get_db_readonly() as conn:
  res = conn.execute("SELECT transaction_date FROM broker_transactions WHERE broker_name='Schwab' AND transaction_year=2025 LIMIT 10").fetchall()
  print([dict(r) for r in res])
