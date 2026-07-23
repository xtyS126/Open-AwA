"""B 站视频流类型枚举与数据类。

定义 5 种流类型枚举（Flv / Html5Mp4 / EpisodeTryMp4 / DashVideo / DashAudio）
与 B 站清晰度常量（Quality），以及 DASH 流的 Pydantic 数据类。

参考实现：``bili-sync/crates/bili_sync/src/bilibili/analyzer.rs`` 的
``VideoQuality`` / ``AudioQuality`` / ``VideoCodecs`` / ``Stream`` 枚举。

注意：B 站 qn 值在视频与音频上下文中有重叠语义（如 120 在视频侧表示 4K，
某些参考文档将其标注为 1440p）。本模块按 spec 要求将视频/音频清晰度合并为
单一 :class:`Quality` 枚举，部分值在 :class:`enum.Enum` 中会自动成为别名
（例如 ``Quality4K`` 与 ``Quality1440p`` 共享 ``120`` 值，后者访问时返回前者）。
"""

from __future__ import annotations

from enum import Enum
from typing import Union

from pydantic import BaseModel, Field


class StreamType(str, Enum):
    """B 站 playurl 响应可能返回的流类型。"""

    Flv = "flv"
    Html5Mp4 = "html5_mp4"
    EpisodeTryMp4 = "episode_try_mp4"
    DashVideo = "dash_video"
    DashAudio = "dash_audio"


class Quality(int, Enum):
    """B 站清晰度常量。

    涵盖视频与音频两套清晰度，按 spec 要求合并为单一枚举。
    部分值在 B 站不同接口中语义不同（如 120 在视频侧为 4K，在部分参考文档中
    标注为 1440p），此处按 spec 列出的全部别名保留。
    """

    # 视频清晰度
    Quality360p = 16
    Quality480p = 32
    Quality720p = 64
    Quality720p60 = 74
    Quality1080p = 80
    Quality1080pPlus = 112
    Quality1080p60 = 116
    Quality1080pHDR = 125
    Quality1440p = 120
    Quality1440pHFR = 126
    Quality1440pHDR = 127
    Quality4K = 120  # 与 Quality1440p 同值，Enum 自动作为别名
    Quality6K = 126  # 与 Quality1440pHFR 同值，Enum 自动作为别名
    Quality8K = 127  # 与 Quality1440pHDR 同值，Enum 自动作为别名
    DolbyVision = 126  # 与 Quality1440pHFR 同值，Enum 自动作为别名
    HDR = 125  # 与 Quality1080pHDR 同值，Enum 自动作为别名
    # 音频清晰度
    DolbyAudio = 30255
    HiResAudio = 30251
    HighAudio = 30280  # 192k 普通高音质


class DashVideo(BaseModel):
    """DASH 视频流。"""

    id: int = Field(..., description="视频流 ID（qn 值）")
    base_url: str = Field(..., description="主下载 URL（baseUrl 字段）")
    backup_url: list[str] = Field(default_factory=list, description="备用下载 URL 列表（backupUrl 字段）")
    quality: Quality = Field(..., description="视频清晰度枚举")
    codecs: str = Field(..., description="视频编码标识（如 avc / hev / av01 或 codecid 数字字符串）")


class DashAudio(BaseModel):
    """DASH 音频流。"""

    id: int = Field(..., description="音频流 ID")
    base_url: str = Field(..., description="主下载 URL（baseUrl 字段）")
    backup_url: list[str] = Field(default_factory=list, description="备用下载 URL 列表（backupUrl 字段）")
    quality: Quality = Field(..., description="音频清晰度枚举")
    codecs: str = Field(default="", description="音频编码标识（部分响应可能缺失，留空）")


class FlvStream(BaseModel):
    """FLV 单流（durl 格式，无音频分离）。"""

    url: str = Field(..., description="FLV 流下载 URL")


class Html5Mp4Stream(BaseModel):
    """HTML5 MP4 单流（durl + mp4 格式）。"""

    url: str = Field(..., description="MP4 流下载 URL")


class EpisodeTryMp4Stream(BaseModel):
    """剧集试看 MP4 单流（durl + mp4 格式但非 html5）。"""

    url: str = Field(..., description="试看 MP4 流下载 URL")


# DashStream：playurl 解析后的可能流类型联合
DashStream = Union[FlvStream, Html5Mp4Stream, EpisodeTryMp4Stream, DashVideo, DashAudio]


class DashStreams(BaseModel):
    """playurl 解析结果容器。

    B 站 playurl 响应可能返回单混合流（FLV/MP4）或 DASH 分离流（视频+音频），
    本类将解析结果统一封装为 ``streams`` 列表 + ``stream_type`` 标签，
    便于后续 ``analyzer`` 模块筛选最佳流。

    Attributes:
        stream_type: 流类型标签（Flv / Html5Mp4 / EpisodeTryMp4 / DashVideo+DashAudio 混合）。
        streams: 解析后的流对象列表。FLV/MP4 类型仅含 1 个元素；
                 DASH 类型可能含多个视频流与多个音频流。
    """

    stream_type: StreamType = Field(..., description="流类型标签")
    streams: list[DashStream] = Field(default_factory=list, description="流对象列表")


def parse_playurl(data: dict) -> DashStreams:
    """解析 playurl 响应为类型化对象。

    根据 ``data`` 中的 ``format`` / ``durl`` / ``dash`` 字段判断流类型：

    1. ``format`` 以 ``flv`` 开头 + 有 ``durl`` → :class:`FlvStream`
    2. ``format`` 以 ``mp4`` 开头 + ``is_html5=True`` → :class:`Html5Mp4Stream`
    3. ``format`` 以 ``mp4`` 开头 + ``is_html5`` 非 True → :class:`EpisodeTryMp4Stream`
    4. 有 ``dash`` 字段 → 多个 :class:`DashVideo` + :class:`DashAudio`

    Args:
        data: playurl 响应的 ``data`` 字段（已通过 :func:`check_response` 风控检测）。

    Returns:
        :class:`DashStreams` 容器，包含流类型标签与流对象列表。

    Raises:
        ValueError: ``data`` 中无任何可用流字段时抛出。
    """
    if not isinstance(data, dict):
        raise ValueError(f"playurl data 必须是 dict，实际类型: {type(data).__name__}")

    fmt = str(data.get("format", "") or "")
    has_durl = isinstance(data.get("durl"), list) and bool(data.get("durl"))
    is_html5 = bool(data.get("is_html5", False))

    # FLV 单流
    if has_durl and fmt.startswith("flv"):
        durl_list = data.get("durl") or []
        first_url = str((durl_list[0] or {}).get("url", "") or "")
        if not first_url:
            raise ValueError("FLV 流缺少 url 字段")
        return DashStreams(
            stream_type=StreamType.Flv,
            streams=[FlvStream(url=first_url)],
        )

    # HTML5 MP4 单流
    if has_durl and fmt.startswith("mp4") and is_html5:
        durl_list = data.get("durl") or []
        first_url = str((durl_list[0] or {}).get("url", "") or "")
        if not first_url:
            raise ValueError("HTML5 MP4 流缺少 url 字段")
        return DashStreams(
            stream_type=StreamType.Html5Mp4,
            streams=[Html5Mp4Stream(url=first_url)],
        )

    # 剧集试看 MP4 单流
    if has_durl and fmt.startswith("mp4"):
        durl_list = data.get("durl") or []
        first_url = str((durl_list[0] or {}).get("url", "") or "")
        if not first_url:
            raise ValueError("EpisodeTry MP4 流缺少 url 字段")
        return DashStreams(
            stream_type=StreamType.EpisodeTryMp4,
            streams=[EpisodeTryMp4Stream(url=first_url)],
        )

    # DASH 分离流（视频 + 音频）
    dash = data.get("dash")
    if isinstance(dash, dict):
        streams: list[DashStream] = []
        # 视频流
        videos = dash.get("video") or []
        if isinstance(videos, list):
            for video in videos:
                if not isinstance(video, dict):
                    continue
                parsed = _parse_dash_video(video)
                if parsed is not None:
                    streams.append(parsed)
        # 音频流
        audios = dash.get("audio") or []
        if isinstance(audios, list):
            for audio in audios:
                if not isinstance(audio, dict):
                    continue
                parsed = _parse_dash_audio(audio)
                if parsed is not None:
                    streams.append(parsed)
        # HiRes FLAC 音频
        flac = dash.get("flac") or {}
        if isinstance(flac, dict):
            flac_audio = flac.get("audio") or {}
            if isinstance(flac_audio, dict):
                parsed = _parse_dash_audio(flac_audio)
                if parsed is not None:
                    streams.append(parsed)
        # 杜比全景声音频
        dolby = dash.get("dolby") or {}
        if isinstance(dolby, dict):
            dolby_audios = dolby.get("audio") or []
            if isinstance(dolby_audios, list):
                for audio in dolby_audios:
                    if isinstance(audio, dict):
                        parsed = _parse_dash_audio(audio)
                        if parsed is not None:
                            streams.append(parsed)
        if streams:
            return DashStreams(
                stream_type=StreamType.DashVideo,
                streams=streams,
            )

    raise ValueError(
        f"playurl data 中无可用流字段: format={fmt!r}, has_durl={has_durl}, "
        f"has_dash={isinstance(dash, dict)}"
    )


def _parse_dash_video(video: dict) -> DashVideo | None:
    """解析单个 DASH 视频流字典。

    Args:
        video: playurl ``dash.video[]`` 元素。

    Returns:
        :class:`DashVideo` 对象，或 ``None``（缺少必要字段时跳过）。
    """
    base_url = str(video.get("baseUrl") or video.get("base_url") or "")
    if not base_url:
        return None
    video_id = video.get("id")
    if not isinstance(video_id, int):
        return None
    quality_id = video.get("id")
    quality = _resolve_quality(quality_id)
    if quality is None:
        return None
    codecs = str(video.get("codecs") or video.get("codecid") or "")
    backup_url = _extract_backup_urls(video.get("backupUrl") or video.get("backup_url"))
    return DashVideo(
        id=video_id,
        base_url=base_url,
        backup_url=backup_url,
        quality=quality,
        codecs=codecs,
    )


def _parse_dash_audio(audio: dict) -> DashAudio | None:
    """解析单个 DASH 音频流字典。

    Args:
        audio: playurl ``dash.audio[]`` / ``dash.flac.audio`` / ``dash.dolby.audio[]`` 元素。

    Returns:
        :class:`DashAudio` 对象，或 ``None``（缺少必要字段时跳过）。
    """
    base_url = str(audio.get("baseUrl") or audio.get("base_url") or "")
    if not base_url:
        return None
    audio_id = audio.get("id")
    if not isinstance(audio_id, int):
        return None
    quality = _resolve_quality(audio_id)
    if quality is None:
        return None
    codecs = str(audio.get("codecs") or "")
    backup_url = _extract_backup_urls(audio.get("backupUrl") or audio.get("backup_url"))
    return DashAudio(
        id=audio_id,
        base_url=base_url,
        backup_url=backup_url,
        quality=quality,
        codecs=codecs,
    )


def _resolve_quality(quality_id: int | None) -> Quality | None:
    """根据 qn 数值解析为 :class:`Quality` 枚举。

    Args:
        quality_id: B 站 qn / 音频 id 数值。

    Returns:
        :class:`Quality` 枚举成员，或 ``None``（未识别时跳过该流）。
    """
    if quality_id is None or not isinstance(quality_id, int):
        return None
    try:
        return Quality(quality_id)
    except ValueError:
        # spec 未列出的 qn 值（如 30216=64k / 30232=132k / 30280=192k 音频）跳过
        return None


def _extract_backup_urls(raw: object) -> list[str]:
    """从 ``backupUrl`` 字段提取备用 URL 列表。

    ``backupUrl`` 可能是字符串列表或 JSON 字符串，本函数统一转为 list[str]。
    """
    if isinstance(raw, list):
        return [str(item) for item in raw if isinstance(item, str) and item]
    if isinstance(raw, str) and raw:
        # 部分响应中 backupUrl 是 JSON 字符串
        return [raw]
    return []
