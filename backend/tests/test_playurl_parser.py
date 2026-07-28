"""playurl 响应解析器单元测试。

覆盖 ``bilibili/stream_types.py`` 的 :func:`parse_playurl` 与辅助函数：
- FLV 单流（``format=flv_*`` + ``durl``）
- HTML5 MP4 单流（``format=mp4_*`` + ``is_html5=True``）
- 剧集试看 MP4 单流（``format=mp4_*`` + ``is_html5`` 非 True）
- DASH 分离流（``dash`` 字段，含 video / audio / flac / dolby）
- 异常路径（非 dict / 无流字段 / 缺 url 等）

测试隔离：所有测试用例使用静态构造的 dict 输入，不调用任何网络 API。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# 注入 backend 目录到 sys.path
_BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from plugins.bilibili_toolkit_builtin.bilibili.stream_types import (  # noqa: E402
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


# ---------------------------------------------------------------------------
# FLV 单流解析
# ---------------------------------------------------------------------------


def test_parse_flv_stream() -> None:
    """format=flv_* + durl → FlvStream，stream_type=Flv。"""
    data = {
        "format": "flv720",
        "durl": [{"url": "https://example.com/flv.flv", "size": 12345}],
    }
    result = parse_playurl(data)
    assert result.stream_type == StreamType.Flv
    assert len(result.streams) == 1
    assert isinstance(result.streams[0], FlvStream)
    assert result.streams[0].url == "https://example.com/flv.flv"


def test_parse_flv_missing_url_raises() -> None:
    """FLV 流缺 url 字段时抛 ValueError。"""
    data = {"format": "flv720", "durl": [{"size": 12345}]}
    with pytest.raises(ValueError, match="FLV"):
        parse_playurl(data)


# ---------------------------------------------------------------------------
# HTML5 MP4 单流解析
# ---------------------------------------------------------------------------


def test_parse_html5_mp4_stream() -> None:
    """format=mp4_* + is_html5=True → Html5Mp4Stream。"""
    data = {
        "format": "mp4",
        "is_html5": True,
        "durl": [{"url": "https://example.com/html5.mp4", "size": 12345}],
    }
    result = parse_playurl(data)
    assert result.stream_type == StreamType.Html5Mp4
    assert len(result.streams) == 1
    assert isinstance(result.streams[0], Html5Mp4Stream)
    assert result.streams[0].url == "https://example.com/html5.mp4"


# ---------------------------------------------------------------------------
# 剧集试看 MP4 单流解析
# ---------------------------------------------------------------------------


def test_parse_episode_try_mp4_stream() -> None:
    """format=mp4_* + is_html5 非 True → EpisodeTryMp4Stream。"""
    data = {
        "format": "mp4",
        "is_html5": False,
        "durl": [{"url": "https://example.com/episode.mp4", "size": 12345}],
    }
    result = parse_playurl(data)
    assert result.stream_type == StreamType.EpisodeTryMp4
    assert len(result.streams) == 1
    assert isinstance(result.streams[0], EpisodeTryMp4Stream)
    assert result.streams[0].url == "https://example.com/episode.mp4"


# ---------------------------------------------------------------------------
# DASH 分离流解析
# ---------------------------------------------------------------------------


def test_parse_dash_video_and_audio() -> None:
    """dash 字段含 video + audio → 多个 DashVideo + DashAudio。"""
    data = {
        "dash": {
            "video": [
                {
                    "id": 80,
                    "baseUrl": "https://example.com/video_1080p.m4s",
                    "codecs": "avc1.640028",
                    "backupUrl": ["https://backup.example.com/v.m4s"],
                },
                {
                    "id": 64,
                    "baseUrl": "https://example.com/video_720p.m4s",
                    "codecs": "avc1.640028",
                },
            ],
            "audio": [
                {
                    "id": 30280,
                    "baseUrl": "https://example.com/audio_192k.m4s",
                    "codecs": "mp4a.40.2",
                },
            ],
        }
    }
    result = parse_playurl(data)
    assert result.stream_type == StreamType.DashVideo
    # 2 视频 + 1 音频
    videos = [s for s in result.streams if isinstance(s, DashVideo)]
    audios = [s for s in result.streams if isinstance(s, DashAudio)]
    assert len(videos) == 2
    assert len(audios) == 1
    # 视频流字段
    assert videos[0].id == 80
    assert videos[0].base_url == "https://example.com/video_1080p.m4s"
    assert videos[0].quality == Quality.Quality1080p
    assert videos[0].codecs == "avc1.640028"
    assert videos[0].backup_url == ["https://backup.example.com/v.m4s"]


def test_parse_dash_with_flac_hires_audio() -> None:
    """dash.flac.audio 字段 → HiRes 音频流。"""
    data = {
        "dash": {
            "video": [
                {
                    "id": 80,
                    "baseUrl": "https://example.com/v.m4s",
                    "codecs": "avc1.640028",
                },
            ],
            "audio": [
                {
                    "id": 30280,
                    "baseUrl": "https://example.com/normal.m4s",
                    "codecs": "mp4a.40.2",
                },
            ],
            "flac": {
                "audio": {
                    "id": 30251,
                    "baseUrl": "https://example.com/hires.m4s",
                    "codecs": "flac",
                },
            },
        }
    }
    result = parse_playurl(data)
    audios = [s for s in result.streams if isinstance(s, DashAudio)]
    # 普通音频 + HiRes 音频
    assert len(audios) == 2
    hires = next(a for a in audios if a.quality == Quality.HiResAudio)
    assert hires.base_url == "https://example.com/hires.m4s"


def test_parse_dash_with_dolby_audio() -> None:
    """dash.dolby.audio 数组 → 杜比全景声音频流。"""
    data = {
        "dash": {
            "video": [
                {
                    "id": 80,
                    "baseUrl": "https://example.com/v.m4s",
                    "codecs": "avc1.640028",
                },
            ],
            "audio": [],
            "dolby": {
                "audio": [
                    {
                        "id": 30255,
                        "baseUrl": "https://example.com/dolby.m4s",
                        "codecs": "ec-3",
                    },
                ],
            },
        }
    }
    result = parse_playurl(data)
    audios = [s for s in result.streams if isinstance(s, DashAudio)]
    assert len(audios) == 1
    assert audios[0].quality == Quality.DolbyAudio
    assert audios[0].base_url == "https://example.com/dolby.m4s"


def test_parse_dash_skips_invalid_video_entries() -> None:
    """缺 baseUrl / id 字段的视频流条目应被跳过。"""
    data = {
        "dash": {
            "video": [
                # 缺 baseUrl
                {"id": 80, "codecs": "avc1.640028"},
                # id 非 int
                {"baseUrl": "https://example.com/v.m4s", "id": "80"},
                # 有效
                {"id": 80, "baseUrl": "https://example.com/valid.m4s", "codecs": "avc"},
            ],
            "audio": [],
        }
    }
    result = parse_playurl(data)
    videos = [s for s in result.streams if isinstance(s, DashVideo)]
    assert len(videos) == 1
    assert videos[0].base_url == "https://example.com/valid.m4s"


def test_parse_dash_snake_case_field_names() -> None:
    """snake_case 字段名（base_url / backup_url）也应被识别。"""
    data = {
        "dash": {
            "video": [
                {
                    "id": 80,
                    "base_url": "https://example.com/v.m4s",
                    "codecs": "avc1.640028",
                    "backup_url": ["https://backup.example.com/v.m4s"],
                },
            ],
            "audio": [],
        }
    }
    result = parse_playurl(data)
    videos = [s for s in result.streams if isinstance(s, DashVideo)]
    assert len(videos) == 1
    assert videos[0].base_url == "https://example.com/v.m4s"
    assert videos[0].backup_url == ["https://backup.example.com/v.m4s"]


def test_parse_dash_codecid_string_fallback() -> None:
    """缺 codecs 字段时使用 codecid 数字字符串作为兜底。"""
    data = {
        "dash": {
            "video": [
                {
                    "id": 80,
                    "baseUrl": "https://example.com/v.m4s",
                    "codecid": "7",
                },
            ],
            "audio": [],
        }
    }
    result = parse_playurl(data)
    videos = [s for s in result.streams if isinstance(s, DashVideo)]
    assert len(videos) == 1
    assert videos[0].codecs == "7"


def test_parse_dash_unrecognized_quality_skipped() -> None:
    """qn 值未在 Quality 枚举中时跳过该视频流。"""
    data = {
        "dash": {
            "video": [
                # 9999 不在 Quality 枚举中
                {"id": 9999, "baseUrl": "https://example.com/v.m4s", "codecs": "avc"},
                {"id": 80, "baseUrl": "https://example.com/valid.m4s", "codecs": "avc"},
            ],
            "audio": [],
        }
    }
    result = parse_playurl(data)
    videos = [s for s in result.streams if isinstance(s, DashVideo)]
    assert len(videos) == 1
    assert videos[0].quality == Quality.Quality1080p


def test_parse_dash_empty_dash_dict_raises() -> None:
    """dash 字段为空 dict 时（无 video/audio）抛 ValueError。"""
    data = {"dash": {}}
    with pytest.raises(ValueError, match="无可用流字段"):
        parse_playurl(data)


# ---------------------------------------------------------------------------
# 异常路径
# ---------------------------------------------------------------------------


def test_parse_playurl_non_dict_raises() -> None:
    """非 dict 输入抛 ValueError。"""
    with pytest.raises(ValueError, match="必须是 dict"):
        parse_playurl("not a dict")  # type: ignore[arg-type]


def test_parse_playurl_empty_dict_raises() -> None:
    """空 dict 输入抛 ValueError（无任何流字段）。"""
    with pytest.raises(ValueError, match="无可用流字段"):
        parse_playurl({})


def test_parse_playurl_format_only_no_durl_raises() -> None:
    """有 format 但无 durl 与 dash 时抛 ValueError。"""
    with pytest.raises(ValueError, match="无可用流字段"):
        parse_playurl({"format": "flv720"})


# ---------------------------------------------------------------------------
# backupUrl 字段提取
# ---------------------------------------------------------------------------


def test_parse_dash_backup_url_as_json_string() -> None:
    """backupUrl 为 JSON 字符串时应转为单元素列表。"""
    data = {
        "dash": {
            "video": [
                {
                    "id": 80,
                    "baseUrl": "https://example.com/v.m4s",
                    "codecs": "avc",
                    "backupUrl": "https://backup.example.com/v.m4s",
                },
            ],
            "audio": [],
        }
    }
    result = parse_playurl(data)
    videos = [s for s in result.streams if isinstance(s, DashVideo)]
    assert videos[0].backup_url == ["https://backup.example.com/v.m4s"]


def test_parse_dash_backup_url_filters_non_string_entries() -> None:
    """backupUrl 列表中的非字符串元素应被过滤。"""
    data = {
        "dash": {
            "video": [
                {
                    "id": 80,
                    "baseUrl": "https://example.com/v.m4s",
                    "codecs": "avc",
                    "backupUrl": ["https://a.example.com/v.m4s", 123, "", None],
                },
            ],
            "audio": [],
        }
    }
    result = parse_playurl(data)
    videos = [s for s in result.streams if isinstance(s, DashVideo)]
    assert videos[0].backup_url == ["https://a.example.com/v.m4s"]


# ---------------------------------------------------------------------------
# Quality 枚举别名
# ---------------------------------------------------------------------------


def test_quality_4k_alias_shares_value_with_1440p() -> None:
    """Quality4K 与 Quality1440p 共享值 120（Enum 自动别名）。"""
    assert Quality.Quality4K == Quality.Quality1440p
    assert Quality.Quality4K.value == 120
