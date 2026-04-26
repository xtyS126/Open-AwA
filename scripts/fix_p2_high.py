"""
P2 high-priority fixes: executor.py shell command + json.dumps, MIME validation
"""
import re

# ============================================
# P2-01: executor.py - Add command length limit and logging to _execute_command
# P2-02: executor.py - Add default=str to json.dumps for TypeError protection
# ============================================
path = r"d:\代码\Open-AwA\backend\core\executor.py"
with open(path, "r", encoding="utf-8") as f:
    content = f.read()

changes = []

# P2-01: Add length limit and sanitization before create_subprocess_shell
old_cmd = (
    "    command = step.get(\"command\", \"\")\n"
    "\n"
    "    try:\n"
    "        proc = await asyncio.create_subprocess_shell("
)
new_cmd = (
    "    command = step.get(\"command\", \"\")\n"
    "    if len(command) > 512:\n"
    "        return {\"status\": \"error\", \"message\": \"Command too long (max 512 chars)\"}\n"
    "    if command and any(c in command for c in [\"&\", \"|\", \";\", \"`\", \"$\", \"(\", \")\", \"<\", \">\", \"\\n\"]):\n"
    '        logger.bind(event="command_blocked_special_chars", module="executor", '
    "command_length=len(command)).warning(\n"
    '            f"Blocked command with special shell characters: {command[:100]}"\n'
    "        )\n"
    "        return {\"status\": \"error\", \"message\": \"Command contains forbidden shell characters\"}\n"
    "\n"
    "    try:\n"
    "        logger.bind(event=\"exec_command\", module=\"executor\", "
    "command_length=len(command)).info(\n"
    '            f"Executing command: {command[:200]}"\n'
    "        )\n"
    "        proc = await asyncio.create_subprocess_shell("
)

if old_cmd in content:
    content = content.replace(old_cmd, new_cmd)
    changes.append("P2-01: Added command length limit and sanitization to _execute_command")
else:
    print("WARNING: P2-01 pattern not found!")
    idx = content.find('command = step.get("command", "")')
    if idx >= 0:
        print(f"Found at position {idx}")
        print(repr(content[idx:idx+120]))

# P2-02: Add default=str to json.dumps on line 955
if 'json.dumps(exec_result, ensure_ascii=False)' in content:
    content = content.replace(
        'json.dumps(exec_result, ensure_ascii=False)',
        'json.dumps(exec_result, ensure_ascii=False, default=str)'
    )
    changes.append("P2-02: Added default=str to json.dumps for TypeError protection")
else:
    print("WARNING: P2-02 pattern not found!")

with open(path, "w", encoding="utf-8") as f:
    f.write(content)
for c in changes:
    print(c)

# ============================================
# P2-03: Add MIME type validation to skills.py and plugins.py file uploads
# ============================================

# skills.py
path = r"d:\代码\Open-AwA\backend\api\routes\skills.py"
with open(path, "r", encoding="utf-8") as f:
    content = f.read()

old_skill = (
    "    try:\n"
    "        if file.size is not None and file.size > MAX_UPLOAD_SIZE:"
)
new_skill = (
    "    try:\n"
    "        if file.content_type and file.content_type not in [\"application/zip\", \"application/x-zip-compressed\"]:\n"
    "            raise HTTPException(status_code=400, detail=\"Only ZIP files are allowed\")\n"
    "        if file.size is not None and file.size > MAX_UPLOAD_SIZE:"
)

if old_skill in content:
    content = content.replace(old_skill, new_skill)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    print("P2-03: Added MIME type validation to skills.py /install-from-package")
else:
    print("WARNING: P2-03 skills.py pattern not found!")

# plugins.py
path = r"d:\代码\Open-AwA\backend\api\routes\plugins.py"
with open(path, "r", encoding="utf-8") as f:
    content = f.read()

old_plugin = (
    "    if not file.filename or not file.filename.endswith('.zip'):\n"
    "        raise HTTPException(status_code=400, detail=\"Only .zip files are supported\")"
)
new_plugin = (
    "    if not file.filename or not file.filename.endswith('.zip'):\n"
    "        raise HTTPException(status_code=400, detail=\"Only .zip files are supported\")\n"
    "    if file.content_type and file.content_type not in [\"application/zip\", \"application/x-zip-compressed\"]:\n"
    "        raise HTTPException(status_code=400, detail=\"Invalid ZIP file MIME type\")"
)

if old_plugin in content:
    content = content.replace(old_plugin, new_plugin)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    print("P2-03: Added MIME type validation to plugins.py /upload")
else:
    print("WARNING: P2-03 plugins.py pattern not found!")
    idx = content.find("if not file.filename")
    if idx >= 0:
        print(f"Found at position {idx}")
        print(repr(content[idx:idx+150]))
