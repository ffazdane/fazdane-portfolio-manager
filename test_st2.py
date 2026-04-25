import streamlit as st
import pandas as pd
import datetime
df = pd.DataFrame({'transaction_date': ['12/31/2025']})
df['transaction_date'] = pd.to_datetime(df['transaction_date'], errors='coerce').dt.date
print('Before render:', df['transaction_date'].tolist())
st.dataframe(df, column_config={'transaction_date': st.column_config.DateColumn('Date', format='YYYY-MM-DD')})
