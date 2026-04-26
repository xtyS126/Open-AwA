"""
P1-01: Add continuous error threshold to executor.py tool_calls loop
"""
path = r"d:\代码\Open-AwA\backend\core\executor.py"
with open(path, "r", encoding="utf-8") as f:
    content = f.read()

old_code = """        max_rounds = 5
        round_count = 0
        tool_events = []

        while round_count < max_rounds:
            tool_calls = result.get("tool_calls")
            if not tool_calls:
                break

            round_count += 1
            for tc in tool_calls:
                exec_result = await self._execute_tool_call(tc, context)
                tool_events.append({
                    "name": tc.get("function", {}).get("name", "unknown"),
                    "status": "completed" if exec_result.get("ok") else "error",
                    "result": exec_result.get("result", exec_result.get("error")),
                })
                tool_message = self._build_tool_message(tc, exec_result)
                messages.append(tool_message)"""

new_code = """        max_rounds = 5
        round_count = 0
        consecutive_errors = 0
        max_consecutive_errors = 3
        tool_events = []

        while round_count < max_rounds:
            tool_calls = result.get("tool_calls")
            if not tool_calls:
                break

            round_count += 1
            _abort = False
            for tc in tool_calls:
                exec_result = await self._execute_tool_call(tc, context)
                if exec_result.get("ok"):
                    consecutive_errors = 0
                else:
                    consecutive_errors += 1
                    if consecutive_errors >= max_consecutive_errors:
                        logger.bind(
                            event="tool_calls_max_consecutive_errors",
                            module="executor",
                            consecutive_errors=consecutive_errors,
                            threshold=max_consecutive_errors,
                        ).warning(f"\u5de5\u5177\u8c03\u7528\u8fde\u7eed\u5931\u8d25 {consecutive_errors} \u6b21\uff0c\u7ec8\u6b62 tool_calls \u5faa\u73af")
                        _abort = True
                        break
                tool_events.append({
                    "name": tc.get("function", {}).get("name", "unknown"),
                    "status": "completed" if exec_result.get("ok") else "error",
                    "result": exec_result.get("result", exec_result.get("error")),
                })
                tool_message = self._build_tool_message(tc, exec_result)
                messages.append(tool_message)
            if _abort:
                break"""

if old_code in content:
    content = content.replace(old_code, new_code)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    print("P1-01: executor.py tool_calls loop updated with consecutive error threshold")
else:
    print("ERROR: old_code not found!")
    idx = content.find("max_rounds = 5")
    if idx >= 0:
        print(f"Found at position {idx}")
        print(repr(content[idx:idx+500]))
