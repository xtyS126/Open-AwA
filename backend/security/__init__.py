"""
安全控制模块，负责权限约束、沙箱限制、审计记录或安全边界保护。
这里的逻辑通常用于避免未授权操作、危险行为或不可控的资源访问。
"""

from .sandbox import Sandbox
from .sandbox import SandboxPermissionError
from .sandbox import SandboxPathError
from .backends import SandboxResult
from .backends import SandboxBackend
from .backends import RestrictedPythonBackend
from .backends import E2BBackend
from .backends import get_sandbox_backend

__all__ = [
    "Sandbox",
    "SandboxPermissionError",
    "SandboxPathError",
    "SandboxResult",
    "SandboxBackend",
    "RestrictedPythonBackend",
    "E2BBackend",
    "get_sandbox_backend",
]
