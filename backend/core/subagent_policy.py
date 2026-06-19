"""
子代理策略模块。

定义子代理运行时的资源控制策略，包括：
- 并发控制
- 深度控制
- 工具权限控制
- 网络访问控制

参考 Agent Diva 的 SubagentPolicy 设计。
"""

from dataclasses import dataclass
from typing import Any, Dict, Optional, Set


@dataclass
class SubagentPolicy:
    """
    子代理运行时策略。
    
    控制子代理的资源使用和权限边界。
    """
    
    # 并发控制
    max_concurrent: int = 8  # 最大并发子代理数
    
    # 深度控制
    max_depth: int = 3  # 最大嵌套深度（防止无限递归）
    
    # 工具权限
    allow_shell: bool = False  # 是否允许执行 shell 命令
    allow_filesystem: bool = True  # 是否允许文件系统操作
    allow_web_fetch: bool = False  # 是否允许网页抓取
    allow_web_search: bool = False  # 是否允许网络搜索
    allow_mcp: bool = True  # 是否允许 MCP 工具
    
    # 资源限制
    max_tool_calls: int = 50  # 单次执行最大工具调用次数
    max_tokens: int = 100000  # 单次执行最大 token 消耗
    
    def __post_init__(self):
        """校验参数合法性。"""
        if self.max_concurrent < 1:
            raise ValueError("max_concurrent 必须 >= 1")
        if self.max_depth < 1:
            raise ValueError("max_depth 必须 >= 1")
        if self.max_tool_calls < 1:
            raise ValueError("max_tool_calls 必须 >= 1")
        if self.max_tokens < 1000:
            raise ValueError("max_tokens 必须 >= 1000")
    
    def check_depth_allowed(self, current_depth: int) -> bool:
        """
        检查当前深度是否允许继续创建子代理。
        
        Args:
            current_depth: 当前嵌套深度
            
        Returns:
            True 表示允许，False 表示不允许
        """
        return current_depth < self.max_depth
    
    def get_allowed_tools(self, parent_tools: Set[str]) -> Set[str]:
        """
        根据策略过滤允许的工具集。
        
        Args:
            parent_tools: 父代理的工具集
            
        Returns:
            子代理允许的工具集
        """
        allowed = set(parent_tools)
        
        # 根据策略移除受限工具
        if not self.allow_shell:
            allowed = {t for t in allowed if not t.startswith("shell_")}
        
        if not self.allow_filesystem:
            allowed = {t for t in allowed if not t.startswith("file_")}
        
        if not self.allow_web_fetch:
            allowed = {t for t in allowed if t != "web_fetch"}
        
        if not self.allow_web_search:
            allowed = {t for t in allowed if t != "web_search"}
        
        if not self.allow_mcp:
            allowed = {t for t in allowed if t.startswith("mcp_")}
        
        return allowed
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式。"""
        return {
            "max_concurrent": self.max_concurrent,
            "max_depth": self.max_depth,
            "allow_shell": self.allow_shell,
            "allow_filesystem": self.allow_filesystem,
            "allow_web_fetch": self.allow_web_fetch,
            "allow_web_search": self.allow_web_search,
            "allow_mcp": self.allow_mcp,
            "max_tool_calls": self.max_tool_calls,
            "max_tokens": self.max_tokens,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SubagentPolicy":
        """从字典创建实例。"""
        return cls(
            max_concurrent=data.get("max_concurrent", 8),
            max_depth=data.get("max_depth", 3),
            allow_shell=data.get("allow_shell", False),
            allow_filesystem=data.get("allow_filesystem", True),
            allow_web_fetch=data.get("allow_web_fetch", False),
            allow_web_search=data.get("allow_web_search", False),
            allow_mcp=data.get("allow_mcp", True),
            max_tool_calls=data.get("max_tool_calls", 50),
            max_tokens=data.get("max_tokens", 100000),
        )
    
    @classmethod
    def default(cls) -> "SubagentPolicy":
        """创建默认策略。"""
        return cls()
    
    @classmethod
    def permissive(cls) -> "SubagentPolicy":
        """创建宽松策略（允许所有工具）。"""
        return cls(
            allow_shell=True,
            allow_filesystem=True,
            allow_web_fetch=True,
            allow_web_search=True,
            allow_mcp=True,
        )
    
    @classmethod
    def restrictive(cls) -> "SubagentPolicy":
        """创建严格策略（最小权限）。"""
        return cls(
            allow_shell=False,
            allow_filesystem=False,
            allow_web_fetch=False,
            allow_web_search=False,
            allow_mcp=False,
            max_tool_calls=20,
            max_tokens=50000,
        )
