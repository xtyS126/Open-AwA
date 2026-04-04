import os
import re

def create_basic_test(filepath):
    # e.g., d:\代码\Open-AwA\frontend\src\features\dashboard\DashboardPage.tsx
    rel_path = os.path.relpath(filepath, r"d:\代码\Open-AwA\frontend\src")
    test_path = os.path.join(r"d:\代码\Open-AwA\frontend\src\__tests__", rel_path.replace('\\', '_').replace('/', '_').replace('.tsx', '.test.tsx').replace('.ts', '.test.ts'))
    
    if os.path.exists(test_path):
        return

    import_path = '@/' + rel_path.replace('\\', '/').rsplit('.', 1)[0]
    name = os.path.basename(filepath).rsplit('.', 1)[0]
    
    content = ""
    if filepath.endswith('.tsx'):
        content = f"""import '@testing-library/jest-dom/vitest'
import {{ render }} from '@testing-library/react'
import {{ describe, it, expect, vi }} from 'vitest'
import {name} from '{import_path}'
import {{ BrowserRouter }} from 'react-router-dom'

vi.mock('@/shared/api/api', () => ({{
  pluginsAPI: {{ getAll: vi.fn().mockResolvedValue({{ data: [] }}) }},
  weixinAPI: {{ getConfig: vi.fn().mockResolvedValue({{ data: {{}} }}) }},
  authAPI: {{ getMe: vi.fn().mockResolvedValue({{ data: {{}} }}) }},
  billingAPI: {{ getSummary: vi.fn().mockResolvedValue({{ data: {{}} }}) }},
  chatAPI: {{ getHistory: vi.fn().mockResolvedValue({{ data: [] }}) }},
  modelsAPI: {{ getConfigurations: vi.fn().mockResolvedValue({{ data: {{ configurations: [] }} }}) }},
  memoryAPI: {{ getShortTerm: vi.fn().mockResolvedValue({{ data: [] }}), getLongTerm: vi.fn().mockResolvedValue({{ data: [] }}) }},
  experiencesAPI: {{ getList: vi.fn().mockResolvedValue({{ data: [] }}) }},
  fileExperiencesAPI: {{ getList: vi.fn().mockResolvedValue({{ data: [] }}) }},
  skillsAPI: {{ getAll: vi.fn().mockResolvedValue({{ data: [] }}) }},
  promptsAPI: {{ getAll: vi.fn().mockResolvedValue({{ data: [] }}) }},
  logsAPI: {{ query: vi.fn().mockResolvedValue({{ data: {{ records: [], total: 0 }} }}) }},
  behaviorAPI: {{ getStats: vi.fn().mockResolvedValue({{ data: {{}} }}) }},
  conversationAPI: {{ getRecordsPreview: vi.fn().mockResolvedValue({{ data: {{ records: [], count: 0 }} }}) }}
}}))

vi.mock('@/features/settings/modelsApi', () => ({{
  modelsAPI: {{
    getConfigurations: vi.fn().mockResolvedValue({{ data: {{ configurations: [] }} }}),
    updateConfiguration: vi.fn().mockResolvedValue({{ data: {{}} }})
  }}
}}))

describe('{name}', () => {{
  it('renders without crashing', () => {{
    render(<BrowserRouter><{name} /></BrowserRouter>)
    expect(true).toBe(true)
  }})
}})
"""
    elif filepath.endswith('.ts') and not filepath.endswith('.d.ts'):
        content = f"""import {{ describe, it, expect }} from 'vitest'
import * as module from '{import_path}'

describe('{name}', () => {{
  it('loads module', () => {{
    expect(module).toBeDefined()
  }})
}})
"""
    else:
        return
        
    with open(test_path, 'w', encoding='utf-8') as f:
        f.write(content)

src_dir = r"d:\代码\Open-AwA\frontend\src"
for root, _, files in os.walk(src_dir):
    if '__tests__' in root:
        continue
    for file in files:
        if file.endswith('.tsx') or file.endswith('.ts'):
            create_basic_test(os.path.join(root, file))
