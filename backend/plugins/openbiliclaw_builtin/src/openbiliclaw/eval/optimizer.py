"""PromptOptimizer — 归因驱动的 prompt 和参数优化。

将评估偏差映射回具体的 prompt/参数，
生成针对性修改（利用）或随机扰动（探索）。
支持 commit/rollback 以安全实验。
"""

from __future__ import annotations

import hashlib
import json
import logging
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from openbiliclaw.eval.evaluator import FIELD_TO_PARAM, FieldScore

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 参数空间
# ---------------------------------------------------------------------------


@dataclass
class ContinuousParam:
    """可通过扰动优化的数值参数。"""

    name: str
    file_path: str
    accessor: str  # 值的 dot-path（例如 "decay_factor_per_week"）
    current: float = 0.0
    min_val: float = 0.0
    max_val: float = 1.0
    step: float = 0.05


@dataclass
class PromptParam:
    """通过 LLM 重写优化的 prompt 模板参数。"""

    name: str
    file_path: str
    function_name: str
    current_hash: str = ""


@dataclass
class ParamChange:
    """单个参数修改。"""

    param_name: str
    change_type: str  # "continuous" / "prompt"
    old_value: object = None
    new_value: object = None
    description: str = ""
    file_path: str = ""


# ---------------------------------------------------------------------------
# 默认参数注册表
# ---------------------------------------------------------------------------

_SRC = "src/openbiliclaw"

# optimizer 允许修改的文件白名单
MODIFIABLE_FILES: list[str] = [
    f"{_SRC}/llm/prompts.py",
    f"{_SRC}/soul/layer_updaters.py",
    f"{_SRC}/soul/preference_analyzer.py",
    f"{_SRC}/soul/profile_builder.py",
    f"{_SRC}/soul/profile.py",
    f"{_SRC}/soul/pipeline.py",
    f"{_SRC}/soul/engine.py",
    f"{_SRC}/recommendation/engine.py",
    f"{_SRC}/recommendation/curator.py",
    f"{_SRC}/discovery/strategies/search.py",
    f"{_SRC}/discovery/strategies/trending.py",
    f"{_SRC}/discovery/strategies/related_chain.py",
    f"{_SRC}/discovery/strategies/explore.py",
]

DEFAULT_CONTINUOUS_PARAMS: list[ContinuousParam] = [
    ContinuousParam(
        name="interest_decay_factor",
        file_path=f"{_SRC}/soul/preference_analyzer.py",
        accessor="decay_factor_per_week",
        current=0.9,
        min_val=0.7,
        max_val=0.99,
        step=0.03,
    ),
    ContinuousParam(
        name="candidate_confidence_threshold",
        file_path=f"{_SRC}/soul/engine.py",
        accessor="_candidate_ready_for_learning.confidence",
        current=0.8,
        min_val=0.5,
        max_val=0.95,
        step=0.05,
    ),
    ContinuousParam(
        name="candidate_occurrence_threshold",
        file_path=f"{_SRC}/soul/engine.py",
        accessor="_candidate_ready_for_learning.occurrences",
        current=2.0,
        min_val=1.0,
        max_val=5.0,
        step=1.0,
    ),
]

DEFAULT_PROMPT_PARAMS: list[PromptParam] = [
    PromptParam(
        name="preference_analysis_prompt",
        file_path=f"{_SRC}/llm/prompts.py",
        function_name="build_preference_analysis_prompt",
    ),
    PromptParam(
        name="soul_profile_prompt",
        file_path=f"{_SRC}/llm/prompts.py",
        function_name="build_soul_profile_prompt",
    ),
    PromptParam(
        name="awareness_prompt",
        file_path=f"{_SRC}/llm/prompts.py",
        function_name="build_awareness_prompt",
    ),
    PromptParam(
        name="insight_prompt",
        file_path=f"{_SRC}/llm/prompts.py",
        function_name="build_insight_prompt",
    ),
    PromptParam(
        name="speculation_generation_prompt",
        file_path=f"{_SRC}/llm/prompts.py",
        function_name="build_speculation_generation_prompt",
    ),
]


# ---------------------------------------------------------------------------
# PromptOptimizer
# ---------------------------------------------------------------------------


class PromptOptimizer:
    """将评估偏差归因到参数并生成优化。

    支持两种后端：
    - Claude Agent SDK（默认）：使用 `run_optimizer_agent()` — agent
      可以自主 Read/Edit/Grep 文件并运行测试
    - 直接 LLM：传入 `llm` 实例用于单元测试
    """

    def __init__(
        self,
        llm: Any = None,
        *,
        use_agent_sdk: bool = True,
        project_root: Path | None = None,
        continuous_params: list[ContinuousParam] | None = None,
        prompt_params: list[PromptParam] | None = None,
        modifiable_files: list[str] | None = None,
        field_to_param: dict[str, str] | None = None,
    ) -> None:
        self._llm = llm
        self._use_agent_sdk = use_agent_sdk and llm is None
        self._project_root = project_root or Path(".")
        self._continuous = continuous_params or list(DEFAULT_CONTINUOUS_PARAMS)
        self._prompts = prompt_params or list(DEFAULT_PROMPT_PARAMS)
        self._modifiable_files = modifiable_files or list(MODIFIABLE_FILES)
        self._field_to_param = field_to_param or dict(FIELD_TO_PARAM)
        self._pending_changes: list[ParamChange] = []
        self._backup: dict[str, str] = {}  # file_path → 原始内容

    async def exploit(
        self,
        worst_fields: list[FieldScore],
    ) -> list[ParamChange]:
        """生成修复最差评分字段的改动（利用）。"""
        if not worst_fields:
            return []

        # Agent SDK 路径：让 optimizer agent 读取文件并提出修改
        if self._use_agent_sdk:
            return await self._exploit_via_agent(worst_fields)

        changes: list[ParamChange] = []
        targeted_params: set[str] = set()

        for field_score in worst_fields[:2]:  # 聚焦最差的 top-2
            param_name = self._field_to_param.get(
                f"{field_score.layer}.{field_score.field}",
                "",
            )
            if not param_name or param_name in targeted_params:
                continue
            targeted_params.add(param_name)

            # 检查是否映射到连续参数
            cont = self._find_continuous(param_name)
            if cont:
                change = self._perturb_continuous(cont, direction="improve")
                if change:
                    changes.append(change)
                continue

            # 否则是 prompt 参数 — 生成 LLM 驱动的修改
            prompt_param = self._find_prompt(param_name)
            if prompt_param:
                change = await self._optimize_prompt(prompt_param, field_score)
                if change:
                    changes.append(change)

        return changes

    async def _exploit_via_agent(
        self,
        worst_fields: list[FieldScore],
    ) -> list[ParamChange]:
        """使用 Claude Agent SDK 自主读取文件并提出修复。"""
        from openbiliclaw.eval.agents import run_optimizer_agent

        eval_data = {
            "worst_fields": [
                {"layer": f.layer, "field": f.field, "score": f.score, "deviation": f.deviation}
                for f in worst_fields[:5]
            ],
            "attributions": [
                (
                    f"{f.layer}.{f.field} → "
                    f"{self._field_to_param.get(f'{f.layer}.{f.field}', 'unknown')}"
                )
                for f in worst_fields[:5]
            ],
        }
        result = await run_optimizer_agent(eval_data, self._project_root)

        changes: list[ParamChange] = []
        for c in result.get("changes", []):
            if not isinstance(c, dict):
                continue
            changes.append(
                ParamChange(
                    param_name=str(c.get("file_path", "")),
                    change_type="prompt",
                    old_value=str(c.get("old_text", "")),
                    new_value=str(c.get("new_text", "")),
                    description=str(c.get("reason", "")),
                    file_path=str(c.get("file_path", "")),
                )
            )
        return changes

    async def explore(self) -> list[ParamChange]:
        """对参数进行随机扰动（探索）。"""
        all_params: list[str] = [p.name for p in self._continuous] + [p.name for p in self._prompts]
        if not all_params:
            return []

        target = random.choice(all_params)

        cont = self._find_continuous(target)
        if cont:
            change = self._perturb_continuous(cont, direction="random")
            return [change] if change else []

        prompt_param = self._find_prompt(target)
        if prompt_param:
            change = await self._explore_prompt(prompt_param)
            return [change] if change else []

        return []

    def apply(self, changes: list[ParamChange]) -> int:
        """应用参数改动（写入文件）。返回成功改动的数量。"""
        self._pending_changes = changes
        applied = 0
        for change in changes:
            if not change.file_path:
                continue
            # 白名单检查
            if change.file_path not in self._modifiable_files:
                logger.warning(
                    "File not in MODIFIABLE_FILES whitelist, skipping: %s",
                    change.file_path,
                )
                continue
            full_path = self._project_root / change.file_path
            if not full_path.exists():
                logger.warning("File not found: %s", change.file_path)
                continue
            # 备份原始内容
            if change.file_path not in self._backup:
                self._backup[change.file_path] = full_path.read_text(encoding="utf-8")

            if change.change_type == "continuous":
                ok = self._apply_continuous_change(full_path, change)
            else:
                # "prompt" 和 "pipeline" 都使用文本替换
                ok = self._apply_prompt_change(full_path, change)
            if ok:
                applied += 1
            else:
                logger.warning(
                    "Change not applied (old_text not found): %s — %s",
                    change.file_path,
                    change.description[:60],
                )
        return applied

    def has_pipeline_changes(self) -> bool:
        """检查是否有待处理改动触及非 prompt 文件。"""
        prompt_file = f"{_SRC}/llm/prompts.py"
        return any(c.file_path and c.file_path != prompt_file for c in self._pending_changes)

    def validate_with_tests(self, timeout: int = 60) -> tuple[bool, str]:
        """运行 pytest 验证 pipeline 改动。返回 (passed, output)。"""
        import subprocess

        try:
            result = subprocess.run(
                [
                    ".venv/bin/python",
                    "-m",
                    "pytest",
                    "tests/",
                    "-x",
                    "-q",
                    "-W",
                    "ignore::DeprecationWarning",
                ],
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=str(self._project_root),
            )
            passed = result.returncode == 0
            output = (result.stdout + result.stderr)[-500:]
            return passed, output
        except subprocess.TimeoutExpired:
            return False, "pytest timed out"
        except Exception as exc:
            return False, f"pytest failed to run: {exc}"

    def commit(self) -> None:
        """确认改动 — 清空备份。"""
        self._backup.clear()
        self._pending_changes.clear()
        logger.info("Optimizer committed changes")

    def rollback(self) -> None:
        """回滚改动 — 从备份恢复。"""
        for file_path, content in self._backup.items():
            full_path = self._project_root / file_path
            full_path.write_text(content, encoding="utf-8")
            logger.info("Rolled back %s", file_path)
        self._backup.clear()
        self._pending_changes.clear()

    def get_change_log(self) -> list[dict[str, str]]:
        """返回待处理改动的描述。"""
        return [
            {"param": c.param_name, "type": c.change_type, "description": c.description}
            for c in self._pending_changes
        ]

    # -- 内部辅助函数 ------------------------------------------------------

    def _find_continuous(self, name: str) -> ContinuousParam | None:
        for p in self._continuous:
            if p.name == name:
                return p
        return None

    def _find_prompt(self, name: str) -> PromptParam | None:
        for p in self._prompts:
            if p.name == name:
                return p
        return None

    def _perturb_continuous(
        self,
        param: ContinuousParam,
        *,
        direction: str,
    ) -> ParamChange | None:
        delta = random.choice([-param.step, param.step]) if direction == "random" else param.step

        new_val = max(param.min_val, min(param.max_val, param.current + delta))
        if new_val == param.current:
            return None

        change = ParamChange(
            param_name=param.name,
            change_type="continuous",
            old_value=param.current,
            new_value=new_val,
            description=f"{param.name}: {param.current:.3f} → {new_val:.3f}",
            file_path=param.file_path,
        )
        param.current = new_val
        return change

    async def _optimize_prompt(
        self,
        param: PromptParam,
        worst: FieldScore,
    ) -> ParamChange | None:
        """使用 LLM 生成针对性的 prompt 修复。"""
        full_path = self._project_root / param.file_path
        if not full_path.exists():
            return None

        current_content = full_path.read_text(encoding="utf-8")
        # 提取函数体
        func_start = current_content.find(f"def {param.function_name}")
        if func_start < 0:
            return None

        # 查找下一个函数或文件末尾
        next_def = current_content.find("\ndef ", func_start + 1)
        end = next_def if next_def > 0 else len(current_content)
        func_body = current_content[func_start:end]

        messages = [
            {
                "role": "system",
                "content": (
                    "你是一个 prompt 优化器。根据评估偏差，对 prompt 函数提出最小化修改。\n"
                    "只修改 prompt 文本中的特定片段，不要重写整个函数。\n"
                    '返回 JSON: {"old_text": "要替换的原文", "new_text": "替换后的文本", '
                    '"reason": "修改原因"}'
                ),
            },
            {
                "role": "user",
                "content": (
                    f"评估偏差:\n"
                    f"  层: {worst.layer}\n"
                    f"  字段: {worst.field}\n"
                    f"  分数: {worst.score:.2f}\n"
                    f"  偏差: {worst.deviation}\n\n"
                    f"当前 prompt 函数:\n```python\n{func_body[:3000]}\n```\n\n"
                    f"请提出一个最小化的 prompt 文本修改来改善这个偏差。"
                ),
            },
        ]

        try:
            response = await self._llm.complete(
                messages,
                temperature=0.4,
                max_tokens=2048,
                json_mode=True,
            )
            fix = json.loads(response.content)
            if not isinstance(fix, dict):
                return None

            old_text = str(fix.get("old_text", ""))
            new_text = str(fix.get("new_text", ""))
            reason = str(fix.get("reason", ""))
            if not old_text or not new_text or old_text == new_text:
                return None

            return ParamChange(
                param_name=param.name,
                change_type="prompt",
                old_value=old_text,
                new_value=new_text,
                description=f"{param.name}: {reason}",
                file_path=param.file_path,
            )
        except Exception:
            logger.warning("Failed to generate prompt optimization for %s", param.name)
            return None

    async def _explore_prompt(self, param: PromptParam) -> ParamChange | None:
        """生成随机 prompt 变体用于探索。"""
        full_path = self._project_root / param.file_path
        if not full_path.exists():
            return None

        current_content = full_path.read_text(encoding="utf-8")
        func_start = current_content.find(f"def {param.function_name}")
        if func_start < 0:
            return None

        next_def = current_content.find("\ndef ", func_start + 1)
        end = next_def if next_def > 0 else len(current_content)
        func_body = current_content[func_start:end]

        messages = [
            {
                "role": "system",
                "content": (
                    "你是一个 prompt 探索器。对 prompt 提出一个创造性的小修改——"
                    "可以是更精确的措辞、增加一条规则、或调整输出格式。\n"
                    '返回 JSON: {"old_text": "原文", "new_text": "新文本", '
                    '"reason": "探索原因"}'
                ),
            },
            {
                "role": "user",
                "content": (
                    f"当前 prompt 函数:\n```python\n{func_body[:3000]}\n```\n\n"
                    f"请提出一个有创意的小修改。"
                ),
            },
        ]

        try:
            response = await self._llm.complete(
                messages,
                temperature=0.9,
                max_tokens=2048,
                json_mode=True,
            )
            fix = json.loads(response.content)
            if not isinstance(fix, dict):
                return None

            old_text = str(fix.get("old_text", ""))
            new_text = str(fix.get("new_text", ""))
            reason = str(fix.get("reason", ""))
            if not old_text or not new_text or old_text == new_text:
                return None

            return ParamChange(
                param_name=param.name,
                change_type="prompt",
                old_value=old_text,
                new_value=new_text,
                description=f"[explore] {param.name}: {reason}",
                file_path=param.file_path,
            )
        except Exception:
            logger.warning("Failed to explore prompt variation for %s", param.name)
            return None

    @staticmethod
    def _apply_continuous_change(path: Path, change: ParamChange) -> bool:
        """将连续参数改动应用到文件。"""
        content = path.read_text(encoding="utf-8")
        old_str = str(change.old_value)
        new_str = str(change.new_value)
        if old_str in content:
            content = content.replace(old_str, new_str, 1)
            path.write_text(content, encoding="utf-8")
            return True
        return False

    @staticmethod
    def _apply_prompt_change(path: Path, change: ParamChange) -> bool:
        """通过模糊空白匹配将 prompt 文本改动应用到文件。"""
        content = path.read_text(encoding="utf-8")
        old_text = str(change.old_value)
        new_text = str(change.new_value)

        # 先尝试精确匹配
        if old_text in content:
            content = content.replace(old_text, new_text, 1)
            path.write_text(content, encoding="utf-8")
            return True

        # 模糊：去除每行尾部空白后重试
        def _normalize(s: str) -> str:
            return "\n".join(line.rstrip() for line in s.splitlines())

        norm_content = _normalize(content)
        norm_old = _normalize(old_text)
        if norm_old in norm_content:
            # 通过匹配规范化位置找到原始区间
            start = norm_content.index(norm_old)
            # 反向映射：按相同行/列计数原始字符
            orig_lines = content.splitlines(keepends=True)
            norm_lines = norm_content.splitlines(keepends=True)
            char_count = 0
            norm_char_count = 0
            orig_start = 0
            for orig_line, norm_line in zip(orig_lines, norm_lines, strict=False):
                if norm_char_count + len(norm_line) > start and norm_char_count <= start:
                    offset_in_line = start - norm_char_count
                    orig_start = char_count + offset_in_line
                    break
                char_count += len(orig_line)
                norm_char_count += len(norm_line)

            # 通过计数原始中规范化 old_text 的长度找到结尾
            orig_end = orig_start
            norm_remaining = len(norm_old)
            for orig_line in content[orig_start:].splitlines(keepends=True):
                if norm_remaining <= 0:
                    break
                orig_end += len(orig_line)
                norm_remaining -= len(orig_line.rstrip()) + 1  # +1 为 \n

            content = content[:orig_start] + new_text + content[orig_end:]
            path.write_text(content, encoding="utf-8")
            logger.info("Applied change via fuzzy whitespace matching")
            return True

        # 模糊：规范化中英文标点
        def _normalize_punct(s: str) -> str:
            return (
                s.replace("。", ".")
                .replace("，", ",")
                .replace("：", ":")
                .replace("；", ";")
                .replace("（", "(")
                .replace("）", ")")
            )

        if _normalize_punct(old_text) in _normalize_punct(content):
            # 找到最佳匹配子串
            np_content = _normalize_punct(content)
            np_old = _normalize_punct(old_text)
            idx = np_content.index(np_old)
            # 由于只替换单个字符，字符位置 1:1 对应
            content = content[:idx] + new_text + content[idx + len(old_text) :]
            path.write_text(content, encoding="utf-8")
            logger.info("Applied change via punctuation normalization")
            return True

        # 激进：将所有空白折叠为单个空格后尝试
        import re as _re

        def _collapse(s: str) -> str:
            return _re.sub(r"\s+", " ", s.strip())

        collapsed_content = _collapse(content)
        collapsed_old = _collapse(old_text)
        if collapsed_old and collapsed_old in collapsed_content:
            # 在原始内容中找到近似位置
            idx = collapsed_content.index(collapsed_old)
            # 通过计数非空白字符将折叠索引映射回原始
            orig_idx = 0
            collapsed_idx = 0
            for i, ch in enumerate(content):
                if collapsed_idx >= idx:
                    orig_idx = i
                    break
                if ch.isspace():
                    if i == 0 or not content[i - 1].isspace():
                        collapsed_idx += 1
                else:
                    collapsed_idx += 1
            # 同样找到结尾
            end_target = idx + len(collapsed_old)
            orig_end = orig_idx
            for i in range(orig_idx, len(content)):
                if collapsed_idx >= end_target:
                    orig_end = i
                    break
                ch = content[i]
                if ch.isspace():
                    if i == 0 or not content[i - 1].isspace():
                        collapsed_idx += 1
                else:
                    collapsed_idx += 1
            else:
                orig_end = len(content)

            content = content[:orig_idx] + new_text + content[orig_end:]
            path.write_text(content, encoding="utf-8")
            logger.info("Applied change via aggressive whitespace collapse")
            return True

        return False

    @staticmethod
    def _hash_content(content: str) -> str:
        return hashlib.sha256(content.encode()).hexdigest()[:12]
