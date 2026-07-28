"""
报告生成器单元测试

验证 Markdown/JSON 两种格式报告的正确生成，
以及摘要统计、模块分布等计算逻辑。
"""

import json
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from core.models import (
    AssertionResult,
    ModuleStat,
    Summary,
    TestCase,
    TestExecutionConfig,
    TestReport,
    TestRequestLog,
    TestResponseLog,
    TestResult,
)
from core.reporter import ReportGenerator, build_and_save_report


@pytest.fixture
def sample_results():
    """构建一组采样测试结果"""
    return [
        TestResult(
            case_id="sys-001",
            case_name="健康检查",
            module="system",
            status="pass",
            duration_ms=12.5,
            request=TestRequestLog(method="GET", url="http://test/health"),
            response=TestResponseLog(status_code=200),
            assertion_results=[
                AssertionResult(
                    rule_type="status_code", passed=True,
                    expected=200, actual=200, operator="eq",
                ),
            ],
        ),
        TestResult(
            case_id="auth-001",
            case_name="CSRF Token",
            module="auth",
            status="pass",
            duration_ms=8.3,
            request=TestRequestLog(method="GET", url="http://test/api/auth/csrf-token"),
            response=TestResponseLog(status_code=200),
            assertion_results=[
                AssertionResult(
                    rule_type="status_code", passed=True,
                    expected=200, actual=200, operator="eq",
                ),
            ],
        ),
        TestResult(
            case_id="auth-002",
            case_name="无认证应 401",
            module="auth",
            status="fail",
            duration_ms=5.1,
            request=TestRequestLog(method="GET", url="http://test/api/auth/me"),
            response=TestResponseLog(status_code=200),
            assertion_results=[
                AssertionResult(
                    rule_type="status_code", passed=False,
                    expected=401, actual=200, operator="eq",
                    message="期望 401, 实际 200",
                ),
            ],
        ),
        TestResult(
            case_id="chat-001",
            case_name="消息列表",
            module="chat",
            status="error",
            duration_ms=30001.0,
            error_type="timeout",
            error_message="请求超时",
        ),
        TestResult(
            case_id="market-001",
            case_name="插件市场",
            module="marketplace",
            status="skipped",
            error_message="插件市场未启用",
        ),
    ]


class TestSummaryBuilding:
    """摘要统计计算测试"""

    def test_build_summary_counts(self, sample_results):
        """各项计数正确"""
        summary = ReportGenerator._build_summary(sample_results)
        assert summary.total == 5
        assert summary.passed == 2
        assert summary.failed == 1
        assert summary.error == 1
        assert summary.skipped == 1

    def test_build_summary_pass_rate(self, sample_results):
        """通过率计算正确"""
        summary = ReportGenerator._build_summary(sample_results)
        assert summary.pass_rate == pytest.approx(0.4)  # 2/5

    def test_build_summary_durations(self, sample_results):
        """耗时统计正确"""
        summary = ReportGenerator._build_summary(sample_results)
        assert summary.total_duration_ms > 0
        assert summary.avg_duration_ms > 0
        assert summary.min_duration_ms == 5.1
        assert summary.max_duration_ms == 30001.0

    def test_build_summary_error_types(self, sample_results):
        """错误类型分布"""
        summary = ReportGenerator._build_summary(sample_results)
        assert "timeout" in summary.error_types
        assert summary.error_types["timeout"] == 1

    def test_empty_results(self):
        """空结果集摘要"""
        summary = ReportGenerator._build_summary([])
        assert summary.total == 0
        assert summary.passed == 0
        assert summary.pass_rate == 0.0


class TestModuleBreakdown:
    """模块分布统计测试"""

    def test_module_counts(self, sample_results):
        """各模块计数正确"""
        breakdown = ReportGenerator._build_module_breakdown(sample_results)
        assert "system" in breakdown
        assert "auth" in breakdown
        assert "chat" in breakdown
        assert "marketplace" in breakdown

        assert breakdown["system"].total == 1
        assert breakdown["system"].passed == 1

        assert breakdown["auth"].total == 2
        assert breakdown["auth"].passed == 1
        assert breakdown["auth"].failed == 1


class TestMarkdownGeneration:
    """Markdown 报告生成测试"""

    def test_generate_markdown_structure(self, sample_results):
        """Markdown 报告包含必要结构"""
        generator = ReportGenerator()
        config = TestExecutionConfig(base_url="http://127.0.0.1:8000")
        report = generator.build_report(sample_results, config=config)
        md = generator.generate_markdown(report)

        assert "API 自动化测试报告" in md
        assert report.report_id in md
        assert "127.0.0.1:8000" in md
        assert "执行摘要" in md
        assert "模块分布" in md
        assert "失败与错误详情" in md

    def test_generate_markdown_all_pass(self):
        """全部通过的 Markdown 报告"""
        results = [
            TestResult(
                case_id="t-001", case_name="测试1", module="test",
                status="pass", duration_ms=10.0,
                request=TestRequestLog(method="GET", url="http://test/api"),
                response=TestResponseLog(status_code=200),
            ),
            TestResult(
                case_id="t-002", case_name="测试2", module="test",
                status="pass", duration_ms=20.0,
                request=TestRequestLog(method="GET", url="http://test/api"),
                response=TestResponseLog(status_code=200),
            ),
        ]
        generator = ReportGenerator()
        report = generator.build_report(results)
        md = generator.generate_markdown(report)

        assert "100.0%" in md
        assert "所有测试用例通过" in md

    def test_generate_markdown_failure_details(self, sample_results):
        """失败用例详情正确渲染"""
        generator = ReportGenerator()
        report = generator.build_report(sample_results)
        md = generator.generate_markdown(report)

        assert "无认证应 401" in md
        assert "401" in md
        assert "消息列表" in md


class TestJsonGeneration:
    """JSON 报告生成测试"""

    def test_generate_json_valid(self, sample_results):
        """JSON 输出为有效 JSON 且包含数据"""
        generator = ReportGenerator()
        report = generator.build_report(sample_results)
        json_str = generator.generate_json(report)

        data = json.loads(json_str)
        assert data["summary"]["total"] == 5
        assert data["summary"]["passed"] == 2
        assert len(data["results"]) == 5
        assert len(data["failures"]) == 2  # 1 fail + 1 error


class TestSaveReport:
    """报告保存功能测试"""

    def test_save_markdown_report(self, sample_results, tmp_path):
        """Markdown 报告保存成功"""
        generator = ReportGenerator(output_dir=str(tmp_path))
        report = generator.build_report(sample_results)
        files = generator.save_report(report, formats=["markdown"])

        assert len(files) == 1
        assert files[0].endswith(".md")
        assert os.path.exists(files[0])

        content = open(files[0], "r", encoding="utf-8").read()
        assert "API 自动化测试报告" in content

    def test_save_json_report(self, sample_results, tmp_path):
        """JSON 报告保存成功"""
        generator = ReportGenerator(output_dir=str(tmp_path))
        report = generator.build_report(sample_results)
        files = generator.save_report(report, formats=["json"])

        assert len(files) == 1
        assert files[0].endswith(".json")
        assert os.path.exists(files[0])

        data = json.load(open(files[0], "r", encoding="utf-8"))
        assert data["summary"]["total"] == 5


class TestBuildAndSaveReport:
    """便捷函数 test_build_and_save_report 测试"""

    def test_convenience_function(self, sample_results, tmp_path):
        """便捷函数可正常调用"""
        files = build_and_save_report(
            sample_results,
            output_dir=str(tmp_path),
        )
        assert len(files) == 2  # 默认 markdown + json
        assert any(f.endswith(".md") for f in files)
        assert any(f.endswith(".json") for f in files)
