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
    支持 project_dir 和 workspace_dir 的物理隔离。
    """

    def __init__(self, project_dir: str, workspace_dir: Optional[str] = None):
        self.project_dir = Path(project_dir).resolve()
        self.workspace_dir = Path(workspace_dir).resolve() if workspace_dir else self.project_dir
        self._available: Optional[bool] = None
        self._use_worktree: bool = False
        self._worktree_path: Optional[Path] = None

    def ensure_project_dir(self) -> Path:
        """
        确保项目目录存在并初始化 git 仓库（如果需要）。
        项目目录必须是 workspace_dir 的子目录，实现物理隔离。

        Returns:
            已验证的项目目录路径

        Raises:
            ValueError: 当项目目录试图突破工作区隔离时
        """
        # 验证隔离：project_dir 必须是 workspace_dir 的子目录
        try:
            self.project_dir.relative_to(self.workspace_dir)
        except ValueError:
            # project_dir 不在 workspace_dir 内，自动创建隔离目录
            safe_dir = self.workspace_dir / "coding_projects" / self.project_dir.name
            safe_dir.mkdir(parents=True, exist_ok=True)
            logger.bind(
                event="coding_isolation_enforced",
                original=str(self.project_dir),
                isolated=str(safe_dir),
            ).warning("项目目录不在工作区内，已自动创建隔离目录")
            self.project_dir = safe_dir

        # 确保目录存在
        self.project_dir.mkdir(parents=True, exist_ok=True)

        # 初始化 git 仓库（如果不存在）
        if not (self.project_dir / ".git").exists():
            try:
                subprocess.run(
                    ["git", "init"],
                    cwd=str(self.project_dir),
                    capture_output=True,
                    timeout=10,
                )
                # 创建初始提交以便 worktree 操作
                readme = self.project_dir / "README.md"
                readme.write_text(f"# {self.project_dir.name}\n\n由 Open-AwA Coding 模式创建。\n")
                subprocess.run(
                    ["git", "add", "-A"],
                    cwd=str(self.project_dir),
                    capture_output=True,
                    timeout=10,
                )
                subprocess.run(
                    ["git", "commit", "-m", "Initial commit by Open-AwA"],
                    cwd=str(self.project_dir),
                    capture_output=True,
                    timeout=10,
                )
            except Exception as e:
                logger.warning(f"Git 仓库初始化失败: {str(e)}")

        return self.project_dir

    def enable_worktree(self, base_branch: str = "main") -> Path:
        """
        启用 worktree 隔离模式。
        创建独立的 git worktree，任务完成后自动清理。

        Args:
            base_branch: 基础分支

        Returns:
            worktree 目录路径
        """
        import uuid
        worktree_name = f"coding_{uuid.uuid4().hex[:8]}"
        worktree_dir = self.workspace_dir / ".worktrees" / worktree_name
        worktree_dir.mkdir(parents=True, exist_ok=True)

        try:
            subprocess.run(
                ["git", "worktree", "add", str(worktree_dir), base_branch],
                cwd=str(self.project_dir),
                capture_output=True,
                timeout=30,
                check=True,
            )
            self._use_worktree = True
            self._worktree_path = worktree_dir
            logger.bind(event="worktree_created", path=str(worktree_dir)).info("Git worktree 已创建")
            return worktree_dir
        except subprocess.CalledProcessError as e:
            logger.warning(f"Worktree 创建失败: {str(e)}，将使用原目录")
            return self.project_dir

    def cleanup_worktree(self):
        """
        清理 worktree（如果启用了 worktree 模式）。
        """
        if not self._use_worktree or not self._worktree_path:
            return

        try:
            subprocess.run(
                ["git", "worktree", "remove", str(self._worktree_path), "--force"],
                cwd=str(self.project_dir),
                capture_output=True,
                timeout=15,
            )
            # 确保目录已删除
            import shutil
            if self._worktree_path.exists():
                shutil.rmtree(self._worktree_path, ignore_errors=True)
            logger.bind(event="worktree_cleaned", path=str(self._worktree_path)).info("Worktree 已清理")
        except Exception as e:
            logger.warning(f"清理 worktree 失败: {str(e)}")
            # 如果 git worktree remove 失败，强制删除目录
            import shutil
            shutil.rmtree(str(self._worktree_path), ignore_errors=True)

        self._use_worktree = False
        self._worktree_path = None

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
