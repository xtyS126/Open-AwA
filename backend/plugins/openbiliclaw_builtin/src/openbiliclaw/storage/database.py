"""SQLite 数据库管理。

提供事件日志、内容缓存和推荐历史的 async 兼容 SQLite 操作。
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
import time
from collections import defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import parse_qs, urlparse

if TYPE_CHECKING:
    from datetime import datetime

logger = logging.getLogger(__name__)
# v0.3.62+：重试预算从 5×100ms（最坏情况 500ms 阻塞 asyncio 事件循环的
# 锁竞争）收紧到 8×20ms（最坏情况 160ms）。通过增加尝试次数保留了
# 相同的绝对超时下限（~160-500ms）；单次睡眠足够短，即使在 async
# 上下文中触发，事件循环卡顿也低于人类感知阈值。大多数写入第一次
# 就成功 —— 这只在重度并发写入负载下才有意义（刷新 tick + ingest +
# classify 同时猛砸 pool 行）。未来重写可以改用 asyncio.to_thread 做
# 真正的非阻塞 DB I/O，但那是更大的重构（每个调用方都得变 async）
# —— 现在这个常量微调是务实的折中方案。
_LOCK_RETRY_ATTEMPTS = 8
_LOCK_RETRY_SLEEP_SECONDS = 0.02
_BVID_PATTERN = re.compile(r"(BV[0-9A-Za-z]+)")
_VIEW_CONTENT_ID_METADATA_KEYS = (
    "content_id",
    "bvid",
    "note_id",
    "aweme_id",
    "video_id",
    "yt_video_id",
)


def _unique_clean_strings(values: Sequence[object]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _chunks(values: Sequence[str], size: int) -> list[list[str]]:
    chunk_size = max(1, int(size))
    return [list(values[index : index + chunk_size]) for index in range(0, len(values), chunk_size)]


# 与 recommendation.delight.DEFAULT_DELIGHT_THRESHOLD 对齐。Storage 保持为
# 叶子模块（不 import openbiliclaw），因此值在这里重复一份，并由
# tests/test_delight_scorer.py::test_delight_claim_threshold_in_sync 钉住。
_DELIGHT_CLAIM_MIN_SCORE = 0.70
_DEFAULT_ADMISSION_MIN_SCORE = 0.60

# 被惊喜（delight）通道占用的行：已作为 delight 投递，或当前符合
# delight 条件（pending-queue 谓词）。常规 feed 的可服务门排除它们，
# 这样同一内容不会同时出现在推荐列表和惊喜托盘中。
_DELIGHT_CLAIM_GUARD_SQL = f"""
                  AND NOT (
                    COALESCE(delight_notified, 0) = 1
                    OR (
                      COALESCE(delight_score, 0.0) >= {_DELIGHT_CLAIM_MIN_SCORE}
                      AND COALESCE(delight_reason, '') != ''
                      AND COALESCE(delight_hook, '') != ''
                    )
                  )
"""

_LEGACY_STYLE_KEY_MAP: dict[str, str] = {
    "deep_dive": "deep_focus",
    "tech_analysis": "deep_focus",
    "music_analysis": "deep_focus",
    "news_brief": "quick_scan",
    "practical_guide": "hands_on",
    "tutorial_short": "hands_on",
    "game_strategy": "hands_on",
    "review_roundup": "decision_support",
    "unboxing_experience": "decision_support",
    "story_doc": "story_immersion",
    "emotional_narrative": "story_immersion",
    "true_crime": "story_immersion",
    "opinion_stand": "opinion_sparring",
    "light_chat": "social_chat",
    "lifestyle": "daily_wander",
    "fun_variety": "mood_release",
    "parody_remix": "mood_release",
    "visual_showcase": "aesthetic_browse",
    "audio_background": "ambient_companion",
    "music_live": "live_pulse",
    "live_moment": "live_pulse",
    "sports_highlight": "live_pulse",
    "sci_fact": "curiosity_spark",
}

_XHS_SOURCE_FAMILY = "xiaohongshu"
_XHS_SOURCE_PREFIXES = ("xhs-", "xhs_", "xiaohongshu")
_DOUYIN_SOURCE_FAMILY = "douyin"
_DOUYIN_SOURCE_PREFIXES = ("dy-", "dy_", "douyin")
_BILIBILI_SOURCE_FAMILY = "bilibili"
_BILIBILI_SOURCE_KEYS = ("search", "related_chain", "trending", "explore")
_YOUTUBE_SOURCE_FAMILY = "youtube"
_YOUTUBE_SOURCE_PREFIXES = ("yt-", "yt_", "youtube")
_TWITTER_SOURCE_FAMILY = "twitter"
_TWITTER_SOURCE_PREFIXES = ("x-", "x_", "twitter")
_EXPLORE_HIGH_RISK_CLUSTERS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "manufacturing",
        ("制造", "工艺", "工厂", "工业", "材料", "金属", "芯片", "显微", "纳米", "疲劳"),
    ),
    (
        "game_theory",
        ("博弈", "桌游", "纳什", "机制", "策略模型", "平衡性"),
    ),
)

# 迁移用的 schema 版本
_SCHEMA_VERSION = 2

_SCHEMA_SQL = """
-- Event log (behavioral data from browser extension)
CREATE TABLE IF NOT EXISTS events (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type            TEXT NOT NULL,        -- click, search, scroll, comment, etc.
    url                   TEXT,
    title                 TEXT,
    context               TEXT,                 -- JSON: DOM snapshot reference, viewport, etc.
    metadata              TEXT,                 -- JSON: additional event-specific data
    -- v0.3.x event-satisfaction signal: deterministic classification
    -- written at insert time by ``classify_event_satisfaction``. NULL on
    -- pre-migration rows; consumers treat NULL as ``unknown``.
    inferred_satisfaction TEXT,                 -- "positive" | "neutral" | "negative" | "unknown"
    satisfaction_reason   TEXT,                 -- short snake_case reason; see event_format.py
    created_at            TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Content cache (discovered/evaluated content)
CREATE TABLE IF NOT EXISTS content_cache (
    bvid        TEXT PRIMARY KEY,
    title       TEXT,
    up_name     TEXT,
    up_mid      INTEGER,
    duration    INTEGER,
    tags        TEXT,                 -- JSON array
    topic_key   TEXT DEFAULT '',
    style_key   TEXT DEFAULT '',
    franchise_key TEXT DEFAULT '',  -- LLM IP/series; see _ensure_content_cache_topic_columns
    description TEXT,
    cover_url   TEXT,
    view_count  INTEGER DEFAULT 0,
    like_count  INTEGER DEFAULT 0,
    favorite_count INTEGER DEFAULT 0,
    collect_count INTEGER DEFAULT 0,
    comment_count INTEGER DEFAULT 0,
    share_count INTEGER DEFAULT 0,
    danmaku_count INTEGER DEFAULT 0,
    reply_count INTEGER DEFAULT 0,
    retweet_count INTEGER DEFAULT 0,
    bookmark_count INTEGER DEFAULT 0,
    relevance_score REAL DEFAULT 0.0,
    relevance_reason TEXT DEFAULT '',
    pool_expression TEXT DEFAULT '',
    pool_topic_label TEXT DEFAULT '',
    candidate_tier TEXT DEFAULT 'primary',
    discovered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_scored_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    notification_sent INTEGER DEFAULT 0,
    notified_at TIMESTAMP,
    pool_status TEXT DEFAULT 'fresh',
    recommended_at TIMESTAMP,
    feedback_type TEXT,
    feedback_at TIMESTAMP,
    source      TEXT,                -- Which discovery strategy found it
    body_text   TEXT DEFAULT '',     -- Full text body for text-first sources (X tweet/thread)
    content_type TEXT DEFAULT 'video',  -- Content shape: "video"|"note"|"tweet"|"thread"
    -- P1.8 yield provenance: discovery_keywords.id that produced this row;
    -- NULL for legacy / non-search / flag-off content.
    source_keyword_id INTEGER
);

-- Unified raw discovery candidate queue.
-- Producers enqueue platform-specific raw content here; evaluators claim
-- mixed-source batches and only accepted items advance into content_cache.
CREATE TABLE IF NOT EXISTS discovery_candidates (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    candidate_key         TEXT NOT NULL UNIQUE,
    status                TEXT NOT NULL DEFAULT 'pending_eval',
    source_platform       TEXT NOT NULL DEFAULT '',
    source_strategy       TEXT NOT NULL DEFAULT '',
    source_context        TEXT NOT NULL DEFAULT '',
    content_type          TEXT NOT NULL DEFAULT 'video',
    body_text             TEXT NOT NULL DEFAULT '',
    bvid                  TEXT NOT NULL DEFAULT '',
    content_id            TEXT NOT NULL DEFAULT '',
    content_url           TEXT NOT NULL DEFAULT '',
    title                 TEXT NOT NULL DEFAULT '',
    author_name           TEXT NOT NULL DEFAULT '',
    up_name               TEXT NOT NULL DEFAULT '',
    up_mid                INTEGER NOT NULL DEFAULT 0,
    description           TEXT NOT NULL DEFAULT '',
    cover_url             TEXT NOT NULL DEFAULT '',
    duration              INTEGER NOT NULL DEFAULT 0,
    view_count            INTEGER NOT NULL DEFAULT 0,
    like_count            INTEGER NOT NULL DEFAULT 0,
    favorite_count        INTEGER NOT NULL DEFAULT 0,
    collect_count         INTEGER NOT NULL DEFAULT 0,
    comment_count         INTEGER NOT NULL DEFAULT 0,
    share_count           INTEGER NOT NULL DEFAULT 0,
    danmaku_count         INTEGER NOT NULL DEFAULT 0,
    reply_count           INTEGER NOT NULL DEFAULT 0,
    retweet_count         INTEGER NOT NULL DEFAULT 0,
    bookmark_count        INTEGER NOT NULL DEFAULT 0,
    tags                  TEXT NOT NULL DEFAULT '[]',
    candidate_tier        TEXT NOT NULL DEFAULT 'primary',
    score_threshold       REAL NOT NULL DEFAULT 0.0,
    raw_payload           TEXT NOT NULL DEFAULT '{}',
    source_keyword_id     INTEGER,
    topic_key             TEXT NOT NULL DEFAULT '',
    topic_group           TEXT NOT NULL DEFAULT '',
    style_key             TEXT NOT NULL DEFAULT '',
    franchise_key         TEXT NOT NULL DEFAULT '',
    relevance_score       REAL NOT NULL DEFAULT 0.0,
    relevance_reason      TEXT NOT NULL DEFAULT '',
    pool_expression       TEXT NOT NULL DEFAULT '',
    pool_topic_label      TEXT NOT NULL DEFAULT '',
    eval_error            TEXT NOT NULL DEFAULT '',
    eval_attempts         INTEGER NOT NULL DEFAULT 0,
    batch_eval_attempts   INTEGER NOT NULL DEFAULT 0,
    created_at            TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_seen_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    claimed_at            TIMESTAMP,
    evaluated_at          TIMESTAMP,
    cached_at             TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_discovery_candidates_status_seen
    ON discovery_candidates(status, last_seen_at, id);
CREATE INDEX IF NOT EXISTS idx_discovery_candidates_source_status
    ON discovery_candidates(source_platform, status);
CREATE INDEX IF NOT EXISTS idx_discovery_candidates_content_id
    ON discovery_candidates(source_platform, content_id);

-- Recommendation history
CREATE TABLE IF NOT EXISTS recommendations (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    bvid        TEXT NOT NULL,
    expression  TEXT,                -- Friend-style recommendation text
    topic       TEXT,                -- Personal topic label
    confidence  REAL DEFAULT 0.0,
    presented   INTEGER DEFAULT 0,   -- Boolean
    feedback    TEXT,                -- User feedback (like/dislike/comment)
    feedback_type TEXT,
    feedback_note TEXT,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    presented_at TIMESTAMP,
    feedback_at TIMESTAMP,
    FOREIGN KEY (bvid) REFERENCES content_cache(bvid)
);

-- Durable popup chat turns.  These let the side panel recover in-flight
-- and completed replies after Chrome reloads or discards the panel page.
CREATE TABLE IF NOT EXISTS chat_turns (
    turn_id       TEXT PRIMARY KEY,
    session       TEXT NOT NULL DEFAULT 'popup',
    scope         TEXT NOT NULL DEFAULT 'chat',
    subject_id    TEXT NOT NULL DEFAULT '',
    subject_title TEXT NOT NULL DEFAULT '',
    message       TEXT NOT NULL DEFAULT '',
    status        TEXT NOT NULL DEFAULT 'pending',
    reply         TEXT NOT NULL DEFAULT '',
    error         TEXT NOT NULL DEFAULT '',
    created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_chat_turns_session_created
    ON chat_turns(session, created_at, turn_id);
CREATE INDEX IF NOT EXISTS idx_chat_turns_scope_subject
    ON chat_turns(scope, subject_id, created_at);

-- Schema version tracking
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY
);

-- Per-call LLM usage ledger. Populated by ``UsageRecorder`` after every
-- successful provider response. Used by ``openbiliclaw cost`` to print
-- daily spend summaries and by future per-module attribution work.
CREATE TABLE IF NOT EXISTS llm_usage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    provider TEXT NOT NULL,
    model TEXT NOT NULL DEFAULT '',
    caller TEXT NOT NULL DEFAULT '',
    prompt_tokens INTEGER NOT NULL DEFAULT 0,
    completion_tokens INTEGER NOT NULL DEFAULT 0,
    total_tokens INTEGER NOT NULL DEFAULT 0,
    -- v0.3.28+: portion of prompt_tokens served from provider-side
    -- prompt cache. Always <= prompt_tokens. 0 means cache miss / no
    -- caching. Used to compute cache hit rate per caller.
    cached_input_tokens INTEGER NOT NULL DEFAULT 0,
    estimated_cost_cny REAL NOT NULL DEFAULT 0.0,
    success INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_llm_usage_timestamp ON llm_usage(timestamp);
CREATE INDEX IF NOT EXISTS idx_llm_usage_provider ON llm_usage(provider, model);
"""


def _pool_source_family(source: object, source_platform: object = "") -> str:
    """返回 pool 份额核算使用的 source family key。"""
    platform = str(source_platform or "").strip().lower()
    raw_source = str(source or "").strip()
    source_key = raw_source.lower()
    if platform in {_XHS_SOURCE_FAMILY, "xhs"} or source_key.startswith(_XHS_SOURCE_PREFIXES):
        return _XHS_SOURCE_FAMILY
    if platform in {_DOUYIN_SOURCE_FAMILY, "dy"} or source_key.startswith(_DOUYIN_SOURCE_PREFIXES):
        return _DOUYIN_SOURCE_FAMILY
    if platform in {_YOUTUBE_SOURCE_FAMILY, "yt"} or source_key.startswith(
        _YOUTUBE_SOURCE_PREFIXES
    ):
        return _YOUTUBE_SOURCE_FAMILY
    if platform in {_TWITTER_SOURCE_FAMILY, "x"} or source_key.startswith(_TWITTER_SOURCE_PREFIXES):
        return _TWITTER_SOURCE_FAMILY
    if platform in {_BILIBILI_SOURCE_FAMILY, "bili"} or source_key in _BILIBILI_SOURCE_KEYS:
        return _BILIBILI_SOURCE_FAMILY
    return raw_source or "unknown"


def _normalize_source_platform_key(source_platform: object) -> str:
    """返回跨源 content ID 中使用的规范 source key。"""
    raw = str(source_platform or "").strip().lower()
    if raw in {_XHS_SOURCE_FAMILY, "xhs"}:
        return _XHS_SOURCE_FAMILY
    if raw in {_DOUYIN_SOURCE_FAMILY, "dy"}:
        return _DOUYIN_SOURCE_FAMILY
    if raw in {_YOUTUBE_SOURCE_FAMILY, "yt"}:
        return _YOUTUBE_SOURCE_FAMILY
    if raw in {_TWITTER_SOURCE_FAMILY, "x"}:
        return _TWITTER_SOURCE_FAMILY
    if raw in {_BILIBILI_SOURCE_FAMILY, "bili"}:
        return _BILIBILI_SOURCE_FAMILY
    return raw


def _normalize_style_key_for_storage(value: object) -> str:
    """规范化已知 style_key 值，同时保留未知的遗留行。"""
    token = re.sub(r"[\s-]+", "_", str(value or "").strip().lower())
    if not token:
        return ""
    return _LEGACY_STYLE_KEY_MAP.get(token, token)


def _is_linkable_pool_source(
    source: object,
    source_platform: object,
    content_url: object,
) -> bool:
    """对无法从推荐中打开的 xhs 行返回 False。"""
    if _pool_source_family(source, source_platform) != _XHS_SOURCE_FAMILY:
        return True
    return "xsec_token=" in str(content_url or "")


def _xhs_self_author_guard_sql(table_alias: str = "content_cache") -> str:
    """返回一个排除自己发布的 XHS 行的 SQL AND 子句。

    子句接受 3 个位置 ``?`` 参数（都是同一个昵称字符串）。昵称为空时
    子句是 no-op。
    """
    prefix = f"{table_alias}." if table_alias else ""
    return (
        "AND ("
        "? = '' "
        f"OR COALESCE({prefix}source_platform, '') != 'xiaohongshu' "
        "OR ("
        f"LOWER(COALESCE({prefix}up_name, '')) != LOWER(?) "
        f"AND LOWER(COALESCE({prefix}author_name, '')) != LOWER(?)"
        ")"
        ")"
    )


def _xhs_self_author_guard_params(xhs_self_nickname: str | None) -> tuple[str, str, str]:
    """返回 ``_xhs_self_author_guard_sql`` 的 3 个绑定值。"""
    nickname = str(xhs_self_nickname or "").strip()
    return (nickname, nickname, nickname)


def _normalize_admission_min_score(value: object) -> float:
    if isinstance(value, bool):
        return _DEFAULT_ADMISSION_MIN_SCORE
    if not isinstance(value, (int, float, str)):
        return _DEFAULT_ADMISSION_MIN_SCORE
    try:
        score = float(value)
    except (TypeError, ValueError):
        return _DEFAULT_ADMISSION_MIN_SCORE
    if score <= 0.0 or score > 1.0:
        return _DEFAULT_ADMISSION_MIN_SCORE
    return score


class Database:
    """OpenBiliClaw 的轻量 SQLite 封装。

    管理事件日志、内容缓存和推荐历史。
    """

    def __init__(self, db_path: str | Path) -> None:
        self._db_path = Path(db_path)
        self._conn: sqlite3.Connection | None = None
        self._admission_min_score = _DEFAULT_ADMISSION_MIN_SCORE

    def set_admission_min_score(self, value: object) -> None:
        """设置统一的推荐池准入下限。"""
        self._admission_min_score = _normalize_admission_min_score(value)

    def initialize(self) -> None:
        """初始化数据库并在需要时运行迁移。"""
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._db_path), timeout=30.0, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA busy_timeout = 30000")
        self._conn.executescript(_SCHEMA_SQL)
        self._ensure_event_satisfaction_columns()
        self._ensure_recommendation_feedback_columns()
        self._ensure_content_cache_runtime_columns()
        self._ensure_content_cache_relevance_columns()
        self._ensure_content_cache_topic_columns()
        self._ensure_content_cache_pool_copy_columns()
        self._ensure_content_cache_delight_columns()
        self._ensure_content_cache_multisource_columns()
        self._ensure_recommendation_read_indexes()
        self._ensure_source_recipes_table()
        self._ensure_xhs_observed_urls_table()
        self._ensure_discovery_candidate_columns()
        self._normalize_legacy_style_keys()
        self._ensure_llm_usage_cache_columns()
        self._ensure_chat_turns_table()
        self._ensure_watch_later_table()
        self._ensure_discovery_keywords_table()
        self._ensure_favorites_table()
        self._ensure_auth_state_table()
        self._ensure_init_runs_table()
        self.reset_stale_discovery_candidate_evaluations()
        self.suppress_low_score_pool_items()
        self.suppress_low_confidence_recommendations()

        # 设置 schema 版本
        self._conn.execute(
            "INSERT OR IGNORE INTO schema_version (version) VALUES (?)",
            (_SCHEMA_VERSION,),
        )
        self._conn.commit()
        logger.info("Database initialized at %s", self._db_path)

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            raise RuntimeError("Database not initialized. Call initialize() first.")
        return self._conn

    def _pool_admission_min_score(self) -> float:
        return _normalize_admission_min_score(self._admission_min_score)

    def open_connection(self) -> sqlite3.Connection:
        """打开一个到已初始化数据库的短生命周期连接。

        用于可能从 FastAPI 线程池运行的显式事务。单独的连接让 SQLite
        通过 ``busy_timeout`` 串行化写入，而不是在进程级连接上嵌套事务。
        """
        if self._conn is None:
            raise RuntimeError("Database not initialized. Call initialize() first.")
        conn = sqlite3.connect(str(self._db_path), timeout=30.0, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout = 30000")
        return conn

    def _ensure_fresh_read(self) -> None:
        """关闭任何隐式事务，使下一次 SELECT 能看到最新 WAL 状态。

        当 CLI 命令（独立进程）写入同一数据库时，本服务进程可能仍在
        隐式事务中持有过期的读快照。提交会关闭该事务，使下一次查询
        针对当前 WAL head 启动新事务。
        """
        if self.conn.in_transaction:
            self.conn.commit()

    def _execute_write(
        self,
        sql: str,
        params: tuple[Any, ...] | list[Any] = (),
    ) -> sqlite3.Cursor:
        """执行写入，对瞬态 SQLite 锁做短重试。"""
        attempts = _LOCK_RETRY_ATTEMPTS
        while True:
            try:
                cursor = self.conn.execute(sql, params)
                self.conn.commit()
                return cursor
            except sqlite3.OperationalError as exc:
                message = str(exc).lower()
                if "database is locked" not in message or attempts <= 1:
                    raise
                attempts -= 1
                logger.warning(
                    "SQLite write locked, retrying (%s attempts left): %s",
                    attempts,
                    sql.splitlines()[0].strip() if sql.strip() else "<empty-sql>",
                )
                time.sleep(_LOCK_RETRY_SLEEP_SECONDS)

    def _execute_many_write(
        self,
        sql: str,
        seq_of_params: Sequence[tuple[Any, ...] | list[Any]],
    ) -> sqlite3.Cursor:
        """批量执行写入，带与 ``_execute_write`` 相同的瞬态锁重试。"""
        attempts = _LOCK_RETRY_ATTEMPTS
        while True:
            try:
                cursor = self.conn.executemany(sql, seq_of_params)
                self.conn.commit()
                return cursor
            except sqlite3.OperationalError as exc:
                message = str(exc).lower()
                if "database is locked" not in message or attempts <= 1:
                    raise
                attempts -= 1
                logger.warning(
                    "SQLite batch write locked, retrying (%s attempts left): %s",
                    attempts,
                    sql.splitlines()[0].strip() if sql.strip() else "<empty-sql>",
                )
                time.sleep(_LOCK_RETRY_SLEEP_SECONDS)

    def insert_event(self, event_type: str, **kwargs: Any) -> int:
        """插入一条行为事件。

        v0.3.23+：``context`` 现在是自然语言字符串（来自
        ``event_format.build_event()``）。以原始文本存储 —— 没有
        外层 JSON 包装 —— 这样通过 SELECT 读取的消费者拿回的就是
        存进去的同一个字符串。v0.3.22 之前传入 dict 形式 context 的
        调用方仍然可用：dict / list / 其他非字符串值会被 JSON 编码后
        存储，旧代码路径不会突然丢数据。

        Args:
            event_type: 事件类型。
            **kwargs: 额外的事件字段。``context`` 可以是 str、dict、
                list 或 None。

        Returns:
            插入行的 ID。
        """
        import json

        from openbiliclaw.sources.event_format import classify_event_satisfaction

        raw_context = kwargs.get("context", "")
        if isinstance(raw_context, str):
            context_text = raw_context
        elif raw_context is None:
            context_text = ""
        else:
            # 遗留 dict / list 载荷 —— JSON 编码后存储。
            context_text = json.dumps(raw_context, ensure_ascii=False)

        metadata_payload = kwargs.get("metadata", {})

        # 单一分类 owner。重建分类器期望的 event dict 形状
        # （event_type + url + title + metadata）。
        # API ingest 可能也会在顶层设置 dwell 字段；把这些透传过去，
        # 这样点击规则可以读取任一位置。
        classifier_event: dict[str, Any] = {
            "event_type": event_type,
            "url": kwargs.get("url", ""),
            "title": kwargs.get("title", ""),
            "metadata": metadata_payload if isinstance(metadata_payload, dict) else {},
        }
        for top_level_key in ("watch_seconds", "video_duration_seconds"):
            if top_level_key in kwargs and kwargs[top_level_key] is not None:
                classifier_event[top_level_key] = kwargs[top_level_key]
        inferred_satisfaction, satisfaction_reason = classify_event_satisfaction(classifier_event)

        cursor = self._execute_write(
            "INSERT INTO events "
            "(event_type, url, title, context, metadata, "
            " inferred_satisfaction, satisfaction_reason) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                event_type,
                kwargs.get("url", ""),
                kwargs.get("title", ""),
                context_text,
                json.dumps(metadata_payload, ensure_ascii=False),
                inferred_satisfaction,
                satisfaction_reason,
            ),
        )
        return cursor.lastrowid or 0

    def get_recent_events(self, limit: int = 100) -> list[dict[str, Any]]:
        """获取最近的事件。

        Args:
            limit: 最大事件数。

        Returns:
            event dict 列表。
        """
        cursor = self.conn.execute(
            "SELECT * FROM events ORDER BY created_at DESC LIMIT ?", (limit,)
        )
        return [dict(row) for row in cursor.fetchall()]

    # ------------------------------------------------------------------
    # 持久化的 popup chat 轮次
    # ------------------------------------------------------------------

    def create_chat_turn(
        self,
        *,
        turn_id: str,
        message: str,
        session: str = "popup",
        scope: str = "chat",
        subject_id: str = "",
        subject_title: str = "",
    ) -> dict[str, Any]:
        """创建一个 pending 状态的 popup chat 轮次（若尚不存在）。"""
        self._execute_write(
            """
            INSERT OR IGNORE INTO chat_turns (
                turn_id, session, scope, subject_id, subject_title, message, status
            )
            VALUES (?, ?, ?, ?, ?, ?, 'pending')
            """,
            (
                turn_id,
                session or "popup",
                scope or "chat",
                subject_id or "",
                subject_title or "",
                message,
            ),
        )
        row = self.get_chat_turn(turn_id)
        if row is None:
            raise RuntimeError(f"Failed to create chat turn {turn_id!r}")
        return row

    def complete_chat_turn(self, turn_id: str, *, reply: str) -> None:
        """把 pending 的 popup chat 轮次标记为 completed。"""
        self._execute_write(
            """
            UPDATE chat_turns
            SET status = 'completed',
                reply = ?,
                error = '',
                updated_at = CURRENT_TIMESTAMP
            WHERE turn_id = ?
            """,
            (reply, turn_id),
        )

    def fail_chat_turn(self, turn_id: str, *, error: str, reply: str = "") -> None:
        """把 popup chat 轮次标记为 failed，同时保留可见文案。"""
        self._execute_write(
            """
            UPDATE chat_turns
            SET status = 'failed',
                reply = ?,
                error = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE turn_id = ?
            """,
            (reply, error, turn_id),
        )

    def get_chat_turn(self, turn_id: str) -> dict[str, Any] | None:
        """按 id 返回一条持久化的 popup chat 轮次。"""
        self._ensure_fresh_read()
        cursor = self.conn.execute(
            """
            SELECT turn_id, session, scope, subject_id, subject_title, message,
                   status, reply, error, created_at, updated_at
            FROM chat_turns
            WHERE turn_id = ?
            """,
            (turn_id,),
        )
        row = cursor.fetchone()
        return dict(row) if row else None

    def list_chat_turns(
        self,
        *,
        session: str = "popup",
        scope: str = "",
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """按展示顺序返回最近的 popup chat 轮次。"""
        self._ensure_fresh_read()
        clauses = ["session = ?"]
        params: list[Any] = [session or "popup"]
        if scope:
            clauses.append("scope = ?")
            params.append(scope)
        params.append(max(1, int(limit)))
        cursor = self.conn.execute(
            f"""
            SELECT turn_id, session, scope, subject_id, subject_title, message,
                   status, reply, error, created_at, updated_at
            FROM (
                SELECT turn_id, session, scope, subject_id, subject_title, message,
                       status, reply, error, created_at, updated_at
                FROM chat_turns
                WHERE {" AND ".join(clauses)}
                ORDER BY created_at DESC, turn_id DESC
                LIMIT ?
            )
            ORDER BY created_at ASC, turn_id ASC
            """,
            params,
        )
        return [dict(row) for row in cursor.fetchall()]

    # ------------------------------------------------------------------
    # LLM usage 账本
    # ------------------------------------------------------------------

    def insert_llm_usage(
        self,
        *,
        provider: str,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        estimated_cost_cny: float,
        caller: str = "",
        success: bool = True,
        cached_input_tokens: int = 0,
    ) -> int:
        """追加一条 LLM 调用的 usage 记录。

        ``cached_input_tokens``（v0.3.28+）是 ``prompt_tokens`` 中由
        provider 端 prompt cache 服务的部分 —— 始终 ``<= prompt_tokens``。
        0 表示未使用缓存。供 ``cost --by caller`` 计算命中率，并供
        ``estimate_cost`` 正确折扣缓存 token。
        """
        total = max(0, prompt_tokens) + max(0, completion_tokens)
        cursor = self._execute_write(
            """INSERT INTO llm_usage
               (provider, model, caller, prompt_tokens, completion_tokens,
                total_tokens, cached_input_tokens, estimated_cost_cny,
                success)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                provider or "",
                model or "",
                caller or "",
                int(max(0, prompt_tokens)),
                int(max(0, completion_tokens)),
                int(total),
                int(max(0, cached_input_tokens)),
                float(estimated_cost_cny),
                1 if success else 0,
            ),
        )
        return cursor.lastrowid or 0

    def query_llm_usage_by_day(
        self,
        *,
        days: int = 7,
    ) -> list[dict[str, Any]]:
        """返回最近 ``days`` 天的按天聚合。

        每行：{day, calls, prompt_tokens, completion_tokens,
        total_tokens, cost_cny}。零用量的天会被省略 —— CLI 会补齐
        显示用的空缺。
        """
        cursor = self.conn.execute(
            """
            SELECT date(timestamp, 'localtime') AS day,
                   COUNT(*) AS calls,
                   COALESCE(SUM(prompt_tokens), 0) AS prompt_tokens,
                   COALESCE(SUM(completion_tokens), 0) AS completion_tokens,
                   COALESCE(SUM(total_tokens), 0) AS total_tokens,
                   COALESCE(SUM(estimated_cost_cny), 0) AS cost_cny
            FROM llm_usage
            WHERE timestamp >= datetime('now', '-' || ? || ' day', 'localtime')
            GROUP BY day
            ORDER BY day DESC
            """,
            (max(1, int(days)),),
        )
        return [dict(row) for row in cursor.fetchall()]

    def query_llm_usage_by_provider(
        self,
        *,
        days: int = 7,
    ) -> list[dict[str, Any]]:
        """返回最近 ``days`` 天按 (provider, model) 的汇总。"""
        cursor = self.conn.execute(
            """
            SELECT provider,
                   model,
                   COUNT(*) AS calls,
                   COALESCE(SUM(prompt_tokens), 0) AS prompt_tokens,
                   COALESCE(SUM(completion_tokens), 0) AS completion_tokens,
                   COALESCE(SUM(estimated_cost_cny), 0) AS cost_cny
            FROM llm_usage
            WHERE timestamp >= datetime('now', '-' || ? || ' day', 'localtime')
            GROUP BY provider, model
            ORDER BY cost_cny DESC
            """,
            (max(1, int(days)),),
        )
        return [dict(row) for row in cursor.fetchall()]

    def query_llm_usage_by_caller(
        self,
        *,
        days: int = 7,
    ) -> list[dict[str, Any]]:
        """返回最近 ``days`` 天按 caller 的汇总。

        ``caller`` 是 LLM 服务打在每行上的自由格式字符串（如
        ``discovery.evaluate`` / ``recommendation.write`` /
        ``soul.profile``）。未打标签的调用落在 ``""`` 下，CLI 把它
        渲染为 ``(untagged)``。结果按成本排序，第一行就是最贵的 caller。

        v0.3.28+ 还返回 ``cached_input_tokens``，CLI 据此计算并展示
        各 caller 的缓存命中率 —— 低命中率（< 30%）意味着 prompt
        前缀不稳定，值得排查。
        """
        cursor = self.conn.execute(
            """
            SELECT COALESCE(caller, '') AS caller,
                   COUNT(*) AS calls,
                   COALESCE(SUM(prompt_tokens), 0) AS prompt_tokens,
                   COALESCE(SUM(completion_tokens), 0) AS completion_tokens,
                   COALESCE(SUM(cached_input_tokens), 0) AS cached_input_tokens,
                   COALESCE(SUM(estimated_cost_cny), 0) AS cost_cny
            FROM llm_usage
            WHERE timestamp >= datetime('now', '-' || ? || ' day', 'localtime')
            GROUP BY caller
            ORDER BY cost_cny DESC
            """,
            (max(1, int(days)),),
        )
        return [dict(row) for row in cursor.fetchall()]

    def query_llm_usage_total(self, *, days: int = 7) -> dict[str, Any]:
        """返回最近 ``days`` 天的单行汇总。"""
        cursor = self.conn.execute(
            """
            SELECT COUNT(*) AS calls,
                   COALESCE(SUM(prompt_tokens), 0) AS prompt_tokens,
                   COALESCE(SUM(completion_tokens), 0) AS completion_tokens,
                   COALESCE(SUM(total_tokens), 0) AS total_tokens,
                   COALESCE(SUM(cached_input_tokens), 0) AS cached_input_tokens,
                   COALESCE(SUM(estimated_cost_cny), 0) AS cost_cny
            FROM llm_usage
            WHERE timestamp >= datetime('now', '-' || ? || ' day', 'localtime')
            """,
            (max(1, int(days)),),
        )
        row = cursor.fetchone()
        return (
            dict(row)
            if row
            else {
                "calls": 0,
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
                "cached_input_tokens": 0,
                "cost_cny": 0.0,
            }
        )

    def max_llm_usage_id(self) -> int:
        """返回当前已存储的最大 ``llm_usage.id``（空表返回 0）。

        用作"自此点之后计费了多少"查询的检查点 —— init / discovery
        周期封装在入口快照它，出口传给 ``query_llm_usage_since_id``
        以把成本摘要限定在单个阶段。
        """
        cursor = self.conn.execute("SELECT COALESCE(MAX(id), 0) AS m FROM llm_usage")
        row = cursor.fetchone()
        return int(row["m"]) if row else 0

    def query_llm_usage_since_id(self, *, since_id: int) -> dict[str, Any]:
        """返回 ``id > since_id`` 行的按 caller 明细 + 汇总。

        输出：``{"total": {calls, prompt_tokens, completion_tokens,
        cost_cny}, "by_caller": [{caller, calls, ...}, ...]}``。通过
        传入阶段入口取的 ``max_llm_usage_id()`` 来限定到单个阶段。
        """
        total_cursor = self.conn.execute(
            """
            SELECT COUNT(*) AS calls,
                   COALESCE(SUM(prompt_tokens), 0) AS prompt_tokens,
                   COALESCE(SUM(completion_tokens), 0) AS completion_tokens,
                   COALESCE(SUM(cached_input_tokens), 0) AS cached_input_tokens,
                   COALESCE(SUM(estimated_cost_cny), 0) AS cost_cny
            FROM llm_usage
            WHERE id > ?
            """,
            (int(since_id),),
        )
        total_row = total_cursor.fetchone()
        total = (
            dict(total_row)
            if total_row
            else {
                "calls": 0,
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "cached_input_tokens": 0,
                "cost_cny": 0.0,
            }
        )

        caller_cursor = self.conn.execute(
            """
            SELECT COALESCE(caller, '') AS caller,
                   COUNT(*) AS calls,
                   COALESCE(SUM(prompt_tokens), 0) AS prompt_tokens,
                   COALESCE(SUM(completion_tokens), 0) AS completion_tokens,
                   COALESCE(SUM(cached_input_tokens), 0) AS cached_input_tokens,
                   COALESCE(SUM(estimated_cost_cny), 0) AS cost_cny
            FROM llm_usage
            WHERE id > ?
            GROUP BY caller
            ORDER BY cost_cny DESC
            """,
            (int(since_id),),
        )
        return {
            "total": total,
            "by_caller": [dict(row) for row in caller_cursor.fetchall()],
        }

    def query_events(
        self,
        *,
        event_types: list[str] | None = None,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        keyword: str = "",
        limit: int = 100,
        satisfaction_modes: frozenset[str] | None = None,
        after_event_id: int | None = None,
    ) -> list[dict[str, Any]]:
        """带可选过滤条件查询事件。

        ``satisfaction_modes`` 按 ``inferred_satisfaction`` 过滤。当集合
        包含 ``"unknown"`` 时，分类为 NULL 的行（迁移前遗留行）也会返回。

        ``after_event_id`` 限定 ``id`` 严格大于给定 watermark 的行 ——
        供 cognition 周期读取尚未折叠进 awareness 的事件。结果顺序不变
        （最新优先）；需要时间序的调用方自行反转。
        """
        sql = "SELECT * FROM events"
        clauses: list[str] = []
        params: list[Any] = []

        if event_types:
            placeholders = ", ".join("?" for _ in event_types)
            clauses.append(f"event_type IN ({placeholders})")
            params.extend(event_types)

        if after_event_id is not None:
            clauses.append("id > ?")
            params.append(after_event_id)

        if start_time is not None:
            clauses.append("created_at >= ?")
            params.append(start_time.isoformat(sep=" "))

        if end_time is not None:
            clauses.append("created_at <= ?")
            params.append(end_time.isoformat(sep=" "))

        if keyword:
            like = f"%{keyword}%"
            clauses.append("(url LIKE ? OR title LIKE ? OR metadata LIKE ?)")
            params.extend([like, like, like])

        if satisfaction_modes is not None:
            modes = list(satisfaction_modes)
            mode_clauses: list[str] = []
            if modes:
                placeholders = ", ".join("?" for _ in modes)
                mode_clauses.append(f"inferred_satisfaction IN ({placeholders})")
                params.extend(modes)
            if "unknown" in satisfaction_modes:
                mode_clauses.append("inferred_satisfaction IS NULL")
            if mode_clauses:
                clauses.append("(" + " OR ".join(mode_clauses) + ")")
            else:
                # 显式请求空 modes 集 → 不匹配任何行。
                clauses.append("1 = 0")

        if clauses:
            sql = f"{sql} WHERE {' AND '.join(clauses)}"

        sql = f"{sql} ORDER BY created_at DESC, id DESC LIMIT ?"
        params.append(limit)
        cursor = self.conn.execute(sql, params)
        return [dict(row) for row in cursor.fetchall()]

    def count_events_by_type(
        self,
        *,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
    ) -> dict[str, int]:
        """按事件类型分组计数。"""
        sql = "SELECT event_type, COUNT(*) AS count FROM events"
        clauses: list[str] = []
        params: list[Any] = []

        if start_time is not None:
            clauses.append("created_at >= ?")
            params.append(start_time.isoformat(sep=" "))

        if end_time is not None:
            clauses.append("created_at <= ?")
            params.append(end_time.isoformat(sep=" "))

        if clauses:
            sql = f"{sql} WHERE {' AND '.join(clauses)}"

        sql = f"{sql} GROUP BY event_type ORDER BY event_type ASC"
        cursor = self.conn.execute(sql, params)
        return {str(row["event_type"]): int(row["count"]) for row in cursor.fetchall()}

    def cache_content(self, bvid: str, **kwargs: Any) -> None:
        """缓存已发现的内容。

        Args:
            bvid: 视频 BV ID。
            **kwargs: 内容字段。
        """
        import json

        self._execute_write(
            """
            INSERT INTO content_cache (
                bvid,
                title,
                up_name,
                up_mid,
                duration,
                tags,
                topic_key,
                topic_group,
                style_key,
                franchise_key,
                description,
                cover_url,
                view_count,
                like_count,
                favorite_count,
                collect_count,
                comment_count,
                share_count,
                danmaku_count,
                reply_count,
                retweet_count,
                bookmark_count,
                relevance_score,
                relevance_reason,
                pool_expression,
                pool_topic_label,
                candidate_tier,
                last_scored_at,
                source,
                content_id,
                content_url,
                source_platform,
                author_name,
                body_text,
                content_type,
                source_keyword_id
            )
            VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                CURRENT_TIMESTAMP, ?, ?, ?, ?, ?, ?, ?, ?
            )
            ON CONFLICT(bvid) DO UPDATE SET
                title = excluded.title,
                up_name = excluded.up_name,
                up_mid = excluded.up_mid,
                duration = excluded.duration,
                tags = excluded.tags,
                -- Preserve LLM-classified fields: when the incoming value
                -- is empty/zero, keep the existing DB value.  This prevents
                -- re-ingest from raw sources (e.g. xhs extension re-sending
                -- the same notes on every page load) from wiping out
                -- classifications that classify_pool_backlog has written.
                topic_key = COALESCE(
                    NULLIF(excluded.topic_key, ''),
                    content_cache.topic_key,
                    ''
                ),
                topic_group = COALESCE(
                    NULLIF(excluded.topic_group, ''),
                    content_cache.topic_group,
                    ''
                ),
                style_key = COALESCE(
                    NULLIF(excluded.style_key, ''),
                    content_cache.style_key,
                    ''
                ),
                franchise_key = COALESCE(
                    NULLIF(excluded.franchise_key, ''),
                    content_cache.franchise_key,
                    ''
                ),
                description = excluded.description,
                cover_url = excluded.cover_url,
                view_count = excluded.view_count,
                like_count = excluded.like_count,
                favorite_count = excluded.favorite_count,
                collect_count = excluded.collect_count,
                comment_count = excluded.comment_count,
                share_count = excluded.share_count,
                danmaku_count = excluded.danmaku_count,
                reply_count = excluded.reply_count,
                retweet_count = excluded.retweet_count,
                bookmark_count = excluded.bookmark_count,
                relevance_score = CASE
                    WHEN excluded.relevance_score > 0 THEN excluded.relevance_score
                    ELSE COALESCE(content_cache.relevance_score, 0)
                END,
                relevance_reason = COALESCE(
                    NULLIF(excluded.relevance_reason, ''),
                    content_cache.relevance_reason,
                    ''
                ),
                pool_expression = COALESCE(
                    NULLIF(excluded.pool_expression, ''),
                    content_cache.pool_expression,
                    ''
                ),
                pool_topic_label = COALESCE(
                    NULLIF(excluded.pool_topic_label, ''),
                    content_cache.pool_topic_label,
                    ''
                ),
                candidate_tier = excluded.candidate_tier,
                last_scored_at = CURRENT_TIMESTAMP,
                -- Re-fresh items previously trim-suppressed: 'suppressed' is
                -- an internal diversity decision (over-quota cuts, topic cap),
                -- not a user signal. When a discovery strategy re-finds the
                -- item it deserves another shot. Without this, B站 trending
                -- (which churns slowly) stays bottlenecked because most hot
                -- BVIDs are already cached as 'suppressed' from earlier
                -- trim cycles. User-driven states ('shown', 'feedbacked',
                -- 'purged_by_dislike') are preserved. Low-score suppressed
                -- rows only revive after a fresh/effective score meets the
                -- unified admission floor.
                pool_status = CASE
                    WHEN content_cache.pool_status = 'suppressed'
                         AND (
                            CASE
                                WHEN excluded.relevance_score > 0 THEN excluded.relevance_score
                                ELSE COALESCE(content_cache.relevance_score, 0)
                            END
                         ) >= ?
                    THEN 'fresh'
                    ELSE content_cache.pool_status
                END,
                source = excluded.source,
                content_id = excluded.content_id,
                content_url = excluded.content_url,
                source_platform = excluded.source_platform,
                author_name = COALESCE(
                    NULLIF(excluded.author_name, ''),
                    content_cache.author_name,
                    ''
                ),
                body_text = COALESCE(
                    NULLIF(excluded.body_text, ''),
                    content_cache.body_text,
                    ''
                ),
                content_type = COALESCE(
                    NULLIF(excluded.content_type, ''),
                    content_cache.content_type,
                    'video'
                ),
                -- P1.8: keep the producing-keyword provenance once set; a later
                -- re-ingest from a source that doesn't carry the id (NULL) must
                -- not wipe it.
                source_keyword_id = COALESCE(
                    excluded.source_keyword_id,
                    content_cache.source_keyword_id
                )
            """,
            (
                bvid,
                kwargs.get("title", ""),
                kwargs.get("up_name", ""),
                kwargs.get("up_mid", 0),
                kwargs.get("duration", 0),
                json.dumps(kwargs.get("tags", []), ensure_ascii=False),
                kwargs.get("topic_key", ""),
                kwargs.get("topic_group", ""),
                _normalize_style_key_for_storage(kwargs.get("style_key", "")),
                kwargs.get("franchise_key", ""),
                kwargs.get("description", ""),
                kwargs.get("cover_url", ""),
                kwargs.get("view_count", 0),
                kwargs.get("like_count", 0),
                kwargs.get("favorite_count", 0),
                kwargs.get("collect_count", 0),
                kwargs.get("comment_count", 0),
                kwargs.get("share_count", 0),
                kwargs.get("danmaku_count", 0),
                kwargs.get("reply_count", 0),
                kwargs.get("retweet_count", 0),
                kwargs.get("bookmark_count", 0),
                kwargs.get("relevance_score", self._pool_admission_min_score()),
                kwargs.get("relevance_reason", ""),
                kwargs.get("pool_expression", ""),
                kwargs.get("pool_topic_label", ""),
                kwargs.get("candidate_tier", "primary"),
                kwargs.get("source", ""),
                kwargs.get("content_id", bvid),
                kwargs.get("content_url", ""),
                kwargs.get("source_platform", "bilibili"),
                kwargs.get("author_name", ""),
                kwargs.get("body_text", ""),
                kwargs.get("content_type", "video") or "video",
                self._coerce_source_keyword_id(kwargs.get("source_keyword_id")),
                self._pool_admission_min_score(),
            ),
        )

    @staticmethod
    def _coerce_source_keyword_id(value: Any) -> int | None:
        """把 ``source_keyword_id`` kwarg 规范化为 ``int`` 或 ``None``。

        容忍字段缺失 / 空白 / 非数字，这样未走 P1.8 provenance 路径的
        调用方仍写普通 NULL（与 P1.8 前的 schema 行为一致）。
        """
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _candidate_value(candidate: object, key: str, default: Any = "") -> Any:
        if isinstance(candidate, Mapping):
            return candidate.get(key, default)
        return getattr(candidate, key, default)

    @staticmethod
    def _candidate_json_payload(value: object, *, default: object) -> str:
        if isinstance(value, str):
            try:
                json.loads(value)
            except json.JSONDecodeError:
                return json.dumps(default, ensure_ascii=False)
            return value
        try:
            return json.dumps(default if value is None else value, ensure_ascii=False)
        except TypeError:
            return json.dumps(default, ensure_ascii=False)

    def enqueue_discovery_candidates(
        self,
        candidates: Sequence[Any],
        *,
        max_pending_per_source: int | None = None,
    ) -> int:
        """把原始 discovery 候选插入待评估队列。

        已存在的 ``candidate_key`` 行被视为重新发现信号：不复制行，但
        刷新 ``last_seen_at``，使活跃 source 不会显得陈旧。
        """

        inserted = 0
        touched_sources: set[str] = set()
        for candidate in candidates:
            candidate_key = str(self._candidate_value(candidate, "candidate_key", "") or "").strip()
            if not candidate_key:
                continue
            source_platform = str(self._candidate_value(candidate, "source_platform", "") or "")
            tags = self._candidate_json_payload(
                self._candidate_value(candidate, "tags", []),
                default=[],
            )
            raw_payload = self._candidate_json_payload(
                self._candidate_value(candidate, "raw_payload", {}),
                default={},
            )
            score_threshold = float(self._candidate_value(candidate, "score_threshold", 0.0) or 0.0)
            cursor = self._execute_write(
                """
                INSERT OR IGNORE INTO discovery_candidates (
                    candidate_key,
                    status,
                    source_platform,
                    source_strategy,
                    source_context,
                    content_type,
                    body_text,
                    bvid,
                    content_id,
                    content_url,
                    title,
                    author_name,
                    up_name,
                    up_mid,
                    description,
                    cover_url,
                    duration,
                    view_count,
                    like_count,
                    favorite_count,
                    collect_count,
                    comment_count,
                    share_count,
                    danmaku_count,
                    reply_count,
                    retweet_count,
                    bookmark_count,
                    tags,
                    candidate_tier,
                    score_threshold,
                    raw_payload,
                    source_keyword_id
                )
                VALUES (
                    ?, 'pending_eval', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                )
                """,
                (
                    candidate_key,
                    source_platform,
                    str(self._candidate_value(candidate, "source_strategy", "") or ""),
                    str(self._candidate_value(candidate, "source_context", "") or ""),
                    str(self._candidate_value(candidate, "content_type", "video") or "video"),
                    str(self._candidate_value(candidate, "body_text", "") or ""),
                    str(self._candidate_value(candidate, "bvid", "") or ""),
                    str(self._candidate_value(candidate, "content_id", "") or ""),
                    str(self._candidate_value(candidate, "content_url", "") or ""),
                    str(self._candidate_value(candidate, "title", "") or ""),
                    str(self._candidate_value(candidate, "author_name", "") or ""),
                    str(self._candidate_value(candidate, "up_name", "") or ""),
                    int(self._candidate_value(candidate, "up_mid", 0) or 0),
                    str(self._candidate_value(candidate, "description", "") or ""),
                    str(self._candidate_value(candidate, "cover_url", "") or ""),
                    int(self._candidate_value(candidate, "duration", 0) or 0),
                    int(self._candidate_value(candidate, "view_count", 0) or 0),
                    int(self._candidate_value(candidate, "like_count", 0) or 0),
                    int(self._candidate_value(candidate, "favorite_count", 0) or 0),
                    int(self._candidate_value(candidate, "collect_count", 0) or 0),
                    int(self._candidate_value(candidate, "comment_count", 0) or 0),
                    int(self._candidate_value(candidate, "share_count", 0) or 0),
                    int(self._candidate_value(candidate, "danmaku_count", 0) or 0),
                    int(self._candidate_value(candidate, "reply_count", 0) or 0),
                    int(self._candidate_value(candidate, "retweet_count", 0) or 0),
                    int(self._candidate_value(candidate, "bookmark_count", 0) or 0),
                    tags,
                    str(self._candidate_value(candidate, "candidate_tier", "primary") or "primary"),
                    score_threshold,
                    raw_payload,
                    self._coerce_source_keyword_id(
                        self._candidate_value(candidate, "source_keyword_id", None)
                    ),
                ),
            )
            if source_platform:
                touched_sources.add(source_platform)
            if cursor.rowcount > 0:
                inserted += 1
                continue
            self._execute_write(
                """
                UPDATE discovery_candidates
                SET last_seen_at = CURRENT_TIMESTAMP
                WHERE candidate_key = ?
                """,
                (candidate_key,),
            )
        if max_pending_per_source is not None:
            max_pending = max(0, int(max_pending_per_source))
            if max_pending > 0:
                for source in touched_sources:
                    self.trim_discovery_candidates_for_source(
                        source_platform=source,
                        max_pending=max_pending,
                    )
        return inserted

    def trim_discovery_candidates_for_source(
        self,
        *,
        source_platform: str,
        max_pending: int,
    ) -> int:
        """当某 source 超过队列上限时丢弃最旧的候选行。

        进行中的 ``evaluating`` 行永不会被删除。终态行先于 pending/
        evaluated 行被裁剪，尽可能保留活跃原料。
        """

        source = str(source_platform or "").strip()
        cap = max(0, int(max_pending))
        if not source or cap <= 0:
            return 0
        self._ensure_fresh_read()
        row = self.conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM discovery_candidates
            WHERE source_platform = ?
            """,
            (source,),
        ).fetchone()
        current = int(row["count"] if row else 0)
        excess = current - cap
        if excess <= 0:
            return 0
        cursor = self._execute_write(
            """
            DELETE FROM discovery_candidates
            WHERE id IN (
                SELECT id
                FROM discovery_candidates
                WHERE source_platform = ?
                  AND status != 'evaluating'
                ORDER BY
                    CASE
                        WHEN status IN (
                            'cached',
                            'rejected_low_score',
                            'rejected_duplicate',
                            'rejected_cache_admission',
                            'rejected_recently_viewed',
                            'rejected_franchise_quota',
                            'failed_eval'
                        ) THEN 0
                        ELSE 1
                    END ASC,
                    last_seen_at ASC,
                    id ASC
                LIMIT ?
            )
            """,
            (source, excess),
        )
        return int(cursor.rowcount)

    def reset_stale_discovery_candidate_evaluations(
        self,
        *,
        max_age_minutes: int = 30,
    ) -> int:
        """释放崩溃进程遗留的评估者 claim。"""

        minutes = max(1, int(max_age_minutes))
        cursor = self._execute_write(
            """
            UPDATE discovery_candidates
            SET status = 'pending_eval',
                claimed_at = NULL,
                eval_error = 'stale evaluating claim reset'
            WHERE status = 'evaluating'
              AND claimed_at IS NOT NULL
              AND claimed_at < datetime('now', ?)
            """,
            (f"-{minutes} minutes",),
        )
        return int(cursor.rowcount)

    def claim_discovery_candidates_for_eval(self, *, limit: int) -> list[dict[str, Any]]:
        """claim 一批混合 source 的 pending 候选用于评估。"""

        claim_limit = max(0, int(limit))
        if claim_limit <= 0:
            return []
        self._ensure_fresh_read()
        # 窥探一个有界窗口并在 Python 中轮询，防止一个噪声 source 独占
        # 混合评估批次。
        cursor = self.conn.execute(
            """
            SELECT *
            FROM discovery_candidates
            WHERE status = 'pending_eval'
            ORDER BY last_seen_at ASC, id ASC
            LIMIT ?
            """,
            (max(claim_limit * 4, claim_limit),),
        )
        pending = [dict(row) for row in cursor.fetchall()]
        if not pending:
            return []

        source_order: list[str] = []
        by_source: dict[str, list[dict[str, Any]]] = {}
        for row in pending:
            source = str(row.get("source_platform") or "unknown")
            if source not in by_source:
                source_order.append(source)
                by_source[source] = []
            by_source[source].append(row)

        selected: list[dict[str, Any]] = []
        while len(selected) < claim_limit:
            added = False
            for source in source_order:
                rows = by_source[source]
                if not rows:
                    continue
                selected.append(rows.pop(0))
                added = True
                if len(selected) >= claim_limit:
                    break
            if not added:
                break

        ids = [int(row["id"]) for row in selected]
        placeholders = ", ".join("?" for _ in ids)
        self._execute_write(
            f"""
            UPDATE discovery_candidates
            SET status = 'evaluating',
                claimed_at = CURRENT_TIMESTAMP,
                eval_error = ''
            WHERE id IN ({placeholders})
              AND status = 'pending_eval'
            """,
            ids,
        )
        claimed_rows = self.conn.execute(
            f"""
            SELECT id
            FROM discovery_candidates
            WHERE id IN ({placeholders})
              AND status = 'evaluating'
            """,
            ids,
        ).fetchall()
        claimed_ids = {int(row["id"]) for row in claimed_rows}
        claimed = [row for row in selected if int(row["id"]) in claimed_ids]
        for row in claimed:
            row["status"] = "evaluating"
        return claimed

    def get_evaluated_discovery_candidates_for_admission(
        self,
        *,
        limit: int,
    ) -> list[dict[str, Any]]:
        """返回已评估但仍待 content-cache 准入的候选。"""

        admission_limit = max(0, int(limit))
        if admission_limit <= 0:
            return []
        self._ensure_fresh_read()
        cursor = self.conn.execute(
            """
            SELECT *
            FROM discovery_candidates
            WHERE status = 'evaluated'
            ORDER BY evaluated_at ASC, last_seen_at ASC, id ASC
            LIMIT ?
            """,
            (admission_limit,),
        )
        return [dict(row) for row in cursor.fetchall()]

    def update_discovery_candidate_evaluations(
        self,
        evaluations: Sequence[Mapping[str, Any]],
    ) -> int:
        """把评估者输出持久化回已 claim 的候选行。"""

        updated = 0
        for evaluation in evaluations:
            candidate_id = int(evaluation.get("candidate_id") or evaluation.get("id") or 0)
            if candidate_id <= 0:
                continue
            cursor = self._execute_write(
                """
                UPDATE discovery_candidates
                SET status = ?,
                    topic_key = ?,
                    topic_group = ?,
                    style_key = ?,
                    franchise_key = ?,
                    relevance_score = ?,
                    relevance_reason = ?,
                    pool_expression = ?,
                    pool_topic_label = ?,
                    eval_error = ?,
                    eval_attempts = 0,
                    batch_eval_attempts = 0,
                    evaluated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                  AND status = 'evaluating'
                """,
                (
                    str(evaluation.get("status") or "evaluated"),
                    str(evaluation.get("topic_key") or ""),
                    str(evaluation.get("topic_group") or ""),
                    _normalize_style_key_for_storage(evaluation.get("style_key")),
                    str(evaluation.get("franchise_key") or ""),
                    float(evaluation.get("relevance_score") or evaluation.get("score") or 0.0),
                    str(evaluation.get("relevance_reason") or evaluation.get("reason") or ""),
                    str(evaluation.get("pool_expression") or ""),
                    str(evaluation.get("pool_topic_label") or ""),
                    str(evaluation.get("eval_error") or ""),
                    candidate_id,
                ),
            )
            if cursor.rowcount > 0:
                updated += 1
        return updated

    def reset_discovery_candidates_to_pending(
        self,
        candidate_ids: Sequence[int],
        *,
        reason: str = "",
        max_attempts: int = 5,
        max_batch_attempts: int = 50,
        increment_attempts: bool = True,
    ) -> int:
        """在瞬态评估失败后释放已 claim 的候选。"""

        ids = [int(candidate_id) for candidate_id in candidate_ids if int(candidate_id) > 0]
        if not ids:
            return 0
        placeholders = ", ".join("?" for _ in ids)
        if not increment_attempts:
            batch_attempts_limit = max(1, int(max_batch_attempts))
            cursor = self._execute_write(
                f"""
                UPDATE discovery_candidates
                SET batch_eval_attempts = batch_eval_attempts + 1,
                    status = CASE
                        WHEN batch_eval_attempts + 1 >= ? THEN 'failed_eval'
                        ELSE 'pending_eval'
                    END,
                    claimed_at = NULL,
                    eval_error = ?,
                    evaluated_at = CASE
                        WHEN batch_eval_attempts + 1 >= ? THEN CURRENT_TIMESTAMP
                        ELSE evaluated_at
                    END,
                    last_seen_at = CASE
                        WHEN batch_eval_attempts + 1 >= ? THEN last_seen_at
                        ELSE CURRENT_TIMESTAMP
                    END
                WHERE id IN ({placeholders})
                  AND status = 'evaluating'
                """,
                (
                    batch_attempts_limit,
                    str(reason),
                    batch_attempts_limit,
                    batch_attempts_limit,
                    *ids,
                ),
            )
            return int(cursor.rowcount)

        attempts_limit = max(1, int(max_attempts))
        cursor = self._execute_write(
            f"""
            UPDATE discovery_candidates
            SET eval_attempts = eval_attempts + 1,
                status = CASE
                    WHEN eval_attempts + 1 >= ? THEN 'failed_eval'
                    ELSE 'pending_eval'
                END,
                claimed_at = NULL,
                eval_error = ?,
                evaluated_at = CASE
                    WHEN eval_attempts + 1 >= ? THEN CURRENT_TIMESTAMP
                    ELSE evaluated_at
                END,
                last_seen_at = CASE
                    WHEN eval_attempts + 1 >= ? THEN last_seen_at
                    ELSE CURRENT_TIMESTAMP
                END
            WHERE id IN ({placeholders})
              AND status = 'evaluating'
            """,
            (attempts_limit, str(reason), attempts_limit, attempts_limit, *ids),
        )
        return int(cursor.rowcount)

    def mark_discovery_candidate_cached(self, candidate_id: int) -> None:
        """把已评估候选标记为已成功插入 content_cache。"""

        self._execute_write(
            """
            UPDATE discovery_candidates
            SET status = 'cached',
                cached_at = CURRENT_TIMESTAMP,
                eval_error = '',
                eval_attempts = 0,
                batch_eval_attempts = 0
            WHERE id = ?
              AND status IN ('evaluating', 'evaluated')
            """,
            (int(candidate_id),),
        )

    def reject_discovery_candidate(
        self,
        candidate_id: int,
        *,
        status: str,
        reason: str = "",
    ) -> None:
        """把候选标记为在进入 content_cache 前被拒绝。"""

        self._execute_write(
            """
            UPDATE discovery_candidates
            SET status = ?,
                eval_error = ?,
                evaluated_at = COALESCE(evaluated_at, CURRENT_TIMESTAMP)
            WHERE id = ?
              AND status IN ('evaluating', 'evaluated')
            """,
            (status, reason, int(candidate_id)),
        )

    def count_discovery_candidates_by_status(self) -> dict[str, int]:
        """按生命周期状态分组返回候选队列计数。"""

        self._ensure_fresh_read()
        cursor = self.conn.execute(
            """
            SELECT status, COUNT(*) AS count
            FROM discovery_candidates
            GROUP BY status
            ORDER BY status ASC
            """
        )
        return {str(row["status"]): int(row["count"]) for row in cursor.fetchall()}

    def get_existing_discovery_candidate_keys(self, candidate_keys: Sequence[str]) -> set[str]:
        """返回已存在于原始评估队列中的候选 key。"""

        clean = _unique_clean_strings(candidate_keys)
        if not clean:
            return set()
        self._ensure_fresh_read()
        existing: set[str] = set()
        for chunk in _chunks(clean, 900):
            placeholders = ", ".join("?" for _ in chunk)
            cursor = self.conn.execute(
                f"""
                SELECT candidate_key
                FROM discovery_candidates
                WHERE candidate_key IN ({placeholders})
                """,
                chunk,
            )
            existing.update(str(row["candidate_key"]) for row in cursor.fetchall())
        return existing

    def get_existing_content_cache_ids(self, content_ids: Sequence[str]) -> set[str]:
        """返回已存在于 evaluated content cache 中的 BVID/content id。"""

        clean = _unique_clean_strings(content_ids)
        if not clean:
            return set()
        self._ensure_fresh_read()
        existing: set[str] = set()
        for chunk in _chunks(clean, 450):
            placeholders = ", ".join("?" for _ in chunk)
            cursor = self.conn.execute(
                f"""
                SELECT bvid, content_id
                FROM content_cache
                WHERE bvid IN ({placeholders})
                   OR content_id IN ({placeholders})
                """,
                [*chunk, *chunk],
            )
            for row in cursor.fetchall():
                bvid = str(row["bvid"] or "").strip()
                content_id = str(row["content_id"] or "").strip()
                if bvid:
                    existing.add(bvid)
                if content_id:
                    existing.add(content_id)
        return existing

    def count_discovery_candidates_by_source_status(self) -> dict[str, dict[str, int]]:
        """返回按 source 与 lifecycle status 分组的候选队列计数。"""

        self._ensure_fresh_read()
        cursor = self.conn.execute(
            """
            SELECT source_platform, status, COUNT(*) AS count
            FROM discovery_candidates
            GROUP BY source_platform, status
            ORDER BY source_platform ASC, status ASC
            """
        )
        counts: dict[str, dict[str, int]] = {}
        for row in cursor.fetchall():
            source = str(row["source_platform"] or "unknown")
            status = str(row["status"])
            counts.setdefault(source, {})[status] = int(row["count"])
        return counts

    def count_discovery_pending_raw_material_by_source(self) -> dict[str, int]:
        """返回按 source 分组、尚未缓存的 raw candidate 计数。"""

        self._ensure_fresh_read()
        cursor = self.conn.execute(
            """
            SELECT source_platform, COUNT(*) AS count
            FROM discovery_candidates
            WHERE status IN ('pending_eval', 'evaluating', 'evaluated')
            GROUP BY source_platform
            ORDER BY source_platform ASC
            """
        )
        return {str(row["source_platform"] or "unknown"): int(row["count"]) for row in cursor}

    def _count_pending_discovery_raw_material(self) -> int:
        self._ensure_fresh_read()
        cursor = self.conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM discovery_candidates
            WHERE status IN ('pending_eval', 'evaluating', 'evaluated')
            """
        )
        row = cursor.fetchone()
        return int(row["count"] if row else 0)

    def get_cached_content(self, limit: int = 100) -> list[dict[str, Any]]:
        """按基础质量信号排序返回已缓存的 discovered content。"""
        cursor = self.conn.execute(
            """
            SELECT *
            FROM content_cache
            ORDER BY
                CASE candidate_tier WHEN 'primary' THEN 0 ELSE 1 END ASC,
                relevance_score DESC,
                last_scored_at DESC,
                view_count DESC,
                bvid ASC
            LIMIT ?
            """,
            (limit,),
        )
        return [dict(row) for row in cursor.fetchall()]

    def get_unrecommended_content(self, limit: int = 100) -> list[dict[str, Any]]:
        """返回尚未被推荐过的已缓存 content。"""
        min_score = self._pool_admission_min_score()
        cursor = self.conn.execute(
            """
            SELECT c.*
            FROM content_cache AS c
            WHERE COALESCE(c.relevance_score, 0.0) >= ?
              AND NOT EXISTS (
                SELECT 1
                FROM recommendations AS r
                WHERE r.bvid = c.bvid
            )
            ORDER BY
                CASE c.candidate_tier WHEN 'primary' THEN 0 ELSE 1 END ASC,
                c.relevance_score DESC,
                c.last_scored_at DESC,
                c.view_count DESC,
                c.bvid ASC
            LIMIT ?
            """,
            (min_score, max(limit * 5, 50)),
        )
        rows = [dict(row) for row in cursor.fetchall()]
        rows = self._exclude_viewed_rows(
            rows,
            self.get_recent_viewed_content_keys(),
            limit=len(rows),
        )
        return self._balance_pool_rows(rows, limit=limit)

    def suppress_low_score_pool_items(self, min_score: float | None = None) -> int:
        """把低于统一准入下限的已缓存 pool 行标记为 suppressed。"""
        threshold = (
            self._pool_admission_min_score()
            if min_score is None
            else _normalize_admission_min_score(min_score)
        )
        cursor = self._execute_write(
            """
            UPDATE content_cache
            SET pool_status = 'suppressed'
            WHERE COALESCE(relevance_score, 0.0) < ?
              AND COALESCE(pool_status, 'fresh') IN ('fresh', 'shown', 'suppressed')
            """,
            (threshold,),
        )
        return int(cursor.rowcount or 0)

    def suppress_low_confidence_recommendations(self, min_score: float | None = None) -> int:
        """把旧的低置信度 recommendation 行标记为 suppressed。"""
        threshold = (
            self._pool_admission_min_score()
            if min_score is None
            else _normalize_admission_min_score(min_score)
        )
        cursor = self._execute_write(
            """
            UPDATE recommendations
            SET feedback_type = 'suppressed_low_score'
            WHERE COALESCE(confidence, 0.0) < ?
              AND COALESCE(feedback_type, '') = ''
            """,
            (threshold,),
        )
        return int(cursor.rowcount or 0)

    def get_pool_candidates(
        self,
        limit: int = 20,
        *,
        max_per_topic_group: int = 3,
        xhs_self_nickname: str = "",
    ) -> list[dict[str, Any]]:
        """从 discovery pool 直接获取新鲜的 recommendation 候选。

        ``max_per_topic_group`` 限制任意单个 ``topic_group`` 进入
        relevance 排序头部的项数。没有这个上限时，一个含 270 个不同
        topic_group 的 600 项 pool 仍会产生集中在 ~10 个头部 group 的
        top-50 短名单，因为高 relevance 候选会聚集在用户的主要兴趣
        周围；长尾 group（典型 pool 中 197 个只有一项）永远进不了候选
        窗口。上限为 3 让明显的偏好仍保持强存在感，同时为候选窗口中
        ~40+ 个不同 group 腾出空间。传 ``max_per_topic_group=0`` 可为
        需要的 caller（如健康检查）恢复旧的、无限制排序。

        被惊喜（delight）通道占用的行通过 ``_DELIGHT_CLAIM_GUARD_SQL``
        排除 —— 已投递或当前符合 queue 条件的 delight 绝不能被常规
        feed 重复。``count_pool_candidates`` 应用同样的 guard，这样
        "还有 N 条"显示与 serve() 能加载的保持同步。

        Notes:
            ``content_url`` 中没有 ``xsec_token`` 的 xhs 行被排除。
            裸 xhs URL 在外部分享时会被 xhs 以错误 300031 拒绝，因此
            在 recommendation 中暴露它们只会产生死链。token 由
            MAIN-world sniffer 在用户浏览 xhs 时回填；裸行在
            ``_backfill_xhs_tokens`` 升级它们后会重新变得可用。
        """
        self._ensure_fresh_read()
        # 大范围预取，使分组过滤后仍为下游平衡 pass 留出余量。
        fetch_limit = max(limit * 8, 80)
        min_score = self._pool_admission_min_score()
        guard_sql = _xhs_self_author_guard_sql()
        guard_params = _xhs_self_author_guard_params(xhs_self_nickname)
        delight_guard_sql = _DELIGHT_CLAIM_GUARD_SQL
        if max_per_topic_group <= 0:
            sql = f"""
                SELECT *
                FROM content_cache
                WHERE COALESCE(pool_status, 'fresh') = 'fresh'
                  AND COALESCE(feedback_type, '') != 'dislike'
                  AND COALESCE(relevance_score, 0.0) >= ?
                  AND COALESCE(pool_expression, '') != ''
                  AND COALESCE(pool_topic_label, '') != ''
                  AND COALESCE(style_key, '') != ''
                  AND COALESCE(topic_group, '') != ''
                  AND (
                    source_platform != 'xiaohongshu'
                    OR content_url LIKE '%xsec_token=%'
                  )
                  {guard_sql}
                  {delight_guard_sql}
                  AND NOT EXISTS (
                    SELECT 1
                    FROM recommendations AS r
                    WHERE r.bvid = content_cache.bvid
                  )
                ORDER BY
                    CASE candidate_tier WHEN 'primary' THEN 0 ELSE 1 END ASC,
                    relevance_score DESC,
                    last_scored_at DESC,
                    view_count DESC,
                    bvid ASC
                LIMIT ?
            """
            params: tuple[Any, ...] = (min_score, *guard_params, fetch_limit)
        else:
            # 通过窗口函数按组排名：保留每个 topic_group 的 top-N 已分类
            # 项，然后按 relevance 排序剩余部分。
            sql = f"""
                WITH ranked AS (
                    SELECT *,
                           ROW_NUMBER() OVER (
                               PARTITION BY topic_group
                               ORDER BY
                                   relevance_score DESC,
                                   last_scored_at DESC,
                                   view_count DESC,
                                   bvid ASC
                           ) AS group_rank
                    FROM content_cache
                    WHERE COALESCE(pool_status, 'fresh') = 'fresh'
                      AND COALESCE(feedback_type, '') != 'dislike'
                      AND COALESCE(relevance_score, 0.0) >= ?
                      AND COALESCE(pool_expression, '') != ''
                      AND COALESCE(pool_topic_label, '') != ''
                      AND COALESCE(style_key, '') != ''
                      AND COALESCE(topic_group, '') != ''
                      AND (
                        source_platform != 'xiaohongshu'
                        OR content_url LIKE '%xsec_token=%'
                      )
                      {guard_sql}
                      {delight_guard_sql}
                      AND NOT EXISTS (
                        SELECT 1
                        FROM recommendations AS r
                        WHERE r.bvid = content_cache.bvid
                      )
                )
                SELECT * FROM ranked
                WHERE group_rank <= ?
                ORDER BY
                    CASE candidate_tier WHEN 'primary' THEN 0 ELSE 1 END ASC,
                    relevance_score DESC,
                    last_scored_at DESC,
                    view_count DESC,
                    bvid ASC
                LIMIT ?
            """
            params = (min_score, *guard_params, max_per_topic_group, fetch_limit)
        cursor = self.conn.execute(sql, params)
        rows = [dict(row) for row in cursor.fetchall()]
        rows = self._exclude_viewed_rows(
            rows,
            self.get_recent_viewed_content_keys(),
            limit=len(rows),
        )
        return self._balance_pool_rows(rows, limit=limit)

    def count_pool_candidates(
        self, *, max_per_topic_group: int = 3, xhs_self_nickname: str = ""
    ) -> int:
        """返回立即可用于 reshuffle 的新鲜候选数量。

        v0.3.57+：与 ``get_pool_candidates`` 的 precompute 门对齐 ——
        没有 ``pool_expression`` / ``pool_topic_label`` 的行被排除，这样
        popup 的"还有 N 条"永远不会夸大 serve() 实际能返回的数量。

        v0.3.66+：还要求 ``style_key`` / ``topic_group`` —— content 必须
        先被分类才能被 serve，与 source platform 无关。

        v0.3.91+：应用与 ``get_pool_candidates`` 相同的
        ``max_per_topic_group`` 窗口，这样集中的 topic group 不会把显示
        数量膨胀到 ``serve()`` 实际能加载的之外。
        """
        return len(
            self._load_available_pool_candidate_rows(
                max_per_topic_group=max_per_topic_group,
                xhs_self_nickname=xhs_self_nickname,
            )
        )

    def _load_available_pool_candidate_rows(
        self, *, max_per_topic_group: int = 3, xhs_self_nickname: str = ""
    ) -> list[dict[str, Any]]:
        """加载由前端可见的 pool 可用性门计数的行。

        像 ``get_pool_candidates`` 一样应用 ``_DELIGHT_CLAIM_GUARD_SQL``，
        这样可用性计数永远不会包含 serve() 会拒绝加载的惊喜通道行。
        """
        self._ensure_fresh_read()
        min_score = self._pool_admission_min_score()
        guard_sql = _xhs_self_author_guard_sql()
        guard_params = _xhs_self_author_guard_params(xhs_self_nickname)
        delight_guard_sql = _DELIGHT_CLAIM_GUARD_SQL
        if max_per_topic_group > 0:
            cursor = self.conn.execute(
                f"""
                WITH ranked AS (
                    SELECT bvid, source, source_platform, content_url,
                           ROW_NUMBER() OVER (
                               PARTITION BY topic_group
                               ORDER BY
                                   relevance_score DESC,
                                   last_scored_at DESC,
                                   view_count DESC,
                                   bvid ASC
                           ) AS group_rank
                    FROM content_cache
                    WHERE COALESCE(pool_status, 'fresh') = 'fresh'
                      AND COALESCE(feedback_type, '') != 'dislike'
                      AND COALESCE(relevance_score, 0.0) >= ?
                      AND COALESCE(pool_expression, '') != ''
                      AND COALESCE(pool_topic_label, '') != ''
                      AND COALESCE(style_key, '') != ''
                      AND COALESCE(topic_group, '') != ''
                      AND (
                        source_platform != 'xiaohongshu'
                        OR content_url LIKE '%xsec_token=%'
                      )
                      {guard_sql}
                      {delight_guard_sql}
                      AND NOT EXISTS (
                        SELECT 1
                        FROM recommendations AS r
                        WHERE r.bvid = content_cache.bvid
                      )
                )
                SELECT bvid, source, source_platform, content_url
                FROM ranked
                WHERE group_rank <= ?
                """,
                (min_score, *guard_params, max_per_topic_group),
            )
        else:
            cursor = self.conn.execute(
                f"""
                SELECT bvid, source, source_platform, content_url
                FROM content_cache
                WHERE COALESCE(pool_status, 'fresh') = 'fresh'
                  AND COALESCE(feedback_type, '') != 'dislike'
                  AND COALESCE(relevance_score, 0.0) >= ?
                  AND COALESCE(pool_expression, '') != ''
                  AND COALESCE(pool_topic_label, '') != ''
                  AND COALESCE(style_key, '') != ''
                  AND COALESCE(topic_group, '') != ''
                  AND (
                    source_platform != 'xiaohongshu'
                    OR content_url LIKE '%xsec_token=%'
                  )
                  {guard_sql}
                  {delight_guard_sql}
                  AND NOT EXISTS (
                    SELECT 1
                    FROM recommendations AS r
                    WHERE r.bvid = content_cache.bvid
                  )
                """,
                (min_score, *guard_params),
            )
        viewed_content_keys = self.get_recent_viewed_content_keys()
        rows: list[dict[str, Any]] = []
        for row in cursor.fetchall():
            row_dict = dict(row)
            if not str(row_dict.get("bvid", "")).strip():
                continue
            if self._is_viewed_row(row_dict, viewed_content_keys):
                continue
            if not _is_linkable_pool_source(
                row["source"],
                row["source_platform"],
                row["content_url"],
            ):
                continue
            rows.append(row_dict)
        return rows

    def count_pool_available_candidates_by_source(
        self, *, max_per_topic_group: int = 3, xhs_self_nickname: str = ""
    ) -> dict[str, int]:
        """返回按 source family 分组、前端可见的 pool 可用性。"""
        rows = self._load_available_pool_candidate_rows(
            max_per_topic_group=max_per_topic_group,
            xhs_self_nickname=xhs_self_nickname,
        )
        counts: dict[str, int] = defaultdict(int)
        for row in rows:
            source_family = _pool_source_family(row["source"], row["source_platform"])
            counts[source_family] += 1
        return dict(counts)

    def _load_pool_raw_material_rows(self) -> list[dict[str, Any]]:
        """加载受 raw ceiling 约束的 raw fresh material 行。"""
        self._ensure_fresh_read()
        min_score = self._pool_admission_min_score()
        cursor = self.conn.execute(
            """
            SELECT
                bvid,
                source,
                source_platform,
                content_url,
                relevance_score,
                last_scored_at,
                pool_expression,
                pool_topic_label,
                style_key,
                topic_group
            FROM content_cache
            WHERE COALESCE(pool_status, 'fresh') = 'fresh'
              AND COALESCE(feedback_type, '') != 'dislike'
              AND COALESCE(relevance_score, 0.0) >= ?
              AND NOT EXISTS (
                SELECT 1 FROM recommendations AS r WHERE r.bvid = content_cache.bvid
              )
            """,
            (min_score,),
        )
        viewed_content_keys = self.get_recent_viewed_content_keys()
        rows: list[dict[str, Any]] = []
        for row in cursor.fetchall():
            row_dict = dict(row)
            if not str(row_dict.get("bvid", "")).strip():
                continue
            if self._is_viewed_row(row_dict, viewed_content_keys):
                continue
            rows.append(row_dict)
        return rows

    def count_pool_raw_material_candidates(self) -> int:
        """返回用于 raw-ceiling headroom 的 raw fresh material 计数。"""
        return (
            len(self._load_pool_raw_material_rows()) + self._count_pending_discovery_raw_material()
        )

    def count_pool_raw_material_by_source(self) -> dict[str, int]:
        """返回按 source family 分组的 raw fresh material。

        与 ``count_pool_candidates_by_source()`` 不同，这里有意计数
        pending/unopenable 行，如等待 ``xsec_token`` 的 XHS 笔记。
        """
        counts: dict[str, int] = defaultdict(int)
        for row in self._load_pool_raw_material_rows():
            source_family = _pool_source_family(row["source"], row["source_platform"])
            counts[source_family] += 1
        cursor = self.conn.execute(
            """
            SELECT source_platform, source_strategy, COUNT(*) AS count
            FROM discovery_candidates
            WHERE status IN ('pending_eval', 'evaluating', 'evaluated')
            GROUP BY source_platform, source_strategy
            """
        )
        for row in cursor.fetchall():
            source_family = _pool_source_family(row["source_strategy"], row["source_platform"])
            counts[source_family] += int(row["count"])
        return dict(counts)

    def count_pool_readiness(self, *, xhs_self_nickname: str = "") -> dict[str, int]:
        """返回按立即可服务行与 pending 行拆分的 pool 库存。

        ``available`` 是公开的"可换"计数。``raw`` 是 readiness 门之前的
        宽泛 fresh material。``pending`` 独立计数：最近查看过的行是
        unavailable，但不算 pending。
        """
        self._ensure_fresh_read()
        min_score = self._pool_admission_min_score()
        guard_sql = _xhs_self_author_guard_sql()
        guard_params = _xhs_self_author_guard_params(xhs_self_nickname)
        raw_cursor = self.conn.execute(
            f"""
            SELECT COUNT(*) AS count
            FROM content_cache
            WHERE COALESCE(pool_status, 'fresh') = 'fresh'
              AND COALESCE(feedback_type, '') != 'dislike'
              AND COALESCE(relevance_score, 0.0) >= ?
              {guard_sql}
              AND NOT EXISTS (
                SELECT 1
                FROM recommendations AS r
                WHERE r.bvid = content_cache.bvid
              )
            """,
            (min_score, *guard_params),
        )
        raw_count = int(raw_cursor.fetchone()["count"])
        pending_cursor = self.conn.execute(
            f"""
            SELECT
                bvid,
                content_id,
                source,
                source_platform,
                content_url,
                pool_expression,
                pool_topic_label,
                style_key,
                topic_group
            FROM content_cache
            WHERE COALESCE(pool_status, 'fresh') = 'fresh'
              AND COALESCE(feedback_type, '') != 'dislike'
              AND COALESCE(relevance_score, 0.0) >= ?
              {guard_sql}
              AND NOT EXISTS (
                SELECT 1
                FROM recommendations AS r
                WHERE r.bvid = content_cache.bvid
              )
            """,
            (min_score, *guard_params),
        )
        viewed_content_keys = self.get_recent_viewed_content_keys()
        pending_count = 0
        for row in pending_cursor.fetchall():
            item = dict(row)
            if self._is_viewed_row(item, viewed_content_keys):
                continue
            if (
                not str(item.get("pool_expression") or "").strip()
                or not str(item.get("pool_topic_label") or "").strip()
                or not str(item.get("style_key") or "").strip()
                or not str(item.get("topic_group") or "").strip()
                or not _is_linkable_pool_source(
                    item.get("source"),
                    item.get("source_platform"),
                    item.get("content_url"),
                )
            ):
                pending_count += 1

        status_counts = self.count_discovery_candidates_by_status()
        pending_eval_count = int(status_counts.get("pending_eval", 0)) + int(
            status_counts.get("evaluating", 0)
        )
        evaluated_pending_count = int(status_counts.get("evaluated", 0))
        discovery_pending_count = pending_eval_count + evaluated_pending_count

        return {
            "available": self.count_pool_candidates(xhs_self_nickname=xhs_self_nickname),
            "raw": raw_count + discovery_pending_count,
            "pending": pending_count + discovery_pending_count,
            "pending_eval": pending_eval_count,
            "evaluated_pending": evaluated_pending_count,
        }

    def count_pool_candidates_by_source(self) -> dict[str, int]:
        """返回按 discovery source family 分组的新鲜 pool 计数。"""
        min_score = self._pool_admission_min_score()
        cursor = self.conn.execute(
            """
            SELECT bvid, source, source_platform, content_url
            FROM content_cache
            WHERE COALESCE(pool_status, 'fresh') = 'fresh'
              AND COALESCE(feedback_type, '') != 'dislike'
              AND COALESCE(relevance_score, 0.0) >= ?
              AND NOT EXISTS (
                SELECT 1
                FROM recommendations AS r
                WHERE r.bvid = content_cache.bvid
              )
            """,
            (min_score,),
        )
        viewed_content_keys = self.get_recent_viewed_content_keys()
        counts: dict[str, int] = defaultdict(int)
        for row in cursor.fetchall():
            bvid = str(row["bvid"]).strip()
            row_dict = dict(row)
            if not bvid or self._is_viewed_row(row_dict, viewed_content_keys):
                continue
            if not _is_linkable_pool_source(
                row["source"],
                row["source_platform"],
                row["content_url"],
            ):
                continue
            source_family = _pool_source_family(row["source"], row["source_platform"])
            counts[source_family] += 1
        return dict(counts)

    def get_pool_distribution_counts(self) -> dict[str, dict[str, int]]:
        """返回按 topic、style 与 franchise 分组的新鲜 pool 计数。"""
        min_score = self._pool_admission_min_score()
        cursor = self.conn.execute(
            """
            SELECT bvid, topic_group, style_key, franchise_key, source, source_platform, content_url
            FROM content_cache
            WHERE COALESCE(pool_status, 'fresh') = 'fresh'
              AND COALESCE(feedback_type, '') != 'dislike'
              AND COALESCE(relevance_score, 0.0) >= ?
              AND COALESCE(pool_expression, '') != ''
              AND COALESCE(pool_topic_label, '') != ''
              AND NOT EXISTS (
                SELECT 1
                FROM recommendations AS r
                WHERE r.bvid = content_cache.bvid
              )
            """,
            (min_score,),
        )
        viewed_content_keys = self.get_recent_viewed_content_keys()
        counts: dict[str, dict[str, int]] = {
            "topic_group": defaultdict(int),
            "style_key": defaultdict(int),
            "franchise_key": defaultdict(int),
        }
        for row in cursor.fetchall():
            bvid = str(row["bvid"]).strip()
            row_dict = dict(row)
            if not bvid or self._is_viewed_row(row_dict, viewed_content_keys):
                continue
            if not _is_linkable_pool_source(
                row["source"],
                row["source_platform"],
                row["content_url"],
            ):
                continue
            for axis in ("topic_group", "style_key", "franchise_key"):
                value = str(row[axis] or "").strip()
                if value:
                    counts[axis][value] += 1
        return {axis: dict(axis_counts) for axis, axis_counts in counts.items()}

    def get_pool_topic_counts_by_platform(self) -> dict[str, dict[str, int]]:
        """按平台分组的 fresh servable pool 行 ``topic_group`` 计数（P3.1）。

        与 :meth:`get_pool_distribution_counts` 使用相同的 servable 过滤，
        但以 ``source_platform`` → ``{platform: {topic_group: count}}`` 为
        key，这样 keyword planner 可以避免 *该平台* 已饱和的 topic，而不是
        pool 范围内的（B 站堆积的 topic 在小红书可能很稀缺）。出错返回
        ``{}``。
        """
        try:
            min_score = self._pool_admission_min_score()
            cursor = self.conn.execute(
                """
                SELECT bvid, topic_group, style_key, franchise_key,
                       source, source_platform, content_url
                FROM content_cache
                WHERE COALESCE(pool_status, 'fresh') = 'fresh'
                  AND COALESCE(feedback_type, '') != 'dislike'
                  AND COALESCE(relevance_score, 0.0) >= ?
                  AND COALESCE(pool_expression, '') != ''
                  AND COALESCE(pool_topic_label, '') != ''
                  AND NOT EXISTS (
                    SELECT 1 FROM recommendations AS r WHERE r.bvid = content_cache.bvid
                  )
                """,
                (min_score,),
            )
            viewed_content_keys = self.get_recent_viewed_content_keys()
        except Exception:
            logger.debug("get_pool_topic_counts_by_platform query failed", exc_info=True)
            return {}
        counts: dict[str, dict[str, int]] = {}
        for row in cursor.fetchall():
            bvid = str(row["bvid"]).strip()
            row_dict = dict(row)
            if not bvid or self._is_viewed_row(row_dict, viewed_content_keys):
                continue
            if not _is_linkable_pool_source(
                row["source"], row["source_platform"], row["content_url"]
            ):
                continue
            platform = str(row["source_platform"] or "").strip()
            topic = str(row["topic_group"] or "").strip()
            if not platform or not topic:
                continue
            counts.setdefault(platform, defaultdict(int))[topic] += 1
        return {platform: dict(topics) for platform, topics in counts.items()}

    def get_admitted_topic_counts_by_platform(self) -> dict[str, dict[str, int]]:
        """按平台分组的所有 admitted content 的 ``topic_group`` 计数（P3.3）。

        :meth:`get_pool_topic_counts_by_platform` 计数的是 *当前 servable
        pool*（饱和信号 —— 现在太多了），而这里计数的是每个平台曾经写入
        cache 的每一个非 dislike、可链接的行（无论是否 serve 过）—— 一个
        *supply-advantage* 信号：每个平台实际为该用户交付过哪些 topic。
        keyword planner 把 top topics 作为静态 ``<supply_advantage>`` 表的
        数据驱动补充回填（减去该平台当前的 avoid 集合）。出错返回 ``{}``。
        """
        try:
            min_score = self._pool_admission_min_score()
            cursor = self.conn.execute(
                """
                SELECT topic_group, source, source_platform, content_url
                FROM content_cache
                WHERE COALESCE(feedback_type, '') != 'dislike'
                  AND COALESCE(relevance_score, 0.0) >= ?
                  AND COALESCE(topic_group, '') != ''
                """,
                (min_score,),
            )
        except Exception:
            logger.debug("get_admitted_topic_counts_by_platform query failed", exc_info=True)
            return {}
        counts: dict[str, dict[str, int]] = {}
        for row in cursor.fetchall():
            if not _is_linkable_pool_source(
                row["source"], row["source_platform"], row["content_url"]
            ):
                continue
            platform = str(row["source_platform"] or "").strip()
            topic = str(row["topic_group"] or "").strip()
            if not platform or not topic:
                continue
            counts.setdefault(platform, defaultdict(int))[topic] += 1
        return {platform: dict(topics) for platform, topics in counts.items()}

    def canonicalize_topic_groups(self, canonical_map: dict[str, str]) -> int:
        """按 map 把 ``content_cache.topic_group`` 重写为规范形式。

        v0.3.56+：``canonical_map`` 由
        ``RecommendationEngine.prewarm_supergroup_embeddings`` 构造，映射
        规范化（小写 + 去空白）后的 topic_group → 规范形式。不应用到
        数据库行的话，合并只会在 serve 时触发，下游分析
        （``get_topic_group_samples``、popup status 中的按 topic 计数）
        看到的都是未合并的 label。

        返回实际更新的行数。空输入或全 identity 映射短路返回 0。
        """
        if not canonical_map:
            return 0
        # 批量更新：每个 (src → dst) 对一条语句。纯 SQL，无行级
        # fetch。单事务批量，对 WAL 友好。只重写 lowercased+trimmed
        # topic_group 精确匹配 source key 的行 —— 非匹配行保留大小写
        # 原样存储。
        total = 0
        for src, dst in canonical_map.items():
            if src == dst or not src or not dst:
                continue
            cursor = self._execute_write(
                """
                UPDATE content_cache
                SET topic_group = ?
                WHERE LOWER(TRIM(COALESCE(topic_group, ''))) = ?
                  AND COALESCE(topic_group, '') != ?
                """,
                (dst, src, dst),
            )
            total += cursor.rowcount or 0
        return total

    def count_pool_by_franchise(self) -> dict[str, int]:
        """返回 fresh pool 项的 ``{franchise_key_lower: count}``。

        供 discovery 的 pool 范围 franchise 配额检查（v0.3.50+）使用，
        这样一个已在 pool 中有很多项的 franchise 就不会在多个 discovery
        周期中持续堆积。空 franchise_key 被排除 —— 大多数通用 content 没有
        IP 信号，配额只对 series / IP / UP 驱动的 group 有意义。
        """
        min_score = self._pool_admission_min_score()
        cursor = self.conn.execute(
            """
            SELECT LOWER(TRIM(franchise_key)) AS fk, COUNT(*) AS n
            FROM content_cache
            WHERE COALESCE(pool_status, 'fresh') = 'fresh'
              AND COALESCE(feedback_type, '') != 'dislike'
              AND COALESCE(relevance_score, 0.0) >= ?
              AND franchise_key IS NOT NULL
              AND TRIM(franchise_key) != ''
            GROUP BY LOWER(TRIM(franchise_key))
            """,
            (min_score,),
        )
        return {str(row["fk"]): int(row["n"]) for row in cursor.fetchall() if row["fk"]}

    def get_distinct_topic_groups(self) -> list[str]:
        """返回 fresh pool 中非空的 distinct ``topic_group`` 值。

        供 recommendation 预热使用，使 embedding cache 在 popup 命中
        ``serve()`` 之前就热起来。在无 JOIN 的小列上做廉价的 GROUP BY。
        """
        min_score = self._pool_admission_min_score()
        cursor = self.conn.execute(
            """
            SELECT DISTINCT topic_group
            FROM content_cache
            WHERE COALESCE(pool_status, 'fresh') = 'fresh'
              AND COALESCE(relevance_score, 0.0) >= ?
              AND COALESCE(topic_group, '') != ''
            """,
            (min_score,),
        )
        return [str(row[0]) for row in cursor.fetchall() if row and row[0]]

    def get_active_pool_topic_groups(
        self,
        *,
        limit: int = 30,
        min_count: int = 2,
    ) -> list[str]:
        """返回当前 active pool 中 top ``limit`` 个 topic_group 名。

        供 ExploreStrategy 用于了解 pool 已覆盖哪些 topic，让生成 explore
        domain 的 LLM 可以避免重复提议它们（v0.3.31 explore 盲点模式）。
        过滤掉成员少于 ``min_count`` 的 group，这样单个一次性 item 不会
        阻塞对实际空区域的探索。结果按 group size DESC 排序。
        """
        min_score = self._pool_admission_min_score()
        cursor = self.conn.execute(
            """
            SELECT topic_group, COUNT(*) AS n
            FROM content_cache
            WHERE COALESCE(pool_status, 'fresh') = 'fresh'
              AND COALESCE(relevance_score, 0.0) >= ?
              AND COALESCE(topic_group, '') != ''
              AND NOT EXISTS (
                SELECT 1 FROM recommendations AS r WHERE r.bvid = content_cache.bvid
              )
            GROUP BY topic_group
            HAVING COUNT(*) >= ?
            ORDER BY n DESC, topic_group ASC
            LIMIT ?
            """,
            (min_score, max(1, int(min_count)), max(1, int(limit))),
        )
        return [str(row["topic_group"]) for row in cursor.fetchall()]

    def get_topic_group_samples(
        self,
        *,
        samples_per_group: int = 5,
        top_n_groups: int = 60,
    ) -> list[tuple[str, list[str]]]:
        """为每个 fresh-pool ``topic_group`` 返回最多 N 个样本标题。

        返回按成员数排名的 top ``top_n_groups`` 个 group（同分以组内
        最高 ``relevance_score`` 决胜）。长尾 micro-topic（1-2 项）几乎
        永远不会在单个 40 候选 recommendation 批次中一起出现，因此投入
        API 预算对它们做 merge-map 只会增加延迟，不影响可见的多样性。

        供 recommendation prewarmer 用于构建准确的 supergroup-merge
        map：短的中文 label（``赛博朋克``、``动漫`` ……）在 embedding
        空间中单独嵌入时灾难性模糊 —— 它们需要 title-context 消歧。
        样本标题在每个 group 内按 ``relevance_score`` 取 top，因此
        输入在 pool 稳定时相当稳定。
        """
        min_score = self._pool_admission_min_score()
        cursor = self.conn.execute(
            """
            SELECT topic_group, title, relevance_score
            FROM content_cache
            WHERE COALESCE(pool_status, 'fresh') = 'fresh'
              AND COALESCE(relevance_score, 0.0) >= ?
              AND COALESCE(topic_group, '') != ''
              AND COALESCE(title, '') != ''
            ORDER BY topic_group, relevance_score DESC, bvid
            """,
            (min_score,),
        )
        by_group: dict[str, list[str]] = defaultdict(list)
        group_max_score: dict[str, float] = {}
        group_count: dict[str, int] = defaultdict(int)
        for row in cursor.fetchall():
            group = str(row["topic_group"]).strip()
            title = str(row["title"]).strip()
            if not group or not title:
                continue
            group_count[group] += 1
            score = float(row["relevance_score"] or 0.0)
            if score > group_max_score.get(group, -1.0):
                group_max_score[group] = score
            if len(by_group[group]) < samples_per_group:
                by_group[group].append(title)

        # 按成员数降序、分数降序、标签升序排名（稳定排序）。
        ranked = sorted(
            by_group.keys(),
            key=lambda g: (-group_count[g], -group_max_score.get(g, 0.0), g),
        )
        return [(group, by_group[group]) for group in ranked[:top_n_groups]]

    def trim_explore_cluster_overflow(self, *, max_per_cluster: int = 3) -> int:
        """把高风险 topic cluster 中多余的 fresh explore 项标记为 suppressed。"""
        min_score = self._pool_admission_min_score()
        cursor = self.conn.execute(
            """
            SELECT bvid, title, topic_key, relevance_score, last_scored_at
            FROM content_cache
            WHERE COALESCE(pool_status, 'fresh') = 'fresh'
              AND COALESCE(feedback_type, '') != 'dislike'
              AND COALESCE(relevance_score, 0.0) >= ?
              AND COALESCE(source, '') = 'explore'
            """,
            (min_score,),
        )
        rows = [dict(row) for row in cursor.fetchall()]
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            cluster = self._explore_risk_cluster(row)
            if not cluster:
                continue
            grouped[cluster].append(row)

        overflow_bvids: list[str] = []
        for items in grouped.values():
            ranked = sorted(
                items,
                key=lambda row: (
                    -float(row.get("relevance_score", 0.0) or 0.0),
                    -self._sort_timestamp_score(str(row.get("last_scored_at", ""))),
                    str(row.get("bvid", "")),
                ),
            )
            overflow_bvids.extend(
                str(row.get("bvid", "")).strip() for row in ranked[max(0, max_per_cluster) :]
            )

        clean_bvids = [bvid for bvid in overflow_bvids if bvid]
        if not clean_bvids:
            return 0

        placeholders = ", ".join("?" for _ in clean_bvids)
        self._execute_write(
            f"""
            UPDATE content_cache
            SET pool_status = 'suppressed'
            WHERE bvid IN ({placeholders})
            """,
            clean_bvids,
        )
        return len(clean_bvids)

    def trim_topic_group_overflow(self, *, max_per_group: int) -> int:
        """把任意单个 ``topic_group`` 超过 *max_per_group* 的 fresh 项标记为 suppressed。

        把 source 与 keyword 特定的 :meth:`trim_explore_cluster_overflow`
        推广为对每个有值的 ``topic_group`` 的跨 source 动态上限。没有这层，
        单个 topic（如 ``人工智能``）会随着 related_chain/search/explore
        在多个周期中持续返回同一个粗粒度 group 而累积数百个 fresh 候选 ——
        m118 的 per-call ``_compress_topic_repeats`` 不会跨周期组合，而
        explore-only 的 cluster cap 看不到 related_chain 或 search。

        ``topic_group`` 为空的项被忽略。在超上限的 group 内，分数最高 /
        最近打分的项被保留；其余被设为 ``pool_status='suppressed'``。

        v0.3.31+：丢弃项时发一条 INFO 日志，点名溢出的 group 及每个 group
        丢了多少项。没有这层时函数是静默运行的 —— 运维无法判断多样性
        机制是否真的在裁剪，还是在睡觉。
        """
        if max_per_group <= 0:
            return 0

        min_score = self._pool_admission_min_score()
        cursor = self.conn.execute(
            """
            SELECT bvid, topic_group, relevance_score, last_scored_at
            FROM content_cache
            WHERE COALESCE(pool_status, 'fresh') = 'fresh'
              AND COALESCE(feedback_type, '') != 'dislike'
              AND COALESCE(relevance_score, 0.0) >= ?
              AND COALESCE(topic_group, '') != ''
              AND NOT EXISTS (
                SELECT 1 FROM recommendations AS r WHERE r.bvid = content_cache.bvid
              )
            """,
            (min_score,),
        )
        rows = [dict(row) for row in cursor.fetchall()]
        if not rows:
            return 0

        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            group = str(row.get("topic_group", "") or "").strip().lower()
            if not group:
                continue
            grouped[group].append(row)

        overflow_bvids: list[str] = []
        # v0.3.31+：为 INFO 日志追踪按组丢弃计数
        drops_per_group: dict[str, int] = {}
        for group_name, items in grouped.items():
            if len(items) <= max_per_group:
                continue
            ranked = sorted(
                items,
                key=lambda row: (
                    -float(row.get("relevance_score", 0.0) or 0.0),
                    -self._sort_timestamp_score(str(row.get("last_scored_at", ""))),
                    str(row.get("bvid", "")),
                ),
            )
            losers = ranked[max_per_group:]
            drops_per_group[group_name] = len(losers)
            overflow_bvids.extend(str(row.get("bvid", "")).strip() for row in losers)

        clean_bvids = [bvid for bvid in overflow_bvids if bvid]
        if not clean_bvids:
            return 0

        placeholders = ", ".join("?" for _ in clean_bvids)
        self._execute_write(
            f"""
            UPDATE content_cache
            SET pool_status = 'suppressed'
            WHERE bvid IN ({placeholders})
            """,
            clean_bvids,
        )

        # 裁剪最多的 top 10 组，保持日志行可读。
        # 降级到 DEBUG：这每分钟由刷新 tick 运行一次。当 pool 处于
        # 稳态且某个组持续超 cap ~8 项时，同一行在 INFO 级别每天会
        # 被记 1440 次。调用方可以在裁剪形态确实变化时升回 INFO
        # （见 refresh.enforce_pool_cap）。
        top = sorted(drops_per_group.items(), key=lambda kv: -kv[1])[:10]
        logger.debug(
            "[diversity] trim_topic_group_overflow: cap=%d, dropped=%d items "
            "across %d over-cap groups, top: %s",
            max_per_group,
            len(clean_bvids),
            len(drops_per_group),
            ", ".join(f"{g}:{c}" for g, c in top),
        )
        return len(clean_bvids)

    def trim_pool_to_target_count(
        self,
        *,
        target: int,
        source_share_quotas: dict[str, int] | None = None,
    ) -> int:
        """把溢出的 fresh 项标记为 suppressed，使 pool 不超过 *target*。

        排序（保留哪些）：更高 ``relevance_score`` > 更新
        ``last_scored_at`` > 非 ``explore`` source > 稳定 ``bvid``。已
        surface 为 recommendation 的项不计入 —— recommendation 侧把 pool
        当作队列，已消费的行不会在这里被裁剪。

        当提供 ``source_share_quotas`` 时，裁剪会尊重按 source family
        的份额目标：已达或超过配额的 source family 中的项会 *先于* 未达
        配额 source 中的低分项被 suppressed。没有这层，仅按分数裁剪会
        在高 relevance source（search、related_chain）溢出时系统性砍掉
        低 relevance source（trending、explore）—— 破坏 per-source 多样
        性目标。小红书扩展通道（task/search/explore/profile）合并到单一
        ``xiaohongshu`` family 下。
        """
        if target <= 0:
            return 0

        rows = self._load_pool_raw_material_rows()
        if len(rows) <= target:
            return 0

        ranked = sorted(
            rows,
            key=self._pool_trim_keep_key,
        )

        if source_share_quotas:
            # 三层保护，使配额未满的 source 保持完整：
            #   protected：source 总数 ≤ 配额的项，或 source 总数 > 配额
            #              时的 top-N 项（N=配额）
            #   negotiable_tracked：超配额 tracked source 的底部
            #              （总数-配额）项
            #   negotiable_untracked：没有声明份额的 source 的项 ——
            #              在碰 protected 之前先裁这些。
            # 最终保留遍历顺序：protected → negotiable_untracked
            # → negotiable_tracked。确保 trending（未达配额）即使因
            # untracked source 占了名额导致 in_quota 总和 > target，
            # 也保持 100% protected。
            counts_per_source: dict[str, int] = defaultdict(int)
            for row in rows:
                source_family = _pool_source_family(
                    row.get("source", ""),
                    row.get("source_platform", ""),
                )
                counts_per_source[source_family] += 1

            protected: list[dict[str, Any]] = []
            negotiable_tracked: list[dict[str, Any]] = []
            negotiable_untracked: list[dict[str, Any]] = []
            seen: dict[str, int] = defaultdict(int)
            for row in ranked:
                source_family = _pool_source_family(
                    row.get("source", ""),
                    row.get("source_platform", ""),
                )
                quota = source_share_quotas.get(source_family)
                if quota is None:
                    negotiable_untracked.append(row)
                    continue
                if counts_per_source[source_family] <= quota:
                    # 整个 source 未达配额 —— 每项都受保护
                    protected.append(row)
                else:
                    # 超配额：top `quota` 项受保护，其余可协商
                    if seen[source_family] < quota:
                        protected.append(row)
                        seen[source_family] += 1
                    else:
                        negotiable_tracked.append(row)
            ranked = protected + negotiable_untracked + negotiable_tracked

        overflow_rows = ranked[target:]
        overflow_bvids = [str(row.get("bvid", "")).strip() for row in overflow_rows]
        clean_bvids = [bvid for bvid in overflow_bvids if bvid]
        if not clean_bvids:
            return 0

        placeholders = ", ".join("?" for _ in clean_bvids)
        self._execute_write(
            f"""
            UPDATE content_cache
            SET pool_status = 'suppressed'
            WHERE bvid IN ({placeholders})
            """,
            clean_bvids,
        )
        # v0.3.31+：记录按 source 的明细，让运维看到配额守卫是否在生效
        # （如"explore 溢出 80%"→ 修 discovery 周期，而不是推荐器）。
        per_source: dict[str, int] = defaultdict(int)
        for row in overflow_rows:
            family = _pool_source_family(
                row.get("source", ""),
                row.get("source_platform", ""),
            )
            per_source[family] += 1
        breakdown = ", ".join(
            f"{src}:{cnt}" for src, cnt in sorted(per_source.items(), key=lambda kv: -kv[1])
        )
        logger.info(
            "[diversity] trim_pool_to_target_count: target=%d, before=%d, "
            "suppressed=%d, by-source: %s",
            target,
            len(rows),
            len(clean_bvids),
            breakdown or "(none)",
        )
        return len(clean_bvids)

    def trim_pool_source_overflow(self, *, source_share_quotas: dict[str, int]) -> int:
        """把超过 platform-family pool 配额的 fresh 行标记为 suppressed。

        ``trim_pool_to_target_count`` 限制 pool 的总大小。这一 pass 独立地
        限制每个被追踪的 platform family，这样一个过满的 family 不能在
        总 pool 仍低于 target 时占用为另一个 source 预留的容量。
        """
        clean_quotas: dict[str, int] = {}
        for source_family, quota in source_share_quotas.items():
            try:
                clean_quotas[str(source_family)] = max(0, int(quota))
            except (TypeError, ValueError):
                continue
        if not clean_quotas:
            return 0

        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in self._load_pool_raw_material_rows():
            source_family = _pool_source_family(row["source"], row["source_platform"])
            if source_family in clean_quotas:
                grouped[source_family].append(row)

        overflow_rows: list[dict[str, Any]] = []
        for source_family, rows in grouped.items():
            quota = clean_quotas[source_family]
            if len(rows) <= quota:
                continue
            ranked = sorted(
                rows,
                key=self._pool_trim_keep_key,
            )
            overflow_rows.extend(ranked[quota:])

        clean_bvids = [str(row.get("bvid", "")).strip() for row in overflow_rows]
        clean_bvids = [bvid for bvid in clean_bvids if bvid]
        if not clean_bvids:
            return 0

        placeholders = ", ".join("?" for _ in clean_bvids)
        self._execute_write(
            f"""
            UPDATE content_cache
            SET pool_status = 'suppressed'
            WHERE bvid IN ({placeholders})
            """,
            clean_bvids,
        )
        per_source: dict[str, int] = defaultdict(int)
        for row in overflow_rows:
            family = _pool_source_family(
                row.get("source", ""),
                row.get("source_platform", ""),
            )
            per_source[family] += 1
        breakdown = ", ".join(
            f"{src}:{cnt}" for src, cnt in sorted(per_source.items(), key=lambda kv: -kv[1])
        )
        logger.info(
            "[diversity] trim_pool_source_overflow: suppressed=%d, by-source: %s",
            len(clean_bvids),
            breakdown or "(none)",
        )
        return len(clean_bvids)

    def reactivate_under_quota_pool_sources(
        self,
        *,
        target: int,
        source_share_quotas: dict[str, int],
        raw_source_share_quotas: dict[str, int] | None = None,
    ) -> int:
        """把未达配额的 source family 中 suppressed 候选移回 fresh。

        这是一个针对已满但不均衡 pool 的 source-balance 修复 pass。它只
        重新激活其他方面符合 recommendation pool 条件的行。重新激活由
        前端可见的缺口驱动，但受 raw-material headroom 限制，这样已占用
        某 source raw ceiling 的 pending 行不会触发更多 fresh 库存。
        """
        if target <= 0 or not source_share_quotas:
            return 0

        current_counts = self.count_pool_available_candidates_by_source()
        raw_counts = self.count_pool_raw_material_by_source()
        raw_quotas = raw_source_share_quotas or source_share_quotas
        deficits = {
            source_family: min(
                min(target, max(0, int(quota))) - int(current_counts.get(source_family, 0)),
                max(
                    0,
                    int(raw_quotas.get(source_family, quota))
                    - int(raw_counts.get(source_family, 0)),
                ),
            )
            for source_family, quota in source_share_quotas.items()
            if int(quota) > 0
        }
        deficits = {source: deficit for source, deficit in deficits.items() if deficit > 0}
        if not deficits:
            return 0

        min_score = self._pool_admission_min_score()
        cursor = self.conn.execute(
            """
            SELECT bvid, source, source_platform, content_url, relevance_score, last_scored_at
            FROM content_cache
            WHERE COALESCE(pool_status, 'fresh') = 'suppressed'
              AND COALESCE(feedback_type, '') != 'dislike'
              AND COALESCE(relevance_score, 0.0) >= ?
              AND NOT EXISTS (
                SELECT 1 FROM recommendations AS r WHERE r.bvid = content_cache.bvid
              )
            ORDER BY
                CASE candidate_tier WHEN 'primary' THEN 0 ELSE 1 END ASC,
                relevance_score DESC,
                last_scored_at DESC,
                bvid ASC
            """,
            (min_score,),
        )
        viewed_content_keys = self.get_recent_viewed_content_keys()
        selected_bvids: list[str] = []
        selected_counts: dict[str, int] = defaultdict(int)
        target_selection_count = sum(deficits.values())

        for row in cursor.fetchall():
            bvid = str(row["bvid"]).strip()
            row_dict = dict(row)
            if not bvid or self._is_viewed_row(row_dict, viewed_content_keys):
                continue
            if not _is_linkable_pool_source(
                row["source"],
                row["source_platform"],
                row["content_url"],
            ):
                continue
            source_family = _pool_source_family(row["source"], row["source_platform"])
            deficit = deficits.get(source_family, 0)
            if deficit <= 0 or selected_counts[source_family] >= deficit:
                continue
            selected_bvids.append(bvid)
            selected_counts[source_family] += 1
            if len(selected_bvids) >= target_selection_count:
                break

        if not selected_bvids:
            return 0

        placeholders = ", ".join("?" for _ in selected_bvids)
        self._execute_write(
            f"""
            UPDATE content_cache
            SET pool_status = 'fresh'
            WHERE bvid IN ({placeholders})
            """,
            selected_bvids,
        )
        return len(selected_bvids)

    @staticmethod
    def _balance_pool_rows(rows: list[dict[str, Any]], *, limit: int) -> list[dict[str, Any]]:
        """从 relevance 排序的 pool 中按 content topic 平衡做轮询采样。

        按 ``topic_group`` 分桶（回退到 ``topic_key``，再回退到一个哨兵
        值），这样 relevance 头部中一个占主导的 topic 不会挤掉候选窗口。
        Source/platform 被有意忽略 —— content 侧特征驱动丰富度，而不是
        来源。

        轮询总是执行（即使 ``len(rows) <= limit``），这样返回的顺序对
        可能做子选择的下游 caller 也是平衡的；否则 SQL 排序可能把同一
        topic 的多项排在顶部相邻位置。
        """
        if limit <= 0 or len(rows) <= 1:
            return rows[:limit]

        buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
        topic_order: list[str] = []
        for row in rows:
            key = str(row.get("topic_group", "") or "").strip().lower()
            if not key:
                key = str(row.get("topic_key", "") or "").strip().lower()
            if not key:
                key = "unknown"
            if key not in buckets:
                topic_order.append(key)
            buckets[key].append(row)

        balanced: list[dict[str, Any]] = []
        while len(balanced) < limit:
            progressed = False
            for key in topic_order:
                bucket = buckets[key]
                if not bucket:
                    continue
                balanced.append(bucket.pop(0))
                progressed = True
                if len(balanced) >= limit:
                    break
            if not progressed:
                break
        return balanced[:limit]

    def get_recent_viewed_bvids(self, limit: int = 2000) -> set[str]:
        """从 view 事件中返回最近被查看过的 BVID。"""
        cursor = self.conn.execute(
            """
            SELECT url, metadata
            FROM events
            WHERE event_type = 'view'
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        )
        viewed_bvids: set[str] = set()
        for row in cursor.fetchall():
            bvid = self._extract_bvid_from_view_event(dict(row))
            if bvid:
                viewed_bvids.add(bvid)
        return viewed_bvids

    def get_recent_viewed_content_keys(self, limit: int = 2000) -> set[str]:
        """返回跨受支持 source 的最近被查看 content identity。

        key 是 source-aware（``source_platform:content_id``），并包含
        legacy Bilibili caller 使用的裸 BVID。
        """
        cursor = self.conn.execute(
            """
            SELECT url, metadata
            FROM events
            WHERE event_type = 'view'
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        )
        viewed_keys: set[str] = set()
        for row in cursor.fetchall():
            viewed_keys.update(self._extract_content_keys_from_view_event(dict(row)))
        return viewed_keys

    @staticmethod
    def _explore_risk_cluster(row: dict[str, Any]) -> str:
        haystack = " ".join(
            [
                str(row.get("topic_key", "") or ""),
                str(row.get("title", "") or ""),
            ]
        ).lower()
        if not haystack.strip():
            return ""
        compact = re.sub(r"\s+", "", haystack)
        for cluster, keywords in _EXPLORE_HIGH_RISK_CLUSTERS:
            if any(keyword in compact for keyword in keywords):
                return cluster
        return ""

    @staticmethod
    def _sort_timestamp_score(value: str) -> float:
        if not value:
            return 0.0
        normalized = value.replace(" ", "T")
        try:
            from datetime import datetime

            return datetime.fromisoformat(normalized).timestamp()
        except ValueError:
            return 0.0

    def _pool_trim_keep_key(self, row: dict[str, Any]) -> tuple[int, int, float, float, int, str]:
        """把 fresh raw material 按最值得保留到最不值得保留排序。

        Raw-ceiling 裁剪包含 pending 行，因此 servability 必须排在
        relevance 之前：绝不能因为一个 pending 行分数更高，就保留它
        而不是同一裁剪候选集中可打开的行。
        """
        linkable = _is_linkable_pool_source(
            row.get("source"),
            row.get("source_platform"),
            row.get("content_url"),
        )
        ready = all(
            str(row.get(field, "") or "").strip()
            for field in ("pool_expression", "pool_topic_label", "style_key", "topic_group")
        )
        return (
            0 if linkable else 1,
            0 if ready else 1,
            -float(row.get("relevance_score", 0.0) or 0.0),
            -self._sort_timestamp_score(str(row.get("last_scored_at", ""))),
            1 if str(row.get("source", "") or "") == "explore" else 0,
            str(row.get("bvid", "")),
        )

    def mark_pool_items_shown(self, bvids: list[str]) -> None:
        """把 discovery-pool 项标记为已在 recommendation 中展示过。"""
        clean_bvids = [item for item in bvids if item]
        if not clean_bvids:
            return
        placeholders = ", ".join("?" for _ in clean_bvids)
        self._execute_write(
            f"""
            UPDATE content_cache
            SET pool_status = 'shown',
                recommended_at = CURRENT_TIMESTAMP
            WHERE bvid IN ({placeholders})
            """,
            clean_bvids,
        )

    def evict_stale_pool_items(self, *, max_age_days: int = 14) -> int:
        """把超过 *max_age_days* 的 pool 项标记为 stale。"""
        cursor = self._execute_write(
            """
            UPDATE content_cache
            SET pool_status = 'stale'
            WHERE pool_status = 'fresh'
              AND discovered_at < datetime('now', '-' || ? || ' days')
              AND NOT EXISTS (
                SELECT 1 FROM recommendations AS r WHERE r.bvid = content_cache.bvid
              )
            """,
            (max_age_days,),
        )
        return cursor.rowcount

    def purge_pool_by_disliked_topics(self, topics: list[str]) -> int:
        """把匹配新 dislike 的 fresh pool 候选标记为 purged。

        匹配策略（在 SQLite 层全部大小写敏感 —— 中文文本使大小写折叠
        无意义，ASCII 匹配仍然有效）：
          1. ``topic_key``、``topic_group`` 或 ``pool_topic_label`` 精确匹配
          2. ``title`` 或 ``pool_topic_label`` 子串匹配
             （当 dislike 是"鬼畜"时能匹配到"鬼畜合集"）

        只有 ``pool_status = 'fresh'`` 的候选受影响 —— 历史行
        （``shown``、``feedbacked``、``stale``）保留以供审计。已推荐项
        被跳过，使 recommendation 历史保持完整。

        Args:
            topics：新添加的 dislike topic（已 strip、非空字符串）。

        Returns:
            转换为 ``pool_status = 'purged_by_dislike'`` 的行数。
        """
        clean = [t.strip() for t in topics if t and t.strip()]
        if not clean:
            return 0

        # 动态构建匹配子句。全程使用参数化查询 —— topic 值可能包含
        # SQL 元字符，绝不能插值到查询字符串中。
        exact_placeholders = ", ".join("?" for _ in clean)
        like_conditions = " OR ".join("title LIKE ? OR pool_topic_label LIKE ?" for _ in clean)

        params: list[Any] = []
        params.extend(clean)  # topic_key IN (...)
        params.extend(clean)  # topic_group IN (...)
        params.extend(clean)  # pool_topic_label IN (...)
        for topic in clean:
            like = f"%{topic}%"
            params.append(like)  # title LIKE ?
            params.append(like)  # pool_topic_label LIKE ?

        cursor = self._execute_write(
            f"""
            UPDATE content_cache
            SET pool_status = 'purged_by_dislike'
            WHERE COALESCE(pool_status, 'fresh') = 'fresh'
              AND NOT EXISTS (
                SELECT 1 FROM recommendations AS r WHERE r.bvid = content_cache.bvid
              )
              AND (
                topic_key IN ({exact_placeholders})
                OR topic_group IN ({exact_placeholders})
                OR pool_topic_label IN ({exact_placeholders})
                OR {like_conditions}
              )
            """,
            params,
        )
        return cursor.rowcount

    def get_fresh_pool_candidates_for_purge_scan(
        self,
        *,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        """返回用于语义扫描的 fresh、尚未被推荐的 pool 候选。

        只返回 embedding 匹配所需的字段：
        bvid、title、topic_key、topic_group、pool_topic_label。
        """
        cursor = self.conn.execute(
            """
            SELECT bvid, title, topic_key, topic_group, pool_topic_label
            FROM content_cache
            WHERE COALESCE(pool_status, 'fresh') = 'fresh'
              AND NOT EXISTS (
                SELECT 1 FROM recommendations AS r WHERE r.bvid = content_cache.bvid
              )
            ORDER BY discovered_at DESC
            LIMIT ?
            """,
            (limit,),
        )
        return [dict(row) for row in cursor.fetchall()]

    def mark_pool_items_purged_by_dislike(self, bvids: list[str]) -> int:
        """把指定 bvid 标记为 purged_by_dislike（仅当前为 fresh 时）。"""
        clean = [b.strip() for b in bvids if b and b.strip()]
        if not clean:
            return 0
        placeholders = ", ".join("?" for _ in clean)
        cursor = self._execute_write(
            f"""
            UPDATE content_cache
            SET pool_status = 'purged_by_dislike'
            WHERE bvid IN ({placeholders})
              AND COALESCE(pool_status, 'fresh') = 'fresh'
            """,
            clean,
        )
        return cursor.rowcount

    def get_pool_candidates_needing_evaluation(
        self, limit: int = 20, *, xhs_self_nickname: str = ""
    ) -> list[dict[str, Any]]:
        """返回缺少 LLM content 分类的 fresh pool 候选。

        针对 ``style_key`` 与 ``topic_group`` 均为空的项 —— 通常是来自
        非 bilibili source（如 xiaohongshu）、未经 discovery 引擎
        ``evaluate_content`` 流程直接写入 ``content_cache`` 的 content。

        这些项需要 LLM 评估以获得 ``style_key``、``topic_group`` 和
        ``relevance_score``，这样 ``_select_diversified_batch`` 中的
        多样性机制才能把它们与 bilibili content 同等对待。
        """
        guard_sql = _xhs_self_author_guard_sql()
        guard_params = _xhs_self_author_guard_params(xhs_self_nickname)
        cursor = self.conn.execute(
            f"""
            SELECT *
            FROM content_cache
            WHERE COALESCE(pool_status, 'fresh') = 'fresh'
              AND COALESCE(feedback_type, '') != 'dislike'
              AND COALESCE(style_key, '') = ''
              AND COALESCE(topic_group, '') = ''
              AND COALESCE(relevance_score, 0) = 0
              {guard_sql}
              AND NOT EXISTS (
                SELECT 1
                FROM recommendations AS r
                WHERE r.bvid = content_cache.bvid
              )
            ORDER BY
                last_scored_at DESC,
                bvid ASC
            LIMIT ?
            """,
            (*guard_params, limit),
        )
        rows = [dict(row) for row in cursor.fetchall()]
        rows = self._exclude_viewed_rows(
            rows,
            self.get_recent_viewed_content_keys(),
            limit=len(rows),
        )
        return rows[:limit]

    def get_pool_candidates_needing_copy(
        self, limit: int = 20, *, xhs_self_nickname: str = ""
    ) -> list[dict[str, Any]]:
        """返回缺少预计算 popup copy 的 fresh pool 候选。

        v0.3.66+：要求 ``style_key`` / ``topic_group`` —— content 必须
        先被分类才能生成 expression。这防止未分类项（如 raw XHS 笔记）
        获得 expression 并在没有正确 relevance 打分的情况下泄漏通过
        serve 门。
        """
        min_score = self._pool_admission_min_score()
        guard_sql = _xhs_self_author_guard_sql()
        guard_params = _xhs_self_author_guard_params(xhs_self_nickname)
        cursor = self.conn.execute(
            f"""
            SELECT *
            FROM content_cache
            WHERE COALESCE(pool_status, 'fresh') = 'fresh'
              AND COALESCE(feedback_type, '') != 'dislike'
              AND COALESCE(relevance_score, 0.0) >= ?
              AND COALESCE(style_key, '') != ''
              AND COALESCE(topic_group, '') != ''
              AND (
                COALESCE(pool_expression, '') = ''
                OR COALESCE(pool_topic_label, '') = ''
              )
              {guard_sql}
              AND NOT EXISTS (
                SELECT 1
                FROM recommendations AS r
                WHERE r.bvid = content_cache.bvid
              )
            ORDER BY
                CASE candidate_tier WHEN 'primary' THEN 0 ELSE 1 END ASC,
                relevance_score DESC,
                last_scored_at DESC,
                view_count DESC,
                bvid ASC
            LIMIT ?
            """,
            (min_score, *guard_params, limit),
        )
        rows = [dict(row) for row in cursor.fetchall()]
        rows = self._exclude_viewed_rows(
            rows,
            self.get_recent_viewed_content_keys(),
            limit=len(rows),
        )
        return rows[:limit]

    def update_pool_copy(
        self,
        bvid: str,
        *,
        expression: str,
        topic_label: str,
    ) -> None:
        """持久化单个 pooled 候选的预计算 popup copy。"""
        self._execute_write(
            """
            UPDATE content_cache
            SET pool_expression = ?,
                pool_topic_label = ?
            WHERE bvid = ?
            """,
            (expression, topic_label, bvid),
        )

    def get_latest_event_id(self) -> int:
        """返回最新 event 的主键。"""
        cursor = self.conn.execute("SELECT COALESCE(MAX(id), 0) AS latest_id FROM events")
        row = cursor.fetchone()
        return int(row["latest_id"]) if row is not None else 0

    def query_events_since(
        self,
        *,
        after_event_id: int,
        event_types: list[str],
    ) -> list[dict[str, Any]]:
        """查询比给定 id 新的、选定 event 类型的事件。"""
        if not event_types:
            return []
        placeholders = ", ".join("?" for _ in event_types)
        cursor = self.conn.execute(
            f"""
            SELECT *
            FROM events
            WHERE id > ? AND event_type IN ({placeholders})
            ORDER BY id ASC
            """,
            [after_event_id, *event_types],
        )
        return [dict(row) for row in cursor.fetchall()]

    def insert_recommendation(
        self,
        bvid: str,
        *,
        confidence: float,
        expression: str = "",
        topic: str = "",
        presented: int = 0,
    ) -> int:
        """插入一条 recommendation 历史记录。"""
        cursor = self._execute_write(
            """
            INSERT INTO recommendations (bvid, expression, topic, confidence, presented)
            VALUES (?, ?, ?, ?, ?)
            """,
            (bvid, expression, topic, confidence, presented),
        )
        return cursor.lastrowid or 0

    def batch_insert_recommendations(
        self,
        items: list[dict[str, Any]],
    ) -> list[int]:
        """在单个事务中插入 N 条 recommendation 行；按顺序返回 row ID。

        用一次 fsync 替代 N 次（discovery 写入竞争下原本每次 200-300ms
        → popup 10 项批次 ~3s）。按项返回 ``lastrowid``，从该连接上一次
        id 起的 auto-increment 增量计算。
        """
        return self.batch_insert_recommendations_and_mark_shown(items, [])

    def batch_insert_recommendations_and_mark_shown(
        self,
        items: list[dict[str, Any]],
        shown_bvids: list[str],
    ) -> list[int]:
        """在 **单个事务** 中插入 recommendation 并把 pool 项标记为 shown。

        v0.3.45+：serve() 以前会发两次独立写入（插入 recs，再 UPDATE
        content_cache.pool_status='shown'）并付两次 fsync。在 refresh-tick
        写入竞争下这会把尾部延迟拉到 ~1s。一对 BEGIN IMMEDIATE / COMMIT
        用单次 fsync 提供相同的原子语义，且少见的 lost-write 情况（插入
        成功、标记失败）现在在结构上不可能 —— 两者一起成功或一起回滚。

        按 ``items`` 顺序返回每项的 ``lastrowid``。
        """
        if not items and not shown_bvids:
            return []
        clean_bvids = [b for b in shown_bvids if b]
        attempts = _LOCK_RETRY_ATTEMPTS
        while True:
            try:
                cursor = self.conn.cursor()
                cursor.execute("BEGIN IMMEDIATE")
                try:
                    ids: list[int] = []
                    for item in items:
                        cursor.execute(
                            """
                            INSERT INTO recommendations
                                (bvid, expression, topic, confidence, presented)
                            VALUES (?, ?, ?, ?, ?)
                            """,
                            (
                                str(item.get("bvid", "")),
                                str(item.get("expression", "")),
                                str(item.get("topic", "")),
                                float(item.get("confidence", 0.0) or 0.0),
                                int(item.get("presented", 0) or 0),
                            ),
                        )
                        ids.append(cursor.lastrowid or 0)
                    if clean_bvids:
                        placeholders = ", ".join("?" for _ in clean_bvids)
                        cursor.execute(
                            f"""
                            UPDATE content_cache
                            SET pool_status = 'shown',
                                recommended_at = CURRENT_TIMESTAMP
                            WHERE bvid IN ({placeholders})
                            """,
                            clean_bvids,
                        )
                    self.conn.commit()
                    return ids
                except Exception:
                    self.conn.rollback()
                    raise
            except sqlite3.OperationalError as exc:
                if "database is locked" not in str(exc).lower() or attempts <= 1:
                    raise
                attempts -= 1
                time.sleep(_LOCK_RETRY_SLEEP_SECONDS)

    def get_recent_recommendation_signals(self, *, limit: int = 30) -> list[dict[str, Any]]:
        """返回带 topic/source 的近期 recommendation，供打分上下文使用。

        同时包含 ``topic_key``（细，如 ``"洛克王国"``）与 ``topic_group``
        （粗，如 ``"游戏"``），让 curator 能在两条轴上做疲劳。没有
        ``topic_group`` 时，``动漫杂谈`` / ``动漫补番`` / ``动漫解说``
        这样的同源细粒度 key 是相互独立的，按 key 的疲劳永远不会跨它们
        触发。
        """
        cursor = self.conn.execute(
            """
            SELECT r.bvid, c.topic_key, c.topic_group, c.source, r.created_at
            FROM recommendations AS r
            JOIN content_cache AS c ON c.bvid = COALESCE(
                (SELECT bvid FROM content_cache WHERE bvid = r.bvid),
                (SELECT bvid FROM content_cache WHERE content_id = r.bvid LIMIT 1)
            )
            ORDER BY r.created_at DESC, r.id DESC
            LIMIT ?
            """,
            (limit,),
        )
        return [dict(row) for row in cursor.fetchall()]

    def get_recent_recommendation_signals_since(
        self,
        *,
        since: datetime,
    ) -> list[dict[str, Any]]:
        """返回自给定时间戳以来展示过的 recommendation topic/source 行。"""
        self._ensure_fresh_read()
        since_text = since.isoformat(sep=" ")
        cursor = self.conn.execute(
            """
            SELECT r.bvid,
                   c.topic_key,
                   c.topic_group,
                   c.source,
                   r.created_at,
                   r.presented_at
            FROM recommendations AS r
            JOIN content_cache AS c ON c.bvid = COALESCE(
                (SELECT bvid FROM content_cache WHERE bvid = r.bvid),
                (SELECT bvid FROM content_cache WHERE content_id = r.bvid LIMIT 1)
            )
            WHERE COALESCE(r.presented_at, r.created_at) >= ?
            ORDER BY COALESCE(r.presented_at, r.created_at) DESC, r.id DESC
            """,
            (since_text,),
        )
        return [dict(row) for row in cursor.fetchall()]

    def get_feedback_signals(self, *, limit: int = 50) -> list[dict[str, Any]]:
        """返回带 UP/topic/franchise 信息的近期 feedback，用于分数调整。

        ``franchise_key`` 是 LLM 打标的 IP / series 列（v0.3.18 加入）。
        dislike 一个原神视频以前只会屏蔽其精确 bvid；现在 curator 会跨
        近期 dislike 收集 ``franchise_key``，并下调任何自身
        ``franchise_key`` 匹配的候选 —— 不依赖标题字符串启发式。
        """
        cursor = self.conn.execute(
            """
            SELECT r.feedback_type, c.up_mid, c.up_name, c.topic_key,
                   c.source, c.title, c.franchise_key
            FROM recommendations AS r
            JOIN content_cache AS c ON c.bvid = COALESCE(
                (SELECT bvid FROM content_cache WHERE bvid = r.bvid),
                (SELECT bvid FROM content_cache WHERE content_id = r.bvid LIMIT 1)
            )
            WHERE r.feedback_type IS NOT NULL
            ORDER BY r.feedback_at DESC
            LIMIT ?
            """,
            (limit,),
        )
        return [dict(row) for row in cursor.fetchall()]

    def get_recommendations(
        self,
        limit: int = 100,
        *,
        exclude_processed: bool = False,
    ) -> list[dict[str, Any]]:
        """按最新优先返回 recommendation 历史。

        缓存 ``content_url`` 中缺少 ``xsec_token`` 的 xhs 行被过滤掉
        —— 点击它们会撞上 xhs 的 300031 登录墙。

        当 *exclude_processed* 为 True 时，已被处理过（liked / disliked /
        dismissed / commented）的行被省略，使 API 只返回可操作项。

        ``franchise_key`` (v0.3.18) 被暴露，使 /api/recommendations 在
        返回 client 之前能应用最终的 per-IP 上限 —— 否则一个 popup 视图
        中可能落下五个原神 / 提瓦特项。
        """
        self._ensure_fresh_read()
        min_score = self._pool_admission_min_score()
        processed_clause = (
            "AND (r.feedback_type IS NULL OR r.feedback_type = '')" if exclude_processed else ""
        )
        cursor = self.conn.execute(
            f"""
            SELECT
                r.*,
                COALESCE(c.title, '') AS title,
                COALESCE(c.up_name, '') AS up_name,
                COALESCE(c.cover_url, '') AS cover_url,
                COALESCE(c.content_id, r.bvid) AS content_id,
                COALESCE(c.content_url, '') AS content_url,
                COALESCE(c.source_platform, '') AS source_platform,
                COALESCE(c.content_type, 'video') AS content_type,
                COALESCE(c.body_text, '') AS body_text,
                COALESCE(c.franchise_key, '') AS franchise_key
            FROM recommendations AS r
            LEFT JOIN content_cache AS c ON c.bvid = COALESCE(
                (SELECT bvid FROM content_cache WHERE bvid = r.bvid),
                (SELECT bvid FROM content_cache WHERE content_id = r.bvid LIMIT 1)
            )
            WHERE (
                COALESCE(c.source_platform, '') != 'xiaohongshu'
                OR COALESCE(c.content_url, '') LIKE '%xsec_token=%'
            )
            AND COALESCE(r.confidence, 0.0) >= ?
            {processed_clause}
            ORDER BY created_at DESC, id DESC
            LIMIT ?
            """,
            (min_score, limit),
        )
        return [dict(row) for row in cursor.fetchall()]

    def count_recommendations(self) -> int:
        """返回已存储的 recommendation 总数。"""
        self._ensure_fresh_read()
        cursor = self.conn.execute("SELECT COUNT(*) AS count FROM recommendations")
        row = cursor.fetchone()
        return int(row["count"]) if row is not None else 0

    def count_unread_recommendations(self) -> int:
        """返回未展示的 recommendation 数量。"""
        self._ensure_fresh_read()
        cursor = self.conn.execute(
            "SELECT COUNT(*) AS count FROM recommendations WHERE presented = 0"
        )
        row = cursor.fetchone()
        return int(row["count"]) if row is not None else 0

    def get_notification_candidate(
        self,
        *,
        min_confidence: float = 0.82,
    ) -> dict[str, Any] | None:
        """返回一条值得通知用户的 recommendation。"""
        cursor = self.conn.execute(
            """
            SELECT
                r.id,
                r.bvid,
                r.expression,
                r.confidence,
                c.title,
                c.notification_sent,
                c.notified_at
            FROM recommendations AS r
            JOIN content_cache AS c ON c.bvid = COALESCE(
                (SELECT bvid FROM content_cache WHERE bvid = r.bvid),
                (SELECT bvid FROM content_cache WHERE content_id = r.bvid LIMIT 1)
            )
            WHERE r.presented = 0
              AND c.notification_sent = 0
              AND r.confidence >= ?
            ORDER BY r.confidence DESC, r.created_at DESC, r.id DESC
            LIMIT 1
            """,
            (min_confidence,),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return dict(row)

    def mark_notification_sent(self, bvid: str) -> None:
        """把一个 cached 项标记为已通知。"""
        self._execute_write(
            """
            UPDATE content_cache
            SET notification_sent = 1,
                notified_at = CURRENT_TIMESTAMP
            WHERE bvid = ?
            """,
            (bvid,),
        )

    def update_recommendation_content(
        self,
        recommendation_id: int,
        *,
        expression: str,
        topic: str,
    ) -> None:
        """更新 recommendation 的生成 expression 字段。"""
        self._execute_write(
            """
            UPDATE recommendations
            SET expression = ?, topic = ?
            WHERE id = ?
            """,
            (expression, topic, recommendation_id),
        )

    def get_recommendation_by_id(self, recommendation_id: int) -> dict[str, Any] | None:
        """按主键返回单条 recommendation 行。"""
        self._ensure_fresh_read()
        cursor = self.conn.execute(
            """
            SELECT
                r.*,
                r.topic AS topic_label,
                c.title AS title,
                c.up_name AS up_name,
                COALESCE(c.content_id, r.bvid) AS content_id,
                COALESCE(c.content_url, '') AS content_url,
                COALESCE(c.source_platform, '') AS source_platform
            FROM recommendations AS r
            LEFT JOIN content_cache AS c ON c.bvid = COALESCE(
                (SELECT bvid FROM content_cache WHERE bvid = r.bvid),
                (SELECT bvid FROM content_cache WHERE content_id = r.bvid LIMIT 1)
            )
            WHERE r.id = ?
            """,
            (recommendation_id,),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return dict(row)

    def update_recommendation_feedback(
        self,
        recommendation_id: int,
        *,
        feedback_type: str,
        feedback_note: str = "",
    ) -> None:
        """更新 recommendation 的当前 feedback 状态。"""
        self._execute_write(
            """
            UPDATE recommendations
            SET feedback = ?,
                feedback_type = ?,
                feedback_note = ?,
                feedback_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (feedback_type, feedback_type, feedback_note, recommendation_id),
        )
        self._execute_write(
            """
            UPDATE content_cache
            SET pool_status = 'feedbacked',
                feedback_type = ?,
                feedback_at = CURRENT_TIMESTAMP
            WHERE bvid = (
                SELECT bvid
                FROM recommendations
                WHERE id = ?
            )
            """,
            (feedback_type, recommendation_id),
        )

    def mark_recommendations_presented(self, recommendation_ids: list[int]) -> None:
        """把 recommendation 标记为已展示，并设置其 presented 时间戳。"""
        if not recommendation_ids:
            return
        placeholders = ", ".join("?" for _ in recommendation_ids)
        self._execute_write(
            f"""
            UPDATE recommendations
            SET presented = 1,
                presented_at = CURRENT_TIMESTAMP
            WHERE id IN ({placeholders})
            """,
            recommendation_ids,
        )

    def close(self) -> None:
        """关闭数据库连接。"""
        if self._conn:
            self._conn.close()
            self._conn = None

    def _ensure_llm_usage_cache_columns(self) -> None:
        """为已存在的 llm_usage 表回填 v0.3.28+ prompt-cache 列。"""
        existing_columns = {
            str(row["name"]) for row in self.conn.execute("PRAGMA table_info(llm_usage)").fetchall()
        }
        required_columns = {
            "cached_input_tokens": "INTEGER NOT NULL DEFAULT 0",
        }
        for column_name, column_type in required_columns.items():
            if column_name in existing_columns:
                continue
            self.conn.execute(f"ALTER TABLE llm_usage ADD COLUMN {column_name} {column_type}")

    def _ensure_event_satisfaction_columns(self) -> None:
        """为迁移前的数据库回填 v0.3.x event-satisfaction 列。

        已存在的行在两列上保持 ``NULL``；消费方将 NULL 视作 ``unknown``，
        因此升级是非阻塞的。
        """
        existing_columns = {
            str(row["name"]) for row in self.conn.execute("PRAGMA table_info(events)").fetchall()
        }
        required_columns = {
            "inferred_satisfaction": "TEXT",
            "satisfaction_reason": "TEXT",
        }
        for column_name, column_type in required_columns.items():
            if column_name in existing_columns:
                continue
            self.conn.execute(f"ALTER TABLE events ADD COLUMN {column_name} {column_type}")

    def _ensure_recommendation_feedback_columns(self) -> None:
        """为已存在的数据库回填 recommendation feedback 列。"""
        existing_columns = {
            str(row["name"])
            for row in self.conn.execute("PRAGMA table_info(recommendations)").fetchall()
        }
        required_columns = {
            "feedback_type": "TEXT",
            "feedback_note": "TEXT",
            "feedback_at": "TIMESTAMP",
        }
        for column_name, column_type in required_columns.items():
            if column_name in existing_columns:
                continue
            self.conn.execute(f"ALTER TABLE recommendations ADD COLUMN {column_name} {column_type}")

    def _ensure_content_cache_runtime_columns(self) -> None:
        """为持续刷新回填 content-cache 运行时列。"""
        existing_columns = {
            str(row["name"])
            for row in self.conn.execute("PRAGMA table_info(content_cache)").fetchall()
        }
        required_columns = {
            "last_scored_at": "TIMESTAMP",
            "notification_sent": "INTEGER DEFAULT 0",
            "notified_at": "TIMESTAMP",
            "pool_status": "TEXT DEFAULT 'fresh'",
            "recommended_at": "TIMESTAMP",
            "feedback_type": "TEXT",
            "feedback_at": "TIMESTAMP",
        }
        for column_name, column_type in required_columns.items():
            if column_name in existing_columns:
                continue
            self.conn.execute(f"ALTER TABLE content_cache ADD COLUMN {column_name} {column_type}")

    def _ensure_content_cache_relevance_columns(self) -> None:
        """为已存在的 content-cache 行回填 relevance 字段。"""
        existing_columns = {
            str(row["name"])
            for row in self.conn.execute("PRAGMA table_info(content_cache)").fetchall()
        }
        required_columns = {
            "relevance_score": "REAL DEFAULT 0.0",
            "relevance_reason": "TEXT DEFAULT ''",
            "candidate_tier": "TEXT DEFAULT 'primary'",
        }
        for column_name, column_type in required_columns.items():
            if column_name in existing_columns:
                continue
            self.conn.execute(f"ALTER TABLE content_cache ADD COLUMN {column_name} {column_type}")

    def _ensure_content_cache_topic_columns(self) -> None:
        """为已存在的 content-cache 行回填 topic 分桶字段。"""
        existing_columns = {
            str(row["name"])
            for row in self.conn.execute("PRAGMA table_info(content_cache)").fetchall()
        }
        if "topic_key" not in existing_columns:
            self.conn.execute("ALTER TABLE content_cache ADD COLUMN topic_key TEXT DEFAULT ''")
        if "topic_group" not in existing_columns:
            self.conn.execute("ALTER TABLE content_cache ADD COLUMN topic_group TEXT DEFAULT ''")
        if "style_key" not in existing_columns:
            self.conn.execute("ALTER TABLE content_cache ADD COLUMN style_key TEXT DEFAULT ''")
        if "franchise_key" not in existing_columns:
            # v0.3.18：LLM 打标的 IP / franchise / series。一般兴趣内容
            # 为空字符串；非空行让 curator 在同一 IP 内传播 dislike，并让
            # /api/recommendations 限制单个响应窗口中同 franchise 项的
            # 数量 —— 不依赖任何标题字符串启发式或硬编码别名表。
            self.conn.execute("ALTER TABLE content_cache ADD COLUMN franchise_key TEXT DEFAULT ''")

    def _ensure_content_cache_pool_copy_columns(self) -> None:
        """为已存在的数据库回填预计算 pool-copy 字段。"""
        existing_columns = {
            str(row["name"])
            for row in self.conn.execute("PRAGMA table_info(content_cache)").fetchall()
        }
        required_columns = {
            "pool_expression": "TEXT DEFAULT ''",
            "pool_topic_label": "TEXT DEFAULT ''",
        }
        for column_name, column_type in required_columns.items():
            if column_name in existing_columns:
                continue
            self.conn.execute(f"ALTER TABLE content_cache ADD COLUMN {column_name} {column_type}")

    def _ensure_content_cache_delight_columns(self) -> None:
        """为已存在的数据库回填 proactive delight scoring 字段。"""
        existing_columns = {
            str(row["name"])
            for row in self.conn.execute("PRAGMA table_info(content_cache)").fetchall()
        }
        required_columns = {
            "delight_score": "REAL DEFAULT 0.0",
            "delight_reason": "TEXT DEFAULT ''",
            "delight_hook": "TEXT DEFAULT ''",
            "delight_notified": "INTEGER DEFAULT 0",
            "delight_notified_at": "TIMESTAMP",
        }
        for column_name, column_type in required_columns.items():
            if column_name in existing_columns:
                continue
            self.conn.execute(f"ALTER TABLE content_cache ADD COLUMN {column_name} {column_type}")

    def _ensure_content_cache_multisource_columns(self) -> None:
        """为已存在的数据库新增多源内容身份字段。"""
        existing_columns = {
            str(row["name"])
            for row in self.conn.execute("PRAGMA table_info(content_cache)").fetchall()
        }
        required_columns = {
            "content_id": "TEXT DEFAULT ''",
            "content_url": "TEXT DEFAULT ''",
            "source_platform": "TEXT DEFAULT 'bilibili'",
            "author_name": "TEXT DEFAULT ''",
            "body_text": "TEXT DEFAULT ''",
            "content_type": "TEXT DEFAULT 'video'",
            "favorite_count": "INTEGER DEFAULT 0",
            "collect_count": "INTEGER DEFAULT 0",
            "comment_count": "INTEGER DEFAULT 0",
            "share_count": "INTEGER DEFAULT 0",
            "danmaku_count": "INTEGER DEFAULT 0",
            "reply_count": "INTEGER DEFAULT 0",
            "retweet_count": "INTEGER DEFAULT 0",
            "bookmark_count": "INTEGER DEFAULT 0",
            # P1.8 yield provenance：产出该行的 discovery_keywords.id
            # （legacy / 非搜索 / flag 关闭时为 NULL）。可空，叠加式。
            "source_keyword_id": "INTEGER",
        }
        added = False
        for column_name, column_type in required_columns.items():
            if column_name in existing_columns:
                continue
            self.conn.execute(f"ALTER TABLE content_cache ADD COLUMN {column_name} {column_type}")
            added = True
        if added:
            self.conn.execute("UPDATE content_cache SET content_id = bvid WHERE content_id = ''")

    def _ensure_discovery_candidate_columns(self) -> None:
        """为已存在的数据库回填 discovery-candidate 生命周期列。"""

        existing_columns = {
            str(row["name"])
            for row in self.conn.execute("PRAGMA table_info(discovery_candidates)").fetchall()
        }
        required_columns = {
            "score_threshold": "REAL NOT NULL DEFAULT 0.0",
            "eval_attempts": "INTEGER NOT NULL DEFAULT 0",
            "batch_eval_attempts": "INTEGER NOT NULL DEFAULT 0",
            "body_text": "TEXT NOT NULL DEFAULT ''",
            "favorite_count": "INTEGER NOT NULL DEFAULT 0",
            "collect_count": "INTEGER NOT NULL DEFAULT 0",
            "comment_count": "INTEGER NOT NULL DEFAULT 0",
            "share_count": "INTEGER NOT NULL DEFAULT 0",
            "danmaku_count": "INTEGER NOT NULL DEFAULT 0",
            "reply_count": "INTEGER NOT NULL DEFAULT 0",
            "retweet_count": "INTEGER NOT NULL DEFAULT 0",
            "bookmark_count": "INTEGER NOT NULL DEFAULT 0",
            # P1.8 yield provenance：可空，叠加式（已存在行保持 NULL）。
            "source_keyword_id": "INTEGER",
        }
        for column_name, column_type in required_columns.items():
            if column_name in existing_columns:
                continue
            self.conn.execute(
                f"ALTER TABLE discovery_candidates ADD COLUMN {column_name} {column_type}"
            )

    def _normalize_legacy_style_keys(self) -> None:
        """将已知的 legacy content-form style 键改写为 viewing-mode 键。"""

        targets = (
            ("content_cache", "style_key"),
            ("discovery_candidates", "style_key"),
        )
        for table_name, column_name in targets:
            existing_columns = {
                str(row["name"])
                for row in self.conn.execute(f"PRAGMA table_info({table_name})").fetchall()
            }
            if column_name not in existing_columns:
                continue
            for legacy_key, style_key in _LEGACY_STYLE_KEY_MAP.items():
                self.conn.execute(
                    f"UPDATE {table_name} SET {column_name} = ? WHERE {column_name} = ?",
                    (style_key, legacy_key),
                )

    def _ensure_recommendation_read_indexes(self) -> None:
        """创建被推荐和 activity-feed 读路径使用的索引。"""
        self.conn.executescript("""
            CREATE INDEX IF NOT EXISTS idx_recommendations_created_id
                ON recommendations (created_at DESC, id DESC);
            CREATE INDEX IF NOT EXISTS idx_content_cache_content_id
                ON content_cache (content_id);
        """)

    def _ensure_source_recipes_table(self) -> None:
        """若 source_recipes 表不存在则创建。"""
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS source_recipes (
                id            TEXT PRIMARY KEY,
                source_type   TEXT NOT NULL,
                name          TEXT NOT NULL,
                strategy      TEXT NOT NULL,
                config        TEXT DEFAULT '{}',
                target_share  INTEGER DEFAULT 4,
                enabled       INTEGER DEFAULT 1,
                created_by    TEXT DEFAULT 'system',
                created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_fetched_at TIMESTAMP
            );
        """)

    def _ensure_xhs_observed_urls_table(self) -> None:
        """若 xhs_observed_urls 表不存在则创建。"""
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS xhs_observed_urls (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                url         TEXT NOT NULL,
                page_type   TEXT NOT NULL DEFAULT 'other',
                observed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                enriched    INTEGER DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS idx_xhs_observed_urls_url
                ON xhs_observed_urls (url);
        """)

    def _ensure_chat_turns_table(self) -> None:
        """为已存在的数据库创建持久化的 popup chat-turn 存储。"""
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS chat_turns (
                turn_id       TEXT PRIMARY KEY,
                session       TEXT NOT NULL DEFAULT 'popup',
                scope         TEXT NOT NULL DEFAULT 'chat',
                subject_id    TEXT NOT NULL DEFAULT '',
                subject_title TEXT NOT NULL DEFAULT '',
                message       TEXT NOT NULL DEFAULT '',
                status        TEXT NOT NULL DEFAULT 'pending',
                reply         TEXT NOT NULL DEFAULT '',
                error         TEXT NOT NULL DEFAULT '',
                created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_chat_turns_session_created
                ON chat_turns(session, created_at, turn_id);
            CREATE INDEX IF NOT EXISTS idx_chat_turns_scope_subject
                ON chat_turns(scope, subject_id, created_at);
        """)

    def _ensure_watch_later_table(self) -> None:
        """为已存在的数据库创建 watch_later 收藏表。"""
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS watch_later (
                bvid     TEXT PRIMARY KEY,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                note     TEXT DEFAULT ''
            );
            CREATE INDEX IF NOT EXISTS idx_watch_later_added
                ON watch_later(added_at DESC);
        """)

    def _ensure_discovery_keywords_table(self) -> None:
        """创建统一的 search-keyword 存储 + planner single-flight 锁。

        ``discovery_keywords`` 是统一 keyword planner（Discover backpressure
        重构，P1）的生成侧缓存/历史/yield 账本。它承载与
        ``xhs_tasks`` / ``dy_tasks`` 执行队列相同的原子 claim + lease-reclaim
        语义（``BEGIN IMMEDIATE`` claim、``pending → claimed`` 转换、
        ``claimed_at`` lease），但跟踪的是*要搜索哪些词*，而不是*要打开
        哪些 tab*。

        唯一性约束是**部分索引** —— 仅覆盖 in-flight 状态
        （``pending`` / ``claimed`` / ``executing``），因此已经 ``used``
        （或 ``expired``）的词不会阻止 planner 在后续周期中重新生成同一个
        词（一旦它已滚出 dedup 窗口）。

        ``discovery_planner_lock`` 是一个小的 CAS 行，用于跨 loop / 重启
        对 planner 做 single-flight。它只在*短*事务中持有
        （acquire → commit → 不持锁运行 LLM → 写结果时再 reacquire），
        绝不跨 LLM 调用持有，因此它不会阻塞其他 SQLite 写入者。
        """
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS discovery_keywords (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                platform          TEXT NOT NULL,
                keyword           TEXT NOT NULL,
                profile_kw_digest TEXT NOT NULL DEFAULT '',
                status            TEXT NOT NULL DEFAULT 'pending',
                created_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                claimed_at        TIMESTAMP,
                executing_at      TIMESTAMP,
                used_at           TIMESTAMP,
                attempts          INTEGER NOT NULL DEFAULT 0,
                yield_count       INTEGER NOT NULL DEFAULT 0
            );
            -- Partial uniqueness: only the in-flight triplet is unique, so
            -- used/expired history never blocks re-generating the same word.
            CREATE UNIQUE INDEX IF NOT EXISTS uq_discovery_keywords_inflight
                ON discovery_keywords (platform, keyword, profile_kw_digest)
                WHERE status IN ('pending', 'claimed', 'executing');
            CREATE INDEX IF NOT EXISTS idx_discovery_keywords_status_digest
                ON discovery_keywords (platform, status, profile_kw_digest);
            CREATE INDEX IF NOT EXISTS idx_discovery_keywords_status_used
                ON discovery_keywords (platform, status, used_at);

            CREATE TABLE IF NOT EXISTS discovery_planner_lock (
                lock_name    TEXT PRIMARY KEY,
                owner        TEXT NOT NULL DEFAULT '',
                locked_until TIMESTAMP NOT NULL,
                updated_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            -- P1.8 yield ledger. One row per (keyword, admitted content) the
            -- keyword produced. The composite primary key makes the yield
            -- backfill idempotent: a retried / out-of-order / duplicate admit
            -- of the SAME (keyword, content) is an INSERT-OR-IGNORE no-op, so
            -- ``discovery_keywords.yield_count`` is only ever bumped once per
            -- distinct produced content. Decoupled from ``used`` (P1.7).
            CREATE TABLE IF NOT EXISTS discovery_keyword_yield (
                keyword_id  INTEGER NOT NULL,
                content_id  TEXT NOT NULL,
                created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (keyword_id, content_id)
            );
        """)

    # ── Discovery keyword 存储（统一 search-keyword planner）──
    #
    # 状态机：
    #   pending → claimed → (inline：used / failed)
    #                     → (async：executing → used / failed)
    #   任意 in-flight 状态 → pending（lease 回收 / 预算回滚）
    #   pending（digest 过期）→ expired
    # ``used`` 只会落在终态（绝不在 enqueue 时写入）；这个 word 在其
    # fetch 真正完成之前一直是"in flight"。yield_count 在 P1.8 阶段于
    # admit time 回填；P1.1 只存储这一列。

    def insert_pending_keywords(
        self,
        platform: str,
        keywords: Sequence[str],
        profile_kw_digest: str,
    ) -> int:
        """批量插入 ``pending`` 关键词，忽略 in-flight 重复。

        部分唯一索引 ``uq_discovery_keywords_inflight`` 意味着对同一
        ``(platform, profile_kw_digest)`` 已经 ``pending`` / ``claimed``
        / ``executing`` 的词会被静默跳过（``OR IGNORE``）；仅以
        ``used`` / ``expired`` 历史形式存在的词**不**冲突，因此同一个词
        可以被重新生成。``keywords`` 内部的空白/重复词会先被去重。

        返回实际插入的行数。
        """
        platform_key = platform.strip()
        digest = profile_kw_digest.strip()
        seen: set[str] = set()
        rows: list[tuple[str, str, str]] = []
        for raw in keywords:
            word = str(raw).strip()
            if not word or word in seen:
                continue
            seen.add(word)
            rows.append((platform_key, word, digest))
        if not rows:
            return 0
        before = self.conn.total_changes
        self._execute_many_write(
            """
            INSERT OR IGNORE INTO discovery_keywords
                (platform, keyword, profile_kw_digest, status)
            VALUES (?, ?, ?, 'pending')
            """,
            rows,
        )
        return self.conn.total_changes - before

    def count_pending_keywords(self, platform: str, profile_kw_digest: str) -> int:
        """返回此 digest 下存在多少个 ``pending`` 关键词。"""
        self._ensure_fresh_read()
        row = self.conn.execute(
            """
            SELECT COUNT(*) AS n
            FROM discovery_keywords
            WHERE platform = ? AND status = 'pending' AND profile_kw_digest = ?
            """,
            (platform.strip(), profile_kw_digest.strip()),
        ).fetchone()
        return int(row["n"]) if row is not None else 0

    def claim_keywords(self, platform: str, n: int) -> list[dict[str, Any]]:
        """原子地为某个平台 claim 最多 ``n`` 个 ``pending`` 关键词。

        使用短生命周期的连接 + ``BEGIN IMMEDIATE``，使两个并发调用方串行化
        且永远不会收到重叠的行：第二个写入者会阻塞直到第一个提交，之后刚被
        claim 的行不再是 ``pending``，无法被重新选中。镜像
        ``xhs_tasks`` / ``dy_tasks`` 的 ``next_pending`` claim，并泛化到
        批量场景。返回被 claim 的行（``status='claimed'``），最旧的在前。
        """
        claim_n = max(0, int(n))
        if claim_n <= 0:
            return []
        self._ensure_fresh_read()
        conn = self.open_connection()
        try:
            conn.execute("BEGIN IMMEDIATE")
            pending = conn.execute(
                """
                SELECT id
                FROM discovery_keywords
                WHERE platform = ? AND status = 'pending'
                ORDER BY created_at ASC, id ASC
                LIMIT ?
                """,
                (platform.strip(), claim_n),
            ).fetchall()
            if not pending:
                conn.commit()
                return []
            ids = [int(row["id"]) for row in pending]
            placeholders = ", ".join("?" for _ in ids)
            conn.execute(
                f"""
                UPDATE discovery_keywords
                SET status = 'claimed', claimed_at = CURRENT_TIMESTAMP
                WHERE id IN ({placeholders}) AND status = 'pending'
                """,
                ids,
            )
            claimed = conn.execute(
                f"""
                SELECT *
                FROM discovery_keywords
                WHERE id IN ({placeholders}) AND status = 'claimed'
                ORDER BY claimed_at ASC, id ASC
                """,
                ids,
            ).fetchall()
            conn.commit()
        except Exception:
            if conn.in_transaction:
                conn.rollback()
            raise
        finally:
            conn.close()
        return [dict(row) for row in claimed]

    def mark_keyword_executing(self, keyword_id: int) -> None:
        """将一个 ``claimed`` 关键词移动到 ``executing``（async fetch 已入队）。"""
        self._execute_write(
            """
            UPDATE discovery_keywords
            SET status = 'executing', executing_at = CURRENT_TIMESTAMP
            WHERE id = ? AND status IN ('claimed', 'executing')
            """,
            (int(keyword_id),),
        )

    def mark_keyword_used(self, keyword_id: int) -> None:
        """将一个关键词标记为 ``used``（终态 —— 其 fetch 已完成）。"""
        self._execute_write(
            """
            UPDATE discovery_keywords
            SET status = 'used', used_at = CURRENT_TIMESTAMP
            WHERE id = ? AND status IN ('claimed', 'executing')
            """,
            (int(keyword_id),),
        )

    def mark_keyword_failed(self, keyword_id: int) -> int:
        """将一个关键词标记为 ``failed`` 并递增 ``attempts``。

        返回新的 ``attempts`` 计数，调用方据此决定是重试（重新 pending）
        还是把该词视作终态失败。
        """
        self._execute_write(
            """
            UPDATE discovery_keywords
            SET status = 'failed',
                attempts = attempts + 1
            WHERE id = ? AND status IN ('claimed', 'executing')
            """,
            (int(keyword_id),),
        )
        row = self.conn.execute(
            "SELECT attempts FROM discovery_keywords WHERE id = ?",
            (int(keyword_id),),
        ).fetchone()
        return int(row["attempts"]) if row is not None else 0

    def rollback_keyword_to_pending(self, keyword_id: int) -> None:
        """将一个 ``claimed`` 关键词退回为 ``pending``（预算拒绝回滚）。

        当 claim 成功但下游 enqueue 被拒绝（例如日预算耗尽）时使用，此时
        没有任何 fetch 真正运行 —— 该词必须回到池中而不是被烧掉。只有
        ``claimed`` 会回滚；``executing`` 行已经有一个 in-flight 任务，不
        会被处理。
        """
        self._execute_write(
            """
            UPDATE discovery_keywords
            SET status = 'pending', claimed_at = NULL
            WHERE id = ? AND status = 'claimed'
            """,
            (int(keyword_id),),
        )

    def reclaim_leased_keywords(
        self,
        claim_lease_minutes: float,
        executing_timeout_minutes: float,
    ) -> int:
        """回收泄漏的 in-flight 关键词回到 ``pending``。

        ``claimed_at`` 早于 ``claim_lease_minutes`` 的 ``claimed`` 行
        （loop 在 claim 与 fetch 之间崩溃）以及 ``executing_at`` 早于
        ``executing_timeout_minutes`` 的 ``executing`` 行（async 任务从未回报）
        会被退回为 ``pending``，避免该词丢失。返回被回收的行数。
        """
        from datetime import UTC, datetime, timedelta

        now = datetime.now(UTC)
        claimed_cutoff = (now - timedelta(minutes=max(0.0, claim_lease_minutes))).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        executing_cutoff = (now - timedelta(minutes=max(0.0, executing_timeout_minutes))).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        cursor = self._execute_write(
            """
            UPDATE discovery_keywords
            SET status = 'pending', claimed_at = NULL, executing_at = NULL
            WHERE (status = 'claimed' AND claimed_at IS NOT NULL AND claimed_at <= ?)
               OR (status = 'executing' AND executing_at IS NOT NULL AND executing_at <= ?)
            """,
            (claimed_cutoff, executing_cutoff),
        )
        return int(cursor.rowcount or 0)

    def history_keywords(
        self,
        platform: str,
        window_size: int,
        window_hours: float,
    ) -> list[str]:
        """返回最近的 in-flight + used 关键词用于 dedup，最新的在前。

        包含 ``claimed`` / ``executing``（in-flight，这样 planner 不会
        重新生成一个 fetch 即将消费的词）以及滚动窗口内的 ``used``
        （最近搜索过）。上限为 ``window_size``，且限定在最近 ``window_hours``
        之内。
        """
        from datetime import UTC, datetime, timedelta

        cap = max(0, int(window_size))
        if cap <= 0:
            return []
        self._ensure_fresh_read()
        cutoff = (datetime.now(UTC) - timedelta(hours=max(0.0, window_hours))).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        rows = self.conn.execute(
            """
            SELECT keyword
            FROM discovery_keywords
            WHERE platform = ?
              AND status IN ('claimed', 'executing', 'used')
              AND COALESCE(used_at, executing_at, claimed_at, created_at) >= ?
            ORDER BY COALESCE(used_at, executing_at, claimed_at, created_at) DESC, id DESC
            LIMIT ?
            """,
            (platform.strip(), cutoff, cap),
        ).fetchall()
        return [str(row["keyword"]) for row in rows]

    def recycle_oldest_used(
        self,
        platform: str,
        n: int,
        profile_kw_digest: str,
    ) -> int:
        """回收最旧的 ``used`` 关键词到 ``pending``。

        Sparse-profile 安全阀：当生成只能产出已在历史中的词时，planner
        回收最久未使用的词，避免缓存饿死。被回收的行会被重新打上当前
        ``profile_kw_digest`` 并再次变为 ``pending``。会与已存在的 in-flight
        行冲突的行（同一词已为该 digest 处于 pending/claimed/executing）会
        被跳过，以尊重部分唯一索引。返回被回收的行数。
        """
        recycle_n = max(0, int(n))
        if recycle_n <= 0:
            return 0
        digest = profile_kw_digest.strip()
        self._ensure_fresh_read()
        conn = self.open_connection()
        try:
            conn.execute("BEGIN IMMEDIATE")
            candidates = conn.execute(
                """
                SELECT id, keyword
                FROM discovery_keywords
                WHERE platform = ? AND status = 'used'
                ORDER BY used_at ASC, id ASC
                """,
                (platform.strip(),),
            ).fetchall()
            recycled = 0
            for row in candidates:
                if recycled >= recycle_n:
                    break
                clash = conn.execute(
                    """
                    SELECT 1
                    FROM discovery_keywords
                    WHERE platform = ?
                      AND keyword = ?
                      AND profile_kw_digest = ?
                      AND status IN ('pending', 'claimed', 'executing')
                    LIMIT 1
                    """,
                    (platform.strip(), str(row["keyword"]), digest),
                ).fetchone()
                if clash is not None:
                    continue
                conn.execute(
                    """
                    UPDATE discovery_keywords
                    SET status = 'pending',
                        profile_kw_digest = ?,
                        claimed_at = NULL,
                        executing_at = NULL,
                        used_at = NULL
                    WHERE id = ? AND status = 'used'
                    """,
                    (digest, int(row["id"])),
                )
                recycled += 1
            conn.commit()
        except Exception:
            if conn.in_transaction:
                conn.rollback()
            raise
        finally:
            conn.close()
        return recycled

    def expire_pending_by_digest(self, platform: str, current_digest: str) -> int:
        """让基于过期 profile digest 生成的 ``pending`` 关键词失效。

        当 profile 变化时，planner 会让任何来自旧 digest 的 ``pending`` 词
        失效，使下一次生成使用新的 profile。``used`` / ``claimed`` /
        ``executing`` 行保持不变（dedup 历史 + in-flight 工作会被保留）。
        返回被失效的计数。
        """
        cursor = self._execute_write(
            """
            UPDATE discovery_keywords
            SET status = 'expired'
            WHERE platform = ? AND status = 'pending' AND profile_kw_digest != ?
            """,
            (platform.strip(), current_digest.strip()),
        )
        return int(cursor.rowcount or 0)

    def purge_archived_keywords(
        self,
        retention_hours: float,
        *,
        platform: str | None = None,
    ) -> int:
        """删除超过保留期的已归档（``used`` / ``expired`` / ``failed``）行。

        清理已经离开 dedup 窗口、不再需要用于 yield 核算的行。只有终态归档
        状态会被清除；in-flight 行永远不会被删除。返回被移除的行数。
        """
        from datetime import UTC, datetime, timedelta

        cutoff = (datetime.now(UTC) - timedelta(hours=max(0.0, retention_hours))).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        params: list[Any] = [cutoff]
        platform_clause = ""
        if platform is not None:
            platform_clause = " AND platform = ?"
            params.append(platform.strip())
        cursor = self._execute_write(
            f"""
            DELETE FROM discovery_keywords
            WHERE status IN ('used', 'expired', 'failed')
              AND COALESCE(used_at, executing_at, claimed_at, created_at) < ?
              {platform_clause}
            """,
            params,
        )
        return int(cursor.rowcount or 0)

    # ── Discovery keyword yield（P1.8 admit-time 回填）───────────

    def increment_keyword_yield(self, keyword_id: int, content_id: str) -> bool:
        """幂等地把一个 admitted content 计入产出它的 keyword。

        在 admission 时（唯一的 ``_cache_results`` 汇合点）为每个
        ``source_keyword_id`` 已设置的 pool 项调用。幂等性以
        ``(keyword_id, content_id)`` 为 key 通过 ``discovery_keyword_yield``
        账本实现：账本的 ``INSERT OR IGNORE`` 对每个不同的产出 content 只
        触发一次，因此对同一项的重试 / 部分 / 乱序 admit **不会**重复计数。
        ``yield_count`` 仅在真正新写入账本行时才递增。与 ``used`` (P1.7)
        解耦 —— 一个 word 可以已经是 ``used`` 但仍能在后续累计 yield。

        本次调用记录了新 yield（计数器递增）返回 True，重复 / 无效的 no-op
        返回 False。
        """
        kid = int(keyword_id)
        cid = str(content_id or "").strip()
        if kid <= 0 or not cid:
            return False
        before = self.conn.total_changes
        self._execute_write(
            """
            INSERT OR IGNORE INTO discovery_keyword_yield (keyword_id, content_id)
            VALUES (?, ?)
            """,
            (kid, cid),
        )
        if self.conn.total_changes == before:
            # 账本行已存在 → 这个 (keyword, content) 已经计过 credit。
            # 不要动计数器。
            return False
        self._execute_write(
            "UPDATE discovery_keywords SET yield_count = yield_count + 1 WHERE id = ?",
            (kid,),
        )
        return True

    def keyword_yield_count(self, keyword_id: int) -> int:
        """返回某个 keyword 存储的 ``yield_count``（未知则返回 0）。"""
        self._ensure_fresh_read()
        row = self.conn.execute(
            "SELECT yield_count FROM discovery_keywords WHERE id = ?",
            (int(keyword_id),),
        ).fetchone()
        return int(row["yield_count"]) if row is not None else 0

    def keyword_yield_total(self, platform: str) -> int:
        """返回某平台所有 keyword 的 ``yield_count`` 之和。

        廉价的单次聚合（``(platform, status, …)`` 索引已覆盖该扫描），
        仅用于 planner 的每周期可观测性账本 (P1.9)：合并后的 LLM 调用是
        单个 ``discovery.keyword_planner`` caller（token 成本无法按平台
        拆分），因此账本暴露按平台的 keyword *production*（生成）+
        累计 *yield*，让运维仍能看到哪个平台的搜索词真正落到了 content。
        统计每一行存储的 ``yield_count``（含 used / expired 历史）——
        这是一个累计生产总量，不是 live-pool 计量。任何错误都返回 0，
        这样它永远不会打断 generation pass。
        """
        try:
            self._ensure_fresh_read()
            row = self.conn.execute(
                "SELECT COALESCE(SUM(yield_count), 0) AS total "
                "FROM discovery_keywords WHERE platform = ?",
                (platform.strip(),),
            ).fetchone()
        except Exception:
            logger.debug("keyword_yield_total failed for %s", platform, exc_info=True)
            return 0
        return int(row["total"]) if row is not None else 0

    def used_keyword_count(self, platform: str) -> int:
        """统计某平台的 ``used`` 关键词数（P3.2 dynamic-cap 分母）。

        与 :meth:`keyword_yield_total` 配对，用于推导平台观测到的平均
        yield-per-keyword（总 yield / used 计数）。廉价的单次聚合；任何错误
        都返回 0，因此它永远不会打断 generation pass。
        """
        try:
            self._ensure_fresh_read()
            row = self.conn.execute(
                "SELECT COUNT(*) AS n FROM discovery_keywords "
                "WHERE platform = ? AND status = 'used'",
                (platform.strip(),),
            ).fetchone()
        except Exception:
            logger.debug("used_keyword_count failed for %s", platform, exc_info=True)
            return 0
        return int(row["n"]) if row is not None else 0

    def retire_zero_yield_keywords(
        self,
        platform: str,
        *,
        min_age_minutes: float = 60.0,
    ) -> int:
        """保守地退休那些未产出任何内容的 ``used`` 词。

        一个已经被 ``used`` 至少 ``min_age_minutes`` 分钟且仍然
        ``yield_count == 0`` 的词会被移到 ``expired``，这样回收器就不会
        持续重新 pending 一个明显永远落不到内容上的搜索词。

        年龄下限是安全阀，避免退休一个*刚刚*被 used 的词，其 admit 仍可能
        pending：inline-admit 会同步计入 yield，但 fetch-only（X / YouTube）
        和 async（XHS）的词在 handoff 时被标记为 ``used``，只有当共享 pipeline
        admit 时（几分钟后）才会累计 yield。``min_age_minutes`` 必须明显超过
        该 admit 延迟。只动 ``used`` 行；in-flight / pending / 已 expired 的
        行不动。返回被退休的行数。
        """
        from datetime import UTC, datetime, timedelta

        cutoff = (datetime.now(UTC) - timedelta(minutes=max(0.0, min_age_minutes))).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        cursor = self._execute_write(
            """
            UPDATE discovery_keywords
            SET status = 'expired'
            WHERE platform = ?
              AND status = 'used'
              AND yield_count = 0
              AND used_at IS NOT NULL
              AND used_at <= ?
            """,
            (platform.strip(), cutoff),
        )
        return int(cursor.rowcount or 0)

    # ── Discovery keyword planner single-flight 锁 ─────────────

    def acquire_planner_lock(self, owner: str, lease_seconds: float) -> bool:
        """尝试通过 CAS 获取 planner single-flight 锁。

        ``BEGIN IMMEDIATE`` 把 check-and-set 串行化：当锁未被持有、已由
        ``owner`` 持有、或其 ``locked_until`` 已过期（上一持有者崩溃）时
        授予锁。成功时 ``locked_until`` 延长 ``lease_seconds``，并设置行的
        ``owner``。**只做短事务** —— acquire、commit，然后在不持有任何
        DB 锁的情况下运行 LLM 调用；写结果时再 reacquire/``renew``。
        锁现在由 ``owner`` 持有则返回 True。
        """
        from datetime import UTC, datetime, timedelta

        lock_name = "keyword_planner"
        now = datetime.now(UTC)
        now_text = now.strftime("%Y-%m-%d %H:%M:%S")
        new_until = (now + timedelta(seconds=max(0.0, lease_seconds))).strftime("%Y-%m-%d %H:%M:%S")
        conn = self.open_connection()
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT owner, locked_until FROM discovery_planner_lock WHERE lock_name = ?",
                (lock_name,),
            ).fetchone()
            if row is None:
                conn.execute(
                    """
                    INSERT INTO discovery_planner_lock
                        (lock_name, owner, locked_until, updated_at)
                    VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                    """,
                    (lock_name, owner, new_until),
                )
                conn.commit()
                return True
            held_by = str(row["owner"] or "")
            locked_until = str(row["locked_until"] or "")
            if held_by and held_by != owner and locked_until > now_text:
                # 仍被其他人有效持有。
                conn.commit()
                return False
            conn.execute(
                """
                UPDATE discovery_planner_lock
                SET owner = ?, locked_until = ?, updated_at = CURRENT_TIMESTAMP
                WHERE lock_name = ?
                """,
                (owner, new_until, lock_name),
            )
            conn.commit()
        except Exception:
            if conn.in_transaction:
                conn.rollback()
            raise
        finally:
            conn.close()
        return True

    def renew_planner_lock(self, owner: str, lease_seconds: float) -> bool:
        """若 planner 锁仍由 ``owner`` 持有则延长其租约。

        租约延长成功返回 True，期间锁已被其他 owner 取走则返回 False。
        """
        from datetime import UTC, datetime, timedelta

        new_until = (datetime.now(UTC) + timedelta(seconds=max(0.0, lease_seconds))).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        cursor = self._execute_write(
            """
            UPDATE discovery_planner_lock
            SET locked_until = ?, updated_at = CURRENT_TIMESTAMP
            WHERE lock_name = 'keyword_planner' AND owner = ?
            """,
            (new_until, owner),
        )
        return int(cursor.rowcount or 0) > 0

    def release_planner_lock(self, owner: str) -> bool:
        """若 planner 锁仍由 ``owner`` 持有则释放。

        清除 owner 并使 ``locked_until`` 过期，使下一个 acquirer 可以立即
        取得锁。如果释放了某行则返回 True。
        """
        from datetime import UTC, datetime

        now_text = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")
        cursor = self._execute_write(
            """
            UPDATE discovery_planner_lock
            SET owner = '', locked_until = ?, updated_at = CURRENT_TIMESTAMP
            WHERE lock_name = 'keyword_planner' AND owner = ?
            """,
            (now_text, owner),
        )
        return int(cursor.rowcount or 0) > 0

    # ── Watch-later CRUD ─────────────────────────────────────────

    def add_to_watch_later(self, bvid: str, note: str = "") -> bool:
        """收藏一个视频。新插入返回 True，已存在并更新返回 False。"""
        self._execute_write(
            """
            INSERT INTO watch_later (bvid, note)
            VALUES (?, ?)
            ON CONFLICT(bvid) DO UPDATE SET
                added_at = CURRENT_TIMESTAMP,
                note = excluded.note
            """,
            (bvid.strip(), note),
        )
        return self.conn.total_changes > 0

    def remove_from_watch_later(self, bvid: str) -> bool:
        """移除一个收藏。删除了行返回 True。"""
        self._execute_write(
            "DELETE FROM watch_later WHERE bvid = ?",
            (bvid.strip(),),
        )
        return self.conn.total_changes > 0

    def is_in_watch_later(self, bvid: str) -> bool:
        """检查视频是否已被收藏。"""
        row = self.conn.execute(
            "SELECT 1 FROM watch_later WHERE bvid = ?",
            (bvid.strip(),),
        ).fetchone()
        return row is not None

    def count_watch_later(self) -> int:
        """返回已收藏视频总数。"""
        row = self.conn.execute("SELECT COUNT(*) FROM watch_later").fetchone()
        return int(row[0]) if row else 0

    def list_watch_later(self, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
        """返回带 content_cache 元数据的收藏视频，按最新优先。"""
        cursor = self.conn.execute(
            """
            SELECT
                w.bvid,
                w.added_at,
                w.note,
                COALESCE(c.title, '') AS title,
                COALESCE(c.up_name, '') AS up_name,
                COALESCE(c.cover_url, '') AS cover_url,
                COALESCE(c.content_url, '') AS content_url,
                COALESCE(c.source_platform, '') AS source_platform
            FROM watch_later AS w
            LEFT JOIN content_cache AS c ON c.bvid = w.bvid
            ORDER BY w.added_at DESC
            LIMIT ? OFFSET ?
            """,
            (limit, offset),
        )
        return [dict(row) for row in cursor.fetchall()]

    def _ensure_favorites_table(self) -> None:
        """为已存在的数据库创建 favorites（收藏夹）表。

        Favorites 是一个永久的、curated 的保留区 —— 与临时的
        ``watch_later`` 队列区分。两张表相互独立，一个视频可以只在
        其中一张、两张都有、或都不在。
        """
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS favorites (
                bvid     TEXT PRIMARY KEY,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                note     TEXT DEFAULT ''
            );
            CREATE INDEX IF NOT EXISTS idx_favorites_added
                ON favorites(added_at DESC);
        """)

    # ── Auth state（password gate 撤销 epoch）──────────────────

    def _ensure_auth_state_table(self) -> None:
        """创建 auth_state key/value 表。

        存放全局撤销 epoch（``auth_epoch``）和 password fingerprint，
        与 ``config.toml`` 分离，这样撤销是一个跨进程的原子计数器，
        而不是整文件重写。见
        ``docs/plans/2026-05-30-web-password-auth-design.md`` §4.7。
        """
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS auth_state (
                key   TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
        """)

    def _ensure_init_runs_table(self) -> None:
        """创建支撑 guided（GUI）初始化的 init_runs 表。

        每次 guided-init 运行对应一行；最新一行是 ``GET /api/init-status``
        （docs/specs/gui-init.md §5a）的权威进度来源。状态跨重启保留，
        这样崩溃 / 热重载的运行在启动时会被修正为 ``failed``，而不是
        留下一个卡住的 ``running`` 标志。
        """
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS init_runs (
                run_id          TEXT PRIMARY KEY,
                -- status: idle|starting|running|completed|failed|cancelled
                status          TEXT NOT NULL,
                stage           INTEGER NOT NULL DEFAULT 0,  -- 0..4
                stages_json     TEXT,  -- JSON: per-stage [{n,status,reason}]
                partial_success INTEGER NOT NULL DEFAULT 0,
                error_reason    TEXT,
                sequence        INTEGER NOT NULL DEFAULT 0,
                started_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                finished_at     TIMESTAMP
            );
        """)

    def get_latest_init_run(self) -> dict[str, Any] | None:
        """返回最近一次 init run 的 dict，不存在则返回 None。

        读取最新的 WAL 状态，这样后台任务 / 另一个进程写入的 run 能
        立刻可见。
        """
        self._ensure_fresh_read()
        row = self.conn.execute(
            "SELECT * FROM init_runs ORDER BY started_at DESC, rowid DESC LIMIT 1"
        ).fetchone()
        return dict(row) if row is not None else None

    def try_reserve_init_starting(self, run_id: str) -> bool:
        """原子地把一个新的 init run 预留为 ``starting`` 状态。

        通过 ``BEGIN IMMEDIATE`` CAS 实现单飞（与 ``bump_auth_epoch``
        类似）：仅当没有 run 当前处于 ``starting``/``running`` 时才成功。
        init 已在运行时返回 False，这样并发的 ``POST /api/init`` 调用方
        不会重复启动（spec §5b TOCTOU）。
        """
        conn = self.open_connection()
        try:
            conn.execute("BEGIN IMMEDIATE")
            active = conn.execute(
                "SELECT 1 FROM init_runs WHERE status IN ('starting','running') LIMIT 1"
            ).fetchone()
            if active is not None:
                conn.rollback()
                return False
            conn.execute(
                """
                INSERT INTO init_runs (run_id, status, stage, sequence, started_at, updated_at)
                VALUES (?, 'starting', 0, 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                ON CONFLICT(run_id) DO UPDATE SET
                    status='starting', stage=0, sequence=0, partial_success=0,
                    error_reason=NULL, finished_at=NULL, updated_at=CURRENT_TIMESTAMP
                """,
                (run_id,),
            )
            conn.commit()
            return True
        finally:
            conn.close()

    def update_init_run(self, run_id: str, **fields: Any) -> None:
        """更新 init run 的可变列（唯一的 status 写入点）。

        只接受白名单中的列，且 ``updated_at`` 总会被刷新；未知 key 会
        抛异常，这样拼写错误不会静默 no-op。
        """
        allowed = {
            "status",
            "stage",
            "stages_json",
            "partial_success",
            "error_reason",
            "sequence",
            "finished_at",
        }
        unknown = set(fields) - allowed
        if unknown:
            raise ValueError(f"update_init_run: unknown columns {sorted(unknown)}")
        if not fields:
            return
        assignments = ", ".join(f"{col} = ?" for col in fields)
        params = [*fields.values(), run_id]
        self._execute_write(
            f"UPDATE init_runs SET {assignments}, updated_at = CURRENT_TIMESTAMP WHERE run_id = ?",
            params,
        )

    def reconcile_init_runs_on_boot(self) -> int:
        """把任何因崩溃/重启而残留为 ``starting``/``running`` 的 run 标记为 failed。

        没有任何 init 任务能在进程重启后存活，因此持久化的 active 状态
        一定是过期的。返回被修正的行数（spec §5a）。
        """
        cursor = self._execute_write(
            """
            UPDATE init_runs
               SET status = 'failed', error_reason = 'interrupted',
                   finished_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
             WHERE status IN ('starting','running')
            """
        )
        return cursor.rowcount

    def get_auth_epoch(self) -> int:
        """返回当前撤销 epoch。读取最新 WAL 状态。

        缺失行表示"从未 bump 过" → 0。存在但值损坏时抛异常（绝不静默
        返回 0），这样 auth gate 会 fail closed，而不是把上一次撤销
        之前签发的 token 复活。见 §4.7。
        """
        self._ensure_fresh_read()
        row = self.conn.execute("SELECT value FROM auth_state WHERE key = 'auth_epoch'").fetchone()
        if row is None:
            return 0
        try:
            return int(row[0])
        except (TypeError, ValueError) as exc:
            raise ValueError(f"corrupt auth_epoch value: {row[0]!r}") from exc

    def bump_auth_epoch(self) -> int:
        """原子地递增并返回撤销 epoch。

        使用短生命周期连接配合 ``BEGIN IMMEDIATE``，这样并发的 bump
        （或另一个进程）不会丢失递增。
        """
        conn = self.open_connection()
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT value FROM auth_state WHERE key = 'auth_epoch'").fetchone()
            # 缺失 → 0；损坏 → 抛异常（绝不把受损的 epoch 向下重置）。
            current = 0 if row is None else int(row[0])
            new_value = current + 1
            conn.execute(
                """
                INSERT INTO auth_state (key, value) VALUES ('auth_epoch', ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (str(new_value),),
            )
            conn.commit()
            return new_value
        finally:
            conn.close()

    def reconcile_password_fingerprint(self, fingerprint: str) -> bool:
        """检测 password 变更并在需要时 bump epoch。

        在单个 ``BEGIN IMMEDIATE`` 事务（CAS）内把 ``fingerprint``（从
        稳定 credential material 派生，见
        ``auth_core.password_fingerprint``）与存储值比较。epoch 被 bump
        时返回 ``True``。首次启用（无先前 fingerprint）只记录值、不 bump。
        见 §4.7。
        """
        conn = self.open_connection()
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT value FROM auth_state WHERE key = 'password_fingerprint'"
            ).fetchone()
            stored = row[0] if row is not None else None
            bumped = False
            if stored is None:
                conn.execute(
                    "INSERT OR REPLACE INTO auth_state (key, value) VALUES "
                    "('password_fingerprint', ?)",
                    (fingerprint,),
                )
            elif stored != fingerprint:
                epoch_row = conn.execute(
                    "SELECT value FROM auth_state WHERE key = 'auth_epoch'"
                ).fetchone()
                # 缺失 → 0；损坏 → 抛异常（caller 会 fail closed）。
                current = 0 if epoch_row is None else int(epoch_row[0])
                conn.execute(
                    "INSERT OR REPLACE INTO auth_state (key, value) VALUES ('auth_epoch', ?)",
                    (str(current + 1),),
                )
                conn.execute(
                    "INSERT OR REPLACE INTO auth_state (key, value) VALUES "
                    "('password_fingerprint', ?)",
                    (fingerprint,),
                )
                bumped = True
            conn.commit()
            return bumped
        finally:
            conn.close()

    def set_password_fingerprint(self, fingerprint: str) -> None:
        """覆盖存储的 fingerprint，但不触碰 epoch。

        在 ``--rotate-secret`` 于新签名 secret 下重置 fingerprint 后使用，
        这样下一次 reconcile 不会重复 bump。
        """
        self._execute_write(
            "INSERT OR REPLACE INTO auth_state (key, value) VALUES ('password_fingerprint', ?)",
            (fingerprint,),
        )

    def revoke_and_set_fingerprint(self, fingerprint: str | None, *, force_bump: bool) -> None:
        """原子地（单个 ``BEGIN IMMEDIATE``）设置 fingerprint，并在 credential
        变更或 ``force_bump`` 为真时 bump epoch。

        供本地 admin endpoint 使用，使 password 变更的撤销（epoch bump）与
        fingerprint 更新一起提交 —— 绝不会出现新 password 已生效但旧 session
        仍存活的半状态（review r1#2）。

        bump 决策在事务内部通过把 ``fingerprint`` 与存储值比较（CAS）做出，
        与 ``reconcile_password_fingerprint`` 一致：首次设置（无存储
        fingerprint）从不 bump，但从已存在 fingerprint 出发的任何 *变更*
        都会 bump —— 即使 caller 的 ``force_bump`` 为 false。这样可以捕获
        caller 在其请求中看不到的有效 credential 变更，例如 admin 通过
        带外 ``set-password`` 热发布一个在磁盘上漂移的 ``password_hash``
        （review r4#2）。``force_bump`` 为 enabled on/off 切换补上一个
        revoke（这类切换不携带 fingerprint 变更）。

        epoch 损坏时抛异常（caller fail closed）。caller 先持久化新 config
        （若此处抛异常则回滚），并仅在此处 commit 之后才发布到 live gate，
        因此这里的失败会让持久化 DB 状态保持不变，持久化/live 的 auth 仍
        使用旧 password；config 写入与本调用之间崩溃的情况由启动时的
        fingerprint reconcile 自愈（review r2#1）。
        """
        conn = self.open_connection()
        try:
            conn.execute("BEGIN IMMEDIATE")
            stored_row = conn.execute(
                "SELECT value FROM auth_state WHERE key = 'password_fingerprint'"
            ).fetchone()
            stored = stored_row[0] if stored_row is not None else None
            credential_changed = (
                fingerprint is not None and stored is not None and stored != fingerprint
            )
            if force_bump or credential_changed:
                row = conn.execute(
                    "SELECT value FROM auth_state WHERE key = 'auth_epoch'"
                ).fetchone()
                current = 0 if row is None else int(row[0])  # corrupt → raise
                conn.execute(
                    "INSERT OR REPLACE INTO auth_state (key, value) VALUES ('auth_epoch', ?)",
                    (str(current + 1),),
                )
            if fingerprint is not None:
                conn.execute(
                    "INSERT OR REPLACE INTO auth_state (key, value) VALUES "
                    "('password_fingerprint', ?)",
                    (fingerprint,),
                )
            conn.commit()
        finally:
            conn.close()

    # ── Favorites CRUD ───────────────────────────────────────────

    def add_to_favorites(self, bvid: str, note: str = "") -> bool:
        """把视频保存到 favorites。新插入返回 True。"""
        self._execute_write(
            """
            INSERT INTO favorites (bvid, note)
            VALUES (?, ?)
            ON CONFLICT(bvid) DO UPDATE SET
                added_at = CURRENT_TIMESTAMP,
                note = excluded.note
            """,
            (bvid.strip(), note),
        )
        return self.conn.total_changes > 0

    def remove_from_favorites(self, bvid: str) -> bool:
        """移除一个 favorite。删除了行返回 True。"""
        self._execute_write(
            "DELETE FROM favorites WHERE bvid = ?",
            (bvid.strip(),),
        )
        return self.conn.total_changes > 0

    def is_in_favorites(self, bvid: str) -> bool:
        """检查视频是否已被收藏到 favorites。"""
        row = self.conn.execute(
            "SELECT 1 FROM favorites WHERE bvid = ?",
            (bvid.strip(),),
        ).fetchone()
        return row is not None

    def count_favorites(self) -> int:
        """返回已收藏到 favorites 的视频总数。"""
        row = self.conn.execute("SELECT COUNT(*) FROM favorites").fetchone()
        return int(row[0]) if row else 0

    def list_favorites(self, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
        """返回带 content_cache 元数据的 favorites 视频，按最新优先。"""
        cursor = self.conn.execute(
            """
            SELECT
                f.bvid,
                f.added_at,
                f.note,
                COALESCE(c.title, '') AS title,
                COALESCE(c.up_name, '') AS up_name,
                COALESCE(c.cover_url, '') AS cover_url,
                COALESCE(c.content_url, '') AS content_url,
                COALESCE(c.source_platform, '') AS source_platform
            FROM favorites AS f
            LEFT JOIN content_cache AS c ON c.bvid = f.bvid
            ORDER BY f.added_at DESC
            LIMIT ? OFFSET ?
            """,
            (limit, offset),
        )
        return [dict(row) for row in cursor.fetchall()]

    def iter_cover_lifecycle(self) -> list[tuple[str, str, bool]]:
        """返回每个缓存封面候选的 ``(cover_url, pool_status, is_saved)``。

        ``is_saved`` 为 True 表示该 bvid 在 favorites 或 watch_later 中。被
        image-cache 清理（:mod:`openbiliclaw.runtime.image_cache`）消费，用于
        决定哪些缓存的封面文件可以安全驱逐：已保存或仍 pending 内容的封面会被
        保留；已消费且未保存内容的封面可被移除。
        """
        cursor = self.conn.execute(
            """
            SELECT
                COALESCE(cc.cover_url, '') AS cover_url,
                COALESCE(cc.pool_status, 'fresh') AS pool_status,
                CASE WHEN f.bvid IS NOT NULL OR w.bvid IS NOT NULL THEN 1 ELSE 0 END AS is_saved
            FROM content_cache AS cc
            LEFT JOIN favorites AS f ON f.bvid = cc.bvid
            LEFT JOIN watch_later AS w ON w.bvid = cc.bvid
            WHERE COALESCE(cc.cover_url, '') <> ''
            """
        )
        return [
            (str(row["cover_url"]), str(row["pool_status"]), bool(row["is_saved"]))
            for row in cursor.fetchall()
        ]

    def iter_servable_cover_urls(self, *, recent_hours: int = 12, limit: int = 300) -> list[str]:
        """返回最近且仍可服务的封面 URL（最新优先），用于 discovery 时预取。

        返回可能仍会被展示的内容封面 —— ``pool_status`` 为
        ``fresh / shown / suppressed``，或已被保存（favorites / watch_later）
        —— 限定为最近 ``recent_hours`` 内的发现，并按最新优先排序，使预取
        扫描（:mod:`openbiliclaw.runtime.image_cache`）在 freshest CDN token
        （尤其是 XHS）过期前缓存它们。recency 窗口还避免扫描不断重试签名
        token 已失效的旧内容。
        """
        cursor = self.conn.execute(
            """
            SELECT cc.cover_url
            FROM content_cache AS cc
            LEFT JOIN favorites AS f ON f.bvid = cc.bvid
            LEFT JOIN watch_later AS w ON w.bvid = cc.bvid
            WHERE COALESCE(cc.cover_url, '') <> ''
              AND cc.discovered_at >= datetime('now', ?)
              AND (
                COALESCE(cc.pool_status, 'fresh') IN ('fresh', 'shown', 'suppressed')
                OR f.bvid IS NOT NULL
                OR w.bvid IS NOT NULL
              )
            ORDER BY cc.discovered_at DESC
            LIMIT ?
            """,
            (f"-{int(recent_hours)} hours", limit),
        )
        return [str(row["cover_url"]) for row in cursor.fetchall()]

    # ── XHS observed URL ingest ───────────────────────────────────

    def save_xhs_observed_urls(self, urls: list[str], page_type: str) -> int:
        """插入观察到的 xhs URL，跳过重复项。返回插入条数。"""
        inserted = 0
        for url in urls:
            # 跳过已见过的 URL
            existing = self.conn.execute(
                "SELECT 1 FROM xhs_observed_urls WHERE url = ?", (url,)
            ).fetchone()
            if existing:
                continue
            self._execute_write(
                "INSERT INTO xhs_observed_urls (url, page_type) VALUES (?, ?)",
                (url, page_type),
            )
            inserted += 1
        return inserted

    # ── Source recipe CRUD ──────────────────────────────────────────

    def save_source_recipe(self, recipe: dict[str, Any]) -> None:
        """插入或更新一条 source recipe。"""
        import json as _json

        self._execute_write(
            """
            INSERT INTO source_recipes (id, source_type, name, strategy, config,
                                        target_share, enabled, created_by, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, COALESCE(?, CURRENT_TIMESTAMP))
            ON CONFLICT(id) DO UPDATE SET
                name = excluded.name,
                strategy = excluded.strategy,
                config = excluded.config,
                target_share = excluded.target_share,
                enabled = excluded.enabled
            """,
            (
                str(recipe["id"]),
                str(recipe["source_type"]),
                str(recipe["name"]),
                str(recipe["strategy"]),
                _json.dumps(recipe.get("config", {}), ensure_ascii=False),
                int(recipe.get("target_share", 4)),
                int(recipe.get("enabled", True)),
                str(recipe.get("created_by", "system")),
                recipe.get("created_at") or None,
            ),
        )

    def get_all_recipes(self) -> list[dict[str, Any]]:
        """返回所有 source recipes。"""
        self._ensure_fresh_read()
        rows = self.conn.execute("SELECT * FROM source_recipes ORDER BY created_at").fetchall()
        return [self._row_to_recipe(row) for row in rows]

    def get_enabled_recipes(self) -> list[dict[str, Any]]:
        """只返回已启用的 source recipes。"""
        self._ensure_fresh_read()
        rows = self.conn.execute(
            "SELECT * FROM source_recipes WHERE enabled = 1 ORDER BY created_at"
        ).fetchall()
        return [self._row_to_recipe(row) for row in rows]

    def update_recipe(self, recipe_id: str, **fields: Any) -> bool:
        """更新 recipe 的指定字段。有行被更新返回 True。"""
        import json as _json

        allowed = {"name", "strategy", "config", "target_share", "enabled", "last_fetched_at"}
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return False
        if "config" in updates and not isinstance(updates["config"], str):
            updates["config"] = _json.dumps(updates["config"], ensure_ascii=False)
        if "enabled" in updates:
            updates["enabled"] = int(updates["enabled"])

        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [recipe_id]
        cursor = self._execute_write(
            f"UPDATE source_recipes SET {set_clause} WHERE id = ?",
            tuple(values),
        )
        return cursor.rowcount > 0

    def delete_recipe(self, recipe_id: str) -> bool:
        """按 id 删除一个 recipe。如果删除了某行则返回 True。"""
        cursor = self._execute_write(
            "DELETE FROM source_recipes WHERE id = ?",
            (recipe_id,),
        )
        return cursor.rowcount > 0

    @staticmethod
    def _row_to_recipe(row: Any) -> dict[str, Any]:
        import json as _json

        config_raw = row["config"] if row["config"] else "{}"
        try:
            config = _json.loads(config_raw)
        except (ValueError, TypeError):
            config = {}
        return {
            "id": str(row["id"]),
            "source_type": str(row["source_type"]),
            "name": str(row["name"]),
            "strategy": str(row["strategy"]),
            "config": config,
            "target_share": int(row["target_share"]),
            "enabled": bool(row["enabled"]),
            "created_by": str(row["created_by"]),
            "created_at": str(row["created_at"] or ""),
            "last_fetched_at": str(row["last_fetched_at"] or ""),
        }

    def get_delight_candidate(
        self,
        *,
        min_delight_score: float = 0.85,
        limit: int = 1,
    ) -> dict[str, Any] | None:
        """返回一个未通知的、``delight_score`` 最高的 pool 项。

        向后兼容：``limit=1`` 返回单个 dict（或 None）；想要多个候选
        （例如在 Python 中过滤 disliked topics）的调用方应改调
        ``get_delight_candidates``。
        """
        rows = self.get_delight_candidates(
            min_delight_score=min_delight_score,
            limit=max(1, int(limit)),
        )
        return rows[0] if rows else None

    def get_delight_candidates(
        self,
        *,
        min_delight_score: float = 0.85,
        limit: int = 20,
        include_liked: bool = False,
    ) -> list[dict[str, Any]]:
        """返回最多 ``limit`` 个按分数排序的未通知 delight 候选。

        限定 ``pool_status IN ('fresh', 'shown')`` —— ``suppressed`` 项已
        被 topic-group cap 或 source-share quota 从活动池中裁掉，不应该再
        作为 delight 重新出现。没有这个守卫，popup re-hydration 会从
        suppressed 墓地中拉出在早期（更宽松的）校准下烘焙的历史 delight
        分数，并在每次扩展重载时浮现 20 个陈旧的"惊喜"（2026-05-04 观测到：
        562 个 suppressed 项携带 delight 元数据，而 fresh 中只有 2 个）。

        ``include_liked`` 让 ``feedback_type='like'`` 行保留在结果中。
        Queue re-hydration（``/api/delight/pending-batch``）传 True，这样
        已 like 的 delight 在用户显式关闭之前保持可见 —— 正向反馈不能移除
        卡片（v0.3.63 契约）。新交付路径（WS 推送、counts、CLI）保持默认
        False，使已经 like 的项绝不会被作为新的 surprise 重新推送。
        """
        feedback_clause = (
            "COALESCE(feedback_type, '') IN ('', 'like')"
            if include_liked
            else "COALESCE(feedback_type, '') = ''"
        )
        min_score = self._pool_admission_min_score()
        cursor = self.conn.execute(
            f"""
            SELECT *
            FROM content_cache
            WHERE COALESCE(delight_score, 0.0) >= ?
              AND COALESCE(relevance_score, 0.0) >= ?
              AND COALESCE(delight_notified, 0) = 0
              AND COALESCE(delight_reason, '') != ''
              AND COALESCE(delight_hook, '') != ''
              AND {feedback_clause}
              AND COALESCE(pool_status, 'fresh') IN ('fresh', 'shown')
            ORDER BY delight_score DESC, relevance_score DESC, discovered_at DESC
            LIMIT ?
            """,
            (min_delight_score, min_score, max(1, int(limit))),
        )
        return [dict(row) for row in cursor.fetchall()]

    def mark_delight_notified(self, bvid: str) -> None:
        """将一个内容项标记为 delight-notified。"""
        self._execute_write(
            """
            UPDATE content_cache
            SET delight_notified = 1,
                delight_notified_at = CURRENT_TIMESTAMP
            WHERE bvid = ?
            """,
            (bvid,),
        )

    def update_delight_score(
        self,
        bvid: str,
        *,
        delight_score: float,
        delight_reason: str,
        delight_hook: str = "",
    ) -> None:
        """持久化某个 pool 项计算出的 delight 分数与解释。"""
        self._execute_write(
            """
            UPDATE content_cache
            SET delight_score = ?,
                delight_reason = ?,
                delight_hook = ?
            WHERE bvid = ?
            """,
            (delight_score, delight_reason, delight_hook, bvid),
        )

    def count_delight_candidates(
        self,
        *,
        min_delight_score: float = 0.85,
    ) -> int:
        """返回未通知的 delight 候选数量。"""
        min_score = self._pool_admission_min_score()
        cursor = self.conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM content_cache
            WHERE COALESCE(delight_score, 0.0) >= ?
              AND COALESCE(relevance_score, 0.0) >= ?
              AND COALESCE(delight_notified, 0) = 0
              AND COALESCE(delight_reason, '') != ''
              AND COALESCE(delight_hook, '') != ''
              AND COALESCE(feedback_type, '') = ''
              AND COALESCE(pool_status, 'fresh') IN ('fresh', 'shown', 'suppressed')
            """,
            (min_delight_score, min_score),
        )
        row = cursor.fetchone()
        return int(row["count"]) if row is not None else 0

    def get_pool_candidates_needing_delight_score(
        self,
        limit: int = 30,
        *,
        min_delight_score_for_reason: float | None = None,
        min_relevance_score: float = 0.55,
        xhs_self_nickname: str = "",
    ) -> list[dict[str, Any]]:
        """返回仍需要 delight 评估或 copy 的 pool 候选。

        两阶段检索：``relevance_score >= min_relevance_score`` 是廉价的
        预过滤（discovery LLM 已在 ``evaluate_batch`` 期间评判过用户-内容
        契合度），然后调用方只对这个 shortlist 运行昂贵的 LLM delight
        scorer。

        默认 0.55 是基于 discovery rubric 校准的：
          0.6+ 强契合，0.5-0.6 中等，<0.5 弱契合。
        低于 ``min_relevance_score`` 的项完全跳过 delight 评分 —— 它们
        不会 delight 任何它们本就一半不契合的人，在弱契合项上烧 LLM 调用
        只是浪费预算。
        """
        guard_sql = _xhs_self_author_guard_sql()
        guard_params = _xhs_self_author_guard_params(xhs_self_nickname)
        effective_min_relevance_score = _normalize_admission_min_score(min_relevance_score)
        if min_delight_score_for_reason is None:
            cursor = self.conn.execute(
                f"""
                SELECT *
                FROM content_cache
                WHERE COALESCE(pool_status, 'fresh') IN ('fresh', 'suppressed')
                  AND COALESCE(feedback_type, '') != 'dislike'
                  AND COALESCE(delight_score, 0.0) = 0.0
                  AND COALESCE(relevance_score, 0.0) >= ?
                  {guard_sql}
                  AND NOT EXISTS (
                    SELECT 1
                    FROM recommendations AS r
                    WHERE r.bvid = content_cache.bvid
                  )
                ORDER BY relevance_score DESC, discovered_at DESC
                LIMIT ?
                """,
                (effective_min_relevance_score, *guard_params, limit),
            )
        else:
            cursor = self.conn.execute(
                f"""
                SELECT *
                FROM content_cache
                WHERE COALESCE(pool_status, 'fresh') IN ('fresh', 'suppressed')
                  AND COALESCE(feedback_type, '') != 'dislike'
                  AND COALESCE(relevance_score, 0.0) >= ?
                  AND (
                    COALESCE(delight_score, 0.0) = 0.0
                    OR (
                      COALESCE(delight_score, 0.0) >= ?
                      AND (
                        COALESCE(delight_reason, '') = ''
                        OR COALESCE(delight_hook, '') = ''
                      )
                    )
                  )
                  {guard_sql}
                  AND NOT EXISTS (
                    SELECT 1
                    FROM recommendations AS r
                    WHERE r.bvid = content_cache.bvid
                  )
                ORDER BY
                    CASE WHEN COALESCE(delight_score, 0.0) > 0.0 THEN 0 ELSE 1 END ASC,
                    delight_score DESC,
                    relevance_score DESC,
                    discovered_at DESC
                LIMIT ?
                """,
                (
                    effective_min_relevance_score,
                    min_delight_score_for_reason,
                    *guard_params,
                    limit,
                ),
            )
        return [dict(row) for row in cursor.fetchall()]

    @staticmethod
    def _decode_event_metadata(row: dict[str, Any]) -> dict[str, Any]:
        metadata_raw = row.get("metadata", "")
        if isinstance(metadata_raw, str) and metadata_raw:
            try:
                metadata = json.loads(metadata_raw)
            except json.JSONDecodeError:
                metadata = {}
            if isinstance(metadata, dict):
                return metadata
        if isinstance(metadata_raw, dict):
            return metadata_raw
        return {}

    @classmethod
    def _extract_content_keys_from_view_event(cls, row: dict[str, Any]) -> set[str]:
        metadata = cls._decode_event_metadata(row)
        url = str(row.get("url", "")).strip()

        platform = _normalize_source_platform_key(metadata.get("source_platform", ""))
        if not platform:
            platform = cls._infer_source_platform_from_url(url)

        content_ids: set[str] = set()
        for key in _VIEW_CONTENT_ID_METADATA_KEYS:
            raw_value = metadata.get(key, "")
            if isinstance(raw_value, (str, int)):
                value = str(raw_value).strip()
                if value:
                    content_ids.add(value)

        url_content_id = cls._extract_content_id_from_url(platform, url)
        if url_content_id:
            content_ids.add(url_content_id)

        bvid = cls._extract_bvid_from_view_event(row)
        if bvid:
            content_ids.add(bvid)
            platform = platform or _BILIBILI_SOURCE_FAMILY

        keys: set[str] = set()
        for content_id in content_ids:
            if content_id.startswith("BV"):
                keys.add(content_id)
            if platform:
                keys.add(f"{platform}:{content_id}")
        return keys

    @staticmethod
    def _infer_source_platform_from_url(url: str) -> str:
        if not url:
            return ""
        host = urlparse(url).netloc.lower()
        if "bilibili.com" in host or host == "b23.tv":
            return _BILIBILI_SOURCE_FAMILY
        if "xiaohongshu.com" in host or "xhslink.com" in host:
            return _XHS_SOURCE_FAMILY
        if "douyin.com" in host:
            return _DOUYIN_SOURCE_FAMILY
        if "youtube.com" in host or host == "youtu.be":
            return _YOUTUBE_SOURCE_FAMILY
        if (
            host == "x.com"
            or host.endswith(".x.com")
            or host == "twitter.com"
            or host.endswith(".twitter.com")
        ):
            return _TWITTER_SOURCE_FAMILY
        return ""

    @staticmethod
    def _extract_content_id_from_url(platform: str, url: str) -> str:
        if not url:
            return ""
        parsed = urlparse(url)
        path_parts = [part for part in parsed.path.split("/") if part]
        if platform == _XHS_SOURCE_FAMILY:
            if len(path_parts) >= 2 and path_parts[0] == "explore":
                return path_parts[1]
            if len(path_parts) >= 3 and path_parts[:2] == ["discovery", "item"]:
                return path_parts[2]
        if platform == _DOUYIN_SOURCE_FAMILY and "video" in path_parts:
            video_index = path_parts.index("video")
            if len(path_parts) > video_index + 1:
                return path_parts[video_index + 1]
        if platform == _YOUTUBE_SOURCE_FAMILY:
            query_video_id = parse_qs(parsed.query).get("v", [""])[0].strip()
            if query_video_id:
                return query_video_id
            if parsed.netloc.lower() == "youtu.be" and path_parts:
                return path_parts[0]
            for prefix in ("shorts", "embed", "live"):
                if prefix in path_parts:
                    prefix_index = path_parts.index(prefix)
                    if len(path_parts) > prefix_index + 1:
                        return path_parts[prefix_index + 1]
        if platform == _BILIBILI_SOURCE_FAMILY:
            match = _BVID_PATTERN.search(url)
            if match:
                return match.group(1)
        return ""

    @staticmethod
    def _extract_bvid_from_view_event(row: dict[str, Any]) -> str:
        metadata = Database._decode_event_metadata(row)
        bvid = str(metadata.get("bvid", "")).strip()
        if bvid:
            return bvid

        url = str(row.get("url", "")).strip()
        match = _BVID_PATTERN.search(url)
        if match:
            return match.group(1)
        return ""

    @staticmethod
    def _content_row_view_keys(row: dict[str, Any]) -> set[str]:
        platform = _normalize_source_platform_key(row.get("source_platform", ""))
        if not platform:
            platform = _pool_source_family(row.get("source", ""), row.get("source_platform", ""))
            if platform == "unknown":
                platform = ""

        keys: set[str] = set()
        raw_bvid = str(row.get("bvid", "") or "").strip()
        content_id = str(row.get("content_id", "") or "").strip() or raw_bvid
        for value in {raw_bvid, content_id}:
            if not value:
                continue
            if value.startswith("BV"):
                keys.add(value)
            if platform:
                keys.add(f"{platform}:{value}")
        return keys

    @staticmethod
    def _is_viewed_row(row: dict[str, Any], viewed_content_keys: set[str]) -> bool:
        if not viewed_content_keys:
            return False
        return bool(Database._content_row_view_keys(row) & viewed_content_keys)

    @staticmethod
    def _exclude_viewed_rows(
        rows: list[dict[str, Any]],
        viewed_content_keys: set[str],
        *,
        limit: int,
    ) -> list[dict[str, Any]]:
        if not viewed_content_keys:
            return rows[:limit]
        filtered = [row for row in rows if not Database._is_viewed_row(row, viewed_content_keys)]
        return filtered[:limit]
