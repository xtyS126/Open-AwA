"""
API 自动化测试 Skill — 数据模型定义

本模块定义了测试用例、断言规则、执行结果、测试报告等核心数据结构，
全部基于 Pydantic v2 构建，提供完整的类型安全和序列化支持。
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


# ============================================================================
# HTTP 方法枚举
# ============================================================================

class HttpMethod(str, Enum):
    """支持的 HTTP 请求方法"""
    GET = "GET"
    POST = "POST"
    PUT = "PUT"
    DELETE = "DELETE"
    PATCH = "PATCH"


# ============================================================================
# 断言规则
# ============================================================================

class AssertionRule(BaseModel):
    """
    单条断言规则定义

    支持的断言类型:
        - status_code:  校验 HTTP 状态码
        - json_path:    校验 JSON 响应体中指定字段的值
        - response_time: 校验响应耗时上限
        - body_contains: 校验响应体是否包含指定文本
        - header_check:  校验响应头中指定字段的值
        - schema_match:  校验 JSON 结构是否匹配指定 schema
    """
    type: Literal[
        "status_code", "json_path", "response_time",
        "body_contains", "header_check", "schema_match"
    ] = Field(..., description="断言类型")
    expected: Any = Field(..., description="期望值")
    field: Optional[str] = Field(
        default=None,
        description="目标字段路径，使用点号分隔（如 'data.id'、'results.0.name'）"
    )
    operator: str = Field(
        default="eq",
        description="比较运算符：eq/ne/gt/lt/gte/lte/contains/regex/in/not_in/is_none/is_not_none"
    )
    description: str = Field(default="", description="断言说明，用于报告展示")


class AssertionResult(BaseModel):
    """单条断言的执行结果"""
    rule_type: str = Field(..., description="断言类型")
    passed: bool = Field(..., description="是否通过")
    expected: Any = Field(default=None, description="期望值")
    actual: Any = Field(default=None, description="实际值")
    operator: str = Field(default="eq", description="比较运算符")
    field: Optional[str] = Field(default=None, description="目标字段路径")
    message: str = Field(default="", description="结果描述信息")
    description: str = Field(default="", description="断言说明")


# ============================================================================
# 请求/响应日志
# ============================================================================

class TestRequestLog(BaseModel):
    """单次测试的请求快照"""
    method: str = Field(..., description="HTTP 方法")
    url: str = Field(..., description="完整请求 URL")
    headers: Dict[str, str] = Field(default_factory=dict, description="请求头（已脱敏）")
    query_params: Dict[str, str] = Field(default_factory=dict, description="查询参数")
    body: Optional[Any] = Field(default=None, description="请求体")


class TestResponseLog(BaseModel):
    """单次测试的响应快照"""
    status_code: int = Field(..., description="HTTP 状态码")
    headers: Dict[str, str] = Field(default_factory=dict, description="响应头")
    body: Optional[Any] = Field(default=None, description="响应体（JSON 解析后）")
    body_raw_preview: str = Field(
        default="",
        description="原始响应体前 500 字符（用于非 JSON 响应或解析失败时）"
    )
    content_type: str = Field(default="", description="响应 Content-Type")


# ============================================================================
# 测试结果
# ============================================================================

class TestResult(BaseModel):
    """单个测试用例的完整执行结果"""
    case_id: str = Field(..., description="用例唯一标识")
    case_name: str = Field(..., description="用例名称")
    module: str = Field(..., description="所属模块")
    description: str = Field(default="", description="用例描述")
    status: Literal["pass", "fail", "error", "skipped"] = Field(
        default="skipped", description="执行状态"
    )
    duration_ms: float = Field(default=0.0, description="执行耗时（毫秒）")
    request: Optional[TestRequestLog] = Field(default=None, description="请求快照")
    response: Optional[TestResponseLog] = Field(default=None, description="响应快照")
    assertion_results: List[AssertionResult] = Field(
        default_factory=list, description="断言结果列表"
    )
    error_message: Optional[str] = Field(default=None, description="错误信息")
    error_type: Optional[str] = Field(
        default=None,
        description="错误分类：network / timeout / http_error / assertion / parse_error / unknown"
    )
    tags: List[str] = Field(default_factory=list, description="标签")
    executed_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="执行时间（ISO 8601）"
    )

    @property
    def all_assertions_passed(self) -> bool:
        """全部断言是否通过"""
        if not self.assertion_results:
            return False
        return all(r.passed for r in self.assertion_results)

    @property
    def failed_assertions(self) -> List[AssertionResult]:
        """获取失败的断言列表"""
        return [r for r in self.assertion_results if not r.passed]


# ============================================================================
# 摘要统计
# ============================================================================

class Summary(BaseModel):
    """测试执行摘要统计"""
    total: int = Field(default=0, description="总用例数")
    passed: int = Field(default=0, description="通过数")
    failed: int = Field(default=0, description="失败数（断言不通过）")
    error: int = Field(default=0, description="错误数（执行异常）")
    skipped: int = Field(default=0, description="跳过数")
    pass_rate: float = Field(default=0.0, description="通过率（0.0 ~ 1.0）")
    total_duration_ms: float = Field(default=0.0, description="总耗时（毫秒）")
    avg_duration_ms: float = Field(default=0.0, description="平均耗时（毫秒）")
    min_duration_ms: float = Field(default=0.0, description="最短耗时（毫秒）")
    max_duration_ms: float = Field(default=0.0, description="最长耗时（毫秒）")
    error_types: Dict[str, int] = Field(
        default_factory=dict, description="错误类型分布"
    )


class ModuleStat(BaseModel):
    """单个模块的测试统计"""
    module: str = Field(..., description="模块名称")
    total: int = Field(default=0)
    passed: int = Field(default=0)
    failed: int = Field(default=0)
    error: int = Field(default=0)
    pass_rate: float = Field(default=0.0)
    avg_duration_ms: float = Field(default=0.0)


# ============================================================================
# 测试报告
# ============================================================================

class TestReport(BaseModel):
    """完整的测试报告"""
    report_id: str = Field(..., description="报告唯一标识")
    title: str = Field(default="API 自动化测试报告", description="报告标题")
    generated_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="报告生成时间（ISO 8601）"
    )
    base_url: str = Field(default="", description="测试目标基础 URL")
    summary: Summary = Field(default_factory=Summary, description="摘要统计")
    results: List[TestResult] = Field(default_factory=list, description="所有测试结果")
    module_breakdown: Dict[str, ModuleStat] = Field(
        default_factory=dict, description="按模块汇总"
    )
    failures: List[TestResult] = Field(
        default_factory=list, description="失败和错误的用例详情"
    )


# ============================================================================
# 测试执行配置
# ============================================================================

class TestExecutionConfig(BaseModel):
    """测试执行全局配置"""
    base_url: str = Field(
        default="http://127.0.0.1:8000",
        description="API 服务基础 URL"
    )
    auth_token: Optional[str] = Field(
        default=None, description="认证 Token（Bearer）"
    )
    auth_username: Optional[str] = Field(
        default=None, description="登录用户名（自动获取 Token 时使用）"
    )
    auth_password: Optional[str] = Field(
        default=None, description="登录密码（自动获取 Token 时使用）"
    )
    default_timeout_seconds: int = Field(
        default=30, ge=5, le=300, description="默认请求超时秒数"
    )
    max_concurrency: int = Field(
        default=5, ge=1, le=20, description="最大并发数"
    )
    modules_filter: List[str] = Field(
        default_factory=list, description="指定执行的模块列表（空表示全部）"
    )
    tags_filter: List[str] = Field(
        default_factory=list, description="按标签筛选（空表示全部）"
    )
    report_formats: List[Literal["markdown", "json"]] = Field(
        default=["markdown", "json"], description="报告输出格式"
    )
    report_output_dir: str = Field(
        default="reports", description="报告输出目录"
    )
    stop_on_first_failure: bool = Field(
        default=False, description="首个失败即停止"
    )
    verbose: bool = Field(
        default=False, description="详细日志输出"
    )


# ============================================================================
# 测试用例定义
# ============================================================================

class TestCase(BaseModel):
    """
    单个测试用例定义

    用例可以从 YAML 配置文件加载，也可以由代码动态构建。
    """
    id: str = Field(..., description="用例唯一标识")
    name: str = Field(..., description="用例名称")
    module: str = Field(..., description="所属模块（auth/chat/conversation...）")
    description: str = Field(default="", description="用例描述")
    method: HttpMethod = Field(..., description="HTTP 方法")
    path: str = Field(..., description="API 路径（如 /api/v1/auth/login）")
    query_params: Dict[str, str] = Field(
        default_factory=dict, description="查询参数"
    )
    body: Optional[Dict[str, Any]] = Field(
        default=None, description="请求体（POST/PUT/PATCH 时使用）"
    )
    headers: Dict[str, str] = Field(
        default_factory=dict, description="自定义请求头"
    )
    requires_auth: bool = Field(
        default=True, description="是否需要携带认证 Token"
    )
    assertions: List[AssertionRule] = Field(
        default_factory=list, description="断言规则列表"
    )
    timeout_seconds: int = Field(
        default=30, ge=1, le=300, description="超时秒数"
    )
    tags: List[str] = Field(default_factory=list, description="标签")
    priority: Literal["high", "normal", "low"] = Field(
        default="normal", description="优先级"
    )
    skip: bool = Field(default=False, description="是否跳过此用例")
    skip_reason: str = Field(default="", description="跳过原因")
    depends_on: Optional[str] = Field(
        default=None, description="依赖的用例 ID（前置条件）"
    )


# ============================================================================
# 批量用例定义（YAML 加载用）
# ============================================================================

class TestCaseSet(BaseModel):
    """YAML 中定义的测试用例集合"""
    name: str = Field(..., description="用例集名称")
    version: str = Field(default="1.0.0", description="用例集版本")
    description: str = Field(default="", description="用例集描述")
    base_url: str = Field(
        default="http://127.0.0.1:8000", description="目标服务器基础 URL"
    )
    modules: Dict[str, List[TestCase]] = Field(
        default_factory=dict, description="按模块分组的测试用例"
    )
