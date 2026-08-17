"""
兼容层：backend/mcp/ 已重命名为 backend/mcp_integration/。
此文件仅用于向后兼容，将在后续版本中移除。

使用 PEP 562 __getattr__ 延迟导入，避免与官方 SDK 的循环导入：
mcp_integration/manager.py 加载官方 SDK 时，SDK 内部会 `import mcp.types`，
此时若本兼容层立即从 mcp_integration 导入，会因 manager.py 尚未完成初始化而循环导入。
"""
import warnings

# 延迟导入——仅在实际访问 mcp.X 属性时才触发
# 所有公共接口的映射表，首次访问时惰性填充
_LAZY_EXPORTS = {
    "MCPClient": ("mcp_integration.manager", "MCPClient"),
    "MCPClientError": ("mcp_integration.manager", "MCPClientError"),
    "MCPManager": ("mcp_integration.manager", "MCPManager"),
    "MCPMessage": ("mcp_integration.manager", "MCPMessage"),
    "MCPResource": ("mcp_integration.manager", "MCPResource"),
    "MCPResourceContent": ("mcp_integration.manager", "MCPResourceContent"),
    "MCPServerConfig": ("mcp_integration.manager", "MCPServerConfig"),
    "MCPTool": ("mcp_integration.manager", "MCPTool"),
    "MCPToolCallRequest": ("mcp_integration.manager", "MCPToolCallRequest"),
    "MCPToolCallResponse": ("mcp_integration.manager", "MCPToolCallResponse"),
    "MCPTransportError": ("mcp_integration.manager", "MCPTransportError"),
    "SSETransport": ("mcp_integration.manager", "SSETransport"),
    "TransportType": ("mcp_integration.manager", "TransportType"),
    "build_mcp_tool_name": ("mcp_integration.manager", "build_mcp_tool_name"),
    "is_mcp_session_expired_error": ("mcp_integration.manager", "is_mcp_session_expired_error"),
    "MCPConfigStore": ("mcp_integration.config_store", "MCPConfigStore"),
    "SandboxError": ("mcp_integration.sandbox", "SandboxError"),
    "SandboxLimits": ("mcp_integration.sandbox", "SandboxLimits"),
    "SandboxTimeoutError": ("mcp_integration.sandbox", "SandboxTimeoutError"),
    "_validate_command_path": ("mcp_integration.sandbox", "_validate_command_path"),
    "create_sandboxed_subprocess": ("mcp_integration.sandbox", "create_sandboxed_subprocess"),
    "kill_process_tree": ("mcp_integration.sandbox", "kill_process_tree"),
    "wait_with_timeout": ("mcp_integration.sandbox", "wait_with_timeout"),
}

__all__ = list(_LAZY_EXPORTS.keys())


def __getattr__(name: str):
    """PEP 562: 模块级 __getattr__，延迟导入以避免循环导入。"""
    if name == "__path__":
        # 避免某些导入工具检查 __path__ 时触发
        raise AttributeError(name)
    if name not in _LAZY_EXPORTS:
        raise AttributeError(f"module 'mcp' has no attribute '{name}'")
    module_name, attr_name = _LAZY_EXPORTS[name]
    import importlib
    mod = importlib.import_module(module_name)
    # 缓存到模块字典，下次直接访问
    val = getattr(mod, attr_name)
    globals()[name] = val
    return val