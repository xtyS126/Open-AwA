"""
P1-02: Add explicit action=None guard in executor.py execute_step
"""
path = r"d:\代码\Open-AwA\backend\core\executor.py"
with open(path, "r", encoding="utf-8") as f:
    content = f.read()

old_code = """        action = step.get("action")
        logger.info(f"Executing step: {action}")
        idempotency_key = self._build_tool_idempotency_key(step, context)"""

new_code = """        action = step.get("action")
        if action is None:
            logger.bind(
                event="execute_step_missing_action",
                module="executor",
                step_keys=list(step.keys()) if isinstance(step, dict) else None,
            ).warning("execute_step 收到 action=None 的步骤，跳过执行")
            return {
                "status": "error",
                "error": "步骤缺少 action 字段",
                "step": step.get("step"),
                "action": None,
            }
        logger.info(f"Executing step: {action}")
        idempotency_key = self._build_tool_idempotency_key(step, context)"""

if old_code in content:
    content = content.replace(old_code, new_code)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    print("P1-02: executor.py action=None guard added")
else:
    print("ERROR: old_code not found!")
    idx = content.find('action = step.get("action")')
    if idx >= 0:
        print(f"Found at position {idx}")
        print(repr(content[idx:idx+200]))
