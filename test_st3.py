import streamlit as st
import pandas as pd
df = pd.DataFrame({'transaction_date': ['12/31/2025', None]})
df['transaction_date'] = pd.to_datetime(df['transaction_date'], errors='coerce')
st.dataframe(df, column_config={'transaction_date': st.column_config.DatetimeColumn('Date', format='YYYY-MM-DD')})
