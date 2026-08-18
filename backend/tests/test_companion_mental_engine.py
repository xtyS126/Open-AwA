"""
陪伴系统心智引擎单元测试。

覆盖 NSP-roleplay 心智模型的确定性算法：
信念网络（精度/应变/负荷/灾变 + v9 优化）、OCC 情绪评估、
双通道引导、记忆召回优先级、观察者弧线、认知谱系、端到端分化。
"""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from companion.appraisal import (
    Appraisal,
    dual_channel_guidance,
    emotion_from_appraisal,
    mix_weight,
)
from companion.belief_network import BeliefNetwork
from companion.cognition import COGNITION_STATES, Cognition
from companion.memory import (
    MAX_COMPANION_MEMORY_CONTENT_CHARS,
    CompanionMemory,
    recall_priority,
    sanitize_memory_content,
    time_decay,
)
from companion.mental_engine import MentalEngine, MentalExtraction
from companion.observer import detect_arc


# ---- 信念网络：精度 ----

class TestBeliefPrecision:
    def test_extremity_range(self):
        net = BeliefNetwork({"a": 0.5, "b": 0.1, "c": 0.9})
        assert net.extremity("a") == pytest.approx(0.0)
        assert net.extremity("b") == pytest.approx(0.8)
        assert net.extremity("c") == pytest.approx(0.8)

    def test_extreme_belief_is_more_rigid(self):
        net = BeliefNetwork({"extreme": 0.9, "moderate": 0.5})
        assert net.precision("extreme") > net.precision("moderate")

    def test_load_erodes_precision(self):
        light = BeliefNetwork({"a": 0.9})
        heavy = BeliefNetwork({"a": 0.9})
        heavy.nodes["a"].load = 0.8
        assert heavy.precision("a") < light.precision("a")

    def test_emotion_lowers_precision(self):
        net = BeliefNetwork({"a": 0.9})
        assert net.precision("a", emotion_intensity=0.9) < net.precision("a", emotion_intensity=0.0)


# ---- 信念网络：应变/负荷/灾变 ----

class TestBeliefEvolution:
    def test_strain_decays_without_stress(self):
        net = BeliefNetwork({"a": 0.5})
        net.update({"a": -0.5})
        strain_before = net.nodes["a"].strain
        net.update({"a": 0.0})
        assert net.nodes["a"].strain == pytest.approx(strain_before * 0.95)

    def test_load_never_decays_during_sleep_of_update(self):
        net = BeliefNetwork({"a": 0.5})
        for _ in range(3):
            net.update({"a": -0.8})
        load = net.nodes["a"].load
        # 负荷只增不减（正面恢复之外）
        net.update({"a": -0.8})
        assert net.nodes["a"].load >= load

    def test_catastrophe_jumps_to_opposite_side(self):
        net = BeliefNetwork({"trust": 0.8})
        net.nodes["trust"].load = 0.6  # 越过阈值
        milestones = net.update({"trust": -0.1})
        assert "trust" in milestones
        # 从信任侧（>0.5）跳变到对侧（<0.5）
        assert net.nodes["trust"].value < 0.5
        # 灾变后负荷清零
        assert net.nodes["trust"].load == 0.0

    def test_v9_distance_proportional_to_load(self):
        mild = BeliefNetwork({"a": 0.8})
        mild.nodes["a"].load = 0.5  # 刚越过阈值
        mild.update({"a": -0.1})
        severe = BeliefNetwork({"a": 0.8})
        severe.nodes["a"].load = 1.0  # 极限负荷
        severe.update({"a": -0.1})
        # 负荷越大，跳变越剧烈（距离 0.5 越远）
        assert abs(severe.nodes["a"].value - 0.5) > abs(mild.nodes["a"].value - 0.5)

    def test_positive_event_reduces_load(self):
        net = BeliefNetwork({"a": 0.5})
        net.nodes["a"].load = 0.3
        net.update({"a": 0.0}, desirability=0.8)
        assert net.nodes["a"].load < 0.3


# ---- OCC 情绪与双通道 ----

class TestAppraisal:
    def test_negative_controllable_is_anger(self):
        app = Appraisal(relevance=0.9, desirability=-0.8, controllability=0.9, novelty=0.3)
        emotion = emotion_from_appraisal(app)
        assert emotion.primary == "anger"
        assert emotion.valence < 0

    def test_negative_uncontrollable_is_sadness(self):
        app = Appraisal(relevance=0.9, desirability=-0.8, controllability=0.1, novelty=0.3)
        emotion = emotion_from_appraisal(app)
        assert emotion.primary == "sadness"

    def test_positive_novel_is_surprise(self):
        app = Appraisal(relevance=0.5, desirability=0.8, controllability=0.5, novelty=0.9)
        emotion = emotion_from_appraisal(app)
        assert emotion.primary == "surprise"

    def test_neutral_stays_neutral(self):
        app = Appraisal(desirability=0.0)
        emotion = emotion_from_appraisal(app)
        assert emotion.primary == "neutral"


class TestDualChannel:
    def test_mix_weight_endpoints(self):
        assert mix_weight(0.0) == pytest.approx(0.2, abs=0.01)
        assert mix_weight(0.5) == pytest.approx(0.5, abs=0.01)
        assert mix_weight(1.0) == pytest.approx(0.8, abs=0.01)

    def test_guidance_reflects_share(self):
        result = dual_channel_guidance(rational_cue="责任", emotional_cue="愤怒", emotion_intensity=0.8)
        assert result["emotional_share"] > result["rational_share"]


# ---- 记忆召回 ----

class TestMemoryRecall:
    def _memory(self, intensity, impact, turn, keywords, _id="m1"):
        return CompanionMemory(
            id=_id,
            content="记忆内容",
            memory_type="emotional_moment",
            emotional_intensity=intensity,
            personality_impact=impact,
            created_turn=turn,
            keywords=keywords,
        )

    def test_flashbulb_memory_decays_slowly(self):
        # 高情感记忆的时效衰减应慢于低情感记忆
        assert time_decay(age=50, emotional_intensity=0.9) > time_decay(age=50, emotional_intensity=0.1)

    def test_high_impact_memory_ranked_higher(self):
        traumatic = self._memory(0.9, 0.9, 5, ["背叛"], _id="traumatic")
        mundane = self._memory(0.1, 0.1, 5, ["日常"], _id="mundane")
        assert recall_priority(traumatic, 100, ["背叛"]) > recall_priority(mundane, 100, ["背叛"])


# ---- 观察者弧线 ----

class TestObserver:
    def test_sudden_jump(self):
        assert detect_arc([0.5, 0.5, 0.3], "trust").arc == "SUDDEN_JUMP"

    def test_gradual_shift(self):
        history = [0.2 + i * 0.02 for i in range(10)]
        assert detect_arc(history, "x").arc == "GRADUAL_SHIFT"

    def test_plateau(self):
        assert detect_arc([0.5, 0.5, 0.51, 0.5], "x").arc == "PLATEAU"


# ---- 认知谱系 ----

class TestCognition:
    def test_state_spectrum_complete(self):
        assert len(COGNITION_STATES) == 8

    def test_typical_transition_chain(self):
        cog = Cognition()
        assert cog.state_of("fact") == "unaware"
        cog.transition("fact", "hint", turn=1)
        assert cog.state_of("fact") == "suspects"
        cog.transition("fact", "threat", turn=2)
        assert cog.state_of("fact") == "denies"
        cog.transition("fact", "accept", turn=3)
        assert cog.state_of("fact") == "aware"


# ---- 端到端分化 ----

class TestEndToEndDivergence:
    def test_kind_vs_hostile_self_worth_diverges(self):
        kind = MentalEngine({"self_worth": 0.3})
        hostile = MentalEngine({"self_worth": 0.3})

        # 善意：正向误差 + 正面事件
        for _ in range(30):
            kind.process_turn(
                MentalExtraction(
                    appraisal=Appraisal(desirability=0.6),
                    weighted_errors={"self_worth": 0.4},
                )
            )
        # 敌意：负向误差 + 负面事件，持续累积负荷
        hostile_milestones = 0
        for _ in range(30):
            update = hostile.process_turn(
                MentalExtraction(
                    appraisal=Appraisal(desirability=-0.6),
                    weighted_errors={"self_worth": -0.6},
                )
            )
            hostile_milestones += len(update.milestones)

        kind_worth = kind.network.nodes["self_worth"].value
        hostile_worth = hostile.network.nodes["self_worth"].value

        # 善意让自我价值上升
        assert kind_worth > 0.3
        # 敌意触发灾变，且走向与善意不同
        assert hostile_milestones > 0
        assert hostile_worth != pytest.approx(kind_worth)


# ---- 状态管理器持久化往返 ----

class TestPersistence:
    def test_state_roundtrip(self):
        from companion.state_manager import CompanionStateManager
        from db.models import SessionLocal

        db = SessionLocal()
        try:
            manager = CompanionStateManager(db)
            engine = manager.get_or_create_engine("persist-user", "persist-role")
            engine.process_turn(
                MentalExtraction(
                    appraisal=Appraisal(desirability=0.5),
                    weighted_errors={"self_worth": 0.5},
                )
            )
            manager.save("persist-user", "persist-role", engine)

            reloaded = manager.get_or_create_engine("persist-user", "persist-role")
            assert reloaded.turn == engine.turn
            assert reloaded.network.nodes["self_worth"].value == pytest.approx(
                engine.network.nodes["self_worth"].value
            )
        finally:
            db.close()

    def test_memory_persisted(self):
        from companion.state_manager import CompanionStateManager
        from db.models import SessionLocal

        db = SessionLocal()
        try:
            manager = CompanionStateManager(db)
            engine = manager.get_or_create_engine("persist-user2", "persist-role2")
            manager.save("persist-user2", "persist-role2", engine)
            mem = CompanionMemory(
                id="mem-test-1",
                content="第一次见面",
                memory_type="first_meeting",
                emotional_intensity=0.8,
                personality_impact=0.7,
                keywords=["初识"],
            )
            engine.memories.append(mem)
            manager.save_memory("persist-user2", "persist-role2", mem)

            reloaded = manager.get_or_create_engine("persist-user2", "persist-role2")
            assert any(m.content == "第一次见面" for m in reloaded.memories)
        finally:
            db.close()


# ---- 陪伴记忆内容防护：长度上限 + PII 脱敏 ----

class TestMemorySanitization:
    def test_redacts_api_key(self):
        """验证陪伴记忆内容中的 API key 被脱敏。"""
        api_key = "sk-" + "a" * 32
        result = sanitize_memory_content(f"用户给了我一个密钥 {api_key} 用于调试")
        assert api_key not in result
        assert "[REDACTED]" in result

    def test_truncates_overlong_content(self):
        """验证超长内容被截断到上限。"""
        result = sanitize_memory_content("长" * 1000)
        assert len(result) == MAX_COMPANION_MEMORY_CONTENT_CHARS

    def test_empty_and_non_string_unchanged(self):
        """验证空值与非字符串原样返回。"""
        assert sanitize_memory_content("") == ""
        assert sanitize_memory_content(None) is None

    def test_parse_mental_extraction_sanitizes_new_memory(self):
        """验证抽取层解析出的 new_memory.content 经过脱敏。"""
        from companion.extraction import parse_mental_extraction

        api_key = "sk-" + "b" * 32
        payload = json.dumps(
            {
                "new_memory": {
                    "content": f"用户分享了一个密钥 {api_key}",
                    "memory_type": "user_preference",
                }
            },
            ensure_ascii=False,
        )
        extraction = parse_mental_extraction(payload)
        assert extraction.new_memory is not None
        assert api_key not in extraction.new_memory.content
        assert "[REDACTED]" in extraction.new_memory.content