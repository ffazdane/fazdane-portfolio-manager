import os
import shutil
import re

pages_dir = 'pages'
views_dir = 'views'

os.makedirs(views_dir, exist_ok=True)

renames = {
    '1_??_Dashboard.py': 'dashboard.py',
    '2_??_Active_Portfolio.py': 'active_portfolio.py',
    '3_??_Trade_Detail.py': 'trade_detail.py',
    '4_??_History_Log.py': 'history_log.py',
    '5_??_Imports.py': 'imports.py',
    '6_??_Risk_Monitor.py': 'risk_monitor.py',
    '7_??_Settings.py': 'settings.py',
    '8_??_Manual_Entry.py': 'manual_entry.py',
    '9_??_Portfolio_Monitor.py': 'portfolio_monitor.py',
    '10_??_Broker_Data_Upload.py': 'broker_data_upload.py',
    '11_??_YTD_Analytics.py': 'ytd_analytics.py',
    '12_??_Year_Close.py': 'year_close.py'
}

for old_name, new_name in renames.items():
    old_path = os.path.join(pages_dir, old_name)
    new_path = os.path.join(views_dir, new_name)
    if os.path.exists(old_path):
        with open(old_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Remove st.set_page_config
        content = re.sub(r'st\.set_page_config\(.*?\)\n', '', content)
        
        with open(new_path, 'w', encoding='utf-8') as f:
            f.write(content)
        os.remove(old_path)

os.rmdir(pages_dir)
print('Refactored pages to views')
