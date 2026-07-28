"""流分析器单元测试。

覆盖 ``analyzer.py`` 的：
- :func:`filter_by_quality`：视频清晰度范围过滤
- :func:`filter_special_streams`：杜比/HDR/HiRes 过滤
- :func:`sort_by_codecs`：编码偏好排序
- :func:`select_best_stream`：综合选择最佳流
- :func:`sort_by_cdn` / :func:`sort_all_urls`：CDN 优先级排序
- :class:`FilterOption`：默认值与可变性
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# 注入 backend 目录到 sys.path
_BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from plugins.bilibili_toolkit_builtin.analyzer import (  # noqa: E402
    FilterOption,
    MixedStream,
    VideoAudioStream,
    filter_by_quality,
    filter_special_streams,
    select_best_stream,
    sort_all_urls,
    sort_by_cdn,
    sort_by_codecs,
)
from plugins.bilibili_toolkit_builtin.bilibili.stream_types import (  # noqa: E402
    DashAudio,
    DashStreams,
    DashVideo,
    EpisodeTryMp4Stream,
    FlvStream,
    Html5Mp4Stream,
    Quality,
    StreamType,
)


# ---------------------------------------------------------------------------
# 辅助构造函数
# ---------------------------------------------------------------------------


def _make_video(
    qn: int = 80,
    codecs: str = "avc1.640028",
    base_url: str = "https://example.com/v.m4s",
) -> DashVideo:
    """构造 DashVideo 实例，简化测试用例构造。"""
    return DashVideo(
        id=qn,
        base_url=base_url,
        backup_url=[],
        quality=Quality(qn),
        codecs=codecs,
    )


def _make_audio(
    qn: int = 30280,
    codecs: str = "mp4a.40.2",
    base_url: str = "https://example.com/a.m4s",
) -> DashAudio:
    """构造 DashAudio 实例，简化测试用例构造。"""
    return DashAudio(
        id=qn,
        base_url=base_url,
        backup_url=[],
        quality=Quality(qn),
        codecs=codecs,
    )


# ---------------------------------------------------------------------------
# FilterOption 默认值
# ---------------------------------------------------------------------------


def test_filter_option_defaults() -> None:
    """FilterOption 默认值与 schema.json 描述一致。"""
    opt = FilterOption()
    assert opt.video_max_quality == Quality.Quality8K
    assert opt.video_min_quality == Quality.Quality360p
    assert opt.video_codecs == ["avc", "hevc", "av1"]
    assert opt.audio_max_quality == Quality.HiResAudio
    assert opt.audio_min_quality == Quality.HighAudio
    assert opt.audio_codecs == ["mp4a", "ec3"]
    assert opt.no_dolby_video is False
    assert opt.no_dolby_audio is False
    assert opt.no_hdr is False
    assert opt.no_hires is False


# ---------------------------------------------------------------------------
# filter_by_quality
# ---------------------------------------------------------------------------


def test_filter_by_quality_keeps_in_range() -> None:
    """清晰度在 [min, max] 闭区间内的视频流保留。"""
    videos = [_make_video(80), _make_video(64), _make_video(32)]
    opt = FilterOption(
        video_min_quality=Quality.Quality720p,
        video_max_quality=Quality.Quality1080p,
    )
    filtered = filter_by_quality(videos, opt)
    assert len(filtered) == 2
    assert {v.quality for v in filtered} == {Quality.Quality1080p, Quality.Quality720p}


def test_filter_by_quality_empty_input() -> None:
    """空列表输入返回空列表。"""
    assert filter_by_quality([], FilterOption()) == []


# ---------------------------------------------------------------------------
# sort_by_codecs
# ---------------------------------------------------------------------------


def test_sort_by_codecs_orders_by_preference() -> None:
    """按编码偏好数组顺序排序，未在列表中的排最后。"""
    videos = [
        _make_video(80, codecs="av01.0.04M.08"),
        _make_video(80, codecs="hev1.1.6.L120.B0"),
        _make_video(80, codecs="avc1.640028"),
        _make_video(80, codecs="vp9"),  # 未在偏好列表中
    ]
    sorted_videos = sort_by_codecs(videos, ["avc", "hevc", "av1"])
    # avc 第一，hevc 第二，av1 第三，vp9 最后
    assert sorted_videos[0].codecs == "avc1.640028"
    assert sorted_videos[1].codecs == "hev1.1.6.L120.B0"
    assert sorted_videos[2].codecs == "av01.0.04M.08"
    assert sorted_videos[3].codecs == "vp9"


def test_sort_by_codecs_stable_within_same_codec() -> None:
    """同编码保持原顺序（稳定排序）。"""
    videos = [
        _make_video(80, codecs="avc1.640028", base_url="https://a.com/v.m4s"),
        _make_video(80, codecs="avc1.640028", base_url="https://b.com/v.m4s"),
    ]
    sorted_videos = sort_by_codecs(videos, ["avc"])
    assert sorted_videos[0].base_url == "https://a.com/v.m4s"
    assert sorted_videos[1].base_url == "https://b.com/v.m4s"


# ---------------------------------------------------------------------------
# filter_special_streams
# ---------------------------------------------------------------------------


def test_filter_special_streams_no_dolby_video() -> None:
    """no_dolby_video=True 时过滤 DolbyVision 视频流。"""
    videos = [
        _make_video(126, codecs="dav1.10.01"),  # DolbyVision 别名
        _make_video(80, codecs="avc1.640028"),
    ]
    audios = []
    opt = FilterOption(no_dolby_video=True)
    filtered_videos, _ = filter_special_streams(videos, audios, opt)
    assert len(filtered_videos) == 1
    assert filtered_videos[0].quality == Quality.Quality1080p


def test_filter_special_streams_no_hdr() -> None:
    """no_hdr=True 时过滤 HDR 视频流。"""
    videos = [
        _make_video(125, codecs="avc1.640028"),  # HDR 别名
        _make_video(80, codecs="avc1.640028"),
    ]
    opt = FilterOption(no_hdr=True)
    filtered_videos, _ = filter_special_streams(videos, [], opt)
    assert len(filtered_videos) == 1
    assert filtered_videos[0].quality == Quality.Quality1080p


def test_filter_special_streams_no_dolby_audio() -> None:
    """no_dolby_audio=True 时过滤 DolbyAudio 音频流。"""
    audios = [
        _make_audio(30255, codecs="ec-3"),  # Dolby
        _make_audio(30280, codecs="mp4a.40.2"),  # High
    ]
    opt = FilterOption(no_dolby_audio=True)
    _, filtered_audios = filter_special_streams([], audios, opt)
    assert len(filtered_audios) == 1
    assert filtered_audios[0].quality == Quality.HighAudio


def test_filter_special_streams_no_hires() -> None:
    """no_hires=True 时过滤 HiResAudio 音频流。"""
    audios = [
        _make_audio(30251, codecs="flac"),  # HiRes
        _make_audio(30280, codecs="mp4a.40.2"),  # High
    ]
    opt = FilterOption(no_hires=True)
    _, filtered_audios = filter_special_streams([], audios, opt)
    assert len(filtered_audios) == 1
    assert filtered_audios[0].quality == Quality.HighAudio


# ---------------------------------------------------------------------------
# select_best_stream
# ---------------------------------------------------------------------------


def test_select_best_stream_dash_returns_video_audio_stream() -> None:
    """DASH 流返回 VideoAudioStream，含最佳视频与最佳音频。"""
    dash_streams = DashStreams(
        stream_type=StreamType.DashVideo,
        streams=[
            _make_video(64, codecs="avc1.640028", base_url="https://a.com/720p.m4s"),
            _make_video(80, codecs="avc1.640028", base_url="https://a.com/1080p.m4s"),
            _make_audio(30280, base_url="https://a.com/192k.m4s"),
            _make_audio(30251, base_url="https://a.com/hires.m4s"),
        ],
    )
    result = select_best_stream(dash_streams, FilterOption())
    assert isinstance(result, VideoAudioStream)
    # 最高清晰度视频
    assert result.video.quality == Quality.Quality1080p
    # 最高音质（HiRes > High via +40 偏移）
    assert result.audio is not None
    assert result.audio.quality == Quality.HiResAudio


def test_select_best_stream_dash_no_audio() -> None:
    """无声视频（无音频流）返回 audio=None。"""
    dash_streams = DashStreams(
        stream_type=StreamType.DashVideo,
        streams=[_make_video(80, codecs="avc1.640028")],
    )
    result = select_best_stream(dash_streams, FilterOption())
    assert isinstance(result, VideoAudioStream)
    assert result.audio is None
    assert result.video.quality == Quality.Quality1080p


def test_select_best_stream_dash_prefers_avc_over_hevc() -> None:
    """同清晰度下按编码偏好选择（avc > hevc > av1）。"""
    dash_streams = DashStreams(
        stream_type=StreamType.DashVideo,
        streams=[
            _make_video(80, codecs="hev1.1.6.L120.B0"),
            _make_video(80, codecs="avc1.640028"),
        ],
    )
    result = select_best_stream(dash_streams, FilterOption())
    assert result.video.codecs == "avc1.640028"


def test_select_best_stream_flv_returns_mixed_stream() -> None:
    """FLV 单流返回 MixedStream。"""
    dash_streams = DashStreams(
        stream_type=StreamType.Flv,
        streams=[FlvStream(url="https://example.com/flv.flv")],
    )
    result = select_best_stream(dash_streams, FilterOption())
    assert isinstance(result, MixedStream)
    assert result.url == "https://example.com/flv.flv"


def test_select_best_stream_html5_mp4_returns_mixed_stream() -> None:
    """HTML5 MP4 单流返回 MixedStream。"""
    dash_streams = DashStreams(
        stream_type=StreamType.Html5Mp4,
        streams=[Html5Mp4Stream(url="https://example.com/html5.mp4")],
    )
    result = select_best_stream(dash_streams, FilterOption())
    assert isinstance(result, MixedStream)
    assert result.url == "https://example.com/html5.mp4"


def test_select_best_stream_episode_try_mp4_returns_mixed_stream() -> None:
    """剧集试看 MP4 单流返回 MixedStream。"""
    dash_streams = DashStreams(
        stream_type=StreamType.EpisodeTryMp4,
        streams=[EpisodeTryMp4Stream(url="https://example.com/episode.mp4")],
    )
    result = select_best_stream(dash_streams, FilterOption())
    assert isinstance(result, MixedStream)
    assert result.url == "https://example.com/episode.mp4"


def test_select_best_stream_empty_mixed_raises() -> None:
    """单混合流列表为空时抛 ValueError。"""
    dash_streams = DashStreams(stream_type=StreamType.Flv, streams=[])
    with pytest.raises(ValueError, match="单混合流列表为空"):
        select_best_stream(dash_streams, FilterOption())


def test_select_best_stream_no_matching_video_raises() -> None:
    """清晰度范围过滤后无视频流时抛 ValueError。"""
    dash_streams = DashStreams(
        stream_type=StreamType.DashVideo,
        streams=[_make_video(80, codecs="avc1.640028")],
    )
    opt = FilterOption(
        video_min_quality=Quality.Quality8K,
        video_max_quality=Quality.Quality8K,
    )
    with pytest.raises(ValueError, match="无符合条件的视频流"):
        select_best_stream(dash_streams, opt)


# ---------------------------------------------------------------------------
# sort_by_cdn / sort_all_urls
# ---------------------------------------------------------------------------


def test_sort_by_cdn_priority_upos_first() -> None:
    """CDN 优先级：upos- > cn- > mcdn > 其他。"""
    urls = [
        "https://mcdn.example.com/v.m4s",
        "https://other.example.com/v.m4s",
        "https://upos-sz.example.com/v.m4s",
        "https://cn-example.example.com/v.m4s",
    ]
    sorted_urls = sort_by_cdn(urls)
    assert sorted_urls[0] == "https://upos-sz.example.com/v.m4s"
    assert sorted_urls[1] == "https://cn-example.example.com/v.m4s"
    assert sorted_urls[2] == "https://mcdn.example.com/v.m4s"
    assert sorted_urls[3] == "https://other.example.com/v.m4s"


def test_sort_by_cdn_preserves_order_within_same_priority() -> None:
    """同优先级保持原顺序（稳定排序）。"""
    urls = [
        "https://upos-a.example.com/v.m4s",
        "https://upos-b.example.com/v.m4s",
    ]
    sorted_urls = sort_by_cdn(urls)
    assert sorted_urls == urls


def test_sort_all_urls_merges_main_and_backup() -> None:
    """主 URL 与备用 URL 合并后按 CDN 优先级排序。"""
    # 注意：_cdn_score 通过子串匹配，"upos-" 需带连字符才匹配
    main_url = "https://mcdn.example.com/v.m4s"
    backup_urls = ["https://upos-sz-mirror.example.com/v.m4s"]
    sorted_urls = sort_all_urls(main_url, backup_urls)
    # upos- 优先级最高（score=0），应排第一
    assert sorted_urls[0] == "https://upos-sz-mirror.example.com/v.m4s"
    assert sorted_urls[1] == "https://mcdn.example.com/v.m4s"


def test_sort_all_urls_empty_backup() -> None:
    """空 backup_url 时仅返回主 URL。"""
    sorted_urls = sort_all_urls("https://upos.example.com/v.m4s", [])
    assert sorted_urls == ["https://upos.example.com/v.m4s"]
