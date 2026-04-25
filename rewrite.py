import re

with open('app.py', 'r', encoding='utf-8') as f:
    content = f.read()

start_idx = content.find('def main():')
end_idx = content.find('if __name__ ==')

with open('rewrite_script.py', 'w') as f:
    pass
