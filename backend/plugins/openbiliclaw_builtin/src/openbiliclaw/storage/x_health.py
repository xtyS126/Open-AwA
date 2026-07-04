"""X (Twitter) 源健康状态机（spec §7）。

X 的 discovery 是服务端 cookie 重放；一个失效的 cookie、一次封禁，或
一次限流都会让用户主账号付出真实的往返代价。为避免在已知失败后重复
访问 x.com，producer 在这里持久化源最近一次的健康状态以及按状态码
区分的退避窗口，然后在每个周期开始时读回。

状态：

    ``ok``             — 最近一次调用成功，可自由抓取
    ``missing_cookie`` — 暂无可用 ``auth_token`` / ``ct0``
    ``expired_cookie`` — HTTP 401：cookie 失效，等待重新登录
    ``blocked``        — HTTP 403：账号/端点被禁，等待重新登录
    ``rate_limited``   — HTTP 429：退避至 ``cooldown_until``

401 / 403 要求用户在 x.com 重新登录（扩展会重新同步 cookie），因此源
保持"未就绪"，直到后续某次成功把它翻回 ``ok``。429 设置一个定时冷却，
到点自动恢复。

For-You 是最高可见度（也是风险最高）的抓取，因此在连续失败
``feed_pause_after`` 次后自动暂停；任何一次 For-You 成功都会解除暂停。

状态存放在单行 ``x_source_health`` 表中，可跨重启保留。本模块的风格
与 ``sources.x_tasks.XCreatorStore`` 一致：轻量、自包含。
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from openbiliclaw.sources.x_client import (
    XAuthError,
    XBlockedError,
    XClientError,
    XMissingCookieError,
    XRateLimitError,
)

if TYPE_CHECKING:
    from openbiliclaw.storage.database import Database

logger = logging.getLogger(__name__)

OK = "ok"
MISSING_COOKIE = "missing_cookie"
EXPIRED_COOKIE = "expired_cookie"
BLOCKED = "blocked"
RATE_LIMITED = "rate_limited"

# 需要用户在 x.com 重新登录后 discovery 才能继续的状态 —— 没有定时恢复
# 机制，只有后续某次成功才能把它们翻回 ok。
_RELOGIN_STATES = frozenset({MISSING_COOKIE, EXPIRED_COOKIE, BLOCKED})

# 单例 key（单用户模型 —— 一个 X 账号）。
_ROW_KEY = "x"


def health_state_for_error(exc: BaseException) -> str:
    """把类型化的 :class:`XClientError` 映射到离散的健康状态。

    对未知的 ``XClientError`` 回退到 :data:`RATE_LIMITED`（短暂退避比
    当作健康更安全），对完全不是 X 错误的异常回退到 :data:`OK`。
    """
    if isinstance(exc, XMissingCookieError):
        return MISSING_COOKIE
    if isinstance(exc, XAuthError):
        return EXPIRED_COOKIE
    if isinstance(exc, XBlockedError):
        return BLOCKED
    if isinstance(exc, XRateLimitError):
        return RATE_LIMITED
    if isinstance(exc, XClientError):
        return RATE_LIMITED
    return OK


def _now() -> datetime:
    return datetime.now(UTC)


def _parse_iso(value: str) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt


class XSourceHealthStore:
    """持久化的 X 源健康状态 + 按状态码区分的退避。"""

    def __init__(
        self,
        db: Database,
        *,
        rate_limit_cooldown_minutes: int = 30,
        feed_pause_after: int = 3,
    ) -> None:
        self._db = db
        self._rate_limit_cooldown_minutes = max(1, int(rate_limit_cooldown_minutes))
        self._feed_pause_after = max(1, int(feed_pause_after))
        self._ensure_table()

    def _ensure_table(self) -> None:
        self._db.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS x_source_health (
                key                  TEXT PRIMARY KEY,
                state                TEXT NOT NULL DEFAULT 'ok',
                consecutive_failures INTEGER NOT NULL DEFAULT 0,
                feed_failures        INTEGER NOT NULL DEFAULT 0,
                feed_paused          INTEGER NOT NULL DEFAULT 0,
                cooldown_until       TEXT NOT NULL DEFAULT '',
                detail               TEXT NOT NULL DEFAULT '',
                updated_at           TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        self._db.conn.execute(
            "INSERT OR IGNORE INTO x_source_health (key, state) VALUES (?, 'ok')",
            (_ROW_KEY,),
        )
        self._db.conn.commit()

    # ── 读 ─────────────────────────────────────────────────────────

    def get(self) -> dict[str, Any]:
        """以 JSON 友好的 dict 形式返回当前健康行。"""
        row = self._db.conn.execute(
            "SELECT * FROM x_source_health WHERE key = ?",
            (_ROW_KEY,),
        ).fetchone()
        if row is None:
            return {
                "state": OK,
                "consecutive_failures": 0,
                "feed_paused": False,
                "cooldown_until": "",
                "detail": "",
                "updated_at": "",
            }
        data = dict(row)
        return {
            "state": str(data.get("state") or OK),
            "consecutive_failures": int(data.get("consecutive_failures") or 0),
            "feed_paused": bool(data.get("feed_paused")),
            "cooldown_until": str(data.get("cooldown_until") or ""),
            "detail": str(data.get("detail") or ""),
            "updated_at": str(data.get("updated_at") or ""),
        }

    def is_ready(self) -> bool:
        """源现在是否可以发起抓取时返回 True。

        ``ok`` 总是就绪。``rate_limited`` 在冷却窗口过后变回就绪。
        需要重新登录的状态（``missing_cookie`` / ``expired_cookie`` /
        ``blocked``）保持未就绪，直到后续某次成功。
        """
        health = self.get()
        state = health["state"]
        if state == OK:
            return True
        if state in _RELOGIN_STATES:
            return False
        if state == RATE_LIMITED:
            cooldown = _parse_iso(health["cooldown_until"])
            if cooldown is None:
                return True
            return _now() >= cooldown
        return True

    def feed_allowed(self) -> bool:
        """For-You 未被自动暂停时返回 True。"""
        return not self.get()["feed_paused"]

    # ── 写 ─────────────────────────────────────────────────────────

    def record_success(self, *, strategy: str = "") -> None:
        """成功抓取后重置为 ``ok``。

        任何一次成功都会清掉全局失败计数和冷却。For-You 成功还会额外
        解除 For-You 自动暂停。
        """
        feed_clear = self._is_feed(strategy)
        self._db.conn.execute(
            """
            UPDATE x_source_health
               SET state = 'ok',
                   consecutive_failures = 0,
                   cooldown_until = '',
                   detail = '',
                   feed_failures = CASE WHEN ? THEN 0 ELSE feed_failures END,
                   feed_paused = CASE WHEN ? THEN 0 ELSE feed_paused END,
                   updated_at = CURRENT_TIMESTAMP
             WHERE key = ?
            """,
            (1 if feed_clear else 0, 1 if feed_clear else 0, _ROW_KEY),
        )
        self._db.conn.commit()

    def clear_relogin_block(self) -> bool:
        """在新的有效 cookie 同步后清除重新登录阻塞。

        需要重新登录的状态（``missing_cookie`` / ``expired_cookie`` /
        ``blocked``）没有定时恢复机制：:meth:`is_ready` 会让 producer
        停摆，因此永远赚不到能重置它们的"后续成功"。新的浏览器 cookie
        *就是* 这个外部重新登录信号，所以这里重置为 ``ok`` —— 否则即使
        用户重新登录后 discovery 也会一直死锁。

        不动 ``rate_limited``（它的冷却是基于时间的，不是 cookie 问题）。
        同时解除任何 For-You 自动暂停，因为触发暂停的失败都归因于同一
        个失效会话。当确实清除了阻塞时返回 True。
        """
        if self.get()["state"] not in _RELOGIN_STATES:
            return False
        self._db.conn.execute(
            """
            UPDATE x_source_health
               SET state = 'ok',
                   consecutive_failures = 0,
                   feed_failures = 0,
                   feed_paused = 0,
                   cooldown_until = '',
                   detail = '',
                   updated_at = CURRENT_TIMESTAMP
             WHERE key = ?
            """,
            (_ROW_KEY,),
        )
        self._db.conn.commit()
        return True

    def record_error(self, exc: BaseException, *, strategy: str = "") -> str:
        """把错误映射到健康状态，持久化后返回该状态。"""
        state = health_state_for_error(exc)
        cooldown_until = ""
        if state == RATE_LIMITED:
            cooldown_until = (
                _now() + timedelta(minutes=self._rate_limit_cooldown_minutes)
            ).isoformat()
        is_feed = self._is_feed(strategy)
        current = self.get()
        # feed_failures 是内部计数器（不通过 get() 暴露）。
        raw = self._db.conn.execute(
            "SELECT feed_failures FROM x_source_health WHERE key = ?",
            (_ROW_KEY,),
        ).fetchone()
        feed_failures = int(raw["feed_failures"]) if raw is not None else 0
        if is_feed:
            feed_failures += 1
        feed_paused = bool(current["feed_paused"]) or (
            is_feed and feed_failures >= self._feed_pause_after
        )
        self._db.conn.execute(
            """
            UPDATE x_source_health
               SET state = ?,
                   consecutive_failures = consecutive_failures + 1,
                   feed_failures = ?,
                   feed_paused = ?,
                   cooldown_until = ?,
                   detail = ?,
                   updated_at = CURRENT_TIMESTAMP
             WHERE key = ?
            """,
            (
                state,
                feed_failures,
                1 if feed_paused else 0,
                cooldown_until,
                str(exc)[:500],
                _ROW_KEY,
            ),
        )
        self._db.conn.commit()
        return state

    def set_cooldown_until(self, value: str) -> None:
        """覆盖冷却时间戳（测试切面 / 手动恢复）。"""
        self._db.conn.execute(
            "UPDATE x_source_health SET cooldown_until = ?, updated_at = CURRENT_TIMESTAMP "
            "WHERE key = ?",
            (str(value or ""), _ROW_KEY),
        )
        self._db.conn.commit()

    @staticmethod
    def _is_feed(strategy: str) -> bool:
        s = str(strategy or "").strip().lower()
        return s in {"feed", "for_you", "for-you", "foryou", "x-feed"}
