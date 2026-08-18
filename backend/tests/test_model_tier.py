"""
模型等级（Model Tier）配置与抽取层解析单元测试。
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from billing.model_tier import (
    EXTRACTION_TIER,
    MODEL_TIERS,
    SUBAGENT_NOTE,
    VALID_TIERS,
    ensure_tier_configs,
    get_tier_configs,
    set_tier_config,
)
from companion.extraction import parse_mental_extraction


class TestTierMeta:
    def test_four_tiers_defined(self):
        assert len(MODEL_TIERS) == 4
        assert {t["tier"] for t in MODEL_TIERS} == {"fable", "opus", "sonnet", "haiku"}

    def test_extraction_uses_haiku(self):
        assert EXTRACTION_TIER == "haiku"
        assert "haiku" in VALID_TIERS

    def test_subagent_note_present(self):
        assert "Subagent" in SUBAGENT_NOTE
        assert "自行选择" in SUBAGENT_NOTE


class TestTierConfigCrud:
    def test_ensure_and_get(self):
        from db.models import SessionLocal

        db = SessionLocal()
        try:
            ensure_tier_configs(db)
            configs = get_tier_configs(db)
            assert len(configs) == 4
            # 每档都带用途说明
            haiku = next(c for c in configs if c["tier"] == "haiku")
            assert haiku["description"]
        finally:
            db.close()

    def test_set_and_read(self):
        from db.models import SessionLocal

        db = SessionLocal()
        try:
            set_tier_config(db, "haiku", "openai", "gpt-haiku")
            configs = get_tier_configs(db)
            haiku = next(c for c in configs if c["tier"] == "haiku")
            assert haiku["provider"] == "openai"
            assert haiku["model"] == "gpt-haiku"
        finally:
            db.close()

    def test_unknown_tier_raises(self):
        from db.models import SessionLocal

        db = SessionLocal()
        try:
            with pytest.raises(ValueError):
                set_tier_config(db, "unknown", "openai", "x")
        finally:
            db.close()


class TestParseExtraction:
    def test_parse_valid_json(self):
        import json

        raw = json.dumps({
            "appraisal": {"relevance": 0.8, "desirability": -0.6, "controllability": 0.9, "novelty": 0.3},
            "weighted_errors": {"self_worth": -0.4},
            "new_memory": {
                "content": "用户很伤心",
                "memory_type": "emotional_moment",
                "emotional_intensity": 0.9,
                "personality_impact": 0.7,
                "keywords": ["伤心"],
            },
            "cognition_updates": [{"fact_id": "x", "event_type": "hint"}],
            "current_keywords": ["伤心"],
            "rational_cue": "理性导向",
            "emotional_cue": "情感导向",
        })
        ex = parse_mental_extraction(raw)
        assert ex.appraisal.desirability == pytest.approx(-0.6)
        assert ex.weighted_errors["self_worth"] == pytest.approx(-0.4)
        assert ex.new_memory is not None
        assert ex.new_memory.memory_type == "emotional_moment"
        assert ex.cognition_updates == [("x", "hint")]

    def test_parse_invalid_returns_neutral(self):
        ex = parse_mental_extraction("这不是 JSON")
        assert ex.appraisal.desirability == 0.0
        assert ex.weighted_errors == {}
        assert ex.new_memory is None

    def test_parse_code_block_wrapped(self):
        raw = '```json\n{"appraisal": {"desirability": 0.5}}\n```'
        ex = parse_mental_extraction(raw)
        assert ex.appraisal.desirability == pytest.approx(0.5)