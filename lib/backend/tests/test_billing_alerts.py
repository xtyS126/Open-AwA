"""
计费预警与成本优化建议模块单元测试。
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from billing.alerts import BudgetAlertService, CostOptimizationService


# ==================== BudgetAlertService 测试 ====================

@pytest.fixture
def mock_db():
    """模拟数据库会话。"""
    return MagicMock()


@pytest.fixture
def alert_service(mock_db):
    """预算预警服务实例。"""
    return BudgetAlertService(mock_db)


def test_alert_service_no_budget_configured(alert_service):
    """用户未配置预算时应返回空预警列表。"""
    with patch.object(alert_service.budget_manager, 'get_budget_status', return_value={
        'has_budget_configured': False,
        'message': 'No budget configured',
    }):
        alerts = alert_service.check_and_generate_alerts('user1')
        assert alerts == []


def test_alert_service_low_usage_no_alert(alert_service):
    """用量低于 50% 时不应产生预警。"""
    with patch.object(alert_service.budget_manager, 'get_budget_status', return_value={
        'has_budget_configured': True,
        'usage_percentage': 30.0,
        'warning_threshold': 0.8,
        'is_exceeded': False,
        'current_usage': 30.0,
        'max_amount': 100.0,
        'currency': 'USD',
        'period_type': 'monthly',
    }):
        alerts = alert_service.check_and_generate_alerts('user1')
        assert alerts == []


def test_alert_service_info_at_50_percent(alert_service):
    """用量达到 50% 时应产生 info 级别预警。"""
    with patch.object(alert_service.budget_manager, 'get_budget_status', return_value={
        'has_budget_configured': True,
        'usage_percentage': 55.0,
        'warning_threshold': 0.8,
        'is_exceeded': False,
        'current_usage': 55.0,
        'max_amount': 100.0,
        'currency': 'USD',
        'period_type': 'monthly',
    }):
        alerts = alert_service.check_and_generate_alerts('user1')
        assert len(alerts) == 1
        assert alerts[0]['level'] == 'info'
        assert '过半' in alerts[0]['title']


def test_alert_service_warning_at_threshold(alert_service):
    """用量达到阈值时应产生 warning 级别预警。"""
    with patch.object(alert_service.budget_manager, 'get_budget_status', return_value={
        'has_budget_configured': True,
        'usage_percentage': 82.0,
        'warning_threshold': 0.8,
        'is_exceeded': False,
        'current_usage': 82.0,
        'max_amount': 100.0,
        'currency': 'USD',
        'period_type': 'monthly',
    }):
        alerts = alert_service.check_and_generate_alerts('user1')
        assert len(alerts) == 1
        assert alerts[0]['level'] == 'warning'
        assert '阈值' in alerts[0]['title']


def test_alert_service_critical_at_95_percent(alert_service):
    """用量达到 95% 时应产生 critical 级别预警。"""
    with patch.object(alert_service.budget_manager, 'get_budget_status', return_value={
        'has_budget_configured': True,
        'usage_percentage': 96.0,
        'warning_threshold': 0.8,
        'is_exceeded': False,
        'current_usage': 96.0,
        'max_amount': 100.0,
        'currency': 'USD',
        'period_type': 'monthly',
    }):
        alerts = alert_service.check_and_generate_alerts('user1')
        assert len(alerts) == 1
        assert alerts[0]['level'] == 'critical'
        assert '即将耗尽' in alerts[0]['title']


def test_alert_service_exceeded(alert_service):
    """预算超支时应产生 critical 级别预警。"""
    with patch.object(alert_service.budget_manager, 'get_budget_status', return_value={
        'has_budget_configured': True,
        'usage_percentage': 105.0,
        'warning_threshold': 0.8,
        'is_exceeded': True,
        'current_usage': 105.0,
        'max_amount': 100.0,
        'currency': 'USD',
        'period_type': 'monthly',
    }):
        alerts = alert_service.check_and_generate_alerts('user1')
        assert len(alerts) == 1
        assert alerts[0]['level'] == 'critical'
        assert '超支' in alerts[0]['title']


def test_alert_service_get_active_alerts_all_users(alert_service, mock_db):
    """get_active_alerts 不传 user_id 时应查询所有用户预算。"""
    mock_budget = MagicMock()
    mock_budget.scope_id = 'user1'
    mock_budget.is_active = True
    mock_budget.budget_type = 'user'

    mock_query = MagicMock()
    mock_query.filter.return_value.all.return_value = [mock_budget]
    mock_db.query.return_value = mock_query

    with patch.object(alert_service, 'check_and_generate_alerts', return_value=[{'level': 'warning'}]):
        alerts = alert_service.get_active_alerts()
        assert len(alerts) == 1


# ==================== CostOptimizationService 测试 ====================

@pytest.fixture
def optimization_service(mock_db):
    """成本优化建议服务实例。"""
    return CostOptimizationService(mock_db)


def test_optimization_no_usage_data(optimization_service, mock_db):
    """无用量数据时不应产生建议。"""
    mock_query = MagicMock()
    mock_query.filter.return_value.group_by.return_value.all.return_value = []
    mock_db.query.return_value = mock_query

    # 缓存统计也返回 0
    cache_query = MagicMock()
    cache_query.filter.return_value.first.return_value = MagicMock(cache_tokens=0, total_input=0)
    # 需要区分两次 query 调用
    mock_db.query.side_effect = [mock_query, cache_query, mock_query]

    with patch.object(optimization_service, '_get_model_usage_stats', return_value=[]), \
         patch.object(optimization_service, '_get_cache_stats', return_value={'hit_rate': 0, 'total_input': 0}), \
         patch.object(optimization_service, '_detect_idle_models', return_value=[]), \
         patch.object(optimization_service, '_identify_expensive_models', return_value=[]):
        report = optimization_service.get_optimization_suggestions('user1')

    assert report['total_suggestions'] == 0
    assert report['suggestions'] == []


def test_optimization_model_efficiency_suggestion(optimization_service):
    """高成本模型应触发性价比建议。"""
    model_stats = [
        {'model_name': 'gpt-4', 'total_cost': 80.0, 'total_input': 1000, 'total_output': 500, 'call_count': 10},
        {'model_name': 'gpt-3.5-turbo', 'total_cost': 20.0, 'total_input': 2000, 'total_output': 1000, 'call_count': 20},
    ]

    with patch.object(optimization_service, '_get_model_usage_stats', return_value=model_stats), \
         patch.object(optimization_service, '_get_cache_stats', return_value={'hit_rate': 60, 'total_input': 3000}), \
         patch.object(optimization_service, '_detect_idle_models', return_value=[]), \
         patch.object(optimization_service, '_identify_expensive_models', return_value=['gpt-4']):
        report = optimization_service.get_optimization_suggestions('user1')

    # 应该有性价比建议和昂贵模型建议
    suggestion_types = [s['type'] for s in report['suggestions']]
    assert 'model_efficiency' in suggestion_types
    assert 'expensive_models' in suggestion_types


def test_optimization_cache_suggestion(optimization_service):
    """低缓存命中率应触发缓存优化建议。"""
    with patch.object(optimization_service, '_get_model_usage_stats', return_value=[]), \
         patch.object(optimization_service, '_get_cache_stats', return_value={
             'hit_rate': 10.0,
             'total_input': 5000,
             'cache_tokens': 500,
         }), \
         patch.object(optimization_service, '_detect_idle_models', return_value=[]), \
         patch.object(optimization_service, '_identify_expensive_models', return_value=[]):
        report = optimization_service.get_optimization_suggestions('user1')

    cache_suggestions = [s for s in report['suggestions'] if s['type'] == 'cache_optimization']
    assert len(cache_suggestions) == 1
    assert cache_suggestions[0]['current_hit_rate'] == 10.0


def test_optimization_idle_models_suggestion(optimization_service):
    """检测到闲置模型应产生建议。"""
    with patch.object(optimization_service, '_get_model_usage_stats', return_value=[]), \
         patch.object(optimization_service, '_get_cache_stats', return_value={'hit_rate': 60, 'total_input': 100}), \
         patch.object(optimization_service, '_detect_idle_models', return_value=['claude-3-opus', 'gemini-pro']), \
         patch.object(optimization_service, '_identify_expensive_models', return_value=[]):
        report = optimization_service.get_optimization_suggestions('user1')

    idle_suggestions = [s for s in report['suggestions'] if s['type'] == 'idle_models']
    assert len(idle_suggestions) == 1
    assert 'claude-3-opus' in idle_suggestions[0]['models']


def test_get_cheaper_alternatives_gpt4(optimization_service):
    """GPT-4 应推荐 gpt-4o-mini。"""
    alternatives = optimization_service._get_cheaper_alternatives('gpt-4')
    assert 'gpt-4o-mini' in alternatives


def test_get_cheaper_alternatives_claude_opus(optimization_service):
    """Claude 3 Opus 应推荐 Sonnet 和 Haiku。"""
    alternatives = optimization_service._get_cheaper_alternatives('claude-3-opus')
    assert 'claude-3-5-sonnet' in alternatives
    assert 'claude-3-haiku' in alternatives


def test_get_cheaper_alternatives_no_alternative(optimization_service):
    """无已知替代模型时应返回空列表。"""
    alternatives = optimization_service._get_cheaper_alternatives('unknown-model')
    assert alternatives == []


def test_identify_expensive_models(optimization_service):
    """成本占比超过 40% 的模型应被识别。"""
    model_stats = [
        {'model_name': 'gpt-4', 'total_cost': 50.0},
        {'model_name': 'gpt-3.5', 'total_cost': 30.0},
        {'model_name': 'claude', 'total_cost': 20.0},
    ]
    expensive = optimization_service._identify_expensive_models(model_stats)
    assert 'gpt-4' in expensive  # 50% > 40%


def test_identify_expensive_models_empty(optimization_service):
    """无数据时应返回空列表。"""
    assert optimization_service._identify_expensive_models([]) == []


def test_analyze_cache_efficiency_high_rate(optimization_service):
    """高缓存命中率不应产生建议。"""
    result = optimization_service._analyze_cache_efficiency({
        'hit_rate': 60.0,
        'total_input': 5000,
    })
    assert result is None


def test_analyze_cache_efficiency_low_usage(optimization_service):
    """用量太小不应产生建议。"""
    result = optimization_service._analyze_cache_efficiency({
        'hit_rate': 10.0,
        'total_input': 500,  # 小于 1000
    })
    assert result is None
