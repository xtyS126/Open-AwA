"""
API 自动化测试 Skill — 报告生成器

支持生成 Markdown 和 JSON 两种格式的标准化测试报告，
包含通过率、失败用例详情、模块汇总和耗时分析等核心指标。
"""

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from loguru import logger

from .models import (
    ModuleStat,
    Summary,
    TestExecutionConfig,
    TestReport,
    TestResult,
)


class ReportGenerator:
    """
    测试报告生成器

    支持格式:
        - markdown: 人类可读，含进度条、表格、统计摘要
        - json:      机器可读，包含完整数据

    使用方式:
        generator = ReportGenerator(output_dir="reports")
        report = generator.build_report(results, config)
        generator.save_report(report, formats=["markdown", "json"])
    """

    def __init__(self, output_dir: str = "reports"):
        """
        初始化报告生成器

        Args:
            output_dir: 报告输出目录
        """
        self.output_dir = Path(output_dir)

    # ========================================================================
    # 报告构建
    # ========================================================================

    def build_report(
        self,
        results: List[TestResult],
        config: Optional[TestExecutionConfig] = None,
        title: str = "API 自动化测试报告",
    ) -> TestReport:
        """
        根据测试结果列表构建完整的 TestReport

        Args:
            results: 测试结果列表
            config: 测试执行配置（可选，用于记录 base_url）
            title: 报告标题

        Returns:
            完整的 TestReport 对象
        """
        report_id = str(uuid.uuid4())[:8]
        summary = self._build_summary(results)
        module_breakdown = self._build_module_breakdown(results)

        # 收集失败和错误的用例
        failures = [
            r for r in results
            if r.status in ("fail", "error")
        ]

        return TestReport(
            report_id=report_id,
            title=title,
            base_url=config.base_url if config else "",
            summary=summary,
            results=results,
            module_breakdown=module_breakdown,
            failures=failures,
        )

    # ========================================================================
    # 格式生成
    # ========================================================================

    def generate_markdown(self, report: TestReport) -> str:
        """
        生成 Markdown 格式的测试报告

        包含:
            - 标题和元信息
            - 通过率（含 ASCII 进度条）
            - 摘要统计表
            - 模块分布表
            - 失败/错误用例详情

        Args:
            report: 测试报告对象

        Returns:
            Markdown 格式的报告字符串
        """
        lines: List[str] = []
        s = report.summary

        # 标题
        lines.append(f"# {report.title}")
        lines.append("")
        lines.append(f"**报告ID**: `{report.report_id}`")
        lines.append(f"**生成时间**: {report.generated_at}")
        if report.base_url:
            lines.append(f"**目标服务器**: {report.base_url}")
        lines.append("")

        # 通过率
        pass_pct = s.pass_rate * 100
        emoji = "[PASS]" if pass_pct >= 95 else ("[WARN]" if pass_pct >= 80 else "[FAIL]")
        lines.append(f"## {emoji} 总体通过率: {pass_pct:.1f}%")
        lines.append("")
        lines.append(self._build_pass_rate_bar(s.pass_rate))
        lines.append("")

        # 摘要统计
        lines.append("## [CHART] 执行摘要")
        lines.append("")
        lines.append("| 指标 | 数值 |")
        lines.append("|------|------|")
        lines.append(f"| 总用例数 | {s.total} |")
        lines.append(f"| [PASS] 通过 | {s.passed} |")
        lines.append(f"| [FAIL] 失败 | {s.failed} |")
        lines.append(f"| [ERROR] 错误 | {s.error} |")
        lines.append(f"| [SKIP] 跳过 | {s.skipped} |")
        lines.append(f"| 通过率 | {pass_pct:.1f}% |")
        lines.append(f"| 总耗时 | {s.total_duration_ms:.0f}ms ({s.total_duration_ms / 1000:.2f}s) |")
        lines.append(f"| 平均耗时 | {s.avg_duration_ms:.0f}ms |")
        lines.append(f"| 最短耗时 | {s.min_duration_ms:.0f}ms |")
        lines.append(f"| 最长耗时 | {s.max_duration_ms:.0f}ms |")
        lines.append("")

        # 错误类型分布
        if s.error_types:
            lines.append("### 错误类型分布")
            lines.append("")
            lines.append("| 错误类型 | 数量 |")
            lines.append("|----------|------|")
            for error_type, count in sorted(s.error_types.items(), key=lambda x: -x[1]):
                lines.append(f"| {error_type} | {count} |")
            lines.append("")

        # 模块分布
        if report.module_breakdown:
            lines.append("## [MODULE] 模块分布")
            lines.append("")
            lines.append("| 模块 | 总数 | 通过 | 失败 | 错误 | 通过率 | 平均耗时 |")
            lines.append("|------|------|------|------|------|--------|----------|")
            for module_name, stat in sorted(report.module_breakdown.items()):
                pct = stat.pass_rate * 100
                status_icon = "[PASS]" if stat.failed == 0 and stat.error == 0 else "[FAIL]"
                lines.append(
                    f"| {status_icon} {module_name} | {stat.total} | {stat.passed} | "
                    f"{stat.failed} | {stat.error} | {pct:.0f}% | {stat.avg_duration_ms:.0f}ms |"
                )
            lines.append("")

        # 失败/错误用例详情
        if report.failures:
            lines.append("## [FAIL] 失败与错误详情")
            lines.append("")
            for idx, result in enumerate(report.failures, 1):
                lines.extend(self._render_failure_detail(idx, result))
                lines.append("")
        else:
            lines.append("## [DONE] 所有测试用例通过！")
            lines.append("")

        # 页脚
        lines.append("---")
        lines.append(f"*本报告由 Open-AwA API Testing Skill 自动生成 — {report.generated_at}*")

        return "\n".join(lines)

    def generate_json(self, report: TestReport) -> str:
        """
        生成 JSON 格式的完整测试报告

        Args:
            report: 测试报告对象

        Returns:
            格式化后的 JSON 字符串
        """
        return json.dumps(
            report.model_dump(),
            ensure_ascii=False,
            indent=2,
            default=str,
        )

    # ========================================================================
    # 报告保存
    # ========================================================================

    def save_report(
        self,
        report: TestReport,
        formats: Optional[List[str]] = None,
        filename_prefix: str = "api_test_report",
    ) -> List[str]:
        """
        将测试报告保存为文件

        Args:
            report: 测试报告对象
            formats: 输出格式列表（默认 ["markdown", "json"]）
            filename_prefix: 文件名前缀

        Returns:
            已生成的文件路径列表
        """
        formats = formats or ["markdown", "json"]
        self.output_dir.mkdir(parents=True, exist_ok=True)

        saved_files: List[str] = []

        for fmt in formats:
            if fmt == "markdown":
                content = self.generate_markdown(report)
                filename = f"{filename_prefix}_{report.report_id}.md"
            elif fmt == "json":
                content = self.generate_json(report)
                filename = f"{filename_prefix}_{report.report_id}.json"
            else:
                logger.warning(f"不支持的报告格式: {fmt}")
                continue

            filepath = self.output_dir / filename
            filepath.write_text(content, encoding="utf-8")
            saved_files.append(str(filepath.resolve()))
            logger.info(f"测试报告已保存: {filepath}")

        return saved_files

    # ========================================================================
    # 辅助方法
    # ========================================================================

    @staticmethod
    def _build_summary(results: List[TestResult]) -> Summary:
        """根据结果列表构建摘要统计"""
        total = len(results)
        passed = sum(1 for r in results if r.status == "pass")
        failed = sum(1 for r in results if r.status == "fail")
        error = sum(1 for r in results if r.status == "error")
        skipped = sum(1 for r in results if r.status == "skipped")

        pass_rate = passed / total if total > 0 else 0.0

        durations = [r.duration_ms for r in results if r.duration_ms > 0]
        total_duration = sum(durations)
        avg_duration = total_duration / len(durations) if durations else 0.0
        min_duration = min(durations) if durations else 0.0
        max_duration = max(durations) if durations else 0.0

        # 错误类型分布
        error_types: dict = {}
        for r in results:
            if r.status == "error" and r.error_type:
                error_types[r.error_type] = error_types.get(r.error_type, 0) + 1

        return Summary(
            total=total,
            passed=passed,
            failed=failed,
            error=error,
            skipped=skipped,
            pass_rate=round(pass_rate, 4),
            total_duration_ms=round(total_duration, 2),
            avg_duration_ms=round(avg_duration, 2),
            min_duration_ms=round(min_duration, 2),
            max_duration_ms=round(max_duration, 2),
            error_types=error_types,
        )

    @staticmethod
    def _build_module_breakdown(results: List[TestResult]) -> dict:
        """按模块汇总统计"""
        breakdown: dict = {}

        for r in results:
            module = r.module or "unknown"
            if module not in breakdown:
                breakdown[module] = {"total": 0, "passed": 0, "failed": 0, "error": 0, "durations": []}

            stat = breakdown[module]
            stat["total"] += 1
            if r.status == "pass":
                stat["passed"] += 1
            elif r.status == "fail":
                stat["failed"] += 1
            elif r.status == "error":
                stat["error"] += 1
            if r.duration_ms > 0:
                stat["durations"].append(r.duration_ms)

        result = {}
        for module, stat in sorted(breakdown.items()):
            total = stat["total"]
            passed = stat["passed"]
            pass_rate = (passed + stat["error"] * 0) / total if total > 0 else 0.0
            # pass_rate 只计算 pass 的
            effective_pass_rate = passed / total if total > 0 else 0.0
            avg_duration = sum(stat["durations"]) / len(stat["durations"]) if stat["durations"] else 0.0

            result[module] = ModuleStat(
                module=module,
                total=total,
                passed=passed,
                failed=stat["failed"],
                error=stat["error"],
                pass_rate=round(effective_pass_rate, 4),
                avg_duration_ms=round(avg_duration, 2),
            )

        return result

    @staticmethod
    def _build_pass_rate_bar(rate: float, width: int = 40) -> str:
        """生成 ASCII 进度条"""
        filled = int(width * rate)
        empty = width - filled
        bar = "█" * filled + "░" * empty
        pct = rate * 100
        return f"`[{bar}] {pct:.1f}%`"

    @staticmethod
    def _render_failure_detail(index: int, result: TestResult) -> List[str]:
        """渲染单个失败/错误用例的详情"""
        lines: List[str] = []
        status_label = {
            "fail": "[FAIL] 断言失败",
            "error": "[ERROR] 执行错误",
        }.get(result.status, result.status)

        lines.append(f"### {index}. {status_label} — {result.case_name}")
        lines.append("")
        lines.append(f"- **用例ID**: `{result.case_id}`")
        lines.append(f"- **模块**: {result.module}")
        lines.append(f"- **耗时**: {result.duration_ms:.0f}ms")

        if result.error_message:
            lines.append(f"- **错误信息**: {result.error_message[:500]}")

        if result.error_type:
            lines.append(f"- **错误类型**: `{result.error_type}`")

        # 请求信息
        if result.request:
            lines.append("")
            lines.append("<details>")
            lines.append("<summary>[REQ] 请求详情</summary>")
            lines.append("")
            lines.append(f"- **方法**: `{result.request.method}`")
            lines.append(f"- **URL**: `{result.request.url}`")
            if result.request.body:
                body_str = json.dumps(result.request.body, ensure_ascii=False)[:500]
                lines.append(f"- **请求体**: `{body_str}`")
            lines.append("</details>")

        # 响应信息
        if result.response:
            lines.append("")
            lines.append("<details>")
            lines.append("<summary>[RESP] 响应详情</summary>")
            lines.append("")
            lines.append(f"- **状态码**: {result.response.status_code}")
            lines.append(f"- **Content-Type**: {result.response.content_type}")
            if result.response.body:
                body_str = json.dumps(result.response.body, ensure_ascii=False)[:500]
                lines.append(f"- **响应体**: `{body_str}`")
            elif result.response.body_raw_preview:
                lines.append(f"- **响应体**: `{result.response.body_raw_preview[:500]}`")
            lines.append("</details>")

        # 断言失败详情
        if result.failed_assertions:
            lines.append("")
            lines.append("<details open>")
            lines.append("<summary>[ASSERT] 断言失败详情</summary>")
            lines.append("")
            lines.append("| 断言类型 | 期望值 | 实际值 | 说明 |")
            lines.append("|----------|--------|--------|------|")
            for assertion in result.failed_assertions:
                expected_str = str(assertion.expected)[:100]
                actual_str = str(assertion.actual)[:100]
                desc = assertion.description or assertion.message
                lines.append(
                    f"| {assertion.rule_type} | {expected_str} | {actual_str} | {desc[:200]} |"
                )
            lines.append("</details>")

        return lines


# ============================================================================
# 便捷函数
# ============================================================================

def build_and_save_report(
    results: List[TestResult],
    output_dir: str = "reports",
    config: Optional[TestExecutionConfig] = None,
    formats: Optional[List[str]] = None,
) -> List[str]:
    """
    一键构建并保存测试报告

    Args:
        results: 测试结果列表
        output_dir: 输出目录
        config: 执行配置（可选）
        formats: 输出格式（默认 markdown + json）

    Returns:
        已生成的文件路径列表
    """
    generator = ReportGenerator(output_dir=output_dir)
    report = generator.build_report(results, config=config)
    return generator.save_report(report, formats=formats)
