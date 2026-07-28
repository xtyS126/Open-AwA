"""
API 自动化测试 Skill — 测试执行器

基于 httpx.AsyncClient 实现的批量 API 测试执行引擎，
支持单用例执行、批量执行（并发控制）、按模块执行和全量执行模式。
集成断言引擎和异常处理器，自动记录请求/响应快照。
"""

import asyncio
import json
import time
from typing import Any, Dict, List, Optional

import httpx
from loguru import logger

from .assertions import AssertionEngine
from .exception_handler import ExceptionHandler
from .models import (
    AssertionResult,
    TestCase,
    TestExecutionConfig,
    TestRequestLog,
    TestResponseLog,
    TestResult,
)


class TestExecutor:
    """
    API 测试执行器

    负责:
        1. 构建 HTTP 请求（含认证头）
        2. 发送请求并精确计时
        3. 运行断言引擎校验响应
        4. 通过异常处理器捕获并分类错误
        5. 生成标准化的 TestResult

    使用方式:
        config = TestExecutionConfig(base_url="http://127.0.0.1:8000", auth_token="xxx")
        executor = TestExecutor(config)
        results = await executor.execute_all(test_cases)
    """

    def __init__(self, config: TestExecutionConfig):
        """
        初始化测试执行器

        Args:
            config: 执行配置（包含 base_url、auth_token、超时、并发等参数）
        """
        self.config = config
        self.assertion_engine = AssertionEngine()
        self.exception_handler = ExceptionHandler()
        self._client: Optional[httpx.AsyncClient] = None
        self._auth_token_obtained: Optional[str] = None

    # ========================================================================
    # 生命周期
    # ========================================================================

    async def _get_client(self) -> httpx.AsyncClient:
        """获取或创建共享的 httpx 客户端（懒初始化）"""
        if self._client is None:
            limits = httpx.Limits(
                max_keepalive_connections=self.config.max_concurrency * 2,
                max_connections=self.config.max_concurrency * 2,
            )
            self._client = httpx.AsyncClient(
                base_url=self.config.base_url,
                timeout=httpx.Timeout(self.config.default_timeout_seconds),
                limits=limits,
                follow_redirects=True,
            )
        return self._client

    async def close(self):
        """关闭 HTTP 客户端，释放连接池"""
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    # ========================================================================
    # 认证 Token 管理
    # ========================================================================

    async def _ensure_auth_token(self):
        """
        确保存在有效的认证 Token

        优先级:
            1. 配置中直接提供的 auth_token
            2. 通过 auth_username / auth_password 自动登录获取
        """
        if self.config.auth_token:
            self._auth_token_obtained = self.config.auth_token
            return

        if self.config.auth_username and self.config.auth_password:
            await self._login_and_get_token()

    async def _login_and_get_token(self):
        """通过用户凭证自动登录获取 Token"""
        try:
            client = await self._get_client()
            # 先获取 CSRF Token
            csrf_resp = await client.get("/api/v1/auth/csrf-token")
            csrf_data = csrf_resp.json()
            csrf_token = csrf_data.get("token", "")

            # 执行登录
            login_resp = await client.post(
                "/api/v1/auth/login",
                json={
                    "username": self.config.auth_username,
                    "password": self.config.auth_password,
                },
                headers={"X-CSRF-Token": csrf_token} if csrf_token else {},
            )
            login_data = login_resp.json()
            token = (
                login_data.get("access_token")
                or login_data.get("token")
                or login_data.get("data", {}).get("access_token")
                or ""
            )
            if token:
                self._auth_token_obtained = token
                if self.config.verbose:
                    logger.info(f"自动获取认证 Token 成功 (用户名: {self.config.auth_username})")
            else:
                logger.warning("自动登录获取 Token 失败，后续需要认证的测试将跳过")
        except Exception as e:
            logger.warning(f"自动登录获取 Token 异常: {e}")

    def _get_auth_headers(self, test_case: TestCase) -> Dict[str, str]:
        """构建请求头（包括认证 Token 和自定义头）"""
        headers: Dict[str, str] = {
            "Accept": "application/json",
            **test_case.headers,
        }

        if test_case.requires_auth and self._auth_token_obtained:
            headers["Authorization"] = f"Bearer {self._auth_token_obtained}"
        elif test_case.requires_auth and not self._auth_token_obtained:
            if self.config.verbose:
                logger.debug(f"用例 [{test_case.id}] 需要认证但无可用 Token")

        return headers

    # ========================================================================
    # 核心执行方法
    # ========================================================================

    async def execute(self, test_case: TestCase) -> TestResult:
        """
        执行单个测试用例

        执行流程:
            1. 检查是否跳过
            2. 构建请求
            3. 发送 HTTP 请求并计时
            4. 运行断言引擎
            5. 处理异常（如有）
            6. 返回完整 TestResult

        Args:
            test_case: 测试用例定义

        Returns:
            TestResult 包含请求/响应快照、断言结果和错误信息
        """
        # 跳过标记
        if test_case.skip:
            return TestResult(
                case_id=test_case.id,
                case_name=test_case.name,
                module=test_case.module,
                description=test_case.description,
                status="skipped",
                tags=test_case.tags,
                error_message=test_case.skip_reason or "此用例被标记为跳过",
            )

        method = test_case.method.value
        url = test_case.path
        headers = self._get_auth_headers(test_case)
        query_params = test_case.query_params
        body = test_case.body
        timeout = httpx.Timeout(
            test_case.timeout_seconds or self.config.default_timeout_seconds
        )

        # 构建请求快照
        request_log = TestRequestLog(
            method=method,
            url=f"{self.config.base_url}{url}",
            headers={k: v if k.lower() != "authorization" else "Bearer ***"
                     for k, v in headers.items()},
            query_params=query_params,
            body=body,
        )

        start_time = time.perf_counter()
        client = await self._get_client()

        try:
            # 发送请求
            response = await client.request(
                method=method,
                url=url,
                headers=headers,
                params=query_params,
                json=body,
                timeout=timeout,
            )

            duration_ms = round((time.perf_counter() - start_time) * 1000, 2)

            # 构建响应快照
            response_log = await self._build_response_log(response)

            # 运行断言
            assertion_results = self.assertion_engine.run(
                response, duration_ms, test_case.assertions
            )

            # 判定状态
            all_passed = all(r.passed for r in assertion_results)
            has_assertions = len(assertion_results) > 0

            if not has_assertions:
                status = "pass"  # 无断言规则视为通过
            elif all_passed:
                status = "pass"
            else:
                status = "fail"

            return TestResult(
                case_id=test_case.id,
                case_name=test_case.name,
                module=test_case.module,
                description=test_case.description,
                status=status,
                duration_ms=duration_ms,
                request=request_log,
                response=response_log,
                assertion_results=assertion_results,
                tags=test_case.tags,
            )

        except Exception as exc:
            duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
            error_type, error_message = self.exception_handler.classify(exc)

            # 构建响应快照（如果能从异常中提取）
            response_log = self._build_error_response_log(exc)

            if self.config.verbose:
                logger.warning(
                    f"用例 [{test_case.id}] 执行异常: "
                    f"[{error_type}] {error_message[:200]}"
                )

            return TestResult(
                case_id=test_case.id,
                case_name=test_case.name,
                module=test_case.module,
                description=test_case.description,
                status="error",
                duration_ms=duration_ms,
                request=request_log,
                response=response_log,
                assertion_results=[],
                error_message=error_message,
                error_type=error_type,
                tags=test_case.tags,
            )

    # ========================================================================
    # 批量执行方法
    # ========================================================================

    async def execute_batch(
        self,
        test_cases: List[TestCase],
        concurrency: Optional[int] = None,
    ) -> List[TestResult]:
        """
        批量执行测试用例，支持并发控制

        Args:
            test_cases: 测试用例列表
            concurrency: 并发数（None 使用配置默认值）

        Returns:
            TestResult 列表
        """
        max_concurrency = concurrency or self.config.max_concurrency
        semaphore = asyncio.Semaphore(max_concurrency)

        async def _execute_with_semaphore(case: TestCase) -> TestResult:
            async with semaphore:
                return await self.execute(case)

        tasks = [_execute_with_semaphore(case) for case in test_cases]
        results = await asyncio.gather(*tasks)
        return list(results)

    async def execute_module(
        self,
        module_name: str,
        test_cases: List[TestCase],
    ) -> List[TestResult]:
        """
        按模块名筛选并执行测试用例

        Args:
            module_name: 目标模块名
            test_cases: 全量测试用例列表

        Returns:
            该模块的 TestResult 列表
        """
        filtered = [c for c in test_cases if c.module == module_name and not c.skip]
        if not filtered:
            logger.warning(f"模块 '{module_name}' 没有可执行的测试用例")
            return []
        return await self.execute_batch(filtered)

    async def execute_all(
        self,
        test_cases: List[TestCase],
    ) -> List[TestResult]:
        """
        执行全部测试用例

        会先按 priority 排序（high > normal > low），
        然后通过 execute_batch 并发执行。

        Args:
            test_cases: 全量测试用例列表

        Returns:
            所有 TestResult 列表
        """
        # 按优先级排序
        priority_order = {"high": 0, "normal": 1, "low": 2}
        sorted_cases = sorted(
            test_cases,
            key=lambda c: (priority_order.get(c.priority, 1), c.module, c.id),
        )

        # 过滤跳过的用例（但保留依赖关系处理）
        active_cases = [c for c in sorted_cases if not c.skip]

        if not active_cases:
            logger.warning("没有可执行的测试用例")
            return []

        # 如果设置了模块过滤器
        if self.config.modules_filter:
            active_cases = [
                c for c in active_cases
                if c.module in self.config.modules_filter
            ]

        # 如果设置了标签过滤器
        if self.config.tags_filter:
            active_cases = [
                c for c in active_cases
                if any(tag in self.config.tags_filter for tag in c.tags)
            ]

        if self.config.verbose:
            logger.info(
                f"开始执行 {len(active_cases)} 个测试用例 "
                f"(基础URL: {self.config.base_url}, 并发数: {self.config.max_concurrency})"
            )

        return await self.execute_batch(active_cases)

    # ========================================================================
    # 辅助方法
    # ========================================================================

    async def _build_response_log(self, response: httpx.Response) -> TestResponseLog:
        """从成功的 httpx.Response 构建响应日志"""
        content_type = response.headers.get("content-type", "")
        body: Optional[Any] = None
        body_raw_preview = ""

        try:
            if "application/json" in content_type:
                body = response.json()
            else:
                body_raw_preview = response.text[:500]
        except (json.JSONDecodeError, ValueError):
            body_raw_preview = response.text[:500]

        return TestResponseLog(
            status_code=response.status_code,
            headers=dict(response.headers),
            body=body,
            body_raw_preview=body_raw_preview,
            content_type=content_type,
        )

    @staticmethod
    def _build_error_response_log(exception: Exception) -> Optional[TestResponseLog]:
        """从异常对象尝试构建响应日志"""
        if isinstance(exception, httpx.HTTPStatusError):
            response = exception.response
            content_type = response.headers.get("content-type", "")
            body: Optional[Any] = None
            body_raw_preview = ""

            try:
                if "application/json" in content_type:
                    body = response.json()
                else:
                    body_raw_preview = response.text[:500]
            except Exception:
                body_raw_preview = response.text[:500] if response.text else ""

            return TestResponseLog(
                status_code=response.status_code,
                headers=dict(response.headers),
                body=body,
                body_raw_preview=body_raw_preview,
                content_type=content_type,
            )
        return None


# ============================================================================
# 便捷工厂函数
# ============================================================================

async def run_api_tests(
    test_cases: List[TestCase],
    base_url: str = "http://127.0.0.1:8000",
    auth_token: Optional[str] = None,
    concurrency: int = 5,
    verbose: bool = False,
) -> List[TestResult]:
    """
    快速执行 API 测试的便捷函数

    Args:
        test_cases: 测试用例列表
        base_url: API 基础 URL
        auth_token: 认证 Token（可选）
        concurrency: 并发数
        verbose: 详细日志

    Returns:
        TestResult 列表
    """
    config = TestExecutionConfig(
        base_url=base_url,
        auth_token=auth_token,
        max_concurrency=concurrency,
        verbose=verbose,
    )
    executor = TestExecutor(config)
    try:
        results = await executor.execute_all(test_cases)
        return results
    finally:
        await executor.close()
