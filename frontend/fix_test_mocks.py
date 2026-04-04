import os
import re

test_dir = r"d:\代码\Open-AwA\frontend\src\__tests__"
for f in os.listdir(test_dir):
    if f.endswith('.tsx') or f.endswith('.ts'):
        filepath = os.path.join(test_dir, f)
        with open(filepath, 'r', encoding='utf-8') as file:
            content = file.read()
            
        # Fix mock paths
        content = re.sub(r"vi\.mock\('\.\./services/(.*?)'", r"vi.mock('@/features/\1'", content)
        content = re.sub(r"vi\.mock\('\.\./stores/(.*?)'", r"vi.mock('@/features/\1'", content)
        content = re.sub(r"vi\.mock\('@/services/(.*?)'", r"vi.mock('@/features/\1'", content)
        content = re.sub(r"vi\.mock\('@/stores/(.*?)'", r"vi.mock('@/features/\1'", content)
        
        # specific fixes based on the real paths
        content = content.replace("vi.mock('@/features/modelsApi'", "vi.mock('@/features/settings/modelsApi'")
        content = content.replace("vi.mock('@/features/chatStore'", "vi.mock('@/features/chat/store/chatStore'")
        content = content.replace("vi.mock('@/features/pluginsApi'", "vi.mock('@/shared/api/api'")
        content = content.replace("vi.mock('@/features/weixinApi'", "vi.mock('@/shared/api/api'")
        
        with open(filepath, 'w', encoding='utf-8') as file:
            file.write(content)
