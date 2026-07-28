"""
MemoryManager._calculate_confidence 五因子加权公式单元测试。

覆盖：source_score / completeness_score / recency_score / dedup_penalty / access_factor
五因子的独立变化与组合场景。
"""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from memory.manager import MemoryManager


@pytest.fixture
def manager():
    """构造一个无副作用的 MemoryManager 实例（mock 依赖）。"""
    mgr = MemoryManager.__new__(MemoryManager)
    mgr.session_factory = MagicMock()
    mgr.vector_store = MagicMock()
    mgr.working_memory = MagicMock()
    return mgr


def _make_memory(
    content: str = "用户偏好 Python 编程",
    importance: float = 0.7,
    source_type: str = "user_input",
    last_access: datetime = None,
    access_count: int = 0,
):
    """构造一个最小化的 LongTermMemory mock 对象。"""
    memory = MagicMock()
    memory.content = content
    memory.importance = importance
    memory.memory_metadata = {"source_type": source_type}
    memory.last_access = last_access or datetime.now(timezone.utc)
    memory.access_count = access_count
    memory.confidence = 0.5
    memory.quality_score = 0.0
    memory.archive_status = "active"
    memory.id = 1
    return memory


class TestSourceScore:
    """五因子之一：source_score（权重 0.3）。"""

    def test_user_input_score(self, manager):
        memory = _make_memory(source_type="user_input")
        confidence = manager._calculate_confidence(memory)
        # content="用户偏好 Python 编程" 14 字符 → completeness=14/200=0.07 → 0.07*0.25=0.0175
        # user_input=1.0 → 1.0 * 0.3 = 0.3
        # recency=1.0（now）→ 1.0 * 0.2 = 0.2
        # dedup_penalty=1.0 → 1.0 * 0.15 = 0.15
        # access=min(0/20,1)=0 → 0 * 0.1 = 0
        # 总计：0.3 + 0.0175 + 0.2 + 0.15 + 0 = 0.6675
        assert abs(confidence - 0.6675) < 0.001

    def test_llm_extracted_score(self, manager):
        memory = _make_memory(source_type="llm_extracted")
        confidence = manager._calculate_confidence(memory)
        # llm_extracted=0.8 → 0.8 * 0.3 = 0.24
        # 总计：0.24 + 0.0175 + 0.2 + 0.15 + 0 = 0.6075
        assert abs(confidence - 0.6075) < 0.001

    def test_plugin_score(self, manager):
        memory = _make_memory(source_type="plugin")
        confidence = manager._calculate_confidence(memory)
        # plugin=0.6 → 0.6 * 0.3 = 0.18
        # 总计：0.18 + 0.0175 + 0.2 + 0.15 + 0 = 0.5475
        assert abs(confidence - 0.5475) < 0.001

    def test_unknown_source_default(self, manager):
        memory = _make_memory(source_type="unknown_source")
        confidence = manager._calculate_confidence(memory)
        # 默认 0.5 → 0.5 * 0.3 = 0.15
        # 总计：0.15 + 0.0175 + 0.2 + 0.15 + 0 = 0.5175
        assert abs(confidence - 0.5175) < 0.001


class TestCompletenessScore:
    """五因子之二：completeness_score（权重 0.25）。"""

    def test_short_content_low_score(self, manager):
        memory = _make_memory(content="hi")
        confidence = manager._calculate_confidence(memory)
        # completeness=min(2/200,1)=0.01 → 0.01 * 0.25 = 0.0025
        # 总计：0.3 + 0.0025 + 0.2 + 0.15 + 0 = 0.6525
        assert abs(confidence - 0.6525) < 0.001

    def test_full_content_max_score(self, manager):
        # 200+ 字符内容
        long_content = "用户偏好 Python 编程，使用 FastAPI 搭建后端服务，前端 React + TypeScript，数据库 PostgreSQL 与 Qdrant 向量库混合检索，记忆系统长期/短期双层，agent.py 协调 comprehension/planner/executor/feedback 四阶段闭环。" * 2
        memory = _make_memory(content=long_content)
        confidence = manager._calculate_confidence(memory)
        # completeness=1.0 → 1.0 * 0.25 = 0.25
        # 总计：0.3 + 0.25 + 0.2 + 0.15 + 0 = 0.9
        assert abs(confidence - 0.9) < 0.001


class TestRecencyScore:
    """五因子之三：recency_score（权重 0.2）。"""

    def test_fresh_memory_max_score(self, manager):
        memory = _make_memory(last_access=datetime.now(timezone.utc))
        confidence = manager._calculate_confidence(memory)
        # recency=1.0 → 1.0 * 0.2 = 0.2
        # 总计：0.3 + 0.0175 + 0.2 + 0.15 + 0 = 0.6675
        assert abs(confidence - 0.6675) < 0.001

    def test_old_memory_low_score(self, manager):
        # 15 天前访问：recency = 1 - 15/30 = 0.5
        old_time = datetime.now(timezone.utc) - timedelta(days=15)
        memory = _make_memory(last_access=old_time)
        confidence = manager._calculate_confidence(memory)
        # recency=0.5 → 0.5 * 0.2 = 0.1
        # 总计：0.3 + 0.0175 + 0.1 + 0.15 + 0 = 0.5675
        assert abs(confidence - 0.5675) < 0.001

    def test_very_old_memory_zero_score(self, manager):
        # 30+ 天前访问：recency = 0
        old_time = datetime.now(timezone.utc) - timedelta(days=60)
        memory = _make_memory(last_access=old_time)
        confidence = manager._calculate_confidence(memory)
        # recency=0 → 0
        # 总计：0.3 + 0.0175 + 0 + 0.15 + 0 = 0.4675
        assert abs(confidence - 0.4675) < 0.001


class TestDedupPenalty:
    """五因子之四：dedup_penalty（权重 0.15）。"""

    def test_no_dedup_keeps_penalty(self, manager):
        memory = _make_memory()
        confidence = manager._calculate_confidence(memory, dedup_hit=False)
        # dedup_penalty=1.0 → 1.0 * 0.15 = 0.15
        # 总计：0.3 + 0.0175 + 0.2 + 0.15 + 0 = 0.6675
        assert abs(confidence - 0.6675) < 0.001

    def test_dedup_hit_reduces_and_boosts(self, manager):
        memory = _make_memory()
        confidence = manager._calculate_confidence(memory, dedup_hit=True)
        # dedup_penalty=0.0 → 0
        # 但去重命中时额外 +0.05 强化
        # 总计：0.3 + 0.0175 + 0.2 + 0 + 0 + 0.05 = 0.5675
        assert abs(confidence - 0.5675) < 0.001


class TestAccessFactor:
    """五因子之五：access_factor（权重 0.1）。"""

    def test_zero_access(self, manager):
        memory = _make_memory(access_count=0)
        confidence = manager._calculate_confidence(memory)
        # access=min(0/20,1)=0 → 0
        # 总计：0.3 + 0.0175 + 0.2 + 0.15 + 0 = 0.6675
        assert abs(confidence - 0.6675) < 0.001

    def test_ten_access(self, manager):
        memory = _make_memory(access_count=10)
        confidence = manager._calculate_confidence(memory)
        # access=min(10/20,1)=0.5 → 0.5 * 0.1 = 0.05
        # 总计：0.3 + 0.0175 + 0.2 + 0.15 + 0.05 = 0.7175
        assert abs(confidence - 0.7175) < 0.001

    def test_capped_at_twenty_access(self, manager):
        memory = _make_memory(access_count=100)
        confidence = manager._calculate_confidence(memory)
        # access=min(100/20,1)=1.0 → 1.0 * 0.1 = 0.1
        # 总计：0.3 + 0.0175 + 0.2 + 0.15 + 0.1 = 0.7675
        assert abs(confidence - 0.7675) < 0.001


class TestCombinedScenarios:
    """组合场景：综合验证五因子加权。"""

    def test_high_quality_memory(self, manager):
        """高来源 + 长内容 + 新鲜 + 未去重 + 高访问 → 接近上限。"""
        long_content = "用户偏好 Python 编程，使用 FastAPI 搭建后端服务，前端 React + TypeScript" * 5
        memory = _make_memory(
            content=long_content,
            source_type="user_input",
            last_access=datetime.now(timezone.utc),
            access_count=50,
        )
        confidence = manager._calculate_confidence(memory)
        # source=1.0 → 0.3
        # completeness=1.0 → 0.25
        # recency=1.0 → 0.2
        # dedup_penalty=1.0 → 0.15
        # access=1.0 → 0.1
        # 总计：0.3 + 0.25 + 0.2 + 0.15 + 0.1 = 1.0
        assert abs(confidence - 1.0) < 0.001

    def test_low_quality_memory(self, manager):
        """低来源 + 短内容 + 陈旧 + 已去重 + 无访问 → 远低于上限。"""
        old_time = datetime.now(timezone.utc) - timedelta(days=60)
        memory = _make_memory(
            content="hi",
            source_type="plugin",
            last_access=old_time,
            access_count=0,
        )
        confidence = manager._calculate_confidence(memory, dedup_hit=True)
        # source=0.6 → 0.18
        # completeness=min(2/200,1)=0.01 → 0.0025
        # recency=0 → 0
        # dedup_penalty=0 → 0
        # access=0 → 0
        # 总计：0.18 + 0.0025 + 0 + 0 + 0 + 0.05 = 0.2325
        assert abs(confidence - 0.2325) < 0.001

    def test_confidence_bounded_zero_to_one(self, manager):
        """confidence 永远在 [0, 1] 范围内。"""
        # 极端低：陈旧、空内容、plugin
        old_time = datetime.now(timezone.utc) - timedelta(days=365)
        memory = _make_memory(
            content="",
            source_type="plugin",
            last_access=old_time,
            access_count=0,
        )
        confidence = manager._calculate_confidence(memory)
        assert 0.0 <= confidence <= 1.0
