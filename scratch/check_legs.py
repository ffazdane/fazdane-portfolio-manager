import sqlite3
import pandas as pd

conn = sqlite3.connect('data/portfolio.db')
df = pd.read_sql("SELECT * FROM trade_legs WHERE trade_id=136", conn)
print(df.to_string())
