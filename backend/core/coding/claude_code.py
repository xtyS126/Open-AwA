"""
Claude Code (CC) 集成适配器。
通过调用 claude CLI 实现编码任务的委托执行，捕获输出和文件变更。

支持两种执行路径：
1. ACP 协议（优先）：通过 acp_host.ACPService.run_turn 与 Claude Code Agent 交互，
   事件流聚合为兼容返回值。
2. subprocess（回退）：直接调用 claude CLI 子进程，捕获 stdout/stderr 与文件快照 diff。

当 prefer_acp=True 但 ACP SDK 未安装或 service 未初始化时，自动降级到 subprocess。
"""
import asyncio
import json
import os
import subprocess
import tempfile
import threading
from pathlib import Path
from typing import Any, Optional

from loguru import logger


class ClaudeCodeAdapter:
    """
    Claude Code CLI 适配器。
    将编码子任务委托给 claude CLI 执行，解析输出并捕获文件变更。
    支持 project_dir 和 workspace_dir 的物理隔离。

    优先走 ACP 协议（prefer_acp=True，默认），失败时回退到 subprocess。
    """

    def __init__(
        self,
        project_dir: str,
        workspace_dir: Optional[str] = None,
        prefer_acp: bool = True,
    ):
        self.project_dir = Path(project_dir).resolve()
        self.workspace_dir = Path(workspace_dir).resolve() if workspace_dir else self.project_dir
        self._available: Optional[bool] = None
        self._use_worktree: bool = False
        self._worktree_path: Optional[Path] = None
        # ACP 协议优先开关
        self.prefer_acp = prefer_acp
        # ACP 可用性标记，首次调用 _run_via_acp 时探测
        self._acp_available: bool = False
        # ACP 事件收集列表，由 _collect_acp_events 回调追加
        self._acp_events: list[dict[str, Any]] = []

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
        mode: str = "default",
        cwd: Optional[str] = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """
        运行 Claude Code 任务，优先走 ACP 协议，回退到 subprocess。

        Args:
            prompt: 任务提示词。
            mode: 执行模式，传递给 subprocess 路径。
            cwd: 工作目录；None 时使用 project_dir。
            **kwargs: 透传给 subprocess 路径的额外参数（auto_approve/max_turns/timeout 等）。

        Returns:
            包含 success/output/error/changed_files 等字段的结果字典。
        """
        # 优先尝试 ACP 模式
        if self.prefer_acp:
            try:
                acp_result = self._run_via_acp(prompt, cwd=cwd)
                if acp_result is not None:
                    return acp_result
            except Exception as e:
                logger.warning(
                    f"ACP 模式执行失败，回退到 subprocess: {e}",
                    exc_info=e,
                )

        # 回退到 subprocess
        return self._run_via_subprocess(prompt, mode=mode, cwd=cwd, **kwargs)

    def _run_via_acp(
        self,
        prompt: str,
        cwd: Optional[str] = None,
    ) -> Optional[dict[str, Any]]:
        """
        通过 ACP 协议执行 Claude Code 任务。

        检查 ACP 可用性，不可用时记录 cc_fallback_to_subprocess 日志并返回 None，
        由调用方走 subprocess 回退。ACP 可用时调用 ACPService.run_turn，聚合事件流
        为兼容旧格式的返回值。

        Args:
            prompt: 任务提示词。
            cwd: 工作目录；None 时使用 project_dir。

        Returns:
            聚合后的结果字典；当 ACP 不可用或 service 未初始化时返回 None。
        """
        # 探测 ACP SDK 可用性
        try:
            import acp_host  # noqa: F401
            import acp  # noqa: F401
            self._acp_available = True
        except ImportError:
            self._acp_available = False
            logger.bind(
                event="cc_fallback_to_subprocess",
                reason="acp_sdk_not_installed",
            ).warning("ACP SDK 未安装，回退到 subprocess 模式")
            return None

        # 获取 ACP service 实例
        from acp_host import get_acp_service

        service = get_acp_service()
        if service is None:
            logger.bind(
                event="cc_fallback_to_subprocess",
                reason="acp_service_not_initialized",
            ).warning("ACP service 未初始化，回退到 subprocess 模式")
            return None

        # 重置事件收集列表
        self._acp_events = []
        work_cwd = cwd or str(self.project_dir)

        logger.bind(
            event="cc_acp_task_start",
            cwd=work_cwd,
        ).info(f"ACP 模式任务开始: {prompt[:100]}...")

        # 调用 service.run_turn（async 方法，需桥接到同步上下文）
        result = self._run_async_safely(
            service.run_turn(
                chat_id="claude_code_adapter",
                agent="claude_code",
                prompt_blocks=[{"type": "text", "text": prompt}],
                cwd=work_cwd,
                on_message=self._collect_acp_events,
            )
        )

        return self._aggregate_acp_events(result)

    async def _collect_acp_events(
        self,
        payload: dict[str, Any],
        is_last: bool,
    ) -> None:
        """
        ACP 事件回调：把事件追加到内部列表。

        Args:
            payload: ACP 事件字典。
            is_last: 是否为最后一个事件。
        """
        self._acp_events.append(payload)

    def _aggregate_acp_events(self, run_turn_result: dict[str, Any]) -> dict[str, Any]:
        """
        把 ACP 事件流聚合为兼容旧格式的返回值。

        - success: True 当 status="completed"，False 当 status="error" 或其他
        - output: 拼接所有 type=="text" 事件的 text 字段
        - error: 当 status="error" 时含错误消息，否则 None
        - changed_files: 从 type=="tool_end" 事件的 locations/target 字段收集路径列表

        Args:
            run_turn_result: ACPService.run_turn 返回的结果字典。

        Returns:
            兼容旧格式的结果字典。
        """
        status = run_turn_result.get("status", "completed")

        # 聚合文本输出
        output_parts: list[str] = []
        for event in self._acp_events:
            if event.get("type") == "text":
                text = event.get("text", "")
                if text:
                    output_parts.append(text)
        output = "".join(output_parts)

        # 推导变更文件列表
        changed_files: list[str] = []
        for event in self._acp_events:
            if event.get("type") != "tool_end":
                continue
            # 兼容两种事件结构：locations 列表 或 target 字符串
            locations = event.get("locations")
            if isinstance(locations, list):
                for loc in locations:
                    if isinstance(loc, dict):
                        path = loc.get("path")
                    elif isinstance(loc, str):
                        path = loc
                    else:
                        path = None
                    if path and path not in changed_files:
                        changed_files.append(path)
            target = event.get("target")
            if isinstance(target, str) and target not in changed_files:
                changed_files.append(target)

        # 构造返回值
        success = status == "completed"
        error: Optional[str] = None
        if status == "error":
            error = run_turn_result.get("message") or run_turn_result.get("error") or "ACP 任务执行失败"
        elif status == "permission_required":
            error = "ACP 任务需要权限审批"

        return {
            "success": success,
            "output": output,
            "error": error,
            "changed_files": changed_files,
            "changed_count": len(changed_files),
            "status": status,
        }

    @staticmethod
    def _run_async_safely(coro: Any) -> Any:
        """
        安全运行异步协程：当前无事件循环时用 asyncio.run，
        已有运行中事件循环时在新线程的新 loop 中执行。

        Args:
            coro: 待执行的协程对象。

        Returns:
            协程返回值。

        Raises:
            协程内部抛出的异常会被重新抛出。
        """
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(coro)

        result_holder: dict[str, Any] = {}
        error_holder: dict[str, BaseException] = {}

        def _runner() -> None:
            """在新线程的新事件循环中运行协程。"""
            new_loop = asyncio.new_event_loop()
            asyncio.set_event_loop(new_loop)
            try:
                result_holder["value"] = new_loop.run_until_complete(coro)
            except BaseException as thread_error:
                error_holder["error"] = thread_error
            finally:
                new_loop.close()

        thread = threading.Thread(target=_runner, daemon=True)
        thread.start()
        thread.join(timeout=300.0)

        if "error" in error_holder:
            raise error_holder["error"]
        return result_holder.get("value")

    def _run_via_subprocess(
        self,
        prompt: str,
        mode: str = "default",
        cwd: Optional[str] = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """
        通过 subprocess 调用 claude CLI 执行任务（原有 run_task 逻辑）。

        Args:
            prompt: 任务提示词。
            mode: 执行模式（保留参数，现有逻辑未使用）。
            cwd: 工作目录；None 时使用 project_dir。
            **kwargs: auto_approve/max_turns/timeout 等参数。

        Returns:
            包含 success/exit_code/output/error/changed_files 等字段的结果字典。
        """
        # 兼容旧参数（保留所有现有逻辑）
        auto_approve: bool = kwargs.get("auto_approve", False)
        max_turns: Optional[int] = kwargs.get("max_turns")
        timeout: int = kwargs.get("timeout", 300)

        if not self.is_available():
            return {"error": "Claude Code CLI (claude) 不可用，请先安装"}

        cmd = ["claude"]

        # 确定工作目录：优先使用传入的 cwd，否则使用 project_dir
        work_dir = Path(cwd).resolve() if cwd else self.project_dir

        # 设置工作目录
        cmd.extend(["--cwd", str(work_dir)])

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
            logger.bind(event="cc_task_start", project=str(work_dir)).info(
                f"Claude Code 任务开始: {prompt[:100]}..."
            )
            result = subprocess.run(
                cmd,
                cwd=str(work_dir),
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
