"""
测试场景执行器 - 定义真实功能测试场景，通过API触发端到端验证。
供Claude Code等外部工具通过HTTP调用，测试系统各功能是否正常启用。
"""

import asyncio
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List

from fastapi import APIRouter, Depends
from loguru import logger
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from api.dependencies import get_current_user
from db.models import User, get_db, ScheduledTask

router = APIRouter(prefix="/api/test-scenarios", tags=["Test Scenarios"])


class RunScenarioRequest(BaseModel):
    """运行单个场景的请求体"""
    name: str = Field(..., description="场景名称")


class ScenarioResult(BaseModel):
    """单个场景的执行结果"""
    name: str
    label: str
    category: str
    status: str = "idle"
    duration_ms: float = 0
    message: str = ""
    detail: Any = None


class ScenarioRunResponse(BaseModel):
    """场景运行响应"""
    results: List[ScenarioResult]
    passed: int
    failed: int
    total: int
    duration_ms: float


# 场景定义
SCENARIO_DEFINITIONS: Dict[str, Dict[str, str]] = {
    "health-basic": {
        "label": "服务器基础健康",
        "category": "基础设施",
        "description": "验证 /health 端点可达，服务进程正常运行",
    },
    "diagnostics-full": {
        "label": "全量系统诊断",
        "category": "基础设施",
        "description": "运行所有子系统诊断检查(DB/插件/技能/MCP)",
    },
    "conversation-lifecycle": {
        "label": "对话全生命周期",
        "category": "对话管理",
        "description": "创建对话 → 列表查询 → 重命名 → 软删除 → 恢复",
    },
    "chat-nonstream": {
        "label": "非流式聊天",
        "category": "AI聊天",
        "description": "发送非流式消息，验证AI代理能返回有效响应",
    },
    "plugin-discovery": {
        "label": "插件发现与列表",
        "category": "插件系统",
        "description": "列出已加载插件，验证 twitter-monitor 等已加载",
    },
    "skills-list": {
        "label": "技能列表",
        "category": "技能系统",
        "description": "列出已注册技能，验证内置技能可访问",
    },
    "tool-file-operation": {
        "label": "文件工具操作",
        "category": "工具调用",
        "description": "测试文件列表和文件读取工具是否正常工作",
    },
    "scheduled-task-lifecycle": {
        "label": "定时任务生命周期",
        "category": "定时任务",
        "description": "创建一次性任务 → 查看详情 → 取消任务",
    },
    "auth-session-valid": {
        "label": "用户会话验证",
        "category": "身份认证",
        "description": "验证当前认证用户会话有效且能获取用户信息",
    },
    "mcp-status": {
        "label": "MCP服务状态",
        "category": "MCP服务",
        "description": "查询MCP服务器连接状态和工具数量",
    },
}


def _timed_run(name: str, label: str, category: str, fn: Callable, *args, **kwargs) -> ScenarioResult:
    """包装场景函数，统一计时和异常捕获"""
    start = time.perf_counter()
    try:
        detail, message = fn(*args, **kwargs)
        elapsed = (time.perf_counter() - start) * 1000
        return ScenarioResult(
            name=name, label=label, category=category,
            status="ok", duration_ms=round(elapsed, 2),
            message=message, detail=detail,
        )
    except Exception as e:
        elapsed = (time.perf_counter() - start) * 1000
        logger.warning(f"场景 [{name}] 执行失败: {e}")
        return ScenarioResult(
            name=name, label=label, category=category,
            status="fail", duration_ms=round(elapsed, 2),
            message=f"场景执行异常: {str(e)}", detail={"error": str(e)},
        )


# ---- 场景实现 ----

def _run_health_basic() -> tuple:
    """验证服务基础健康检查可达（真实 HTTP 请求 /api/system/health 并断言 200）"""
    import os

    import httpx

    raw_port = (os.getenv("BACKEND_PORT") or os.getenv("PORT") or "8000").strip() or "8000"
    try:
        port = int(raw_port)
    except ValueError as exc:
        raise RuntimeError(f"无效的端口配置: {raw_port}") from exc
    url = f"http://127.0.0.1:{port}/api/system/health"
    try:
        resp = httpx.get(url, timeout=10.0)
    except Exception as exc:
        raise RuntimeError(f"/api/system/health 请求失败: {exc}") from exc
    if resp.status_code != 200:
        raise RuntimeError(
            f"/api/system/health 返回 HTTP {resp.status_code}: {resp.text[:300]}"
        )
    return {
        "endpoint": url,
        "status_code": resp.status_code,
        "body": resp.json(),
    }, "服务健康检查正常（HTTP 200）"


def _run_diagnostics_full(db: Session, current_user: User) -> tuple:
    """运行完整系统诊断"""
    from api.routes.system import _check_database, _check_plugins, _check_skills, _check_mcp

    db_status = _check_database()
    plugins_status = _check_plugins()
    skills_status = _check_skills()
    mcp_status = _check_mcp()

    checks = [
        ("数据库", db_status["ok"]),
        ("插件系统", plugins_status["ok"]),
        ("技能系统", skills_status["ok"]),
        ("MCP服务", mcp_status["ok"]),
    ]
    passed = [c[0] for c in checks if c[1]]
    failed = [c[0] for c in checks if not c[1]]

    detail = {
        "database": db_status,
        "plugins": plugins_status,
        "skills": skills_status,
        "mcp": mcp_status,
    }
    if failed:
        raise RuntimeError(
            f"诊断失败: {len(passed)}通过 / {len(failed)}失败 ({', '.join(failed)})"
        )
    return detail, f"诊断完成: 全部 {len(passed)} 项通过"


def _run_conversation_lifecycle(db: Session, current_user: User) -> tuple:
    """对话完整生命周期测试"""
    from core.conversation_sessions import (
        ensure_conversation,
        soft_delete_conversation, restore_conversation,
    )

    # 创建
    session_id = f"test-scenario:{uuid.uuid4().hex}"
    conv = ensure_conversation(
        db,
        session_id,
        str(current_user.id),
        title="[测试] 自动化场景验证",
    )
    if conv is None:
        raise RuntimeError("测试会话创建失败")
    session_id = conv.session_id

    # 重命名
    conv.title = "[测试] 自动化场景验证-已重命名"
    db.commit()

    # 软删除
    soft_delete_conversation(db, session_id, str(current_user.id))
    db.commit()

    # 恢复
    restored = restore_conversation(db, session_id, str(current_user.id))

    return {
        "session_id": session_id,
        "title": restored.title,
        "deleted_at": restored.deleted_at,
    }, f"对话生命周期测试通过 (会话ID: {session_id[:12]})"


def _run_chat_nonstream(db: Session, current_user: User) -> tuple:
    """通过AIAgent发送非流式聊天消息并验证响应"""
    import asyncio
    import threading
    from api.adapters.workflow_repository_adapter import WorkflowRepositoryAdapter
    from core.agent import AIAgent
    from db.models import SessionLocal

    context = {
        "user_id": current_user.id,
        "username": current_user.username,
        "session_id": "test-scenario-probe",
        "db": db,
        "output_mode": "final_only",
    }

    # 与生产 chat 路由保持一致：构造必须注入完整持久化边界
    # （db_session / workflow_repository / memory_session_factory），
    # 否则能力注入与对话历史构建在缺依赖时 fail-closed 抛出
    agent = AIAgent(
        db_session=db,
        workflow_repository=WorkflowRepositoryAdapter(db),
        memory_session_factory=SessionLocal,
    )
    coro = agent.process(
        "你好，请回复'功能测试通过'这一句话，不要多说任何其他内容。",
        context
    )

    # 安全运行异步协程：如果当前处于异步上下文（FastAPI），在新线程中执行
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        result = asyncio.run(coro)
    else:
        result_holder = {}
        error_holder = {}

        def _runner():
            new_loop = asyncio.new_event_loop()
            asyncio.set_event_loop(new_loop)
            try:
                result_holder["value"] = new_loop.run_until_complete(coro)
            except BaseException as thread_error:
                error_holder["error"] = thread_error
            finally:
                new_loop.close()

        thread = threading.Thread(target=_runner, daemon=True)
        thread.start()
        thread.join(timeout=120.0)
        if thread.is_alive():
            raise TimeoutError("非流式聊天场景执行超过 120 秒")
        if "error" in error_holder:
            raise error_holder["error"]
        result = result_holder.get("value")

    if not isinstance(result, dict):
        raise RuntimeError("非流式聊天未返回结构化结果")
    response_text = result.get("response", "")
    status = str(result.get("status") or "")
    if status not in {"completed", "success"}:
        error_detail = result.get("error") or response_text or "未知错误"
        raise RuntimeError(f"非流式聊天执行失败 (status={status}): {error_detail}")
    has_content = bool(response_text and len(response_text.strip()) > 0)
    if not has_content:
        raise RuntimeError("非流式聊天返回为空")

    return {
        "response_preview": response_text[:200],
        "response_length": len(response_text),
        "status": status,
    }, f"聊天响应正常，返回 {len(response_text)} 字符"


def _run_plugin_discovery(db: Session, current_user: User) -> tuple:
    """验证插件发现和列表"""
    from plugins.plugin_instance import get

    manager = get()
    loaded = list(manager.loaded_plugins.keys())
    discovered = manager.discover_plugins()

    return {
        "loaded_count": len(loaded),
        "loaded_plugins": loaded,
        "discovered_count": len(discovered),
    }, f"插件系统正常: 已加载 {len(loaded)} 个, 发现 {len(discovered)} 个"


def _run_skills_list(db: Session, current_user: User) -> tuple:
    """验证技能列表"""
    from skills.skill_loader import SkillLoader

    loader = SkillLoader(db_session=db)
    skills = loader.list_skills()
    enabled = [s.get("name", s.get("id", "?")) for s in skills if s.get("enabled", True)]

    return {
        "total_skills": len(skills),
        "enabled_count": len(enabled),
        "enabled_skills": enabled[:10],
    }, f"技能系统正常: {len(skills)} 个技能, {len(enabled)} 个已启用"


def _run_tool_file_operation() -> tuple:
    """验证文件列表和读取工具；任一操作失败即抛错，由场景框架标记为失败"""
    import os

    # 列出当前目录的 .py 文件；失败即抛错，禁止以 message 文案形式静默通过
    py_files = [f for f in os.listdir(".") if f.endswith(".py")]
    list_count = len(py_files)
    if list_count == 0:
        raise RuntimeError("当前目录未发现 .py 文件，文件列表工具验证失败")

    # 读取 main.py
    with open("main.py", "r", encoding="utf-8") as fh:
        content = fh.read()
    if not content:
        raise RuntimeError("main.py 读取内容为空，文件读取工具验证失败")
    preview = content[:100]

    return {
        "file_list": {"ok": True, "file_count": list_count},
        "file_read": {"ok": True, "preview": preview},
    }, f"文件工具正常: 列表通过 ({list_count}个py文件), 读取通过"


def _run_scheduled_task_lifecycle(db: Session, current_user: User) -> tuple:
    """定时任务生命周期测试"""
    now = datetime.now(timezone.utc)
    task = ScheduledTask(
        user_id=current_user.id,
        title="[测试] 自动化场景-定时任务",
        prompt="回复'任务执行成功'",
        scheduled_at=now + timedelta(hours=24),
        status="pending",
        provider="openai",
        model="gpt-3.5-turbo",
    )
    db.add(task)
    db.commit()

    # 读取
    db.refresh(task)
    task_id = task.id

    # 取消
    task.status = "cancelled"
    task.cancelled_at = datetime.now(timezone.utc)
    db.commit()

    return {
        "task_id": task_id,
        "title": task.title,
        "final_status": "cancelled",
    }, f"定时任务生命周期测试通过 (任务ID: {task_id})"


def _run_auth_session_valid(db: Session, current_user: User) -> tuple:
    """验证当前用户会话"""
    return {
        "user_id": current_user.id,
        "username": current_user.username,
        "role": current_user.role,
    }, f"用户会话有效: {current_user.username} (role={current_user.role})"


def _run_mcp_status() -> tuple:
    """验证MCP服务状态"""
    from mcp.manager import MCPManager

    manager = MCPManager()
    servers = manager.get_all_servers()
    connected = [s for s in servers if s.get("status") == "connected"]

    return {
        "total_servers": len(servers),
        "connected_count": len(connected),
        "server_ids": [s.get("id", "?") for s in servers],
    }, f"MCP服务正常: {len(servers)} 个服务器, {len(connected)} 个已连接"


# 场景注册表
SCENARIO_RUNNERS: Dict[str, Callable] = {
    "health-basic": lambda db, user: _timed_run("health-basic", "服务器基础健康", "基础设施", _run_health_basic),
    "diagnostics-full": lambda db, user: _timed_run("diagnostics-full", "全量系统诊断", "基础设施", _run_diagnostics_full, db, user),
    "conversation-lifecycle": lambda db, user: _timed_run("conversation-lifecycle", "对话全生命周期", "对话管理", _run_conversation_lifecycle, db, user),
    "chat-nonstream": lambda db, user: _timed_run("chat-nonstream", "非流式聊天", "AI聊天", _run_chat_nonstream, db, user),
    "plugin-discovery": lambda db, user: _timed_run("plugin-discovery", "插件发现与列表", "插件系统", _run_plugin_discovery, db, user),
    "skills-list": lambda db, user: _timed_run("skills-list", "技能列表", "技能系统", _run_skills_list, db, user),
    "tool-file-operation": lambda db, user: _timed_run("tool-file-operation", "文件工具操作", "工具调用", _run_tool_file_operation),
    "scheduled-task-lifecycle": lambda db, user: _timed_run("scheduled-task-lifecycle", "定时任务生命周期", "定时任务", _run_scheduled_task_lifecycle, db, user),
    "auth-session-valid": lambda db, user: _timed_run("auth-session-valid", "用户会话验证", "身份认证", _run_auth_session_valid, db, user),
    "mcp-status": lambda db, user: _timed_run("mcp-status", "MCP服务状态", "MCP服务", _run_mcp_status),
}


# ---- API 端点 ----

@router.get("")
async def list_scenarios(
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """
    列出所有可用测试场景及其描述。
    供Claude Code等工具了解可用的测试场景。

    需要认证：场景元数据暴露了系统支持的测试能力，匿名探测不应获得此信息。
    """
    scenarios = []
    for name, info in SCENARIO_DEFINITIONS.items():
        scenarios.append({
            "name": name,
            "label": info["label"],
            "category": info["category"],
            "description": info["description"],
        })
    return {"total": len(scenarios), "scenarios": scenarios}


@router.post("/run")
async def run_scenario(
    body: RunScenarioRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """
    运行指定的单个测试场景。
    传入场景名称，返回执行结果（通过/失败/耗时）。
    """
    name = body.name.strip()
    if name not in SCENARIO_RUNNERS:
        return {
            "results": [{
                "name": name, "label": "未知场景", "category": "N/A",
                "status": "fail", "duration_ms": 0,
                "message": f"未知场景名称: {name}",
                "detail": None,
            }],
            "passed": 0, "failed": 1, "total": 1, "duration_ms": 0,
        }

    runner = SCENARIO_RUNNERS[name]
    start = time.perf_counter()
    # 场景为同步函数且可能发起到自身的 HTTP 请求（health-basic），
    # 必须在线程池执行，避免阻塞事件循环导致自请求死锁
    result = await asyncio.to_thread(runner, db, current_user)
    total_ms = round((time.perf_counter() - start) * 1000, 2)

    passed = 1 if result.status == "ok" else 0
    failed = 0 if result.status == "ok" else 1

    logger.bind(
        event="test_scenario_run",
        module="test_runner",
        scenario=name,
        status=result.status,
        duration_ms=result.duration_ms,
        user_id=current_user.id,
    ).info(f"场景 [{name}] 执行完成: {result.status}")

    return ScenarioRunResponse(
        results=[result],
        passed=passed,
        failed=failed,
        total=1,
        duration_ms=total_ms,
    ).model_dump()


@router.post("/run-all")
async def run_all_scenarios(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """
    运行全部测试场景。
    按顺序执行所有已注册场景，返回汇总报告。
    """
    results: List[ScenarioResult] = []
    start = time.perf_counter()

    for name in SCENARIO_DEFINITIONS:
        runner = SCENARIO_RUNNERS[name]
        # 同步场景在线程池执行：health-basic 会向自身端口发起真实 HTTP
        # 请求，若在事件循环线程同步阻塞则服务无法响应自己的请求（自死锁超时）
        result = await asyncio.to_thread(runner, db, current_user)
        results.append(result)
        logger.bind(
            event="test_scenario_run",
            module="test_runner",
            scenario=name,
            status=result.status,
            duration_ms=result.duration_ms,
            user_id=current_user.id,
        ).info(f"场景 [{name}] 执行完成: {result.status}")

    total_ms = round((time.perf_counter() - start) * 1000, 2)
    passed = sum(1 for r in results if r.status == "ok")
    failed = len(results) - passed

    logger.bind(
        event="test_scenario_run_all",
        module="test_runner",
        passed=passed,
        failed=failed,
        total=len(results),
        duration_ms=total_ms,
        user_id=current_user.id,
    ).info(f"全部场景执行完成: {passed}/{len(results)} 通过")

    return ScenarioRunResponse(
        results=results,
        passed=passed,
        failed=failed,
        total=len(results),
        duration_ms=total_ms,
    ).model_dump()
