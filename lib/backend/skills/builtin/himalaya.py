"""
himalaya 内置技能 — 通过 IMAP/SMTP 管理邮件。
使用 himalaya CLI 工具列出、阅读、搜索和整理邮件。
"""
import subprocess
from typing import Any, Optional
from loguru import logger

SKILL_NAME = "himalaya"
SKILL_DESCRIPTION = "通过 IMAP/SMTP 管理邮件：列出、阅读、搜索、发送和整理邮件"


def _check_himalaya() -> bool:
    """检查 himalaya CLI 是否可用。"""
    try:
        result = subprocess.run(
            ["himalaya", "--version"],
            capture_output=True, text=True, timeout=5,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


async def execute(
    action: str,
    query: Optional[str] = None,
    folder: str = "INBOX",
    limit: int = 10,
    **kwargs: Any,
) -> dict[str, Any]:
    """
    执行邮件管理操作。

    Args:
        action: 操作类型（list/search/send/info）
        query: 搜索关键词
        folder: 邮件文件夹
        limit: 最大邮件数

    Returns:
        操作结果
    """
    if not _check_himalaya():
        return {
            "success": False,
            "error": "himalaya CLI 不可用。安装方法: cargo install himalaya 或访问 https://github.com/pimalaya/himalaya",
        }

    valid_actions = {"list", "search", "send", "info"}
    if action not in valid_actions:
        return {"success": False, "error": f"不支持的操作: {action}"}

    logger.bind(event="himalaya_skill", action=action).info("邮件操作")

    try:
        if action == "list":
            cmd = ["himalaya", "list", folder, "-w", str(limit)]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            return {
                "success": True,
                "action": "list",
                "folder": folder,
                "output": result.stdout[:5000] if result.stdout else "(空)",
                "count": len(result.stdout.strip().split("\n")) if result.stdout else 0,
            }

        elif action == "search":
            if not query:
                return {"success": False, "error": "搜索需要提供 query 参数"}
            cmd = ["himalaya", "search", query, folder, "-w", str(limit)]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            return {
                "success": True,
                "action": "search",
                "query": query,
                "folder": folder,
                "output": result.stdout[:5000] if result.stdout else "(无结果)",
            }

        elif action == "send":
            to = kwargs.get("to")
            subject = kwargs.get("subject", "")
            body = kwargs.get("body", "")
            if not to:
                return {"success": False, "error": "发送需要提供 to 参数"}
            # himalaya send 通过管道输入邮件内容
            email_content = f"To: {to}\nSubject: {subject}\n\n{body}"
            result = subprocess.run(
                ["himalaya", "send"],
                input=email_content,
                capture_output=True, text=True, timeout=30,
            )
            return {
                "success": result.returncode == 0,
                "action": "send",
                "to": to,
                "subject": subject,
            }

        elif action == "info":
            return {
                "success": True,
                "action": "info",
                "himalaya_available": True,
                "note": "使用 himalaya CLI 管理邮件。默认读取 ~/.config/himalaya/config.toml 配置。",
            }

    except subprocess.TimeoutExpired:
        return {"success": False, "error": "邮件操作超时"}
    except Exception as e:
        return {"success": False, "error": f"操作失败: {str(e)}"}

    return {"success": False}
