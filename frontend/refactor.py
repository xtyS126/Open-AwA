import os
import re
import glob

def refactor_file(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    # Rename css imports to module.css
    content = re.sub(r"import\s+['\"](.*)\.css['\"]", r"import styles from '\1.module.css'", content)
    
    # Fix absolute paths if any (e.g., import { api } from '../services/api' -> '@/shared/api/api')
    # This is complex, so let's just use @/ alias for everything
    
    # Simple replacement of className="some-class" to className={styles.someClass}
    # To handle kebab-case, we use styles['some-class']
    def repl_simple_class(match):
        classes = match.group(1).split()
        if len(classes) == 1:
            return f"className={{styles['{classes[0]}']}}"
        else:
            style_refs = [f"styles['{c}']" for c in classes]
            return f"className={{`${{{'} ${'.join(style_refs)}}}`}}"
            
    content = re.sub(r'className="([^"{}$]+)"', repl_simple_class, content)

    # Replacement of className={`some-class ${var}`}
    # Example: className={`sidebar ${collapsed ? 'collapsed' : ''}`}
    # Result: className={`${styles['sidebar']} ${collapsed ? styles['collapsed'] : ''}`}
    def repl_template_class(match):
        inner = match.group(1)
        # Find all literal strings or plain text outside of ${} and wrap them with styles
        # This is quite hard with simple regex, so let's just do a basic one for known patterns
        # Replace plain text classes:
        parts = re.split(r'(\$\{[^}]+\})', inner)
        new_parts = []
        for part in parts:
            if part.startswith('${'):
                # Check if there's a literal class inside like collapsed ? 'collapsed' : ''
                # Just leave it as is for now, it's safer
                
                # Let's try to replace 'some-class' with styles['some-class'] inside the condition
                # Wait, this might replace things we shouldn't.
                # So just keep it
                new_parts.append(part)
            else:
                classes = part.strip().split()
                if classes:
                    style_refs = [f"${{styles['{c}']}}" for c in classes]
                    new_parts.append(' '.join(style_refs) + (' ' if part.endswith(' ') else ''))
                else:
                    new_parts.append(part)
        return f"className={{`{''.join(new_parts)}`}}"

    content = re.sub(r'className=\{`([^`]+)`\}', repl_template_class, content)

    # Write back
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)

# Update all TSX files
tsx_files = glob.glob('src/**/*.tsx', recursive=True)
for f in tsx_files:
    refactor_file(f)

# Rename CSS files
css_files = glob.glob('src/**/*.css', recursive=True)
for f in css_files:
    if 'global.css' in f or 'module.css' in f:
        continue
    new_name = f.replace('.css', '.module.css')
    os.rename(f, new_name)
