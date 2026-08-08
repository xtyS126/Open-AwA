"""
图像生成服务：通过已配置的生图模型（SD / GPT-Image / Qwen-Image 系列）生成图片。

模型在设置页被手动标记为"生图模型"（is_image_generation=True）并填写用途/限制描述后，
本服务负责调用其对应协议完成生图：

1. OpenAI 兼容 images/generations（默认协议）：GPT-Image（gpt-image-1）原生支持；
   SD 的 OpenAI 兼容端点（stable-diffusion-api / new-api 等网关）；Qwen-Image 经
   OpenAI 兼容网关接入。
2. DashScope 原生：qwen-image 系列（阿里云百炼原生 multimodal-generation 端点，
   compatible-mode 不提供 images/generations，需走原生接口）。
3. SD WebUI 原生：/sdapi/v1/txt2img。

模型配置与 API Key 复用 PricingManager 凭据体系（provider_credentials 加密存储）。
生成图片统一保存到 {DATA_DIR}/generated 目录，接口返回 base64 + 文件路径。
"""

from __future__ import annotations

import base64
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from uuid import uuid4

import httpx
from loguru import logger
from sqlalchemy.orm import Session

from billing.pricing_manager import PricingManager
from config.runtime_paths import DATA_DIR
from config.security import decrypt_secret_value
from db.models.billing import ModelConfiguration

# 生图输出目录：var/data/generated
IMAGE_OUTPUT_DIR: Path = DATA_DIR / "generated"

# 生图请求超时：SD 等本地生图可能耗时数分钟，统一放宽到 300 秒
_GENERATION_TIMEOUT = httpx.Timeout(300.0)


def _parse_size(size: str) -> Tuple[int, int]:
    """解析图片尺寸字符串（宽x高），非法格式直接报错。"""
    match = re.match(r"^(\d+)x(\d+)$", size.strip())
    if not match:
        raise ValueError(f"无效的图片尺寸: {size}（应为 宽x高，如 1024x1024）")
    return int(match.group(1)), int(match.group(2))


def _detect_protocol(provider: str, endpoint: Optional[str]) -> str:
    """按 provider 名与端点判定生图协议：dashscope / sdwebui / openai。"""
    ep = (endpoint or "").lower()
    provider_lower = provider.lower()
    if "dashscope" in ep or "dashscope" in provider_lower:
        return "dashscope"
    if "sdapi" in ep or "sd" in provider_lower or "stable" in provider_lower:
        return "sdwebui"
    return "openai"


def _normalize_openai_base(endpoint: str) -> str:
    """规范化 OpenAI 兼容基址：剥掉已知 API 后缀，确保以 /v1 结尾。"""
    base = endpoint.strip().rstrip("/")
    for suffix in (
        "/chat/completions",
        "/completions",
        "/images/generations",
        "/v1/images/generations",
        "/embeddings",
    ):
        if base.endswith(suffix):
            base = base[: -len(suffix)]
            break
    base = base.rstrip("/")
    if not base.endswith("/v1"):
        base = f"{base}/v1"
    return base


def _dashscope_native_endpoint(endpoint: Optional[str]) -> str:
    """从配置端点推导 DashScope 原生生图端点（compatible-mode 仅支持 chat/embedding）。"""
    ep = (endpoint or "").strip()
    host_match = re.search(r"(https?://[a-zA-Z0-9.\-]+)", ep)
    host = host_match.group(1).rstrip("/") if host_match else "https://dashscope.aliyuncs.com"
    return f"{host}/api/v1/services/aigc/multimodal-generation/generation"


def _sdwebui_endpoint(endpoint: str) -> str:
    """推导 SD WebUI 原生 txt2img 端点。"""
    base = endpoint.strip().rstrip("/")
    if base.endswith("/sdapi/v1/txt2img"):
        return base
    return f"{base}/sdapi/v1/txt2img"


def list_image_models(db: Session) -> List[Dict[str, Any]]:
    """列出已启用且标记为生图模型的配置（含用途/限制描述），供 UI 与 AI 选型。"""
    configurations = (
        db.query(ModelConfiguration)
        .filter(
            ModelConfiguration.is_image_generation.is_(True),
            ModelConfiguration.is_active.is_(True),
        )
        .order_by(ModelConfiguration.id.asc())
        .all()
    )
    return [
        {
            "id": config.id,
            "provider": config.provider,
            "model": config.model,
            "display_name": config.display_name or config.model,
            "label": f"{config.provider}:{config.model}",
            "usage": config.image_generation_usage or "",
            "api_endpoint": config.api_endpoint,
        }
        for config in configurations
    ]


def _resolve_image_configuration(db: Session, config_id: Optional[int]) -> Dict[str, Any]:
    """解析生图模型配置与解密后的 API Key，失败时显式抛错（不静默降级）。"""
    query = db.query(ModelConfiguration)
    if config_id is not None:
        config = query.filter(ModelConfiguration.id == config_id).first()
        if config is None:
            raise ValueError(f"生图模型配置不存在: config_id={config_id}")
    else:
        config = (
            query.filter(
                ModelConfiguration.is_image_generation.is_(True),
                ModelConfiguration.is_active.is_(True),
            )
            .order_by(ModelConfiguration.id.asc())
            .first()
        )
        if config is None:
            raise ValueError("未找到启用的生图模型，请在模型设置中将模型标记为生图模型")

    if not getattr(config, "is_image_generation", False):
        raise ValueError(f"模型配置 {config.provider}:{config.model} 未标记为生图模型")

    pricing_manager = PricingManager(db)
    # API Key 解析顺序：ModelConfiguration.api_key（legacy，解密）→ ProviderCredential 表
    raw_key = config.api_key or ""
    if raw_key.startswith("enc:"):
        raise ValueError("生图模型 API Key 已失效，请在设置页重新录入")
    api_key = decrypt_secret_value(raw_key) if raw_key else None
    if not api_key:
        credential = pricing_manager.get_provider_credential(
            pricing_manager.normalize_provider(config.provider)
        )
        credential_key = credential.api_key if credential else ""
        if credential_key and credential_key.startswith("enc:"):
            raise ValueError("生图模型 API Key 已失效，请在设置页重新录入")
        api_key = decrypt_secret_value(credential_key) if credential_key else None
        endpoint = config.api_endpoint or (credential.api_endpoint if credential else None)
    else:
        endpoint = config.api_endpoint

    if not api_key:
        raise ValueError("生图模型未配置 API Key，请在模型设置中补充")
    if not endpoint:
        raise ValueError("生图模型未配置 API 端点（api_endpoint），请在模型设置中补充")

    return {
        "id": config.id,
        "provider": config.provider,
        "model": config.model,
        "label": f"{config.provider}:{config.model}",
        "api_key": api_key,
        "endpoint": endpoint,
    }


def _raise_api_error(url: str, response: httpx.Response) -> None:
    """生图接口非 2xx 时抛出带响应明细的错误，禁止静默吞掉。"""
    detail = response.text[:500]
    raise ValueError(f"生图接口请求失败: {url} 状态码 {response.status_code}，响应: {detail}")


def _detect_binary_format(data: bytes) -> str:
    """按二进制魔数识别图片格式（png/jpeg/webp），无法识别时按 png 处理。"""
    if data.startswith(b"\x89PNG"):
        return "png"
    if data.startswith(b"\xff\xd8"):
        return "jpeg"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "webp"
    return "png"


async def _download_image(client: httpx.AsyncClient, url: str) -> bytes:
    """下载生图接口返回的远程图片（GPT-Image URL 有效期 60 分钟、DashScope 24 小时，需即时保存）。"""
    response = await client.get(url)
    if response.status_code >= 400:
        raise ValueError(f"生图结果图片下载失败: {url} 状态码 {response.status_code}")
    return response.content


async def _generate_openai_compat(
    config: Dict[str, Any],
    prompt: str,
    size: str,
    n: int,
    quality: Optional[str],
) -> List[Dict[str, Any]]:
    """OpenAI 兼容 images/generations 协议（GPT-Image / SD 兼容端点 / Qwen-Image 网关）。"""
    url = f"{_normalize_openai_base(config['endpoint'])}/images/generations"
    payload: Dict[str, Any] = {
        "model": config["model"],
        "prompt": prompt,
        "n": n,
        "size": size,
        "response_format": "b64_json",
    }
    if quality:
        payload["quality"] = quality

    async with httpx.AsyncClient(timeout=_GENERATION_TIMEOUT) as client:
        response = await client.post(
            url,
            headers={"Authorization": f"Bearer {config['api_key']}"},
            json=payload,
        )
        if response.status_code >= 400:
            _raise_api_error(url, response)
        data = response.json()

    images: List[Dict[str, Any]] = []
    for item in data.get("data") or []:
        if item.get("b64_json"):
            images.append({"data": base64.b64decode(item["b64_json"])})
        elif item.get("url"):
            async with httpx.AsyncClient(timeout=_GENERATION_TIMEOUT) as client:
                images.append({"data": await _download_image(client, item["url"])})
    if not images:
        raise ValueError("生图接口未返回任何图片数据")
    return images


async def _generate_dashscope(
    config: Dict[str, Any],
    prompt: str,
    size: str,
    n: int,
) -> List[Dict[str, Any]]:
    """DashScope 原生 multimodal-generation（qwen-image 系列，compatible-mode 不提供生图）。"""
    url = _dashscope_native_endpoint(config["endpoint"])
    payload = {
        "model": config["model"],
        "input": {"messages": [{"role": "user", "content": [{"text": prompt}]}]},
        "parameters": {"n": n, "size": size.replace("x", "*"), "prompt_extend": True},
    }

    async with httpx.AsyncClient(timeout=_GENERATION_TIMEOUT) as client:
        response = await client.post(
            url,
            headers={"Authorization": f"Bearer {config['api_key']}"},
            json=payload,
        )
        if response.status_code >= 400:
            _raise_api_error(url, response)
        data = response.json()

    output = data.get("output") or {}
    images: List[Dict[str, Any]] = []
    for choice in output.get("choices") or []:
        content = (choice.get("message") or {}).get("content") or []
        for part in content:
            image_url = part.get("image")
            if image_url:
                async with httpx.AsyncClient(timeout=_GENERATION_TIMEOUT) as client:
                    images.append({"data": await _download_image(client, image_url)})
    if not images:
        raise ValueError(f"DashScope 生图未返回结果: {str(data)[:500]}")
    return images


async def _generate_sdwebui(
    config: Dict[str, Any],
    prompt: str,
    width: int,
    height: int,
    n: int,
) -> List[Dict[str, Any]]:
    """SD WebUI 原生 txt2img（/sdapi/v1/txt2img）。"""
    url = _sdwebui_endpoint(config["endpoint"])
    payload = {
        "prompt": prompt,
        "negative_prompt": "",
        "width": width,
        "height": height,
        "steps": 20,
        "batch_size": n,
    }

    async with httpx.AsyncClient(timeout=_GENERATION_TIMEOUT) as client:
        response = await client.post(
            url,
            headers={"Authorization": f"Bearer {config['api_key']}"},
            json=payload,
        )
        if response.status_code >= 400:
            _raise_api_error(url, response)
        data = response.json()

    raw_images = data.get("images") or []
    if not raw_images:
        raise ValueError("SD WebUI 未返回任何图片数据")
    return [{"data": base64.b64decode(item)} for item in raw_images]


def _save_images(images: List[Dict[str, Any]], label: str) -> List[Dict[str, Any]]:
    """将生图结果保存到 var/data/generated 并返回带文件路径与格式的结果列表。"""
    IMAGE_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    saved: List[Dict[str, Any]] = []
    timestamp = int(time.time())
    for index, image in enumerate(images):
        data = image["data"]
        image_format = _detect_binary_format(data)
        file_name = f"image_{timestamp}_{uuid4().hex[:8]}_{index}.{image_format}"
        file_path = IMAGE_OUTPUT_DIR / file_name
        file_path.write_bytes(data)
        saved.append(
            {
                "b64_json": base64.b64encode(data).decode("ascii"),
                "format": image_format,
                "file_path": str(file_path),
                "bytes": len(data),
            }
        )
        logger.bind(
            event="image_generated",
            module="image_generation",
            model=label,
            file=file_name,
            bytes=len(data),
        ).info(f"生图完成: {label} → {file_name} ({len(data)} bytes)")
    return saved


async def generate_image(
    db: Session,
    prompt: str,
    config_id: Optional[int] = None,
    size: str = "1024x1024",
    n: int = 1,
    quality: Optional[str] = None,
) -> Dict[str, Any]:
    """
    按模型配置的协议族生图，统一返回图片 base64 与保存路径。

    Args:
        db: 数据库会话
        prompt: 生图提示词
        config_id: 生图模型配置 ID（缺省时自动选择第一个启用的生图模型）
        size: 图片尺寸（宽x高，如 1024x1024）
        n: 生成数量（SD 支持多张；GPT-Image 固定 1 张）
        quality: 质量参数（仅 OpenAI 兼容协议支持，如 high）

    Returns:
        {"ok": True, "model": {provider, model, label}, "size": ..., "n": ...,
         "images": [{"b64_json", "format", "file_path", "bytes"}]}
    """
    prompt = prompt.strip()
    if not prompt:
        raise ValueError("生图提示词不能为空")
    width, height = _parse_size(size)
    if n < 1 or n > 6:
        raise ValueError("生成数量 n 必须在 1 到 6 之间")

    config = _resolve_image_configuration(db, config_id)
    protocol = _detect_protocol(config["provider"], config["endpoint"])
    logger.bind(
        event="image_generation_started",
        module="image_generation",
        model=config["label"],
        protocol=protocol,
        size=size,
    ).info(f"开始生图: {config['label']}（协议 {protocol}，尺寸 {size}）")

    if protocol == "dashscope":
        images = await _generate_dashscope(config, prompt, size, n)
    elif protocol == "sdwebui":
        images = await _generate_sdwebui(config, prompt, width, height, n)
    else:
        images = await _generate_openai_compat(config, prompt, size, n, quality)

    saved_images = _save_images(images, config["label"])
    return {
        "ok": True,
        "model": {
            "id": config["id"],
            "provider": config["provider"],
            "model": config["model"],
            "label": config["label"],
        },
        "protocol": protocol,
        "size": size,
        "n": len(saved_images),
        "images": saved_images,
    }
