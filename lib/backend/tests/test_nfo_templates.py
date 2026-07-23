"""NFO 元数据模板单元测试。

覆盖 4 个 NFO 渲染模块的字段完整性与边界处理：
- :mod:`nfo.movie`：``render_movie_nfo`` / ``format_plot`` / ``format_pubtime``
- :mod:`nfo.tvshow`：``render_tvshow_nfo``
- :mod:`nfo.episode`：``render_episode_nfo``
- :mod:`nfo.upper`：``render_upper_nfo``

校验点：
1. XML 声明、根元素标签、UTF-8 编码声明完整
2. 字段映射正确（title / plot / actor / genre / country / year / premiered /
   studio / uniqueid）
3. XML 转义处理（``<`` / ``>`` / ``&`` / ``"`` 等）
4. 边界处理：空 desc、空 tags、pubtime <= 0
5. Episode NFO 的 season=1、episode=page.page、uniqueid=``{aid}_{cid}``
6. Upper NFO 的 ``<Person>`` 根元素与 mid/upper_name 字段
"""

from __future__ import annotations

import sys
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

# 注入 backend 目录到 sys.path，便于直接 import 被测模块
_BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from plugins.bilibili_toolkit_builtin.bilibili.video import (  # noqa: E402
    Page,
    VideoInfo,
)
from plugins.bilibili_toolkit_builtin.nfo.episode import (  # noqa: E402
    render_episode_nfo,
)
from plugins.bilibili_toolkit_builtin.nfo.movie import (  # noqa: E402
    format_plot,
    format_pubtime,
    render_movie_nfo,
)
from plugins.bilibili_toolkit_builtin.nfo.tvshow import (  # noqa: E402
    render_tvshow_nfo,
)
from plugins.bilibili_toolkit_builtin.nfo.upper import (  # noqa: E402
    render_upper_nfo,
)


# ---------------------------------------------------------------------------
# fixture：构造标准 VideoInfo / Page
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_video() -> VideoInfo:
    """构造一个含完整字段的 VideoInfo 测试样本。"""
    return VideoInfo(
        bvid="BV1gLfnY8E6D",
        aid=113280255938624,
        title="测试视频标题",
        cover="https://example.com/cover.jpg",
        upper_mid=12345,
        upper_name="测试UP主",
        upper_face="https://example.com/face.jpg",
        pages=[
            Page(cid=111, page=1, name="分P一", duration=120, width=1920, height=1080),
            Page(cid=222, page=2, name="分P二", duration=240, width=1920, height=1080),
        ],
        pubtime=1700000000,  # 2023-11-14 22:13:20 UTC
        ctime=1699999000,
        desc="这是视频简介",
        tags=["科技", "知识"],
    )


@pytest.fixture
def sample_page() -> Page:
    """构造一个 Page 测试样本。"""
    return Page(
        cid=111,
        page=1,
        name="分P一",
        duration=120,
        width=1920,
        height=1080,
    )


# ---------------------------------------------------------------------------
# format_plot 测试
# ---------------------------------------------------------------------------


def test_format_plot_with_desc():
    """有 desc 时应拼接简介 + 链接。"""
    result = format_plot("视频简介", "BV1xx")
    assert "视频简介" in result
    assert "https://www.bilibili.com/video/BV1xx/" in result
    # 简介在前，链接在后
    assert result.index("视频简介") < result.index("https://")


def test_format_plot_empty_desc():
    """desc 为空字符串时应仅保留链接，避免前导空格。"""
    result = format_plot("", "BV1xx")
    assert result == "https://www.bilibili.com/video/BV1xx/"


def test_format_plot_xml_escape():
    """desc 含 XML 特殊字符时应做转义（``xml.sax.saxutils.escape`` 默认只转义 < > &）。"""
    result = format_plot("a<b>&c\"d", "BV1xx")
    assert "&lt;" in result
    assert "&gt;" in result
    assert "&amp;" in result
    # 注意：``escape`` 默认 ``quote=False``，``"`` 不被转义为 &quot;
    assert "&quot;" not in result
    assert '"' in result


def test_format_plot_url_not_escaped():
    """正常 URL 中的 / 与 : 不应被转义。"""
    result = format_plot("", "BV1xx")
    assert "/" in result
    assert ":" in result


# ---------------------------------------------------------------------------
# format_pubtime 测试
# ---------------------------------------------------------------------------


def test_format_pubtime_normal():
    """正常时间戳应返回 (year_str, YYYY-MM-DD) 元组。"""
    # 1700000000 在本地时区可能不同，校验格式即可
    year_str, premiered_str = format_pubtime(1700000000)
    assert len(year_str) == 4
    assert year_str.isdigit()
    # YYYY-MM-DD 格式
    assert len(premiered_str) == 10
    assert premiered_str[4] == "-"
    assert premiered_str[7] == "-"


def test_format_pubtime_zero():
    """pubtime=0 时应返回空字符串元组。"""
    year_str, premiered_str = format_pubtime(0)
    assert year_str == ""
    assert premiered_str == ""


def test_format_pubtime_negative():
    """pubtime<0 时应返回空字符串元组。"""
    year_str, premiered_str = format_pubtime(-100)
    assert year_str == ""
    assert premiered_str == ""


def test_format_pubtime_year_consistency():
    """year_str 应与 premiered_str 前 4 字符一致。"""
    year_str, premiered_str = format_pubtime(1700000000)
    assert year_str == premiered_str[:4]


# ---------------------------------------------------------------------------
# render_movie_nfo 测试
# ---------------------------------------------------------------------------


def test_render_movie_nfo_xml_declaration(sample_video: VideoInfo):
    """Movie NFO 应以 XML 声明开头。"""
    nfo = render_movie_nfo(sample_video)
    assert nfo.startswith('<?xml version="1.0" encoding="UTF-8"?>\n')


def test_render_movie_nfo_root_element(sample_video: VideoInfo):
    """Movie NFO 根元素应为 <movie>。"""
    nfo = render_movie_nfo(sample_video)
    assert nfo.endswith("</movie>")
    # 用 ElementTree 校验 XML 合法性
    root = ET.fromstring(nfo)
    assert root.tag == "movie"


def test_render_movie_nfo_contains_title(sample_video: VideoInfo):
    """Movie NFO 应包含 <title> 子元素，内容与 VideoInfo.title 一致。"""
    nfo = render_movie_nfo(sample_video)
    root = ET.fromstring(nfo)
    assert root.findtext("title") == "测试视频标题"


def test_render_movie_nfo_contains_plot(sample_video: VideoInfo):
    """Movie NFO <plot> 应包含 desc 与视频链接。"""
    nfo = render_movie_nfo(sample_video)
    root = ET.fromstring(nfo)
    plot = root.findtext("plot") or ""
    assert "这是视频简介" in plot
    assert "https://www.bilibili.com/video/BV1gLfnY8E6D/" in plot


def test_render_movie_nfo_actor_block(sample_video: VideoInfo):
    """Movie NFO 应含 <actor> 子元素，name=UP主名、role=UP主。"""
    nfo = render_movie_nfo(sample_video)
    root = ET.fromstring(nfo)
    actor = root.find("actor")
    assert actor is not None
    assert actor.findtext("name") == "测试UP主"
    assert actor.findtext("role") == "UP主"


def test_render_movie_nfo_genre_from_first_tag(sample_video: VideoInfo):
    """Movie NFO <genre> 应取 tags[0]。"""
    nfo = render_movie_nfo(sample_video)
    root = ET.fromstring(nfo)
    assert root.findtext("genre") == "科技"


def test_render_movie_nfo_country_fixed(sample_video: VideoInfo):
    """Movie NFO <country> 固定为"中国"。"""
    nfo = render_movie_nfo(sample_video)
    root = ET.fromstring(nfo)
    assert root.findtext("country") == "中国"


def test_render_movie_nfo_year_and_premiered(sample_video: VideoInfo):
    """Movie NFO <year> 与 <premiered> 应来自 format_pubtime。"""
    nfo = render_movie_nfo(sample_video)
    root = ET.fromstring(nfo)
    year_str, premiered_str = format_pubtime(sample_video.pubtime)
    assert root.findtext("year") == year_str
    assert root.findtext("premiered") == premiered_str


def test_render_movie_nfo_studio_fixed(sample_video: VideoInfo):
    """Movie NFO <studio> 固定为"bilibili"。"""
    nfo = render_movie_nfo(sample_video)
    root = ET.fromstring(nfo)
    assert root.findtext("studio") == "bilibili"


def test_render_movie_nfo_uniqueid_aid(sample_video: VideoInfo):
    """Movie NFO <uniqueid type="bilibili"> 应为 AV 号。"""
    nfo = render_movie_nfo(sample_video)
    root = ET.fromstring(nfo)
    uid = root.find("uniqueid")
    assert uid is not None
    assert uid.get("type") == "bilibili"
    assert uid.text == str(sample_video.aid)


def test_render_movie_nfo_empty_tags(sample_video: VideoInfo):
    """tags 为空时 <genre> 应为空字符串。"""
    sample_video.tags = []
    nfo = render_movie_nfo(sample_video)
    root = ET.fromstring(nfo)
    assert root.findtext("genre") == ""


def test_render_movie_nfo_empty_desc(sample_video: VideoInfo):
    """desc 为空时 <plot> 应仅含链接。"""
    sample_video.desc = ""
    nfo = render_movie_nfo(sample_video)
    root = ET.fromstring(nfo)
    plot = root.findtext("plot") or ""
    assert plot == "https://www.bilibili.com/video/BV1gLfnY8E6D/"


def test_render_movie_nfo_zero_pubtime(sample_video: VideoInfo):
    """pubtime=0 时 <year> 与 <premiered> 应为空字符串。"""
    sample_video.pubtime = 0
    nfo = render_movie_nfo(sample_video)
    root = ET.fromstring(nfo)
    assert root.findtext("year") == ""
    assert root.findtext("premiered") == ""


def test_render_movie_nfo_xml_escape_title(sample_video: VideoInfo):
    """title 含 < > & 应做 XML 转义。"""
    sample_video.title = "a<b>&c"
    nfo = render_movie_nfo(sample_video)
    root = ET.fromstring(nfo)
    assert root.findtext("title") == "a<b>&c"


def test_render_movie_nfo_no_trailing_newline(sample_video: VideoInfo):
    """NFO 字符串结尾不应有换行。"""
    nfo = render_movie_nfo(sample_video)
    assert not nfo.endswith("\n")


# ---------------------------------------------------------------------------
# render_tvshow_nfo 测试
# ---------------------------------------------------------------------------


def test_render_tvshow_nfo_xml_declaration(sample_video: VideoInfo):
    """TVShow NFO 应以 XML 声明开头。"""
    nfo = render_tvshow_nfo(sample_video)
    assert nfo.startswith('<?xml version="1.0" encoding="UTF-8"?>\n')


def test_render_tvshow_nfo_root_element(sample_video: VideoInfo):
    """TVShow NFO 根元素应为 <tvshow>。"""
    nfo = render_tvshow_nfo(sample_video)
    assert nfo.endswith("</tvshow>")
    root = ET.fromstring(nfo)
    assert root.tag == "tvshow"


def test_render_tvshow_nfo_title(sample_video: VideoInfo):
    """TVShow NFO 应包含 <title> 子元素。"""
    nfo = render_tvshow_nfo(sample_video)
    root = ET.fromstring(nfo)
    assert root.findtext("title") == "测试视频标题"


def test_render_tvshow_nfo_actor_block(sample_video: VideoInfo):
    """TVShow NFO 应含 <actor> 子元素。"""
    nfo = render_tvshow_nfo(sample_video)
    root = ET.fromstring(nfo)
    actor = root.find("actor")
    assert actor is not None
    assert actor.findtext("name") == "测试UP主"
    assert actor.findtext("role") == "UP主"


def test_render_tvshow_nfo_genre_from_first_tag(sample_video: VideoInfo):
    """TVShow NFO <genre> 应取 tags[0]。"""
    nfo = render_tvshow_nfo(sample_video)
    root = ET.fromstring(nfo)
    assert root.findtext("genre") == "科技"


def test_render_tvshow_nfo_uniqueid_aid(sample_video: VideoInfo):
    """TVShow NFO <uniqueid type="bilibili"> 应为 AV 号。"""
    nfo = render_tvshow_nfo(sample_video)
    root = ET.fromstring(nfo)
    uid = root.find("uniqueid")
    assert uid is not None
    assert uid.get("type") == "bilibili"
    assert uid.text == str(sample_video.aid)


def test_render_tvshow_nfo_country_studio_fixed(sample_video: VideoInfo):
    """TVShow NFO <country> 与 <studio> 应为固定值。"""
    nfo = render_tvshow_nfo(sample_video)
    root = ET.fromstring(nfo)
    assert root.findtext("country") == "中国"
    assert root.findtext("studio") == "bilibili"


def test_render_tvshow_nfo_empty_tags(sample_video: VideoInfo):
    """tags 为空时 <genre> 应为空字符串。"""
    sample_video.tags = []
    nfo = render_tvshow_nfo(sample_video)
    root = ET.fromstring(nfo)
    assert root.findtext("genre") == ""


# ---------------------------------------------------------------------------
# render_episode_nfo 测试
# ---------------------------------------------------------------------------


def test_render_episode_nfo_xml_declaration(sample_video: VideoInfo, sample_page: Page):
    """Episode NFO 应以 XML 声明开头。"""
    nfo = render_episode_nfo(sample_video, sample_page)
    assert nfo.startswith('<?xml version="1.0" encoding="UTF-8"?>\n')


def test_render_episode_nfo_root_element(sample_video: VideoInfo, sample_page: Page):
    """Episode NFO 根元素应为 <episodedetails>。"""
    nfo = render_episode_nfo(sample_video, sample_page)
    assert nfo.endswith("</episodedetails>")
    root = ET.fromstring(nfo)
    assert root.tag == "episodedetails"


def test_render_episode_nfo_title_from_page(sample_video: VideoInfo, sample_page: Page):
    """Episode NFO <title> 应取 Page.name。"""
    nfo = render_episode_nfo(sample_video, sample_page)
    root = ET.fromstring(nfo)
    assert root.findtext("title") == "分P一"


def test_render_episode_nfo_season_always_one(sample_video: VideoInfo, sample_page: Page):
    """Episode NFO <season> 应固定为 1。"""
    nfo = render_episode_nfo(sample_video, sample_page)
    root = ET.fromstring(nfo)
    assert root.findtext("season") == "1"


def test_render_episode_nfo_episode_from_page(
    sample_video: VideoInfo, sample_page: Page
):
    """Episode NFO <episode> 应取 Page.page。"""
    nfo = render_episode_nfo(sample_video, sample_page)
    root = ET.fromstring(nfo)
    assert root.findtext("episode") == "1"


def test_render_episode_nfo_episode_second_page(sample_video: VideoInfo):
    """Page.page=2 时 <episode> 应为 2。"""
    page2 = Page(cid=222, page=2, name="分P二", duration=240, width=1920, height=1080)
    nfo = render_episode_nfo(sample_video, page2)
    root = ET.fromstring(nfo)
    assert root.findtext("episode") == "2"


def test_render_episode_nfo_plot(sample_video: VideoInfo, sample_page: Page):
    """Episode NFO <plot> 应含 desc 与链接。"""
    nfo = render_episode_nfo(sample_video, sample_page)
    root = ET.fromstring(nfo)
    plot = root.findtext("plot") or ""
    assert "这是视频简介" in plot
    assert "https://www.bilibili.com/video/BV1gLfnY8E6D/" in plot


def test_render_episode_nfo_aired(sample_video: VideoInfo, sample_page: Page):
    """Episode NFO <aired> 应为 YYYY-MM-DD 格式。"""
    nfo = render_episode_nfo(sample_video, sample_page)
    root = ET.fromstring(nfo)
    aired = root.findtext("aired") or ""
    _year, expected = format_pubtime(sample_video.pubtime)
    assert aired == expected
    assert len(aired) == 10


def test_render_episode_nfo_studio_fixed(sample_video: VideoInfo, sample_page: Page):
    """Episode NFO <studio> 固定为"bilibili"。"""
    nfo = render_episode_nfo(sample_video, sample_page)
    root = ET.fromstring(nfo)
    assert root.findtext("studio") == "bilibili"


def test_render_episode_nfo_uniqueid_aid_cid(
    sample_video: VideoInfo, sample_page: Page
):
    """Episode NFO <uniqueid type="bilibili"> 应为 {aid}_{cid}。"""
    nfo = render_episode_nfo(sample_video, sample_page)
    root = ET.fromstring(nfo)
    uid = root.find("uniqueid")
    assert uid is not None
    assert uid.get("type") == "bilibili"
    assert uid.text == f"{sample_video.aid}_{sample_page.cid}"


def test_render_episode_nfo_uniqueid_differs_per_page(
    sample_video: VideoInfo, sample_page: Page
):
    """不同分 P 的 uniqueid 应不同（cid 不同）。"""
    page2 = Page(cid=222, page=2, name="分P二", duration=240, width=1920, height=1080)
    nfo1 = render_episode_nfo(sample_video, sample_page)
    nfo2 = render_episode_nfo(sample_video, page2)
    uid1 = ET.fromstring(nfo1).find("uniqueid")
    uid2 = ET.fromstring(nfo2).find("uniqueid")
    assert uid1 is not None
    assert uid2 is not None
    assert uid1.text != uid2.text


def test_render_episode_nfo_no_year_element(
    sample_video: VideoInfo, sample_page: Page
):
    """Episode NFO 不应包含 <year> 元素（仅 <aired>）。"""
    nfo = render_episode_nfo(sample_video, sample_page)
    root = ET.fromstring(nfo)
    assert root.find("year") is None


def test_render_episode_nfo_zero_pubtime(sample_video: VideoInfo, sample_page: Page):
    """pubtime=0 时 <aired> 应为空字符串。"""
    sample_video.pubtime = 0
    nfo = render_episode_nfo(sample_video, sample_page)
    root = ET.fromstring(nfo)
    assert root.findtext("aired") == ""


def test_render_episode_nfo_no_actor_block(
    sample_video: VideoInfo, sample_page: Page
):
    """Episode NFO 不应含 <actor> 元素（UP 主信息在 tvshow.nfo 中）。"""
    nfo = render_episode_nfo(sample_video, sample_page)
    root = ET.fromstring(nfo)
    assert root.find("actor") is None


def test_render_episode_nfo_xml_escape_page_name(
    sample_video: VideoInfo, sample_page: Page
):
    """Page.name 含 XML 特殊字符时应转义。"""
    sample_page.name = "a<b>&c"
    nfo = render_episode_nfo(sample_video, sample_page)
    root = ET.fromstring(nfo)
    assert root.findtext("title") == "a<b>&c"


# ---------------------------------------------------------------------------
# render_upper_nfo 测试
# ---------------------------------------------------------------------------


def test_render_upper_nfo_xml_declaration():
    """Upper NFO 应以 XML 声明开头。"""
    nfo = render_upper_nfo(12345, "测试UP主")
    assert nfo.startswith('<?xml version="1.0" encoding="UTF-8"?>\n')


def test_render_upper_nfo_root_element():
    """Upper NFO 根元素应为 <Person>。"""
    nfo = render_upper_nfo(12345, "测试UP主")
    assert nfo.endswith("</Person>")
    root = ET.fromstring(nfo)
    assert root.tag == "Person"


def test_render_upper_nfo_title_is_upper_name():
    """Upper NFO <title> 应为 upper_name。"""
    nfo = render_upper_nfo(12345, "测试UP主")
    root = ET.fromstring(nfo)
    assert root.findtext("title") == "测试UP主"


def test_render_upper_nfo_uniqueid_is_mid():
    """Upper NFO <uniqueid type="bilibili"> 应为 upper_mid。"""
    nfo = render_upper_nfo(12345, "测试UP主")
    root = ET.fromstring(nfo)
    uid = root.find("uniqueid")
    assert uid is not None
    assert uid.get("type") == "bilibili"
    assert uid.text == "12345"


def test_render_upper_nfo_country_fixed():
    """Upper NFO <country> 固定为"中国"。"""
    nfo = render_upper_nfo(12345, "测试UP主")
    root = ET.fromstring(nfo)
    assert root.findtext("country") == "中国"


def test_render_upper_nfo_xml_escape_name():
    """upper_name 含 XML 特殊字符时应转义。"""
    nfo = render_upper_nfo(12345, "a<b>&c\"d")
    root = ET.fromstring(nfo)
    assert root.findtext("title") == 'a<b>&c"d'


def test_render_upper_nfo_empty_name():
    """upper_name 为空时 <title> 应为空字符串。"""
    nfo = render_upper_nfo(12345, "")
    root = ET.fromstring(nfo)
    assert root.findtext("title") == ""


def test_render_upper_nfo_mid_zero():
    """upper_mid=0 时 <uniqueid> 文本应为 "0"。"""
    nfo = render_upper_nfo(0, "测试UP主")
    root = ET.fromstring(nfo)
    uid = root.find("uniqueid")
    assert uid is not None
    assert uid.text == "0"


def test_render_upper_nfo_no_trailing_newline():
    """NFO 字符串结尾不应有换行。"""
    nfo = render_upper_nfo(12345, "测试UP主")
    assert not nfo.endswith("\n")


def test_render_upper_nfo_only_three_fields():
    """Upper NFO 应只含 title / uniqueid / country 三个子元素。"""
    nfo = render_upper_nfo(12345, "测试UP主")
    root = ET.fromstring(nfo)
    children = [child.tag for child in root]
    assert set(children) == {"title", "uniqueid", "country"}
