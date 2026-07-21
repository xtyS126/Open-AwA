"""
子代理策略单元测试。
"""

import pytest
from core.subagent_policy import SubagentPolicy


class TestSubagentPolicy:
    """子代理策略测试套件。"""
    
    def test_default_policy(self):
        """测试默认策略配置。"""
        policy = SubagentPolicy()
        
        assert policy.max_concurrent == 8
        assert policy.max_depth == 3
        assert policy.allow_shell is False
        assert policy.allow_filesystem is True
        assert policy.allow_web_fetch is False
        assert policy.allow_web_search is False
        assert policy.allow_mcp is True
        assert policy.max_tool_calls == 50
        assert policy.max_tokens == 100000
    
    def test_custom_policy(self):
        """测试自定义策略配置。"""
        policy = SubagentPolicy(
            max_concurrent=4,
            max_depth=2,
            allow_shell=True,
            allow_filesystem=False,
            allow_web_fetch=True,
            allow_web_search=True,
            allow_mcp=False,
            max_tool_calls=30,
            max_tokens=50000
        )
        
        assert policy.max_concurrent == 4
        assert policy.max_depth == 2
        assert policy.allow_shell is True
        assert policy.allow_filesystem is False
        assert policy.allow_web_fetch is True
        assert policy.allow_web_search is True
        assert policy.allow_mcp is False
        assert policy.max_tool_calls == 30
        assert policy.max_tokens == 50000
    
    def test_policy_validation(self):
        """测试策略参数验证。"""
        # 测试无效的并发数
        with pytest.raises(ValueError, match="max_concurrent"):
            SubagentPolicy(max_concurrent=0)
        
        # 测试无效的深度
        with pytest.raises(ValueError, match="max_depth"):
            SubagentPolicy(max_depth=0)
        
        # 测试无效的工具调用次数
        with pytest.raises(ValueError, match="max_tool_calls"):
            SubagentPolicy(max_tool_calls=0)
        
        # 测试无效的 token 数
        with pytest.raises(ValueError, match="max_tokens"):
            SubagentPolicy(max_tokens=500)
    
    def test_check_depth_allowed(self):
        """测试深度检查。"""
        policy = SubagentPolicy(max_depth=3)
        
        assert policy.check_depth_allowed(0) is True
        assert policy.check_depth_allowed(1) is True
        assert policy.check_depth_allowed(2) is True
        assert policy.check_depth_allowed(3) is False
        assert policy.check_depth_allowed(4) is False
    
    def test_get_allowed_tools(self):
        """测试工具过滤。"""
        policy = SubagentPolicy(
            allow_shell=False,
            allow_filesystem=True,
            allow_web_fetch=False,
            allow_web_search=False,
            allow_mcp=True
        )
        
        parent_tools = {
            "shell_exec", "shell_run",
            "file_read", "file_write",
            "web_fetch", "web_search",
            "mcp_tool1", "mcp_tool2",
            "other_tool"
        }
        
        allowed = policy.get_allowed_tools(parent_tools)
        
        # shell 工具被移除
        assert "shell_exec" not in allowed
        assert "shell_run" not in allowed
        
        # 文件工具保留
        assert "file_read" in allowed
        assert "file_write" in allowed
        
        # web 工具被移除
        assert "web_fetch" not in allowed
        assert "web_search" not in allowed
        
        # MCP 工具保留
        assert "mcp_tool1" in allowed
        assert "mcp_tool2" in allowed
        
        # 其他工具保留
        assert "other_tool" in allowed
    
    def test_to_dict(self):
        """测试序列化为字典。"""
        policy = SubagentPolicy(
            max_concurrent=4,
            max_depth=2,
            allow_shell=True,
            max_tool_calls=30
        )
        
        d = policy.to_dict()
        
        assert d["max_concurrent"] == 4
        assert d["max_depth"] == 2
        assert d["allow_shell"] is True
        assert d["max_tool_calls"] == 30
    
    def test_from_dict(self):
        """测试从字典反序列化。"""
        data = {
            "max_concurrent": 6,
            "max_depth": 4,
            "allow_shell": True,
            "allow_filesystem": False,
            "allow_web_fetch": True,
            "allow_web_search": True,
            "allow_mcp": False,
            "max_tool_calls": 40,
            "max_tokens": 80000
        }
        
        policy = SubagentPolicy.from_dict(data)
        
        assert policy.max_concurrent == 6
        assert policy.max_depth == 4
        assert policy.allow_shell is True
        assert policy.allow_filesystem is False
        assert policy.allow_web_fetch is True
        assert policy.allow_web_search is True
        assert policy.allow_mcp is False
        assert policy.max_tool_calls == 40
        assert policy.max_tokens == 80000
    
    def test_permissive_policy(self):
        """测试宽松策略。"""
        policy = SubagentPolicy.permissive()
        
        assert policy.allow_shell is True
        assert policy.allow_filesystem is True
        assert policy.allow_web_fetch is True
        assert policy.allow_web_search is True
        assert policy.allow_mcp is True
    
    def test_restrictive_policy(self):
        """测试严格策略。"""
        policy = SubagentPolicy.restrictive()
        
        assert policy.allow_shell is False
        assert policy.allow_filesystem is False
        assert policy.allow_web_fetch is False
        assert policy.allow_web_search is False
        assert policy.allow_mcp is False
        assert policy.max_tool_calls == 20
        assert policy.max_tokens == 50000
