"""
Bilibili Toolkit 域 ORM 模型：B 站视频同步下载链路的持久化层。

本模块对应 bili-sync 移植 spec 阶段 13，承载 4 张表：
- ``bilibili_toolkit_videos``：视频元数据（bvid 唯一，download_status 位图）
- ``bilibili_toolkit_pages``：分 P 信息（cid + page 唯一，download_status 位图）
- ``bilibili_toolkit_subscriptions``：订阅源（type + source_id 唯一，filter_option/rule 存 JSON 文本）
- ``bilibili_toolkit_download_tasks``：下载子任务执行记录（5 类子任务 × 5 种状态）

所有模型继承 db.models.base.Base，与主业务模型共享同一 Metadata，
统一在 init_db 的 create_all 中建表，并通过 Alembic 迁移脚本管理 schema 变更。

字段约定：
- ``download_status`` 为 5 子任务 × 4 态位图（详见 plugins/bilibili_toolkit_builtin/status.py）
- ``filter_option`` / ``rule`` 用 Text 存 JSON 字符串，运行时由调用方 json.loads 解析
- ``latest_row_at`` 为增量扫描水位线（Unix 秒），由 sources 模块在每轮扫描后更新
"""

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.models.base import Base


class BilibiliToolkitVideo(Base):
    """B 站视频元数据。

    每个视频以 ``bvid`` 唯一标识，记录 UP 主、分 P 数、发布时间、收藏时间
    与下载状态位图。``fav_time`` 仅 favorite / watchlater 源填充，其他源为 None。

    Attributes:
        id: 自增主键。
        bvid: B 站视频 BV 号（唯一索引）。
        aid: B 站视频 AV 号。
        title: 视频标题。
        cover: 封面 URL。
        upper_mid: UP 主 mid（索引，便于按 UP 主聚合）。
        upper_name: UP 主名称。
        pages_count: 分 P 数量。
        pubtime: 发布时间戳（秒）。
        fav_time: 收藏/加入时间戳（秒），仅 favorite/watchlater 源填充。
        download_status: 5 子任务 × 4 态位图，详见 status.py。
        created_at: 首次入库时间。
        updated_at: 最近更新时间。
    """

    __tablename__ = "bilibili_toolkit_videos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    bvid: Mapped[str] = mapped_column(String(32), unique=True, nullable=False, index=True)
    aid: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    cover: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    upper_mid: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    upper_name: Mapped[str] = mapped_column(String(128), nullable=False)
    pages_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    pubtime: Mapped[int] = mapped_column(Integer, nullable=False)
    fav_time: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    download_status: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    pages: Mapped[list["BilibiliToolkitPage"]] = relationship(
        "BilibiliToolkitPage",
        back_populates="video",
        cascade="all, delete-orphan",
    )


class BilibiliToolkitPage(Base):
    """B 站视频分 P 信息。

    每个分 P 属于一个视频，``cid`` 为 B 站分 P 唯一标识。
    ``download_status`` 位图与视频级别位图布局一致，用于追踪单 P 下载状态。

    Attributes:
        id: 自增主键。
        video_id: 所属视频外键（索引）。
        cid: B 站分 P cid。
        page: 分 P 序号（从 1 开始）。
        name: 分 P 标题。
        duration: 时长（秒）。
        width: 视频宽度（可选，部分源不返回）。
        height: 视频高度（可选，部分源不返回）。
        download_status: 5 子任务 × 4 态位图。
    """

    __tablename__ = "bilibili_toolkit_pages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    video_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("bilibili_toolkit_videos.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    cid: Mapped[int] = mapped_column(Integer, nullable=False)
    page: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    name: Mapped[str] = mapped_column(String(512), nullable=False)
    duration: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    width: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    height: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    download_status: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    video: Mapped["BilibiliToolkitVideo"] = relationship(
        "BilibiliToolkitVideo",
        back_populates="pages",
    )

    __table_args__ = (
        # 同一视频下 cid 唯一，避免重复入库
        UniqueConstraint("video_id", "cid", name="uq_bilibili_toolkit_pages_video_cid"),
    )


class BilibiliToolkitSubscription(Base):
    """B 站视频订阅源。

    四种订阅类型（favorite / collection / submission / watchlater）共享一张表，
    通过 ``type`` + ``source_id`` 联合唯一标识一个订阅：
    - favorite: source_id = media_id（收藏夹 ID）
    - collection: source_id = season_id 或 series_id（合集 ID）
    - submission: source_id = upper_mid（UP 主 mid）
    - watchlater: source_id = 1（全局唯一稍后再看）

    ``filter_option`` / ``rule`` 字段以 JSON 字符串存储，运行时由调用方
    ``json.loads`` 解析为 FilterOption / 额外规则字典。

    Attributes:
        id: 自增主键。
        type: 订阅类型（favorite / collection / submission / watchlater）。
        source_id: 订阅源 ID（语义随 type 变化）。
        name: 订阅名称（用户可读）。
        path: 下载根路径。
        rule: 额外规则 JSON 字符串。
        filter_option: FilterOption JSON 字符串。
        latest_row_at: 增量扫描水位线（Unix 秒）。
        enabled: 是否启用。
        created_at: 创建时间。
    """

    __tablename__ = "bilibili_toolkit_subscriptions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    type: Mapped[str] = mapped_column(String(32), nullable=False)
    source_id: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    path: Mapped[str] = mapped_column(String(1024), nullable=False)
    rule: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    filter_option: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    latest_row_at: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )

    __table_args__ = (
        # 同类型 + 同 source_id 唯一，避免重复订阅
        UniqueConstraint(
            "type",
            "source_id",
            name="uq_bilibili_toolkit_subscriptions_type_source",
        ),
        # 增量扫描常用 type + enabled 过滤
        Index(
            "ix_bilibili_toolkit_subscriptions_type_enabled",
            "type",
            "enabled",
        ),
    )


class BilibiliToolkitDownloadTask(Base):
    """下载子任务执行记录。

    每个视频/分 P 的 5 类子任务（cover / video / nfo / danmaku / subtitle）
    各占一行，独立追踪状态与重试次数。``status`` 为字符串枚举：
    pending / running / succeeded / failed / skipped。

    Attributes:
        id: 自增主键。
        video_id: 所属视频外键（索引）。
        page_id: 所属分 P 外键（可空，cover / nfo 等视频级任务无 page_id）。
        subtask: 子任务类型（cover / video / nfo / danmaku / subtitle）。
        status: 任务状态（pending / running / succeeded / failed / skipped）。
        retry_count: 已重试次数，达到 MAX_RETRY 后不再重试。
        error: 失败原因（status=failed 时填充）。
        created_at: 任务创建时间。
        updated_at: 任务最近更新时间。
    """

    __tablename__ = "bilibili_toolkit_download_tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    video_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("bilibili_toolkit_videos.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    page_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("bilibili_toolkit_pages.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    subtask: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="pending", index=True
    )
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    __table_args__ = (
        # 同一视频/分 P 下同子任务类型唯一，避免重复创建
        UniqueConstraint(
            "video_id",
            "page_id",
            "subtask",
            name="uq_bilibili_toolkit_tasks_video_page_subtask",
        ),
    )
