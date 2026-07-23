"""订阅源扫描结果数据类。

四种订阅源（Favorite / Collection / Submission / WatchLater）的 scan_*
函数统一返回 ``list[ScanResult]``，不写库；持久化由阶段 13+ 的数据库
与阶段 14 的 workflow 编排层处理。

字段映射参考 bili-sync ``utils/convert.rs`` 的 ``VideoInfo::release_datetime``
与 ``bvid_owned``：
- Favorite：水位线字段为 ``fav_time``（收藏时间）
- WatchLater：水位线字段为 ``fav_time``（add_at 加入时间），但本源不增量扫描
- Submission：水位线字段为 ``pubtime``（对应 API 的 ``created`` 投稿创建时间）
- Collection：水位线字段为 ``pubtime``（发布时间），但本源全量扫描不提前停止
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class ScanResult(BaseModel):
    """订阅源扫描结果条目。

    所有 scan_* 函数返回该对象的列表。部分字段在某些源中可能缺失
    （如收藏夹响应不含分 P 数），调用方可在后续阶段通过
    :func:`bilibili.video.get_video_info` 补全。

    Attributes:
        bvid: BV 号（必填，作为视频唯一标识）。
        aid: AV 号（部分源响应中缺失时为 0）。
        title: 视频标题。
        cover: 封面 URL。
        upper_mid: UP 主 mid。
        upper_name: UP 主名称。
        pages_count: 分 P 数量（收藏夹/动态源不返回，默认 0）。
        pubtime: 发布时间戳（秒）。
        fav_time: 收藏/加入时间戳（秒）；仅 favorite 与 watchlater 源填充，
            其他源为 None。
    """

    bvid: str = Field(..., description="BV 号")
    aid: int = Field(default=0, description="AV 号")
    title: str = Field(default="", description="视频标题")
    cover: str = Field(default="", description="封面 URL")
    upper_mid: int = Field(default=0, description="UP 主 mid")
    upper_name: str = Field(default="", description="UP 主名称")
    pages_count: int = Field(default=0, description="分 P 数量，部分源不返回")
    pubtime: int = Field(default=0, description="发布时间戳（秒）")
    fav_time: Optional[int] = Field(
        default=None,
        description="收藏/加入时间戳（秒），仅 favorite/watchlater 源填充",
    )
