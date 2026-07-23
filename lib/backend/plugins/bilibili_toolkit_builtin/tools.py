"""bilibili-toolkit-builtin 内置插件 Agent 工具函数。

阶段 16 实现：5 个 Agent 工具函数，按 Open-AwA 插件工具规范定义。
由 ``plugin.py:get_tools()`` 注册到插件工具列表，供 LLM Agent 调用。

工具列表：
- ``bilibili_add_subscription``：添加订阅源
- ``bilibili_list_subscriptions``：列出订阅
- ``bilibili_trigger_download``：手动触发下载
- ``bilibili_get_download_status``：查询下载状态
- ``bilibili_list_videos``：列出已下载视频

设计约定：
- 所有工具均为 ``async def``，签名为 ``(db, user_id, ...) -> dict | list[dict]``
- ``db`` 参数由 ``PluginManager`` 在调用工具时注入（``AsyncSession`` 或 ``Session``）
- ``user_id`` 参数用于权限校验与日志关联
- 工具内部不直接抛异常，失败时返回 ``{"error": ..., "message": ...}`` 字典
- 工具返回值均为 JSON 可序列化的字典或列表，便于 LLM 解析
"""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any, Dict, List, Optional

from loguru import logger
from sqlalchemy import select
from sqlalchemy.orm import Session

from db.models.bilibili_toolkit import (
    BilibiliToolkitDownloadTask,
    BilibiliToolkitSubscription,
    BilibiliToolkitVideo,
)
from plugins.bilibili_toolkit_builtin.api.routes import (
    _execute_download,
    _running_tasks,
    _SUPPORTED_SUBSCRIPTION_TYPES,
)


# ---------------------------------------------------------------------------
# 工具 1：添加订阅
# ---------------------------------------------------------------------------


async def bilibili_add_subscription(
    db: Session,
    user_id: int,
    subscription_type: str,
    source_id: int,
    name: str,
    path: str,
    filter_option: Optional[Dict[str, Any]] = None,
) -> dict:
    """添加订阅源，触发立即扫描，返回订阅 ID 与首批视频列表。

    Args:
        db: 数据库会话（由 PluginManager 注入）。
        user_id: 调用方用户 ID（用于日志关联）。
        subscription_type: 订阅类型（favorite / season / series /
            submission / watchlater）。
        source_id: 订阅源 ID（语义随 ``subscription_type`` 变化）。
        name: 订阅名称（用户可读）。
        path: 下载根路径。
        filter_option: FilterOption 字典，可选，缺省时使用全局配置。

    Returns:
        ``{"subscription_id": int, "message": str, "videos": list[dict]}`` 字典。
        失败时返回 ``{"error": str, "message": str}``。
    """
    # 1. 校验订阅类型
    if subscription_type not in _SUPPORTED_SUBSCRIPTION_TYPES:
        return {
            "error": "invalid_subscription_type",
            "message": (
                f"不支持的订阅类型: {subscription_type}, 支持的类型: "
                f"{sorted(_SUPPORTED_SUBSCRIPTION_TYPES)}"
            ),
        }

    # 2. 校验 (type, source_id) 唯一性
    existing = (
        db.execute(
            select(BilibiliToolkitSubscription).where(
                BilibiliToolkitSubscription.type == subscription_type,
                BilibiliToolkitSubscription.source_id == source_id,
            )
        )
        .scalars()
        .first()
    )
    if existing is not None:
        return {
            "error": "subscription_already_exists",
            "message": (
                f"订阅已存在: type={subscription_type}, source_id={source_id}, "
                f"existing_id={existing.id}"
            ),
        }

    # 3. 创建订阅记录
    filter_option_json: Optional[str] = None
    if filter_option is not None:
        try:
            filter_option_json = json.dumps(filter_option, ensure_ascii=False)
        except (TypeError, ValueError) as exc:
            return {
                "error": "filter_option_invalid",
                "message": f"filter_option 序列化失败: {exc}",
            }

    subscription = BilibiliToolkitSubscription(
        type=subscription_type,
        source_id=source_id,
        name=name,
        path=path,
        filter_option=filter_option_json,
        enabled=True,
    )
    db.add(subscription)
    db.commit()
    db.refresh(subscription)

    logger.bind(
        event="bilibili_toolkit_agent_subscription_added",
        module="bilibili_toolkit",
        subscription_id=subscription.id,
        user_id=str(user_id),
    ).info(
        f"Agent 添加订阅: id={subscription.id}, type={subscription_type}, "
        f"source_id={source_id}, name={name}"
    )

    # 4. 触发立即扫描（后台异步执行，不阻塞工具响应）
    task_id = uuid.uuid4().hex
    _running_tasks[task_id] = subscription.id
    asyncio.create_task(_execute_download(task_id, subscription))

    return {
        "subscription_id": subscription.id,
        "message": (
            f"订阅已创建并触发首次扫描: id={subscription.id}, task_id={task_id}"
        ),
        "videos": [],  # 首批视频列表由后台扫描异步写入，此处返回空
    }


# ---------------------------------------------------------------------------
# 工具 2：列出订阅
# ---------------------------------------------------------------------------


async def bilibili_list_subscriptions(
    db: Session,
    user_id: int,
) -> List[dict]:
    """列出当前所有订阅源。

    Args:
        db: 数据库会话。
        user_id: 调用方用户 ID（用于日志关联）。

    Returns:
        订阅字典列表，每项含 ``id`` / ``type`` / ``source_id`` / ``name`` /
        ``path`` / ``enabled`` / ``latest_row_at`` / ``created_at``。
    """
    rows = (
        db.execute(
            select(BilibiliToolkitSubscription).order_by(
                BilibiliToolkitSubscription.id.asc()
            )
        )
        .scalars()
        .all()
    )
    return [
        {
            "id": row.id,
            "type": row.type,
            "source_id": row.source_id,
            "name": row.name,
            "path": row.path,
            "enabled": row.enabled,
            "latest_row_at": row.latest_row_at,
            "created_at": str(row.created_at) if row.created_at else None,
        }
        for row in rows
    ]


# ---------------------------------------------------------------------------
# 工具 3：手动触发下载
# ---------------------------------------------------------------------------


async def bilibili_trigger_download(
    db: Session,
    user_id: int,
    subscription_id: int,
) -> dict:
    """手动触发下载，返回任务 ID。

    Args:
        db: 数据库会话。
        user_id: 调用方用户 ID。
        subscription_id: 订阅 ID。

    Returns:
        ``{"task_id": str, "subscription_id": int, "message": str}`` 字典。
        失败时返回 ``{"error": str, "message": str}``。
    """
    subscription = db.get(BilibiliToolkitSubscription, subscription_id)
    if subscription is None:
        return {
            "error": "subscription_not_found",
            "message": f"订阅不存在: id={subscription_id}",
        }

    task_id = uuid.uuid4().hex
    _running_tasks[task_id] = subscription.id
    asyncio.create_task(_execute_download(task_id, subscription))

    logger.bind(
        event="bilibili_toolkit_agent_download_triggered",
        module="bilibili_toolkit",
        subscription_id=subscription_id,
        task_id=task_id,
        user_id=str(user_id),
    ).info(
        f"Agent 触发下载: subscription_id={subscription_id}, task_id={task_id}"
    )

    return {
        "task_id": task_id,
        "subscription_id": subscription_id,
        "message": f"订阅 {subscription_id} 下载任务已触发, task_id={task_id}",
    }


# ---------------------------------------------------------------------------
# 工具 4：查询下载状态
# ---------------------------------------------------------------------------


async def bilibili_get_download_status(
    db: Session,
    user_id: int,
    video_id: Optional[int] = None,
) -> dict:
    """查询下载状态，含子任务进度与失败原因。

    Args:
        db: 数据库会话。
        user_id: 调用方用户 ID。
        video_id: 视频 ID，可选。``None`` 时返回最近 50 条任务记录。

    Returns:
        ``{"video_id": int|None, "tasks": list[dict], "summary": dict}`` 字典。
        每条 task 含 ``id`` / ``subtask`` / ``status`` / ``error`` /
        ``retry_count`` / ``created_at``；``summary`` 含各状态计数。
    """
    query = select(BilibiliToolkitDownloadTask).order_by(
        BilibiliToolkitDownloadTask.created_at.desc()
    )
    if video_id is not None:
        query = query.where(BilibiliToolkitDownloadTask.video_id == video_id)
    else:
        # 未指定 video_id 时仅返回最近 50 条，避免结果集过大
        query = query.limit(50)

    rows = db.execute(query).scalars().all()

    tasks: List[dict] = [
        {
            "id": row.id,
            "video_id": row.video_id,
            "page_id": row.page_id,
            "subtask": row.subtask,
            "status": row.status,
            "error": row.error,
            "retry_count": row.retry_count,
            "created_at": str(row.created_at) if row.created_at else None,
        }
        for row in rows
    ]

    # 汇总各状态计数
    status_counts: Dict[str, int] = {}
    for task in tasks:
        s = task["status"]
        status_counts[s] = status_counts.get(s, 0) + 1

    return {
        "video_id": video_id,
        "tasks": tasks,
        "summary": {
            "total": len(tasks),
            "by_status": status_counts,
        },
    }


# ---------------------------------------------------------------------------
# 工具 5：列出已下载视频
# ---------------------------------------------------------------------------


async def bilibili_list_videos(
    db: Session,
    user_id: int,
    subscription_id: Optional[int] = None,
    page: int = 1,
    page_size: int = 20,
) -> List[dict]:
    """列出已下载视频。

    Args:
        db: 数据库会话。
        user_id: 调用方用户 ID。
        subscription_id: 订阅 ID，可选（当前未生效，预留扩展）。
        page: 页码，从 1 开始。
        page_size: 每页数量，默认 20。

    Returns:
        视频字典列表，每项含 ``id`` / ``bvid`` / ``title`` / ``cover`` /
        ``upper_name`` / ``pages_count`` / ``download_status`` /
        ``created_at``。
    """
    offset = (page - 1) * page_size
    query = select(BilibiliToolkitVideo).order_by(
        BilibiliToolkitVideo.created_at.desc()
    )
    # subscription_id 参数当前未生效（视频表无 subscription_id 字段）
    # 保留参数为后续扩展预留接口
    rows = db.execute(query.offset(offset).limit(page_size)).scalars().all()

    return [
        {
            "id": row.id,
            "bvid": row.bvid,
            "title": row.title,
            "cover": row.cover,
            "upper_name": row.upper_name,
            "pages_count": row.pages_count,
            "download_status": row.download_status,
            "created_at": str(row.created_at) if row.created_at else None,
        }
        for row in rows
    ]


# ---------------------------------------------------------------------------
# 工具定义注册表（供 plugin.py:get_tools() 引用）
# ---------------------------------------------------------------------------


# 5 个工具的 Open-AwA 工具定义（name / description / parameters / handler）
# parameters 字段为 JSON Schema 格式，供 LLM 调用时参考
BILIBILI_TOOLKIT_TOOLS: List[Dict[str, Any]] = [
    {
        "name": "bilibili_add_subscription",
        "description": (
            "添加 B 站订阅源（收藏夹/合集/UP 主投稿/稍后再看），"
            "创建后自动触发首次扫描。支持 5 种订阅类型："
            "favorite（收藏夹 media_id）/ season（合集 season_id）/ "
            "series（视频列表 series_id）/ submission（UP 主 upper_mid）/ "
            "watchlater（稍后再看，source_id 固定为 1）。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "subscription_type": {
                    "type": "string",
                    "enum": [
                        "favorite",
                        "season",
                        "series",
                        "submission",
                        "watchlater",
                    ],
                    "description": "订阅类型",
                },
                "source_id": {
                    "type": "integer",
                    "description": "订阅源 ID（语义随 subscription_type 变化）",
                },
                "name": {
                    "type": "string",
                    "description": "订阅名称（用户可读）",
                },
                "path": {
                    "type": "string",
                    "description": "下载根路径（如 /data/videos/favorites）",
                },
                "filter_option": {
                    "type": "object",
                    "description": "可选 FilterOption 字典，控制清晰度/编码偏好",
                    "properties": {
                        "video_max_quality": {
                            "type": "string",
                            "description": "视频最高清晰度（如 1080p）",
                        },
                        "video_min_quality": {
                            "type": "string",
                            "description": "视频最低清晰度（如 720p）",
                        },
                        "video_codecs": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "视频编码偏好顺序（如 avc/hevc/av1）",
                        },
                    },
                },
            },
            "required": ["subscription_type", "source_id", "name", "path"],
        },
        "handler": bilibili_add_subscription,
    },
    {
        "name": "bilibili_list_subscriptions",
        "description": (
            "列出当前所有 B 站订阅源，返回每项的 id / type / source_id / "
            "name / path / enabled / latest_row_at / created_at 字段。"
        ),
        "parameters": {
            "type": "object",
            "properties": {},
        },
        "handler": bilibili_list_subscriptions,
    },
    {
        "name": "bilibili_trigger_download",
        "description": (
            "手动触发指定订阅的下载任务，立即返回 task_id，"
            "下载在后台异步执行（不阻塞响应）。"
            "可配合 bilibili_get_download_status 查询下载进度。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "subscription_id": {
                    "type": "integer",
                    "description": "要触发下载的订阅 ID",
                },
            },
            "required": ["subscription_id"],
        },
        "handler": bilibili_trigger_download,
    },
    {
        "name": "bilibili_get_download_status",
        "description": (
            "查询下载任务状态，含子任务进度与失败原因。"
            "可指定 video_id 查询单个视频的所有子任务，"
            "未指定时返回最近 50 条任务记录。"
            "返回值含 summary.by_status 各状态计数。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "video_id": {
                    "type": "integer",
                    "description": "视频 ID，可选。未指定时返回最近 50 条任务",
                },
            },
        },
        "handler": bilibili_get_download_status,
    },
    {
        "name": "bilibili_list_videos",
        "description": (
            "列出已下载的 B 站视频（分页），含下载状态位图。"
            "返回值按 created_at 倒序排列。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "subscription_id": {
                    "type": "integer",
                    "description": "可选，按订阅过滤（当前未生效，预留扩展）",
                },
                "page": {
                    "type": "integer",
                    "description": "页码，从 1 开始，默认 1",
                    "minimum": 1,
                },
                "page_size": {
                    "type": "integer",
                    "description": "每页数量，默认 20，最大 100",
                    "minimum": 1,
                    "maximum": 100,
                },
            },
        },
        "handler": bilibili_list_videos,
    },
]


__all__ = [
    # 工具函数
    "bilibili_add_subscription",
    "bilibili_list_subscriptions",
    "bilibili_trigger_download",
    "bilibili_get_download_status",
    "bilibili_list_videos",
    # 工具定义注册表
    "BILIBILI_TOOLKIT_TOOLS",
]
