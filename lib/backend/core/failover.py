"""
LLM 故障转移管理器。

按优先级配置备用模型链，主模型不可用时自动切换到下一个候选。
触发故障转移的条件：熔断器开启、5xx 错误、超时、连接失败。
"""
import asyncio
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

from loguru import logger

from core.litellm_adapter import (
    CircuitBreaker,
    _get_circuit_breaker,
    RETRYABLE_STATUS_CODES,
)
from core.metrics import record_model_service_metric


# 故障转移触发错误码
FAILOVER_TRIGGER_STATUS_CODES = RETRYABLE_STATUS_CODES | {503}

# 故障转移事件类型
FAILOVER_EVENT_TRIGGERED = "failover_triggered"
FAILOVER_EVENT_EXHAUSTED = "failover_exhausted"
FAILOVER_EVENT_RECOVERED = "failover_recovered"


@dataclass
class ModelCandidate:
    """故障转移候选模型。"""
    provider: str
    model: str
    api_key: str = ""
    api_base: str = ""
    priority: int = 0  # 越小优先级越高
    weight: int = 100  # 权重（用于同优先级负载均衡，暂未启用）
    tags: List[str] = field(default_factory=list)


@dataclass
class FailoverEvent:
    """故障转移事件记录。"""
    timestamp: datetime
    primary_provider: str
    primary_model: str
    fallback_provider: str
    fallback_model: str
    reason: str
    request_id: Optional[str] = None


@dataclass
class LatencyRecord:
    """单次请求延迟记录。"""
    provider: str
    model: str
    purpose: str
    duration_ms: float
    ttft_ms: Optional[float] = None  # 首 token 时间
    success: bool = True
    error_code: Optional[str] = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class FailoverManager:
    """
    故障转移管理器。

    维护模型候选链、记录故障转移事件、收集延迟指标。
    """

    def __init__(self, max_history: int = 1000):
        self._chains: Dict[str, List[ModelCandidate]] = {}
        self._events: List[FailoverEvent] = []
        self._latency_records: List[LatencyRecord] = []
        self._max_history = max_history
        self._lock = asyncio.Lock()

    def register_chain(
        self,
        chain_key: str,
        candidates: List[ModelCandidate],
    ) -> None:
        """
        注册模型故障转移链。

        Args:
            chain_key: 链标识（通常为 "primary_provider:primary_model"）
            candidates: 候选模型列表（将按 priority 排序）
        """
        sorted_candidates = sorted(candidates, key=lambda c: (c.priority, c.weight))
        self._chains[chain_key] = sorted_candidates
        logger.info(
            f"注册故障转移链: key={chain_key}, candidates={len(sorted_candidates)}"
        )

    def get_chain(self, chain_key: str) -> List[ModelCandidate]:
        """获取故障转移链。"""
        return self._chains.get(chain_key, [])

    def list_chains(self) -> Dict[str, List[ModelCandidate]]:
        """列出所有故障转移链。"""
        return dict(self._chains)

    async def record_event(self, event: FailoverEvent) -> None:
        """记录故障转移事件。"""
        async with self._lock:
            self._events.append(event)
            if len(self._events) > self._max_history:
                self._events = self._events[-self._max_history:]

    async def record_latency(self, record: LatencyRecord) -> None:
        """记录延迟指标。"""
        async with self._lock:
            self._latency_records.append(record)
            if len(self._latency_records) > self._max_history:
                self._latency_records = self._latency_records[-self._max_history:]
            # 同步到 Prometheus 指标
            status = "success" if record.success else "error"
            record_model_service_metric(
                provider=record.provider,
                purpose=record.purpose,
                status=status,
                duration_ms=record.duration_ms,
            )

    def get_events(
        self,
        limit: int = 50,
        chain_key: Optional[str] = None,
    ) -> List[FailoverEvent]:
        """获取故障转移事件列表。"""
        events = list(reversed(self._events))
        if chain_key:
            # 简单过滤：事件中包含指定 provider/model
            events = [
                e for e in events
                if chain_key in f"{e.primary_provider}:{e.primary_model}"
                or chain_key in f"{e.fallback_provider}:{e.fallback_model}"
            ]
        return events[:limit]

    def get_latency_stats(
        self,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        limit: int = 100,
    ) -> Dict[str, Any]:
        """
        获取延迟统计。

        Returns:
            包含 count、avg_ms、p50_ms、p95_ms、p99_ms、ttft_avg_ms 的字典
        """
        records = list(self._latency_records)
        if provider:
            records = [r for r in records if r.provider == provider]
        if model:
            records = [r for r in records if r.model == model]
        records = records[-limit:]

        if not records:
            return {
                "count": 0,
                "avg_ms": 0.0,
                "p50_ms": 0.0,
                "p95_ms": 0.0,
                "p99_ms": 0.0,
                "ttft_avg_ms": 0.0,
                "success_rate": 0.0,
            }

        durations = sorted([r.duration_ms for r in records])
        ttfts = [r.ttft_ms for r in records if r.ttft_ms is not None]
        success_count = sum(1 for r in records if r.success)

        return {
            "count": len(records),
            "avg_ms": round(sum(durations) / len(durations), 2),
            "p50_ms": round(self._percentile(durations, 50), 2),
            "p95_ms": round(self._percentile(durations, 95), 2),
            "p99_ms": round(self._percentile(durations, 99), 2),
            "ttft_avg_ms": round(sum(ttfts) / len(ttfts), 2) if ttfts else 0.0,
            "success_rate": round(success_count / len(records), 4),
        }

    @staticmethod
    def _percentile(sorted_values: List[float], p: float) -> float:
        """计算分位数。"""
        if not sorted_values:
            return 0.0
        idx = int(len(sorted_values) * p / 100)
        idx = min(idx, len(sorted_values) - 1)
        return sorted_values[idx]

    def get_circuit_breaker_status(self) -> Dict[str, Dict[str, Any]]:
        """获取所有熔断器状态。"""
        # 从 litellm_adapter 的全局熔断器字典获取
        from core.litellm_adapter import _circuit_breakers
        import time as _time
        status: Dict[str, Dict[str, Any]] = {}
        for provider, breaker in _circuit_breakers.items():
            # 将 monotonic 时间戳转为可读的"距今秒数"
            last_failure_ago = None
            if breaker._last_failure_time > 0:
                last_failure_ago = round(_time.monotonic() - breaker._last_failure_time, 2)
            status[provider] = {
                "state": breaker.state,
                "failure_count": breaker._failure_count,
                "last_failure_ago_seconds": last_failure_ago,
                "recovery_timeout_seconds": breaker._recovery_timeout,
                "failure_threshold": breaker._failure_threshold,
            }
        return status

    def list_latency_providers(self) -> set:
        """返回所有有延迟记录的提供商集合。"""
        return {r.provider for r in self._latency_records}


# 全局单例
_failover_manager: Optional[FailoverManager] = None


def get_failover_manager() -> FailoverManager:
    """获取故障转移管理器单例。"""
    global _failover_manager
    if _failover_manager is None:
        _failover_manager = FailoverManager()
    return _failover_manager


def should_failover(error: Dict[str, Any]) -> bool:
    """
    判断错误是否应触发故障转移。

    Args:
        error: litellm_adapter 返回的 error 字典

    Returns:
        True 表示应切换到备用模型
    """
    if not error:
        return False

    error_code = error.get("error_code", "")
    status_code = error.get("status_code", 0)

    # 熔断器开启
    if error_code == "model_service_circuit_breaker_open":
        return True

    # 可重试的 HTTP 状态码
    if status_code in FAILOVER_TRIGGER_STATUS_CODES:
        return True

    # 超时
    if error_code in ("model_service_timeout", "model_service_request_error"):
        return True

    return False


async def execute_with_failover(
    candidates: List[ModelCandidate],
    call_fn: Callable[[ModelCandidate], Dict[str, Any]],
    chain_key: str,
    request_id: Optional[str] = None,
) -> Tuple[Dict[str, Any], Optional[ModelCandidate]]:
    """
    按候选链执行调用，遇到可故障转移错误时切换到下一个候选。

    Args:
        candidates: 候选模型列表（已按优先级排序）
        call_fn: 调用函数，接收 ModelCandidate 返回结果字典
        chain_key: 链标识（用于事件记录）
        request_id: 请求 ID

    Returns:
        (最终结果, 使用的候选模型)
    """
    if not candidates:
        return {"ok": False, "error": {"error_code": "no_candidates", "message": "无可用候选模型"}}, None

    manager = get_failover_manager()
    last_error: Optional[Dict[str, Any]] = None
    started_at = time.time()

    for idx, candidate in enumerate(candidates):
        is_primary = idx == 0
        logger.info(
            f"故障转移链调用: chain={chain_key}, idx={idx}, "
            f"provider={candidate.provider}, model={candidate.model}"
        )

        result = await call_fn(candidate)

        if result.get("ok"):
            # 成功
            duration_ms = (time.time() - started_at) * 1000
            await manager.record_latency(LatencyRecord(
                provider=candidate.provider,
                model=candidate.model,
                purpose=chain_key,
                duration_ms=duration_ms,
                success=True,
            ))

            # 若从非主模型恢复，记录恢复事件
            if not is_primary and last_error:
                logger.info(
                    f"故障转移恢复: chain={chain_key}, "
                    f"fallback={candidate.provider}:{candidate.model}"
                )

            return result, candidate

        # 失败
        error = result.get("error", {})
        last_error = error
        await manager.record_latency(LatencyRecord(
            provider=candidate.provider,
            model=candidate.model,
            purpose=chain_key,
            duration_ms=(time.time() - started_at) * 1000,
            success=False,
            error_code=error.get("error_code"),
        ))

        if not should_failover(error):
            # 不可故障转移的错误，直接返回
            logger.info(
                f"不可故障转移的错误，返回: chain={chain_key}, "
                f"error_code={error.get('error_code')}"
            )
            return result, candidate

        # 记录故障转移事件
        if is_primary and len(candidates) > 1:
            next_candidate = candidates[idx + 1]
            await manager.record_event(FailoverEvent(
                timestamp=datetime.now(timezone.utc),
                primary_provider=candidate.provider,
                primary_model=candidate.model,
                fallback_provider=next_candidate.provider,
                fallback_model=next_candidate.model,
                reason=error.get("error_code", "unknown"),
                request_id=request_id,
            ))
            logger.warning(
                f"触发故障转移: chain={chain_key}, "
                f"from={candidate.provider}:{candidate.model}, "
                f"to={next_candidate.provider}:{next_candidate.model}, "
                f"reason={error.get('error_code')}"
            )

    # 所有候选都失败
    logger.error(f"故障转移链耗尽: chain={chain_key}, candidates={len(candidates)}")
    return {"ok": False, "error": last_error or {"error_code": "all_candidates_failed"}}, None
