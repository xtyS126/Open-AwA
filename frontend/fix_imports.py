import os
import re
import glob

def fix_imports(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    # Rewrite paths starting with '.' or '..' to use '@/'
    # Since we moved files, relative imports are broken anyway.
    
    # We can just map known names to their new paths
    import_map = {
        r"['\"].*/services/api['\"]": "'@/shared/api/api'",
        r"['\"].*/services/logger['\"]": "'@/shared/utils/logger'",
        r"['\"].*/stores/chatStore['\"]": "'@/features/chat/store/chatStore'",
        r"['\"].*/services/modelsApi['\"]": "'@/features/settings/modelsApi'",
        r"['\"].*/services/billingApi['\"]": "'@/features/billing/billingApi'",
        r"['\"].*/services/experiencesApi['\"]": "'@/features/experiences/experiencesApi'",
        r"['\"].*/services/fileExperiencesApi['\"]": "'@/features/experiences/fileExperiencesApi'",
        r"['\"].*/types/api['\"]": "'@/shared/types/api'",
        r"['\"].*/types/dashboard['\"]": "'@/features/dashboard/dashboard'",
        r"['\"].*/types/billing['\"]": "'@/features/billing/billing'",
        r"['\"].*/types/plugin-sdk['\"]": "'@/features/plugins/plugin-sdk'",
        r"['\"].*/components/Sidebar['\"]": "'@/shared/components/Sidebar/Sidebar'",
        r"['\"].*/components/SkillModal['\"]": "'@/features/skills/SkillModal'",
        r"['\"].*/components/PluginDebugPanel['\"]": "'@/features/plugins/PluginDebugPanel'",
        
        # For App.tsx
        r"['\"].*/pages/ChatPage['\"]": "'@/features/chat/ChatPage'",
        r"['\"].*/pages/CommunicationPage['\"]": "'@/features/chat/CommunicationPage'",
        r"['\"].*/pages/DashboardPage['\"]": "'@/features/dashboard/DashboardPage'",
        r"['\"].*/pages/SettingsPage['\"]": "'@/features/settings/SettingsPage'",
        r"['\"].*/pages/SkillsPage['\"]": "'@/features/skills/SkillsPage'",
        r"['\"].*/pages/PluginsPage['\"]": "'@/features/plugins/PluginsPage'",
        r"['\"].*/pages/MemoryPage['\"]": "'@/features/memory/MemoryPage'",
        r"['\"].*/pages/BillingPage['\"]": "'@/features/billing/BillingPage'",
        r"['\"].*/pages/ExperiencePage['\"]": "'@/features/experiences/ExperiencePage'",
    }
    
    for pattern, replacement in import_map.items():
        content = re.sub(r"from\s+" + pattern, f"from {replacement}", content)
        # Handle cases like `import * as pluginTypes from '../types/plugin-sdk'`
        # Handled by the above as well
        # What about `import { xyz } from '../types/api'`
        # Handled.

    # Also handle dynamic imports if any
    
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)

tsx_files = glob.glob('src/**/*.tsx', recursive=True)
ts_files = glob.glob('src/**/*.ts', recursive=True)
for f in tsx_files + ts_files:
    fix_imports(f)

