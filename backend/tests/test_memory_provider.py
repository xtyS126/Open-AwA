"""
Memory Provider 单元测试。
"""

import pytest
import tempfile
from pathlib import Path
from memory.provider import (
    MemoryProvider,
    SystemPromptRequest,
    SystemPromptResponse,
    PrefetchRequest,
    PrefetchResponse,
    SyncTurnRequest,
    SyncTurnResponse,
    SessionEndRequest,
    SessionEndResponse,
    DummyMemoryProvider,
)


class TestDummyMemoryProvider:
    """虚拟 Memory Provider 测试套件。"""
    
    def test_system_prompt_block(self):
        """测试系统提示词块生成。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            provider = DummyMemoryProvider()
            request = SystemPromptRequest(workspace_root=Path(tmpdir))
            
            response = provider.system_prompt_block(request)
            
            assert isinstance(response, SystemPromptResponse)
            assert response.status == "ready"
            assert response.markdown is not None
            assert tmpdir in response.markdown
    
    @pytest.mark.asyncio
    async def test_prefetch(self):
        """测试意图预取。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            provider = DummyMemoryProvider()
            request = PrefetchRequest(
                workspace_root=Path(tmpdir),
                intent="测试意图",
                current_room="测试房间"
            )
            
            response = await provider.prefetch(request)
            
            assert isinstance(response, PrefetchResponse)
            assert response.status == "ready"
            assert response.prompt_block is not None
            assert "测试意图" in response.prompt_block
    
    @pytest.mark.asyncio
    async def test_sync_turn(self):
        """测试回合同步。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            provider = DummyMemoryProvider()
            request = SyncTurnRequest(
                workspace_root=Path(tmpdir),
                memory_update_markdown="# 测试记忆",
                history_entry="测试历史"
            )
            
            response = await provider.sync_turn(request)
            
            assert isinstance(response, SyncTurnResponse)
            assert response.status == "persisted"
    
    @pytest.mark.asyncio
    async def test_on_session_end(self):
        """测试会话结束处理。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            provider = DummyMemoryProvider()
            request = SessionEndRequest(
                workspace_root=Path(tmpdir),
                session_id="test-session-123"
            )
            
            response = await provider.on_session_end(request)
            
            assert isinstance(response, SessionEndResponse)
            assert response.status == "triggered"
    
    @pytest.mark.asyncio
    async def test_full_lifecycle(self):
        """测试完整生命周期。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            provider = DummyMemoryProvider()
            workspace_root = Path(tmpdir)
            
            # 1. 启动注入
            sys_request = SystemPromptRequest(workspace_root=workspace_root)
            sys_response = provider.system_prompt_block(sys_request)
            assert sys_response.status == "ready"
            
            # 2. 意图预取
            prefetch_request = PrefetchRequest(
                workspace_root=workspace_root,
                intent="查询项目状态"
            )
            prefetch_response = await provider.prefetch(prefetch_request)
            assert prefetch_response.status == "ready"
            
            # 3. 回合同步
            sync_request = SyncTurnRequest(
                workspace_root=workspace_root,
                memory_update_markdown="# 项目状态更新"
            )
            sync_response = await provider.sync_turn(sync_request)
            assert sync_response.status == "persisted"
            
            # 4. 会话结束
            end_request = SessionEndRequest(
                workspace_root=workspace_root,
                session_id="lifecycle-test-session"
            )
            end_response = await provider.on_session_end(end_request)
            assert end_response.status == "triggered"
