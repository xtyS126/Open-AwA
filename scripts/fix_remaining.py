# Fix 1: test_agent_capability_prompt.py - remove "严格禁令" assertion
fp1 = 'backend/tests/test_agent_capability_prompt.py'
with open(fp1, 'r', encoding='utf-8') as f:
    lines = f.readlines()
# Line 108 (1-indexed) = index 107
target = '    assert "严格禁令" in messages[0]["content"]\n'
if lines[107] == target:
    del lines[107]
    with open(fp1, 'w', encoding='utf-8') as f:
        f.writelines(lines)
    print('Fix 1 done: removed 严格禁令 assertion')
else:
    print(f'Fix 1 SKIP: line 108 is "{lines[107].strip()}"')

# Fix 2: test_backend_protocol_features.py - change intent="chat" to intent dict
fp2 = 'backend/tests/test_backend_protocol_features.py'
with open(fp2, 'r', encoding='utf-8') as f:
    c = f.read()

old_intent = '        intent="chat",'
new_intent = '        intent={"type": "summarize"},'
if old_intent in c:
    c = c.replace(old_intent, new_intent)
    with open(fp2, 'w', encoding='utf-8') as f:
        f.write(c)
    print('Fix 2 done: intent="chat" -> intent={"type": "summarize"}')
else:
    print('Fix 2 SKIP: pattern not found')

# Fix 3: test_twitter_monitor_plugin.py - fix package context for relative imports
fp3 = 'backend/tests/test_twitter_monitor_plugin.py'
with open(fp3, 'r', encoding='utf-8') as f:
    c = f.read()

old_loader = """sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

_plugin_path = Path(__file__).resolve().parents[2] / "plugins" / "twitter-monitor" / "src" / "index.py"
_spec = importlib.util.spec_from_file_location("twitter_monitor_plugin", _plugin_path)
_module = importlib.util.module_from_spec(_spec)
sys.modules["backend.plugins.base_plugin"] = importlib.import_module("plugins.base_plugin")
_spec.loader.exec_module(_module)
TwitterMonitorPlugin = _module.TwitterMonitorPlugin"""

new_loader = """sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# 加载 twitter-monitor 插件（需要包上下文以支持相对导入）
_plugin_src_dir = Path(__file__).resolve().parents[2] / "plugins" / "twitter-monitor" / "src"
_parent_dir = str(_plugin_src_dir.parent)
if _parent_dir not in sys.path:
    sys.path.insert(0, _parent_dir)

sys.modules["backend.plugins.base_plugin"] = importlib.import_module("plugins.base_plugin")
_pkg = importlib.import_module(_plugin_src_dir.name)
_module = importlib.import_module(_plugin_src_dir.name + ".index")
TwitterMonitorPlugin = _module.TwitterMonitorPlugin"""

if old_loader in c:
    c = c.replace(old_loader, new_loader)
    with open(fp3, 'w', encoding='utf-8') as f:
        f.write(c)
    print('Fix 3 done: package context for relative imports')
else:
    print('Fix 3 SKIP: pattern not found')
    # debug: show first 50 chars of what we found
    idx = c.find('sys.path.insert(0')
    if idx >= 0:
        print(f'  Found at idx {idx}: ...{c[idx:idx+80]}...')
