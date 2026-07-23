"""持久化人格池，用于缓存和重用生成的测试人格。

将成功生成的人格存储到磁盘，以便在多次优化运行间复用，
避免昂贵的 SDK 调用。

目录结构：
    data/eval/persona_pool/
    ├── init/                          # 用于 init profile 任务
    │   ├── INTJ_hardcore_specialist_a1b2.json
    │   └── ENFP_casual_generalist_c3d4.json
    └── update/                        # 用于增量更新任务
        ├── INTJ_hardcore_specialist_new_interest_e5f6.json
        └── ISTP_moderate_specialist_abandon_g7h8.json
"""

from __future__ import annotations

import hashlib
import json
import logging
import random
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class PersonaPool:
    """已生成人格的缓存，以约束签名为键。"""

    def __init__(self, pool_dir: Path | None = None) -> None:
        self._dir = pool_dir or Path("data/eval/persona_pool")
        self._dir.mkdir(parents=True, exist_ok=True)

    def _task_dir(self, task: str) -> Path:
        d = self._dir / task
        d.mkdir(parents=True, exist_ok=True)
        return d

    @staticmethod
    def _signature(constraints: dict[str, str]) -> str:
        """从约束构建人类可读且唯一的键。"""
        parts = [
            constraints.get("mbti", "X"),
            constraints.get("depth", "X"),
            constraints.get("interest_breadth", "X"),
        ]
        # update 任务人格需包含 shift 类型
        shift = constraints.get("shift")
        if shift:
            parts.append(shift)
        base = "_".join(parts)
        # 添加短哈希以避免相同约束集产生冲突
        h = hashlib.md5(json.dumps(constraints, sort_keys=True).encode()).hexdigest()[:6]
        return f"{base}_{h}"

    def save(
        self,
        task: str,
        constraints: dict[str, str],
        data: dict[str, Any],
    ) -> Path:
        """将成功生成的人格保存到池中。"""
        sig = self._signature(constraints)
        task_dir = self._task_dir(task)
        # 为此签名查找下一个可用索引
        existing = list(task_dir.glob(f"{sig}_*.json"))
        idx = len(existing)
        path = task_dir / f"{sig}_{idx:02d}.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(
                {"constraints": constraints, "data": data},
                f,
                ensure_ascii=False,
                indent=2,
            )
        logger.info("Persona saved to pool: %s", path.name)
        return path

    def load_matching(
        self,
        task: str,
        constraints: dict[str, str],
    ) -> dict[str, Any] | None:
        """加载一个匹配给定约束的随机缓存人格。

        返回人格数据 dict，如果没有匹配则返回 None。
        """
        task_dir = self._task_dir(task)
        sig = self._signature(constraints)
        matches = list(task_dir.glob(f"{sig}_*.json"))
        if not matches:
            # 兜底：尝试任何具有相同 mbti + depth 的人格
            mbti = constraints.get("mbti", "")
            depth = constraints.get("depth", "")
            matches = [p for p in task_dir.glob("*.json") if f"{mbti}_{depth}" in p.stem]
        if not matches:
            return None
        path = random.choice(matches)
        with open(path, encoding="utf-8") as f:
            cached = json.load(f)
        logger.info("Persona loaded from pool: %s", path.name)
        data = cached.get("data") if isinstance(cached, dict) else None
        return data if isinstance(data, dict) else None

    def load_any(self, task: str) -> dict[str, Any] | None:
        """从池中为指定任务加载任意一个随机人格。"""
        task_dir = self._task_dir(task)
        matches = list(task_dir.glob("*.json"))
        if not matches:
            return None
        path = random.choice(matches)
        with open(path, encoding="utf-8") as f:
            cached = json.load(f)
        logger.info("Persona loaded (any) from pool: %s", path.name)
        data = cached.get("data") if isinstance(cached, dict) else None
        return data if isinstance(data, dict) else None

    def count(self, task: str) -> int:
        """返回指定任务缓存人格的数量。"""
        return len(list(self._task_dir(task).glob("*.json")))
