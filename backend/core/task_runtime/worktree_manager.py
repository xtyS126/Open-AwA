"""
Git worktree 隔离管理器，为写操作型后台代理创建独立工作副本。
使用 subprocess 调用 git worktree 命令，支持 Windows 路径归一化。
"""

from __future__ import annotations

import asyncio
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from loguru import logger


@dataclass
class WorktreeInfo:
    """Git worktree 信息。"""
    agent_id: str
    path: str
    branch: str
    created: bool = False


class WorktreeManager:
    """
    Git worktree 隔离管理器。

    为写操作型后台代理在 .claude/worktrees/ 下创建独立工作副本，
    代理完成后自动清理。确保多代理并发时文件不冲突。
    """

    def __init__(self, base_dir: Optional[str] = None):
        self._base_dir = Path(base_dir) if base_dir else Path.cwd()
        self._worktree_root = self._base_dir / ".claude" / "worktrees"
        self._active_worktrees: Dict[str, WorktreeInfo] = {}

    async def create_worktree(
        self,
        agent_id: str,
        *,
        base_branch: Optional[str] = None,
    ) -> Optional[WorktreeInfo]:
        """
        为指定代理创建 git worktree。
        在 .claude/worktrees/{agent_id} 下创建独立工作副本。
        """
        worktree_path = self._worktree_root / agent_id

        # 检查是否已存在
        if worktree_path.exists():
            logger.bind(
                module="task_runtime",
                agent_id=agent_id,
                path=str(worktree_path),
            ).warning(f"worktree 路径已存在: {agent_id}")
            # 尝试清理后重建
            await self.cleanup_worktree(agent_id)

        branch_name = f"task-runtime/{agent_id}"

        try:
            # 确保父目录存在
            worktree_path.parent.mkdir(parents=True, exist_ok=True)

            # 获取基准分支
            if not base_branch:
                base_branch = await self._get_current_branch()

            # 创建 worktree
            cmd = [
                "git", "worktree", "add",
                str(worktree_path),
                base_branch,
            ]
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(self._base_dir),
            )
            stdout, stderr = await process.communicate()

            if process.returncode != 0:
                stderr_text = stderr.decode("utf-8", errors="replace") if stderr else ""
                # 如果 worktree 分支已存在，尝试强制创建
                if "already exists" in stderr_text or "already checked out" in stderr_text:
                    logger.bind(
                        module="task_runtime",
                        agent_id=agent_id,
                    ).info(f"worktree 分支已存在，尝试在新路径创建")
                    # 使用不同路径重试
                    fallback_path = self._worktree_root / f"{agent_id}_{os.urandom(4).hex()}"
                    cmd_fallback = [
                        "git", "worktree", "add",
                        str(fallback_path),
                        base_branch,
                    ]
                    process2 = await asyncio.create_subprocess_exec(
                        *cmd_fallback,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                        cwd=str(self._base_dir),
                    )
                    await process2.communicate()
                    if process2.returncode != 0:
                        logger.bind(
                            module="task_runtime",
                            agent_id=agent_id,
                            error=stderr_text,
                        ).error(f"创建 worktree 失败: {agent_id}")
                        return None
                    worktree_path = fallback_path
                else:
                    logger.bind(
                        module="task_runtime",
                        agent_id=agent_id,
                        error=stderr_text,
                    ).error(f"创建 worktree 失败: {agent_id}")
                    return None

            info = WorktreeInfo(
                agent_id=agent_id,
                path=str(worktree_path),
                branch=branch_name,
                created=True,
            )
            self._active_worktrees[agent_id] = info

            logger.bind(
                module="task_runtime",
                agent_id=agent_id,
                worktree_path=str(worktree_path),
                branch=branch_name,
            ).info(f"worktree 已创建: {agent_id}")
            return info

        except Exception as exc:
            logger.bind(
                module="task_runtime",
                agent_id=agent_id,
                error=str(exc),
            ).error(f"创建 worktree 异常: {agent_id}")
            return None

    async def cleanup_worktree(self, agent_id: str) -> bool:
        """
        清理指定代理的 worktree。
        先 git worktree remove，再删除残留目录。
        """
        info = self._active_worktrees.pop(agent_id, None)
        worktree_path = info.path if info else str(self._worktree_root / agent_id)

        try:
            if os.path.exists(worktree_path):
                # 尝试 git worktree remove
                cmd = ["git", "worktree", "remove", worktree_path, "--force"]
                process = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=str(self._base_dir),
                )
                await process.communicate()

                # 清理残留目录
                if os.path.exists(worktree_path):
                    shutil.rmtree(worktree_path, ignore_errors=True)

            # 清理 worktree 列表中的引用
            await self._prune_worktrees()

            logger.bind(
                module="task_runtime",
                agent_id=agent_id,
            ).info(f"worktree 已清理: {agent_id}")
            return True

        except Exception as exc:
            logger.bind(
                module="task_runtime",
                agent_id=agent_id,
                error=str(exc),
            ).warning(f"清理 worktree 异常: {agent_id}")
            return False

    async def list_worktrees(self) -> List[Dict[str, Any]]:
        """列出当前所有 git worktrees。"""
        try:
            cmd = ["git", "worktree", "list", "--porcelain"]
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(self._base_dir),
            )
            stdout, _ = await process.communicate()
            return self._parse_worktree_list(stdout.decode("utf-8", errors="replace"))
        except Exception:
            return []

    async def run_in_worktree(
        self,
        agent_id: str,
        command: str,
        *,
        cwd: Optional[str] = None,
        timeout_seconds: int = 300,
    ) -> Dict[str, Any]:
        """
        在指定 worktree 中执行命令。
        如果 agent 没有关联 worktree 则在基础目录中执行。
        """
        info = self._active_worktrees.get(agent_id)
        work_dir = info.path if info else str(self._base_dir)
        target_cwd = cwd or work_dir

        if not os.path.exists(target_cwd):
            return {"ok": False, "error": f"工作目录不存在: {target_cwd}"}

        try:
            process = await asyncio.create_subprocess_exec(
                *command.split(),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=target_cwd,
            )
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=timeout_seconds,
            )
            return {
                "ok": process.returncode == 0,
                "returncode": process.returncode,
                "stdout": stdout.decode("utf-8", errors="replace") if stdout else "",
                "stderr": stderr.decode("utf-8", errors="replace") if stderr else "",
                "work_dir": target_cwd,
            }
        except asyncio.TimeoutError:
            return {"ok": False, "error": f"命令执行超时 ({timeout_seconds}s)", "work_dir": target_cwd}
        except Exception as exc:
            return {"ok": False, "error": str(exc), "work_dir": target_cwd}

    # ── 内部方法 ──────────────────────────────────────────────

    async def _get_current_branch(self) -> str:
        """获取当前 git 分支名。"""
        try:
            cmd = ["git", "rev-parse", "--abbrev-ref", "HEAD"]
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(self._base_dir),
            )
            stdout, _ = await process.communicate()
            branch = stdout.decode("utf-8", errors="replace").strip()
            return branch or "main"
        except Exception:
            return "main"

    async def _prune_worktrees(self) -> None:
        """清理无效的 worktree 引用。"""
        try:
            cmd = ["git", "worktree", "prune"]
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(self._base_dir),
            )
            await process.communicate()
        except Exception:
            pass

    def _parse_worktree_list(self, output: str) -> List[Dict[str, Any]]:
        """解析 git worktree list --porcelain 输出。"""
        worktrees = []
        current = {}
        for line in output.splitlines():
            line = line.strip()
            if not line:
                if current:
                    worktrees.append(current)
                    current = {}
                continue
            if line.startswith("worktree "):
                current["path"] = line[len("worktree "):]
            elif line.startswith("HEAD "):
                current["head"] = line[len("HEAD "):]
            elif line.startswith("branch "):
                current["branch"] = line[len("branch "):]
        if current:
            worktrees.append(current)
        return worktrees


# 模块级单例
worktree_manager = WorktreeManager()
