import os
import re
import glob

def fix_classnames(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    # Replacements
    # 1. ? 'something' : 'something'
    # we can use a regex to find ? '...' : '...'
    def repl_ternary(m):
        true_val = m.group(1)
        false_val = m.group(2)
        
        new_true = f"styles['{true_val}']" if true_val else "''"
        new_false = f"styles['{false_val}']" if false_val else "''"
        
        return f"? {new_true} : {new_false}"

    content = re.sub(r"\?\s*'([^']*)'\s*:\s*'([^']*)'", repl_ternary, content)
    
    # 2. ${message.type} -> ${styles[message.type] || message.type}
    # Just simple ones: record.provider, record.status, message.type, entry.level
    content = re.sub(r"\$\{(message\.type|record\.provider|record\.status|entry\.level)\}", r"${styles[\1] || \1}", content)
    
    # 3. ' debug-btn-active' -> ` ${styles['debug-btn-active']}`
    content = content.replace("' debug-btn-active'", "styles['debug-btn-active']")
    content = content.replace(" ? 'active' : ''", " ? styles['active'] : ''")
    content = content.replace(" ? 'success' : ''", " ? styles['success'] : ''")
    content = content.replace(" ? 'collapsed' : ''", " ? styles['collapsed'] : ''")
    content = content.replace(" ? 'expanded' : ''", " ? styles['expanded'] : ''")
    
    # fix missing styles[] for string literals like 'user' or 'btn-secondary'
    # Actually the ternary regex covered ? 'user' : 'assistant'
    
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)

tsx_files = glob.glob('src/**/*.tsx', recursive=True)
for f in tsx_files:
    fix_classnames(f)

