"""
IM 渠道管理 API，提供渠道配置、状态查询和消息发送接口。
"""

from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException
from loguru import logger
from pydantic import BaseModel, Field

from api.dependencies import get_current_user, get_db

router = APIRouter(prefix="/im", tags=["im"])


class ChannelConfigRequest(BaseModel):
    """渠道配置请求。"""
    channel: str = Field(..., description="渠道名称: telegram | feishu | dingtalk")
    enabled: bool = Field(default=False, description="是否启用")
    bot_token: str = Field(default="", description="Bot Token (Telegram)")
    app_id: str = Field(default="", description="App ID (飞书/钉钉)")
    app_secret: str = Field(default="", description="App Secret (飞书/钉钉)")
    webhook_url: str = Field(default="", description="Webhook URL")
    extra: Dict[str, Any] = Field(default=dict, description="额外配置")


class SendMessageRequest(BaseModel):
    """发送消息请求。"""
    channel: str = Field(..., description="渠道名称")
    chat_id: str = Field(..., description="目标会话 ID")
    text: str = Field(..., max_length=4000, description="消息内容")


# 渠道配置存储（简化版，实际应持久化到数据库）
_channel_configs: Dict[str, ChannelConfigRequest] = {}


@router.get("/channels")
async def list_channels(
    current_user: Dict = Depends(get_current_user),
):
    """列出所有渠道及其状态。"""
    channels = []
    for channel_name in ["telegram", "feishu", "dingtalk"]:
        config = _channel_configs.get(channel_name)
        channels.append({
            "channel": channel_name,
            "enabled": config.enabled if config else False,
            "configured": bool(config and (config.bot_token or config.app_id)),
        })
    return {"channels": channels}


@router.put("/channels/{channel}")
async def update_channel_config(
    channel: str,
    config: ChannelConfigRequest,
    current_user: Dict = Depends(get_current_user),
):
    """更新渠道配置。"""
    if channel not in ["telegram", "feishu", "dingtalk"]:
        raise HTTPException(status_code=400, detail="不支持的渠道")

    config.channel = channel
    _channel_configs[channel] = config

    logger.bind(
        event="im_channel_configured",
        module="im_api",
        channel=channel,
        enabled=config.enabled,
    ).info(f"渠道配置已更新: {channel}")

    return {"ok": True, "channel": channel, "enabled": config.enabled}


@router.post("/send")
async def send_message(
    request: SendMessageRequest,
    current_user: Dict = Depends(get_current_user),
):
    """通过指定渠道发送消息。"""
    from im.router import message_router

    adapter = message_router.get_adapter(request.channel)
    if not adapter:
        return {"ok": False, "error": f"渠道 {request.channel} 未注册或未启动"}

    success = await adapter.send_message(request.chat_id, request.text)
    return {"ok": success}


@router.get("/status")
async def get_status(
    current_user: Dict = Depends(get_current_user),
):
    """获取 IM 网关整体状态。"""
    from im.router import message_router

    channels = message_router.get_registered_channels()
    return {
        "running": len(channels) > 0,
        "channels": channels,
        "configs": {
            ch: {
                "enabled": _channel_configs[ch].enabled if ch in _channel_configs else False,
            }
            for ch in ["telegram", "feishu", "dingtalk"]
        },
    }
