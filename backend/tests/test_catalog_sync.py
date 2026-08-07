"""
catalog_sync 模块测试。

覆盖场景：
- models.dev / openrouter 上游响应解析（含 capabilities/modalities/pricing）
- 两源合并（capabilities 取并集、context_window 取 max、pricing per-field 合并）
- 转换为 Open-AwA 扁平结构
- write_json 保留 user_overrides 字段与用户手动新增的模型条目
- run_sync dry-run 不写文件

mock 策略：使用 httpx.MockTransport 拦截 HTTP 请求，避免真实网络依赖。
fixture 数据参考 cherry-studio provider-registry/data/models.json 的实际格式。
"""

import json
from typing import Any, Dict

import httpx
import pytest

from billing.catalog_sync import (
    compute_stats,
    convert_to_openawa,
    fetch_models_dev,
    fetch_openrouter,
    merge_meta,
    merge_sources,
    parse_md_entry,
    parse_or_entry,
    run_sync,
    write_json,
)


# ── fixture 数据：参考 cherry-studio 实际上游格式 ──────────────────────────────

MODELS_DEV_SAMPLE: Dict[str, Any] = {
    "openai": {
        "models": {
            "gpt-4o": {
                "name": "GPT-4o",
                "family": "gpt-4",
                "tool_call": True,
                "reasoning": False,
                "structured_output": True,
                "modalities": {
                    "input": ["text", "image"],
                    "output": ["text"],
                },
                "limit": {"context": 128000, "output": 16384},
                "cost": {
                    "input": 2.5,
                    "output": 10.0,
                    "cache_read": 1.25,
                },
            },
        },
    },
    "anthropic": {
        "models": {
            "claude-3-5-sonnet": {
                "name": "Claude 3.5 Sonnet",
                "family": "claude-3",
                "tool_call": True,
                "reasoning": True,
                "attachment": True,
                "modalities": {
                    "input": ["text", "image"],
                    "output": ["text"],
                },
                "limit": {"context": 200000, "output": 8192},
                "cost": {
                    "input": 3.0,
                    "output": 15.0,
                    "cache_read": 0.3,
                    "cache_write": 3.75,
                },
            },
        },
    },
}


OPENROUTER_SAMPLE: Dict[str, Any] = {
    "data": [
        {
            "id": "openai/gpt-4o",
            "context_length": 128000,
            "architecture": {
                "input_modalities": ["text", "image"],
                "output_modalities": ["text"],
            },
            "supported_parameters": ["tools", "response_format"],
            "pricing": {
                "prompt": "0.0000025",  # 美元/token，×1e6 = 2.5 美元/百万 token
                "completion": "0.00001",
            },
        },
        {
            "id": "deepseek/deepseek-chat",
            "context_length": 64000,
            "architecture": {
                "input_modalities": ["text"],
                "output_modalities": ["text"],
            },
            "supported_parameters": ["tools", "reasoning"],
            "pricing": {
                "prompt": "0.00000027",
                "completion": "0.0000011",
            },
        },
    ],
}


def _build_mock_transport(response_map: Dict[str, Any]) -> httpx.MockTransport:
    """
    根据 {url: response_json} 构建 httpx.MockTransport。

    匹配 url 路径返回对应 JSON，未匹配返回 404。
    """

    def handler(request: httpx.Request) -> httpx.Response:
        for url, payload in response_map.items():
            if str(request.url).startswith(url):
                return httpx.Response(200, json=payload)
        return httpx.Response(404, json={"error": "not found"})

    return httpx.MockTransport(handler)


# ── parse_md_entry 单元测试 ──────────────────────────────────────────────────────


def test_parse_md_entry_extracts_capabilities_and_pricing():
    """parse_md_entry 应正确推导 capabilities 并提取定价。"""
    raw = MODELS_DEV_SAMPLE["openai"]["models"]["gpt-4o"]
    parsed = parse_md_entry(raw)

    assert parsed is not None
    # tool_call → function-call, structured_output → structured-output
    # image input → image-recognition
    assert "function-call" in parsed["capabilities"]
    assert "structured-output" in parsed["capabilities"]
    assert "image-recognition" in parsed["capabilities"]
    assert parsed["input_modalities"] == ["text", "image"]
    assert parsed["output_modalities"] == ["text"]
    assert parsed["context_window"] == 128000
    assert parsed["max_output_tokens"] == 16384
    assert parsed["pricing"]["input"] == 2.5
    assert parsed["pricing"]["output"] == 10.0
    assert parsed["pricing"]["cache_read"] == 1.25
    assert parsed["family"] == "gpt-4"


def test_parse_md_entry_returns_none_for_invalid_input():
    """parse_md_entry 对非 dict 输入应返回 None。"""
    assert parse_md_entry("not a dict") is None
    assert parse_md_entry(None) is None
    assert parse_md_entry(123) is None


def test_parse_md_entry_handles_attachment_capability():
    """attachment=True 应推导出 file-input capability。"""
    raw = MODELS_DEV_SAMPLE["anthropic"]["models"]["claude-3-5-sonnet"]
    parsed = parse_md_entry(raw)
    assert parsed is not None
    assert "file-input" in parsed["capabilities"]
    assert "reasoning" in parsed["capabilities"]


# ── parse_or_entry 单元测试 ──────────────────────────────────────────────────────


def test_parse_or_entry_converts_pricing_per_million_tokens():
    """openrouter pricing 字符串（美元/token）应 ×1e6 转换为美元/百万 token。"""
    raw = OPENROUTER_SAMPLE["data"][0]
    parsed = parse_or_entry(raw)

    assert parsed is not None
    # prompt=0.0000025 → 2.5 美元/百万 token
    assert parsed["pricing"]["input"] == pytest.approx(2.5, rel=1e-6)
    assert parsed["pricing"]["output"] == pytest.approx(10.0, rel=1e-6)
    assert parsed["context_window"] == 128000
    assert parsed["input_modalities"] == ["text", "image"]


def test_parse_or_entry_derives_capabilities_from_supported_parameters():
    """supported_parameters 中 tools/response_format 应推导为 function-call/structured-output。"""
    raw = OPENROUTER_SAMPLE["data"][0]
    parsed = parse_or_entry(raw)
    assert "function-call" in parsed["capabilities"]
    assert "structured-output" in parsed["capabilities"]


def test_parse_or_entry_returns_none_for_missing_id_format():
    """无 id 字段或 id 不含 / 的条目应被跳过（在 fetch 层处理，parse 层仅校验 dict 类型）。"""
    assert parse_or_entry("invalid") is None
    assert parse_or_entry(None) is None


# ── merge_meta 单元测试 ──────────────────────────────────────────────────────────


def test_merge_meta_takes_union_of_capabilities():
    """合并后 capabilities 应为两源并集。"""
    a = {"capabilities": ["function-call", "reasoning"]}
    b = {"capabilities": ["structured-output", "reasoning"]}
    merged = merge_meta(a, b)
    assert set(merged["capabilities"]) == {"function-call", "reasoning", "structured-output"}


def test_merge_meta_takes_max_context_window():
    """合并后 context_window 应取两源最大值。"""
    a = {"context_window": 128000}
    b = {"context_window": 200000}
    merged = merge_meta(a, b)
    assert merged["context_window"] == 200000


def test_merge_meta_pricing_per_field_merge_a_wins():
    """pricing 按 per-field 合并：a 优先，b 仅填补 a 缺失字段。"""
    a = {"pricing": {"input": 2.5, "output": 10.0}}  # a 有 input/output，无 cache_read
    b = {"pricing": {"input": 99.0, "cache_read": 1.25}}  # b 有 cache_read
    merged = merge_meta(a, b)
    # a 的 input 优先（不被 b 覆盖）
    assert merged["pricing"]["input"] == 2.5
    assert merged["pricing"]["output"] == 10.0
    # b 填补 a 缺失的 cache_read
    assert merged["pricing"]["cache_read"] == 1.25


def test_merge_meta_modalities_union():
    """input_modalities 应取并集。"""
    a = {"input_modalities": ["text"]}
    b = {"input_modalities": ["text", "image"]}
    merged = merge_meta(a, b)
    assert set(merged["input_modalities"]) == {"text", "image"}


# ── fetch_models_dev / fetch_openrouter 集成测试 ─────────────────────────────────


async def test_fetch_models_dev_parses_correctly(monkeypatch):
    """fetch_models_dev 应正确解析上游响应为 {key: meta} 字典。"""
    transport = _build_mock_transport({
        "https://models.dev/api.json": MODELS_DEV_SAMPLE,
    })

    real_client_init = httpx.AsyncClient.__init__

    def patched_init(self, *args, **kwargs):
        kwargs["transport"] = transport
        real_client_init(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", patched_init)

    result = await fetch_models_dev("https://models.dev/api.json", timeout=5.0)

    assert "openai/gpt-4o" in result
    assert "anthropic/claude-3-5-sonnet" in result
    assert result["openai/gpt-4o"]["pricing"]["input"] == 2.5
    assert "function-call" in result["openai/gpt-4o"]["capabilities"]


async def test_fetch_openrouter_converts_pricing(monkeypatch):
    """fetch_openrouter 应将美元/token 字符串转换为美元/百万 token。"""
    transport = _build_mock_transport({
        "https://openrouter.ai/api/v1/models": OPENROUTER_SAMPLE,
    })

    real_client_init = httpx.AsyncClient.__init__

    def patched_init(self, *args, **kwargs):
        kwargs["transport"] = transport
        real_client_init(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", patched_init)

    result = await fetch_openrouter("https://openrouter.ai/api/v1/models", timeout=5.0)

    assert "openai/gpt-4o" in result
    assert "deepseek/deepseek-chat" in result
    # 0.0000025 美元/token → 2.5 美元/百万 token
    assert result["openai/gpt-4o"]["pricing"]["input"] == pytest.approx(2.5, rel=1e-6)
    assert result["openai/gpt-4o"]["pricing"]["output"] == pytest.approx(10.0, rel=1e-6)


async def test_fetch_raises_on_http_error(monkeypatch):
    """HTTP 4xx/5xx 必须显式抛错（禁止以空字典伪装拉取成功）。"""
    transport = httpx.MockTransport(lambda request: httpx.Response(500, json={"error": "server"}))

    real_client_init = httpx.AsyncClient.__init__

    def patched_init(self, *args, **kwargs):
        kwargs["transport"] = transport
        real_client_init(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", patched_init)

    with pytest.raises(Exception):
        await fetch_models_dev("https://models.dev/api.json", timeout=5.0)
    with pytest.raises(Exception):
        await fetch_openrouter("https://openrouter.ai/api/v1/models", timeout=5.0)


# ── merge_sources 集成测试 ───────────────────────────────────────────────────────


def test_merge_sources_takes_union():
    """两源同一模型合并后 capabilities 应为并集，context_window 取 max。"""
    md = {
        "openai/gpt-4o": {
            "capabilities": ["function-call", "structured-output"],
            "context_window": 128000,
            "pricing": {"input": 2.5, "output": 10.0, "cache_read": 1.25},
            "input_modalities": ["text", "image"],
        },
    }
    or_data = {
        "openai/gpt-4o": {
            "capabilities": ["function-call", "reasoning"],
            "context_window": 200000,
            "pricing": {"input": 99.0, "output": 99.0},
            "input_modalities": ["text"],
        },
    }
    merged = merge_sources(md, or_data)

    assert "openai/gpt-4o" in merged
    meta = merged["openai/gpt-4o"]
    # capabilities 并集
    assert set(meta["capabilities"]) == {"function-call", "structured-output", "reasoning"}
    # context_window 取 max
    assert meta["context_window"] == 200000
    # pricing: md 优先，or 填补缺失（or 的 output=99 不应覆盖 md 的 10）
    assert meta["pricing"]["input"] == 2.5
    assert meta["pricing"]["output"] == 10.0
    assert meta["pricing"]["cache_read"] == 1.25
    # modalities 并集
    assert set(meta["input_modalities"]) == {"text", "image"}


# ── convert_to_openawa 单元测试 ──────────────────────────────────────────────────


def test_convert_to_openawa_flat_structure():
    """转换后应为扁平结构，含所有 cherry-studio 兼容字段。"""
    catalog = {
        "openai/gpt-4o": {
            "capabilities": ["function-call"],
            "input_modalities": ["text", "image"],
            "output_modalities": ["text"],
            "context_window": 128000,
            "max_output_tokens": 16384,
            "pricing": {"input": 2.5, "output": 10.0, "cache_read": 1.25, "cache_write": 2.5},
            "family": "gpt-4",
        },
    }
    rows = convert_to_openawa(catalog)

    assert len(rows) == 1
    row = rows[0]
    assert row["provider"] == "openai"
    assert row["model"] == "gpt-4o"
    assert row["input_price"] == 2.5
    assert row["output_price"] == 10.0
    assert row["cache_read_price"] == 1.25
    assert row["cache_write_price"] == 2.5
    assert row["currency"] == "USD"
    assert row["context_window"] == 128000
    assert row["max_output_tokens"] == 16384
    assert row["owned_by"] == "openai"
    assert row["family"] == "gpt-4"
    assert row["capabilities"] == ["function-call"]
    assert row["input_modalities"] == ["text", "image"]
    assert row["output_modalities"] == ["text"]


def test_convert_to_openawa_handles_missing_pricing():
    """无 pricing 的模型应输出 None 定价字段，但仍保留条目。"""
    catalog = {
        "ai21/jamba-mini-1-7": {
            "capabilities": [],
            "input_modalities": ["text"],
            "output_modalities": ["text"],
        },
    }
    rows = convert_to_openawa(catalog)
    assert len(rows) == 1
    row = rows[0]
    assert row["input_price"] is None
    assert row["output_price"] is None
    assert row["cache_read_price"] is None


# ── compute_stats 单元测试 ───────────────────────────────────────────────────────


def test_compute_stats_correct_categorization():
    """应正确分类新增/更新/移除/跳过。"""
    old = [
        {"provider": "openai", "model": "gpt-4o", "input_price": 2.5, "output_price": 10.0},
        {"provider": "openai", "model": "gpt-4o-mini", "input_price": 0.15, "output_price": 0.6},
        {"provider": "user", "model": "custom-model", "input_price": 1.0, "output_price": 1.0},
    ]
    new = [
        {"provider": "openai", "model": "gpt-4o", "input_price": 2.5, "output_price": 10.0},  # 无变化 → skipped
        {"provider": "openai", "model": "gpt-4o-mini", "input_price": 0.20, "output_price": 0.6},  # 价格变 → updated
        {"provider": "anthropic", "model": "claude-3", "input_price": 3.0, "output_price": 15.0},  # 新增
    ]
    stats = compute_stats(old, new)

    assert stats["added"] == 1
    assert stats["updated"] == 1
    assert stats["skipped"] == 1
    # user/custom-model 仅在旧数据中 → removed
    assert stats["removed"] == 1


# ── write_json 测试（含 SubTask 3.8 user_overrides 保留） ────────────────────────


def test_write_json_preserves_user_overrides(tmp_path):
    """write_json 在 user_overrides 集合中的记录应保留用户修改的定价字段。"""
    target = tmp_path / "pricing_data.json"
    old_data = [
        {
            "provider": "openai",
            "model": "gpt-4o",
            "input_price": 99.99,  # 用户修改后的价格
            "output_price": 88.88,
            "cache_read_price": 50.0,
            "cache_write_price": 60.0,
            "currency": "USD",
            "context_window": 128000,
            "capabilities": ["function-call"],
            "input_modalities": ["text"],
            "output_modalities": ["text"],
        },
    ]
    target.write_text(json.dumps(old_data), encoding="utf-8")

    new_data = [
        {
            "provider": "openai",
            "model": "gpt-4o",
            "input_price": 2.5,  # 上游价格
            "output_price": 10.0,
            "cache_read_price": 1.25,
            "cache_write_price": 2.5,
            "currency": "USD",
            "context_window": 128000,
            "capabilities": ["function-call", "structured-output"],
            "input_modalities": ["text", "image"],
            "output_modalities": ["text"],
        },
    ]

    # 标记 (openai, gpt-4o) 为 user_override
    stats = write_json(new_data, target, user_overrides={("openai", "gpt-4o")})

    # 应被标记为 updated（其他字段有更新）
    assert stats["updated"] == 1

    result = json.loads(target.read_text(encoding="utf-8"))
    assert len(result) == 1
    row = result[0]
    # user_override 字段保留用户值
    assert row["input_price"] == 99.99
    assert row["output_price"] == 88.88
    assert row["cache_read_price"] == 50.0
    assert row["cache_write_price"] == 60.0
    # 非 user_override 字段被更新
    assert "structured-output" in row["capabilities"]
    assert "image" in row["input_modalities"]


def test_write_json_preserves_user_modified_price(tmp_path):
    """用户修改的 input_price 不应被同步覆盖（user_overrides 机制）。"""
    target = tmp_path / "pricing_data.json"
    old_data = [
        {
            "provider": "openai",
            "model": "gpt-4o",
            "input_price": 5.55,  # 用户手动调整
            "output_price": 10.0,
            "currency": "USD",
            "context_window": 128000,
            "capabilities": [],
            "input_modalities": ["text"],
            "output_modalities": ["text"],
        },
    ]
    target.write_text(json.dumps(old_data), encoding="utf-8")

    new_data = [
        {
            "provider": "openai",
            "model": "gpt-4o",
            "input_price": 2.5,  # 上游价格更低
            "output_price": 10.0,
            "currency": "USD",
            "context_window": 128000,
            "capabilities": [],
            "input_modalities": ["text"],
            "output_modalities": ["text"],
        },
    ]

    write_json(new_data, target, user_overrides={("openai", "gpt-4o")})

    result = json.loads(target.read_text(encoding="utf-8"))
    assert result[0]["input_price"] == 5.55  # 用户值保留


def test_write_json_keeps_user_added_models(tmp_path):
    """用户手动新增的模型条目（不在新数据中）应被保留。"""
    target = tmp_path / "pricing_data.json"
    old_data = [
        {
            "provider": "custom",
            "model": "my-finetuned-model",
            "input_price": 0.5,
            "output_price": 1.5,
            "currency": "USD",
            "context_window": 32000,
            "capabilities": [],
            "input_modalities": ["text"],
            "output_modalities": ["text"],
        },
        {
            "provider": "openai",
            "model": "gpt-4o",
            "input_price": 2.5,
            "output_price": 10.0,
            "currency": "USD",
            "context_window": 128000,
            "capabilities": [],
            "input_modalities": ["text"],
            "output_modalities": ["text"],
        },
    ]
    target.write_text(json.dumps(old_data), encoding="utf-8")

    # 新数据中只有 openai/gpt-4o，custom/my-finetuned-model 应被保留
    new_data = [
        {
            "provider": "openai",
            "model": "gpt-4o",
            "input_price": 2.5,
            "output_price": 10.0,
            "currency": "USD",
            "context_window": 128000,
            "capabilities": [],
            "input_modalities": ["text"],
            "output_modalities": ["text"],
        },
    ]

    stats = write_json(new_data, target)

    result = json.loads(target.read_text(encoding="utf-8"))
    # 用户手动新增的条目应保留
    providers_models = {(r["provider"], r["model"]) for r in result}
    assert ("custom", "my-finetuned-model") in providers_models
    assert ("openai", "gpt-4o") in providers_models
    # stats["removed"] 计数应反映保留的条目
    assert stats["removed"] == 1


def test_write_json_creates_new_file_when_not_exists(tmp_path):
    """目标文件不存在时应创建新文件。"""
    target = tmp_path / "subdir" / "pricing_data.json"
    new_data = [
        {
            "provider": "openai",
            "model": "gpt-4o",
            "input_price": 2.5,
            "output_price": 10.0,
            "currency": "USD",
            "context_window": 128000,
            "capabilities": [],
            "input_modalities": ["text"],
            "output_modalities": ["text"],
        },
    ]

    stats = write_json(new_data, target)

    assert target.exists()
    assert stats["added"] == 1
    result = json.loads(target.read_text(encoding="utf-8"))
    assert len(result) == 1
    assert result[0]["provider"] == "openai"


def test_write_json_without_user_overrides_overwrites_pricing(tmp_path):
    """未标记为 user_override 的记录应被新数据覆盖。"""
    target = tmp_path / "pricing_data.json"
    old_data = [
        {
            "provider": "openai",
            "model": "gpt-4o",
            "input_price": 99.99,
            "output_price": 88.88,
            "currency": "USD",
            "context_window": 128000,
            "capabilities": [],
            "input_modalities": ["text"],
            "output_modalities": ["text"],
        },
    ]
    target.write_text(json.dumps(old_data), encoding="utf-8")

    new_data = [
        {
            "provider": "openai",
            "model": "gpt-4o",
            "input_price": 2.5,
            "output_price": 10.0,
            "currency": "USD",
            "context_window": 128000,
            "capabilities": [],
            "input_modalities": ["text"],
            "output_modalities": ["text"],
        },
    ]

    write_json(new_data, target, user_overrides=None)

    result = json.loads(target.read_text(encoding="utf-8"))
    # 未标记 user_override → 用新数据覆盖
    assert result[0]["input_price"] == 2.5
    assert result[0]["output_price"] == 10.0


# ── run_sync 集成测试 ────────────────────────────────────────────────────────────


async def test_run_sync_dry_run_does_not_write_file(tmp_path, monkeypatch):
    """dry_run=True 时不应写入文件，只返回统计。"""
    original_init = httpx.AsyncClient.__init__

    def patched_init(self, *args, **kwargs):
        kwargs.pop("transport", None)
        def handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            for prefix, payload in [
                ("https://models.dev/api.json", MODELS_DEV_SAMPLE),
                ("https://openrouter.ai/api/v1/models", OPENROUTER_SAMPLE),
            ]:
                if url.startswith(prefix):
                    return httpx.Response(200, json=payload)
            return httpx.Response(404, json={"error": "not found"})
        kwargs["transport"] = httpx.MockTransport(handler)
        original_init(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", patched_init)

    # 临时替换 PRICING_DATA_PATH 指向 tmp_path
    fake_path = tmp_path / "pricing_data.json"
    monkeypatch.setattr("billing.catalog_sync.PRICING_DATA_PATH", fake_path)

    stats = await run_sync(dry_run=True)

    # dry_run 不应创建文件
    assert not fake_path.exists()
    assert stats["dry_run"] is True
    assert "synced_at" in stats
    # 应解析到至少 openai/gpt-4o 和 anthropic/claude-3-5-sonnet
    assert stats["added"] >= 2


async def test_run_sync_writes_file_when_not_dry_run(tmp_path, monkeypatch):
    """dry_run=False 时应写入文件。"""
    original_init = httpx.AsyncClient.__init__

    def patched_init(self, *args, **kwargs):
        kwargs.pop("transport", None)
        def handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            for prefix, payload in [
                ("https://models.dev/api.json", MODELS_DEV_SAMPLE),
                ("https://openrouter.ai/api/v1/models", OPENROUTER_SAMPLE),
            ]:
                if url.startswith(prefix):
                    return httpx.Response(200, json=payload)
            return httpx.Response(404, json={"error": "not found"})
        kwargs["transport"] = httpx.MockTransport(handler)
        original_init(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", patched_init)

    fake_path = tmp_path / "pricing_data.json"
    monkeypatch.setattr("billing.catalog_sync.PRICING_DATA_PATH", fake_path)

    stats = await run_sync(dry_run=False)

    assert fake_path.exists()
    result = json.loads(fake_path.read_text(encoding="utf-8"))
    assert len(result) >= 2
    providers_models = {(r["provider"], r["model"]) for r in result}
    assert ("openai", "gpt-4o") in providers_models
    assert stats["dry_run"] is False


async def test_run_sync_raises_on_source_failure(tmp_path, monkeypatch):
    """任一源拉取失败时同步必须显式抛错（禁止假同步完成），且不写文件。"""
    original_init = httpx.AsyncClient.__init__

    def patched_init(self, *args, **kwargs):
        kwargs.pop("transport", None)
        def handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            # models.dev 返回 500
            if url.startswith("https://models.dev"):
                return httpx.Response(500, json={"error": "server error"})
            # openrouter 正常
            if url.startswith("https://openrouter.ai"):
                return httpx.Response(200, json=OPENROUTER_SAMPLE)
            return httpx.Response(404)

        kwargs["transport"] = httpx.MockTransport(handler)
        original_init(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", patched_init)
    fake_path = tmp_path / "pricing_data.json"
    monkeypatch.setattr("billing.catalog_sync.PRICING_DATA_PATH", fake_path)

    with pytest.raises(Exception):
        await run_sync(dry_run=False)

    # 失败时不得写入文件（保留旧数据）
    assert not fake_path.exists()
