"""
P1-11: Add logging to except:pass in mcp/client.py disconnect cleanup
"""
path = r"d:\代码\Open-AwA\backend\mcp\client.py"
with open(path, "r", encoding="utf-8") as f:
    content = f.read()

# Replace the except:pass with logging
old_except = (
    "                except Exception:\n"
    "                    pass\n"
    "                self._transport = None\n"
    "            raise "
)

new_except = (
    "                except Exception as e:\n"
    "                    logger.warning(f\"MCP transport disconnect failed: {e}\")\n"
    "                self._transport = None\n"
    "            raise "
)

if old_except in content:
    content = content.replace(old_except, new_except)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    print("P1-11: Added logging to except:pass in mcp/client.py")
else:
    print("WARNING: Pattern still not found!")
    idx = content.find("except Exception:")
    if idx >= 0:
        print(f"Found at position {idx}")
        print(repr(content[idx-100:idx+100]))
