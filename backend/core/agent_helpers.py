"""AIAgent 纯工具函数集合，不访问实例状态，可被 agent.py 与测试套件复用。

本模块包含以下 8 个纯函数（原 AIAgent 的 @staticmethod，已迁移以便独立测试与演进）：
- is_final_only_mode: 判断当前请求是否要求只返回最终答案
- build_status_event: 构造统一的流式阶段状态事件
- map_finish_reason_to_state: 将 LLM finish_reason 映射为 AgentState
- get_stream_tool_kind: 根据原生 function name 推断工具类别
- summarize_stream_tool_result: 为流式工具事件生成简短摘要
- extract_spawned_subagent_result: 从 task_spawn_agent 结果中提取子代理标识
- build_effective_user_input: 为 continuation 请求拼接内部补充上下文
- build_configured_model_hint: 为 task_spawn_agent 生成精简模型目录提示

另含两个用于消除 agent.py 重复代码的工具：
- match_keywords_against: 合并 _is_skill_relevant / _is_plugin_relevant 共同逻辑
- ttft_stage_logger: 封装 process_stream 中重复的 TTFT 阶段计时日志

core/agent.py 中对应的方法保留为类级别 backward compat 别名（@staticmethod 赋值），
仅用于兼容既有测试 AIAgent._method_name(...) 调用，待 fix-test-implementation-coupling
spec 落地后移除。
"""

from __future__ import annotations

# 标准库
import time
from contextlib import contextmanager
from typing import Any, Dict, List, Optional

# 第三方库
from loguru import logger

# 项目内部
from core.agent_state import AgentState


COMPACTION_MESSAGE_THRESHOLD = 40
MAX_HISTORY_MESSAGE_CHARS = 5_000


def is_final_only_mode(context: Dict[str, Any]) -> bool:
    """
    判断当前请求是否要求只返回最终答案。

    `output_mode=final_only` 是显式协议约定，`suppress_reasoning`
    则作为兼容旧调用方的兜底开关。
    """
    output_mode = str(context.get("output_mode", "")).strip().lower()
    # 如果明确禁用了思考模式，也应对外按 final_only 语义剥离推理内容。
    return (
        output_mode == "final_only"
        or bool(context.get("suppress_reasoning"))
        or context.get("thinking_enabled") is False
    )


def build_status_event(phase: str, message: str, **extra: Any) -> Dict[str, Any]:
    """
    构造统一的流式阶段状态事件，便于前端在首包前显示当前进度。
    """
    payload: Dict[str, Any] = {
        "type": "status",
        "phase": phase,
        "message": message,
    }
    payload.update(extra)
    return payload


def map_finish_reason_to_state(
    finish_reason: str,
    current_round: int,
    max_rounds: int,
) -> AgentState:
    """
    将 LLM 返回的 finish_reason 映射为 AgentState 状态机状态。

    映射规则：
    - current_round >= max_rounds 时优先返回 TERMINAL_MAX_ROUNDS（防止无限循环）
    - tool_calls -> CONTINUE_TOOL_CALLS（执行工具后继续下一轮）
    - stop -> TERMINAL_END_TURN（正常结束）
    - length -> CONTINUE_COMPACT（上下文超限，压缩后继续）
    - content_filter -> TERMINAL_REFUSAL（模型拒绝）
    - 其他未知值 -> 抛出 ValueError（显式错误路径，禁止静默当作正常结束）

    参数:
        finish_reason: LLM 返回的结束原因字符串
        current_round: 当前已执行的轮次（从 1 开始计数）
        max_rounds: 允许的最大轮次上限

    返回:
        对应的 AgentState 枚举值
    """
    # 最大轮次检查优先级最高，避免在边界处仍触发工具调用导致无限循环
    if current_round >= max_rounds:
        return AgentState.TERMINAL_MAX_ROUNDS

    normalized = str(finish_reason or "").strip().lower()
    if normalized == "tool_calls":
        return AgentState.CONTINUE_TOOL_CALLS
    if normalized == "stop":
        return AgentState.TERMINAL_END_TURN
    if normalized == "length":
        return AgentState.CONTINUE_COMPACT
    if normalized == "content_filter":
        return AgentState.TERMINAL_REFUSAL
    # 未知 finish_reason 必须走显式错误路径，禁止静默当作正常结束
    raise ValueError(f"未知的 finish_reason: {finish_reason!r}")


def get_stream_tool_kind(tool_name: str) -> str:
    """
    根据原生 function name 推断工具类别，便于前端展示正确的分组标签。
    """
    normalized = str(tool_name or "").strip()
    if normalized.startswith("plugin_"):
        return "plugin"
    if normalized.startswith("mcp_"):
        return "mcp"
    if normalized.startswith("task_"):
        return "task"
    return "tool"


def summarize_stream_tool_result(exec_result: Dict[str, Any]) -> str:
    """
    为流式工具事件生成简短摘要，避免前端只能看到空的占位节点。
    """
    if not isinstance(exec_result, dict):
        return ""

    if not exec_result.get("ok"):
        return str(exec_result.get("error") or "工具调用失败")

    payload = exec_result.get("result")
    if isinstance(payload, dict):
        for key in ("message", "response", "stdout", "status"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return "工具调用完成"


def extract_spawned_subagent_result(exec_result: Dict[str, Any]) -> Optional[Dict[str, str]]:
    """
    从 task_spawn_agent 的执行结果中提取真实子代理标识与运行模式。
    """
    if not isinstance(exec_result, dict) or not exec_result.get("ok"):
        return None

    payload = exec_result.get("result")
    if not isinstance(payload, dict):
        return None

    nested_payload = payload.get("result")
    if isinstance(nested_payload, dict) and nested_payload.get("agent_id"):
        payload = nested_payload

    agent_id = payload.get("agent_id")
    if not isinstance(agent_id, str) or not agent_id.strip():
        return None

    run_mode = str(payload.get("run_mode") or "").strip().lower()
    status = str(payload.get("status") or "").strip().lower()
    return {
        "agent_id": agent_id.strip(),
        "run_mode": run_mode,
        "status": status,
    }


def build_effective_user_input(user_input: str, context: Dict[str, Any]) -> str:
    """
    为 continuation 请求拼接内部补充上下文，使模型在同一轮任务中继续推进。
    """
    continuation = context.get("continuation")
    if not isinstance(continuation, dict):
        return user_input

    aggregated_context = str(continuation.get("aggregated_context") or "").strip()
    if not aggregated_context:
        return user_input

    source = str(continuation.get("source") or "subagent").strip() or "subagent"
    instruction = (
        f"以下内容是同一轮任务中来自 {source} 的补充执行结果。"
        "请将其视为当前任务的内部上下文，基于这些结果继续完成上一轮任务。"
        "除非确有必要，否则不要重复启动已经完成的子代理。"
    )

    normalized_user_input = str(user_input or "").strip()
    if normalized_user_input:
        return f"{normalized_user_input}\n\n{instruction}\n\n[子代理聚合结果]\n{aggregated_context}"
    return f"{instruction}\n\n[子代理聚合结果]\n{aggregated_context}"


def build_configured_model_hint(capabilities: Dict[str, Any], limit: int = 12) -> str:
    """
    为 task_spawn_agent 生成精简的模型目录提示，帮助模型自行选择已配置模型。
    """
    configured_models = (
        capabilities.get("configured_models")
        if isinstance(capabilities.get("configured_models"), dict)
        else {}
    )
    entries = configured_models.get("entries") if isinstance(configured_models.get("entries"), list) else []
    labels = [
        str(entry.get("label", "")).strip()
        for entry in entries[:limit]
        if isinstance(entry, dict) and str(entry.get("label", "")).strip()
    ]
    if not labels:
        return "当前未发现可枚举的已配置模型；若省略 provider 和 model，将回退到系统默认配置。"

    suffix = " 等" if len(entries) > len(labels) else ""
    hint = f"当前可选的已配置模型: {'、'.join(labels)}{suffix}。"

    # 生图模型目录：仅供图像生成，用途描述辅助选择；生图类工具选择模型时优先参考
    image_entries = (
        configured_models.get("image_entries")
        if isinstance(configured_models.get("image_entries"), list)
        else []
    )
    if image_entries:
        image_lines: List[str] = []
        for entry in image_entries[:limit]:
            if not isinstance(entry, dict):
                continue
            label = str(entry.get("label", "")).strip()
            if not label:
                continue
            usage = str(entry.get("usage", "")).strip()
            image_lines.append(f"{label}" + (f"（用途/限制：{usage}）" if usage else ""))
        hint += f" 可用生图模型（仅用于图像生成，不可聊天）: {'、'.join(image_lines)}。"

    return hint


def match_keywords_against(
    name: str,
    description: str,
    intent_keywords: str,
    entities: List[Dict[str, Any]],
) -> bool:
    """判断给定名称与描述是否匹配意图关键词或实体类型。

    合并自 AIAgent._is_skill_relevant 与 AIAgent._is_plugin_relevant 的共同逻辑：
    - 名称（小写）或描述包含任一长度超过 3 字符的意图关键词即匹配
    - 名称（小写）或描述包含任一非空实体 type（小写）即匹配
    - intent_keywords 为空或 entities 为空时返回 False

    严格保留原方法的匹配语义：
    - intent_keywords 按空白字符分隔（split()），不是逗号分隔
    - 仅匹配 len(keyword) > 3 的关键词
    - 实体字段名为 'type'，不是 'value'
    - 名称使用小写匹配，描述保留原大小写
    - 实体 type 为空字符串时跳过

    Args:
        name: 技能/插件名称
        description: 技能/插件描述
        intent_keywords: 空白分隔的意图关键词字符串
        entities: 实体列表，每项含 type 字段

    Returns:
        bool: 是否匹配
    """
    name_lower = name.lower()

    # 关键词匹配：仅长度超过 3 字符的关键词参与匹配，避免短词误匹配
    if any(
        keyword in name_lower or keyword in description
        for keyword in intent_keywords.split()
        if len(keyword) > 3
    ):
        return True

    # 实体类型匹配：实体 type 转小写后参与匹配，空字符串跳过
    entity_types = [entity.get("type", "").lower() for entity in entities]
    if any(
        entity_type in name_lower or entity_type in description
        for entity_type in entity_types
        if entity_type
    ):
        return True

    return False


@contextmanager
def ttft_stage_logger(
    stage: str,
    session_id: str,
    t0: float,
    *,
    extra_fields: Optional[Dict[str, Any]] = None,
    min_elapsed_ms: Optional[float] = None,
):
    """TTFT 阶段计时 contextmanager。

    封装 process_stream 中重复的 logger.bind(event="ttft_stage", ...) 模式。
    进入时记录阶段开始时间，退出时输出日志。

    兼容原 8 处 TTFT 阶段计时日志：
    - role_engine / inject_capabilities / build_history / auto_compress
    - retrieve_memories / recognize_intent / extract_entities / create_plan

    Args:
        stage: 阶段名称（如 "role_engine" / "inject_capabilities"）
        session_id: 会话 ID
        t0: 整个 process_stream 的起始时间戳，用于计算 total_ms
        extra_fields: 额外日志字段（如 {"memory_count": 3}）；
            调用方可在 with 块内动态填充此 dict，退出时按最新值写入日志
        min_elapsed_ms: 最小耗时阈值（毫秒），低于此值不输出日志；
            用于 auto_compress 阶段保留 "仅超过 50ms 才记录" 的原行为

    Yields:
        None
    """
    stage_t0 = time.time()
    try:
        yield
    finally:
        elapsed_ms = round((time.time() - stage_t0) * 1000, 2)
        # 保留 auto_compress 阶段 "仅超过 50ms 才记录" 的原行为
        if min_elapsed_ms is not None and elapsed_ms < min_elapsed_ms:
            return
        log_payload: Dict[str, Any] = {
            "event": "ttft_stage",
            "module": "agent",
            "stage": stage,
            "session_id": session_id,
            "elapsed_ms": elapsed_ms,
            "total_ms": round((time.time() - t0) * 1000, 2),
        }
        if extra_fields:
            log_payload.update(extra_fields)
        logger.bind(**log_payload).info(f"阶段耗时: {stage}")
