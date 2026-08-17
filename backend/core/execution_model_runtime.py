"""ExecutionModelRuntimeMixin 的单一职责实现。"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any, Dict, List, Optional

from loguru import logger

from billing.token_counter import count_from_stream, count_from_usage
from config.settings import settings
from config.thresholds import (
    OUTPUT_TOKEN_RECOVERY_MAX_RETRIES,
    OUTPUT_TOKEN_RECOVERY_THRESHOLD,
    STREAM_CHUNK_TIMEOUT_SECONDS,
)
from core.circuit_breaker import CircuitOpenError, get_circuit_breaker
from core.execution_support import MAX_TOOL_EVENT_RESULT_CHARS, resolve_max_tool_call_rounds
from core.litellm_adapter import build_standard_error
from core.metrics import record_model_service_metric


class ExecutionModelRuntimeMixin:
    """由 ExecutionLayer 组合的内部协作者。"""

    async def _call_llm_api(self, prompt: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        通过 LiteLLM 统一调用层发起非流式聊天请求。
        支持通过 context["conversation_history"] 注入对话历史。
        """
        record_hook = context.get("_record_hook")
        started_at = time.perf_counter()
        serialized_context = {
            key: value
            for key, value in context.items()
            if key not in {"_record_hook", "db"}
        }
        llm_input_payload = {
            "prompt": prompt,
            "context": serialized_context,
        }

        resolved = await asyncio.to_thread(self._resolve_llm_configuration, context)
        if not resolved.get("ok"):
            duration_ms = int((time.perf_counter() - started_at) * 1000)
            if callable(record_hook):
                record_hook(
                    node_type="llm_call",
                    user_message=context.get("message", prompt),
                    context=context,
                    status="error",
                    error_message=resolved.get("error", {}).get("message"),
                    llm_input=llm_input_payload,
                    llm_output=resolved,
                    execution_duration_ms=duration_ms,
                    metadata={
                        "phase": "resolve_configuration",
                        "error": resolved.get("error"),
                    }
                )
            return resolved

        # 将解析后的 provider 注入 context，供 prompt builder 判断是否需要 Prompt Cache
        context["provider"] = resolved["provider"]
        messages = self._build_messages_with_history(prompt, context)
        llm_input_payload.update({
            "provider": resolved["provider"],
            "model": resolved["model"],
        })

        _tools = context.get("_tools")
        _thinking_params = context.get("_thinking_params")
        step_timeout = context.get("step_timeout", settings.AGENT_STEP_TIMEOUT_SECONDS)

        # 熔断器：LLM 服务持续故障时短路请求，避免请求方阻塞在超时上拖垮整站
        breaker = await get_circuit_breaker(
            "llm_call",
            failure_threshold=settings.LLM_CB_FAILURE_THRESHOLD,
            recovery_timeout=settings.LLM_CB_RECOVERY_TIMEOUT,
            half_open_max_calls=settings.LLM_CB_HALF_OPEN_MAX_CALLS,
        )
        try:
            await breaker.acquire()
        except CircuitOpenError as exc:
            duration_ms = int((time.perf_counter() - started_at) * 1000)
            record_model_service_metric(resolved["provider"], "chat", "circuit_open", duration_ms)
            logger.bind(
                event="llm_circuit_open",
                module="executor",
                provider=resolved["provider"],
                model=resolved["model"],
                retry_after_seconds=exc.retry_after_seconds,
            ).warning(f"LLM 熔断器 open，跳过调用: {exc}")
            return {
                "ok": False,
                "error": {
                    "message": str(exc),
                    "type": "circuit_open",
                    "retryable": True,
                    "retry_after_seconds": exc.retry_after_seconds,
                },
            }

        try:
            result = await asyncio.wait_for(
                self._get_llm_completion_callable()(
                    provider=resolved["provider"],
                    model=resolved["model"],
                    messages=messages,
                    api_key=resolved["api_key"],
                    api_base=resolved.get("api_endpoint"),
                    max_tokens=self._resolve_max_tokens(resolved),
                    request_id=resolved.get("request_id"),
                    tools=_tools,
                    thinking_params=_thinking_params,
                ),
                timeout=step_timeout,
            )
        except asyncio.TimeoutError as exc:
            # 超时计入熔断器失败统计
            await breaker.record_failure(exc)
            duration_ms = int((time.perf_counter() - started_at) * 1000)
            record_model_service_metric(resolved["provider"], "chat", "error", duration_ms)
            logger.bind(
                event="llm_call_timeout",
                module="executor",
                provider=resolved["provider"],
                model=resolved["model"],
                timeout_seconds=step_timeout,
            ).warning(f"LLM 调用超时 ({step_timeout}s)")
            return {
                "ok": False,
                "error": {"message": f"LLM 调用超时 ({step_timeout}s)", "type": "timeout"},
            }
        except Exception as exc:
            # 其他异常（网络、5xx 等）也计入熔断器失败统计
            await breaker.record_failure(exc)
            raise
        else:
            await breaker.record_success()

        # 支持 tool_calls 循环：检测到工具调用时自动执行并将结果回传 LLM
        max_rounds = resolve_max_tool_call_rounds(context)
        round_count = 0
        consecutive_errors = 0
        max_consecutive_errors = 3
        tool_events = []

        while round_count < max_rounds:
            tool_calls = result.get("tool_calls")
            if not tool_calls:
                break

            round_count += 1
            assistant_msg = self.build_assistant_tool_call_message(
                content=result.get("response"),
                reasoning_content=result.get("reasoning_content"),
                tool_calls=tool_calls,
            )
            messages.append(assistant_msg)

            _abort = False
            # 使用 StreamingToolExecutor 并发调度工具调用
            # 只读并发安全工具可同时执行，破坏性工具串行执行
            ordered_results = await self._execute_tool_calls_concurrent(
                tool_calls, context
            )
            for tc, exec_result in ordered_results:
                if exec_result.get("ok"):
                    consecutive_errors = 0
                else:
                    consecutive_errors += 1
                    if consecutive_errors >= max_consecutive_errors:
                        logger.bind(
                            event="tool_calls_max_consecutive_errors",
                            module="executor",
                            consecutive_errors=consecutive_errors,
                            threshold=max_consecutive_errors,
                        ).warning(f"工具调用连续失败 {consecutive_errors} 次，终止 tool_calls 循环")
                        _abort = True
                        break
                # 前端展示用结果摘要，截断防止 tool_events 过大
                _raw_result = exec_result.get("result", exec_result.get("error"))
                _result_str = json.dumps(_raw_result, ensure_ascii=False, default=str)
                if len(_result_str) > MAX_TOOL_EVENT_RESULT_CHARS:
                    _result_str = _result_str[:MAX_TOOL_EVENT_RESULT_CHARS] + "..."
                tool_events.append({
                    "name": tc.get("function", {}).get("name", "unknown"),
                    "status": "completed" if exec_result.get("ok") else "error",
                    "result": _result_str,
                })
                tool_message = self._build_tool_message(tc, exec_result)
                messages.append(tool_message)
            if _abort:
                break

            try:
                result = await asyncio.wait_for(
                    self._get_llm_completion_callable()(
                        provider=resolved["provider"],
                        model=resolved["model"],
                        messages=messages,
                        api_key=resolved["api_key"],
                        api_base=resolved.get("api_endpoint"),
                        max_tokens=self._resolve_max_tokens(resolved),
                        request_id=resolved.get("request_id"),
                        tools=_tools,
                        thinking_params=_thinking_params,
                    ),
                    timeout=step_timeout,
                )
            except asyncio.TimeoutError:
                logger.bind(
                    event="llm_call_timeout",
                    module="executor",
                    provider=resolved["provider"],
                    model=resolved["model"],
                    timeout_seconds=step_timeout,
                    round=round_count,
                ).warning(f"工具调用循环中 LLM 调用超时 ({step_timeout}s)，第 {round_count} 轮")
                result = {
                    "ok": False,
                    "error": {"message": f"LLM 调用超时 ({step_timeout}s)", "type": "timeout"},
                }

            if not result.get("ok"):
                break

        # 将 tool_events 注入到返回结果中
        if tool_events:
            result["tool_events"] = tool_events

        duration_ms = int((time.perf_counter() - started_at) * 1000)

        if not result.get("ok"):
            record_model_service_metric(resolved["provider"], "chat", "error", duration_ms)
            if callable(record_hook):
                record_hook(
                    node_type="llm_call",
                    user_message=context.get("message", prompt),
                    context=context,
                    status="error",
                    error_message=result.get("error", {}).get("message"),
                    llm_input=llm_input_payload,
                    llm_output=result,
                    execution_duration_ms=duration_ms,
                    metadata={
                        "provider": resolved["provider"],
                        "model": resolved["model"],
                    }
                )
            return result

        record_model_service_metric(resolved["provider"], "chat", "success", duration_ms)

        if callable(record_hook):
            usage = result.get("usage")
            token_breakdown = count_from_usage(usage if isinstance(usage, dict) else None)
            record_hook(
                node_type="llm_call",
                user_message=context.get("message", prompt),
                context=context,
                status="success",
                llm_input=llm_input_payload,
                llm_output=result,
                token_breakdown=token_breakdown,
                llm_tokens_used=token_breakdown.total_tokens,
                execution_duration_ms=duration_ms,
                metadata={
                    "provider": resolved["provider"],
                    "model": resolved["model"],
                }
            )
        return result

    async def _call_llm_api_stream(self, prompt: str, context: Dict[str, Any]):
        """
        通过 LiteLLM 统一调用层发起流式聊天请求。
        支持通过 context["conversation_history"] 注入对话历史。
        向外 yield { "content": "...", "reasoning_content": "..." } 结构。
        """
        record_hook = context.get("_record_hook")
        started_at = time.perf_counter()
        serialized_context = {
            key: value
            for key, value in context.items()
            if key not in {"_record_hook", "db"}
        }

        resolved = await asyncio.to_thread(self._resolve_llm_configuration, context)
        if not resolved.get("ok"):
            yield {"error": resolved.get("error")}
            return

        # 将解析后的 provider 注入 context，供 prompt builder 判断是否需要 Prompt Cache
        context["provider"] = resolved["provider"]
        messages = self._build_messages_with_history(prompt, context)
        tool_messages = context.get("_tool_messages", [])
        if tool_messages:
            messages.extend(tool_messages)
        _tools = context.get("_tools")
        full_content = ""
        full_reasoning = ""
        # 收集流式 chunk 用于后续 token 计数（count_from_stream 会查找 usage 字段）
        stream_chunks: List[Dict[str, Any]] = []

        # 熔断器：LLM 服务持续故障时短路请求，避免流式连接积压拖垮整站
        breaker = await get_circuit_breaker(
            "llm_call",
            failure_threshold=settings.LLM_CB_FAILURE_THRESHOLD,
            recovery_timeout=settings.LLM_CB_RECOVERY_TIMEOUT,
            half_open_max_calls=settings.LLM_CB_HALF_OPEN_MAX_CALLS,
        )
        try:
            await breaker.acquire()
        except CircuitOpenError as exc:
            duration_ms = int((time.perf_counter() - started_at) * 1000)
            record_model_service_metric(resolved["provider"], "chat_stream", "circuit_open", duration_ms)
            logger.bind(
                event="llm_stream_circuit_open",
                module="executor",
                provider=resolved["provider"],
                model=resolved["model"],
                retry_after_seconds=exc.retry_after_seconds,
            ).warning(f"LLM 流式熔断器 open，跳过调用: {exc}")
            yield {
                "error": {
                    "message": str(exc),
                    "type": "circuit_open",
                    "retryable": True,
                    "retry_after_seconds": exc.retry_after_seconds,
                }
            }
            return

        # 跟踪本次调用是否已记录成功/失败，避免 yield 错误 chunk 后重复计数
        cb_outcome_recorded = False
        # max_output_tokens 恢复链：输出被 length 截断时升级并重试，上限 3 次
        MAX_OUTPUT_RETRY_LIMIT = 3
        MAX_OUTPUT_RETRY_TOKENS = 64_000
        max_output_retries_left = MAX_OUTPUT_RETRY_LIMIT
        max_output_tokens = self._resolve_max_tokens(resolved)
        # 透传的真实 finish_reason 与 usage（来自流尾 chunk）
        finish_reason: Optional[str] = None
        last_usage: Optional[Dict[str, Any]] = None

        try:
            while True:
                _thinking_params = context.get("_thinking_params")
                stream_gen = self._get_llm_stream_callable()(
                    provider=resolved["provider"],
                    model=resolved["model"],
                    messages=messages,
                    api_key=resolved["api_key"],
                    api_base=resolved.get("api_endpoint"),
                    max_tokens=max_output_tokens,
                    request_id=resolved.get("request_id"),
                    tools=_tools,
                    thinking_params=_thinking_params,
                )
                try:
                    # 流式整体超时控制：每个 chunk 之间最长等待时间
                    # 防止 LLM 服务 hang 住但不断开连接导致永久阻塞
                    # 值由 config.thresholds.STREAM_CHUNK_TIMEOUT_SECONDS 提供
                    stream_iter = stream_gen.__aiter__()
                    while True:
                        try:
                            chunk = await asyncio.wait_for(
                                stream_iter.__anext__(),
                                timeout=STREAM_CHUNK_TIMEOUT_SECONDS,
                            )
                        except asyncio.TimeoutError as timeout_exc:
                            # 流式超时计入熔断器失败统计
                            await breaker.record_failure(timeout_exc)
                            cb_outcome_recorded = True
                            duration_ms = int((time.perf_counter() - started_at) * 1000)
                            record_model_service_metric(resolved["provider"], "chat_stream", "timeout", duration_ms)
                            logger.bind(
                                event="llm_stream_timeout",
                                module="executor",
                                provider=resolved["provider"],
                                model=resolved["model"],
                                timeout_seconds=STREAM_CHUNK_TIMEOUT_SECONDS,
                            ).error(f"流式 LLM 调用超时（{STREAM_CHUNK_TIMEOUT_SECONDS}s 无响应）")
                            yield {
                                "error": {
                                    "message": f"流式响应超时（{STREAM_CHUNK_TIMEOUT_SECONDS}s 无数据）",
                                    "type": "timeout",
                                }
                            }
                            return
                        except StopAsyncIteration:
                            break

                        # 收集 chunk 用于后续 token 计数（count_from_stream 查找 usage 字段）
                        if isinstance(chunk, dict):
                            stream_chunks.append(chunk)

                        # 错误事件直接转发
                        if "error" in chunk:
                            # 流式错误事件计入熔断器失败统计
                            err_exc = Exception(chunk["error"].get("message", "stream error"))
                            await breaker.record_failure(err_exc)
                            cb_outcome_recorded = True
                            duration_ms = int((time.perf_counter() - started_at) * 1000)
                            record_model_service_metric(resolved["provider"], "chat_stream", "error", duration_ms)
                            if callable(record_hook):
                                record_hook(
                                    node_type="llm_call",
                                    user_message=context.get("message", prompt),
                                    context=context,
                                    status="error",
                                    error_message=chunk["error"].get("message"),
                                    llm_input={"prompt": prompt, "context": serialized_context},
                                    llm_output=chunk,
                                    execution_duration_ms=duration_ms,
                                    metadata={
                                        "provider": resolved["provider"],
                                        "model": resolved["model"],
                                        "mode": "stream",
                                    }
                                )
                            yield chunk
                            return

                        if chunk.get("type") == "tool_calls":
                            # tool_calls 事件视为成功完成（LLM 已返回完整结构化响应）
                            await breaker.record_success()
                            cb_outcome_recorded = True
                            yield chunk
                            return

                        # 透传真实 finish_reason 与 usage（流尾 chunk 携带）
                        if chunk.get("finish_reason"):
                            finish_reason = chunk["finish_reason"]
                        if isinstance(chunk.get("usage"), dict):
                            last_usage = chunk["usage"]

                        content = chunk.get("content", "")
                        reasoning = chunk.get("reasoning_content", "")
                        if content:
                            full_content += content
                        if reasoning:
                            full_reasoning += reasoning
                        if content or reasoning or finish_reason:
                            payload: Dict[str, Any] = {
                                "content": content,
                                "reasoning_content": reasoning,
                            }
                            if finish_reason:
                                payload["finish_reason"] = finish_reason
                            yield payload
                finally:
                    # 显式关闭内层流式生成器，避免流中断后资源泄漏
                    close_gen = getattr(stream_gen, "aclose", None)
                    if close_gen is not None:
                        try:
                            await close_gen()
                        except Exception:
                            logger.bind(
                                event="llm_stream_generator_close_error",
                                module="executor",
                            ).debug("关闭流式生成器失败（已忽略）")

                # max_output_tokens 恢复链：默认 8k 输出被 length 截断时
                # 升级到 64k 并注入 meta 恢复消息重试，上限 3 次
                if finish_reason == "length" and max_output_retries_left > 0:
                    max_output_retries_left -= 1
                    max_output_tokens = MAX_OUTPUT_RETRY_TOKENS
                    messages.append({
                        "role": "user",
                        "content": "Output token limit hit. Resume directly from the previous response without repeating content.",
                    })
                    logger.bind(
                        event="llm_stream_output_limit_retry",
                        module="executor",
                        provider=resolved["provider"],
                        model=resolved["model"],
                        retries_left=max_output_retries_left,
                    ).warning(f"输出 token 上限截断（finish_reason=length），升级 max_tokens 到 {MAX_OUTPUT_RETRY_TOKENS} 重试")
                    finish_reason = None
                    last_usage = None
                    continue
                break

            duration_ms = int((time.perf_counter() - started_at) * 1000)
            record_model_service_metric(resolved["provider"], "chat_stream", "success", duration_ms)

            # 流式正常结束计入熔断器成功统计（tool_calls 路径已自行记账）
            if not cb_outcome_recorded:
                await breaker.record_success()
                cb_outcome_recorded = True

            if callable(record_hook):
                token_breakdown = count_from_stream(stream_chunks)
                record_hook(
                    node_type="llm_call",
                    user_message=context.get("message", prompt),
                    context=context,
                    status="success",
                    llm_input={"prompt": prompt, "context": serialized_context},
                    llm_output={
                        "ok": True,
                        "response": full_content,
                        "reasoning_content": full_reasoning,
                        "provider": resolved["provider"],
                        "model": resolved["model"],
                    },
                    token_breakdown=token_breakdown,
                    llm_tokens_used=token_breakdown.total_tokens,
                    execution_duration_ms=duration_ms,
                    metadata={
                        "provider": resolved["provider"],
                        "model": resolved["model"],
                        "mode": "stream",
                    }
                )

        except Exception as e:
            # 流式异常计入熔断器失败统计（超时路径已自行记账）
            if not cb_outcome_recorded:
                await breaker.record_failure(e)
                cb_outcome_recorded = True
            logger.bind(
                event="llm_stream_error",
                module="executor",
                error_type=type(e).__name__,
                provider=resolved.get("provider"),
                model=resolved.get("model"),
            ).opt(exception=True).error(f"LLM 流式调用异常: {e}")
            duration_ms = int((time.perf_counter() - started_at) * 1000)
            record_model_service_metric(resolved["provider"], "chat_stream", "error", duration_ms)

            output_error = {
                "error": build_standard_error(
                    "model_service_stream_error",
                    "模型流式服务调用出现异常",
                    request_id=resolved.get("request_id"),
                    details={
                        "provider": resolved["provider"],
                        "model": resolved["model"],
                        "reason": str(e),
                    },
                )
            }

            if callable(record_hook):
                record_hook(
                    node_type="llm_call",
                    user_message=context.get("message", prompt),
                    context=context,
                    status="error",
                    error_message=output_error["error"]["message"],
                    llm_input={"prompt": prompt, "context": serialized_context},
                    llm_output=output_error,
                    execution_duration_ms=duration_ms,
                    metadata={
                        "provider": resolved["provider"],
                        "model": resolved["model"],
                        "mode": "stream",
                    }
                )

            yield output_error
