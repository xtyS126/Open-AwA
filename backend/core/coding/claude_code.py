"""
Claude Code (CC) 集成适配器。
通过调用 claude CLI 实现编码任务的委托执行，捕获输出和文件变更。
"""
import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

from loguru import logger


class ClaudeCodeAdapter:
    """
    Claude Code CLI 适配器。
    将编码子任务委托给 claude CLI 执行，解析输出并捕获文件变更。
    """

    def __init__(self, project_dir: str):
        self.project_dir = Path(project_dir).resolve()
        self._available: Optional[bool] = None

    def is_available(self) -> bool:
        """
        检查 claude CLI 是否可用。
        """
        if self._available is not None:
            return self._available
        try:
            result = subprocess.run(
                ["claude", "--version"],
                capture_output=True, text=True, timeout=10,
            )
            self._available = result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            self._available = False
        return self._available

    def run_task(
        self,
        prompt: str,
        auto_approve: bool = False,
        max_turns: Optional[int] = None,
        timeout: int = 300,
    ) -> dict:
        """
        在项目目录中运行 Claude Code 任务。
        """
        if not self.is_available():
            return {"error": "Claude Code CLI (claude) 不可用，请先安装"}

        cmd = ["claude"]

        # 设置工作目录
        cmd.extend(["--cwd", str(self.project_dir)])

        # 自动批准模式
        if auto_approve:
            cmd.append("--approve")

        # 设置最大轮数
        if max_turns:
            cmd.extend(["--max-turns", str(max_turns)])

        # 添加提示词
        cmd.extend(["-p", prompt])

        # 获取变更前的文件状态快照
        before_snapshot = self._get_file_snapshot()

        try:
            logger.bind(event="cc_task_start", project=str(self.project_dir)).info(
                f"Claude Code 任务开始: {prompt[:100]}..."
            )
            result = subprocess.run(
                cmd,
                cwd=str(self.project_dir),
                capture_output=True,
                text=True,
                timeout=timeout,
                env={**os.environ, "NO_COLOR": "1"},
            )

            # 获取变更后的文件状态
            after_snapshot = self._get_file_snapshot()
            changed_files = self._diff_snapshots(before_snapshot, after_snapshot)

            output = result.stdout or ""
            error_output = result.stderr or ""

            return {
                "success": result.returncode == 0,
                "exit_code": result.returncode,
                "output": output,
                "error": error_output,
                "changed_files": changed_files,
                "changed_count": len(changed_files),
            }

        except subprocess.TimeoutExpired:
            return {"error": f"Claude Code 任务超时 ({timeout}s)", "success": False}
        except Exception as e:
            return {"error": f"执行失败: {str(e)}", "success": False}

    def run_with_mode(self, prompt: str, mode: str = "chat") -> dict:
        """
        以指定模式运行 Claude Code。
        支持模式: chat（对话模式），code（编码模式）。
        """
        # 根据模式调整提示词
        if mode == "code":
            enhanced_prompt = (
                f"You are a coding assistant. Write production-quality code. "
                f"Do NOT explain the code in detail unless asked. "
                f"Task: {prompt}"
            )
        else:
            enhanced_prompt = prompt

        return self.run_task(prompt=enhanced_prompt, max_turns=20)

    def _get_file_snapshot(self) -> dict[str, float]:
        """
        获取项目目录中所有跟踪文件的修改时间快照。
        """
        snapshot = {}
        for root, dirs, files in os.walk(self.project_dir):
            # 跳过忽略目录
            dirs[:] = [
                d for d in dirs
                if not d.startswith(".") and d not in {
                    "__pycache__", "node_modules", ".venv", "venv",
                    "dist", "build", ".git",
                }
            ]
            for fname in files:
                fpath = Path(root) / fname
                try:
                    snapshot[str(fpath)] = fpath.stat().st_mtime
                except OSError:
                    pass
        return snapshot

    def _diff_snapshots(
        self, before: dict[str, float], after: dict[str, float]
    ) -> list[dict]:
        """
        比较两个文件快照，返回变更文件列表。
        """
        changed = []
        all_keys = set(before.keys()) | set(after.keys())

        for path in all_keys:
            before_mtime = before.get(path)
            after_mtime = after.get(path)

            if before_mtime is None:
                changed.append({"file": path, "change": "created"})
            elif after_mtime is None:
                changed.append({"file": path, "change": "deleted"})
            elif before_mtime != after_mtime:
                changed.append({"file": path, "change": "modified"})

        return changed
