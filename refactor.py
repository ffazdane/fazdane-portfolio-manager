import os
import re
pages_dir = 'pages'
views_dir = 'views'
os.makedirs(views_dir, exist_ok=True)
for f in os.listdir(pages_dir):
    if not f.endswith('.py'): continue
    name = f.split('_', 2)[-1]  # split out the number and emoji
    new_name = name.lower()
    old_path = os.path.join(pages_dir, f)
    new_path = os.path.join(views_dir, new_name)
    with open(old_path, 'r', encoding='utf-8') as file:
        content = file.read()
    content = re.sub(r'st\.set_page_config\(.*?\)\n', '', content)
    # also remove init_app() and branding because app.py handles it
    content = re.sub(r'from app import init_app\n', '', content)
    content = re.sub(r'from src.utils.branding import setup_branding\n', '', content)
    content = re.sub(r'setup_branding\(\)\n', '', content)
    content = re.sub(r'init_app\(\)\n', '', content)
    with open(new_path, 'w', encoding='utf-8') as file:
        file.write(content)
    os.remove(old_path)
print('done')
