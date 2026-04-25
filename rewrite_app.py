import re
with open('app.py', 'r', encoding='utf-8') as f:
    content = f.read()

start_idx = content.find('def main():')
end_idx = content.find('if __name__ == "__main__":')

new_main = '''def main():
    st.set_page_config(
        page_title="Options Portfolio Manager",
        page_icon="??",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    if not check_password():
        st.stop()

    init_app()

    # Define Navigation
    pages = {
        "Overview": [
            st.Page("views/dashboard.py", title="Dashboard", icon="??", default=True),
            st.Page("views/active_portfolio.py", title="Active Portfolio", icon="??"),
            st.Page("views/portfolio_monitor.py", title="Portfolio Monitor", icon="??"),
            st.Page("views/risk_monitor.py", title="Risk Monitor", icon="??"),
        ],
        "Trades & Activity": [
            st.Page("views/trade_detail.py", title="Trade Detail", icon="??"),
            st.Page("views/history_log.py", title="History Log", icon="??"),
            st.Page("views/manual_entry.py", title="Manual Entry", icon="??"),
        ],
        "Data Management": [
            st.Page("views/imports.py", title="Imports", icon="??"),
            st.Page("views/broker_data_upload.py", title="Broker Data Upload", icon="??"),
        ],
        "Analytics": [
            st.Page("views/ytd_analytics.py", title="YTD Analytics", icon="??"),
        ],
        "Year-End Controls": [
            st.Page("views/year_close.py", title="Year Close", icon="??"),
        ],
        "System": [
            st.Page("views/settings.py", title="Settings", icon="??"),
        ]
    }

    pg = st.navigation(pages)
'''

css_part = content[content.find('    # Custom CSS'):content.find('    # Main page content')]

new_main += '\\n' + css_part + '''    # Run the selected page
    pg.run()
\\n'''

new_content = content[:start_idx] + new_main + content[end_idx:]
with open('app.py', 'w', encoding='utf-8') as f:
    f.write(new_content)

