"""
安全控制模块，负责权限约束、沙箱限制、审计记录或安全边界保护。
这里的逻辑通常用于避免未授权操作、危险行为或不可控的资源访问。
"""

from typing import Dict, List, Any, Optional
from loguru import logger


class PermissionChecker:
    """
    封装与PermissionChecker相关的核心逻辑与运行状态。
    该类通常是当前文件中组织数据与调度行为的主要封装单元。
    """
    def __init__(self):
        """
        处理init相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        self.whitelist = {
            "auto_approve": [
                "file:read",
                "file:list",
                "network:ping",
                "network:dns",
                "process:list",
                "system:info"
            ],
            "user_confirm": [
                "file:write",
                "file:delete",
                "command:execute",
                "network:http",
                "process:kill"
            ],
            "admin_only": [
                "system:config",
                "user:manage",
                "plugin:install",
                "skill:install"
            ]
        }
        
        self.dangerous_patterns = [
            "rm -rf",
            "del /s /q",
            "format",
            "shutdown",
            "reboot"
        ]
        
        logger.info("PermissionChecker initialized")
    
    def check_permission(
        self,
        operation: str,
        target: Optional[str] = None,
        user_role: str = "user"
    ) -> Dict[str, Any]:
        """
        检查permission相关条件、状态或权限是否满足要求。
        检查结果往往会直接决定后续是否允许继续执行某项操作。
        """
        if user_role == "admin":
            return {
                "allowed": True,
                "mode": "admin",
                "reason": "Admin has full access"
            }
        
        if operation in self.whitelist["admin_only"]:
            return {
                "allowed": False,
                "mode": "denied",
                "reason": f"Operation '{operation}' requires admin privileges"
            }
        
        if operation in self.whitelist["auto_approve"]:
            return {
                "allowed": True,
                "mode": "auto",
                "reason": "Operation is in auto-approve whitelist"
            }
        
        if target:
            for pattern in self.dangerous_patterns:
                if pattern.lower() in target.lower():
                    return {
                        "allowed": False,
                        "mode": "denied",
                        "reason": f"Dangerous pattern detected: {pattern}"
                    }
        
        if operation in self.whitelist["user_confirm"]:
            return {
                "allowed": True,
                "mode": "confirm",
                "reason": "Operation requires user confirmation"
            }
        
        logger.warning(f"Permission denied for operation '{operation}': not in whitelist")
        return {
            "allowed": False,
            "mode": "denied",
            "reason": "Operation not in whitelist"
        }
    
    def validate_parameters(
        self,
        operation: str,
        params: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        校验parameters相关输入、规则或结构是否合法。
        返回结果通常用于阻止非法输入继续流入后续链路。
        """
        validated: dict[str, Any] = {}
        errors: list[str] = []
        
        if operation == "file:read" or operation == "file:write":
            if "path" not in params:
                errors.append("Missing required parameter: path")
            elif not isinstance(params["path"], str):
                errors.append("Parameter 'path' must be a string")
        
        elif operation == "command:execute":
            if "command" not in params:
                errors.append("Missing required parameter: command")
            elif not isinstance(params["command"], str):
                errors.append("Parameter 'command' must be a string")
        
        elif operation == "network:http":
            if "url" not in params:
                errors.append("Missing required parameter: url")
            elif not params["url"].startswith(("http://", "https://")):
                errors.append("URL must start with http:// or https://")
        
        validated["valid"] = len(errors) == 0
        validated["errors"] = errors
        
        return validated
    
    def get_user_permissions(self, role: str) -> List[str]:
        """
        获取user、permissions相关数据或当前状态。
        调用方通常依赖该结果继续进行后续判断、渲染或业务编排。
        """
        permissions = []
        
        if role == "admin":
            permissions.extend(self.whitelist["auto_approve"])
            permissions.extend(self.whitelist["user_confirm"])
            permissions.extend(self.whitelist["admin_only"])
        elif role == "user":
            permissions.extend(self.whitelist["auto_approve"])
            permissions.extend(self.whitelist["user_confirm"])
        else:
            permissions = ["file:read", "system:info"]
        
        return list(set(permissions))
