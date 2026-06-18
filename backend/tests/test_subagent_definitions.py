"""
SubAgent 内置专业 Agent 与图定义持久化测试。

覆盖范围：
1. 内置专业 Agent（code_reviewer/searcher/data_analyst）功能
2. 图定义持久化 CRUD API
3. 图定义运行与执行历史持久化
4. 图定义校验逻辑
"""

import sys
from contextlib import contextmanager
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from api.dependencies import get_current_user, get_db
from api.routes import subagents as subagents_routes
from core.subagent import AgentState, SubAgentManager
from db.models import Base, SubagentDefinition, SubagentExecutionHistory
from main import app


engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base.metadata.create_all(bind=engine)


def override_get_db():
    """提供测试隔离数据库会话。"""
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


def override_get_current_user():
    """提供固定测试用户。"""

    class DummyUser:
        id = "user-1"
        username = "testuser"

    return DummyUser()


@contextmanager
def _test_client():
    """为 API 测试临时注入依赖。"""
    previous_overrides = dict(app.dependency_overrides)
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_get_current_user
    # 重置单例管理器以避免跨测试污染
    previous_manager = subagents_routes._manager
    previous_orchestrator = subagents_routes._orchestrator
    subagents_routes._manager = None
    subagents_routes._orchestrator = None
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides = previous_overrides
        subagents_routes._manager = previous_manager
        subagents_routes._orchestrator = previous_orchestrator


@pytest.fixture(autouse=True)
def reset_state():
    """保证每个测试从干净的数据库状态开始。"""
    db = TestingSessionLocal()
    try:
        db.query(SubagentDefinition).delete()
        db.query(SubagentExecutionHistory).delete()
        db.commit()
    finally:
        db.close()
    yield
    db = TestingSessionLocal()
    try:
        db.query(SubagentDefinition).delete()
        db.query(SubagentExecutionHistory).delete()
        db.commit()
    finally:
        db.close()


# ──────────────────────────────────────────────
#  内置专业 Agent 测试
# ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_builtin_code_reviewer_detects_eval():
    """验证代码审查 Agent 识别 eval 调用。"""
    from api.routes.subagents import _builtin_code_reviewer
    state = AgentState(context={
        'code': 'result = eval(input())',
        'language': 'python',
    })
    result_state = await _builtin_code_reviewer(state)
    review = result_state.get_result('code_reviewer')
    assert review['approved'] is False
    assert review['severity_count']['critical'] >= 1
    assert any(issue['category'] == 'security' for issue in review['issues'])


@pytest.mark.asyncio
async def test_builtin_code_reviewer_detects_hardcoded_password():
    """验证代码审查 Agent 识别硬编码密码。"""
    from api.routes.subagents import _builtin_code_reviewer
    state = AgentState(context={
        'code': 'password = "admin123"',
        'language': 'python',
    })
    result_state = await _builtin_code_reviewer(state)
    review = result_state.get_result('code_reviewer')
    assert review['severity_count']['high'] >= 1


@pytest.mark.asyncio
async def test_builtin_code_reviewer_detects_broad_exception():
    """验证代码审查 Agent 识别过宽异常捕获。"""
    from api.routes.subagents import _builtin_code_reviewer
    state = AgentState(context={
        'code': 'try:\n    pass\nexcept:\n    pass',
        'language': 'python',
    })
    result_state = await _builtin_code_reviewer(state)
    review = result_state.get_result('code_reviewer')
    assert review['severity_count']['medium'] >= 1


@pytest.mark.asyncio
async def test_builtin_code_reviewer_approves_clean_code():
    """验证代码审查 Agent 通过干净代码。"""
    from api.routes.subagents import _builtin_code_reviewer
    state = AgentState(context={
        'code': 'def add(a, b):\n    return a + b',
        'language': 'python',
    })
    result_state = await _builtin_code_reviewer(state)
    review = result_state.get_result('code_reviewer')
    assert review['approved'] is True
    assert review['severity_count']['critical'] == 0


@pytest.mark.asyncio
async def test_builtin_searcher_returns_keywords():
    """验证搜索 Agent 关键词扩展。"""
    from api.routes.subagents import _builtin_searcher
    state = AgentState(context={'query': 'python async programming'})
    result_state = await _builtin_searcher(state)
    search_result = result_state.get_result('searcher')
    assert search_result['success'] is True
    assert search_result['query'] == 'python async programming'
    assert len(search_result['keywords']) > 0
    assert search_result['total_results'] >= 1


@pytest.mark.asyncio
async def test_builtin_searcher_handles_empty_query():
    """验证搜索 Agent 处理空查询。"""
    from api.routes.subagents import _builtin_searcher
    state = AgentState(context={'query': ''})
    result_state = await _builtin_searcher(state)
    search_result = result_state.get_result('searcher')
    assert search_result['success'] is False
    assert search_result['error'] == '搜索查询为空'


@pytest.mark.asyncio
async def test_builtin_data_analyst_list_statistics():
    """验证数据分析 Agent 列表统计。"""
    from api.routes.subagents import _builtin_data_analyst
    state = AgentState(context={'data': [1, 2, 3, 4, 5]})
    result_state = await _builtin_data_analyst(state)
    analysis = result_state.get_result('data_analyst')
    assert analysis['success'] is True
    assert analysis['analysis']['record_count'] == 5
    assert analysis['analysis']['numeric_stats']['mean'] == 3.0
    assert analysis['analysis']['numeric_stats']['min'] == 1
    assert analysis['analysis']['numeric_stats']['max'] == 5


@pytest.mark.asyncio
async def test_builtin_data_analyst_dict_statistics():
    """验证数据分析 Agent 字典统计。"""
    from api.routes.subagents import _builtin_data_analyst
    state = AgentState(context={'data': {'a': 1, 'b': 'text', 'c': True}})
    result_state = await _builtin_data_analyst(state)
    analysis = result_state.get_result('data_analyst')
    assert analysis['success'] is True
    assert analysis['analysis']['record_count'] == 3
    assert analysis['analysis']['data_type'] == 'dict'
    assert set(analysis['analysis']['keys']) == {'a', 'b', 'c'}


@pytest.mark.asyncio
async def test_builtin_data_analyst_empty_data():
    """验证数据分析 Agent 处理空数据。"""
    from api.routes.subagents import _builtin_data_analyst
    state = AgentState(context={'data': []})
    result_state = await _builtin_data_analyst(state)
    analysis = result_state.get_result('data_analyst')
    assert analysis['success'] is False
    assert analysis['error'] == '数据为空'


@pytest.mark.asyncio
async def test_builtin_data_analyst_outlier_detection():
    """验证数据分析 Agent 异常检测。"""
    from api.routes.subagents import _builtin_data_analyst
    # 1000 是明显的异常值
    state = AgentState(context={'data': [1, 2, 3, 4, 1000]})
    result_state = await _builtin_data_analyst(state)
    analysis = result_state.get_result('data_analyst')
    assert analysis['success'] is True
    assert 'outliers' in analysis['analysis']
    assert 1000 in analysis['analysis']['outliers']


# ──────────────────────────────────────────────
#  内置 Agent 注册测试
# ──────────────────────────────────────────────

def test_builtin_agents_registered():
    """验证专业 Agent 已注册到管理器。"""
    from api.routes.subagents import _get_manager
    manager = _get_manager()
    agents = {info['name'] for info in manager.get_registered_agents()}
    assert 'code_reviewer' in agents
    assert 'searcher' in agents
    assert 'data_analyst' in agents
    # 基础 Agent 仍在
    assert 'analyzer' in agents
    assert 'planner' in agents


def test_builtin_pipelines_registered():
    """验证专业图已注册到管理器。"""
    from api.routes.subagents import _get_manager
    manager = _get_manager()
    graphs = {g['name'] for g in manager.get_graphs_info()}
    assert 'default_pipeline' in graphs
    assert 'code_review_pipeline' in graphs
    assert 'data_analysis_pipeline' in graphs


# ──────────────────────────────────────────────
#  图定义持久化 CRUD API 测试
# ──────────────────────────────────────────────

def _valid_graph_definition():
    """返回有效的图定义 payload。"""
    return {
        "name": "test_pipeline",
        "description": "测试图定义",
        "graph_definition": {
            "nodes": [
                {"name": "analyze", "agent_name": "analyzer", "description": "分析"},
                {"name": "review", "agent_name": "code_reviewer", "description": "审查"},
            ],
            "edges": [
                {"source": "analyze", "target": "review"},
            ],
            "entry_point": "analyze",
            "finish_points": ["review"],
        },
        "tags": "test",
    }


def test_create_definition_success():
    """验证创建图定义成功。"""
    with _test_client() as client:
        response = client.post("/api/subagents/definitions", json=_valid_graph_definition())
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "test_pipeline"
    assert data["is_builtin"] is False
    assert data["user_id"] == "user-1"
    assert len(data["graph_definition"]["nodes"]) == 2


def test_create_definition_duplicate_name_returns_409():
    """验证重复名称返回 409。"""
    with _test_client() as client:
        client.post("/api/subagents/definitions", json=_valid_graph_definition())
        response = client.post("/api/subagents/definitions", json=_valid_graph_definition())
    assert response.status_code == 409


def test_create_definition_invalid_agent_returns_400():
    """验证引用未注册 Agent 返回 400。"""
    payload = _valid_graph_definition()
    payload["graph_definition"]["nodes"][0]["agent_name"] = "nonexistent_agent"
    with _test_client() as client:
        response = client.post("/api/subagents/definitions", json=payload)
    assert response.status_code == 400


def test_create_definition_invalid_edge_returns_400():
    """验证引用不存在节点的边返回 400。"""
    payload = _valid_graph_definition()
    payload["graph_definition"]["edges"].append({"source": "nonexistent", "target": "analyze"})
    with _test_client() as client:
        response = client.post("/api/subagents/definitions", json=payload)
    assert response.status_code == 400


def test_list_definitions_returns_user_and_builtin():
    """验证列表返回用户定义和内置图。"""
    with _test_client() as client:
        # 先创建一个用户定义
        client.post("/api/subagents/definitions", json=_valid_graph_definition())
        # 插入一个内置图
        db = TestingSessionLocal()
        try:
            db.add(SubagentDefinition(
                name="builtin_graph",
                description="内置",
                graph_definition={"nodes": [], "edges": [], "entry_point": "", "finish_points": []},
                user_id="other-user",
                is_builtin=True,
            ))
            db.commit()
        finally:
            db.close()

        response = client.get("/api/subagents/definitions")
    assert response.status_code == 200
    data = response.json()
    names = {item["name"] for item in data}
    assert "test_pipeline" in names  # 用户定义
    assert "builtin_graph" in names  # 内置图


def test_update_definition_success():
    """验证更新图定义成功。"""
    with _test_client() as client:
        create_resp = client.post("/api/subagents/definitions", json=_valid_graph_definition())
        def_id = create_resp.json()["id"]
        update_payload = {
            "description": "更新后的描述",
            "tags": "updated",
        }
        response = client.put(f"/api/subagents/definitions/{def_id}", json=update_payload)
    assert response.status_code == 200
    data = response.json()
    assert data["description"] == "更新后的描述"
    assert data["tags"] == "updated"


def test_delete_definition_success():
    """验证删除图定义成功。"""
    with _test_client() as client:
        create_resp = client.post("/api/subagents/definitions", json=_valid_graph_definition())
        def_id = create_resp.json()["id"]
        response = client.delete(f"/api/subagents/definitions/{def_id}")
    assert response.status_code == 200
    # 验证已删除
    db = TestingSessionLocal()
    try:
        assert db.query(SubagentDefinition).filter_by(id=def_id).first() is None
    finally:
        db.close()


def test_delete_builtin_definition_returns_403():
    """验证删除内置图返回 403。"""
    db = TestingSessionLocal()
    try:
        definition = SubagentDefinition(
            name="builtin_to_delete",
            description="内置",
            graph_definition={"nodes": [], "edges": [], "entry_point": "", "finish_points": []},
            user_id="user-1",
            is_builtin=True,
        )
        db.add(definition)
        db.commit()
        db.refresh(definition)
        def_id = definition.id
    finally:
        db.close()

    with _test_client() as client:
        response = client.delete(f"/api/subagents/definitions/{def_id}")
    assert response.status_code == 403


# ──────────────────────────────────────────────
#  图定义运行与执行历史测试
# ──────────────────────────────────────────────

def test_run_definition_success_persists_history():
    """验证运行图定义成功并持久化执行历史。"""
    with _test_client() as client:
        create_resp = client.post("/api/subagents/definitions", json=_valid_graph_definition())
        def_id = create_resp.json()["id"]
        run_payload = {"context": {"user_message": "test"}}
        response = client.post(f"/api/subagents/definitions/{def_id}/run", json=run_payload)
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert "results" in data
    assert "execution_log" in data

    # 验证执行历史已持久化
    db = TestingSessionLocal()
    try:
        history = db.query(SubagentExecutionHistory).filter_by(graph_name="test_pipeline").first()
        assert history is not None
        assert history.success is True
        assert history.user_id == "user-1"
        assert history.execution_mode == "graph"
    finally:
        db.close()


def test_list_execution_history_returns_user_records():
    """验证查询执行历史返回当前用户的记录。"""
    with _test_client() as client:
        create_resp = client.post("/api/subagents/definitions", json=_valid_graph_definition())
        def_id = create_resp.json()["id"]
        client.post(f"/api/subagents/definitions/{def_id}/run", json={"context": {}})

        response = client.get("/api/subagents/history")
    assert response.status_code == 200
    data = response.json()
    assert len(data) >= 1
    assert data[0]["graph_name"] == "test_pipeline"
    assert data[0]["user_id"] == "user-1"


def test_list_execution_history_filter_by_graph_name():
    """验证按图名称过滤执行历史。"""
    with _test_client() as client:
        # 创建两个不同的图定义
        payload1 = _valid_graph_definition()
        payload2 = _valid_graph_definition()
        payload2["name"] = "another_pipeline"
        def_id1 = client.post("/api/subagents/definitions", json=payload1).json()["id"]
        def_id2 = client.post("/api/subagents/definitions", json=payload2).json()["id"]

        client.post(f"/api/subagents/definitions/{def_id1}/run", json={"context": {}})
        client.post(f"/api/subagents/definitions/{def_id2}/run", json={"context": {}})

        response = client.get("/api/subagents/history?graph_name=test_pipeline")
    assert response.status_code == 200
    data = response.json()
    assert all(item["graph_name"] == "test_pipeline" for item in data)


def test_get_execution_history_detail():
    """验证获取执行历史详情。"""
    with _test_client() as client:
        create_resp = client.post("/api/subagents/definitions", json=_valid_graph_definition())
        def_id = create_resp.json()["id"]
        client.post(f"/api/subagents/definitions/{def_id}/run", json={"context": {}})

        list_resp = client.get("/api/subagents/history")
        history_id = list_resp.json()[0]["id"]

        response = client.get(f"/api/subagents/history/{history_id}")
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == history_id
    assert "results" in data
    assert "execution_log" in data


def test_get_execution_history_not_found():
    """验证获取不存在的执行历史返回 404。"""
    with _test_client() as client:
        response = client.get("/api/subagents/history/99999")
    assert response.status_code == 404
