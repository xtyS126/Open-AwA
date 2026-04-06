"""
微信技能适配器主类
提供统一的微信消息处理接口
"""

from __future__ import annotations

import os
import time
from typing import Any, Dict, List, Optional

from loguru import logger

from backend.skills.weixin.config import (
    WeixinRuntimeConfig,
    DEFAULT_BASE_URL,
    DEFAULT_QR_BASE_URL,
    DEFAULT_BOT_TYPE,
    DEFAULT_CHANNEL_VERSION,
)
from backend.skills.weixin.errors import WeixinAdapterError
from backend.skills.weixin.api.client import (
    api_post,
    api_get,
    fetch_login_qrcode,
    fetch_qrcode_status,
)
from backend.skills.weixin.messaging.inbound import extract_context_tokens
from backend.skills.weixin.messaging.outbound import (
    send_text_message,
    send_message_with_cached_token,
    validate_send_message_params,
)
from backend.skills.weixin.messaging.process import (
    poll_updates,
    check_session_active,
    build_success_result,
    build_error_result,
)
from backend.skills.weixin.storage.state import StateManager
from backend.skills.weixin.utils.helpers import (
    pick_value,
    normalize_binding_status,
)


class WeixinSkillAdapter:
    """
    微信技能适配器类
    封装微信消息处理的核心逻辑，提供统一的接口
    
    该类负责：
    - 配置映射和验证
    - 健康检查
    - 消息发送和接收
    - 登录二维码管理
    - 状态持久化
    """
    
    def __init__(self, project_root: Optional[str] = None):
        """
        初始化适配器
        
        参数:
            project_root: 项目根目录，可选，默认自动推断
        """
        resolved_root = project_root or os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
        self.project_root = resolved_root
        self.state_root = os.path.join(resolved_root, ".openawa", "weixin")
        self._state_manager: Optional[StateManager] = None

    @property
    def state_manager(self) -> StateManager:
        """
        获取状态管理器实例（懒加载）
        
        返回:
            StateManager实例
        """
        if self._state_manager is None:
            self._state_manager = StateManager(self.state_root)
        return self._state_manager

    def is_weixin_skill(self, skill_config: Dict[str, Any]) -> bool:
        """
        判断是否为微信技能配置
        
        参数:
            skill_config: 技能配置字典
            
        返回:
            如果是微信技能则返回True，否则返回False
        """
        adapter = str(skill_config.get("adapter", "")).strip().lower()
        skill_type = str(skill_config.get("type", "")).strip().lower()
        runtime_adapter = str(skill_config.get("runtime", {}).get("adapter", "")).strip().lower()
        candidates = {adapter, skill_type, runtime_adapter}
        return "weixin" in candidates or "openclaw-weixin" in candidates

    def map_skill_config(self, skill_config: Dict[str, Any]) -> WeixinRuntimeConfig:
        """
        将技能配置映射为运行时配置
        
        参数:
            skill_config: 技能配置字典
            
        返回:
            WeixinRuntimeConfig实例
        """
        section = skill_config.get("weixin")
        if not isinstance(section, dict):
            section = {}
        runtime = skill_config.get("runtime")
        if not isinstance(runtime, dict):
            runtime = {}

        account_id = pick_value(section, runtime, "account_id", "accountId")
        token = pick_value(section, runtime, "token")
        base_url = pick_value(section, runtime, "base_url", "baseUrl") or DEFAULT_BASE_URL
        bot_type = str(pick_value(section, runtime, "bot_type", "botType") or DEFAULT_BOT_TYPE)
        channel_version = str(pick_value(section, runtime, "channel_version", "channelVersion") or DEFAULT_CHANNEL_VERSION)
        timeout_raw = pick_value(section, runtime, "timeout_seconds", "timeoutSeconds")
        user_id = pick_value(section, runtime, "user_id", "userId")
        binding_status_raw = pick_value(section, runtime, "binding_status", "bindingStatus")

        try:
            timeout_seconds = int(timeout_raw) if timeout_raw is not None else 15
        except (TypeError, ValueError):
            timeout_seconds = 15
        timeout_seconds = max(5, timeout_seconds)

        normalized_user_id = str(user_id or "").strip()
        normalized_binding_status = normalize_binding_status(binding_status_raw, normalized_user_id)

        return WeixinRuntimeConfig(
            account_id=str(account_id or "").strip(),
            token=str(token or "").strip(),
            base_url=str(base_url).strip().rstrip("/"),
            bot_type=bot_type,
            channel_version=channel_version,
            timeout_seconds=timeout_seconds,
            user_id=normalized_user_id,
            binding_status=normalized_binding_status
        )

    def check_health(self, config: WeixinRuntimeConfig) -> Dict[str, Any]:
        """
        检查健康状态
        
        参数:
            config: 运行时配置
            
        返回:
            包含健康检查结果的字典
        """
        issues: List[str] = []
        suggestions: List[str] = []

        if not config.account_id:
            issues.append("account_id 为空")
            suggestions.append("配置有效的 account_id")
        if not config.token:
            issues.append("token 为空")
            suggestions.append("配置有效的 bot token")
        if not config.base_url or not config.base_url.startswith(("http://", "https://")):
            issues.append("base_url 格式无效")
            suggestions.append("配置有效的 base_url，如 https://ilinkai.weixin.qq.com")

        return {
            "ok": len(issues) == 0,
            "issues": issues,
            "suggestions": suggestions,
            "diagnostics": {
                "base_url": config.base_url,
                "account_id": config.account_id,
                "session_paused": self.state_manager.is_session_paused(config.account_id),
                "user_id": config.user_id,
                "binding_status": config.binding_status,
                "binding_ready": self._is_binding_ready(config),
            }
        }

    async def execute(
        self,
        skill_name: str,
        skill_config: Dict[str, Any],
        inputs: Dict[str, Any],
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        执行技能操作
        
        参数:
            skill_name: 技能名称
            skill_config: 技能配置
            inputs: 输入参数
            context: 执行上下文
            
        返回:
            执行结果字典
        """
        started = time.time()
        runtime = self.map_skill_config(skill_config)
        action = str(inputs.get("action") or inputs.get("operation") or "health_check").strip().lower()
        payload = self._normalize_payload(inputs)

        try:
            health = self.check_health(runtime)
            if not health["ok"]:
                raise WeixinAdapterError.dependency_missing(
                    issues=health["issues"],
                    diagnostics=health["diagnostics"]
                )

            if action in {"health_check", "check_health"}:
                return build_success_result(
                    action="check_health",
                    started=started,
                    config=runtime,
                    data={"health": health},
                    state_manager=self.state_manager
                )

            missing_fields = self._validate_runtime_fields(runtime, required=["account_id", "token"])
            if missing_fields:
                raise WeixinAdapterError.config_missing_fields(missing_fields)

            check_session_active(self.state_manager, runtime.account_id)

            if action in {"send_message", "send_text"}:
                result = await self._send_message(runtime, payload)
                normalized_action = "send_text"
            elif action in {"get_updates", "poll"}:
                result = await self._get_updates(runtime, payload)
                normalized_action = "poll"
            else:
                raise WeixinAdapterError.unsupported_action(action)

            action = normalized_action

            return build_success_result(
                action=action,
                started=started,
                config=runtime,
                data=result,
                state_manager=self.state_manager
            )
        except WeixinAdapterError as exc:
            logger.warning(f"Weixin adapter execution failed for skill={skill_name}, action={action}, code={exc.code}")
            return build_error_result(
                action=action,
                started=started,
                config=runtime,
                error=exc
            )
        except Exception as exc:
            logger.error(f"Weixin adapter unexpected error for skill={skill_name}, action={action}: {exc}")
            wrapped = WeixinAdapterError.internal_error(
                exception_type=type(exc).__name__,
                error=str(exc)
            )
            return build_error_result(
                action=action,
                started=started,
                config=runtime,
                error=wrapped
            )

    async def _send_message(self, config: WeixinRuntimeConfig, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        发送消息内部方法
        
        参数:
            config: 运行时配置
            payload: 消息参数
            
        返回:
            发送结果字典
        """
        import uuid
        
        to_user_id = str(
            payload.get("to_user_id")
            or payload.get("toUserId")
            or payload.get("user_id")
            or payload.get("userId")
            or ""
        ).strip()
        text = str(payload.get("text") or payload.get("content") or "").strip()
        context_token = str(payload.get("context_token") or payload.get("contextToken") or "").strip()
        client_id = str(payload.get("client_id") or payload.get("clientId") or f"ilink-{uuid.uuid4().hex[:8]}")

        if not context_token and to_user_id and config.account_id:
            context_token = self.state_manager.get_context_token(config.account_id, to_user_id)

        missing = []
        if not to_user_id:
            missing.append("to_user_id")
        if not text:
            missing.append("text")
        if not context_token:
            missing.append("context_token")
        if missing:
            raise WeixinAdapterError.input_missing_fields(missing)

        token_from_cache = not payload.get("context_token") and not payload.get("contextToken")
        return await send_message_with_cached_token(
            config=config,
            to_user_id=to_user_id,
            text=text,
            context_token=context_token,
            client_id=client_id,
            token_from_cache=token_from_cache
        )

    async def _get_updates(self, config: WeixinRuntimeConfig, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        获取更新内部方法
        
        参数:
            config: 运行时配置
            payload: 请求参数
            
        返回:
            更新结果字典
        """
        incoming_buf = str(
            payload.get("get_updates_buf")
            or payload.get("getUpdatesBuf")
            or payload.get("cursor")
            or ""
        ).strip()
        
        return await poll_updates(config, self.state_manager, incoming_buf)

    async def fetch_login_qrcode(
        self,
        base_url: str,
        bot_type: str = DEFAULT_BOT_TYPE,
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
        return await fetch_login_qrcode(
            base_url=DEFAULT_QR_BASE_URL,
            bot_type=bot_type,
            timeout_seconds=timeout_seconds
        )

    async def fetch_qrcode_status(
        self,
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
        return await fetch_qrcode_status(
            base_url=base_url,
            qrcode=qrcode,
            timeout_seconds=timeout_seconds
        )

    def _normalize_payload(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """
        规范化输入参数
        
        参数:
            inputs: 原始输入参数
            
        返回:
            规范化后的参数字典
        """
        payload = inputs.get("payload")
        if not isinstance(payload, dict):
            payload = {}
        merged = dict(payload)
        for key, value in inputs.items():
            if key in {"action", "operation", "payload"}:
                continue
            merged[key] = value
        return merged

    def _validate_runtime_fields(self, config: WeixinRuntimeConfig, required: List[str]) -> List[str]:
        """
        验证运行时配置字段
        
        参数:
            config: 运行时配置
            required: 必需字段列表
            
        返回:
            缺失字段列表
        """
        missing: List[str] = []
        for field in required:
            value = getattr(config, field, "")
            if not isinstance(value, str) or not value.strip():
                missing.append(field)
        return missing

    def _is_binding_ready(self, config: WeixinRuntimeConfig) -> bool:
        """
        检查绑定是否就绪
        
        参数:
            config: 运行时配置
            
        返回:
            如果绑定就绪则返回True，否则返回False
        """
        return normalize_binding_status(config.binding_status, config.user_id) == "bound"
