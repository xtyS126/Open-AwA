"""
微信适配器错误类模块
定义统一的错误处理机制
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


class WeixinAdapterError(Exception):
    """
    微信适配器错误类
    封装错误码、消息、详情和建议信息
    
    属性:
        code: 错误码
        message: 错误消息
        details: 错误详情字典
        suggestions: 建议列表
    """
    
    def __init__(
        self,
        code: str,
        message: str,
        details: Optional[Dict[str, Any]] = None,
        suggestions: Optional[List[str]] = None
    ):
        """
        初始化错误实例
        
        参数:
            code: 错误码，用于标识错误类型
            message: 错误消息，描述错误内容
            details: 错误详情，包含额外的上下文信息
            suggestions: 建议列表，提供解决错误的建议
        """
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}
        self.suggestions = suggestions or []

    def to_dict(self) -> Dict[str, Any]:
        """
        将错误转换为字典格式
        
        返回:
            包含错误码、消息、详情和建议的字典
        """
        return {
            "code": self.code,
            "message": self.message,
            "details": self.details,
            "suggestions": self.suggestions
        }

    @classmethod
    def dependency_missing(cls, issues: List[str], diagnostics: Dict[str, Any]) -> WeixinAdapterError:
        """
        创建依赖缺失错误
        
        参数:
            issues: 问题列表
            diagnostics: 诊断信息
            
        返回:
            WeixinAdapterError实例
        """
        return cls(
            code="WEIXIN_DEPENDENCY_MISSING",
            message="weixin 运行环境校验失败",
            details={"issues": issues, "diagnostics": diagnostics},
            suggestions=["检查配置文件中的weixin相关字段"]
        )

    @classmethod
    def config_missing_fields(cls, missing_fields: List[str]) -> WeixinAdapterError:
        """
        创建配置字段缺失错误
        
        参数:
            missing_fields: 缺失字段列表
            
        返回:
            WeixinAdapterError实例
        """
        return cls(
            code="WEIXIN_CONFIG_MISSING_FIELDS",
            message="weixin skill 配置不完整",
            details={"missing_fields": missing_fields},
            suggestions=["补齐 weixin.account_id 与 weixin.token 配置字段"]
        )

    @classmethod
    def unsupported_action(cls, action: str) -> WeixinAdapterError:
        """
        创建不支持操作错误
        
        参数:
            action: 不支持的操作名
            
        返回:
            WeixinAdapterError实例
        """
        return cls(
            code="WEIXIN_UNSUPPORTED_ACTION",
            message=f"不支持的 weixin 操作: {action}",
            details={"supported_actions": ["check_health", "send_text", "poll"]},
            suggestions=["将 inputs.action 设置为 check_health、send_text 或 poll"]
        )

    @classmethod
    def input_missing_fields(cls, missing_fields: List[str]) -> WeixinAdapterError:
        """
        创建输入参数缺失错误
        
        参数:
            missing_fields: 缺失字段列表
            
        返回:
            WeixinAdapterError实例
        """
        return cls(
            code="WEIXIN_INPUT_MISSING_FIELDS",
            message="发送消息参数不完整",
            details={"missing_fields": missing_fields},
            suggestions=["在 inputs.payload 中提供 to_user_id、text、context_token，或先执行 get_updates 建立上下文缓存"]
        )

    @classmethod
    def upstream_http_error(cls, endpoint: str, status_code: int, response_text: str) -> WeixinAdapterError:
        """
        创建上游HTTP错误
        
        参数:
            endpoint: API端点
            status_code: HTTP状态码
            response_text: 响应文本
            
        返回:
            WeixinAdapterError实例
        """
        return cls(
            code="WEIXIN_UPSTREAM_HTTP_ERROR",
            message=f"上游请求失败: HTTP {status_code}",
            details={"endpoint": endpoint, "status_code": status_code, "response_text": response_text[:500]},
            suggestions=["检查 token 是否有效、base_url 是否正确，或稍后重试"]
        )

    @classmethod
    def timeout(cls, endpoint: str, timeout_seconds: int) -> WeixinAdapterError:
        """
        创建超时错误
        
        参数:
            endpoint: API端点
            timeout_seconds: 超时时间
            
        返回:
            WeixinAdapterError实例
        """
        return cls(
            code="WEIXIN_TIMEOUT",
            message="weixin 上游请求超时",
            details={"endpoint": endpoint, "timeout_seconds": timeout_seconds},
            suggestions=["提高 timeout_seconds 或检查网络连通性"]
        )

    @classmethod
    def http_error(cls, endpoint: str, error: str) -> WeixinAdapterError:
        """
        创建HTTP错误
        
        参数:
            endpoint: API端点
            error: 错误信息
            
        返回:
            WeixinAdapterError实例
        """
        return cls(
            code="WEIXIN_HTTP_ERROR",
            message="weixin 上游请求异常",
            details={"endpoint": endpoint, "error": error},
            suggestions=["检查网络、代理和证书配置"]
        )

    @classmethod
    def session_paused(cls, account_id: str, remaining_seconds: int) -> WeixinAdapterError:
        """
        创建会话暂停错误
        
        参数:
            account_id: 账号ID
            remaining_seconds: 剩余暂停时间
            
        返回:
            WeixinAdapterError实例
        """
        return cls(
            code="WEIXIN_SESSION_PAUSED",
            message="weixin 会话已暂停，请稍后再试",
            details={"account_id": account_id, "remaining_seconds": remaining_seconds},
            suggestions=["重新扫码登录或等待暂停窗口结束后重试"]
        )

    @classmethod
    def internal_error(cls, exception_type: str, error: str) -> WeixinAdapterError:
        """
        创建内部错误
        
        参数:
            exception_type: 异常类型
            error: 错误信息
            
        返回:
            WeixinAdapterError实例
        """
        return cls(
            code="WEIXIN_INTERNAL_ERROR",
            message="weixin 适配执行发生未预期错误",
            details={"exception": exception_type, "error": error},
            suggestions=["检查 skill 配置与网络连通性后重试"]
        )
