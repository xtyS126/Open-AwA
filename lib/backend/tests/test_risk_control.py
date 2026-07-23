"""风控信号检测与下载订阅熔断逻辑测试。

覆盖 SubTask 51.3：

- ``check_response`` 对 HTTP 412/403 / 业务 code=-352 / v_voucher 非空 三种
  风控信号的识别与 ``RiskControlError`` 抛出。
- ``RiskControlError`` 异常的 ``reason`` / ``code`` / ``raw_response`` 字段。
- ``is_risk_control_error`` 辅助判断函数。
- ``download_subscription`` 风控熔断：任一视频触发风控后立即终止后续视频处理，
  水位线保持原值（不推进）。
- ``download_subscription`` 对 scan 阶段抛出的 ``RiskControlError`` 向上传播
  （不在编排层吞掉）。
- 非风控异常不触发熔断，跳过该视频继续处理后续视频。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from plugins.bilibili_toolkit_builtin.bilibili.client import BilibiliClient
from plugins.bilibili_toolkit_builtin.bilibili.risk_control import (
    RiskControlError,
    check_response,
    is_risk_control_error,
)
from plugins.bilibili_toolkit_builtin.bilibili.video import VideoInfo
from plugins.bilibili_toolkit_builtin.sources import ScanResult
from plugins.bilibili_toolkit_builtin.workflow.orchestrator import (
    download_subscription,
)
from plugins.bilibili_toolkit_builtin.workflow.pipeline import WorkflowResult


def _make_json_response(
    status_code: int,
    payload: dict[str, Any],
) -> httpx.Response:
    """构造 JSON 响应的 httpx.Response 对象。

    Args:
        status_code: HTTP 状态码。
        payload: 响应体 JSON 内容。

    Returns:
    """
    return httpx.Response(
        status_code=status_code,
        headers={"content-type": "application/json"},
        text=__import__("json").dumps(payload),
    )


def _make_non_json_response(status_code: int, body: bytes) -> httpx.Response:
    """构造非 JSON（如 protobuf 二进制）响应的 httpx.Response。

    Args:
        status_code: HTTP 状态码。
        body: 二进制响应体。

    Returns:
    """
    return httpx.Response(
        status_code=status_code,
        headers={"content-type": "application/octet-stream"},
        content=body,
    )


def _make_scan_result(
    bvid: str,
    *,
    pubtime: int = 1700000000,
    fav_time: int | None = None,
) -> ScanResult:
    """构造测试用 ScanResult 对象。

    Args:
        bvid: BV 号。
        pubtime: 发布时间戳。
        fav_time: 收藏时间戳。

    Returns:
    """
    return ScanResult(
        bvid=bvid,
        aid=100,
        title=f"视频_{bvid}",
        cover="https://example.com/cover.jpg",
        upper_mid=200,
        upper_name="UP主",
        pages_count=1,
        pubtime=pubtime,
        fav_time=fav_time,
    )


def _make_video_info(bvid: str, pages_count: int = 1) -> VideoInfo:
    """构造测试用 VideoInfo 对象。

    Args:
        bvid: BV 号。
        pages_count: 分 P 数量。

    Returns:
    """
    from plugins.bilibili_toolkit_builtin.bilibili.video import Page

    pages = [
        Page(
            cid=1000 + idx,
            page=idx + 1,
            name=f"P{idx + 1}",
            duration=60,
            width=1920,
            height=1080,
        )
        for idx in range(pages_count)
    ]
    return VideoInfo(
        bvid=bvid,
        aid=100,
        title=f"视频_{bvid}",
        cover="https://example.com/cover.jpg",
        upper_mid=200,
        upper_name="UP主",
        upper_face="https://example.com/face.jpg",
        pages=pages,
        pubtime=1700000000,
        ctime=1700000000,
        desc="视频简介",
        tags=[],
    )


def _make_workflow_result(bvid: str) -> WorkflowResult:
    """构造测试用的 WorkflowResult 成功结果。

    Args:
        bvid: BV 号。

    Returns:
    """
    return WorkflowResult(
        video_id=bvid,
        page_id=1,
        status=1,
        error=None,
        files=[f"/tmp/{bvid}.mp4"],
    )


# =============================================================================
# check_response 单元测试
# =============================================================================


class TestCheckResponse:
    """``check_response`` 风控信号检测。"""

    def test_http_412_raises_risk_control_error(self) -> None:
        """HTTP 412 应抛出 reason='http_status' 的 RiskControlError。"""
        response = _make_json_response(
            412,
            {"code": 0, "message": "precondition failed"},
        )
        with pytest.raises(RiskControlError) as exc_info:
            check_response(response)
        assert exc_info.value.reason == "http_status"
        assert exc_info.value.code == 412

    def test_http_403_raises_risk_control_error(self) -> None:
        """HTTP 403 应抛出 reason='http_status' 的 RiskControlError。"""
        response = _make_json_response(
            403,
            {"code": 0, "message": "forbidden"},
        )
        with pytest.raises(RiskControlError) as exc_info:
            check_response(response)
        assert exc_info.value.reason == "http_status"
        assert exc_info.value.code == 403

    def test_risk_code_minus_352_raises_risk_control_error(self) -> None:
        """业务 code=-352 应抛出 reason='risk_code' 的 RiskControlError。"""
        response = _make_json_response(
            200,
            {"code": -352, "message": "风控"},
        )
        with pytest.raises(RiskControlError) as exc_info:
            check_response(response)
        assert exc_info.value.reason == "risk_code"
        assert exc_info.value.code == -352

    def test_v_voucher_non_empty_raises_voucher_error(self) -> None:
        """data.v_voucher 字段非空应抛出 reason='voucher' 的 RiskControlError。"""
        response = _make_json_response(
            200,
            {
                "code": 0,
                "data": {
                    "v_voucher": "0123456789abcdef",
                },
            },
        )
        with pytest.raises(RiskControlError) as exc_info:
            check_response(response)
        assert exc_info.value.reason == "voucher"
        assert exc_info.value.code == 0

    def test_v_voucher_empty_does_not_raise(self) -> None:
        """data.v_voucher 字段为空字符串时不触发风控。"""
        response = _make_json_response(
            200,
            {
                "code": 0,
                "data": {
                    "v_voucher": "",
                },
            },
        )
        # 不抛异常
        check_response(response)

    def test_normal_response_does_not_raise(self) -> None:
        """正常 200 响应（无风控信号）不抛异常。"""
        response = _make_json_response(
            200,
            {"code": 0, "data": {"bvid": "BV1xxx"}},
        )
        check_response(response)

    def test_non_json_response_does_not_raise(self) -> None:
        """非 JSON 响应（如 protobuf）跳过业务码检测，不抛异常。"""
        # 200 + 二进制 protobuf 内容，不触发风控
        response = _make_non_json_response(200, b"\x08\x01\x10\x02")
        check_response(response)

    def test_http_status_takes_precedence_over_risk_code(self) -> None:
        """HTTP 412/403 优先于业务 code 检测（先抛 http_status）。"""
        # 同时存在 412 和 code=-352，应优先抛 http_status
        response = _make_json_response(
            412,
            {"code": -352, "message": "风控"},
        )
        with pytest.raises(RiskControlError) as exc_info:
            check_response(response)
        assert exc_info.value.reason == "http_status"
        assert exc_info.value.code == 412

    def test_risk_code_takes_precedence_over_voucher(self) -> None:
        """业务 code=-352 优先于 v_voucher 检测（先抛 risk_code）。"""
        response = _make_json_response(
            200,
            {
                "code": -352,
                "data": {"v_voucher": "abc"},
            },
        )
        with pytest.raises(RiskControlError) as exc_info:
            check_response(response)
        assert exc_info.value.reason == "risk_code"
        assert exc_info.value.code == -352


# =============================================================================
# RiskControlError 异常类测试
# =============================================================================


class TestRiskControlError:
    """``RiskControlError`` 异常字段与消息格式。"""

    def test_attributes_are_preserved(self) -> None:
        """reason / code / raw_response 字段应被保留在异常实例上。"""
        err = RiskControlError(
            reason="http_status",
            code=412,
            raw_response='{"code": 0}',
        )
        assert err.reason == "http_status"
        assert err.code == 412
        assert err.raw_response == '{"code": 0}'

    def test_raw_response_defaults_to_empty(self) -> None:
        """未提供 raw_response 时默认为空字符串。"""
        err = RiskControlError(reason="voucher", code=0)
        assert err.raw_response == ""

    def test_message_contains_reason_and_code(self) -> None:
        """异常 str(message) 应包含 reason 与 code。"""
        err = RiskControlError(reason="risk_code", code=-352)
        msg = str(err)
        assert "risk_code" in msg
        assert "-352" in msg

    def test_message_contains_truncated_raw_response(self) -> None:
        """raw_response 过长时应在消息中截断为 200 字符。"""
        long_raw = "x" * 500
        err = RiskControlError(
            reason="http_status",
            code=412,
            raw_response=long_raw,
        )
        msg = str(err)
        # 消息应包含截断后的 raw 预览（200 字符）
        assert "raw=" in msg
        # 原始字段完整保留
        assert err.raw_response == long_raw
        # 消息中的预览长度不超过 200
        assert msg.count("x") <= 200 + 10  # 容差


# =============================================================================
# is_risk_control_error 辅助函数测试
# =============================================================================


class TestIsRiskControlError:
    """``is_risk_control_error`` 判断函数。"""

    def test_returns_true_for_risk_control_error(self) -> None:
        """``RiskControlError`` 实例应返回 True。"""
        err = RiskControlError(reason="http_status", code=412)
        assert is_risk_control_error(err) is True

    def test_returns_false_for_value_error(self) -> None:
        """普通 ``ValueError`` 应返回 False。"""
        err = ValueError("普通异常")
        assert is_risk_control_error(err) is False

    def test_returns_false_for_httpx_error(self) -> None:
        """``httpx.HTTPError`` 应返回 False。"""
        err = httpx.HTTPError("网络错误")
        assert is_risk_control_error(err) is False

    def test_returns_false_for_subclass_of_exception(self) -> None:
        """非 ``RiskControlError`` 子类的异常应返回 False。"""
        err = Exception("普通异常")
        assert is_risk_control_error(err) is False


# =============================================================================
# download_subscription 风控熔断测试
# =============================================================================


class TestDownloadSubscriptionCircuitBreaker:
    """``download_subscription`` 风控熔断逻辑。"""

    @pytest.mark.asyncio
    async def test_get_video_info_risk_control_terminates_round(
        self, tmp_path: Path
    ) -> None:
        """第二个视频的 get_video_info 触发风控，应终止后续处理且水位线不推进。

        场景：3 个视频，第一个成功下载，第二个 get_video_info 抛 RiskControlError，
        第三个不应被处理；返回结果列表只含第一个视频的 WorkflowResult；
        新水位线应等于旧水位线（不推进）。
        """
        # 三个扫描结果，pubtime 递增
        scan_results = [
            _make_scan_result("BV1", pubtime=1700000001),
            _make_scan_result("BV2", pubtime=1700000002),
            _make_scan_result("BV3", pubtime=1700000003),
        ]
        old_watermark = 1700000000

        # mock scan_submission 返回 3 个视频
        # mock get_video_info：第一个成功，第二个抛 RiskControlError，第三个不应被调用
        # mock download_video：第一个视频返回 1 个 WorkflowResult
        async def fake_scan_submission(
            client: Any, upper_mid: int, latest_row_at: Any
        ) -> list[ScanResult]:
            return scan_results

        async def fake_get_video_info(client: Any, bvid: str) -> VideoInfo:
            if bvid == "BV1":
                return _make_video_info("BV1")
            if bvid == "BV2":
                raise RiskControlError(
                    reason="risk_code",
                    code=-352,
                    raw_response='{"code": -352}',
                )
            # BV3 不应被调用
            raise AssertionError(f"BV3 不应被处理，但被调用了: {bvid}")

        async def fake_download_video(
            client: Any, video: VideoInfo, config: Any, base_dir: Path
        ) -> list[WorkflowResult]:
            return [_make_workflow_result(video.bvid)]

        mock_client = MagicMock(spec=BilibiliClient)
        config: dict[str, Any] = {"video_name": "{{title}}", "page_name": "{{bvid}}"}

        with patch(
            "plugins.bilibili_toolkit_builtin.workflow.orchestrator.scan_submission",
            new=fake_scan_submission,
        ), patch(
            "plugins.bilibili_toolkit_builtin.workflow.orchestrator.get_video_info",
            new=fake_get_video_info,
        ), patch(
            "plugins.bilibili_toolkit_builtin.workflow.orchestrator.download_video",
            new=fake_download_video,
        ):
            results, new_watermark = await download_subscription(
                client=mock_client,
                subscription_type="submission",
                source_id=200,
                config=config,
                base_dir=tmp_path,
                latest_row_at=old_watermark,
            )

        # 只处理了 BV1，BV2 抛风控后 BV3 未被处理
        assert len(results) == 1
        assert results[0].files[0].endswith("BV1.mp4")
        # 风控触发，水位线保持原值
        assert new_watermark == old_watermark

    @pytest.mark.asyncio
    async def test_download_video_risk_control_terminates_round(
        self, tmp_path: Path
    ) -> None:
        """第二个视频的 download_video 触发风控，应终止后续处理。

        场景：3 个视频，BV1 成功，BV2 在 download_video 阶段抛 RiskControlError，
        BV3 不应被处理；返回结果列表只含 BV1 的 WorkflowResult。
        """
        scan_results = [
            _make_scan_result("BV1", pubtime=1700000001),
            _make_scan_result("BV2", pubtime=1700000002),
            _make_scan_result("BV3", pubtime=1700000003),
        ]
        old_watermark = 1700000000

        async def fake_scan_submission(
            client: Any, upper_mid: int, latest_row_at: Any
        ) -> list[ScanResult]:
            return scan_results

        async def fake_get_video_info(client: Any, bvid: str) -> VideoInfo:
            # 所有视频的 get_video_info 都成功
            return _make_video_info(bvid)

        # 记录调用顺序，确保 BV3 未被处理
        processed_bvids: list[str] = []

        async def fake_download_video(
            client: Any, video: VideoInfo, config: Any, base_dir: Path
        ) -> list[WorkflowResult]:
            processed_bvids.append(video.bvid)
            if video.bvid == "BV2":
                raise RiskControlError(
                    reason="http_status",
                    code=412,
                    raw_response='{"code": 0}',
                )
            return [_make_workflow_result(video.bvid)]

        mock_client = MagicMock(spec=BilibiliClient)
        config: dict[str, Any] = {"video_name": "{{title}}"}

        with patch(
            "plugins.bilibili_toolkit_builtin.workflow.orchestrator.scan_submission",
            new=fake_scan_submission,
        ), patch(
            "plugins.bilibili_toolkit_builtin.workflow.orchestrator.get_video_info",
            new=fake_get_video_info,
        ), patch(
            "plugins.bilibili_toolkit_builtin.workflow.orchestrator.download_video",
            new=fake_download_video,
        ):
            results, new_watermark = await download_subscription(
                client=mock_client,
                subscription_type="submission",
                source_id=200,
                config=config,
                base_dir=tmp_path,
                latest_row_at=old_watermark,
            )

        # BV1 与 BV2 进入 download_video，BV3 未进入
        assert processed_bvids == ["BV1", "BV2"]
        # BV1 成功，BV2 抛风控后无结果
        assert len(results) == 1
        assert results[0].files[0].endswith("BV1.mp4")
        # 风控触发，水位线保持原值
        assert new_watermark == old_watermark

    @pytest.mark.asyncio
    async def test_scan_raises_risk_control_propagates(
        self, tmp_path: Path
    ) -> None:
        """scan 函数本身抛 RiskControlError 应向上传播，不被编排层吞掉。"""
        # mock scan_submission 直接抛风控
        async def fake_scan_submission(
            client: Any, upper_mid: int, latest_row_at: Any
        ) -> list[ScanResult]:
            raise RiskControlError(
                reason="risk_code",
                code=-352,
                raw_response='{"code": -352}',
            )

        mock_client = MagicMock(spec=BilibiliClient)
        config: dict[str, Any] = {"video_name": "{{title}}"}

        with patch(
            "plugins.bilibili_toolkit_builtin.workflow.orchestrator.scan_submission",
            new=fake_scan_submission,
        ):
            # 风控异常应向上传播
            with pytest.raises(RiskControlError) as exc_info:
                await download_subscription(
                    client=mock_client,
                    subscription_type="submission",
                    source_id=200,
                    config=config,
                    base_dir=tmp_path,
                    latest_row_at=1700000000,
                )
            assert exc_info.value.reason == "risk_code"
            assert exc_info.value.code == -352

    @pytest.mark.asyncio
    async def test_non_risk_error_in_get_video_info_continues(
        self, tmp_path: Path
    ) -> None:
        """get_video_info 抛非风控异常（如 ValueError），应跳过该视频继续处理后续视频。

        场景：3 个视频，BV1 与 BV3 的 get_video_info 成功，
        BV2 的 get_video_info 抛 ValueError（非风控），
        应跳过 BV2 继续处理 BV3，最终返回 BV1 与 BV3 的结果。
        水位线应推进到 max(pubtime)。
        """
        scan_results = [
            _make_scan_result("BV1", pubtime=1700000001),
            _make_scan_result("BV2", pubtime=1700000002),
            _make_scan_result("BV3", pubtime=1700000003),
        ]
        old_watermark = 1700000000

        async def fake_scan_submission(
            client: Any, upper_mid: int, latest_row_at: Any
        ) -> list[ScanResult]:
            return scan_results

        async def fake_get_video_info(client: Any, bvid: str) -> VideoInfo:
            if bvid == "BV2":
                raise ValueError("网络错误或解析失败")
            return _make_video_info(bvid)

        async def fake_download_video(
            client: Any, video: VideoInfo, config: Any, base_dir: Path
        ) -> list[WorkflowResult]:
            return [_make_workflow_result(video.bvid)]

        mock_client = MagicMock(spec=BilibiliClient)
        config: dict[str, Any] = {"video_name": "{{title}}"}

        with patch(
            "plugins.bilibili_toolkit_builtin.workflow.orchestrator.scan_submission",
            new=fake_scan_submission,
        ), patch(
            "plugins.bilibili_toolkit_builtin.workflow.orchestrator.get_video_info",
            new=fake_get_video_info,
        ), patch(
            "plugins.bilibili_toolkit_builtin.workflow.orchestrator.download_video",
            new=fake_download_video,
        ):
            results, new_watermark = await download_subscription(
                client=mock_client,
                subscription_type="submission",
                source_id=200,
                config=config,
                base_dir=tmp_path,
                latest_row_at=old_watermark,
            )

        # BV2 被跳过，BV1 与 BV3 的结果都在
        assert len(results) == 2
        bvids_in_results = [r.files[0] for r in results]
        assert any("BV1.mp4" in f for f in bvids_in_results)
        assert any("BV3.mp4" in f for f in bvids_in_results)
        assert not any("BV2.mp4" in f for f in bvids_in_results)
        # 非风控路径，水位线应推进到 max(pubtime)=1700000003
        assert new_watermark == 1700000003

    @pytest.mark.asyncio
    async def test_non_risk_error_in_download_video_continues(
        self, tmp_path: Path
    ) -> None:
        """download_video 抛非风控异常（如 RuntimeError），应跳过该视频继续处理。"""
        scan_results = [
            _make_scan_result("BV1", pubtime=1700000001),
            _make_scan_result("BV2", pubtime=1700000002),
            _make_scan_result("BV3", pubtime=1700000003),
        ]
        old_watermark = 1700000000

        async def fake_scan_submission(
            client: Any, upper_mid: int, latest_row_at: Any
        ) -> list[ScanResult]:
            return scan_results

        async def fake_get_video_info(client: Any, bvid: str) -> VideoInfo:
            return _make_video_info(bvid)

        async def fake_download_video(
            client: Any, video: VideoInfo, config: Any, base_dir: Path
        ) -> list[WorkflowResult]:
            if video.bvid == "BV2":
                raise RuntimeError("ffmpeg 不可用")
            return [_make_workflow_result(video.bvid)]

        mock_client = MagicMock(spec=BilibiliClient)
        config: dict[str, Any] = {"video_name": "{{title}}"}

        with patch(
            "plugins.bilibili_toolkit_builtin.workflow.orchestrator.scan_submission",
            new=fake_scan_submission,
        ), patch(
            "plugins.bilibili_toolkit_builtin.workflow.orchestrator.get_video_info",
            new=fake_get_video_info,
        ), patch(
            "plugins.bilibili_toolkit_builtin.workflow.orchestrator.download_video",
            new=fake_download_video,
        ):
            results, new_watermark = await download_subscription(
                client=mock_client,
                subscription_type="submission",
                source_id=200,
                config=config,
                base_dir=tmp_path,
                latest_row_at=old_watermark,
            )

        # BV2 失败被跳过，BV1 与 BV3 仍在结果中
        assert len(results) == 2
        # 水位线推进到 max(pubtime)
        assert new_watermark == 1700000003

    @pytest.mark.asyncio
    async def test_empty_scan_results_returns_empty_list(
        self, tmp_path: Path
    ) -> None:
        """scan 返回空列表时，应返回 ([], old_watermark)。"""
        async def fake_scan_submission(
            client: Any, upper_mid: int, latest_row_at: Any
        ) -> list[ScanResult]:
            return []

        mock_client = MagicMock(spec=BilibiliClient)
        config: dict[str, Any] = {"video_name": "{{title}}"}

        with patch(
            "plugins.bilibili_toolkit_builtin.workflow.orchestrator.scan_submission",
            new=fake_scan_submission,
        ):
            results, new_watermark = await download_subscription(
                client=mock_client,
                subscription_type="submission",
                source_id=200,
                config=config,
                base_dir=tmp_path,
                latest_row_at=1700000000,
            )

        assert results == []
        # 空列表时返回 old_watermark（无新视频，水位线不变）
        assert new_watermark == 1700000000

    @pytest.mark.asyncio
    async def test_first_video_risk_control_terminates_immediately(
        self, tmp_path: Path
    ) -> None:
        """第一个视频就触发风控，应立即终止，结果列表为空，水位线保持。"""
        scan_results = [
            _make_scan_result("BV1", pubtime=1700000001),
            _make_scan_result("BV2", pubtime=1700000002),
        ]
        old_watermark = 1700000000

        async def fake_scan_submission(
            client: Any, upper_mid: int, latest_row_at: Any
        ) -> list[ScanResult]:
            return scan_results

        async def fake_get_video_info(client: Any, bvid: str) -> VideoInfo:
            if bvid == "BV1":
                raise RiskControlError(
                    reason="voucher",
                    code=0,
                    raw_response='{"data": {"v_voucher": "abc"}}',
                )
            raise AssertionError(f"BV2 不应被处理: {bvid}")

        mock_client = MagicMock(spec=BilibiliClient)
        config: dict[str, Any] = {"video_name": "{{title}}"}

        with patch(
            "plugins.bilibili_toolkit_builtin.workflow.orchestrator.scan_submission",
            new=fake_scan_submission,
        ), patch(
            "plugins.bilibili_toolkit_builtin.workflow.orchestrator.get_video_info",
            new=fake_get_video_info,
        ):
            results, new_watermark = await download_subscription(
                client=mock_client,
                subscription_type="submission",
                source_id=200,
                config=config,
                base_dir=tmp_path,
                latest_row_at=old_watermark,
            )

        # 第一个视频就触发风控，结果为空
        assert results == []
        # 水位线保持原值
        assert new_watermark == old_watermark

    @pytest.mark.asyncio
    async def test_unsupported_subscription_type_raises_value_error(
        self, tmp_path: Path
    ) -> None:
        """不支持的订阅类型应抛 ValueError。"""
        mock_client = MagicMock(spec=BilibiliClient)
        config: dict[str, Any] = {"video_name": "{{title}}"}

        with pytest.raises(ValueError) as exc_info:
            await download_subscription(
                client=mock_client,
                subscription_type="invalid_type",
                source_id=1,
                config=config,
                base_dir=tmp_path,
                latest_row_at=None,
            )
        # 错误消息中应包含不支持的类型名
        assert "invalid_type" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_watchlater_risk_control_terminates(
        self, tmp_path: Path
    ) -> None:
        """WatchLater 订阅的风控熔断：第二个视频触发风控后水位线保持原值（不更新）。"""
        # WatchLater 不增量扫描，fav_time 字段被填充
        scan_results = [
            _make_scan_result("BV1", fav_time=1700000001),
            _make_scan_result("BV2", fav_time=1700000002),
        ]
        # WatchLater 的旧水位线传入 None（全量扫描）
        old_watermark = None

        async def fake_scan_watchlater(client: Any) -> list[ScanResult]:
            return scan_results

        async def fake_get_video_info(client: Any, bvid: str) -> VideoInfo:
            if bvid == "BV2":
                raise RiskControlError(
                    reason="http_status",
                    code=412,
                    raw_response='{"code": 0}',
                )
            return _make_video_info(bvid)

        async def fake_download_video(
            client: Any, video: VideoInfo, config: Any, base_dir: Path
        ) -> list[WorkflowResult]:
            return [_make_workflow_result(video.bvid)]

        mock_client = MagicMock(spec=BilibiliClient)
        config: dict[str, Any] = {"video_name": "{{title}}"}

        with patch(
            "plugins.bilibili_toolkit_builtin.workflow.orchestrator.scan_watchlater",
            new=fake_scan_watchlater,
        ), patch(
            "plugins.bilibili_toolkit_builtin.workflow.orchestrator.get_video_info",
            new=fake_get_video_info,
        ), patch(
            "plugins.bilibili_toolkit_builtin.workflow.orchestrator.download_video",
            new=fake_download_video,
        ):
            results, new_watermark = await download_subscription(
                client=mock_client,
                subscription_type="watchlater",
                source_id=1,
                config=config,
                base_dir=tmp_path,
                latest_row_at=old_watermark,
            )

        # BV1 成功，BV2 风控终止
        assert len(results) == 1
        assert results[0].files[0].endswith("BV1.mp4")
        # 风控触发，水位线保持原值（None）
        assert new_watermark is None
