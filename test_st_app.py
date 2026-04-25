import pandas as pd
from src.database.queries import get_broker_transactions
transactions = get_broker_transactions(year=2025, broker='Schwab')
df = pd.DataFrame([dict(t) for t in transactions])
print('Before to_datetime:', df['transaction_date'].head().tolist())
df['transaction_date'] = pd.to_datetime(df['transaction_date'], errors='coerce')
print('After to_datetime:', df['transaction_date'].head().tolist())
df['transaction_date'] = df['transaction_date'].dt.date
print('After dt.date:', df['transaction_date'].head().tolist())
print('Dtype:', df['transaction_date'].dtype)
