"""
API客户端模块
提供与微信iLink API的HTTP通信能力
"""

from __future__ import annotations

import json
from typing import Any, Dict, Optional

import httpx
from loguru import logger

from backend.skills.weixin.config import WeixinRuntimeConfig, DEFAULT_BASE_URL
from backend.skills.weixin.errors import WeixinAdapterError
from backend.skills.weixin.utils.helpers import build_random_wechat_uin


async def api_post(
    config: WeixinRuntimeConfig,
    endpoint: str,
    body: Dict[str, Any],
    timeout_seconds: Optional[int] = None
) -> Dict[str, Any]:
    """
    发送POST请求到微信API
    
    参数:
        config: 运行时配置
        endpoint: API端点路径
        body: 请求体
        timeout_seconds: 超时时间（秒），默认使用配置中的值
        
    返回:
        API响应字典
        
    抛出:
        WeixinAdapterError: 当请求失败时
    """
    payload = dict(body)
    payload["base_info"] = {"channel_version": config.channel_version}
    url = f"{config.base_url}/{endpoint.lstrip('/')}"
    timeout_value = timeout_seconds or config.timeout_seconds

    headers = {
        "Content-Type": "application/json",
        "AuthorizationType": "ilink_bot_token",
        "Authorization": f"Bearer {config.token}",
        "X-WECHAT-UIN": build_random_wechat_uin(),
        "iLink-App-ClientVersion": "1",
    }

    try:
        async with httpx.AsyncClient(timeout=timeout_value) as client:
            response = await client.post(url, json=payload, headers=headers)
        content_type = response.headers.get("content-type", "")
        if response.status_code >= 400:
            raise WeixinAdapterError.upstream_http_error(
                endpoint=endpoint,
                status_code=response.status_code,
                response_text=response.text
            )
        if "application/json" in content_type.lower():
            return response.json()
        raw = response.text.strip()
        if raw.startswith("{") or raw.startswith("["):
            try:
                return json.loads(raw)
            except Exception:
                pass
        return {"raw_text": raw}
    except WeixinAdapterError:
        raise
    except httpx.TimeoutException:
        raise WeixinAdapterError.timeout(endpoint=endpoint, timeout_seconds=timeout_value)
    except httpx.HTTPError as exc:
        raise WeixinAdapterError.http_error(endpoint=endpoint, error=str(exc))


async def api_get(
    base_url: str,
    endpoint: str,
    params: Optional[Dict[str, Any]] = None,
    timeout_seconds: int = 15,
    extra_headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    """
    发送GET请求到微信API
    
    参数:
        base_url: API基础URL
        endpoint: API端点路径
        params: 查询参数
        timeout_seconds: 超时时间（秒）
        extra_headers: 额外的请求头
        
    返回:
        API响应字典
        
    抛出:
        WeixinAdapterError: 当请求失败时
    """
    normalized_base_url = str(base_url or DEFAULT_BASE_URL).strip().rstrip("/")
    url = f"{normalized_base_url}/{endpoint.lstrip('/')}"
    headers: Dict[str, str] = {}
    if extra_headers:
        headers.update(extra_headers)

    logger.debug(f"[weixin api_get] GET {url} params={params}")
    try:
        async with httpx.AsyncClient(timeout=max(1, int(timeout_seconds))) as client:
            response = await client.get(url, params=params, headers=headers)
        content_type = response.headers.get("content-type", "")
        logger.debug(
            f"[weixin api_get] {endpoint} status={response.status_code} "
            f"content-type={content_type!r} body={response.text[:500]!r}"
        )
        if response.status_code >= 400:
            raise WeixinAdapterError.upstream_http_error(
                endpoint=endpoint,
                status_code=response.status_code,
                response_text=response.text
            )
        if "application/json" in content_type.lower():
            return response.json()
        raw = response.text.strip()
        if raw.startswith("{") or raw.startswith("["):
            try:
                return json.loads(raw)
            except Exception:
                pass
        return {"raw_text": raw}
    except WeixinAdapterError:
        raise
    except httpx.TimeoutException:
        if endpoint.strip().lower() == "ilink/bot/get_qrcode_status":
            logger.debug(f"[weixin api_get] {endpoint} client timeout after {timeout_seconds}s, fallback to waiting")
            return {"status": "waiting"}
        raise WeixinAdapterError.timeout(endpoint=endpoint, timeout_seconds=timeout_seconds)
    except httpx.HTTPError as exc:
        raise WeixinAdapterError.http_error(endpoint=endpoint, error=str(exc))


async def fetch_login_qrcode(
    base_url: str,
    bot_type: str = "3",
    timeout_seconds: int = 15
) -> Dict[str, Any]:
    """
    获取登录二维码
    
    参数:
        base_url: API基础URL
        bot_type: 机器人类型
        timeout_seconds: 超时时间（秒）
        
    返回:
        包含二维码信息的字典
    """
    return await api_get(
        base_url=base_url,
        endpoint="ilink/bot/get_bot_qrcode",
        params={"bot_type": bot_type},
        timeout_seconds=max(1, min(int(timeout_seconds), 5))
    )


async def fetch_qrcode_status(
    base_url: str,
    qrcode: str,
    timeout_seconds: int = 35
) -> Dict[str, Any]:
    """
    获取二维码扫描状态
    
    参数:
        base_url: API基础URL
        qrcode: 二维码标识
        timeout_seconds: 超时时间（秒）
        
    返回:
        包含扫描状态的字典
    """
    poll_base_url = str(base_url or DEFAULT_BASE_URL).strip().rstrip("/") or DEFAULT_BASE_URL
    return await api_get(
        base_url=poll_base_url,
        endpoint="ilink/bot/get_qrcode_status",
        params={"qrcode": qrcode},
        timeout_seconds=max(1, int(timeout_seconds)),
        extra_headers={"iLink-App-ClientVersion": "1"}
    )
