import os
import shutil

test_dir = 'src/__tests__'
for root, dirs, files in os.walk(test_dir):
    if root != test_dir:
        continue
    for f in files:
        if not f.endswith('.ts') and not f.endswith('.tsx'):
            continue
        
        # known names mapping
        mapping = {
            'App.test.tsx': 'App.test.tsx',
            'main.test.tsx': 'main.test.tsx',
            'setupTests.test.ts': 'setupTests.test.ts',
            'logger.test.ts': 'shared/utils/logger.test.ts',
            'ChatPage.test.tsx': 'features/chat/ChatPage.test.tsx',
            'PluginConfigPage.test.tsx': 'features/plugins/components/PluginConfigPage.test.tsx',
            'PluginDebugPanel.test.tsx': 'features/plugins/components/PluginDebugPanel.test.tsx',
            'PluginsPage.test.tsx': 'features/plugins/PluginsPage.test.tsx',
            'ReasoningContent.test.tsx': 'features/chat/components/ReasoningContent.test.tsx',
            'SettingsPageWeixin.test.tsx': 'features/settings/SettingsPageWeixin.test.tsx',
        }
        
        rel_path = ''
        if f in mapping:
            rel_path = mapping[f]
        elif f.startswith('features_') or f.startswith('shared_'):
            # e.g. features_billing_billingApi.test.ts -> features/billing/billingApi.test.ts
            # wait, shared_components_Sidebar_Sidebar.test.tsx -> shared/components/Sidebar/Sidebar.test.tsx
            parts = f.split('_')
            # last part is the file name
            filename = parts[-1]
            dirs_path = '/'.join(parts[:-1])
            rel_path = f"{dirs_path}/{filename}"
        
        if rel_path and rel_path != f:
            target_path = os.path.join(test_dir, rel_path)
            os.makedirs(os.path.dirname(target_path), exist_ok=True)
            print(f"Moving {f} to {target_path}")
            shutil.move(os.path.join(test_dir, f), target_path)

