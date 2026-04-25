import streamlit as st; import pandas as pd; import datetime; df = pd.DataFrame({'d': [datetime.date(2025, 1, 1)]}); st.dataframe(df)
