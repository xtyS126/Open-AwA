"""抖音（douyin.com）引导事件转换辅助函数。

本模块是浏览器扩展捕获的抖音信号的 Python 侧入口。
它**有意独立于** ``xhs_tasks.py`` —— 两者之间无任何 import 交叉，
各平台常量在本模块内定义，``DyTaskQueue`` 类（在后续任务中添加）
将拥有自己的 SQLite 表。唯一有意共享的层是 ``event_format.py``：
抖音事件按标准词汇表发出 ``event_type``，以便 soul-engine 跨源
统一分析事件。

架构设计动机及 dy_ 子树所用 URL / 端点目录的开源先例说明，
参见 ``docs/plans/2026-05-06-douyin-bootstrap-import-design.md``。
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterable

    from openbiliclaw.storage.database import Database

logger = logging.getLogger(__name__)
_RECENT_TASK_STATUSES = ("pending", "in_progress", "completed", "failed")

# 将每个抖音引导 scope 映射至其标准 event_type。这些 scope 是
# 扩展 MAIN-world 的 fetch-tap 在登录用户标签页中可观察到的；
# 参见设计文档 §Scope。
DY_BOOTSTRAP_SCOPE_EVENT_TYPES: dict[str, str] = {
    "dy_post": "view",  # 用户发布 —— 弱口味信号，但仍是信号
    "dy_collect": "favorite",  # 收藏夹：最刻意的行为
    "dy_like": "like",  # 喜欢过 tab
    "dy_follow": "follow",  # 关注列表 —— 对创作者作品的兴趣
}

# 各 scope 的信号强度，输入偏好层。数值与设计文档一致；
# collect 排名最高，因其是最刻意的"留待后看"动作；
# post 排名最低，因为用户作为作者并不能强烈表明消费偏好。
DY_BOOTSTRAP_SIGNAL_STRENGTH: dict[str, float] = {
    "dy_post": 0.4,
    "dy_collect": 1.0,
    "dy_like": 0.85,
    "dy_follow": 0.6,
}

# 可读的 scope 标签，用于偏好 / 感知 LLM 提示词读取的自然语言上下文。
# 动作动词来自事件分类法；此标签补充"在抖音上"的框架。
DY_BOOTSTRAP_SCOPE_LABELS: dict[str, str] = {
    "dy_post": "发布",
    "dy_collect": "收藏",
    "dy_like": "点赞",
    "dy_follow": "关注",
}

_DISCOVERY_CREATOR_SCOPE_PRIORITY = ("dy_follow", "dy_collect", "dy_like", "dy_post")


def dy_bootstrap_videos_to_events(
    videos: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """将扩展收集的抖音引导条目转换为事件。

    通过 ``event_format.build_event`` 路由，使返回的 dict 与 B 站 / 小红书
    事件形状一致。同时缺少 ``title`` 与 ``url`` 的条目将被丢弃；
    scope 未知的条目将被丢弃。

    对于 ``dy_follow`` scope，``creator_sec_uid``（而非 ``aweme_id``）
    是天然的身份键，因此我们在同一 metadata 字段名下传递它。
    """
    from openbiliclaw.sources.event_format import SOURCE_DOUYIN, build_event

    events: list[dict[str, Any]] = []
    for item in videos:
        if not isinstance(item, dict):
            continue
        scope = str(item.get("scope", "")).strip()
        event_type = DY_BOOTSTRAP_SCOPE_EVENT_TYPES.get(scope)
        if event_type is None:
            continue

        title = str(item.get("title", "")).strip()
        url = str(item.get("url", "")).strip()
        if not title and not url:
            continue

        author = str(item.get("author", "")).strip()
        label = DY_BOOTSTRAP_SCOPE_LABELS[scope]
        # 自定义 context —— scope 标签比通用 event_type 动词更精确。
        # 措辞风格镜像偏好 / soul 提示词从小红书路径中已读到的方式。
        context = f"抖音{label}：{title or url}"
        if author:
            context = f"{context} 作者：{author}"

        # 身份键随 scope 不同。
        identity_key = "creator_sec_uid" if scope == "dy_follow" else "aweme_id"
        identity_value = str(item.get(identity_key, "")).strip()

        # scope_short 去除 "dy_" 前缀，使 import_source 读到的
        # 是 "dy_bootstrap_collect" 而非 "dy_bootstrap_dy_collect"。
        scope_short = scope.removeprefix("dy_") if scope.startswith("dy_") else scope

        metadata: dict[str, Any] = {
            identity_key: identity_value,
            "author_sec_uid": str(item.get("author_sec_uid", "")).strip(),
            "cover_url": str(item.get("cover_url", "")).strip(),
            "import_source": f"dy_bootstrap_{scope_short}",
            "signal_strength": DY_BOOTSTRAP_SIGNAL_STRENGTH[scope],
        }

        events.append(
            build_event(
                event_type=event_type,
                source_platform=SOURCE_DOUYIN,
                title=title,
                url=url,
                author=author,
                context=context,
                metadata=metadata,
            )
        )
    return events


def _video_key(video: dict[str, Any]) -> str:
    """用于去重的身份键。包含 scope，使同一 aweme_id 可合法地
    出现在两个 scope 中（例如用户既发布又收藏）。"""
    scope = str(video.get("scope", "")).strip()
    aweme_id = str(video.get("aweme_id", "")).strip()
    creator_sec_uid = str(video.get("creator_sec_uid", "")).strip()
    url = str(video.get("url", "")).strip()
    title = str(video.get("title", "")).strip()
    key = aweme_id or creator_sec_uid or url or title
    return f"{scope}:{key}" if key else ""


def dy_bootstrap_video_key(video: dict[str, Any]) -> str:
    """返回单条引导视频的跨任务稳定身份键。"""
    return _video_key(video)


def _merge_dy_result_payload(
    current: dict[str, Any],
    *,
    videos: list[dict[str, Any]] | None = None,
    scope_counts: dict[str, Any] | None = None,
    debug: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """将部分结果合并入当前行。

    返回合并后的 payload 及本次合并新增的视频列表
    （调用方仅将这些传递至 soul 流水线，避免同一项产生两次事件）。

    独立于 xhs_tasks._merge_result_payload —— 抖音使用 aweme_id
    （而非 note_id），且一旦后续 dy_history 可能加入，
    天然的 scope 计数逻辑也会有所不同。
    """
    merged_videos: list[dict[str, Any]] = []
    seen: set[str] = set()
    for video in current.get("videos") or []:
        if not isinstance(video, dict):
            continue
        key = _video_key(video)
        if not key or key in seen:
            continue
        seen.add(key)
        merged_videos.append(video)

    added: list[dict[str, Any]] = []
    for video in videos or []:
        if not isinstance(video, dict):
            continue
        key = _video_key(video)
        if not key or key in seen:
            continue
        seen.add(key)
        merged_videos.append(video)
        added.append(video)

    merged: dict[str, Any] = {}
    if merged_videos:
        merged["videos"] = merged_videos

    merged_counts: dict[str, Any] = {}
    existing_counts = current.get("scope_counts")
    if isinstance(existing_counts, dict):
        merged_counts.update(existing_counts)
    if isinstance(scope_counts, dict):
        for scope, count in scope_counts.items():
            current_count = merged_counts.get(scope, 0)
            if isinstance(current_count, int) and isinstance(count, int):
                merged_counts[scope] = max(current_count, count)
            else:
                merged_counts[scope] = count
    # 若执行器未发送计数，则从已观察的视频中回填。
    for video in merged_videos:
        scope = str(video.get("scope", "")).strip()
        if scope and scope not in merged_counts:
            merged_counts[scope] = sum(
                1 for v in merged_videos if str(v.get("scope", "")).strip() == scope
            )
    if merged_counts:
        merged["scope_counts"] = merged_counts

    if isinstance(current.get("debug"), dict) or isinstance(debug, dict):
        merged_debug: dict[str, Any] = {}
        if isinstance(current.get("debug"), dict):
            merged_debug.update(current["debug"])
        if isinstance(debug, dict):
            merged_debug.update(debug)
        merged["debug"] = merged_debug

    return merged, added


def recent_dy_creator_sec_uids(
    db: Database,
    *,
    limit: int = 20,
    task_limit: int = 5,
) -> tuple[str, ...]:
    """从近期完成的抖音引导任务中返回创作者 sec_uid 种子。

    直连搜索 / 热搜可能软返回 HTTP 200 但列表为空。创作者时间线
    目前是直连 Cookie 发现中最可靠的接口，因此发现机制可将近期
    引导信号中出现的作者作为兜底种子列表。
    """
    if limit <= 0 or task_limit <= 0:
        return ()

    rows = db.conn.execute(
        """
        SELECT result_json
        FROM dy_tasks
        WHERE status = 'completed' AND result_json IS NOT NULL
        ORDER BY completed_at DESC, created_at DESC
        LIMIT ?
        """,
        (task_limit,),
    ).fetchall()

    buckets: dict[str, list[str]] = {scope: [] for scope in _DISCOVERY_CREATOR_SCOPE_PRIORITY}
    fallback: list[str] = []
    for row in rows:
        try:
            payload = json.loads(str(row[0] or "{}"))
        except json.JSONDecodeError:
            continue
        videos = payload.get("videos")
        if not isinstance(videos, list):
            continue
        for video in videos:
            if not isinstance(video, dict):
                continue
            sec_uid = str(video.get("creator_sec_uid") or video.get("author_sec_uid") or "").strip()
            if not sec_uid:
                continue
            scope = str(video.get("scope", "")).strip()
            if scope in buckets:
                buckets[scope].append(sec_uid)
            else:
                fallback.append(sec_uid)

    seen: set[str] = set()
    result: list[str] = []
    for scope in _DISCOVERY_CREATOR_SCOPE_PRIORITY:
        for sec_uid in buckets[scope]:
            if sec_uid in seen:
                continue
            seen.add(sec_uid)
            result.append(sec_uid)
            if len(result) >= limit:
                return tuple(result)
    for sec_uid in fallback:
        if sec_uid in seen:
            continue
        seen.add(sec_uid)
        result.append(sec_uid)
        if len(result) >= limit:
            break
    return tuple(result)


class DyTaskQueue:
    """管理 dy_tasks 表。

    独立于 XhsTaskQueue。Schema 镜像 xhs_tasks，因为底层状态机
    相同（pending → completed/failed），但表分开，使一个平台的
    日预算耗尽不会阻塞另一个平台，并便于未来按平台添加列而不冲突。
    """

    def __init__(self, db: Database) -> None:
        self._db = db
        self._ensure_table()

    def _ensure_table(self) -> None:
        self._db.conn.executescript("""
            CREATE TABLE IF NOT EXISTS dy_tasks (
                id           TEXT PRIMARY KEY,
                type         TEXT NOT NULL,
                payload_json TEXT NOT NULL DEFAULT '{}',
                status       TEXT NOT NULL DEFAULT 'pending',
                result_json  TEXT,
                created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                completed_at TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_dy_tasks_status
                ON dy_tasks (status, created_at);
        """)
        columns = {
            str(row["name"])
            for row in self._db.conn.execute("PRAGMA table_info(dy_tasks)").fetchall()
        }
        if "claimed_at" not in columns:
            self._db.conn.execute("ALTER TABLE dy_tasks ADD COLUMN claimed_at TIMESTAMP")
            self._db.conn.commit()

    def enqueue(
        self,
        task_type: str,
        payload: dict[str, Any],
        *,
        daily_budget: int = 100,
    ) -> bool:
        """若当日该类型的预算允许，则入队一个任务。

        入队返回 True，预算耗尽返回 False。
        """
        return self.enqueue_with_id(task_type, payload, daily_budget=daily_budget) is not None

    def enqueue_with_id(
        self,
        task_type: str,
        payload: dict[str, Any],
        *,
        daily_budget: int = 100,
    ) -> str | None:
        """入队一个任务并返回其 id，预算耗尽时返回 None。

        ``daily_budget <= 0`` 禁用按天上限；运行时生产者
        随后由源缺口及其按运行节流控制。
        """
        count_today = self._budgeted_count_today(task_type) if daily_budget > 0 else 0

        if daily_budget > 0 and count_today >= daily_budget:
            logger.info(
                "dy task budget exhausted: type=%s, count=%d, budget=%d",
                task_type,
                count_today,
                daily_budget,
            )
            return None

        task_id = str(uuid.uuid4())
        self._db.conn.execute(
            "INSERT INTO dy_tasks (id, type, payload_json) VALUES (?, ?, ?)",
            (task_id, task_type, json.dumps(payload, ensure_ascii=False)),
        )
        self._db.conn.commit()
        return task_id

    def _budgeted_count_today(self, task_type: str) -> int:
        """统计今日应消耗该类型每日预算的任务数。"""
        today = datetime.now(UTC).strftime("%Y-%m-%d")
        rows = self._db.conn.execute(
            """
            SELECT status, result_json
            FROM dy_tasks
            WHERE type = ? AND created_at >= ?
            """,
            (task_type, today),
        ).fetchall()

        count = 0
        for row in rows:
            status = str(row["status"] if hasattr(row, "keys") else row[0])
            result_json = row["result_json"] if hasattr(row, "keys") else row[1]
            if status == "failed" and _is_stale_pending_result(result_json):
                continue
            count += 1
        return count

    def next_pending(self, only_ids: set[str] | None = None) -> dict[str, Any] | None:
        stale_before = (datetime.now(UTC) - timedelta(minutes=15)).strftime("%Y-%m-%d %H:%M:%S")
        # ``only_ids`` 限制可认领的任务（gui-init：活动 init 期间仅派发
        # init 自有的引导任务）。None 表示全部。
        where = "(status = 'pending' OR (status = 'in_progress' AND claimed_at <= ?))"
        params: list[Any] = [stale_before]
        if only_ids is not None:
            ids = [str(i) for i in only_ids]
            if not ids:
                return None
            where += f" AND id IN ({','.join('?' * len(ids))})"
            params.extend(ids)
        conn = self._db.open_connection()
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                f"SELECT * FROM dy_tasks WHERE {where} ORDER BY created_at ASC LIMIT 1",
                params,
            ).fetchone()
            if row is None:
                conn.commit()
                return None
            task_id = str(row["id"])
            conn.execute(
                "UPDATE dy_tasks SET status = 'in_progress', claimed_at = CURRENT_TIMESTAMP "
                "WHERE id = ?",
                (task_id,),
            )
            claimed = conn.execute("SELECT * FROM dy_tasks WHERE id = ?", (task_id,)).fetchone()
            conn.commit()
        except Exception:
            if conn.in_transaction:
                conn.rollback()
            raise
        finally:
            conn.close()
        return dict(claimed) if claimed is not None else None

    def find_recent_task(
        self,
        task_type: str,
        *,
        recent_hours: float,
        statuses: tuple[str, ...] | None = None,
    ) -> dict[str, Any] | None:
        """返回该类型的近期任务，用于幂等入队路径。"""
        if recent_hours <= 0:
            return None
        selected_statuses = statuses or _RECENT_TASK_STATUSES
        if not selected_statuses:
            return None
        placeholders = ",".join("?" for _ in selected_statuses)
        cutoff = (datetime.now(UTC) - timedelta(hours=recent_hours)).strftime("%Y-%m-%d %H:%M:%S")
        row = self._db.conn.execute(
            f"""
            SELECT *
            FROM dy_tasks
            WHERE type = ?
              AND created_at >= ?
              AND status IN ({placeholders})
            ORDER BY
              CASE
                WHEN status IN ('pending', 'in_progress') THEN 0
                WHEN status = 'completed' THEN 1
                ELSE 2
              END,
              created_at DESC
            LIMIT 1
            """,
            (task_type, cutoff, *selected_statuses),
        ).fetchone()
        return dict(row) if row is not None else None

    def expire_stale_pending(
        self,
        task_types: Iterable[str],
        *,
        older_than_seconds: float,
        error: str = "stale_pending",
    ) -> int:
        """将所选类型中超过指定时长的 pending 任务标记为失败。"""
        normalized_types = tuple(str(t).strip() for t in task_types if str(t).strip())
        if not normalized_types:
            return 0
        cutoff_ts = datetime.now(UTC).timestamp() - max(0.0, float(older_than_seconds))
        cutoff_text = datetime.fromtimestamp(cutoff_ts, UTC).strftime("%Y-%m-%d %H:%M:%S")
        placeholders = ",".join("?" for _ in normalized_types)
        result_payload = json.dumps({"error": error}, ensure_ascii=False)
        cursor = self._db.conn.execute(
            f"""
            UPDATE dy_tasks
            SET status = 'failed',
                result_json = ?,
                completed_at = CURRENT_TIMESTAMP
            WHERE status = 'pending'
              AND type IN ({placeholders})
              AND created_at < ?
            """,
            (result_payload, *normalized_types, cutoff_text),
        )
        self._db.conn.commit()
        return int(cursor.rowcount or 0)

    def get(self, task_id: str) -> dict[str, Any] | None:
        row = self._db.conn.execute(
            "SELECT * FROM dy_tasks WHERE id = ?",
            (task_id,),
        ).fetchone()
        return dict(row) if row else None

    def merge_result(
        self,
        task_id: str,
        *,
        videos: list[dict[str, Any]] | None = None,
        scope_counts: dict[str, Any] | None = None,
        debug: dict[str, Any] | None = None,
        complete: bool = False,
    ) -> list[dict[str, Any]]:
        """合并部分/最终结果，并可选标记完成。

        仅返回本次合并新增的视频，以便调用方将这些精确条目
        传递至 soul 流水线（避免执行器重复发送重叠批次时
        产生重复事件）。
        """
        row = self.get(task_id)
        current: dict[str, Any] = {}
        if row and row.get("result_json"):
            try:
                parsed = json.loads(str(row["result_json"]))
                if isinstance(parsed, dict):
                    current = parsed
            except json.JSONDecodeError:
                current = {}

        merged, added = _merge_dy_result_payload(
            current,
            videos=videos,
            scope_counts=scope_counts,
            debug=debug,
        )
        result = json.dumps(merged, ensure_ascii=False)
        if complete:
            self._db.conn.execute(
                "UPDATE dy_tasks SET status = 'completed', result_json = ?, "
                "completed_at = CURRENT_TIMESTAMP WHERE id = ?",
                (result, task_id),
            )
        else:
            self._db.conn.execute(
                "UPDATE dy_tasks SET result_json = ? WHERE id = ?",
                (result, task_id),
            )
        self._db.conn.commit()
        return added

    def fail(
        self,
        task_id: str,
        *,
        error: str = "",
        debug: dict[str, Any] | None = None,
    ) -> None:
        result_payload: dict[str, Any] = {"error": error}
        if debug is not None:
            result_payload["debug"] = debug
        result = json.dumps(result_payload, ensure_ascii=False)
        self._db.conn.execute(
            "UPDATE dy_tasks SET status = 'failed', result_json = ?, "
            "completed_at = CURRENT_TIMESTAMP WHERE id = ?",
            (result, task_id),
        )
        self._db.conn.commit()


def _is_stale_pending_result(result_json: Any) -> bool:
    try:
        payload = json.loads(str(result_json or "{}"))
    except json.JSONDecodeError:
        return False
    return isinstance(payload, dict) and payload.get("error") == "stale_pending"
