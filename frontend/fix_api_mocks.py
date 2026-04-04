import os

test_dir = r"d:\代码\Open-AwA\frontend\src\__tests__"
files = ['PluginDebugPanel.test.tsx', 'PluginsPage.test.tsx', 'SettingsPageWeixin.test.tsx']

for f in files:
    filepath = os.path.join(test_dir, f)
    if os.path.exists(filepath):
        with open(filepath, 'r', encoding='utf-8') as file:
            content = file.read()
            
        content = content.replace("vi.mock('@/features/api'", "vi.mock('@/shared/api/api'")
        
        with open(filepath, 'w', encoding='utf-8') as file:
            file.write(content)
