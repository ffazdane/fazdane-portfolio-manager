from src.database.connection import get_db_readonly
with get_db_readonly() as conn:
  res = conn.execute("SELECT transaction_date FROM broker_transactions WHERE ticker LIKE '%NVDA%205%' LIMIT 5").fetchall()
  print([repr(r['transaction_date']) for r in res])
