"""X (Twitter) 账号订阅存储。

账号订阅跟踪用户希望发现流程关注的 X handle。与 XHS 不同，这里没有
扩展往返：X 生产者（服务端）使用采集到的 Cookie 通过
``XCreatorStrategy`` 拉取每个订阅。本模块只负责 ``x_creator_subscriptions``
表 + CRUD；它镜像 ``xhs_tasks.XhsCreatorStore``（表结构、幂等插入、
``last_fetched_at`` 调度辅助方法）。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from openbiliclaw.storage.database import Database

logger = logging.getLogger(__name__)


def normalize_handle(handle: str) -> str:
    """规范化 X handle：去除空白字符和单个前导 ``@``。"""
    return handle.strip().lstrip("@").strip()


class XCreatorStore:
    """管理 ``x_creator_subscriptions`` 表。"""

    def __init__(self, db: Database) -> None:
        self._db = db
        self._ensure_table()

    def _ensure_table(self) -> None:
        self._db.conn.executescript("""
            CREATE TABLE IF NOT EXISTS x_creator_subscriptions (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                handle          TEXT NOT NULL UNIQUE,
                added_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_fetched_at TIMESTAMP
            );
        """)

    def add(self, handle: str) -> None:
        """添加订阅（对规范化的 handle 幂等）。"""
        normalized = normalize_handle(handle)
        self._db.conn.execute(
            "INSERT OR IGNORE INTO x_creator_subscriptions (handle) VALUES (?)",
            (normalized,),
        )
        self._db.conn.commit()

    def list_all(self) -> list[dict[str, Any]]:
        """返回所有订阅，按添加时间最早优先。"""
        rows = self._db.conn.execute(
            "SELECT * FROM x_creator_subscriptions ORDER BY added_at"
        ).fetchall()
        return [dict(r) for r in rows]

    def delete(self, sub_id: int) -> bool:
        """按主键删除订阅。如果删除了行则返回 True。"""
        cursor = self._db.conn.execute(
            "DELETE FROM x_creator_subscriptions WHERE id = ?",
            (sub_id,),
        )
        self._db.conn.commit()
        return cursor.rowcount > 0

    def due_for_fetch(self, *, hours: int = 24) -> list[dict[str, Any]]:
        """返回 ``last_fetched_at`` 早于 ``hours`` 小时前的订阅。"""
        rows = self._db.conn.execute(
            "SELECT * FROM x_creator_subscriptions "
            "WHERE last_fetched_at IS NULL "
            "   OR last_fetched_at < datetime('now', ?)",
            (f"-{hours} hours",),
        ).fetchall()
        return [dict(r) for r in rows]

    def mark_fetched(self, sub_id: int) -> None:
        """将 ``last_fetched_at`` 更新为当前时间。"""
        self._db.conn.execute(
            "UPDATE x_creator_subscriptions SET last_fetched_at = CURRENT_TIMESTAMP WHERE id = ?",
            (sub_id,),
        )
        self._db.conn.commit()
