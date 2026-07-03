"""
搜索配置路由 - 提供搜索 Provider 配置的查询、更新与连通性测试能力。
支持 duckduckgo / searxng / disabled 三种 provider 类型，遵循 SSRF 安全策略。
"""

import asyncio
import time
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Depends, HTTPException
from loguru import logger
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from api.dependencies import get_current_user, get_db
from db.models import SearchProviderConfig, User
from security.search_ssrf import validate_search_url


router = APIRouter(prefix="/api/search", tags=["search"])

# 默认 provider 配置（数据库无激活记录时返回）
_DEFAULT_PROVIDER = "duckduckgo"


class SearchConfigResponse(BaseModel):
    """搜索配置响应模型，api_key 仅以布尔形式呈现，不暴露原值。"""

    provider: str
    base_url: Optional[str]
    api_key_set: bool
    enabled: bool
    extra_config: Dict[str, Any]
    model_config = ConfigDict(from_attributes=True)


class SearchConfigUpdate(BaseModel):
    """搜索配置更新请求体。"""

    provider: str = Field(..., pattern="^(duckduckgo|searxng|disabled)$")
    base_url: Optional[str] = Field(None, max_length=255)
    api_key: Optional[str] = Field(None, max_length=255)
    enabled: bool = True
    extra_config: Dict[str, Any] = Field(default_factory=dict)


class SearchTestRequest(BaseModel):
    """搜索连通性测试请求体。"""

    provider: str = Field(..., pattern="^(duckduckgo|searxng)$")
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    extra_config: Dict[str, Any] = Field(default_factory=dict)
    test_query: str = Field(default="openawa", max_length=100)


class SearchTestResponse(BaseModel):
    """搜索连通性测试响应体。"""

    success: bool
    latency_ms: int
    sample_results: List[Any]
    error: Optional[str] = None


def _serialize_config(config: Optional[SearchProviderConfig]) -> SearchConfigResponse:
    """将 ORM 对象转为响应模型，未配置时返回默认值（duckduckgo 兜底）。"""
    if config is None:
        return SearchConfigResponse(
            provider=_DEFAULT_PROVIDER,
            base_url=None,
            api_key_set=False,
            enabled=True,
            extra_config={},
        )
    return SearchConfigResponse(
        provider=config.provider,
        base_url=config.base_url,
        api_key_set=bool(config.api_key),
        enabled=config.enabled,
        extra_config=config.extra_config or {},
    )


def _normalize_base_url(raw: Optional[str]) -> Optional[str]:
    """规整 base_url：去首尾空白；空字符串视为 None。"""
    if not raw:
        return None
    return raw.strip()


@router.get("/config", response_model=SearchConfigResponse)
async def get_search_config(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    返回当前激活的搜索 provider 配置。
    激活定义：enabled=True 的记录（理论上仅一条）。
    无激活记录时返回 duckduckgo 默认值。
    """
    active = (
        db.query(SearchProviderConfig)
        .filter(SearchProviderConfig.enabled == True)  # noqa: E712
        .order_by(SearchProviderConfig.updated_at.desc())
        .first()
    )
    logger.bind(
        event="search_config_get",
        module="search",
        action="get_config",
        user_id=current_user.id,
        has_active=active is not None,
    ).debug("查询搜索配置完成")
    return _serialize_config(active)


@router.put("/config", response_model=SearchConfigResponse)
async def update_search_config(
    payload: SearchConfigUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    更新搜索 provider 配置。
    校验规则：
      - provider=searxng 时 base_url 必填，必须以 http:// 或 https:// 开头，
        且通过 urlparse 解析得到 hostname；
      - 调用 validate_search_url 执行 SSRF 校验，失败返回 400。
    持久化策略：
      - 已有激活记录则更新该记录；
      - 否则插入新记录；
      - api_key 为 None 时保留已有值。
    """
    base_url = _normalize_base_url(payload.base_url)

    # provider=searxng 强制要求 base_url，并执行 SSRF 校验
    if payload.provider == "searxng":
        if not base_url:
            raise HTTPException(status_code=400, detail="searxng provider 必须提供 base_url")
        if not (base_url.startswith("http://") or base_url.startswith("https://")):
            raise HTTPException(
                status_code=400,
                detail="base_url 必须以 http:// 或 https:// 开头",
            )
        parsed = urlparse(base_url)
        if not parsed.hostname:
            raise HTTPException(status_code=400, detail="base_url 缺少主机名")

        allow_private = bool(payload.extra_config.get("allow_private_network", False))
        is_valid, error_message = validate_search_url(base_url, allow_private=allow_private)
        if not is_valid:
            logger.bind(
                event="search_config_ssrf_blocked",
                module="search",
                action="update_config",
                user_id=current_user.id,
                base_url=base_url,
                allow_private=allow_private,
            ).warning(f"搜索配置被 SSRF 策略拒绝: {error_message}")
            raise HTTPException(status_code=400, detail=error_message)

    # 查询已有激活记录（理论上仅一条）
    existing = (
        db.query(SearchProviderConfig)
        .filter(SearchProviderConfig.enabled == True)  # noqa: E712
        .order_by(SearchProviderConfig.updated_at.desc())
        .first()
    )

    if existing is not None:
        # 更新已有记录：保留原 api_key 当 payload 未提供时
        existing.provider = payload.provider
        existing.base_url = base_url
        existing.enabled = payload.enabled
        if payload.api_key is not None:
            existing.api_key = payload.api_key
        existing.extra_config = payload.extra_config
        record = existing
    else:
        # 插入新记录
        record = SearchProviderConfig(
            provider=payload.provider,
            base_url=base_url,
            api_key=payload.api_key,
            enabled=payload.enabled,
            extra_config=payload.extra_config,
        )
        db.add(record)

    db.commit()
    db.refresh(record)

    logger.bind(
        event="search_config_update",
        module="search",
        action="update_config",
        provider=payload.provider,
        user_id=current_user.id,
        is_new_record=existing is None,
    ).info(f"搜索配置已更新: provider={payload.provider}")

    return _serialize_config(record)


@router.post("/test", response_model=SearchTestResponse)
async def test_search(
    payload: SearchTestRequest,
    current_user: User = Depends(get_current_user),
):
    """
    测试搜索 provider 的连通性与可用性，不写入数据库。
    - searxng: 调用 {base_url}/search?q=...&format=json&pageno=1，超时 10 秒；
    - duckduckgo: 复用 core.builtin_tools.web_search.WebSearchSkill._duckduckgo_search；
    - 返回延迟、最多 3 条样例结果与失败原因。
    """
    test_query = payload.test_query
    start = time.perf_counter()

    def _build_response(
        success: bool,
        sample: List[Dict[str, Any]],
        error: Optional[str],
    ) -> SearchTestResponse:
        return SearchTestResponse(
            success=success,
            latency_ms=int((time.perf_counter() - start) * 1000),
            sample_results=sample,
            error=error,
        )

    try:
        if payload.provider == "searxng":
            return await _test_searxng(payload, test_query, start, _build_response)
        if payload.provider == "duckduckgo":
            return await _test_duckduckgo(test_query, start, _build_response)
        # pattern 校验已限制 provider 取值，理论上不会到达
        return _build_response(False, [], f"不支持的 provider: {payload.provider}")
    except Exception as exc:
        # 兜底：未预期的异常也以 success=False 返回，不抛 500
        logger.bind(
            event="search_test_error",
            module="search",
            action="test_search",
            provider=payload.provider,
            user_id=current_user.id,
            error_type=type(exc).__name__,
        ).error(f"搜索连通性测试异常: {exc}")
        return _build_response(False, [], f"未知错误: {type(exc).__name__}")


async def _test_searxng(
    payload: SearchTestRequest,
    test_query: str,
    start: float,
    build_response,
) -> SearchTestResponse:
    """执行 SearXNG 连通性测试。"""
    base_url = _normalize_base_url(payload.base_url)
    if not base_url:
        return build_response(False, [], "searxng provider 必须提供 base_url")

    # SSRF 校验（与 PUT /config 保持一致的安全策略）
    allow_private = bool(payload.extra_config.get("allow_private_network", False))
    is_valid, error_message = validate_search_url(base_url, allow_private=allow_private)
    if not is_valid:
        logger.bind(
            event="search_test_ssrf_blocked",
            module="search",
            action="test_search",
            provider="searxng",
            base_url=base_url,
            allow_private=allow_private,
        ).warning(f"搜索测试被 SSRF 策略拒绝: {error_message}")
        return build_response(False, [], error_message)

    query_url = f"{base_url.rstrip('/')}/search"
    # 请求头仅含 ASCII 字符，符合 ISO-8859-1 范围要求
    headers: Dict[str, str] = {
        "User-Agent": "Open-AwA/1.0 SearchConfigTest",
        "Accept": "application/json",
    }
    if payload.api_key:
        headers["Authorization"] = f"Bearer {payload.api_key}"

    params = {
        "q": test_query,
        "format": "json",
        "pageno": "1",
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(query_url, params=params, headers=headers)
    except httpx.TimeoutException:
        logger.bind(
            event="search_test_timeout",
            module="search",
            action="test_search",
            provider="searxng",
            latency_ms=int((time.perf_counter() - start) * 1000),
        ).warning("SearXNG 连通性测试超时")
        return build_response(False, [], "连接超时")
    except httpx.ConnectError as exc:
        logger.bind(
            event="search_test_connect_error",
            module="search",
            action="test_search",
            provider="searxng",
            error_type=type(exc).__name__,
        ).warning(f"SearXNG 连接失败: {exc}")
        return build_response(False, [], f"无法连接到服务器: {type(exc).__name__}")
    except httpx.HTTPError as exc:
        logger.bind(
            event="search_test_http_error",
            module="search",
            action="test_search",
            provider="searxng",
            error_type=type(exc).__name__,
        ).warning(f"SearXNG HTTP 错误: {exc}")
        return build_response(False, [], f"HTTP 错误: {type(exc).__name__}")

    if response.status_code != 200:
        return build_response(False, [], f"HTTP {response.status_code}")

    try:
        data = response.json()
    except Exception:
        return build_response(False, [], "响应不是有效的 JSON")

    raw_results = data.get("results", []) if isinstance(data, dict) else []
    if not isinstance(raw_results, list):
        raw_results = []

    sample = _truncate_results(raw_results, 3)
    logger.bind(
        event="search_test_success",
        module="search",
        action="test_search",
        provider="searxng",
        latency_ms=int((time.perf_counter() - start) * 1000),
        result_count=len(raw_results),
    ).info(f"SearXNG 连通性测试成功，结果数: {len(raw_results)}")
    return build_response(True, sample, None)


async def _test_duckduckgo(
    test_query: str,
    start: float,
    build_response,
) -> SearchTestResponse:
    """执行 DuckDuckGo 连通性测试，复用 WebSearchSkill._duckduckgo_search。"""
    try:
        from core.builtin_tools.web_search import WebSearchSkill

        skill = WebSearchSkill()
        # _duckduckgo_search 内部已有 15 秒超时，外层再包一层 10 秒超时控制
        results = await asyncio.wait_for(
            skill._duckduckgo_search(test_query, 3),
            timeout=10.0,
        )
    except asyncio.TimeoutError:
        logger.bind(
            event="search_test_timeout",
            module="search",
            action="test_search",
            provider="duckduckgo",
            latency_ms=int((time.perf_counter() - start) * 1000),
        ).warning("DuckDuckGo 连通性测试超时")
        return build_response(False, [], "连接超时")
    except Exception as exc:
        logger.bind(
            event="search_test_error",
            module="search",
            action="test_search",
            provider="duckduckgo",
            error_type=type(exc).__name__,
        ).warning(f"DuckDuckGo 搜索失败: {exc}")
        return build_response(False, [], f"DuckDuckGo 搜索失败: {type(exc).__name__}")

    sample = _truncate_results(results, 3)
    logger.bind(
        event="search_test_success",
        module="search",
        action="test_search",
        provider="duckduckgo",
        latency_ms=int((time.perf_counter() - start) * 1000),
        result_count=len(results),
    ).info(f"DuckDuckGo 连通性测试成功，结果数: {len(results)}")
    return build_response(True, sample, None)


def _truncate_results(raw_results: List[Any], limit: int) -> List[Dict[str, Any]]:
    """将原始结果列表规整为统一 schema 并截取前 limit 条。"""
    sample: List[Dict[str, Any]] = []
    for item in raw_results[:limit]:
        if not isinstance(item, dict):
            continue
        sample.append({
            "title": str(item.get("title", ""))[:200],
            "url": str(item.get("url", "")),
            "snippet": str(item.get("snippet") or item.get("content", ""))[:500],
        })
    return sample
