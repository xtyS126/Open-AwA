"""
Git 集成模块 — 提供 Git 仓库操作：状态查询、差异比较、提交和分支管理。
"""
import subprocess
from pathlib import Path
from typing import Optional


class GitIntegration:
    """
    Git 集成服务，通过调用 git CLI 实现版本控制操作。
    """

    def __init__(self, repo_dir: str):
        self.repo_dir = Path(repo_dir).resolve()
        self._git_dir = self.repo_dir / ".git"

    def is_repo(self) -> bool:
        """检查是否为 Git 仓库。"""
        return self._git_dir.exists()

    def _run(self, *args: str, timeout: int = 30) -> tuple[int, str, str]:
        """执行 git 命令。"""
        try:
            result = subprocess.run(
                ["git", *args],
                cwd=str(self.repo_dir),
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            return result.returncode, result.stdout, result.stderr
        except subprocess.TimeoutExpired:
            return -1, "", "命令超时"
        except FileNotFoundError:
            return -1, "", "Git 未安装"

    def get_status(self) -> dict:
        """
        获取仓库状态。
        """
        if not self.is_repo():
            return {"error": "不是 Git 仓库"}

        rc, out, err = self._run("status", "--porcelain", "-b")
        if rc != 0:
            return {"error": err or "获取状态失败"}

        lines = out.strip().split("\n") if out.strip() else []
        branch_line = ""
        changes = []
        for line in lines:
            if line.startswith("## "):
                branch_line = line[3:]
            elif len(line) >= 2:
                status_code = line[:2]
                filename = line[3:]
                changes.append({"status": status_code.strip(), "file": filename})

        return {
            "branch": branch_line,
            "changes": changes,
            "changed_count": len(changes),
            "is_clean": len(changes) == 0,
        }

    def get_diff(self, file_path: Optional[str] = None, staged: bool = False) -> dict:
        """
        获取文件差异。
        """
        args = ["diff"]
        if staged:
            args.append("--staged")
        if file_path:
            args.append("--")
            args.append(file_path)

        rc, out, err = self._run(*args)
        if rc != 0:
            return {"error": err or "获取差异失败"}
        return {"diff": out, "file": file_path or "all"}

    def get_log(self, max_count: int = 20) -> dict:
        """
        获取提交日志。
        """
        rc, out, err = self._run(
            "log", f"--max-count={max_count}",
            "--format=%h|%s|%an|%ar",
            timeout=10,
        )
        if rc != 0:
            return {"error": err or "获取日志失败"}

        commits = []
        for line in out.strip().split("\n"):
            if not line:
                continue
            parts = line.split("|", 3)
            if len(parts) >= 4:
                commits.append({
                    "hash": parts[0],
                    "message": parts[1],
                    "author": parts[2],
                    "date": parts[3],
                })

        return {"commits": commits, "count": len(commits)}

    def commit(self, message: str, files: Optional[list[str]] = None) -> dict:
        """
        提交更改。
        """
        if files:
            add_rc, _, add_err = self._run("add", "--", *files)
            if add_rc != 0:
                return {"error": f"暂存失败: {add_err}"}
        else:
            self._run("add", "-A")

        rc, out, err = self._run("commit", "-m", message)
        if rc != 0:
            return {"error": err or "提交失败"}
        return {"message": "提交成功", "output": out}

    def get_branches(self) -> dict:
        """
        获取分支列表。
        """
        rc, out, err = self._run("branch", "-a")
        if rc != 0:
            return {"error": err or "获取分支失败"}

        branches = []
        for line in out.strip().split("\n"):
            branch = line.strip()
            is_current = branch.startswith("*")
            name = branch[2:] if is_current else branch
            branches.append({"name": name, "current": is_current})

        return {"branches": branches}

    def create_branch(self, name: str) -> dict:
        """
        创建新分支。
        """
        rc, out, err = self._run("checkout", "-b", name)
        if rc != 0:
            return {"error": err or "创建分支失败"}
        return {"message": f"分支 '{name}' 已创建", "branch": name}

    def switch_branch(self, name: str) -> dict:
        """
        切换分支。
        """
        rc, out, err = self._run("checkout", name)
        if rc != 0:
            return {"error": err or "切换分支失败"}
        return {"message": f"已切换到 '{name}'", "branch": name}
