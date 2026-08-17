"""
核心执行编排模块,负责 Agent 主流程中的理解,规划,执行,反馈或记录能力.
这些文件决定了用户请求在内部被如何拆解,编排以及最终落地执行.
"""

import asyncio
import base64
import json
import time
import uuid
from pathlib import Path
from typing import Dict, List, Any, Optional
from loguru import logger


class MemoryPersistenceError(RuntimeError):
    """记忆写入失败且无法安全降级时抛出的异常。"""


class FeedbackLayer:
    """
    Agent 反馈层:负责在工具调用完成后提取经验,记录对话并持久化记忆.
    依赖外部注入的 MemoryManager 执行实际的记忆写入操作.
    """
    def __init__(self):
        """初始化反馈层,memory_manager 需通过 set_memory_manager 注入."""
        self.memory_manager = None
        # Spec memory-quality-and-short-term-recovery Task 6：记忆巩固运行器
        # 由 agent.py 注入；未注入时跳过自动巩固触发（测试或离线场景）
        self.consolidation_runner = None
        logger.info("FeedbackLayer initialized")

    def set_memory_manager(self, memory_manager):
        """注入 MemoryManager 实例,供后续反馈收集时写入记忆和对话记录."""
        self.memory_manager = memory_manager

    # ------------------------------------------------------------------
    # 多模态记忆：图片附件落盘（Spec 多模态记忆）
    # ------------------------------------------------------------------
    _MEMORY_IMAGE_MIME_EXT = {
        "image/png": ".png",
        "image/jpeg": ".jpg",
        "image/jpg": ".jpg",
        "image/gif": ".gif",
        "image/webp": ".webp",
    }

    async def _persist_image_attachments(
        self,
        context: Dict[str, Any],
        user_id: Optional[str],
    ) -> List[Dict[str, Any]]:
        """把本轮聊天中的图片附件落盘到上传目录，返回短期记忆用的图片事件列表。

        图片 base64 → 文件（var/data/uploads/chat，与 /api/chat/upload 同目录），
        访问 URL 为 /api/chat/uploads/{filename}（带所有权校验）。
        视觉理解模型未配置时仅保留图片引用；配置后记忆提炼可基于 URL 理解图片内容。
        """
        attachments = context.get("attachments") or []
        if not attachments:
            return []
        try:
            from config.runtime_paths import UPLOADS_DIR
        except ImportError:
            return []

        events: List[Dict[str, Any]] = []
        for attachment in attachments:
            try:
                if not isinstance(attachment, dict) or attachment.get("type") != "image":
                    continue
                data = attachment.get("data", "")
                mime_type = str(attachment.get("mime_type") or "")
                if not data:
                    continue
                # base64 可能带 data: URI 前缀（data:image/png;base64,...）
                if "," in data and data.startswith("data:"):
                    data = data.split(",", 1)[1]
                raw = base64.b64decode(data)
                if not raw:
                    continue
                ext = self._MEMORY_IMAGE_MIME_EXT.get(mime_type, ".png")
                filename = f"{uuid.uuid4().hex}{ext}"
                UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
                file_path = UPLOADS_DIR / filename
                await asyncio.to_thread(file_path.write_bytes, raw)
                metadata = {
                    "owner_id": str(user_id or ""),
                    "original_name": str(attachment.get("file_name") or filename),
                    "mime_type": mime_type,
                    "purpose": "memory",
                }
                meta_path = UPLOADS_DIR / f"{filename}.meta.json"
                await asyncio.to_thread(meta_path.write_text, json.dumps(metadata, ensure_ascii=False), "utf-8")
                events.append({
                    "kind": "image_attachment",
                    "url": f"/api/chat/uploads/{filename}",
                    "mime_type": mime_type,
                    "file_name": str(attachment.get("file_name") or ""),
                })
            except Exception as exc:
                logger.warning(f"图片附件落盘失败（记忆链路跳过该图）: {exc}")
        return events

    def set_consolidation_runner(self, runner):
        """
        注入 ConsolidationRunner 实例（Spec memory-quality-and-short-term-recovery Task 6）。

        由 agent.py 在初始化时注入；若不注入则 feedback 不会自动触发巩固，
        仍可正常执行短期记忆写入与画像提取。
        """
        self.consolidation_runner = runner
    
    async def evaluate_result(self, result: Dict[str, Any]) -> Dict[str, Any]:
        """评估工具执行结果,判断是否需要重试,提供建议或标记为失败."""
        status = result.get("status")
        
        if status == "error":
            return {
                "needs_retry": True,
                "error_type": "execution_error",
                "message": result.get("message", "Unknown error")
            }
        
        if result.get("requires_confirmation"):
            return {
                "needs_confirmation": True,
                "message": "This operation requires user confirmation",
                "details": result
            }
        
        return {
            "needs_retry": False,
            "needs_confirmation": False,
            "success": True
        }
    
    async def generate_response(self, results: List[Dict[str, Any]], context: Optional[Dict[str, Any]] = None) -> str:
        """根据工具执行结果列表生成面向用户的自然语言反馈文本, 支持通过 context._record_hook 注入行为记录回调."""
        started_at = time.perf_counter()
        if not results:
            response_text = "No results to report."
            if context and callable(context.get("_record_hook")):
                try:
                    context["_record_hook"](
                        node_type="feedback_generation",
                        user_message=context.get("message", ""),
                        context=context,
                        llm_output=response_text,
                        execution_duration_ms=int((time.perf_counter() - started_at) * 1000),
                        metadata={
                            "results_count": 0
                        }
                    )
                except Exception as e:
                    # 反馈生成是关键路径，记录日志而非静默吞异常
                    logger.warning("反馈行为记录回调失败（空结果路径）", exc_info=e)
            return response_text

        responses = []
        for item in results:
            result = item.get("result", item)
            status = result.get("status")

            if status == "completed":
                response_text = result.get("response")
                if response_text is not None:
                    responses.append(str(response_text))
                elif "results" in result:
                    for file_path, file_result in result["results"].items():
                        if file_result.get("status") == "success":
                            responses.append(f"Successfully read {file_path}")
                        else:
                            responses.append(f"Failed to read {file_path}: {file_result.get('message')}")
                elif "stdout" in result:
                    responses.append(f"Command output:\n{result['stdout']}")
            else:
                responses.append(f"Error: {result.get('message', 'Unknown error')}")

        if not responses:
            response_text = "No response generated."
        else:
            response_text = "\n\n".join(responses)

        if context and callable(context.get("_record_hook")):
            try:
                context["_record_hook"](
                    node_type="feedback_generation",
                    user_message=context.get("message", ""),
                    context=context,
                    llm_output=response_text,
                    execution_duration_ms=int((time.perf_counter() - started_at) * 1000),
                    metadata={
                        "results_count": len(results)
                    }
                )
            except Exception as e:
                # 反馈生成是关键路径，记录日志而非静默吞异常
                logger.warning("反馈行为记录回调失败", exc_info=e)

        return response_text
    
    async def update_memory(
        self,
        user_input: str,
        response: str,
        context: Dict[str, Any],
        reasoning_content: Optional[str] = None,
        tool_events: Optional[list] = None,
    ):
        """
        更新memory相关数据,配置或状态.
        reasoning_content 为本轮思维链文本,tool_events 为工具调用事件列表,用于历史恢复时展示.
        阅读时需要重点关注覆盖规则,副作用以及更新后的数据一致性.
        """
        if context.get("scheduled_execution_isolated") or context.get("disable_memory_update"):
            logger.info("Memory update disabled for current execution context")
            return

        if not self.memory_manager:
            # 提升为 warning：记忆写入静默失败会导致对话记录无法在
            # 历史列表/网页端恢复（曾发生 8 小时消息丢失且无任何日志）
            logger.warning("MemoryManager 未注入，跳过记忆更新（对话记录将无法持久化）")
            return

        user_id = context.get("user_id")
        continuation = context.get("continuation")
        is_subagent_continuation = isinstance(continuation, dict) and continuation.get("source") == "subagent"
        # 多模态记忆：把本轮图片附件落盘并记录到短期记忆（tool_events），
        # 供记忆巩固提炼时把图片引用带入长期记忆
        image_events = await self._persist_image_attachments(context, user_id)
        if image_events:
            # 兼容历史数据：tool_events 可能被双重 JSON 序列化为字符串，解析后合并
            if isinstance(tool_events, str):
                try:
                    parsed = json.loads(tool_events)
                    tool_events = parsed if isinstance(parsed, list) else []
                except (ValueError, TypeError):
                    tool_events = []
            tool_events = list(tool_events or []) + image_events

        try:
            if is_subagent_continuation:
                merge_with_last_assistant = bool(continuation.get("merge_with_last_assistant", True))
                continuation_tool_events = list(tool_events or [])
                aggregated_context = str(continuation.get("aggregated_context") or "").strip()
                if aggregated_context:
                    continuation_tool_events.append({
                        "id": "subagent-aggregation",
                        "kind": "subagent",
                        "name": "子代理汇总",
                        "status": "completed",
                        "detail": "子代理执行结果已汇总",
                        "subagent": {
                            "agentId": "subagent-aggregation",
                            "agentType": "汇总",
                            "runMode": "background",
                            "logs": aggregated_context,
                            "summary": aggregated_context[:2000],
                            "visible": True,
                        },
                    })
                if merge_with_last_assistant:
                    await self.memory_manager.append_to_last_assistant_memory(
                        session_id=context.get("session_id", "default"),
                        content=response,
                        user_id=user_id,
                        reasoning_content=reasoning_content or None,
                        tool_events=continuation_tool_events or None,
                    )
                else:
                    await self.memory_manager.add_short_term_memory(
                        session_id=context.get("session_id", "default"),
                        role="assistant",
                        content=response,
                        user_id=user_id,
                        reasoning_content=reasoning_content or None,
                        tool_events=continuation_tool_events or None,
                    )
                return

            await self.memory_manager.add_short_term_memory(
                session_id=context.get("session_id", "default"),
                role="user",
                content=user_input,
                user_id=user_id,
            )
            
            await self.memory_manager.add_short_term_memory(
                session_id=context.get("session_id", "default"),
                role="assistant",
                content=response,
                user_id=user_id,
                reasoning_content=reasoning_content or None,
                tool_events=tool_events or None,
            )

            # 同时检查用户输入与助手响应：用户主动声明偏好（如"请记住我喜欢 Python"）时
            # 助手回复可能不含关键词，必须以 user_input 为主触发持久化
            if self._should_persist(response) or self._should_persist(user_input):
                # Spec memory-experience-redesign：
                # 不再将对话原文直接写入长期记忆。命中关键词后由后台任务调用 LLM
                # 提炼（≤200 字事实 + 模型评估 importance + source_type），提炼失败
                # 或无价值内容时静默跳过、不落原文。对话响应零阻塞，原文仅保留在
                # 短期记忆层（供上下文注入与巩固提炼消费）。
                self._trigger_immediate_extract_async(
                    user_input, response, user_id, context
                )
                # 命中持久化决策后，异步触发画像提取（复用 _should_persist 信号）
                # maybe_extract 内部有锁去重，与 chat 路由的 N 轮兜底不会重复执行
                self._trigger_profile_extract_async(user_id)

            # Spec memory-quality-and-short-term-recovery Task 6：
            # 每轮对话完成后递增 consolidation_state.conversation_count_since_run，
            # 达到阈值（默认 10）时异步触发 consolidation_runner.run_if_due。
            # 后台执行不阻塞 chat 响应；异常静默记录日志，不影响主流程。
            self._trigger_consolidation_check_async(
                user_id=user_id,
                workspace_id=context.get("workspace_id", "default"),
            )

        except Exception as exc:
            logger.opt(exception=True).error("记忆持久化失败")
            raise MemoryPersistenceError("记忆持久化失败") from exc

    def _trigger_immediate_extract_async(
        self,
        user_input: str,
        response: str,
        user_id: Optional[str],
        context: Dict[str, Any],
    ) -> None:
        """
        关键词命中时后台触发即时提炼（Spec memory-experience-redesign）。

        通过 asyncio.create_task 调用 ConsolidationRunner.extract_turn_async，
        由 LLM 将本轮对话提炼为 ≤200 字事实后写入长期记忆；不阻塞 chat 响应。

        关键设计：
        1. 复用注入的 consolidation_runner（未注入时跳过，与自动巩固一致）
        2. 后台任务异常不捕获，在 asyncio 任务中自然浮现（事件循环会记录），
           且不阻塞对话响应
        3. 不持有请求级 session：extract_turn_async 内部分解 LLM 配置时使用
           session_factory 创建独立 session

        Args:
            user_input: 本轮用户输入
            response: 本轮助手响应
            user_id: 用户 ID（可能为空，隔离维度）
            context: 当前执行上下文（用于取 workspace_id）
        """
        runner = self.consolidation_runner
        if runner is None:
            logger.debug("consolidation_runner 未注入，跳过即时提炼")
            return
        workspace_id = context.get("workspace_id", "default")

        async def _extract_task() -> None:
            """后台即时提炼任务（异常自然浮现，由事件循环记录）。"""
            await runner.extract_turn_async(
                user_input, response, user_id, workspace_id
            )

        asyncio.create_task(_extract_task())

    def _trigger_consolidation_check_async(
        self,
        user_id: Optional[str],
        workspace_id: str = "default",
    ) -> None:
        """
        异步触发记忆巩固检查（Spec memory-quality-and-short-term-recovery Task 6）。

        在每轮对话完成 + 短期记忆写入后递增计数器，达到阈值时触发 run_if_due。
        借鉴 OpenBiliClaw CognitionCycle 的 turn-based 调度与 openhanako 的
        turn-based ticker 设计。

        关键设计：
        1. 使用 asyncio.create_task 启动，不 await，确保不阻塞 chat 响应
        2. increment_conversation_count 是同步 DB 操作（短耗时），仍放到后台避免阻塞
        3. 计数 >= 阈值时调用 run_if_due（异步 LLM 提炼在后台执行）
        4. 后台任务异常不捕获，在 asyncio 任务中自然浮现（事件循环会记录），
           且不阻塞对话响应

        Args:
            user_id: 用户 ID（隔离维度）
            workspace_id: 工作区隔离
        """
        if not user_id or not self.consolidation_runner:
            return
        runner = self.consolidation_runner
        threshold = runner._conversation_threshold

        async def _check_task() -> None:
            """后台巩固检查任务：递增计数 + 阈值触发 run_if_due（异常自然浮现）。"""
            count = runner.increment_conversation_count(
                user_id, workspace_id=workspace_id
            )
            if count >= threshold:
                await runner.run_if_due(
                    user_id, workspace_id=workspace_id
                )

        asyncio.create_task(_check_task())

    def _trigger_profile_extract_async(self, user_id: str) -> None:
        """
        异步触发画像提取（后台任务，不阻塞主流程）。

        复用 _should_persist 命中的信号，通过 asyncio.create_task 在后台
        调用 ProfileExtractionCoordinator.maybe_extract(force=False)。

        关键设计：
        1. 使用独立 db session（SessionLocal），不复用请求级 session
           （请求结束后 session 会被关闭，后台任务需独立生命周期）
        2. 通过 asyncio.create_task 启动，不 await，确保不阻塞 chat 响应
        3. 后台任务异常不捕获，在 asyncio 任务中自然浮现（事件循环会记录），
           且不阻塞对话响应

        Args:
            user_id: 用户 ID，从 context.user_id 获取
        """
        if not user_id:
            return
        from plugins.user_profile_builtin.coordinator import get_coordinator
        from db.models import SessionLocal

        async def _extract_task() -> None:
            """后台画像提取任务，使用独立 db session（异常自然浮现）。"""
            async_db = SessionLocal()
            try:
                coordinator = get_coordinator()
                # 偏好关键词触发时使用 force=True，绕过 N 轮阈值检查，
                # 实现"用户显式声明偏好 → 立即提取画像"的即时反馈。
                # maybe_extract 内部有 asyncio.Lock 去重，与 chat 路由的
                # N 轮兜底不会重复执行（锁占用时直接跳过）。
                await coordinator.maybe_extract(user_id, async_db, force=True)
            finally:
                async_db.close()

        # 创建后台 Task，不 await，确保不阻塞 chat 响应
        asyncio.create_task(_extract_task())
    
    def _should_persist(self, content: str) -> bool:
        """判断对话内容是否包含需持久化到长期记忆的关键词(如 remember/记住/preference 等)."""
        important_keywords = [
            "remember", "记住", "important", "重要",
            "preference", "偏好", "习惯", "always",
            # 用户显式偏好表达高频词（中英）
            "喜欢", "不喜欢", "讨厌", "常用", "favorite", "like", "dislike",
        ]

        content_lower = content.lower()
        return any(keyword in content_lower for keyword in important_keywords)

    async def record_explicit_feedback(
        self,
        session_id: str,
        message_id: str,
        user_id: str,
        rating: int,
        comment: Optional[str] = None,
    ) -> None:
        """
        记录用户对助手消息的显式反馈(点赞/点踩).

        Args:
            session_id: 会话 ID
            message_id: 消息 ID
            user_id: 用户 ID(字符串类型)
            rating: 评分(1=点赞,-1=点踩)
            comment: 可选备注
        """
        if rating not in (-1, 1):
            raise ValueError(f"无效的评分值: {rating},应为 1(点赞)或 -1(点踩)")

        import asyncio
        from db.models import UserFeedback, SessionLocal

        def _sync_record():
            db = SessionLocal()
            try:
                feedback_record = UserFeedback(
                    session_id=session_id,
                    message_id=message_id,
                    user_id=user_id,
                    rating=rating,
                    comment=comment,
                )
                db.add(feedback_record)
                db.commit()
                logger.info(f"User feedback recorded: session={session_id}, message={message_id}, rating={rating}")
            except Exception as exc:
                db.rollback()
                logger.error(f"Failed to record user feedback: {exc}")
                raise
            finally:
                db.close()

        await asyncio.to_thread(_sync_record)

    async def diagnose_error(
        self,
        error: Exception,
        context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        诊断执行错误的原因，生成结构化的诊断报告。

        返回:
            {
                "error_type": "tool_execution | llm_call | timeout | unknown",
                "error_message": "...",
                "likely_cause": "...",
                "suggested_fix": "..."
            }
        """
        error_type = "unknown"
        error_message = str(error)
        likely_cause = ""
        suggested_fix = ""

        # 根据异常类型分类
        error_class_name = type(error).__name__.lower()
        if "timeout" in error_class_name or isinstance(error, asyncio.TimeoutError):
            error_type = "timeout"
            likely_cause = "执行超时，可能是目标服务响应慢或任务过于复杂"
            suggested_fix = "增加超时时间或简化任务步骤"
        elif "tool" in error_class_name or "execution" in error_class_name:
            error_type = "tool_execution"
            likely_cause = "工具执行失败，可能是参数错误或目标环境问题"
            suggested_fix = "检查工具参数并重试，或使用替代工具"
        elif "llm" in error_class_name or "api" in error_class_name:
            error_type = "llm_call"
            likely_cause = "LLM 调用失败，可能是模型服务不可用或请求格式错误"
            suggested_fix = "切换到备用模型或调整请求参数"
        else:
            likely_cause = f"未知错误类型: {type(error).__name__}"
            suggested_fix = "检查错误详情并手动修复"

        logger.bind(
            event="error_diagnosed",
            module="feedback",
            error_type=error_type,
            error_message=error_message[:200],
        ).info(f"错误诊断完成: {error_type}")

        return {
            "error_type": error_type,
            "error_message": error_message,
            "likely_cause": likely_cause,
            "suggested_fix": suggested_fix,
        }


# 全局 FeedbackLayer 实例注册表,供 API 路由访问
feedback_layer_registry = FeedbackLayer()


# 保持向后兼容的模块级别名
# 新代码应使用 get_agent_lifecycle().get_feedback_layer()
def _get_feedback_layer():
    """从 AgentLifecycle 获取反馈层（支持测试隔离）"""
    from core.agent_lifecycle import get_agent_lifecycle
    return get_agent_lifecycle().get_feedback_layer()
