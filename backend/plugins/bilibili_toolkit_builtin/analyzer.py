"""B 站视频流分析器。

实现 playurl 解析后的流筛选、排序与最佳流选择算法，以及 CDN 智能排序。

参考实现：``bili-sync/crates/bili_sync/src/bilibili/analyzer.rs`` 的
``FilterOption`` / ``best_stream`` / ``urls`` (CDN 排序) 逻辑。

核心流程：
1. :func:`filter_by_quality` - 按视频清晰度范围 [min, max] 过滤
2. :func:`filter_special_streams` - 按 no_dolby_video / no_hdr / no_dolby_audio / no_hires 开关过滤
3. :func:`sort_by_codecs` - 按编码偏好数组顺序排序（AVC > HEVC > AV1）
4. :func:`select_best_stream` - 综合以上步骤选出最佳视频流与音频流
5. :func:`sort_by_cdn` / :func:`sort_all_urls` - 按 CDN 前缀优先级排序 URL

注意：音频清晰度的原始 qn 值非单调（HiRes=30251 < Dolby=30255 < High=30280），
但实际质量顺序为 High < HiRes < Dolby。本模块通过 :func:`_audio_sort_key`
对 HiRes/Dolby 施加 +40 偏移，使其排序后位于 192k 之后，与 Rust 参考实现一致。
"""

from __future__ import annotations

from typing import Optional, Union

from pydantic import BaseModel, Field

from .bilibili.stream_types import (
    DashAudio,
    DashStream,
    DashStreams,
    DashVideo,
    EpisodeTryMp4Stream,
    FlvStream,
    Html5Mp4Stream,
    Quality,
    StreamType,
)


class FilterOption(BaseModel):
    """流筛选选项。

    控制视频/音频流的选择范围与编码偏好，对应 ``schema.json`` 的
    ``filter_option`` 字段。所有字段均有默认值，缺省时使用最大兼容范围。

    Attributes:
        video_max_quality: 视频允许的最高清晰度，默认 8K。
        video_min_quality: 视频允许的最低清晰度，默认 360p。
        video_codecs: 视频编码偏好顺序，默认 AVC > HEVC > AV1。
        audio_max_quality: 音频允许的最高清晰度，默认 HiRes。
        audio_min_quality: 音频允许的最低清晰度，默认 High(192k)。
        audio_codecs: 音频编码偏好顺序，默认 mp4a > ec3。
        no_dolby_video: 为 True 时过滤杜比视界视频流。
        no_dolby_audio: 为 True 时过滤杜比全景声音频流。
        no_hdr: 为 True 时过滤 HDR 视频流。
        no_hires: 为 True 时过滤 HiRes 音频流。
    """

    video_max_quality: Quality = Quality.Quality8K
    video_min_quality: Quality = Quality.Quality360p
    video_codecs: list[str] = Field(
        default_factory=lambda: ["avc", "hevc", "av1"],
        description="视频编码偏好，按数组顺序优先",
    )
    audio_max_quality: Quality = Quality.HiResAudio
    audio_min_quality: Quality = Quality.HighAudio
    audio_codecs: list[str] = Field(
        default_factory=lambda: ["mp4a", "ec3"],
        description="音频编码偏好，按数组顺序优先",
    )
    no_dolby_video: bool = False
    no_dolby_audio: bool = False
    no_hdr: bool = False
    no_hires: bool = False


class MixedStream(BaseModel):
    """单混合流（FLV / HTML5 MP4 / 试看 MP4）。

    这类流视频与音频未分离，仅有一个下载 URL，无清晰度与内容长度信息
    （B 站 durl 格式不返回这些字段），quality 与 content_length 用占位值。
    """

    url: str = Field(..., description="混合流下载 URL")
    backup_url: list[str] = Field(default_factory=list, description="备用 URL 列表")
    quality: Quality = Field(
        default=Quality.Quality360p,
        description="清晰度占位值（混合流无清晰度信息）",
    )
    content_length: int = Field(
        default=0,
        description="内容长度占位值（混合流无 Content-Length）",
    )


class VideoAudioStream(BaseModel):
    """DASH 分离流（视频 + 可选音频）。

    音频可能不存在（无声视频，如 BV1J7411H7KQ）。
    """

    video: DashVideo = Field(..., description="最佳视频流")
    audio: Optional[DashAudio] = Field(default=None, description="最佳音频流，无声视频时为 None")


# BestStream：最佳流的联合类型
BestStream = Union[MixedStream, VideoAudioStream]


def filter_by_quality(
    videos: list[DashVideo],
    filter_option: FilterOption,
) -> list[DashVideo]:
    """按视频清晰度范围 [min, max] 过滤。

    保留满足 ``video_min_quality.value <= video.quality.value <= video_max_quality.value``
    的视频流，超出范围的过滤掉。

    Args:
        videos: 待过滤的视频流列表。
        filter_option: 筛选选项，使用其中的 video_min_quality / video_max_quality。

    Returns:
        过滤后的视频流列表（保持原顺序）。
    """
    min_val: int = filter_option.video_min_quality.value
    max_val: int = filter_option.video_max_quality.value
    return [v for v in videos if min_val <= v.quality.value <= max_val]


def sort_by_codecs(
    videos: list[DashVideo],
    codecs: list[str],
) -> list[DashVideo]:
    """按编码偏好顺序排序视频流。

    按 ``codecs`` 数组顺序优先排序（如 AVC > HEVC > AV1），
    未在偏好列表中的编码排最后。同编码保持原顺序（稳定排序）。

    Args:
        videos: 待排序的视频流列表。
        codecs: 编码偏好顺序，如 ``["avc", "hevc", "av1"]``。

    Returns:
        排序后的视频流列表（新列表，不修改原列表）。
    """
    return sorted(videos, key=lambda v: _codec_index(v, codecs))


def filter_special_streams(
    videos: list[DashVideo],
    audios: list[DashAudio],
    filter_option: FilterOption,
) -> tuple[list[DashVideo], list[DashAudio]]:
    """过滤杜比视界 / HDR / 杜比全景声 / HiRes 等特殊流。

    根据筛选选项的开关跳过对应清晰度的流：
    - ``no_dolby_video=True`` → 过滤 quality=DolbyVision 的视频
    - ``no_hdr=True`` → 过滤 quality=HDR 的视频
    - ``no_dolby_audio=True`` → 过滤 quality=DolbyAudio 的音频
    - ``no_hires=True`` → 过滤 quality=HiResAudio 的音频

    Args:
        videos: 待过滤的视频流列表。
        audios: 待过滤的音频流列表。
        filter_option: 筛选选项。

    Returns:
        ``(filtered_videos, filtered_audios)`` 元组。
    """
    filtered_videos = videos
    if filter_option.no_dolby_video:
        filtered_videos = [v for v in filtered_videos if v.quality != Quality.DolbyVision]
    if filter_option.no_hdr:
        filtered_videos = [v for v in filtered_videos if v.quality != Quality.HDR]

    filtered_audios = audios
    if filter_option.no_dolby_audio:
        filtered_audios = [a for a in filtered_audios if a.quality != Quality.DolbyAudio]
    if filter_option.no_hires:
        filtered_audios = [a for a in filtered_audios if a.quality != Quality.HiResAudio]

    return filtered_videos, filtered_audios


def select_best_stream(
    dash_streams: DashStreams,
    filter_option: FilterOption,
) -> BestStream:
    """从解析后的流容器中选择最佳流。

    根据 ``dash_streams.stream_type`` 分两种情况：
    1. Flv / Html5Mp4 / EpisodeTryMp4 → 返回 :class:`MixedStream`（单混合流）
    2. DashVideo → 分离视频与音频，依次执行清晰度过滤、特殊流过滤、
       编码排序，取最高清晰度视频（同清晰度取编码偏好靠前）与最高清晰度音频，
       返回 :class:`VideoAudioStream`

    Args:
        dash_streams: :func:`parse_playurl` 解析后的流容器。
        filter_option: 流筛选选项。

    Returns:
        :class:`BestStream` 联合类型（MixedStream 或 VideoAudioStream）。

    Raises:
        ValueError: 单混合流列表为空或缺少 url；DASH 流无符合条件的视频流。
    """
    # 单混合流（FLV / HTML5 MP4 / 试看 MP4）
    if dash_streams.stream_type in (
        StreamType.Flv,
        StreamType.Html5Mp4,
        StreamType.EpisodeTryMp4,
    ):
        if not dash_streams.streams:
            raise ValueError(f"单混合流列表为空: stream_type={dash_streams.stream_type}")
        stream: DashStream = dash_streams.streams[0]
        url = _extract_single_stream_url(stream)
        if not url:
            raise ValueError("单混合流缺少 url 字段")
        return MixedStream(url=url, backup_url=[], quality=Quality.Quality360p, content_length=0)

    # DASH 分离流（视频 + 音频）
    videos: list[DashVideo] = [s for s in dash_streams.streams if isinstance(s, DashVideo)]
    audios: list[DashAudio] = [s for s in dash_streams.streams if isinstance(s, DashAudio)]

    # 1. 视频清晰度范围过滤
    videos = filter_by_quality(videos, filter_option)

    # 2. 杜比/HDR/HiRes 过滤（视频与音频同步过滤）
    videos, audios = filter_special_streams(videos, audios, filter_option)

    # 3. 音频清晰度范围过滤（使用 sort key 处理非单调值）
    audios = _filter_audio_by_quality(audios, filter_option)

    if not videos:
        raise ValueError("无符合条件的视频流（清晰度范围或杜比/HDR 过滤后为空）")

    # 4. 编码偏好排序
    videos = sort_by_codecs(videos, filter_option.video_codecs)

    # 5. 取最佳视频：quality 优先（降序），同 quality 取编码偏好靠前
    best_video: DashVideo = max(
        videos,
        key=lambda v: (v.quality.value, -_codec_index(v, filter_option.video_codecs)),
    )

    # 6. 取最佳音频：按 sort key 取最大（无声视频时 audio 为 None）
    best_audio: Optional[DashAudio] = (
        max(audios, key=lambda a: _audio_sort_key(a.quality)) if audios else None
    )

    return VideoAudioStream(video=best_video, audio=best_audio)


def sort_by_cdn(urls: list[str]) -> list[str]:
    """按 CDN 前缀优先级排序 URL。

    优先级顺序：``upos-`` (服务商 CDN) > ``cn-`` (自建 CDN) > ``mcdn`` > 其他。
    实现为按 score 升序排序（upos=0, cn=1, mcdn=2, 其他=3），同 score 保持原顺序。

    Args:
        urls: 待排序的 URL 列表。

    Returns:
        排序后的 URL 列表（新列表，不修改原列表）。
    """
    return sorted(urls, key=_cdn_score)


def sort_all_urls(main_url: str, backup_url: list[str]) -> list[str]:
    """合并主 URL 与备用 URL 列表并按 CDN 优先级排序。

    Args:
        main_url: 主下载 URL。
        backup_url: 备用下载 URL 列表。

    Returns:
        合并并排序后的 URL 列表（主 URL 与备用 URL 一起参与排序）。
    """
    all_urls: list[str] = [main_url] + list(backup_url)
    return sort_by_cdn(all_urls)


def _audio_sort_key(quality: Quality) -> int:
    """音频清晰度排序键。

    HiRes(30251) 与 Dolby(30255) 的原始 qn 值小于 High(30280=192k)，
    但实际质量更高。通过 +40 偏移使其排序后位于 192k 之后，
    最终顺序为 High < HiRes < Dolby，与 Rust 参考实现 ``as_sort_key`` 一致。

    Args:
        quality: 音频清晰度枚举。

    Returns:
        排序用的 int 键值。
    """
    if quality in (Quality.HiResAudio, Quality.DolbyAudio):
        return quality.value + 40
    return quality.value


def _filter_audio_by_quality(
    audios: list[DashAudio],
    filter_option: FilterOption,
) -> list[DashAudio]:
    """按音频清晰度范围 [min, max] 过滤。

    使用 :func:`_audio_sort_key` 处理非单调的 qn 值，确保
    High(192k) < HiRes < Dolby 的逻辑顺序。

    Args:
        audios: 待过滤的音频流列表。
        filter_option: 筛选选项，使用其中的 audio_min_quality / audio_max_quality。

    Returns:
        过滤后的音频流列表（保持原顺序）。
    """
    min_key: int = _audio_sort_key(filter_option.audio_min_quality)
    max_key: int = _audio_sort_key(filter_option.audio_max_quality)
    return [a for a in audios if min_key <= _audio_sort_key(a.quality) <= max_key]


def _codec_index(video: DashVideo, codecs: list[str]) -> int:
    """返回视频编码在偏好列表中的位置。

    Args:
        video: 视频流。
        codecs: 编码偏好列表。

    Returns:
        编码在列表中的索引（0 最优先）；未在列表中返回 ``len(codecs)``（排最后）。
    """
    normalized = _normalize_video_codec(video.codecs)
    if normalized and normalized in codecs:
        return codecs.index(normalized)
    return len(codecs)


def _normalize_video_codec(codecs: str) -> str:
    """将视频编码字符串标准化为 avc / hevc / av1 之一。

    B 站 playurl 的 ``codecs`` 字段可能是完整编码字符串
    （如 ``avc1.640028`` / ``hev1.1.6.L120.B0`` / ``av01.0.04M.08``），
    也可能是 ``codecid`` 数值字符串（``7`` / ``12`` / ``13``）。
    本函数统一映射为 ``avc`` / ``hevc`` / ``av1``。

    Args:
        codecs: 原始编码字符串。

    Returns:
        标准化后的编码标识，无法识别返回空字符串。
    """
    if not codecs:
        return ""
    codecs_lower = codecs.lower().strip()
    if not codecs_lower:
        return ""
    # codecid 数值字符串
    if codecs_lower == "7":
        return "avc"
    if codecs_lower == "12":
        return "hevc"
    if codecs_lower == "13":
        return "av1"
    # 完整编码字符串前缀匹配
    if codecs_lower.startswith("avc"):
        return "avc"
    if codecs_lower.startswith("hev"):
        return "hevc"
    if codecs_lower.startswith("av01") or codecs_lower.startswith("av1"):
        return "av1"
    return ""


def _cdn_score(url: str) -> int:
    """计算 URL 的 CDN 优先级分数。

    优先级：``upos-`` (0) > ``cn-`` (1) > ``mcdn`` (2) > 其他 (3)。
    分数越小优先级越高。

    Args:
        url: 待评分的 URL。

    Returns:
        CDN 优先级分数（0-3）。
    """
    if "upos-" in url:
        return 0
    if "cn-" in url:
        return 1
    if "mcdn" in url:
        return 2
    return 3


def _extract_single_stream_url(stream: DashStream) -> str:
    """从单混合流对象中提取 url 字段。

    FlvStream / Html5Mp4Stream / EpisodeTryMp4Stream 均有 ``url`` 字段，
    DashVideo / DashAudio 有 ``base_url`` 字段（不应出现在单混合流分支）。

    Args:
        stream: 单混合流对象。

    Returns:
        下载 URL，无法提取返回空字符串。
    """
    if isinstance(stream, (FlvStream, Html5Mp4Stream, EpisodeTryMp4Stream)):
        return stream.url
    # DashVideo / DashAudio 不应进入此分支，兜底返回空
    return ""
