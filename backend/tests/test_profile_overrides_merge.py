"""
ProfileOverrides.merge() 单元测试。
覆盖用户手动编辑与 AI 推断画像的合并逻辑：
description 完全覆盖、structured_data 合并、confidence 提升、无覆盖返回原画像。
"""

from __future__ import annotations

from soul.overrides import ProfileOverrides
from soul.profile import LayerData, OnionProfile


def _build_ai_profile(user_id: str = "user-1") -> OnionProfile:
    """构建 AI 推断的 OnionProfile baseline。"""
    return OnionProfile(
        user_id=user_id,
        surface=LayerData(
            description="AI 推断的行为偏好",
            structured_data={"language": "Python", "editor": "VSCode"},
            confidence=0.6,
        ),
        interest=LayerData(
            description="AI 推断的兴趣",
            structured_data={"fruit": "Apple"},
            confidence=0.7,
        ),
        role=LayerData(
            description="AI 推断的角色",
            structured_data={"role": "Engineer"},
            confidence=0.5,
        ),
        values=LayerData(
            description="AI 推断的价值观",
            structured_data={"goal": "Ship"},
            confidence=0.4,
        ),
        core=LayerData(
            description="AI 推断的人格",
            structured_data={"mbti": "INTJ"},
            confidence=0.3,
        ),
    )


def test_merge_description_override() -> None:
    """Override 的 description 完全覆盖 AI 提取的 description。"""
    ai_profile = _build_ai_profile()
    overrides = ProfileOverrides(
        user_id="user-1",
        overrides={
            "surface": {
                "description": "用户手动编辑的行为描述",
            },
        },
    )

    merged = overrides.merge(ai_profile)

    # surface 层 description 应为覆盖值
    assert merged.surface.description == "用户手动编辑的行为描述"
    # surface 层 structured_data 应保留 AI 推断的值（未传 override 时不动）
    assert merged.surface.structured_data.get("language") == "Python"
    # 其他层 description 不受影响
    assert merged.interest.description == "AI 推断的兴趣"


def test_merge_structured_data_merge() -> None:
    """Override 的 structured_data 合并到 AI 的 structured_data。"""
    ai_profile = _build_ai_profile()
    overrides = ProfileOverrides(
        user_id="user-1",
        overrides={
            "surface": {
                "structured_data": {
                    "language": "Rust",  # 覆盖已有键
                    "os": "Linux",       # 新增键
                },
            },
        },
    )

    merged = overrides.merge(ai_profile)

    # 覆盖已有键
    assert merged.surface.structured_data.get("language") == "Rust"
    # 新增键
    assert merged.surface.structured_data.get("os") == "Linux"
    # 未覆盖的键保留 AI 值
    assert merged.surface.structured_data.get("editor") == "VSCode"


def test_merge_confidence_boost() -> None:
    """Override 的 confidence 提升层的整体 confidence。"""
    ai_profile = _build_ai_profile()
    original_confidence = ai_profile.interest.confidence
    overrides = ProfileOverrides(
        user_id="user-1",
        overrides={
            "interest": {
                "confidence": 0.95,
            },
        },
    )

    merged = overrides.merge(ai_profile)

    # interest 层 confidence 应被覆盖为 0.95
    assert merged.interest.confidence == 0.95
    assert merged.interest.confidence > original_confidence
    # 其他层 confidence 不受影响
    assert merged.surface.confidence == 0.6


def test_merge_no_override_returns_original() -> None:
    """无 override 时返回与原 OnionProfile 等价的画像。"""
    ai_profile = _build_ai_profile()
    overrides = ProfileOverrides(user_id="user-1", overrides={})

    merged = overrides.merge(ai_profile)

    # 无任何覆盖时，合并结果应与原画像数据一致
    assert merged.user_id == ai_profile.user_id
    assert merged.surface.description == ai_profile.surface.description
    assert merged.surface.structured_data == ai_profile.surface.structured_data
    assert merged.surface.confidence == ai_profile.surface.confidence
    assert merged.interest.description == ai_profile.interest.description
    assert merged.role.description == ai_profile.role.description
    assert merged.values.description == ai_profile.values.description
    assert merged.core.description == ai_profile.core.description
