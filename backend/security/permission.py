from typing import Dict, List, Any, Optional
from loguru import logger


class PermissionChecker:
    def __init__(self):
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
        validated = {}
        errors = []
        
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
