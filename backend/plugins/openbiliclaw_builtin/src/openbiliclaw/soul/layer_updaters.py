"""ProfileUpdatePipeline 的各层更新函数。

每一层有自己的更新逻辑：Surface 用计算，Interest 委托给
PreferenceAnalyzer，Role/Values/Core 用 LLM 并带 diff 保护。
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from copy import deepcopy
from datetime import datetime
from typing import TYPE_CHECKING, Any

from openbiliclaw.llm.json_utils import (
    DEFAULT_STRUCTURED_MAX_TOKENS,
    JSONValue,
    parse_llm_json_tolerant,
)
from openbiliclaw.soul.dislike_writeback import purge_pool_for_new_dislikes

if TYPE_CHECKING:
    from openbiliclaw.memory.manager import MemoryManager
    from openbiliclaw.soul.preference_analyzer import PreferenceAnalyzer
    from openbiliclaw.soul.profile import OnionProfile
    from openbiliclaw.soul.profile_builder import ProfileBuilder

from .pipeline import LayerUpdateResult, OnionLayer

logger = logging.getLogger(__name__)

LayerUpdater = Callable[..., Awaitable[LayerUpdateResult]]


def _coerce_float(value: object, *, default: float = 0.0) -> float:
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return default
    return default


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value:
        text = str(item).strip()
        if text:
            result.append(text)
    return result

def _string_set(value: object) -> set[str]:
    return set(_string_list(value))


def _json_list(value: object) -> list[JSONValue]:
    return value if isinstance(value, list) else []


def _json_object(value: object) -> dict[str, JSONValue]:
    return value if isinstance(value, dict) else {}


async def update_layer(
    *,
    layer: OnionLayer,
    signals: list[dict[str, object]],
    profile: OnionProfile,
    memory: MemoryManager,
    preference_analyzer: PreferenceAnalyzer,
    profile_builder: ProfileBuilder,
    embedding_service: Any | None = None,
    llm_service: Any | None = None,
) -> LayerUpdateResult:
    """分派到对应的层更新器。"""
    updater: LayerUpdater | None = _LAYER_UPDATERS.get(layer)
    if updater is None:
        return LayerUpdateResult(layer=layer, changed=False)
    return await updater(
        signals=signals,
        profile=profile,
        memory=memory,
        preference_analyzer=preference_analyzer,
        profile_builder=profile_builder,
        embedding_service=embedding_service,
        llm_service=llm_service,
    )


# ---------------------------------------------------------------------------
# Surface 层 —— 纯计算，无 LLM
# ---------------------------------------------------------------------------


async def _update_surface(
    *,
    signals: list[dict[str, object]],
    profile: OnionProfile,
    **_: Any,
) -> LayerUpdateResult:
    """用纯计算从行为信号更新 surface 层。"""
    changes: list[str] = []

    # 统计事件类型以推断风格
    view_count = 0
    search_count = 0
    for sig in signals:
        payload = sig.get("payload", {})
        if isinstance(payload, dict):
            event_type = str(payload.get("event_type", ""))
            if event_type == "view":
                view_count += 1
            elif event_type == "search":
                search_count += 1

    # 行为数据足够时，调整深度偏好
    if view_count >= 2:
        old_depth = profile.surface.style.depth_preference
        # 相对观看更多的搜索事件意味着更深度的参与
        depth_signal = min(1.0, 0.5 + (search_count / max(view_count, 1)) * 0.3)
        new_depth = round(old_depth * 0.7 + depth_signal * 0.3, 2)
        if abs(new_depth - old_depth) > 0.05:
            profile.surface.style.depth_preference = new_depth
            changes.append(f"depth_preference: {old_depth:.2f} → {new_depth:.2f}")

    return LayerUpdateResult(
        layer=OnionLayer.SURFACE,
        changed=bool(changes),
        changes=changes,
        signals_consumed=len(signals),
        trigger="行为模式分析",
        evidence=f"{view_count} views, {search_count} searches",
        timestamp=datetime.now().isoformat(),
    )


# ---------------------------------------------------------------------------
# Interest 层 —— LLM + 树合并
# ---------------------------------------------------------------------------


async def _update_interest(
    *,
    signals: list[dict[str, object]],
    profile: OnionProfile,
    memory: MemoryManager,
    preference_analyzer: PreferenceAnalyzer,
    embedding_service: Any | None = None,
    llm_service: Any | None = None,
    **_: Any,
) -> LayerUpdateResult:
    """通过委托给 PreferenceAnalyzer 更新 interest 层。"""
    # 把信号转回 PreferenceAnalyzer 用的事件格式
    events: list[dict[str, Any]] = []
    for sig in signals:
        payload = sig.get("payload", {})
        if isinstance(payload, dict):
            events.append(dict(payload))

    if not events:
        return LayerUpdateResult(layer=OnionLayer.INTEREST, changed=False)

    preference_layer = memory.get_layer("preference")
    existing_preference = dict(preference_layer.data)

    pre_update_profile = deepcopy(profile)

    try:
        updated_preference = await preference_analyzer.analyze_events(
            events=events,
            existing_preference=existing_preference,
        )
    except Exception:
        logger.exception("PreferenceAnalyzer failed during interest update")
        return LayerUpdateResult(layer=OnionLayer.INTEREST, changed=False)

    # 持久化扁平 preference（pipeline 不变）
    preference_layer.data.clear()
    preference_layer.data.update(updated_preference)
    preference_layer.save()

    # 从扁平 preference 更新 onion 的 interest + surface 层
    profile.populate_from_flat_preference(updated_preference)

    # 同步 cognitive_style（PreferenceLayer 不建模，绕过 populate）
    cs = updated_preference.get("cognitive_style")
    if isinstance(cs, list):
        profile.surface.cognitive_style = [str(s) for s in cs if s]

    # 检测变化
    changes: list[str] = []
    old_interests = {
        str(item.get("name", "")).strip(): _coerce_float(item.get("weight", 0))
        for item in _json_list(existing_preference.get("interests"))
        if isinstance(item, dict) and str(item.get("name", "")).strip()
    }
    new_interests = {
        str(item.get("name", "")).strip(): _coerce_float(item.get("weight", 0))
        for item in _json_list(updated_preference.get("interests"))
        if isinstance(item, dict) and str(item.get("name", "")).strip()
    }
    for name in new_interests:
        if name not in old_interests:
            changes.append(f"新增兴趣: {name} ({new_interests[name]:.2f})")
        elif abs(new_interests[name] - old_interests.get(name, 0)) > 0.15:
            changes.append(
                f"兴趣权重变化: {name} {old_interests[name]:.2f} → {new_interests[name]:.2f}"
            )

    old_dislikes = _string_set(existing_preference.get("disliked_topics"))
    new_dislikes = _string_set(updated_preference.get("disliked_topics"))
    newly_added_dislikes = new_dislikes - old_dislikes
    for topic in newly_added_dislikes:
        changes.append(f"新增讨厌: {topic}")

    if newly_added_dislikes:
        database = getattr(memory, "_database", None)
        changes.extend(
            await purge_pool_for_new_dislikes(
                database=database,
                embedding_service=embedding_service,
                llm_service=llm_service,
                newly_added=sorted(newly_added_dislikes),
                all_dislikes=sorted(new_dislikes),
            )
        )

    # 把 speculative_interests 喂给 speculator 作为种子候选
    speculative_seeds = updated_preference.get("speculative_interests")
    if isinstance(speculative_seeds, list) and speculative_seeds:
        try:
            from openbiliclaw.soul.speculator import InterestSpeculator

            data_dir = getattr(memory, "_data_dir", None)
            if data_dir:
                speculator = InterestSpeculator(llm_service=None, data_dir=data_dir)
                seed_coverage_profile = deepcopy(pre_update_profile)
                seed_coverage_profile.interest.likes.extend(profile.interest.likes)
                runtime_state: dict[str, object] = {}
                load_runtime_state = getattr(memory, "load_discovery_runtime_state", None)
                if callable(load_runtime_state):
                    runtime_state = load_runtime_state()
                probed_domains_raw = runtime_state.get("probed_domains", {})
                probed_domains = (
                    set(probed_domains_raw) if isinstance(probed_domains_raw, dict) else set()
                )
                added = speculator.ingest_seeds(
                    speculative_seeds,
                    profile=seed_coverage_profile,
                    probed_domains=probed_domains,
                    feedback_history=runtime_state.get("probe_feedback_history", []),
                )
                if added:
                    changes.append(f"注入 {added} 条猜测兴趣种子")
        except Exception:
            logger.debug("Speculator seed ingestion skipped", exc_info=True)

    return LayerUpdateResult(
        layer=OnionLayer.INTEREST,
        changed=bool(changes),
        changes=changes,
        signals_consumed=len(signals),
        trigger="偏好分析",
        evidence=f"分析了 {len(events)} 条事件",
        timestamp=datetime.now().isoformat(),
    )


# ---------------------------------------------------------------------------
# Role 层 —— LLM + diff 保护
# ---------------------------------------------------------------------------


async def _update_role(
    *,
    signals: list[dict[str, object]],
    profile: OnionProfile,
    memory: MemoryManager,
    profile_builder: ProfileBuilder,
    **_: Any,
) -> LayerUpdateResult:
    """从累积信号更新 role 层（life_stage、current_phase）。

    使用带 diff 保护的 LLM：仅当 LLM 显式提出变更时才应用。
    """
    # 从信号里收集证据
    evidence_parts: list[str] = []
    for sig in signals:
        payload = sig.get("payload", {})
        if isinstance(payload, dict):
            title = str(payload.get("title", ""))
            event_type = str(payload.get("event_type", ""))
            up_name = str(payload.get("up_name", ""))
            content = str(payload.get("content", ""))
            if title:
                up_suffix = f" (UP:{up_name})" if up_name else ""
                evidence_parts.append(f"[{event_type}] {title}{up_suffix}")
            elif content:
                evidence_parts.append(content)

    if not evidence_parts:
        return LayerUpdateResult(layer=OnionLayer.ROLE, changed=False)

    from openbiliclaw.llm.prompts import build_role_delta_prompt

    messages = build_role_delta_prompt(
        current_life_stage=profile.role.life_stage,
        current_phase=profile.role.current_phase,
        evidence=evidence_parts,
    )

    try:
        response = await profile_builder.registry.complete_structured_task(
            system_instruction=messages[0]["content"],
            user_input=messages[1]["content"],
            max_tokens=DEFAULT_STRUCTURED_MAX_TOKENS,
            caller="soul.role_update",
        )
        result = parse_llm_json_tolerant(response.content)
        if not isinstance(result, dict):
            raise ValueError("role delta response must be a JSON object")
    except Exception:
        logger.exception("Role delta LLM call failed")
        return LayerUpdateResult(
            layer=OnionLayer.ROLE,
            changed=False,
            signals_consumed=len(signals),
            timestamp=datetime.now().isoformat(),
        )

    changes: list[str] = []
    if result.get("changed"):
        new_stage = str(result.get("life_stage", "")).strip()
        new_phase = str(result.get("current_phase", "")).strip()
        reason = str(result.get("reason", ""))

        if new_stage and new_stage != profile.role.life_stage:
            changes.append(f"life_stage: {profile.role.life_stage!r} → {new_stage!r}")
            profile.role.life_stage = new_stage
        if new_phase and new_phase != profile.role.current_phase:
            changes.append(f"current_phase: {profile.role.current_phase!r} → {new_phase!r}")
            profile.role.current_phase = new_phase
        if changes:
            logger.info("Role updated: %s (reason: %s)", "; ".join(changes), reason[:60])

    return LayerUpdateResult(
        layer=OnionLayer.ROLE,
        changed=bool(changes),
        changes=changes,
        signals_consumed=len(signals),
        trigger="角色信号分析",
        evidence="; ".join(evidence_parts[:3]),
        timestamp=datetime.now().isoformat(),
    )


# ---------------------------------------------------------------------------
# Values 层 —— LLM + 仅 delta 更新
# ---------------------------------------------------------------------------


async def _update_values(
    *,
    signals: list[dict[str, object]],
    profile: OnionProfile,
    profile_builder: ProfileBuilder,
    **_: Any,
) -> LayerUpdateResult:
    """用 LLM delta（增/删，每周期最多 1 条）更新 values 层。"""
    evidence_parts: list[str] = []
    for sig in signals:
        payload = sig.get("payload", {})
        if isinstance(payload, dict):
            title = str(payload.get("title", ""))
            event_type = str(payload.get("event_type", ""))
            content = str(payload.get("content", ""))
            if title:
                evidence_parts.append(f"[{event_type}] {title}")
            elif content:
                evidence_parts.append(content)

    if not evidence_parts:
        return LayerUpdateResult(layer=OnionLayer.VALUES, changed=False)

    # 注入画像上下文，让 LLM 把证据与用户的生活处境联系起来
    ctx_parts: list[str] = []
    if profile.role.life_stage:
        ctx_parts.append(f"生活阶段: {profile.role.life_stage}")
    if profile.role.current_phase:
        ctx_parts.append(f"当前状态: {profile.role.current_phase}")
    interest_names = (
        [d.domain for d in profile.interest.likes[:6]] if profile.interest.likes else []
    )
    if interest_names:
        ctx_parts.append(f"主要兴趣: {', '.join(interest_names)}")
    if ctx_parts:
        evidence_parts.insert(0, "【用户背景】" + "; ".join(ctx_parts))

    from openbiliclaw.llm.prompts import build_values_delta_prompt

    messages = build_values_delta_prompt(
        current_values=profile.values_layer.values,
        current_drivers=profile.values_layer.motivational_drivers,
        evidence=evidence_parts,
    )

    try:
        response = await profile_builder.registry.complete_structured_task(
            system_instruction=messages[0]["content"],
            user_input=messages[1]["content"],
            max_tokens=DEFAULT_STRUCTURED_MAX_TOKENS,
            caller="soul.values_update",
        )
        result = parse_llm_json_tolerant(response.content)
        if not isinstance(result, dict):
            raise ValueError("values delta response must be a JSON object")
    except Exception:
        logger.exception("Values delta LLM call failed")
        return LayerUpdateResult(
            layer=OnionLayer.VALUES,
            changed=False,
            signals_consumed=len(signals),
            timestamp=datetime.now().isoformat(),
        )

    changes: list[str] = []
    if result.get("changed"):
        new_values = result.get("values")
        new_drivers = result.get("motivational_drivers")
        reason = str(result.get("reason", ""))

        new_values_list = _string_list(new_values)
        if new_values_list and set(new_values_list) != set(profile.values_layer.values):
            old = profile.values_layer.values
            profile.values_layer.values = new_values_list
            added = set(new_values_list) - set(old)
            removed = set(old) - set(new_values_list)
            if added:
                changes.append(f"新增价值观: {', '.join(added)}")
            if removed:
                changes.append(f"移除价值观: {', '.join(removed)}")

        new_drivers_list = _string_list(new_drivers)
        if new_drivers_list and set(new_drivers_list) != set(
            profile.values_layer.motivational_drivers
        ):
            old = profile.values_layer.motivational_drivers
            profile.values_layer.motivational_drivers = new_drivers_list
            added = set(new_drivers_list) - set(old)
            removed = set(old) - set(new_drivers_list)
            if added:
                changes.append(f"新增驱动: {', '.join(added)}")
            if removed:
                changes.append(f"移除驱动: {', '.join(removed)}")

        if changes:
            logger.info("Values updated: %s (reason: %s)", "; ".join(changes), reason[:60])

    return LayerUpdateResult(
        layer=OnionLayer.VALUES,
        changed=bool(changes),
        changes=changes,
        signals_consumed=len(signals),
        trigger="价值观信号分析",
        evidence="; ".join(evidence_parts[:3]),
        timestamp=datetime.now().isoformat(),
    )


# ---------------------------------------------------------------------------
# Core 层 —— LLM + 最强 diff 保护
# ---------------------------------------------------------------------------


async def _update_core(
    *,
    signals: list[dict[str, object]],
    profile: OnionProfile,
    profile_builder: ProfileBuilder,
    **_: Any,
) -> LayerUpdateResult:
    """用强 diff 保护更新 core 层（特质、需求、MBTI）。"""
    evidence_parts: list[str] = []
    for sig in signals:
        payload = sig.get("payload", {})
        if isinstance(payload, dict):
            title = str(payload.get("title", ""))
            event_type = str(payload.get("event_type", ""))
            content = str(payload.get("content", ""))
            if title:
                evidence_parts.append(f"[{event_type}] {title}")
            elif content:
                evidence_parts.append(content)

    if not evidence_parts:
        return LayerUpdateResult(layer=OnionLayer.CORE, changed=False)

    from openbiliclaw.llm.prompts import build_core_delta_prompt

    mbti_dict: dict[str, object] = {}
    if profile.core.mbti.type:
        mbti_dict = {
            "type": profile.core.mbti.type,
            "confidence": profile.core.mbti.confidence,
            "dimensions": {
                k: {"pole": v.pole, "strength": v.strength}
                for k, v in profile.core.mbti.dimensions.items()
            },
        }

    messages = build_core_delta_prompt(
        current_traits=profile.core.core_traits,
        current_needs=profile.core.deep_needs,
        current_mbti=mbti_dict,
        evidence=evidence_parts,
    )

    try:
        response = await profile_builder.registry.complete_structured_task(
            system_instruction=messages[0]["content"],
            user_input=messages[1]["content"],
            max_tokens=DEFAULT_STRUCTURED_MAX_TOKENS,
            caller="soul.core_update",
        )
        result = parse_llm_json_tolerant(response.content)
        if not isinstance(result, dict):
            raise ValueError("core delta response must be a JSON object")
    except Exception:
        logger.exception("Core delta LLM call failed")
        return LayerUpdateResult(
            layer=OnionLayer.CORE,
            changed=False,
            signals_consumed=len(signals),
            timestamp=datetime.now().isoformat(),
        )

    changes: list[str] = []
    if result.get("changed"):
        reason = str(result.get("reason", ""))

        new_traits = result.get("core_traits")
        new_traits_list = _string_list(new_traits)
        if new_traits_list and set(new_traits_list) != set(profile.core.core_traits):
            added = set(new_traits_list) - set(profile.core.core_traits)
            removed = set(profile.core.core_traits) - set(new_traits_list)
            profile.core.core_traits = new_traits_list
            if added:
                changes.append(f"新增特质: {', '.join(added)}")
            if removed:
                changes.append(f"移除特质: {', '.join(removed)}")

        new_needs = result.get("deep_needs")
        new_needs_list = _string_list(new_needs)
        if new_needs_list and set(new_needs_list) != set(profile.core.deep_needs):
            added = set(new_needs_list) - set(profile.core.deep_needs)
            removed = set(profile.core.deep_needs) - set(new_needs_list)
            profile.core.deep_needs = new_needs_list
            if added:
                changes.append(f"新增需求: {', '.join(added)}")
            if removed:
                changes.append(f"移除需求: {', '.join(removed)}")

        # MBTI 更新（极罕见）
        new_mbti = result.get("mbti")
        if isinstance(new_mbti, dict) and new_mbti.get("type"):
            from openbiliclaw.soul.profile import MBTI, MBTIDimension

            new_type = str(new_mbti["type"]).upper()
            if new_type != profile.core.mbti.type:
                changes.append(f"MBTI: {profile.core.mbti.type} → {new_type}")
                dims = {}
                for k, v in _json_object(new_mbti.get("dimensions")).items():
                    if isinstance(v, dict):
                        dims[k] = MBTIDimension(
                            pole=str(v.get("pole", "")),
                            strength=_coerce_float(v.get("strength", 0.5), default=0.5),
                        )
                profile.core.mbti = MBTI(
                    type=new_type,
                    confidence=_coerce_float(new_mbti.get("confidence", 0.6), default=0.6),
                    dimensions=dims,
                )

        if changes:
            logger.info("Core updated: %s (reason: %s)", "; ".join(changes), reason[:60])

    return LayerUpdateResult(
        layer=OnionLayer.CORE,
        changed=bool(changes),
        changes=changes,
        signals_consumed=len(signals),
        trigger="核心信号分析",
        evidence="; ".join(evidence_parts[:3]),
        timestamp=datetime.now().isoformat(),
    )


# ---------------------------------------------------------------------------
# 画像重生成
# ---------------------------------------------------------------------------


async def regenerate_portrait(
    *,
    profile: OnionProfile,
    profile_builder: ProfileBuilder,
    memory: MemoryManager,
) -> str:
    """从当前画像状态重生成 personality_portrait。

    仅在 Core 或 Values 层真正变化时调用。返回新的画像文本，
    失败时返回空字符串。
    """
    from .profile import awareness_note_to_dict, insight_hypothesis_to_dict

    try:
        legacy_profile = await profile_builder.build(
            history=[],
            preference=memory.get_layer("preference").data,
            # 两个窗口都按时间最旧→最新排列；取尾部。
            awareness_notes=[awareness_note_to_dict(n) for n in profile.recent_awareness[-5:]],
            active_insights=[insight_hypothesis_to_dict(i) for i in profile.active_insights[-5:]],
        )
        return legacy_profile.personality_portrait
    except Exception:
        logger.exception("Failed to regenerate portrait")
        return ""


# ---------------------------------------------------------------------------
# 更新器分派表
# ---------------------------------------------------------------------------

_LAYER_UPDATERS: dict[OnionLayer, LayerUpdater] = {
    OnionLayer.SURFACE: _update_surface,
    OnionLayer.INTEREST: _update_interest,
    OnionLayer.ROLE: _update_role,
    OnionLayer.VALUES: _update_values,
    OnionLayer.CORE: _update_core,
}
