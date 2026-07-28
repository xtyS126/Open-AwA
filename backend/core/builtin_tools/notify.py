"""
通知推送工具，让 Agent 能主动通过桌面和微信桥接通道向用户发送提醒。

参考 OpenHanako lib/tools/notify-tool.js 和 notification-service.js 设计。

支持通道：
- desktop：通过 WebSocket 向前端推送通知，前端弹出 Toast
- bridge_owner：通过微信自动回复通道向绑定用户发送通知
- auto：自动选择可用通道（优先 desktop）
仅在用户明确要求提醒/通知时使用，普通任务完成不需要调用。
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from loguru import logger

# ── 通道常量 ────────────────────────────────────────────
CHANNEL_DESKTOP = "desktop"
CHANNEL_BRIDGE_OWNER = "bridge_owner"
CHANNEL_AUTO = "auto"
VALID_CHANNELS = {CHANNEL_DESKTOP, CHANNEL_BRIDGE_OWNER, CHANNEL_AUTO}

# ── 上下文策略 ──────────────────────────────────────────
CONTEXT_RECORD_WHEN_DELIVERED = "record_when_delivered"
CONTEXT_NONE = "none"

# ── 通知受众 ────────────────────────────────────────────
AUDIENCE_OWNER = "owner"


def format_notification_text(title: str, body: str) -> str:
    """格式化通知文本为可发送的字符串。
    
    将标题和正文合并为适合微信/桌面展示的文本格式。
    如果两者都有值，用两个换行分隔；否则返回非空的那个。
    
    Args:
        title: 通知标题
        body: 通知正文
    
    Returns:
        格式化后的通知文本字符串，空字符串表示无有效内容
    """
    safe_title = title.strip() if title else ""
    safe_body = body.strip() if body else ""
    if safe_title and safe_body:
        return f"{safe_title}\n\n{safe_body}"
    return safe_body or safe_title


def normalize_channels(raw_channels: Optional[List[str]]) -> List[str]:
    """标准化通知通道列表。
    
    处理规则：
    1. 将 auto 解析为 desktop
    2. 过滤无效通道
    3. 对有效通道去重
    4. 如果最终列表为空，回退到 desktop
    
    Args:
        raw_channels: 原始通道列表，可能包含 None/空/无效值
    
    Returns:
        标准化后的有效通道列表，至少包含一个通道
    """
    if not raw_channels:
        return [CHANNEL_DESKTOP]

    normalized = []
    for ch in raw_channels:
        channel = ch.strip() if isinstance(ch, str) else ""
        if not channel:
            continue
        if channel == CHANNEL_AUTO:
            # auto 自动选择为 desktop
            if CHANNEL_DESKTOP not in normalized:
                normalized.append(CHANNEL_DESKTOP)
            continue
        if channel in VALID_CHANNELS and channel != CHANNEL_AUTO:
            if channel not in normalized:
                normalized.append(channel)

    if not normalized:
        normalized.append(CHANNEL_DESKTOP)

    return normalized


class NotifyTool:
    """通知推送工具。
    
    让 Agent 能主动向用户发送提醒通知。
    通过依赖注入方式接收不同通道的发送回调，保持与现有工具模式一致。
    
    依赖注入（通过构造函数传入）：
    - emit_desktop: 向 desktop 通道发送通知的可调用对象
    - send_bridge_owner: 向 bridge_owner 通道发送通知的可调用对象
    """

    def __init__(
        self,
        emit_desktop: Optional[Callable] = None,
        send_bridge_owner: Optional[Callable] = None,
    ):
        """初始化通知工具。
        
        Args:
            emit_desktop: desktop 通道回调，接收 (title, body, context) 参数
            send_bridge_owner: bridge 通道回调，接收 (text, context) 参数
        """
        self._emit_desktop = emit_desktop
        self._send_bridge_owner = send_bridge_owner
        self._initialized = True
        # 工具元信息，与现有工具模式保持一致
        self.name = "notify"
        self.description = "通知推送工具，支持通过桌面弹窗和微信消息向用户发送提醒"
        self.version = "1.0.0"

    async def initialize(self) -> bool:
        """异步初始化（兼容现有工具接口）。
        
        Returns:
            始终返回 True，因为该工具无异步初始化需求
        """
        return True

    def get_tools(self) -> List[str]:
        """返回工具支持的操作列表。
        
        Returns:
            操作名称列表
        """
        return ["notify"]

    async def execute(self, action: str = "notify", **kwargs: Any) -> Dict[str, Any]:
        """执行通知操作。
        
        支持两种调用方式：
        1. function calling 路径：action="notify", title=..., body=..., channels=...
        2. 旧式兼容路径：通过 manager 调用时传入 action 和参数
        
        Args:
            action: 操作名称，目前仅支持 "notify"
            **kwargs: 通知参数（title, body, channels, audience, agent_id 等）
        
        Returns:
            Dict 包含 success, title, body, channels, deliveries 等字段
        """
        if action == "notify":
            return await self._send_notification(kwargs)
        return {"success": False, "error": f"未知通知操作: {action}"}

    async def _send_notification(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """发送通知到指定通道。
        
        Args:
            params: 通知参数字典
        
        Returns:
            Dict 包含发送结果
        """
        title = params.get("title", "")
        body = params.get("body", "")
        channels_input = params.get("channels")
        audience = params.get("audience", AUDIENCE_OWNER)
        agent_id = params.get("agent_id")

        # ── 参数校验 ──────────────────────────────────────
        if not title and not body:
            return {"success": False, "error": "通知标题和正文不能同时为空"}

        # ── 标准化通道列表 ────────────────────────────────
        if isinstance(channels_input, list):
            channels = normalize_channels(channels_input)
        elif isinstance(channels_input, str) and channels_input:
            channels = normalize_channels([channels_input])
        else:
            channels = normalize_channels(None)

        deliveries = []
        # 构建上下文信息，用于传递给各通道
        context = {}
        if agent_id:
            context["agentId"] = agent_id

        # ── 遍历通道投递通知 ──────────────────────────────
        for channel in channels:
            if channel == CHANNEL_DESKTOP:
                deliveries.append(await self._deliver_desktop(title, body, context))
            elif channel == CHANNEL_BRIDGE_OWNER:
                deliveries.append(
                    await self._deliver_bridge_owner(title, body, audience, context)
                )

        # ── 汇总投递结果 ──────────────────────────────────
        all_sent = len(deliveries) > 0 and all(
            d.get("status") == "sent" for d in deliveries
        )
        failed = [d for d in deliveries if d.get("status") == "failed"]

        if all_sent:
            return {
                "success": True,
                "title": title,
                "body": body,
                "channels": channels,
                "deliveries": deliveries,
                "message": f"通知「{title}」已成功发送",
            }
        elif deliveries:
            fee = failed[0].get("error", "未知错误") if failed else "通知发送失败"
            return {
                "success": False,
                "title": title,
                "body": body,
                "channels": channels,
                "deliveries": deliveries,
                "message": f"通知发送部分失败: {fee}",
            }
        else:
            return {"success": False, "error": "无可用通知通道"}

    async def _deliver_desktop(
        self, title: str, body: str, context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """通过 desktop 通道发送通知。
        
        如果配置了 emit_desktop 回调则调用它，否则仅记录日志
        （适用于回调未注入的开发/测试环境）。
        
        Args:
            title: 通知标题
            body: 通知正文
            context: 上下文信息（agentId 等）
        
        Returns:
            投递结果字典
        """
        try:
            if self._emit_desktop:
                await self._emit_desktop(title=title, body=body, context=context)
            else:
                logger.info(
                    "[通知-desktop] 标题: {title} 正文: {body}",
                    title=title,
                    body=body[:200],
                )
            return {"channel": CHANNEL_DESKTOP, "status": "sent"}
        except Exception as exc:
            logger.bind(module="notify_tool", channel="desktop").exception(
                f"desktop 通知发送失败: {exc}"
            )
            return {"channel": CHANNEL_DESKTOP, "status": "failed", "error": str(exc)}

    async def _deliver_bridge_owner(
        self, title: str, body: str, audience: str, context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """通过 bridge_owner 通道发送通知。
        
        bridge_owner 通道仅支持 audience=owner，
        将通知文本通过微信自动回复通道发送给绑定的用户。
        
        Args:
            title: 通知标题
            body: 通知正文
            audience: 通知受众，必须为 "owner"
            context: 上下文信息（agentId 等）
        
        Returns:
            投递结果字典
        """
        # ── 校验受众类型 ──────────────────────────────────
        if audience != AUDIENCE_OWNER:
            return {
                "channel": CHANNEL_BRIDGE_OWNER,
                "status": "failed",
                "error": f"bridge_owner 通道仅支持 audience=owner，当前为 {audience}",
            }

        # ── 格式化通知文本 ────────────────────────────────
        text = format_notification_text(title, body)
        if not text:
            return {
                "channel": CHANNEL_BRIDGE_OWNER,
                "status": "failed",
                "error": "通知文本为空",
            }

        try:
            if self._send_bridge_owner:
                result = await self._send_bridge_owner(text=text, context=context)
                return {
                    "channel": CHANNEL_BRIDGE_OWNER,
                    "status": "sent" if result else "failed",
                    "detail": result,
                }
            else:
                logger.info(
                    "[通知-bridge] 标题: {title} 正文: {body}",
                    title=title,
                    body=body[:200],
                )
                return {
                    "channel": CHANNEL_BRIDGE_OWNER,
                    "status": "skipped",
                    "error": "bridge_owner 通道未配置",
                }
        except Exception as exc:
            logger.bind(module="notify_tool", channel="bridge_owner").exception(
                f"bridge_owner 通知发送失败: {exc}"
            )
            return {
                "channel": CHANNEL_BRIDGE_OWNER,
                "status": "failed",
                "error": str(exc),
            }
