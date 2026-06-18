"""
P2 LLM 故障转移与延迟监控测试。
"""
import asyncio
import time
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from core.failover import (
    ModelCandidate,
    FailoverEvent,
    LatencyRecord,
    FailoverManager,
    get_failover_manager,
    should_failover,
    execute_with_failover,
)


# ── should_failover 测试 ──────────────────────────────────────────


class TestShouldFailover:
    """故障转移触发判断测试。"""

    def test_no_error_returns_false(self):
        assert should_failover({}) is False
        assert should_failover(None) is False

    def test_circuit_breaker_open_triggers_failover(self):
        error = {"error_code": "model_service_circuit_breaker_open", "status_code": 503}
        assert should_failover(error) is True

    def test_5xx_errors_trigger_failover(self):
        for status in [500, 502, 503, 504]:
            error = {"error_code": "server_error", "status_code": status}
            assert should_failover(error) is True, f"状态码 {status} 应触发故障转移"

    def test_429_rate_limit_triggers_failover(self):
        error = {"error_code": "rate_limited", "status_code": 429}
        assert should_failover(error) is True

    def test_timeout_triggers_failover(self):
        error = {"error_code": "model_service_timeout", "status_code": 0}
        assert should_failover(error) is True

    def test_request_error_triggers_failover(self):
        error = {"error_code": "model_service_request_error", "status_code": 0}
        assert should_failover(error) is True

    def test_400_bad_request_does_not_trigger_failover(self):
        error = {"error_code": "bad_request", "status_code": 400}
        assert should_failover(error) is False

    def test_401_unauthorized_does_not_trigger_failover(self):
        error = {"error_code": "unauthorized", "status_code": 401}
        assert should_failover(error) is False

    def test_404_not_found_does_not_trigger_failover(self):
        error = {"error_code": "not_found", "status_code": 404}
        assert should_failover(error) is False


# ── ModelCandidate 测试 ──────────────────────────────────────────


class TestModelCandidate:
    """候选模型数据结构测试。"""

    def test_candidate_creation(self):
        c = ModelCandidate(
            provider="openai",
            model="gpt-4",
            api_key="sk-xxx",
            priority=0,
        )
        assert c.provider == "openai"
        assert c.model == "gpt-4"
        assert c.priority == 0
        assert c.weight == 100
        assert c.tags == []

    def test_candidate_with_tags(self):
        c = ModelCandidate(
            provider="anthropic",
            model="claude-3",
            priority=1,
            weight=50,
            tags=["fallback", "cheap"],
        )
        assert c.tags == ["fallback", "cheap"]
        assert c.weight == 50


# ── FailoverManager 测试 ──────────────────────────────────────────


class TestFailoverManager:
    """故障转移管理器测试。"""

    def test_register_and_get_chain(self):
        manager = FailoverManager()
        candidates = [
            ModelCandidate(provider="openai", model="gpt-4", priority=0),
            ModelCandidate(provider="anthropic", model="claude-3", priority=1),
        ]
        manager.register_chain("openai:gpt-4", candidates)
        chain = manager.get_chain("openai:gpt-4")
        assert len(chain) == 2
        assert chain[0].provider == "openai"  # priority=0 排在前
        assert chain[1].provider == "anthropic"

    def test_get_nonexistent_chain_returns_empty(self):
        manager = FailoverManager()
        assert manager.get_chain("nonexistent") == []

    def test_list_chains(self):
        manager = FailoverManager()
        manager.register_chain("chain1", [ModelCandidate(provider="p1", model="m1")])
        manager.register_chain("chain2", [ModelCandidate(provider="p2", model="m2")])
        chains = manager.list_chains()
        assert len(chains) == 2
        assert "chain1" in chains
        assert "chain2" in chains

    @pytest.mark.asyncio
    async def test_record_and_get_events(self):
        manager = FailoverManager(max_history=10)
        event = FailoverEvent(
            timestamp=datetime.now(timezone.utc),
            primary_provider="openai",
            primary_model="gpt-4",
            fallback_provider="anthropic",
            fallback_model="claude-3",
            reason="model_service_timeout",
        )
        await manager.record_event(event)
        events = manager.get_events(limit=10)
        assert len(events) == 1
        assert events[0].primary_provider == "openai"
        assert events[0].fallback_provider == "anthropic"

    @pytest.mark.asyncio
    async def test_event_history_limit(self):
        manager = FailoverManager(max_history=5)
        for i in range(10):
            event = FailoverEvent(
                timestamp=datetime.now(timezone.utc),
                primary_provider=f"p{i}",
                primary_model=f"m{i}",
                fallback_provider="fallback",
                fallback_model="fb",
                reason="test",
            )
            await manager.record_event(event)
        events = manager.get_events(limit=100)
        assert len(events) == 5  # 限制为 max_history

    @pytest.mark.asyncio
    async def test_record_latency(self):
        manager = FailoverManager()
        record = LatencyRecord(
            provider="openai",
            model="gpt-4",
            purpose="chat",
            duration_ms=150.5,
            success=True,
        )
        await manager.record_latency(record)
        stats = manager.get_latency_stats()
        assert stats["count"] == 1
        assert stats["avg_ms"] == 150.5

    @pytest.mark.asyncio
    async def test_latency_stats_with_multiple_records(self):
        manager = FailoverManager()
        durations = [100, 200, 300, 400, 500]
        for d in durations:
            await manager.record_latency(LatencyRecord(
                provider="openai",
                model="gpt-4",
                purpose="chat",
                duration_ms=float(d),
                success=True,
            ))
        stats = manager.get_latency_stats()
        assert stats["count"] == 5
        assert stats["avg_ms"] == 300.0
        assert stats["p50_ms"] >= 100.0
        assert stats["p95_ms"] >= 400.0

    @pytest.mark.asyncio
    async def test_latency_stats_filter_by_provider(self):
        manager = FailoverManager()
        await manager.record_latency(LatencyRecord(
            provider="openai", model="gpt-4", purpose="chat", duration_ms=100.0
        ))
        await manager.record_latency(LatencyRecord(
            provider="anthropic", model="claude-3", purpose="chat", duration_ms=200.0
        ))
        stats = manager.get_latency_stats(provider="openai")
        assert stats["count"] == 1
        assert stats["avg_ms"] == 100.0

    @pytest.mark.asyncio
    async def test_latency_stats_empty(self):
        manager = FailoverManager()
        stats = manager.get_latency_stats()
        assert stats["count"] == 0
        assert stats["avg_ms"] == 0.0
        assert stats["success_rate"] == 0.0

    @pytest.mark.asyncio
    async def test_latency_success_rate(self):
        manager = FailoverManager()
        await manager.record_latency(LatencyRecord(
            provider="openai", model="gpt-4", purpose="chat", duration_ms=100.0, success=True
        ))
        await manager.record_latency(LatencyRecord(
            provider="openai", model="gpt-4", purpose="chat", duration_ms=200.0, success=False
        ))
        stats = manager.get_latency_stats()
        assert stats["count"] == 2
        assert stats["success_rate"] == 0.5

    def test_percentile_calculation(self):
        manager = FailoverManager()
        values = [10, 20, 30, 40, 50, 60, 70, 80, 90, 100]
        assert manager._percentile(values, 50) >= 50
        assert manager._percentile(values, 95) >= 90
        assert manager._percentile(values, 99) == 100

    def test_percentile_empty(self):
        manager = FailoverManager()
        assert manager._percentile([], 50) == 0.0


# ── execute_with_failover 测试 ──────────────────────────────────────────


class TestExecuteWithFailover:
    """故障转移执行器测试。"""

    @pytest.mark.asyncio
    async def test_primary_success_no_failover(self):
        candidates = [
            ModelCandidate(provider="openai", model="gpt-4", priority=0),
            ModelCandidate(provider="anthropic", model="claude-3", priority=1),
        ]
        call_count = [0]

        async def call_fn(candidate):
            call_count[0] += 1
            return {"ok": True, "response": "success"}

        result, used = await execute_with_failover(candidates, call_fn, "test_chain")
        assert result["ok"] is True
        assert used.provider == "openai"
        assert call_count[0] == 1  # 只调用了主模型

    @pytest.mark.asyncio
    async def test_failover_on_circuit_breaker_open(self):
        candidates = [
            ModelCandidate(provider="openai", model="gpt-4", priority=0),
            ModelCandidate(provider="anthropic", model="claude-3", priority=1),
        ]
        call_count = [0]

        async def call_fn(candidate):
            call_count[0] += 1
            if candidate.provider == "openai":
                return {"ok": False, "error": {"error_code": "model_service_circuit_breaker_open", "status_code": 503}}
            return {"ok": True, "response": "fallback success"}

        result, used = await execute_with_failover(candidates, call_fn, "test_chain")
        assert result["ok"] is True
        assert used.provider == "anthropic"
        assert call_count[0] == 2  # 调用了主+备

    @pytest.mark.asyncio
    async def test_failover_on_5xx_error(self):
        candidates = [
            ModelCandidate(provider="openai", model="gpt-4", priority=0),
            ModelCandidate(provider="anthropic", model="claude-3", priority=1),
        ]

        async def call_fn(candidate):
            if candidate.provider == "openai":
                return {"ok": False, "error": {"error_code": "server_error", "status_code": 502}}
            return {"ok": True, "response": "fallback"}

        result, used = await execute_with_failover(candidates, call_fn, "test_chain")
        assert result["ok"] is True
        assert used.provider == "anthropic"

    @pytest.mark.asyncio
    async def test_no_failover_on_400_error(self):
        candidates = [
            ModelCandidate(provider="openai", model="gpt-4", priority=0),
            ModelCandidate(provider="anthropic", model="claude-3", priority=1),
        ]

        async def call_fn(candidate):
            return {"ok": False, "error": {"error_code": "bad_request", "status_code": 400}}

        result, used = await execute_with_failover(candidates, call_fn, "test_chain")
        assert result["ok"] is False
        assert used.provider == "openai"  # 没有切换

    @pytest.mark.asyncio
    async def test_all_candidates_exhausted(self):
        candidates = [
            ModelCandidate(provider="openai", model="gpt-4", priority=0),
            ModelCandidate(provider="anthropic", model="claude-3", priority=1),
        ]

        async def call_fn(candidate):
            return {"ok": False, "error": {"error_code": "model_service_timeout", "status_code": 0}}

        result, used = await execute_with_failover(candidates, call_fn, "test_chain")
        assert result["ok"] is False
        assert "error" in result

    @pytest.mark.asyncio
    async def test_empty_candidates(self):
        result, used = await execute_with_failover([], lambda c: {"ok": True}, "test_chain")
        assert result["ok"] is False
        assert used is None

    @pytest.mark.asyncio
    async def test_failover_event_recorded(self):
        manager = get_failover_manager()
        initial_events = len(manager.get_events(limit=1000))

        candidates = [
            ModelCandidate(provider="openai", model="gpt-4", priority=0),
            ModelCandidate(provider="anthropic", model="claude-3", priority=1),
        ]

        async def call_fn(candidate):
            if candidate.provider == "openai":
                return {"ok": False, "error": {"error_code": "model_service_timeout", "status_code": 0}}
            return {"ok": True, "response": "fallback"}

        await execute_with_failover(candidates, call_fn, "test_chain_event", request_id="req-123")
        events = manager.get_events(limit=10)
        # 至少记录了一个事件
        assert len(events) >= 1


# ── 单例测试 ──────────────────────────────────────────


class TestSingleton:
    """单例模式测试。"""

    def test_get_failover_manager_returns_same_instance(self):
        m1 = get_failover_manager()
        m2 = get_failover_manager()
        assert m1 is m2


# ── API 路由测试 ──────────────────────────────────────────


class TestFailoverRoutes:
    """故障转移 API 路由测试。"""

    def test_routes_loaded(self):
        from api.routes.models import router
        route_paths = [route.path for route in router.routes]
        assert "/api/models/failover/circuit-breakers" in route_paths
        assert "/api/models/failover/chains" in route_paths
        assert "/api/models/failover/events" in route_paths
        assert "/api/models/latency/stats" in route_paths
        assert "/api/models/latency/providers" in route_paths
