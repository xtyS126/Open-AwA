"""评估会话的结构化运行日志。

为每次运行创建一个目录，存放所有产物：原始输入、prompt、
LLM 响应、中间结果和最终评估报告。

目录结构：
    data/eval/runs/<task>_<timestamp>/
    ├── 00_input/
    │   ├── history.json
    │   ├── favorites.json
    │   ├── following.json
    │   └── events.json
    ├── 01_preference/
    │   ├── prompt.txt
    │   ├── response.txt
    │   └── result.json
    ├── 02_profile/
    │   ├── prompt.txt
    │   ├── response.txt
    │   └── result.json
    ├── 03_eval/
    │   ├── ground_truth.json
    │   ├── predicted.json
    │   └── eval_report.json
    ├── 04_optimizer/
    │   ├── prompt.txt
    │   ├── response.txt
    │   └── changes.json
    └── summary.json
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_LOG_FORMAT = "%(asctime)s %(name)s %(message)s"
_LOG_DATEFMT = "%H:%M:%S"


def setup_logging(*, log_file: Path | None = None, level: int = logging.INFO) -> None:
    """配置 root logger：stderr 控制台 + 可选文件 handler。

    在脚本启动时调用一次。如果给定 *log_file*，每条日志记录
    （来自任何 logger）也会写入该文件，从而完整保留运行记录到磁盘。
    """
    root = logging.getLogger()
    root.setLevel(level)

    # 移除任何已有 handler（例如来自先前 basicConfig 的）
    for h in root.handlers[:]:
        root.removeHandler(h)

    # 控制台 → stderr（始终不缓冲）
    console = logging.StreamHandler(sys.stderr)
    console.setLevel(level)
    console.setFormatter(logging.Formatter(_LOG_FORMAT, datefmt=_LOG_DATEFMT))
    root.addHandler(console)

    # 文件 → run_dir/run.log
    if log_file is not None:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(log_file, encoding="utf-8")
        fh.setLevel(level)
        fh.setFormatter(
            logging.Formatter(
                "%(asctime)s %(name)s [%(levelname)s] %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )
        root.addHandler(fh)


class RunLogger:
    """单次评估运行的结构化 logger。"""

    def __init__(
        self,
        *,
        task: str,
        data_dir: Path | None = None,
        run_id: str | None = None,
    ) -> None:
        self._task = task
        ts = run_id or datetime.now().strftime("%Y%m%dT%H%M%S")
        base = (data_dir or Path("data")) / "eval" / "runs" / f"{task}_{ts}"
        base.mkdir(parents=True, exist_ok=True)
        self._base = base
        self._step_counter = 0
        self._summary: dict[str, Any] = {
            "task": task,
            "run_id": ts,
            "started_at": datetime.now().isoformat(),
            "steps": [],
        }
        logger.info("RunLogger: %s", self._base)

    def setup_file_logging(self, level: int = logging.INFO) -> Path:
        """在运行目录中设置带文件 handler 的 root logging。

        返回日志文件路径。
        """
        log_path = self._base / "run.log"
        setup_logging(log_file=log_path, level=level)
        logger.info("File logging enabled: %s", log_path)
        return log_path

    @property
    def run_dir(self) -> Path:
        return self._base

    # -- 步骤管理 --

    def step(self, name: str) -> RunStep:
        """创建一个新的步骤目录。"""
        self._step_counter += 1
        prefix = f"{self._step_counter:02d}"
        step_dir = self._base / f"{prefix}_{name}"
        step_dir.mkdir(parents=True, exist_ok=True)
        step = RunStep(step_dir, name)
        self._summary["steps"].append({"step": prefix, "name": name, "dir": str(step_dir.name)})
        return step

    # -- Epoch 支持（用于自动优化）--

    def epoch_dir(self, epoch: int) -> Path:
        d = self._base / f"epoch_{epoch:03d}"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def persona_dir(self, epoch: int, persona_idx: int) -> RunStep:
        d = self.epoch_dir(epoch) / f"persona_{persona_idx:02d}"
        d.mkdir(parents=True, exist_ok=True)
        return RunStep(d, f"epoch{epoch}_persona{persona_idx}")

    # -- 摘要 --

    def finish(self, **extra: Any) -> Path:
        """写入 summary.json 并返回其路径。"""
        self._summary["finished_at"] = datetime.now().isoformat()
        self._summary.update(extra)
        path = self._base / "summary.json"
        _write_json(path, self._summary)
        logger.info("Run finished: %s", path)
        return path


class RunStep:
    """运行中的一个步骤，由目录支撑。"""

    def __init__(self, directory: Path, name: str) -> None:
        self._dir = directory
        self._dir.mkdir(parents=True, exist_ok=True)
        self._name = name

    @property
    def dir(self) -> Path:
        return self._dir

    def save_json(self, filename: str, data: Any) -> Path:
        """保存一个 JSON 产物。"""
        path = self._dir / filename
        _write_json(path, data)
        return path

    def save_text(self, filename: str, text: str) -> Path:
        """保存一个文本产物（prompt、response 等）。"""
        path = self._dir / filename
        path.write_text(text, encoding="utf-8")
        return path

    def save_prompt(self, messages: list[dict[str, str]]) -> Path:
        """将 LLM prompt 消息保存为可读文本。"""
        parts: list[str] = []
        for msg in messages:
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            parts.append(f"=== {role.upper()} ===\n{content}")
        return self.save_text("prompt.txt", "\n\n".join(parts))

    def save_prompt_and_response(
        self,
        messages: list[dict[str, str]],
        response: str,
        parsed: Any = None,
    ) -> None:
        """同时保存 prompt、原始响应和解析结果。"""
        self.save_prompt(messages)
        self.save_text("response.txt", response)
        if parsed is not None:
            self.save_json("result.json", parsed)


def _write_json(path: Path, data: Any) -> None:
    """写入支持中文的 JSON。"""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, default=str)
