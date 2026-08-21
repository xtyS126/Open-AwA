"""SD WebUI (AUTOMATIC1111) 协议兼容层：让酒馆AI等外部客户端直连 Open-AwA 生图。

酒馆AI（SillyTavern）的图像生成扩展支持 "Stable Diffusion Web UI (AUTOMATIC1111)"
后端类型，通过 /sdapi/v1/* 协议与生图后端通信。本模块在 Open-AwA 上实现该协议的
服务端，把 txt2img 请求转发给已配置的生图模型（OpenAI 兼容 / DashScope / SD WebUI
三种协议族，复用 core/image_generation.py）。

酒馆AI 侧配置（扩展 -> 图像生成 -> API 连接）：
- API 类型: Stable Diffusion Web UI (AUTOMATIC1111)
- API URL: http://<Open-AwA 后端地址>:8000
- 认证 (可选): 任意用户名:OPENAWA_API_KEY（HTTP Basic，冒号后为 API Key）

协议端点与 AUTOMATIC1111 对齐：
- GET  /sdapi/v1/options          连通性检测 + 当前模型（sd_model_checkpoint）
- POST /sdapi/v1/options          切换模型（sd_model_checkpoint），随后客户端轮询 progress
- GET  /sdapi/v1/progress         生成进度（本层即时返回空闲态）
- POST /sdapi/v1/interrupt        中断生成（本层为空操作，兼容客户端断开时的调用）
- GET  /sdapi/v1/sd-models        生图模型列表（映射 ModelConfiguration 中标记生图的配置）
- GET  /sdapi/v1/samplers         采样器列表（静态，非 SD 上游忽略）
- GET  /sdapi/v1/schedulers       调度器列表（静态）
- GET  /sdapi/v1/sd-vae           VAE 列表（静态，返回 Automatic 占位）
- GET  /sdapi/v1/upscalers        放大器列表（静态）
- GET  /sdapi/v1/latent-upscale-modes 潜空间放大模式列表（静态）
- POST /sdapi/v1/txt2img          文生图核心端点

认证方式（与酒馆AI的 HTTP Basic 对接）：
- Authorization: Basic base64("用户名:OPENAWA_API_KEY")，冒号后为 API Key
- 或 Authorization: Bearer OPENAWA_API_KEY
"""

from __future__ import annotations

import base64
import binascii
import json
import secrets
import threading
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from loguru import logger
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from api.dependencies import get_db
from config.settings import settings
from core.image_generation import generate_image, list_image_models

router = APIRouter(prefix="/sdapi/v1", tags=["sdwebui-compat"])

# ---------------------------------------------------------------------------
# 当前选中模型（进程内存态，与 A1111 options 语义一致；重启后回退第一个生图模型）
# ---------------------------------------------------------------------------

_selection_lock = threading.Lock()
_selected_title: Optional[str] = None

# 静态采样器/调度器/VAE/放大器列表：填充酒馆AI设置面板用。
# 非 SD WebUI 上游（OpenAI 兼容 / DashScope）不消费这些参数，仅展示。
_SAMPLERS: List[Dict[str, Any]] = [
    {"name": name, "aliases": [], "options": {}}
    for name in (
        "Euler a", "Euler", "LMS", "Heun", "DPM2", "DPM2 a", "DPM++ 2S a",
        "DPM++ 2M", "DPM++ SDE", "DPM++ 2M SDE", "DDIM", "PLMS", "UniPC",
    )
]
_SCHEDULERS: List[Dict[str, Any]] = [
    {"name": name} for name in ("normal", "karras", "exponential", "sgm_uniform", "simple", "beta")
]
_VAES: List[Dict[str, Any]] = [{"model_name": "Automatic"}]
_UPSCALERS: List[Dict[str, Any]] = [
    {"name": name} for name in ("None", "Lanczos", "Nearest", "ESRGAN_4x", "R-ESRGAN 4x+", "R-ESRGAN 4x+ Anime6B")
]
_LATENT_UPSCALE_MODES: List[Dict[str, Any]] = [
    {"name": name}
    for name in ("Latent", "Latent (antialiased)", "Latent (nearest)", "Latent (nearest-exact)", "Latent (bisexual)")
]


# ---------------------------------------------------------------------------
# 认证
# ---------------------------------------------------------------------------


def _verify_compat_auth(request: Request) -> None:
    """校验兼容层请求的认证头。

    支持两种形式：
    1. Authorization: Basic base64("任意用户名:OPENAWA_API_KEY") —— 酒馆AI 标准形式
    2. Authorization: Bearer OPENAWA_API_KEY —— 通用形式

    认证失败统一抛 401，不区分"缺少头"与"密钥错误"以减少信息泄露。
    """
    api_key = settings.OPENAWA_API_KEY.get_secret_value()
    header = request.headers.get("authorization") or ""
    auth_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="SD WebUI 兼容层认证失败：请在酒馆AI认证栏填写 任意用户名:OpenAwA的API_KEY",
        headers={"WWW-Authenticate": "Basic"},
    )
    if not api_key:
        raise auth_exception

    if header.startswith("Basic "):
        try:
            decoded = base64.b64decode(header[len("Basic "):].strip()).decode("utf-8")
        except (binascii.Error, UnicodeDecodeError, ValueError):
            raise auth_exception
        # "用户名:密码" 形式取冒号后为候选 key；无冒号时整串视为 key
        candidate = decoded.split(":", 1)[1] if ":" in decoded else decoded
        if secrets.compare_digest(candidate, api_key):
            return
    elif header.startswith("Bearer "):
        if secrets.compare_digest(header[len("Bearer "):].strip(), api_key):
            return

    raise auth_exception


# ---------------------------------------------------------------------------
# 模型目录与选中状态
# ---------------------------------------------------------------------------


def _build_model_entries(db: Session) -> List[Dict[str, Any]]:
    """构造 sd-models 响应条目：title 唯一（label 重复时追加配置 ID）。"""
    models = list_image_models(db)
    entries: List[Dict[str, Any]] = []
    seen_titles: set[str] = set()
    for item in models:
        title = item["label"]
        if title in seen_titles:
            title = f"{title} #{item['id']}"
        seen_titles.add(title)
        entries.append(
            {
                "title": title,
                "model_name": item["model"],
                "hash": None,
                "sha256": None,
                "filename": item["model"],
                "config": None,
                # 内部字段：txt2img 时按 title 反查 config_id
                "_config_id": item["id"],
            }
        )
    return entries


def _current_model(db: Session) -> Optional[Dict[str, Any]]:
    """返回当前选中的模型条目（选中项失效时回退第一个；无生图模型返回 None）。"""
    entries = _build_model_entries(db)
    if not entries:
        return None
    with _selection_lock:
        selected = _selected_title
    if selected:
        for entry in entries:
            if entry["title"] == selected:
                return entry
    return entries[0]


# ---------------------------------------------------------------------------
# 协议端点
# ---------------------------------------------------------------------------


@router.get("/options")
def get_options(
    _auth: None = Depends(_verify_compat_auth),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """当前配置（酒馆AI ping 连通性检测与 get-model 均消费本端点）。"""
    current = _current_model(db)
    return {
        "sd_model_checkpoint": current["title"] if current else "",
        # 不返回 forge_preset 字段：酒馆AI据此判定是否为 Forge 分支并改写 payload
    }


class OptionsUpdateRequest(BaseModel):
    """酒馆AI set-model 提交的 options 更新体。"""

    model_config = ConfigDict(extra="ignore")

    sd_model_checkpoint: Optional[str] = None


@router.post("/options")
def set_options(
    payload: OptionsUpdateRequest,
    _auth: None = Depends(_verify_compat_auth),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """切换当前生图模型（酒馆AI set-model 调用后轮询 progress 等待加载完成）。"""
    if not payload.sd_model_checkpoint:
        raise HTTPException(status_code=400, detail="缺少 sd_model_checkpoint 字段")
    entries = _build_model_entries(db)
    matched = next((e for e in entries if e["title"] == payload.sd_model_checkpoint), None)
    if matched is None:
        raise HTTPException(status_code=400, detail=f"未知的生图模型: {payload.sd_model_checkpoint}")
    global _selected_title
    with _selection_lock:
        _selected_title = matched["title"]
    logger.bind(
        event="sdwebui_compat_model_selected",
        module="sdwebui_compat",
        model=matched["title"],
    ).info(f"酒馆AI兼容层切换生图模型: {matched['title']}")
    return {"ok": True}


@router.get("/progress")
def get_progress(_auth: None = Depends(_verify_compat_auth)) -> Dict[str, Any]:
    """生成进度：本层无排队概念，恒返回空闲态（progress=0 且 job_count=0）。"""
    return {
        "progress": 0,
        "eta_relative": 0,
        "state": {
            "skipped": False,
            "interrupted": False,
            "job": "",
            "job_count": 0,
            "job_timestamp": "",
            "sampling_step": 0,
            "sample_steps": 0,
        },
        "current_image": None,
        "textinfo": None,
    }


@router.post("/interrupt")
@router.get("/interrupt")
def interrupt(_auth: None = Depends(_verify_compat_auth)) -> Dict[str, Any]:
    """中断生成：酒馆AI客户端断开时会调用，本层无任务队列，返回空操作。"""
    return {"interrupted": True}


@router.get("/sd-models")
def list_models(
    _auth: None = Depends(_verify_compat_auth),
    db: Session = Depends(get_db),
) -> List[Dict[str, Any]]:
    """生图模型列表（映射模型设置页中标记为生图模型的配置）。"""
    entries = _build_model_entries(db)
    # 剔除内部字段后再返回，保持 A1111 响应形状
    return [
        {k: v for k, v in entry.items() if not k.startswith("_")} for entry in entries
    ]


@router.get("/samplers")
def list_samplers(_auth: None = Depends(_verify_compat_auth)) -> List[Dict[str, Any]]:
    """采样器列表（静态；非 SD 上游不消费采样参数）。"""
    return _SAMPLERS


@router.get("/schedulers")
def list_schedulers(_auth: None = Depends(_verify_compat_auth)) -> List[Dict[str, Any]]:
    """调度器列表（静态）。"""
    return _SCHEDULERS


@router.get("/sd-vae")
@router.get("/sd-modules")
def list_vaes(_auth: None = Depends(_verify_compat_auth)) -> List[Dict[str, Any]]:
    """VAE 列表（静态占位；sd-modules 为 Forge 兼容别名）。"""
    return _VAES


@router.get("/upscalers")
def list_upscalers(_auth: None = Depends(_verify_compat_auth)) -> List[Dict[str, Any]]:
    """放大器列表（静态；高清修复相关，上游不支持时酒馆AI侧不生效）。"""
    return _UPSCALERS


@router.get("/latent-upscale-modes")
def list_latent_upscale_modes(
    _auth: None = Depends(_verify_compat_auth),
) -> List[Dict[str, Any]]:
    """潜空间放大模式列表（静态）。"""
    return _LATENT_UPSCALE_MODES


# ---------------------------------------------------------------------------
# 文生图核心端点
# ---------------------------------------------------------------------------


class Txt2ImgRequest(BaseModel):
    """酒馆AI txt2img 请求体（忽略 url / auth / override_settings 等额外字段）。

    字段与 AUTOMATIC1111 /sdapi/v1/txt2img 对齐；酒馆AI转发时会把代理用的
    url / auth 字段一并带入 body，通过 extra="ignore" 忽略。
    """

    model_config = ConfigDict(extra="ignore")

    prompt: str = ""
    negative_prompt: str = ""
    steps: int = 20
    cfg_scale: float = 7.0
    width: int = 512
    height: int = 512
    sampler_name: Optional[str] = None
    scheduler: Optional[str] = None
    seed: int = -1
    n_iter: int = 1
    batch_size: int = 1
    restore_faces: bool = False
    enable_hr: bool = False


@router.post("/txt2img")
async def txt2img(
    payload: Txt2ImgRequest,
    request: Request,
    _auth: None = Depends(_verify_compat_auth),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """文生图：转发给当前选中的生图模型，返回 A1111 形状响应。"""
    prompt = payload.prompt.strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="生图提示词不能为空")

    current = _current_model(db)
    if current is None:
        raise HTTPException(
            status_code=400,
            detail="未找到启用的生图模型，请在 Open-AwA 模型设置中将模型标记为生图模型",
        )

    # A1111 语义：总张数 = 批次数 n_iter * 每批张数 batch_size，限制在核心支持的 1-6
    total = max(1, payload.n_iter * payload.batch_size)
    if total > 6:
        logger.bind(
            event="sdwebui_compat_n_clamped",
            module="sdwebui_compat",
            requested=total,
        ).warning(f"酒馆AI请求 {total} 张超出上限，按 6 张生成")
        total = 6

    client_host = request.client.host if request.client else "unknown"
    size = f"{payload.width}x{payload.height}"
    logger.bind(
        event="sdwebui_compat_txt2img",
        module="sdwebui_compat",
        model=current["title"],
        size=size,
        client=client_host,
    ).info(f"酒馆AI生图请求: {current['title']} 尺寸 {size}")

    try:
        result = await generate_image(
            db=db,
            prompt=prompt,
            config_id=current["_config_id"],
            size=size,
            n=total,
            negative_prompt=payload.negative_prompt or None,
            generation_params={
                "steps": payload.steps,
                "cfg_scale": payload.cfg_scale,
                "sampler_name": payload.sampler_name,
                "scheduler": payload.scheduler,
                "seed": payload.seed,
            },
        )
    except ValueError as exc:
        # 配置缺失 / 参数非法 / 上游业务错误（_raise_api_error 抛 ValueError）
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        # 网络等未预期异常按网关错误返回，不静默吞
        logger.bind(
            event="sdwebui_compat_txt2img_failed",
            module="sdwebui_compat",
            model=current["title"],
        ).error("酒馆AI生图请求失败", exc_info=exc)
        raise HTTPException(status_code=502, detail=f"生图失败: {exc}") from exc

    images = [img["b64_json"] for img in result.get("images", [])]
    info = json.dumps(
        {
            "infotexts": [f"{result['model']['label']} | {size}"],
            "model": result["model"]["label"],
            "seed": payload.seed,
            "width": payload.width,
            "height": payload.height,
        },
        ensure_ascii=False,
    )
    return {
        "images": images,
        "info": info,
        "parameters": payload.model_dump(),
    }
