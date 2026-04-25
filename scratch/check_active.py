import sqlite3
import pandas as pd

conn = sqlite3.connect('data/portfolio.db')
df = pd.read_sql("SELECT underlying, strategy_type, broker, status FROM trades WHERE status='ACTIVE'", conn)
print(df.to_string())
print('Total:', len(df))
