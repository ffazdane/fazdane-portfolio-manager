from src.database.connection import get_db_readonly
import pandas as pd
with get_db_readonly() as conn:
  res = conn.execute("SELECT transaction_date FROM broker_transactions WHERE broker_name='Schwab'").fetchall()
df = pd.DataFrame([dict(r) for r in res])
df['transaction_date_parsed'] = pd.to_datetime(df['transaction_date'], errors='coerce')
print('Total Schwab txns:', len(df))
print('Null dates before parse:', df['transaction_date'].isnull().sum())
print('NaT after parse:', df['transaction_date_parsed'].isna().sum())
