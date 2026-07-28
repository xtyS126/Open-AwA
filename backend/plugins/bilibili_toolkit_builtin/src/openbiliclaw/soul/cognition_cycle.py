"""周期性认知循环 —— 节流的认知 + 洞察生成。

ProfileUpdatePipeline 在其 ``tick()`` 循环中调用 ``CognitionCycle.run_if_due()``。
每次调用时，循环会检查距上次成功运行是否已过足够时间（默认 12 小时），
若是则通过 LLM 后端的分析器重新生成认知笔记和洞察假设，并将结果
同步到 OnionProfile，使扩展弹窗的画像视图能展示它们。

状态持久化到 ``<data_dir>/memory/cognition_cycle_state.json``，
让节流逻辑能在进程重启后保留。

此模块的存在是为了填补一个曾经的「孤儿」缺口：AwarenessAnalyzer
和 InsightAnalyzer 已定义但运行时零调用方，因此
``profile.recent_awareness`` 和 ``profile.active_insights`` 总是空。
本循环将它们接入常规 tick 循环，并用成本感知的节流让 LLM 开销保持有界。
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from openbiliclaw.soul.awareness_analyzer import AwarenessGenerationError

if TYPE_CHECKING:
    from collections.abc import Iterator

    from openbiliclaw.memory.manager import MemoryManager
    from openbiliclaw.soul.awareness_analyzer import AwarenessAnalyzer
    from openbiliclaw.soul.insight_analyzer import InsightAnalyzer
    from openbiliclaw.soul.profile import AwarenessNote, InsightHypothesis

from openbiliclaw.soul.profile import (
    OnionProfile,
    awareness_note_from_dict,
    awareness_note_to_dict,
    insight_hypothesis_from_dict,
    insight_hypothesis_to_dict,
)

logger = logging.getLogger(__name__)

# 默认节流：每 12 小时生成一次认知 + 洞察。
DEFAULT_MIN_INTERVAL_SECONDS = 12 * 60 * 60

# --- 基于游标的增量读取（替代旧的固定 limit=50） ----
# 认知层读取 id > last_awareness_event_id 的事件，而不是最近 50 条窗口，
# 这样一个节流窗口内突发的 >50 条事件不会被静默丢弃，
# 而安静窗口也不会重复发送同样的事件。
#
# 单次认知运行折叠的、最新的、尚未处理事件数的上限。
# 在巨大积压下（例如长时间离线后的首次运行），水位线跳到最新事件，
# 超过此窗口的更老未处理事件会被跳过（记日志，不静默）以保持
# 「近期认知」的近期性。
_AWARENESS_BACKLOG_CAP = 900
# 每次 LLM 调用的批量大小。为现代长上下文模型（256k+）设计：
# 一条事件约 100 token，所以 300 条事件 ≈ 30-45k 输入 token ——
# 一个典型 12 小时窗口（即便重度使用）单次调用即可容纳，无需多余拆分。
# 分批只在病态积压时（一个窗口内 > 300 条新事件）才触发，
# 作为安全网，让最坏情况只是几次中等规模调用，而不是一次
# 上下文较小的 provider 可能噎住的 90k-token 调用。
_AWARENESS_EVENT_BATCH_SIZE = 300
# 已处理的近期事件（id <= 水位线）以只读形式并入第一批，
# 让观察在新增事件很少时仍保持趋势感知。
_AWARENESS_CONTEXT_LOOKBACK = 10

# 洞察读取 last_insight_awareness_index 之后的认知笔记（位置型游标 ——
# 笔记只追加），而不是完整认知历史，这样洞察 prompt 不会无限增长。
# 笔记比事件更密集（每条都是 LLM 写的观察），所以批量比认知层小，
# 但仍大到足以让真实运行（少数几条新笔记）一次调用完成。
_INSIGHT_NOTE_BACKLOG_CAP = 450
_INSIGHT_NOTE_BATCH_SIZE = 150

# 分批认知 LLM 调用的输出 token 预算。比通用 16k 默认值大，
# 让密集的事件/笔记批次能输出完整的 notes / hypotheses 数组而不被截断。
_COGNITION_MAX_TOKENS = 32768

# 附加到 OnionProfile（在 UI 中呈现）的笔记/洞察数量上限。
_PROFILE_AWARENESS_WINDOW = 8
_PROFILE_INSIGHT_WINDOW = 6

# 第一次和第二次认知尝试之间的退避。MiMo 502 和瞬时 JSON 形状
# 故障通常在短暂暂停后重试一次即可恢复；2s 足以躲过大多数可重试
# 突发，又不会让循环明显变长。
_AWARENESS_RETRY_BACKOFF_SECONDS = 2.0


@dataclass
class CognitionCycleResult:
    """一次认知循环运行的摘要。"""

    ran: bool = False
    throttled: bool = False
    awareness_generated: int = 0
    insight_generated: int = 0
    total_awareness_after: int = 0
    total_insight_after: int = 0
    errors: list[str] = field(default_factory=list)


class CognitionCycle:
    """节流的认知 + 洞察生成运行器。

    用法：
        cycle = CognitionCycle(
            memory=memory,
            awareness_analyzer=...,
            insight_analyzer=...,
            min_interval_seconds=43200,
        )
        result = await cycle.run_if_due()
    """

    def __init__(
        self,
        *,
        memory: MemoryManager,
        awareness_analyzer: AwarenessAnalyzer,
        insight_analyzer: InsightAnalyzer,
        min_interval_seconds: int = DEFAULT_MIN_INTERVAL_SECONDS,
    ) -> None:
        self._memory = memory
        self._awareness_analyzer = awareness_analyzer
        self._insight_analyzer = insight_analyzer
        self._min_interval_seconds = int(min_interval_seconds)

    # -- 公开 API -----------------------------------------------------------

    async def run_if_due(self, *, now: datetime | None = None) -> CognitionCycleResult:
        """若节流间隔已到，则运行认知 + 洞察生成。

        返回描述结果的对象。若因节流跳过，则返回
        ``CognitionCycleResult(ran=False, throttled=True)``。
        """
        current_time = now or datetime.now()
        state = self._load_state()
        result = CognitionCycleResult()

        # 门控：认知 + 洞察 LLM 调用消费 `preference` 和 `soul` 记忆层。
        # 若两者均尚未构建（init 的前 ~7 分钟），分析器 prompt 拿到的输入
        # 几乎为空，容易爆掉。这里静默跳过，避免画像落地前每个认知 tick
        # 都打 ERROR 级别日志，同时仍允许部分初始化的画像积累新认知。
        preference_data = self._memory.get_layer("preference").data
        soul_data = self._memory.get_layer("soul").data
        if not preference_data and not soul_data:
            logger.debug("CognitionCycle skipped: preference and soul layers are empty")
            result.throttled = True
            return result

        last_awareness_at = _parse_iso(state.get("last_awareness_at"))
        last_insight_at = _parse_iso(state.get("last_insight_at"))

        awareness_due = self._is_due(last_awareness_at, current_time)
        insight_due = self._is_due(last_insight_at, current_time)

        if not awareness_due and not insight_due:
            result.throttled = True
            return result

        result.ran = True

        # 1. 认知阶段
        if awareness_due:
            try:
                added = await self._run_awareness(state)
                result.awareness_generated = added
                state["last_awareness_at"] = current_time.isoformat()
            except AwarenessGenerationError as exc:
                # 可恢复：JSON 形状错误或单次 LLM 抽风。以 WARNING
                # （而非 ERROR）记日志，且不推进 ``last_awareness_at``
                # —— 下次 tick 会重试，而不是等满 12 小时节流。
                # 健壮性补丁之前这里落到通用 ``except Exception`` 分支，
                # 会静默推进调度并把认知窗口清空半天。
                logger.warning(
                    "Awareness analyzer failed twice; will retry next tick: %s",
                    exc,
                )
                result.errors.append(f"awareness: {exc}")
            except Exception as exc:
                logger.exception("Awareness analyzer failed during cognition cycle")
                result.errors.append(f"awareness: {exc}")

        # 2. 洞察阶段 —— 在认知之后运行，以便使用新笔记
        if insight_due:
            try:
                added = await self._run_insight(state)
                result.insight_generated = added
                state["last_insight_at"] = current_time.isoformat()
            except Exception as exc:
                logger.exception("Insight analyzer failed during cognition cycle")
                result.errors.append(f"insight: {exc}")

        # 3. 把新认知/洞察同步进 OnionProfile，让弹窗立即看到。
        # 这是尽力而为的写入 —— 缺失 soul 层或 init 中状态不应破坏循环。
        try:
            self._sync_to_profile(result)
        except Exception:
            logger.exception("Failed to sync cognition cycle output into profile")

        self._save_state(state)
        return result

    # -- 内部 -------------------------------------------------------------

    def _is_due(
        self,
        last_run_at: datetime | None,
        now: datetime,
    ) -> bool:
        if last_run_at is None:
            return True
        elapsed = (now - last_run_at).total_seconds()
        return elapsed >= self._min_interval_seconds

    async def _run_awareness(self, state: dict[str, Any]) -> int:
        """把水位线之后的新事件折叠为认知笔记。

        基于游标：读取 ``id > last_awareness_event_id`` 的事件
        （大积压下取最新的 ``_AWARENESS_BACKLOG_CAP`` 条），按
        ``_AWARENESS_EVENT_BATCH_SIZE`` 分块处理，每块成功后推进水位线，
        这样后续块失败时部分进展得以保留。第一批还会附带少量已处理事件
        作为上下文，让观察在新增很少时仍保持趋势感知。

        每块的 analyze 调用在 ``AwarenessGenerationError`` 时重试一次
        （镜像旧的单次调用行为）。持续失败会上抛到 ``run_if_due`` ——
        水位线停留在最后一块成功处，下次 tick 从那里恢复而不是等满节流。

        返回所有块新增的笔记数。
        """
        watermark = _coerce_int(state.get("last_awareness_event_id", 0))
        rows = self._memory.query_events(
            after_event_id=watermark,
            limit=_AWARENESS_BACKLOG_CAP,
        )
        if not rows:
            return 0
        if len(rows) >= _AWARENESS_BACKLOG_CAP:
            logger.warning(
                "Awareness backlog hit cap %d; older unprocessed events are "
                "skipped (watermark jumps to newest of this window).",
                _AWARENESS_BACKLOG_CAP,
            )
        rows.reverse()  # 查询返回最新在前；按时间顺序处理

        lookback = self._awareness_lookback(watermark)
        preference = self._memory.get_layer("preference").data
        soul_profile_data = self._memory.get_layer("soul").data

        total_added = 0
        for batch_index, batch in enumerate(_chunk(rows, _AWARENESS_EVENT_BATCH_SIZE)):
            events_for_call = (lookback + batch) if batch_index == 0 else batch
            new_notes = await self._awareness_with_retry(
                events_for_call, preference, soul_profile_data
            )
            if new_notes:
                existing = self._load_awareness_notes()
                merged = self._awareness_analyzer.merge_notes(existing, new_notes)
                total_added += max(0, len(merged) - len(existing))
                self._save_awareness_notes(merged)
            # 把水位线推进到本块之后并立即持久化，
            # 这样后续块的失败不会让本块在下次 tick 被重新处理。
            batch_max_id = max(_coerce_int(item.get("id", 0)) for item in batch)
            watermark = max(watermark, batch_max_id)
            state["last_awareness_event_id"] = watermark
            self._save_state(state)
        return total_added

    async def _awareness_with_retry(
        self,
        events: list[dict[str, Any]],
        preference: dict[str, Any],
        soul_profile_data: dict[str, Any],
    ) -> list[AwarenessNote]:
        """一次认知 analyze 调用，结构化失败时单次重试。"""
        try:
            return await self._awareness_analyzer.analyze(
                events=events,
                preference=preference,
                soul_profile=soul_profile_data,
                max_tokens=_COGNITION_MAX_TOKENS,
            )
        except AwarenessGenerationError:
            await asyncio.sleep(_AWARENESS_RETRY_BACKOFF_SECONDS)
            return await self._awareness_analyzer.analyze(
                events=events,
                preference=preference,
                soul_profile=soul_profile_data,
                max_tokens=_COGNITION_MAX_TOKENS,
            )

    def _awareness_lookback(self, watermark: int) -> list[dict[str, Any]]:
        """已处理的近期事件（id <= 水位线），用作趋势上下文。

        首次运行时为空（没有先前事件）—— 此时积压本身已提供足够上下文。
        按时间顺序返回（最旧在前）。
        """
        if watermark <= 0:
            return []
        recent = self._memory.query_events(limit=_AWARENESS_CONTEXT_LOOKBACK)
        prior = [item for item in recent if _coerce_int(item.get("id", 0)) <= watermark]
        prior.reverse()
        return prior

    async def _run_insight(self, state: dict[str, Any]) -> int:
        """从洞察游标之后的认知笔记中提炼洞察。

        基于游标：读取 ``awareness_notes[last_insight_awareness_index:]``
        （笔记只追加，所以位置索引是稳定游标），而不是完整认知历史 ——
        从而给 prompt 设界。按 ``_INSIGHT_NOTE_BATCH_SIZE`` 分块处理，
        并把当前活跃假设作为只读上下文传入，让 LLM 能精细化而非重述。
        每块之后推进游标。

        返回所有块新增的假设数。
        """
        all_notes = self._load_awareness_notes()
        total_notes = len(all_notes)
        cursor = _coerce_int(state.get("last_insight_awareness_index", 0))
        if cursor > total_notes:
            # 笔记变少了（异常 —— 例如未来某次 GC）。从 0 重新处理。
            cursor = 0
        new_notes = all_notes[cursor:]
        if not new_notes:
            return 0
        if len(new_notes) > _INSIGHT_NOTE_BACKLOG_CAP:
            skipped = len(new_notes) - _INSIGHT_NOTE_BACKLOG_CAP
            logger.warning(
                "Insight note backlog exceeded cap %d; skipping %d older notes.",
                _INSIGHT_NOTE_BACKLOG_CAP,
                skipped,
            )
            new_notes = new_notes[-_INSIGHT_NOTE_BACKLOG_CAP:]
            cursor = total_notes - _INSIGHT_NOTE_BACKLOG_CAP

        preference = self._memory.get_layer("preference").data
        soul_profile_data = self._memory.get_layer("soul").data

        total_added = 0
        processed = cursor
        for batch in _chunk(new_notes, _INSIGHT_NOTE_BATCH_SIZE):
            existing = self._load_insights()
            new_insights = await self._insight_analyzer.analyze(
                awareness_notes=batch,
                preference=preference,
                soul_profile=soul_profile_data,
                existing_insights=existing,
                max_tokens=_COGNITION_MAX_TOKENS,
            )
            if new_insights:
                merged = self._insight_analyzer.merge_insights(existing, new_insights)
                total_added += max(0, len(merged) - len(existing))
                self._save_insights(merged)
            processed += len(batch)
            state["last_insight_awareness_index"] = processed
            self._save_state(state)
        return total_added

    def _sync_to_profile(self, result: CognitionCycleResult) -> None:
        """把最新的认知/洞察复制进 OnionProfile。

        读取当前 soul 层，附上最新的窗口化笔记和洞察，再写回。
        这让它们通过 ``profile.recent_awareness`` 和
        ``profile.active_insights`` 可见，正是 /api/profile-summary
        端点读取的字段。
        """
        if result.awareness_generated == 0 and result.insight_generated == 0:
            # 没什么可同步，但仍更新总数以便可观测性
            result.total_awareness_after = len(self._load_awareness_notes())
            result.total_insight_after = len(self._load_insights())
            return

        soul_layer = self._memory.get_layer("soul")
        if not soul_layer.data:
            # 画像尚未初始化 —— 静默跳过同步
            return

        try:
            profile = OnionProfile.from_dict(soul_layer.data)
        except Exception:
            logger.exception("Failed to load OnionProfile during cognition sync")
            return

        all_notes = self._load_awareness_notes()
        all_insights = self._load_insights()

        # 保留最近的窗口切片。笔记顺序由合并函数保留（追加并去重），
        # 所以取尾部即得到最新条目。
        profile.recent_awareness = all_notes[-_PROFILE_AWARENESS_WINDOW:]
        profile.active_insights = all_insights[-_PROFILE_INSIGHT_WINDOW:]
        profile.updated_at = datetime.now().isoformat()

        soul_layer.data.clear()
        soul_layer.data.update(profile.to_dict())
        soul_layer.save()

        # 同时同步 markdown/json 文件，让文件系统可见的画像反映新认知/洞察。
        try:
            self._memory.sync_profile_files(profile)
        except Exception:
            logger.debug("Failed to sync profile files after cognition cycle", exc_info=True)

        result.total_awareness_after = len(all_notes)
        result.total_insight_after = len(all_insights)

    # -- 记忆层辅助函数（镜像 SoulEngine 的私有辅助） ----------

    def _load_awareness_notes(self) -> list[AwarenessNote]:
        layer_data = self._memory.get_layer("awareness").data
        notes = layer_data.get("notes", [])
        return [awareness_note_from_dict(item) for item in notes if isinstance(item, dict)]

    def _save_awareness_notes(self, notes: list[AwarenessNote]) -> None:
        layer = self._memory.get_layer("awareness")
        layer.data.clear()
        layer.data.update(
            {
                "notes": [awareness_note_to_dict(item) for item in notes],
            }
        )
        layer.save()

    def _load_insights(self) -> list[InsightHypothesis]:
        layer_data = self._memory.get_layer("insight").data
        hypotheses = layer_data.get("hypotheses", [])
        return [insight_hypothesis_from_dict(item) for item in hypotheses if isinstance(item, dict)]

    def _save_insights(self, insights: list[InsightHypothesis]) -> None:
        layer = self._memory.get_layer("insight")
        layer.data.clear()
        layer.data.update(
            {
                "hypotheses": [insight_hypothesis_to_dict(item) for item in insights],
            }
        )
        layer.save()

    # -- 状态持久化 ----------------------------------------------------

    def _state_path(self) -> Path | None:
        data_dir = getattr(self._memory, "_data_dir", None)
        if data_dir is None:
            return None
        return Path(data_dir) / "memory" / "cognition_cycle_state.json"

    def _load_state(self) -> dict[str, Any]:
        path = self._state_path()
        if path is None or not path.exists():
            return {}
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            return {}
        return data if isinstance(data, dict) else {}

    def _save_state(self, state: dict[str, Any]) -> None:
        path = self._state_path()
        if path is None:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(state, f, ensure_ascii=False, indent=2)
        except OSError:
            logger.debug("Failed to save cognition cycle state", exc_info=True)


def _parse_iso(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _coerce_int(value: Any) -> int:
    """对从 JSON 状态读出的水位线/游标值尽力做 int 转换。"""
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return 0
    return 0


def _chunk(items: list[Any], size: int) -> Iterator[list[Any]]:
    """逐个产出 ``items`` 的 ``size`` 长度切片（最后一块可能更短）。"""
    step = max(1, int(size))
    for start in range(0, len(items), step):
        yield items[start : start + step]
