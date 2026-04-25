import pandas as pd
from src.database.queries import get_broker_transactions
txns = get_broker_transactions()
df = pd.DataFrame([dict(t) for t in txns])
mask = df['ticker'].str.contains('NFLX.*920', na=False, regex=True)
print(df[mask][['transaction_date', 'ticker', 'price', 'source_file_name']])
