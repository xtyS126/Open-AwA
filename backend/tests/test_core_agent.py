"""
AIAgent 单元测试模块。
测试 Agent 核心逻辑，包括初始化、执行流程和结果处理。
"""

import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from sqlalchemy.orm import Session

from core.agent import AIAgent


class TestAIAgentInit:
    """测试 AIAgent 初始化"""

    def test_init_without_db_session(self):
        """测试不带数据库会话的初始化"""
        with patch('core.agent.SkillEngine') as mock_skill_engine:
            agent = AIAgent()
            
            assert agent.comprehension is not None
            assert agent.planner is not None
            assert agent.executor is not None
            assert agent.feedback is not None
            assert agent._closed is False
            assert agent.skill_results == []
            assert agent.plugin_results == []
            mock_skill_engine.assert_called_once()

    def test_init_with_db_session(self):
        """测试带数据库会话的初始化"""
        mock_session = MagicMock(spec=Session)
        
        with patch('core.agent.SkillEngine') as mock_skill_engine:
            agent = AIAgent(db_session=mock_session)
            
            assert agent._db_session == mock_session
            mock_skill_engine.assert_called_once_with(mock_session)


class TestAIAgentHandleRecordTaskResult:
    """测试任务结果处理"""

    def test_handle_cancelled_task(self):
        """测试处理被取消的任务"""
        with patch('core.agent.SkillEngine'):
            agent = AIAgent()
            
            mock_task = MagicMock()
            mock_task.cancelled.return_value = True
            
            agent._handle_record_task_result(mock_task)

    def test_handle_task_with_exception(self):
        """测试处理有异常的任务"""
        with patch('core.agent.SkillEngine'):
            agent = AIAgent()
            
            mock_task = MagicMock()
            mock_task.cancelled.return_value = False
            mock_task.exception.return_value = Exception("Test error")
            
            agent._handle_record_task_result(mock_task)

    def test_handle_successful_task(self):
        """测试处理成功的任务"""
        with patch('core.agent.SkillEngine'):
            agent = AIAgent()
            
            mock_task = MagicMock()
            mock_task.cancelled.return_value = False
            mock_task.exception.return_value = None
            mock_task.result.return_value = "success"
            
            agent._handle_record_task_result(mock_task)


class TestAIAgentScheduleRecord:
    """测试记录调度"""

    def test_schedule_record_without_user_id(self):
        """测试无用户ID时不记录"""
        with patch('core.agent.SkillEngine'):
            agent = AIAgent()
            
            context = {"session_id": "test"}
            
            agent._schedule_record(
                node_type="test",
                user_message="test message",
                context=context,
                status="success"
            )

    def test_schedule_record_with_user_id(self):
        """测试有用户ID时调度记录"""
        with patch('core.agent.SkillEngine'):
            agent = AIAgent()
            
            context = {"user_id": "test_user", "session_id": "test_session"}
            
            with patch.object(agent, '_build_behavior_entries', return_value=[]):
                agent._schedule_record(
                    node_type="test",
                    user_message="test message",
                    context=context,
                    status="success"
                )


class TestAIAgentClose:
    """测试资源清理"""

    def test_close_sets_closed_flag(self):
        """测试关闭设置closed标志"""
        with patch('core.agent.SkillEngine'):
            agent = AIAgent()
            
            assert agent._closed is False
            
            agent.close()
            
            assert agent._closed is True

    def test_close_idempotent(self):
        """测试关闭幂等性"""
        with patch('core.agent.SkillEngine'):
            agent = AIAgent()
            
            agent.close()
            agent.close()
            
            assert agent._closed is True


class TestAIAgentProperties:
    """测试属性访问"""

    def test_skill_engine_accessible(self):
        """测试技能引擎可访问"""
        with patch('core.agent.SkillEngine') as mock_skill_engine:
            mock_instance = MagicMock()
            mock_skill_engine.return_value = mock_instance
            
            agent = AIAgent()
            
            assert agent.skill_engine == mock_instance

    def test_plugin_manager_accessible(self):
        """测试插件管理器可访问"""
        with patch('core.agent.SkillEngine'), \
             patch('core.agent.PluginManager') as mock_plugin_manager:
            mock_instance = MagicMock()
            mock_plugin_manager.return_value = mock_instance
            
            agent = AIAgent()
            
            assert agent.plugin_manager == mock_instance
