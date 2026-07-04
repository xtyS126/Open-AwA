"""通过 agent-browser 实现 Bilibili 浏览器自动化。

为 API 不支持或需要视觉上下文的操作提供基于浏览器的
Bilibili 交互能力。使用 Vercel 的 agent-browser CLI：
https://github.com/vercel-labs/agent-browser
"""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
import subprocess
import uuid
from pathlib import Path
from typing import Any, cast

logger = logging.getLogger(__name__)


class BrowserCommandError(RuntimeError):
    """当 agent-browser 返回失败状态时抛出。"""


class BilibiliBrowser:
    """使用 agent-browser 的浏览器自动化接口。

    这是次级访问层，用于以下场景：
    - API 不覆盖某个所需操作
    - 需要视觉上下文（DOM、截图）
    - 需要复杂页面交互

    需要先安装 agent-browser：
        npm install -g agent-browser
        agent-browser install
    """

    def __init__(
        self,
        executable: str = "",
        headed: bool = False,
        cookie: str = "",
    ) -> None:
        self._executable = executable or self._find_executable()
        self._headed = headed
        self._cookie = cookie
        self._session_name = f"openbiliclaw-{uuid.uuid4().hex[:8]}"

    @staticmethod
    def _find_executable() -> str:
        """查找 agent-browser 可执行文件。"""
        path = shutil.which("agent-browser")
        if path:
            return path
        return "agent-browser"

    @staticmethod
    def get_install_hint() -> str:
        """返回官方的 agent-browser 安装提示。"""
        return (
            "未检测到 agent-browser。请先执行 "
            "`npm install -g agent-browser`，然后执行 "
            "`agent-browser install` 安装浏览器内核。"
        )

    @staticmethod
    def _has_executable(executable: str) -> bool:
        """检查配置的可执行文件是否可用。"""
        executable_path = Path(executable)
        if executable_path.is_absolute() or "/" in executable:
            if not (executable_path.exists() and executable_path.is_file()):
                return False
        elif shutil.which(executable) is None:
            return False

        try:
            result = subprocess.run(
                [executable, "--version"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return False

        return result.returncode == 0

    @property
    def is_available(self) -> bool:
        """检查 agent-browser 是否可用。"""
        return self._has_executable(self._executable)

    @property
    def executable(self) -> str:
        """返回解析后的可执行文件名或路径。"""
        return self._executable

    async def _run_command(self, *args: str) -> dict[str, Any]:
        """执行一个 agent-browser 命令并返回结果。

        Args:
            *args: 命令参数。

        Returns:
            从 agent-browser 解析出的 JSON 输出。
        """
        cmd = [self._executable, "--session", self._session_name, *args]
        if self._headed:
            cmd.append("--headed")

        logger.debug("Running agent-browser: %s", " ".join(cmd))

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()

        if proc.returncode != 0:
            error_msg = stderr.decode().strip() if stderr else "Unknown error"
            logger.error("agent-browser error: %s", error_msg)
            command = " ".join(cmd)
            raise BrowserCommandError(f"agent-browser command failed: {command}: {error_msg}")

        try:
            return cast("dict[str, Any]", json.loads(stdout.decode()))
        except json.JSONDecodeError:
            return {"output": stdout.decode()}

    async def navigate(self, url: str) -> dict[str, Any]:
        """导航到指定 URL。

        Args:
            url: 目标 URL。

        Returns:
            页面信息。
        """
        try:
            return await self._run_command("open", url)
        except BrowserCommandError as exc:
            if "ERR_ABORTED" not in str(exc):
                raise
        return await self._run_command("open", url)

    async def get_page_content(self, url: str) -> str:
        """获取页面的文本内容。

        Args:
            url: 目标 URL。

        Returns:
            页面文本内容。
        """
        await self.navigate(url)
        snapshot = await self._run_command("snapshot", "-i", "--json")
        return self._extract_snapshot_text(snapshot)

    @staticmethod
    def _extract_snapshot_text(result: dict[str, Any]) -> str:
        """从快照载荷中提取可见页面文本。"""
        data = result.get("data")
        if isinstance(data, dict):
            snapshot = data.get("snapshot")
            if isinstance(snapshot, str) and snapshot.strip():
                return snapshot
            text = data.get("text")
            if isinstance(text, str) and text.strip():
                return text

        output = result.get("output")
        if isinstance(output, str) and output.strip():
            return output

        raise BrowserCommandError("agent-browser returned no readable snapshot content")

    async def screenshot(self, url: str, output_path: str) -> str:
        """对页面截图。

        Args:
            url: 目标 URL。
            output_path: 截图保存路径。

        Returns:
            已保存截图的路径。
        """
        result = await self._run_command("screenshot", url, "-o", output_path)
        return str(result.get("output", output_path))

    async def close(self) -> None:
        """关闭所有活跃的浏览器会话。"""
        try:
            await self._run_command("close")
        except Exception:
            logger.debug("No active session to close.")
