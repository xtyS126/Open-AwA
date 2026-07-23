"""bilibili-toolkit-builtin B 站 API 客户端模块。

封装 B 站登录凭据、WBI 签名、异步 HTTP 客户端、风控检测、
playurl 解析与视频元信息获取，作为阶段 3+ 下载流水线的基础层。

模块导出：

- :class:`Credential`：登录凭据数据类
- :class:`BilibiliClient`：异步 API 客户端
- :class:`BilibiliAPIError` / :class:`RiskControlError`：异常类
- :func:`sign_wbi` / :func:`get_mixin_key` / :func:`extract_wbi_key`：WBI 签名工具
- :class:`StreamType` / :class:`Quality` / :class:`DashVideo` / :class:`DashAudio`：流类型
- :func:`parse_playurl`：playurl 响应解析
- :func:`get_video_info` / :func:`get_playurl` / :func:`get_playurl_streams`：视频 API
- :class:`VideoInfo` / :class:`Page`：视频元信息数据类
"""

from __future__ import annotations

from .client import BILIBILI_API_BASE, DEFAULT_USER_AGENT, BilibiliClient
from .credential import Credential
from .risk_control import RiskControlError, check_response, is_risk_control_error
from .stream_types import (
    DashAudio,
    DashStreams,
    DashVideo,
    EpisodeTryMp4Stream,
    FlvStream,
    Html5Mp4Stream,
    Quality,
    StreamType,
    parse_playurl,
)
from .video import Page, VideoInfo, get_playurl, get_playurl_streams, get_video_info
from .wbi import (
    BilibiliAPIError,
    MIXIN_KEY_ENC_TAB,
    extract_wbi_key,
    get_mixin_key,
    get_wbi_keys,
    sign_wbi,
)

__all__ = [
    # Credential
    "Credential",
    # BilibiliClient
    "BilibiliClient",
    "BILIBILI_API_BASE",
    "DEFAULT_USER_AGENT",
    # WBI
    "BilibiliAPIError",
    "MIXIN_KEY_ENC_TAB",
    "extract_wbi_key",
    "get_mixin_key",
    "get_wbi_keys",
    "sign_wbi",
    # RiskControl
    "RiskControlError",
    "check_response",
    "is_risk_control_error",
    # StreamTypes
    "DashAudio",
    "DashStreams",
    "DashVideo",
    "EpisodeTryMp4Stream",
    "FlvStream",
    "Html5Mp4Stream",
    "Quality",
    "StreamType",
    "parse_playurl",
    # Video
    "Page",
    "VideoInfo",
    "get_playurl",
    "get_playurl_streams",
    "get_video_info",
]
