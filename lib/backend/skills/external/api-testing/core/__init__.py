"""
API 自动化测试 Skill — 核心模块入口

提供便捷的顶层 API，整合测试用例加载、执行、断言和报告生成全流程。
同时支持作为独立脚本运行和通过 SkillEngine 调用。
"""

import os
import sys
from pathlib import Path
from typing import Dict, List, Optional

import yaml
from loguru import logger

from .assertions import AssertionEngine
from .exception_handler import ExceptionHandler, classify_exception, handle_exception
from .executor import TestExecutor, run_api_tests
from .models import (
    AssertionResult,
    AssertionRule,
    HttpMethod,
    ModuleStat,
    Summary,
    TestCase,
    TestCaseSet,
    TestExecutionConfig,
    TestReport,
    TestRequestLog,
    TestResponseLog,
    TestResult,
)
from .reporter import ReportGenerator, build_and_save_report

__all__ = [
    # 模型
    "HttpMethod",
    "TestCase",
    "TestCaseSet",
    "AssertionRule",
    "AssertionResult",
    "TestResult",
    "TestRequestLog",
    "TestResponseLog",
    "TestReport",
    "Summary",
    "ModuleStat",
    "TestExecutionConfig",
    # 引擎
    "AssertionEngine",
    "TestExecutor",
    "ReportGenerator",
    "ExceptionHandler",
    # 便捷函数
    "run_api_tests",
    "build_and_save_report",
    "classify_exception",
    "handle_exception",
    "load_test_cases_from_yaml",
    "run_full_test_suite",
]


# ============================================================================
# YAML 测试用例加载
# ============================================================================

def load_test_cases_from_yaml(yaml_path: str) -> List[TestCase]:
    """
    从 YAML 配置文件加载测试用例定义

    Args:
        yaml_path: YAML 文件路径（绝对或相对于 YAML 文件的路径）

    Returns:
        TestCase 对象列表

    Raises:
        FileNotFoundError: YAML 文件不存在
        yaml.YAMLError: YAML 解析错误
        ValueError: 配置结构不符合预期
    """
    yaml_file = Path(yaml_path)
    if not yaml_file.exists():
        raise FileNotFoundError(f"测试用例配置文件不存在: {yaml_path}")

    with open(yaml_file, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    if raw is None:
        raise ValueError(f"YAML 文件为空: {yaml_path}")

    if not isinstance(raw, dict):
        raise ValueError("YAML 顶层必须是一个字典")

    modules = raw.get("modules")
    if not modules or not isinstance(modules, dict):
        raise ValueError("YAML 中缺少 'modules' 字段或类型不是字典")

    test_cases: List[TestCase] = []
    loaded_count = 0

    for module_name, cases in modules.items():
        if not isinstance(cases, list):
            logger.warning(f"模块 '{module_name}' 的测试用例格式不正确，已跳过")
            continue

        for case_dict in cases:
            try:
                test_case = _parse_test_case_dict(case_dict, module_name)
                test_cases.append(test_case)
                loaded_count += 1
            except Exception as e:
                logger.warning(f"解析测试用例 [{module_name}] 失败: {e}", exc_info=True)

    logger.info(f"从 {yaml_path} 加载了 {loaded_count} 个测试用例 (共 {len(test_cases)} 个)")
    return test_cases


def _parse_test_case_dict(case_dict: Dict, default_module: str) -> TestCase:
    """
    将 YAML 字典转换为 TestCase 对象

    Args:
        case_dict: YAML 中的用例字典
        default_module: 默认模块名（从 YAML 键获取）

    Returns:
        TestCase 实例
    """
    # 处理断言规则
    assertions = []
    for rule_dict in case_dict.get("assertions", []):
        assertions.append(AssertionRule(
            type=rule_dict["type"],
            expected=rule_dict.get("expected"),
            field=rule_dict.get("field"),
            operator=rule_dict.get("operator", "eq"),
            description=rule_dict.get("description", ""),
        ))

    # 处理 HTTP 方法
    method_str = case_dict.get("method", "GET").upper()

    return TestCase(
        id=case_dict["id"],
        name=case_dict["name"],
        module=case_dict.get("module", default_module),
        description=case_dict.get("description", ""),
        method=HttpMethod(method_str),
        path=case_dict["path"],
        query_params=case_dict.get("query_params", {}),
        body=case_dict.get("body"),
        headers=case_dict.get("headers", {}),
        requires_auth=case_dict.get("requires_auth", True),
        assertions=assertions,
        timeout_seconds=case_dict.get("timeout_seconds", 30),
        tags=case_dict.get("tags", []),
        priority=case_dict.get("priority", "normal"),
        skip=case_dict.get("skip", False),
        skip_reason=case_dict.get("skip_reason", ""),
        depends_on=case_dict.get("depends_on"),
    )


# ============================================================================
# 全流程执行入口
# ============================================================================

async def run_full_test_suite(
    yaml_path: Optional[str] = None,
    base_url: str = "http://127.0.0.1:8000",
    auth_token: Optional[str] = None,
    auth_username: Optional[str] = None,
    auth_password: Optional[str] = None,
    modules_filter: Optional[List[str]] = None,
    tags_filter: Optional[List[str]] = None,
    concurrency: int = 5,
    output_dir: str = "reports",
    verbose: bool = False,
) -> TestReport:
    """
    运行完整测试套件的一站式函数

    流程:
        1. 从 YAML 加载测试用例
        2. 自动获取认证 Token（如配置了凭证）
        3. 并发执行所有测试用例
        4. 生成测试报告并保存

    Args:
        yaml_path: 测试用例 YAML 文件路径（None 使用默认路径）
        base_url: API 服务基础 URL
        auth_token: 认证 Token（可选）
        auth_username: 登录用户名（可选，与 auth_password 配合自动获取 Token）
        auth_password: 登录密码（可选）
        modules_filter: 指定执行的模块列表
        tags_filter: 按标签筛选
        concurrency: 并发数
        output_dir: 报告输出目录
        verbose: 详细日志

    Returns:
        完整的 TestReport 对象
    """
    # 1. 加载测试用例
    if yaml_path is None:
        # 默认路径：相对于本模块的 config/test_cases.yaml
        current_dir = Path(__file__).parent.parent
        yaml_path = str(current_dir / "config" / "test_cases.yaml")

    test_cases = load_test_cases_from_yaml(yaml_path)

    # 2. 构建执行配置
    config = TestExecutionConfig(
        base_url=base_url,
        auth_token=auth_token,
        auth_username=auth_username,
        auth_password=auth_password,
        max_concurrency=concurrency,
        modules_filter=modules_filter or [],
        tags_filter=tags_filter or [],
        verbose=verbose,
    )

    # 3. 执行测试
    executor = TestExecutor(config)
    try:
        results = await executor.execute_all(test_cases)
    finally:
        await executor.close()

    # 4. 生成报告
    report = build_and_save_report(
        results=results,
        output_dir=output_dir,
        config=config,
    )

    # 5. 打印摘要
    s = report.summary
    print(f"\n{'='*60}")
    print(f"  API 自动化测试完成")
    print(f"  通过率: {s.pass_rate * 100:.1f}% ({s.passed}/{s.total})")
    print(f"  失败: {s.failed} | 错误: {s.error} | 跳过: {s.skipped}")
    print(f"  总耗时: {s.total_duration_ms:.0f}ms ({s.total_duration_ms / 1000:.2f}s)")
    print(f"{'='*60}\n")

    return report


# ============================================================================
# 独立脚本运行支持
# ============================================================================

async def _main():
    """作为独立脚本运行时的入口函数"""
    import argparse

    parser = argparse.ArgumentParser(
        description="Open-AwA API 自动化测试工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 使用默认配置运行全部测试
  python -m core.__init__

  # 指定服务器地址和 Token
  python -m core.__init__ --base-url http://localhost:8000 --auth-token xxx

  # 使用用户名密码自动登录
  python -m core.__init__ --base-url http://localhost:8000 --auth-username admin --auth-password admin123

  # 仅运行 system 和 auth 模块
  python -m core.__init__ --modules system auth

  # 以高并发模式运行
  python -m core.__init__ --concurrency 10 --verbose
        """,
    )
    parser.add_argument("--yaml", default=None, help="测试用例 YAML 文件路径")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000", help="API 基础 URL")
    parser.add_argument("--auth-token", default=None, help="认证 Token")
    parser.add_argument("--auth-username", default=None, help="登录用户名")
    parser.add_argument("--auth-password", default=None, help="登录密码")
    parser.add_argument("--modules", nargs="*", default=[], help="指定执行的模块")
    parser.add_argument("--tags", nargs="*", default=[], help="按标签筛选")
    parser.add_argument("--concurrency", type=int, default=5, help="并发数 (默认 5)")
    parser.add_argument("--output-dir", default="reports", help="报告输出目录")
    parser.add_argument("--verbose", action="store_true", help="详细日志")

    args = parser.parse_args()

    report = await run_full_test_suite(
        yaml_path=args.yaml,
        base_url=args.base_url,
        auth_token=args.auth_token,
        auth_username=args.auth_username,
        auth_password=args.auth_password,
        modules_filter=args.modules if args.modules else None,
        tags_filter=args.tags if args.tags else None,
        concurrency=args.concurrency,
        output_dir=args.output_dir,
        verbose=args.verbose,
    )

    # 退出码：全部通过为 0，有失败为 1
    if report.summary.failed > 0 or report.summary.error > 0:
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    import asyncio
    asyncio.run(_main())
