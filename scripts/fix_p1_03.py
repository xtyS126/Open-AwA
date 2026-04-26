"""
P1-03: Add finally block for response.close() in litellm_adapter.py streaming function.
Instead of duplicating response.close() in each except block, use a single finally.
"""
path = r"d:\代码\Open-AwA\backend\core\litellm_adapter.py"
with open(path, "r", encoding="utf-8") as f:
    content = f.read()

changes = 0

# Step 1: Remove response.close() from except asyncio.TimeoutError
pattern = (
    "            if response is not None:\n"
    "                try:\n"
    "                    response.close()\n"
    "                except Exception:\n"
    "                    pass\n"
)
count = content.count(pattern)
if count >= 2:
    # Remove both occurrences
    content = content.replace(pattern, "", 2)
    changes += 1
    print(f"P1-03: Removed {count} occurrences of duplicated response.close()")
else:
    print(f"WARNING: Expected at least 2 response.close() patterns, found {count}")

# Step 2: Add finally block before `if attempt < num_retries:` (8-space indent)
old_snippet = (
    "\n        if attempt < num_retries:\n"
    "            await _exponential_backoff(attempt)"
)
new_snippet = (
    "\n        finally:\n"
    "            if response is not None:\n"
    "                try:\n"
    "                    response.close()\n"
    "                except Exception:\n"
    "                    pass\n"
    "\n"
    "        if attempt < num_retries:\n"
    "            await _exponential_backoff(attempt)"
)

if old_snippet in content:
    content = content.replace(old_snippet, new_snippet, 1)
    changes += 1
    print("P1-03: Added finally block with response.close()")
else:
    print("WARNING: Could not find insertion point for finally block!")
    idx = content.find("if attempt < num_retries:")
    if idx >= 0:
        # Show context around first occurrence
        print(f"Found at position {idx}")
        print(repr(content[idx-50:idx+80]))

if changes:
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"P1-03: File written with {changes} changes")
else:
    print("P1-03: No changes made!")
