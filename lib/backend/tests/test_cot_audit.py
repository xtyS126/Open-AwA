"""
P3 Chain-of-Thought 推理审计测试：复杂度评估、审计记录、统计、导出。
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.cot_complexity import (
    ComplexityAssessor,
    COMPLEXITY_SIMPLE,
    COMPLEXITY_MODERATE,
    COMPLEXITY_COMPLEX,
    COMPLEXITY_DEPTH_MAP,
    get_complexity_assessor,
)
from core.reasoning_audit import ReasoningAuditManager, get_audit_manager
from db.models import Base, ReasoningAudit, ShortTermMemory


# ── 测试夹具 ──────────────────────────────────────────


@pytest.fixture
def db_session(tmp_path):
    """创建临时 SQLite 数据库会话。"""
    db_path = tmp_path / "test_cot_audit.db"
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


@pytest.fixture
def assessor():
    """创建复杂度评估器实例。"""
    return ComplexityAssessor()


@pytest.fixture
def audit_manager(db_session):
    """创建推理审计管理器实例。"""
    return ReasoningAuditManager(db_session)


# ── 复杂度评估器测试 ──────────────────────────────────────────


class TestComplexityAssessor:
    """问题复杂度评估器测试。"""

    def test_simple_greeting(self, assessor):
        result = assessor.assess("你好")
        assert result["complexity"] == COMPLEXITY_SIMPLE
        assert result["thinking_depth"] == COMPLEXITY_DEPTH_MAP[COMPLEXITY_SIMPLE]

    def test_simple_thanks(self, assessor):
        result = assessor.assess("谢谢你的帮助")
        assert result["complexity"] == COMPLEXITY_SIMPLE

    def test_moderate_explanation(self, assessor):
        result = assessor.assess("请解释一下什么是机器学习，以及它的应用场景")
        assert result["complexity"] in (COMPLEXITY_MODERATE, COMPLEXITY_COMPLEX)

    def test_complex_code_block(self, assessor):
        result = assessor.assess("请帮我优化这段代码：\n```python\nfor i in range(10):\n    print(i)\n```")
        assert result["complexity"] == COMPLEXITY_COMPLEX
        assert result["thinking_depth"] == COMPLEXITY_DEPTH_MAP[COMPLEXITY_COMPLEX]

    def test_complex_math_keywords(self, assessor):
        result = assessor.assess("请计算这个方程的导数并证明结果")
        assert result["complexity"] == COMPLEXITY_COMPLEX

    def test_complex_programming_keywords(self, assessor):
        result = assessor.assess("请实现一个算法来优化这个函数的性能")
        assert result["complexity"] == COMPLEXITY_COMPLEX

    def test_empty_input(self, assessor):
        result = assessor.assess("")
        assert result["complexity"] == COMPLEXITY_SIMPLE
        assert result["thinking_depth"] == 0
        assert result["score"] == 0

    def test_whitespace_input(self, assessor):
        result = assessor.assess("   ")
        assert result["complexity"] == COMPLEXITY_SIMPLE

    def test_long_input_increases_complexity(self, assessor):
        long_text = "请分析" + "数据" * 500
        result = assessor.assess(long_text)
        assert result["score"] > 0

    def test_multiple_question_marks(self, assessor):
        result = assessor.assess("什么是 AI？如何使用？为什么需要？")
        assert result["score"] > 0

    def test_url_detection(self, assessor):
        result = assessor.assess("请分析这个网页的内容 https://example.com/article")
        assert result["score"] > 0

    def test_math_formula_detection(self, assessor):
        result = assessor.assess("请求解 $x^2 + 2x + 1 = 0$")
        assert result["complexity"] == COMPLEXITY_COMPLEX

    def test_assess_depth_auto(self, assessor):
        depth = assessor.assess_depth("你好")
        assert 0 <= depth <= 5

    def test_assess_depth_user_override(self, assessor):
        depth = assessor.assess_depth("你好", user_override=5)
        assert depth == 5

    def test_assess_depth_override_clamped(self, assessor):
        depth = assessor.assess_depth("你好", user_override=10)
        assert depth == 5
        depth = assessor.assess_depth("你好", user_override=-1)
        assert depth == 0

    def test_assess_depth_override_zero(self, assessor):
        depth = assessor.assess_depth("复杂问题", user_override=0)
        assert depth == 0

    def test_reasons_not_empty(self, assessor):
        result = assessor.assess("请实现一个算法")
        assert len(result["reasons"]) > 0

    def test_score_in_range(self, assessor):
        result = assessor.assess("任意输入")
        assert 0 <= result["score"] <= 100


class TestComplexityAssessorSingleton:
    """复杂度评估器单例测试。"""

    def test_singleton(self):
        a1 = get_complexity_assessor()
        a2 = get_complexity_assessor()
        assert a1 is a2


# ── 推理审计管理器测试 ──────────────────────────────────────────


class TestReasoningAuditManager:
    """推理审计管理器测试。"""

    def test_record_audit_success(self, audit_manager, db_session):
        audit = audit_manager.record_audit(
            session_id="sess_1",
            user_id="user_1",
            provider="openai",
            model="o1",
            thinking_depth=3,
            complexity="moderate",
            complexity_score=45,
            reasoning_length=500,
            reasoning_tokens=200,
            output_tokens=100,
            input_tokens=50,
            reasoning_duration_ms=1500,
            total_duration_ms=3000,
            ttft_ms=800,
        )
        assert audit.id is not None
        assert audit.session_id == "sess_1"
        assert audit.thinking_depth == 3
        assert audit.reasoning_tokens == 200

    def test_record_audit_with_error(self, audit_manager):
        audit = audit_manager.record_audit(
            session_id="sess_err",
            success=False,
            error_message="模型超时",
        )
        assert audit.success is False
        assert audit.error_message == "模型超时"

    def test_list_audits_empty(self, audit_manager):
        result = audit_manager.list_audits()
        assert result["total"] == 0
        assert result["audits"] == []

    def test_list_audits_with_data(self, audit_manager):
        audit_manager.record_audit(session_id="sess_1", complexity="simple")
        audit_manager.record_audit(session_id="sess_2", complexity="complex")
        result = audit_manager.list_audits()
        assert result["total"] == 2

    def test_list_audits_filter_by_session(self, audit_manager):
        audit_manager.record_audit(session_id="sess_1")
        audit_manager.record_audit(session_id="sess_2")
        result = audit_manager.list_audits(session_id="sess_1")
        assert result["total"] == 1
        assert result["audits"][0]["session_id"] == "sess_1"

    def test_list_audits_filter_by_complexity(self, audit_manager):
        audit_manager.record_audit(session_id="s1", complexity="simple")
        audit_manager.record_audit(session_id="s2", complexity="complex")
        result = audit_manager.list_audits(complexity="complex")
        assert result["total"] == 1
        assert result["audits"][0]["complexity"] == "complex"

    def test_list_audits_filter_by_success(self, audit_manager):
        audit_manager.record_audit(session_id="s1", success=True)
        audit_manager.record_audit(session_id="s2", success=False)
        result = audit_manager.list_audits(success=False)
        assert result["total"] == 1
        assert result["audits"][0]["success"] is False

    def test_list_audits_pagination(self, audit_manager):
        for i in range(25):
            audit_manager.record_audit(session_id=f"sess_{i}")
        result = audit_manager.list_audits(page=1, page_size=10)
        assert result["total"] == 25
        assert len(result["audits"]) == 10
        result2 = audit_manager.list_audits(page=3, page_size=10)
        assert len(result2["audits"]) == 5

    def test_get_audit(self, audit_manager):
        audit = audit_manager.record_audit(session_id="sess_1", complexity="moderate")
        fetched = audit_manager.get_audit(audit.id)
        assert fetched is not None
        assert fetched["id"] == audit.id
        assert fetched["complexity"] == "moderate"

    def test_get_audit_nonexistent(self, audit_manager):
        assert audit_manager.get_audit(9999) is None

    def test_get_stats_empty(self, audit_manager):
        stats = audit_manager.get_stats()
        assert stats["total"] == 0
        assert stats["success_rate"] == 0.0

    def test_get_stats_with_data(self, audit_manager):
        audit_manager.record_audit(
            session_id="s1",
            success=True,
            reasoning_tokens=100,
            output_tokens=50,
            reasoning_duration_ms=1000,
            total_duration_ms=2000,
            ttft_ms=500,
            complexity="simple",
            thinking_depth=1,
        )
        audit_manager.record_audit(
            session_id="s2",
            success=False,
            reasoning_tokens=200,
            output_tokens=80,
            reasoning_duration_ms=2000,
            total_duration_ms=4000,
            ttft_ms=1000,
            complexity="complex",
            thinking_depth=5,
        )
        stats = audit_manager.get_stats()
        assert stats["total"] == 2
        assert stats["success_rate"] == 50.0
        assert stats["avg_reasoning_tokens"] == 150.0
        assert "simple" in stats["complexity_distribution"]
        assert "complex" in stats["complexity_distribution"]
        assert "1" in stats["depth_distribution"]
        assert "5" in stats["depth_distribution"]

    def test_get_stats_filter_by_user(self, audit_manager):
        audit_manager.record_audit(session_id="s1", user_id="u1", reasoning_tokens=100)
        audit_manager.record_audit(session_id="s2", user_id="u2", reasoning_tokens=200)
        stats = audit_manager.get_stats(user_id="u1")
        assert stats["total"] == 1
        assert stats["avg_reasoning_tokens"] == 100.0


class TestReasoningExport:
    """推理内容导出测试。"""

    def test_export_empty_session(self, audit_manager):
        result = audit_manager.export_reasoning_content(session_id="nonexistent")
        assert result["total"] == 0
        assert result["items"] == []

    def test_export_with_reasoning_content(self, audit_manager, db_session):
        # 插入带推理内容的记忆记录
        mem = ShortTermMemory(
            session_id="sess_export",
            role="assistant",
            content="这是回复内容",
            reasoning_content="这是推理过程",
            timestamp=__import__("datetime").datetime.now(),
        )
        db_session.add(mem)
        db_session.commit()

        result = audit_manager.export_reasoning_content(session_id="sess_export")
        assert result["total"] == 1
        assert result["items"][0]["reasoning_content"] == "这是推理过程"
        assert result["items"][0]["reasoning_length"] == 6

    def test_export_without_reasoning_content(self, audit_manager, db_session):
        # 插入不带推理内容的记忆记录
        mem = ShortTermMemory(
            session_id="sess_no_reasoning",
            role="assistant",
            content="这是回复内容",
            reasoning_content=None,
            timestamp=__import__("datetime").datetime.now(),
        )
        db_session.add(mem)
        db_session.commit()

        result = audit_manager.export_reasoning_content(session_id="sess_no_reasoning")
        assert result["total"] == 0

    def test_export_with_audit_metadata(self, audit_manager, db_session):
        # 插入记忆记录
        mem = ShortTermMemory(
            session_id="sess_with_audit",
            role="assistant",
            content="回复",
            reasoning_content="推理",
            timestamp=__import__("datetime").datetime.now(),
        )
        db_session.add(mem)
        db_session.commit()

        # 插入审计记录
        audit_manager.record_audit(
            session_id="sess_with_audit",
            complexity="complex",
            thinking_depth=5,
            reasoning_tokens=300,
            reasoning_duration_ms=2500,
            provider="anthropic",
            model="claude-4",
        )

        result = audit_manager.export_reasoning_content(session_id="sess_with_audit")
        assert result["total"] == 1
        item = result["items"][0]
        assert "audit" in item
        assert item["audit"]["complexity"] == "complex"
        assert item["audit"]["thinking_depth"] == 5
        assert item["audit"]["reasoning_tokens"] == 300


# ── 路由加载测试 ──────────────────────────────────────────


class TestRouterLoading:
    """路由模块加载测试。"""

    def test_cot_audit_router_importable(self):
        from api.routes.cot_audit import router
        assert router is not None
        assert router.prefix == "/api/cot"

    def test_cot_audit_router_has_routes(self):
        from api.routes.cot_audit import router
        assert len(router.routes) >= 5

    def test_cot_audit_router_registered_in_main(self):
        import main
        assert hasattr(main, "cot_audit_router")


# ── 数据模型注册测试 ──────────────────────────────────────────


class TestModelRegistration:
    """数据模型注册测试。"""

    def test_reasoning_audit_model_registered(self):
        from db.models import ReasoningAudit
        assert ReasoningAudit.__tablename__ == "reasoning_audits"

    def test_models_create_tables(self, db_session):
        """模型能正确创建表。"""
        db_session.query(ReasoningAudit).all()


# ── 工厂函数测试 ──────────────────────────────────────────


class TestFactoryFunctions:
    """工厂函数测试。"""

    def test_get_audit_manager_factory(self, db_session):
        m1 = get_audit_manager(db_session)
        m2 = get_audit_manager(db_session)
        # 工厂函数每次创建新实例
        assert m1 is not m2
        assert m1.db is m2.db
