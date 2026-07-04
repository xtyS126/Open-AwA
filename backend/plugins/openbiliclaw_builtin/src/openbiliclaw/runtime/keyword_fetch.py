"""缺口驱动的关键词抓取协调器（Discover 反压，P1.7）。

P1.6 让关键词 *规划器* 用 ``pending`` 搜索词填满 ``discovery_keywords``
存储。P1.7 让五个搜索 *抓取* 站点消费该存储：当
``[discovery].unified_keyword_planner_enabled`` 开关打开时，每个站点
从存储中 claim 词（原子 ``claim_keywords``），通过 P1.5 的注入参数
注入、抓取，并按其 *执行形态* 把每个 claimed 词推到对应终态——
``used`` / ``failed`` / （异步）``executing``（设计规范 §5.1 / §11）：

* **内联准入**（B 站 search、抖音 plugin）：抓取 → 评估 → 准入同步
  发生在调用中。成功返回时把每个 claimed 词标记为 ``used``；抓取异常
  / 空结果标记为 ``failed``。
* **仅抓取 → 延迟管线准入**（X、YouTube）：producer 抓取原始候选，
  交给 ``discovery_candidates`` / 候选管线；准入在下游。词在交接时即
  被 *消费* → ``used``（yield 稍后回填，P1.8，与 ``used`` 解耦）。
* **真正异步**（仅小红书）：扩展在带外执行搜索。Claim → 入队携带
  ``source_keyword_id`` 的 xhs 任务 → 把词标记为 ``executing``（不是
  ``used``）。xhs 任务结果处理器在终态回调中把它标记为 ``used`` /
  ``failed``。回调缺失由规划器的 ``reclaim_leased_keywords`` 租约
  扫描兜底。

**claim 后被预算拒绝的回滚。** 如果一个词已 claim，但随后的入队 /
抓取被预算上限拒绝（实际没有任何抓取发生），该词必须回到
``pending``，而不是被烧掉。这需要一个 *可区分* 的信号：XHS 入队返回
``ok=False``；抖音 ``search_aweme`` 抛
:class:`~openbiliclaw.sources.douyin_plugin_search.DouyinBudgetExhausted`。
协调器的 :meth:`rollback` 会调用 ``rollback_keyword_to_pending``。

开关默认关闭；开关打开的切换 + E2E 属于 P1.9。开关关闭（或未注入
协调器）时，每个站点走字节级一致的旧路径。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from openbiliclaw.config import DiscoveryConfig

logger = logging.getLogger(__name__)

# 规范的长形平台标识——这些是关键词存储 + 规划器共用的键
# （不是短码 xhs/dy/yt/bili）。
PLATFORM_BILIBILI = "bilibili"
PLATFORM_XIAOHONGSHU = "xiaohongshu"
PLATFORM_DOUYIN = "douyin"
PLATFORM_YOUTUBE = "youtube"
PLATFORM_TWITTER = "twitter"
PLATFORM_ZHIHU = "zhihu"


@dataclass(frozen=True)
class ClaimedKeyword:
    """一条 claimed 搜索词 + 其存储行 id（生命周期关联）。"""

    id: int
    keyword: str


class KeywordFetchCoordinator:
    """5 个抓取站点共用的"从存储 claim + 词生命周期"助手。

    持有数据库（``discovery_keywords`` DAO）和 discovery 配置（开关 +
    ``fetch_batch``）。一个协调器实例注入到每个 producer / 刷新控制器
    中；每个抓取站点通过 :meth:`should_claim` 询问是否走开关打开的
    路径，再驱动 :meth:`claim` 及下方的终态标记。
    """

    def __init__(self, *, database: Any, discovery_config: DiscoveryConfig) -> None:
        self._db = database
        self._discovery = discovery_config

    # ── 开关 / 闸门 ─────────────────────────────────────────────────────

    @property
    def enabled(self) -> bool:
        """统一关键词规划器开关是否打开（默认关闭）。"""
        return bool(getattr(self._discovery, "unified_keyword_planner_enabled", False))

    @property
    def fetch_batch(self) -> int:
        """每次抓取 claim 多少个词（``[discovery].fetch_batch``）。"""
        return max(1, int(getattr(self._discovery, "fetch_batch", 5)))

    def should_claim(self) -> bool:
        """返回抓取站点是否应走"从存储 claim"路径。

        缺口闸门（deficit > 0）和独立底线（各平台既有的
        ``min_interval`` / ``_is_due``）由站点在调用此方法 *之前*
        自行强制——协调器只拥有开关。"存储非空" 闸门由 :meth:`claim`
        返回 ``[]`` 来强制。
        """
        return self.enabled

    # ── claim ───────────────────────────────────────────────────────────

    def claim(self, platform: str, n: int | None = None) -> list[ClaimedKeyword]:
        """原子地 claim 最多 ``n`` 个（默认 ``fetch_batch``）pending 词。

        当存储中没有该平台可 claim 的 ``pending`` 词时返回 ``[]``
        （即 "存储非空" 闸门）——此时调用方必须回退到旧路径 / no-op
        路径，且不得标记任何生命周期状态。
        """
        count = self.fetch_batch if n is None else max(0, int(n))
        if count <= 0:
            return []
        claim_fn = getattr(self._db, "claim_keywords", None)
        if not callable(claim_fn):
            return []
        try:
            rows = claim_fn(platform, count)
        except Exception:
            logger.exception("keyword fetch: claim_keywords failed for %s", platform)
            return []
        claimed: list[ClaimedKeyword] = []
        for row in rows or []:
            try:
                kid = int(row["id"])
                word = str(row["keyword"]).strip()
            except (KeyError, TypeError, ValueError):
                continue
            if word:
                claimed.append(ClaimedKeyword(id=kid, keyword=word))
        return claimed

    # ── 生命周期终态 ─────────────────────────────────────────────────────

    def mark_used(self, claimed: list[ClaimedKeyword]) -> None:
        """把每个 claimed 词标记为 ``used``（内联成功 / 仅抓取交接）。"""
        mark = getattr(self._db, "mark_keyword_used", None)
        if not callable(mark):
            return
        for item in claimed:
            try:
                mark(item.id)
            except Exception:
                logger.exception("keyword fetch: mark_keyword_used failed for id=%s", item.id)

    def mark_failed(self, claimed: list[ClaimedKeyword]) -> None:
        """把每个 claimed 词标记为 ``failed``（抓取异常 / 空结果）。"""
        mark = getattr(self._db, "mark_keyword_failed", None)
        if not callable(mark):
            return
        for item in claimed:
            try:
                mark(item.id)
            except Exception:
                logger.exception("keyword fetch: mark_keyword_failed failed for id=%s", item.id)

    def mark_executing(self, claimed: ClaimedKeyword) -> None:
        """把一个 claimed 词标记为 ``executing``（异步 XHS 任务入队）。"""
        mark = getattr(self._db, "mark_keyword_executing", None)
        if not callable(mark):
            return
        try:
            mark(claimed.id)
        except Exception:
            logger.exception("keyword fetch: mark_keyword_executing failed for id=%s", claimed.id)

    def rollback(self, claimed: ClaimedKeyword) -> None:
        """把一个 claimed 词回滚为 ``pending``（claim 后被预算拒绝）。"""
        rollback = getattr(self._db, "rollback_keyword_to_pending", None)
        if not callable(rollback):
            return
        try:
            rollback(claimed.id)
        except Exception:
            logger.exception(
                "keyword fetch: rollback_keyword_to_pending failed for id=%s", claimed.id
            )


def mark_keyword_terminal_from_xhs_task(
    database: Any,
    payload_json: str | None,
    *,
    success: bool,
) -> None:
    """把 xhs 任务的 ``source_keyword_id`` 词标记为 ``used`` / ``failed``。

    在终态回调时由 xhs 任务结果处理器（``api/app.py``）调用。关键词 id
    挂在任务 payload 上（P1.7 生命周期关联）；没有
    ``source_keyword_id`` 的任务（旧任务 / 非规划器任务）静默 no-op。
    容忍缺失 / 格式错误的 payload。
    """
    keyword_id = _extract_source_keyword_id(payload_json)
    if keyword_id is None:
        return
    method = "mark_keyword_used" if success else "mark_keyword_failed"
    mark = getattr(database, method, None)
    if not callable(mark):
        return
    try:
        mark(keyword_id)
    except Exception:
        logger.exception("keyword fetch: %s failed for id=%s", method, keyword_id)


def source_keyword_id_from_xhs_task(payload_json: str | None) -> int | None:
    """公开：从 xhs 任务 payload 读取 ``source_keyword_id``，或 ``None``。

    由 xhs 任务结果处理器（P1.8）使用，把产出关键词的 id 透传到该任务
    摄入的候选上，使准入时能回填该关键词的 yield。容忍缺失 / 格式错误
    / 旧版 payload。
    """
    return _extract_source_keyword_id(payload_json)


def _extract_source_keyword_id(payload_json: str | None) -> int | None:
    """从 xhs 任务 payload JSON 中解析 ``source_keyword_id``。"""
    if not payload_json:
        return None
    import json

    try:
        payload = json.loads(payload_json)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(payload, dict):
        return None
    raw = payload.get("source_keyword_id")
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None
