"""OpenBiliClaw 的命令行接口。

使用 Typer 提供命令行入口。
"""

from __future__ import annotations

import asyncio
import os
import re
import sys
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import click
import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from openbiliclaw.runtime.ollama_supervisor import (
    _ollama_is_running,
    _ollama_start_serve_background,
    effective_ollama_endpoint,
    is_loopback,
    ollama_required,
)
from openbiliclaw.soul.preference_analyzer import DEFAULT_PREFERENCE_EVENT_CHUNK_SIZE


def _force_utf8_stdout_on_windows() -> None:
    """将 stdout/stderr 在 Windows 上重新配置为 UTF-8。

    原因：简体中文 Windows 默认将控制台编码设为 GBK (cp936)。
    CLI 输出中的任何 emoji（如初始化横幅里的 ``[TIME]``、typer 帮助
    文本里的 ``[CRAB]``）一旦输出流尝试编码就会抛出
    UnicodeEncodeError，用户会看到程序崩溃却没有任何有用信息。

    修复：在 import 时强制将 sys.stdout / sys.stderr 切换为 UTF-8 模式，
    并以 ``errors='replace'`` 作为最后的安全网，让偶尔出现的
    不可翻译字节降级为 '?' 而不是让整个运行崩溃。
    该操作幂等，在 POSIX 上为 no-op（``reconfigure`` 是 Python 3.7+
    TextIOWrapper 上的方法，只是重新接线编解码器）。
    """
    if os.name != "nt":
        return
    # PYTHONUTF8=1 是最干净的修复方式，但只在进程启动时生效，
    # 不在模块 import 时生效——为我们 spawn 的任何子进程设置它
    # （CLI 内部的 subprocess 调用会继承该设置）。
    os.environ.setdefault("PYTHONUTF8", "1")
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            with suppress(Exception):
                reconfigure(encoding="utf-8", errors="replace")


_force_utf8_stdout_on_windows()


app = typer.Typer(
    name="openbiliclaw",
    help="[CRAB] OpenBiliClaw — 你的 B 站专属 AI 朋友",
    add_completion=False,
)
auth_app = typer.Typer(help="B 站认证命令")
login_app = typer.Typer(help="账号登录命令")
browser_app = typer.Typer(help="agent-browser 浏览器命令")
autostart_app = typer.Typer(help="开机自启动命令")
app.add_typer(auth_app, name="auth")
app.add_typer(login_app, name="login")
app.add_typer(browser_app, name="browser")
app.add_typer(autostart_app, name="autostart")
console = Console()
_APP_CONTEXT: dict[str, Any] = {}
_DISCOVER_STRATEGIES_OPTION = typer.Option(
    None,
    "--strategy",
    "-S",
    help=(
        "Bilibili 策略过滤，可多次传或逗号分隔："
        "search / trending / explore / related_chain。"
        "仅在 --source=bilibili 时生效。"
    ),
)
_ZHIHU_DISCOVER_KEYWORDS_ARGUMENT = typer.Argument(
    ...,
    help="知乎搜索关键词，可传多个；单个参数里也可以用逗号分隔。",
)
_ZHIHU_CREATOR_URLS_ARGUMENT = typer.Argument(
    ...,
    help="知乎作者主页 URL 或 people slug，可传多个。",
)
_ZHIHU_RELATED_URLS_ARGUMENT = typer.Argument(
    ...,
    help="知乎问题 / 回答 / 文章 URL，可传多个。",
)
_DOUYIN_DISCOVERY_KEYWORDS_OPTION = typer.Option(
    None,
    "--keyword",
    "-k",
    help="指定搜索关键词；可多次传或逗号分隔。不传时从 Soul 画像兴趣生成。",
)
_DOUYIN_DISCOVERY_CREATOR_SEC_UIDS_OPTION = typer.Option(
    None,
    "--creator-sec-uid",
    help=("兼容旧参数；当前公开 discovery 来源不再包含 creator。"),
)
_DOUYIN_DISCOVERY_SOURCES_OPTION = typer.Option(
    None,
    "--source",
    "-s",
    help="抖音 discovery 子来源：search、hot、feed，可多次传或逗号分隔。",
)
_DOUYIN_SEARCH_KEYWORDS_OPTION = typer.Option(
    ...,
    "--keyword",
    "-k",
    help="抖音搜索关键词，可重复传或用逗号分隔。",
)
_CODEX_LOGIN_IMPORT_OPTION = typer.Option(
    False,
    "--import",
    help="只导入已有 Codex CLI 凭据，不调用 `codex login`。",
)
_CODEX_LOGIN_SOURCE_OPTION = typer.Option(
    None,
    "--source",
    help="Codex CLI auth.json 路径；默认读取 ~/.codex/auth.json。",
)
_CODEX_LOGIN_STATUS_OPTION = typer.Option(
    False,
    "--status",
    help="查看 Codex OAuth 登录状态。",
)
_CODEX_LOGIN_LOGOUT_OPTION = typer.Option(
    False,
    "--logout",
    help="删除 OpenBiliClaw 本地 Codex 凭据。",
)


def _bootstrap_container_runtime() -> None:
    """在 Docker 类运行时中引导运行时根目录与可选的代理环境变量。"""
    if not (
        os.environ.get("OPENBILICLAW_PROJECT_ROOT")
        or os.environ.get("OPENBILICLAW_CONFIG_TEMPLATE")
    ):
        return

    from openbiliclaw.docker_runtime import bootstrap_runtime_environment

    bootstrap_runtime_environment(os.environ)


_RUNTIME_COMPONENTS: dict[str, Any] = {}
# 初始 discover 在单个阶段内运行全部四种策略，以便触发
# discovery 引擎内置的并发：phase 1 单独对无 cookie 客户端运行
# ``search`` 以避开 IP 级搜索限流，随后 phase 2 通过
# asyncio.gather 并发扇出 ``trending``、``related_chain``
# 和 ``explore``。墙钟时间从 ``∑strategy`` 压缩到约等于
# ``search + max(trending, related, explore)``。
#
# 限流已经被 ``DiscoveryConcurrencyController`` 约束：
# ``search_budget_total=30`` 在三种使用 search 的策略间分配，
# ``bilibili_request_concurrency=2`` 无论并行多少策略都
# 限制同时进行的 HTTP 请求数。
_INIT_DISCOVERY_PLAN = [
    ["search", "trending", "related_chain", "explore"],
]
# 初始池目标值。保持小以便 discover 阶段在一到两轮
# LLM 评估波内完成，且不会触发 ``_run_backfill``。
# 后台刷新循环会在接下来一小时内把池补到
# ``scheduler.pool_target_count``（默认 300），因此
# 一个小的 init 池只会延迟多样性，绝不会减少多样性。
_INIT_POOL_TARGET_COUNT = 15
_INIT_BILIBILI_HISTORY_LIMIT = 500
_INIT_BILIBILI_FAVORITE_LIMIT = 500
_INIT_BILIBILI_FOLLOW_LIMIT = 100
# X (Twitter)：用户自己的 Likes + Bookmarks，通过 twitter-cli
# 在服务端拉取（无需扩展任务）。两者都是强显式偏好信号。
_INIT_X_LIKES_LIMIT = 200
_INIT_X_BOOKMARKS_LIMIT = 200
_INIT_BOOTSTRAP_MAX_ITEMS_PER_SCOPE = 300
_DEFAULT_XHS_BOOTSTRAP_WAIT_SECONDS = 180.0
_DEFAULT_DY_BOOTSTRAP_WAIT_SECONDS = 180.0
_DEFAULT_YT_BOOTSTRAP_WAIT_SECONDS = 240.0
_DEFAULT_ZHIHU_BOOTSTRAP_WAIT_SECONDS = 180.0
_DEFAULT_XHS_BOOTSTRAP_DEDUPE_HOURS = 6.0
_DEFAULT_DY_BOOTSTRAP_DEDUPE_HOURS = 6.0
_DEFAULT_YT_BOOTSTRAP_DEDUPE_HOURS = 6.0
_DEFAULT_ZHIHU_BOOTSTRAP_DEDUPE_HOURS = 6.0
_EXTENSION_PRESENCE_REQUIRED_WARNING = (
    "WARN extension presence required; backend will pause background LLM work "
    "after grace period if no extension client connects"
)

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine, Mapping


def _print_page_title(title: str, subtitle: str = "") -> None:
    """渲染一致的页面标题。"""
    body = title if not subtitle else f"{title}\n[dim]{subtitle}[/dim]"
    console.print(Panel.fit(body, border_style="cyan"))


def _print_status_panel(kind: str, title: str, body: str) -> None:
    """渲染具有统一视觉语义的状态面板。"""
    styles = {
        "success": "green",
        "warning": "yellow",
        "error": "red",
        "info": "cyan",
        "stub": "blue",
    }
    console.print(Panel(body, title=title, border_style=styles.get(kind, "cyan")))


def _print_key_value_table(title: str, rows: list[tuple[str, str]]) -> None:
    """为状态类命令渲染键值表。"""
    table = Table(title=title, show_header=False, box=None, pad_edge=False)
    table.add_column("key", style="bold cyan", no_wrap=True)
    table.add_column("value")
    for key, value in rows:
        table.add_row(key, value)
    console.print(table)


def _format_pause_on_disconnect_status(*, enabled: bool, grace_seconds: int) -> str:
    if not enabled:
        return "关闭"
    return f"开启（宽限 {grace_seconds}s）"


def _warn_if_pause_on_disconnect_requires_presence() -> None:
    """当后台任务依赖扩展存在时打印启动告警。"""
    try:
        from openbiliclaw.config import load_config

        cfg = load_config()
    except Exception:
        return

    if cfg.scheduler.pause_on_extension_disconnect:
        console.print(
            f"[yellow]{_EXTENSION_PRESENCE_REQUIRED_WARNING}[/yellow]",
            soft_wrap=True,
        )


def _is_default_ollama_endpoint(endpoint: str) -> bool:
    from urllib.parse import urlparse

    parsed = urlparse(endpoint)
    host = (parsed.hostname or "").strip().lower()
    return host in {"localhost", "127.0.0.1", "::1"} and parsed.port == 11434


def _preflight_loopback_ollama(cfg: Any) -> None:
    if not ollama_required(cfg) or not cfg.autostart.manage_ollama:
        return
    endpoint = effective_ollama_endpoint(cfg)
    if not is_loopback(endpoint):
        return
    if _ollama_is_running(host=endpoint):
        return
    if not _is_default_ollama_endpoint(endpoint):
        console.print(
            f"[yellow]本机 Ollama 端点 {endpoint} 未响应；自定义端口不会自动执行 "
            "`ollama serve`，请自行管理该服务。[/yellow]"
        )
        return
    if not _ollama_start_serve_background():
        console.print(
            "[yellow]Ollama preflight 未能拉起本机服务；后端继续启动，"
            "后续 LLM/embedding 请求可能降级或失败。[/yellow]"
        )


def _self_heal_autostart_registration(cfg: Any) -> None:
    from openbiliclaw.runtime import autostart

    state = autostart.status()
    if not state.supported:
        return

    if not cfg.autostart.enabled:
        if state.registered:
            try:
                autostart.unregister()
            except Exception as exc:
                console.print(f"[yellow]开机自启动残留项移除失败：{exc}[/yellow]")
        return

    if state.registered:
        return

    from openbiliclaw.runtime.autostart.guards import active_env_managed_inputs

    managed = active_env_managed_inputs(cfg)
    if managed:
        console.print(
            "[yellow]已开启开机自启动，但检测到环境变量配置，跳过自动补注册："
            f"{', '.join(managed)}。请先写入 config.toml。[/yellow]"
        )
        return
    try:
        autostart.register(cfg)
    except Exception as exc:
        console.print(f"[yellow]开机自启动补注册失败：{exc}[/yellow]")


def _print_section_title(title: str) -> None:
    """渲染一致的章节标题。"""
    console.print(f"[bold cyan]{title}[/bold cyan]")


def _print_placeholder(feature: str, next_step: str = "") -> None:
    """为未完成的命令渲染统一的占位面板。"""
    body = "功能开发中"
    if next_step:
        body = f"{body}\n[dim]下一步：{next_step}[/dim]"
    _print_page_title(feature)
    _print_status_panel("stub", "开发中", body)


async def _run_with_progress(
    coro: Any,
    *,
    label: str,
    eta_seconds: int,
    tick_seconds: int = 20,
) -> Any:
    """运行一个协程并周期性打印进度更新。

    init 的 LLM 密集阶段（analyze_events、build_initial_profile、
    discover）每个都要 1-5 分钟在 deepseek thinking 上静默等待。
    没有心跳用户就无法判断进程是活着还是卡住了。该助手会打印
    一行"已启动，预计 X 秒"，在工作运行期间每 ``tick_seconds``
    秒按 已用/预计 节拍打印一次，最后用实际墙钟时间打印一行
    完成提示。
    """
    import time as _time
    from contextlib import suppress as _suppress

    console.print(f"  [dim]→ {label}（预计 ~{eta_seconds}s）[/dim]")
    start = _time.monotonic()

    async def _ticker() -> None:
        while True:
            await asyncio.sleep(tick_seconds)
            elapsed = int(_time.monotonic() - start)
            remaining = max(0, eta_seconds - elapsed)
            console.print(f"  [dim]· {label}: 已用 {elapsed}s / 预计还需 ~{remaining}s[/dim]")

    ticker_task = asyncio.create_task(_ticker())
    try:
        result = await coro
    finally:
        ticker_task.cancel()
        with _suppress(asyncio.CancelledError, BaseException):
            await ticker_task
    elapsed = int(_time.monotonic() - start)
    console.print(f"  [green][OK][/green] {label} 用时 {elapsed}s")
    return result


def _print_recommendation_card(item: Any, index: int) -> None:
    """以卡片样式渲染单条推荐。"""
    rows = [
        ("标题", item.content.title or "（暂无）"),
        ("UP 主", item.content.up_name or "（未知）"),
    ]
    if item.topic_label:
        rows.append(("话题标签", item.topic_label))
    rows.extend(
        [
            ("推荐理由", item.expression or "（暂无）"),
            ("BV号", item.content.bvid or "（暂无）"),
        ]
    )
    _print_key_value_table(f"推荐 {index}", rows)


def _print_discovered_content_preview(item: Any, index: int) -> None:
    """渲染单条发现内容预览行。"""
    _print_key_value_table(
        f"发现 {index}",
        [
            ("标题", item.title or "（暂无）"),
            ("UP 主", item.up_name or "（未知）"),
            ("来源策略", item.source_strategy or "（未知）"),
            ("相关性分数", f"{float(item.relevance_score or 0.0):.2f}"),
        ],
    )


def _initialize_logging(log_level_override: str | None = None) -> None:
    """加载配置并初始化日志系统。

    当通过 ``logs-prune`` 命令调用时跳过启动时的非托管日志清理——
    该命令的全部意义就是让用户检查/控制清理，所以在回调内
    触发自动清理会破坏 dry-run 契约。
    """
    import sys

    from openbiliclaw.config import load_config
    from openbiliclaw.logging_setup import configure_logging

    config = load_config()
    skip_sweep = "logs-prune" in sys.argv
    configure_logging(
        config,
        console_level_override=log_level_override,
        sweep_unmanaged=not skip_sweep,
    )


def _build_registry() -> Any:
    """构建已配置的 LLM registry。"""
    from openbiliclaw.config import load_config
    from openbiliclaw.llm import build_llm_registry

    return build_llm_registry(load_config())


def _build_auth_manager() -> Any:
    """构建已配置的 Bilibili auth 管理器。"""
    from openbiliclaw.bilibili.auth import AuthManager
    from openbiliclaw.config import load_config

    return AuthManager(load_config().data_path)


def _build_browser() -> Any:
    """构建已配置的 Bilibili 浏览器集成。"""
    from openbiliclaw.bilibili.auth import resolve_runtime_cookie
    from openbiliclaw.bilibili.browser import BilibiliBrowser
    from openbiliclaw.config import load_config

    config = load_config()
    return BilibiliBrowser(
        executable=config.bilibili.browser_executable,
        headed=config.bilibili.browser_headed,
        cookie=resolve_runtime_cookie(
            data_dir=config.data_path,
            configured_cookie=config.bilibili.cookie,
        ),
    )


def _build_bilibili_client() -> Any:
    """构建已配置的 Bilibili API 客户端。"""
    from openbiliclaw.bilibili.api import BilibiliAPIClient
    from openbiliclaw.bilibili.auth import resolve_runtime_cookie
    from openbiliclaw.config import load_config

    config = load_config()
    return BilibiliAPIClient(
        cookie=resolve_runtime_cookie(
            data_dir=config.data_path,
            configured_cookie=config.bilibili.cookie,
        )
    )


def _build_soul_engine() -> Any:
    """构建已配置的 soul 引擎并初始化记忆存储。"""
    from openbiliclaw.config import load_config
    from openbiliclaw.llm.service import module_overrides_from_config
    from openbiliclaw.soul.engine import SoulEngine

    class _UnavailableLLM:
        default_provider = ""

        def is_chat_capable(self, _name: str) -> bool:
            return False

        async def complete(self, *args: Any, **kwargs: Any) -> Any:
            raise RuntimeError("LLM registry is unavailable for this command.")

        async def complete_provider(self, *args: Any, **kwargs: Any) -> Any:
            raise RuntimeError("LLM registry is unavailable for this command.")

    cfg = load_config()
    memory = _build_memory_manager()
    try:
        llm = _build_registry()
    except Exception:
        llm = _UnavailableLLM()
    return SoulEngine(
        llm=llm,
        memory=memory,
        usage_recorder=_build_usage_recorder(),
        satisfaction_filter_enabled=cfg.soul.preference.satisfaction_filter_enabled,
        module_overrides=module_overrides_from_config(cfg),
        llm_concurrency=cfg.llm.concurrency,
        speculation_interval_minutes=cfg.scheduler.speculation_interval_minutes,
        speculation_ttl_days=cfg.scheduler.speculation_ttl_days,
        speculation_cooldown_days=cfg.scheduler.speculation_cooldown_days,
        speculation_confirmation_threshold=cfg.scheduler.speculation_confirmation_threshold,
        speculation_max_active=cfg.scheduler.speculation_max_active,
        speculation_max_primary_interests=cfg.scheduler.speculation_max_primary_interests,
        speculation_max_secondary_interests=cfg.scheduler.speculation_max_secondary_interests,
        avoidance_speculation_interval_minutes=(
            cfg.scheduler.avoidance_speculation_interval_minutes
        ),
        avoidance_speculation_ttl_days=cfg.scheduler.avoidance_speculation_ttl_days,
        avoidance_speculation_cooldown_days=cfg.scheduler.avoidance_speculation_cooldown_days,
        avoidance_speculation_confirmation_threshold=(
            cfg.scheduler.avoidance_speculation_confirmation_threshold
        ),
        avoidance_speculation_max_active=cfg.scheduler.avoidance_speculation_max_active,
        speculator_idle_interval_minutes=cfg.scheduler.speculator_idle_interval_minutes,
        profile_consolidation_enabled=cfg.scheduler.profile_consolidation_enabled,
        profile_consolidation_interval_hours=(cfg.scheduler.profile_consolidation_interval_hours),
        profile_consolidation_like_target_upper=(
            cfg.scheduler.profile_consolidation_like_target_upper
        ),
        profile_consolidation_like_target_soft=cfg.scheduler.profile_consolidation_like_target_soft,
        profile_consolidation_archive_enabled=(cfg.scheduler.profile_consolidation_archive_enabled),
    )


def _build_recommendation_engine() -> Any:
    """构建带核心记忆感知 LLM 访问的推荐引擎。"""
    from openbiliclaw.config import load_config
    from openbiliclaw.llm.service import LLMService, module_overrides_from_config
    from openbiliclaw.recommendation.engine import (
        RecommendationEngine,
        SupportsEmbeddingService,
    )

    memory = _build_memory_manager()
    database = _get_runtime_database()
    cfg = load_config()
    registry = _build_registry()
    llm_service = LLMService(
        registry=registry,
        memory=memory,
        usage_recorder=_build_usage_recorder(),
        module_overrides=module_overrides_from_config(cfg),
        concurrency=cfg.llm.concurrency,
    )
    from openbiliclaw.llm.registry import build_embedding_service

    _emb = build_embedding_service(cfg, registry)
    embedding_service = cast("SupportsEmbeddingService | None", _emb)

    def _xhs_self_info_provider() -> dict[str, object] | None:
        state = memory.load_discovery_runtime_state()
        info = state.get("xhs_self_info")
        return info if isinstance(info, dict) else None

    return RecommendationEngine(
        llm=llm_service,
        database=database,
        embedding_service=embedding_service,
        xhs_self_info_provider=_xhs_self_info_provider,
    )


def _build_dialogue(soul_engine: Any) -> Any:
    """构建用于交互式聊天的 Socratic 对话助手。"""
    from openbiliclaw.soul.dialogue import SocraticDialogue

    return SocraticDialogue(llm=_build_registry(), soul_engine=soul_engine, session="cli")


def _run_api_server(*, host: str = "127.0.0.1", port: int = 8420) -> None:
    """运行浏览器扩展使用的本地 FastAPI 服务。"""
    import uvicorn

    from openbiliclaw.api.app import create_app

    api_app = create_app()
    state = getattr(api_app, "state", None)
    if bool(getattr(state, "degraded", False)):
        issues = []
        for issue in list(getattr(state, "degraded_issues", [])):
            field = str(getattr(issue, "field", ""))
            message = str(getattr(issue, "message", issue))
            issues.append(f"- {field}: {message}" if field else f"- {message}")
        reason = str(getattr(state, "degraded_reason", ""))
        body = (
            f"reason: {reason or 'unknown'}\n"
            + "\n".join(issues)
            + "\n\nOpen the extension popup settings to fix the LLM credentials, "
            "then restart the daemon."
        )
        _print_status_panel("warning", "降级模式 / Degraded mode", body)
    uvicorn.run(api_app, host=host, port=port, log_level="info")


def _build_memory_manager() -> Any:
    """构建已初始化的、用于事件写入的 memory 管理器。"""
    from openbiliclaw.config import load_config
    from openbiliclaw.memory.manager import MemoryManager

    cached = _RUNTIME_COMPONENTS.get("memory_manager")
    if cached is not None:
        return cached

    config = load_config()
    memory = MemoryManager(config.data_path, database=_get_runtime_database())
    memory.initialize()
    _RUNTIME_COMPONENTS["memory_manager"] = memory
    return memory


def _build_discovery_engine() -> Any:
    """构建带当前已实现策略的 discovery 引擎。"""
    from openbiliclaw.discovery.engine import (
        ContentDiscoveryEngine,
        DiscoveryConcurrencyController,
    )
    from openbiliclaw.discovery.strategies.strategies import (
        ExploreStrategy,
        RelatedChainStrategy,
        SearchStrategy,
        TrendingStrategy,
    )
    from openbiliclaw.llm.service import LLMService, module_overrides_from_config

    memory = _build_memory_manager()
    database = _get_runtime_database()
    bilibili_client = _build_bilibili_client()
    from openbiliclaw.config import load_config

    cfg = load_config()
    registry = _build_registry()
    llm_service = LLMService(
        registry=registry,
        memory=memory,
        usage_recorder=_build_usage_recorder(),
        module_overrides=module_overrides_from_config(cfg),
        concurrency=cfg.llm.concurrency,
    )
    concurrency = DiscoveryConcurrencyController(
        bilibili_request_concurrency=2,
        # 继承 dataclass 默认值（当前为 32）——大小恰好让一次 init
        # discover 的约 32 个批次全部并发扇出，而不是排队在紧 cap 后面。
        # 详见 engine.py 中的设计依据。
    )

    # 根据配置构建 embedding 服务（可选）
    from openbiliclaw.llm.registry import build_embedding_service

    embedding_service = build_embedding_service(cfg, registry)
    discovery_cfg = getattr(cfg, "discovery", None)

    engine = ContentDiscoveryEngine(
        llm_service=llm_service,
        database=database,
        concurrency=concurrency,
        embedding_service=embedding_service,
        multimodal_evaluation_enabled=bool(
            getattr(discovery_cfg, "multimodal_evaluation_enabled", False)
        ),
        multimodal_batch_size=int(getattr(discovery_cfg, "multimodal_batch_size", 8)),
        multimodal_image_max_px=int(getattr(discovery_cfg, "multimodal_image_max_px", 384)),
        multimodal_image_quality=int(getattr(discovery_cfg, "multimodal_image_quality", 72)),
        multimodal_image_timeout_seconds=int(
            getattr(discovery_cfg, "multimodal_image_timeout_seconds", 6)
        ),
    )
    search_strategy = SearchStrategy(
        llm_service=llm_service,
        bilibili_client=bilibili_client,
        concurrency=concurrency,
        database=database,
        embedding_service=embedding_service,
    )
    trending_strategy = TrendingStrategy(
        bilibili_client=bilibili_client,
        llm_service=llm_service,
        concurrency=concurrency,
        database=database,
        embedding_service=embedding_service,
    )
    related_strategy = RelatedChainStrategy(
        bilibili_client=bilibili_client,
        llm_service=llm_service,
        memory_manager=cast("Any", memory),
        search_strategy=search_strategy,
        trending_strategy=trending_strategy,
        concurrency=concurrency,
        database=database,
    )
    explore_strategy = ExploreStrategy(
        llm_service=llm_service,
        bilibili_client=bilibili_client,
        concurrency=concurrency,
        embedding_service=embedding_service,
        database=database,
    )

    engine.register_strategy(search_strategy)
    engine.register_strategy(trending_strategy)
    engine.register_strategy(related_strategy)
    engine.register_strategy(explore_strategy)
    return engine


def _get_runtime_database() -> Any:
    """构建或返回共享的运行时数据库实例。"""
    cached = _RUNTIME_COMPONENTS.get("database")
    if cached is not None:
        return cached

    from openbiliclaw.config import load_config
    from openbiliclaw.storage.database import Database

    config = load_config()
    database = Database(config.data_path / "openbiliclaw.db")
    database.initialize()
    _RUNTIME_COMPONENTS["database"] = database
    return database


def _build_usage_recorder() -> Any:
    """构建或返回共享的 LLM usage 记录器（cost ledger sink）。

    CLI 命令会自行构造 ``LLMService`` / ``SoulEngine``，
    而不是走 ``runtime_context``，因此没有这个记录器的话
    每次 CLI 运行的 LLM 调用都会在 ``openbiliclaw cost`` 中不可见。
    """
    cached = _RUNTIME_COMPONENTS.get("usage_recorder")
    if cached is not None:
        return cached

    from openbiliclaw.llm.usage_recorder import UsageRecorder

    recorder = UsageRecorder(sink=_get_runtime_database())
    _RUNTIME_COMPONENTS["usage_recorder"] = recorder
    return recorder


def _runtime_database_path() -> Path:
    from openbiliclaw.config import load_config

    config = load_config()
    return config.data_path / "openbiliclaw.db"


def _runtime_backup_dir() -> Path:
    return _runtime_database_path().parent / "backups"


def _maybe_create_runtime_database_backup() -> None:
    from openbiliclaw.storage.maintenance import maybe_create_scheduled_backup

    db_path = _runtime_database_path()
    if not db_path.exists():
        return
    maybe_create_scheduled_backup(db_path, _runtime_backup_dir())


def _ensure_runtime_database_healthy() -> None:
    from openbiliclaw.storage.maintenance import check_database_integrity

    db_path = _runtime_database_path()
    if not db_path.exists():
        return
    report = check_database_integrity(db_path)
    if report.healthy:
        return
    _print_status_panel(
        "error",
        "数据库损坏",
        "检测到本地数据库损坏，请先执行 `openbiliclaw db-repair` 再启动服务。",
    )
    if report.error:
        console.print(report.error)
    raise typer.Exit(code=1)


def _run_db_repair() -> Any:
    from openbiliclaw.storage.maintenance import repair_database

    return repair_database(_runtime_database_path(), backup_dir=_runtime_backup_dir())


def _history_item_to_event(item: dict[str, Any]) -> dict[str, Any]:
    """将 Bilibili 历史记录项归一化为统一的事件层 payload。

    经由 ``build_event()``（v0.3.22+）流转，使产出的 dict 与
    小红书 / 未来数据源事件保持相同 shape，并带 LLM analyzer 可直接
    消费的自然语言 ``context``。
    """
    from openbiliclaw.sources.event_format import SOURCE_BILIBILI, build_event

    history_meta = item.get("history", {})
    if not isinstance(history_meta, dict):
        history_meta = {}
    bvid = str(history_meta.get("bvid", "")).strip()
    title = str(item.get("title", "")).strip()
    author = str(item.get("author_name", item.get("author", ""))).strip()
    view_at = history_meta.get("view_at", item.get("view_at", ""))
    return build_event(
        event_type="view",
        source_platform=SOURCE_BILIBILI,
        title=title,
        url=f"https://www.bilibili.com/video/{bvid}" if bvid else "",
        author=author,
        metadata={
            "bvid": bvid,
            "view_at": view_at,
        },
    )


def _x_tweet_to_event(tweet: dict[str, Any], *, event_type: str) -> dict[str, Any] | None:
    """将 twitter-cli 的 ``tweet_to_dict`` 归一化为统一偏好事件。

    镜像 ``_history_item_to_event``：经由 ``build_event()`` 流转，
    使 X 的点赞 / 收藏与 B 站收藏共享相同事件 shape，并同样喂给
    soul analyzer。``event_type`` 取 ``"like"``（X 点赞）或
    ``"favorite"``（X 收藏）——两者都是显式正向信号。
    对墓碑推文（无 ``id``）返回 ``None``。规范 URL 与 discovery 侧
    （``x_normalize``）一致：``https://x.com/<handle>/status/<id>``。
    """
    from openbiliclaw.sources.event_format import SOURCE_TWITTER, build_event

    tweet_id = str(tweet.get("id", "") or "").strip()
    if not tweet_id:
        return None
    raw_author = tweet.get("author")
    author = raw_author if isinstance(raw_author, dict) else {}
    screen_name = str(author.get("screenName", "") or "").strip()
    author_name = f"@{screen_name}" if screen_name else str(author.get("name", "") or "").strip()
    handle = screen_name or "i"  # x.com/i/status/<id> resolves without a handle
    text = str(tweet.get("articleText") or tweet.get("text") or "").strip()
    first_line = text.splitlines()[0] if text else ""
    title = first_line[:140]
    verb = "点赞" if event_type == "like" else "收藏"
    if title and author_name:
        context = f"在 X {verb}了 {author_name} 的推文:{title}"
    elif title:
        context = f"在 X {verb}了一条推文:{title}"
    else:
        context = f"在 X {verb}了一条推文"
    return build_event(
        event_type=event_type,
        source_platform=SOURCE_TWITTER,
        title=title,
        url=f"https://x.com/{handle}/status/{tweet_id}",
        author=author_name,
        context=context,
        metadata={
            "tweet_id": tweet_id,
            "screen_name": screen_name,
            "body_text": text,
        },
    )


@app.callback()
def main(log_level: str | None = typer.Option(None, "--log-level")) -> None:
    """全局 CLI 选项。"""
    _APP_CONTEXT["log_level"] = log_level
    _bootstrap_container_runtime()
    _initialize_logging(log_level_override=log_level)


def _print_config_guidance(messages: list[str]) -> None:
    """以一致的方式渲染配置提示。"""
    if not messages:
        return
    console.print("[bold yellow]配置提示[/bold yellow]")
    for message in messages:
        console.print(f"  - {message}")


def _print_auth_status(status: Any) -> None:
    """一致地渲染认证状态。"""
    state_label = "已认证" if status.authenticated else "未认证"
    _print_page_title("认证概览", "B站认证状态")
    rows = [
        ("状态", state_label),
        ("Cookie 文件", str(status.cookie_path)),
    ]
    if status.username:
        rows.append(("用户名", str(status.username)))
    if status.user_id:
        rows.append(("UID", str(status.user_id)))
    if status.message:
        rows.append(("说明", str(status.message)))
    _print_key_value_table("认证信息", rows)


def _print_browser_status(browser: Any) -> None:
    """渲染浏览器安装状态。"""
    availability = "已安装" if browser.is_available else "未安装"
    _print_page_title("浏览器集成状态", "agent-browser 状态")
    _print_key_value_table(
        "浏览器信息",
        [
            ("状态", availability),
            ("可执行文件", str(browser.executable)),
        ],
    )


def _require_runtime_config() -> None:
    """运行时配置不完整时以清晰消息退出。"""
    error = _load_runtime_config_error()
    if error is not None:
        raise typer.Exit(code=1)


def _print_runtime_config_error(error: str, hints: list[str] | None = None) -> None:
    """一致地渲染运行时配置错误。"""
    console.print("[bold red]配置错误[/bold red]")
    _print_config_guidance(hints or [])
    console.print(f"  {error}")


def _load_runtime_config_error(*, render: bool = True) -> str | None:
    """返回面向用户的运行时配置错误，并可选地打印指引。"""
    from openbiliclaw.config import (
        ConfigError,
        load_config_with_diagnostics,
        validate_runtime_config,
    )

    config, diagnostics = load_config_with_diagnostics()
    try:
        validate_runtime_config(config)
    except ConfigError as exc:
        hints = diagnostics.messages + [
            f"{issue.field}: {issue.message}" for issue in diagnostics.issues
        ]
        if render:
            _print_runtime_config_error(str(exc), hints)
        return str(exc)
    return None


def _is_interactive_terminal() -> bool:
    """返回当前进程是否连接到交互式 TTY。"""
    return sys.stdin.isatty() and sys.stdout.isatty()


def _save_runtime_provider_config(
    provider: str,
    *,
    api_key: str = "",
    base_url: str = "",
    model: str = "",
) -> None:
    """将所选 provider 的完整配置三元组持久化到 ``config.toml``。

    写入 ``default_provider`` 以及每个 provider 的 ``[llm.<name>]``
    块。``api_key`` / ``base_url`` / ``model`` 仅在非空时写入
    （这样向导中用户接受默认值、留空提示时不会覆盖已保存的值）。
    """
    from openbiliclaw.config import load_config_with_diagnostics, save_config

    config, diagnostics = load_config_with_diagnostics()
    config.llm.default_provider = provider
    provider_config = getattr(config.llm, provider, None)
    if provider_config is None:
        save_config(config, diagnostics.config_path)
        return
    if api_key and hasattr(provider_config, "api_key"):
        provider_config.api_key = api_key.strip()
    if base_url and hasattr(provider_config, "base_url"):
        provider_config.base_url = base_url.strip()
    if model and hasattr(provider_config, "model"):
        provider_config.model = model.strip()
    save_config(config, diagnostics.config_path)


# 每个 provider 的默认 base_url + chat 模型。用户总可以在向导里
# 覆盖二者；这里只是"我选了 X，默认应该是什么样？"的答案。
# 最近刷新 2026-05。当某 provider 推出新旗舰时，
# 同步更新此处的 model 字段以及对应的 ``_LLM_MENU`` /
# ``_PROVIDER_MODEL_HINT`` 条目。
_PROVIDER_DEFAULTS: dict[str, dict[str, str]] = {
    # OpenAI：gpt-4o-mini 已于 2026 年 2 月从 ChatGPT 退役；
    # gpt-5-nano 是当前最便宜的代际（$0.05 / $0.40 每 1M）。
    "openai": {"base_url": "https://api.openai.com/v1", "model": "gpt-5-nano"},
    # Claude：Sonnet 4.6 是当前主流 Sonnet（1M 上下文）。
    # Opus 4.7 是顶配；Haiku 4.5 是经济款。
    "claude": {"base_url": "", "model": "claude-sonnet-4-6"},
    # Gemini：2.5-flash 是稳定的默认经济款（3-flash 是预览版；
    # 3.1-pro 是推理旗舰）。
    "gemini": {"base_url": "", "model": "gemini-2.5-flash"},
    # DeepSeek：V4 系列。deepseek-chat / deepseek-reasoner
    # 于 2026-07-24 弃用。
    "deepseek": {"base_url": "https://api.deepseek.com", "model": "deepseek-v4-flash"},
    # Ollama：项目以中文为主；qwen2.5:7b 处理中文明显优于
    # 同尺寸的 llama3。
    "ollama": {"base_url": "http://localhost:11434/v1", "model": "qwen2.5:7b"},
    # OpenRouter：默认路由到 OpenAI 最便宜的当前代际。
    "openrouter": {"base_url": "https://openrouter.ai/api/v1", "model": "openai/gpt-5-nano"},
}


_PROVIDER_HINTS: dict[str, str] = {
    "openai": "OpenAI 官方（api.openai.com）",
    "claude": "Anthropic Claude 官方",
    "gemini": "Google Gemini 官方",
    "deepseek": "DeepSeek 官方（OpenAI 兼容协议）",
    "ollama": "本地 Ollama（无需 Key）",
    "openrouter": "OpenRouter 聚合",
}


# 在模型提示之前显示的一行简介，让用户知道实际可选项，
# 而不是确认一个不透明的字符串。
# 列出每个 provider 的当前主流模型名——当某 provider 弃用 /
# 重命名模型时刷新。
_PROVIDER_MODEL_HINT: dict[str, str] = {
    "deepseek": (
        "可选模型: deepseek-v4-flash (默认 / 便宜) / deepseek-v4-pro (更强)。"
        "旧名 deepseek-chat / deepseek-reasoner 将于 2026/07/24 弃用"
    ),
    "openai": (
        "可选模型: gpt-5-nano (默认 / 最便宜) / gpt-5.4-nano / "
        "gpt-5.4-mini / gpt-5.5 (旗舰 4/2026) / gpt-5.5-pro (高精度)。"
        "gpt-4o / gpt-4o-mini 已从 ChatGPT 退役,API 仍可调"
    ),
    "gemini": (
        "可选模型: gemini-2.5-flash (默认 / 稳定) / "
        "gemini-3-flash-preview (新一代 / 推理强) / "
        "gemini-3.1-pro-preview (旗舰 / Public Preview, 需付费项目) / "
        "gemini-3.1-flash-lite-preview (最便宜)"
    ),
    "claude": (
        "可选模型: claude-sonnet-4-6 (默认 / 1M 上下文) / "
        "claude-haiku-4-5 (便宜) / claude-opus-4-7 (旗舰 / agentic 最强)。"
        "claude-sonnet-4-5 仍可调"
    ),
    "openrouter": (
        "默认 openai/gpt-5-nano。OpenRouter 模型名格式: <vendor>/<model>,"
        "如 anthropic/claude-sonnet-4-6 / google/gemini-2.5-flash"
    ),
    "ollama": (
        "常见模型: qwen2.5:7b (默认 / 中文好) / llama3.2 (Meta 新版) / "
        "gemma2 (Google) / mistral (轻量) / deepseek-r1 (开源推理)。"
        "模型名要和 Ollama 库里完全一致 (`ollama list` 看)"
    ),
}


# 子菜单：当用户在 _LLM_MENU 中选 "OpenAI 协议兼容自建网关" 时显示。
# 顺序 = 菜单顺序。每条都预填了 base_url，省得用户去文档里翻找；
# default_model 是合理起点，但提示仍允许用户修改。``hint``
# 是一行简介，显示在模型提示正上方，列出该服务当前真实的主流模型。
#
# 新增 compat-protocol 厂商时：
# 1. 验证它真正使用 OpenAI Chat Completions 协议（Bearer
#    auth + ``/v1/chat/completions`` shape）。很多 "OpenAI 兼容"
#    API 在 tools / streaming / function_call 格式上略有出入——
#    上架前先做一次 smoke call。
# 2. 选一个有代表性的低价 default_model，让用户默认获得便宜体验；
#    高级用户可在 Phase 2 切换。
#
# 顺序依据（2026-05）：OpenAI 协议兼容菜单的真实主要用途是接入
# 中转站 / OneAPI / 团队 LLM 网关 key——用户已经从某中转商买好访问权，
# 只是想让 OpenBiliClaw 跟它对话。这就是 ``relay`` 是默认（#1）的原因。
# 国产厂商原生 API（Kimi / MiniMax / Qwen / GLM / Yi）紧随其后，因为
# 部分用户确实直接用厂商 API；Azure 和自建是企业 / 玩家向变体；
# ``custom`` 是手动逃生口。
_OPENAI_COMPAT_PRESETS: tuple[tuple[str, dict[str, str]], ...] = (
    (
        "relay",
        {
            "label": "[ICON] 中转站 / OneAPI / 公司团队 LLM 网关 (大多数人选这个)",
            "description": (
                "中转站 = 第三方代理 OpenAI / Claude 的二级商家(国内付人民币用海外模型)。"
                "OneAPI / 团队 LLM 网关 = 公司自建的多模型聚合 + 计费 + 限流网关。"
                "买中转站 Key 的人选这个就对了"
            ),
            "signup_url": (
                "找你充值的那家中转站官网拿 Key (它们大多有自己的 base_url 和文档)。"
                "OneAPI 是开源自建项目: https://github.com/songquanpeng/one-api"
            ),
            "supports_embedding": "true",  # most relay services proxy embeddings too
            "base_url": "",  # user-supplied — every relay has its own
            "default_model": "gpt-5-nano",
            "hint": (
                "看你中转站后端代理到哪个真实模型。中转站 / OneAPI 通常代理 "
                "OpenAI (gpt-5-nano / gpt-5.4-mini / gpt-5.5) 或 "
                "Claude (claude-sonnet-4-6 / claude-opus-4-7) 或国产模型,"
                "按你充值的那家给你的模型清单填"
            ),
            "embedding_alt": (
                "中转站通常也代理 OpenAI text-embedding-3-small,"
                "Phase 3 高级选项里可以指向同一个 base_url"
            ),
        },
    ),
    (
        "kimi",
        {
            "label": "Kimi (Moonshot AI 月之暗面) 官方",
            "description": (
                "国产长上下文老牌 (256K ctx),长文档理解 / 网页爬阅 / "
                "学术阅读这些场景表现好,日常对话也稳。直接从 Moonshot 官方拿 Key"
            ),
            "signup_url": (
                "https://platform.moonshot.cn/console/api-keys （国内）/ "
                "https://platform.moonshot.ai （国际）"
            ),
            "supports_embedding": "false",
            "base_url": "https://api.moonshot.ai/v1",
            "default_model": "kimi-k2.6",
            "hint": (
                "kimi-k2.6 (默认 / 最新 / 256K 上下文 / 多模态) / kimi-k2.5。"
                "旧 moonshot-v1-* 和 K2-series 即将停服(K2 系列 2026-05-25 停)"
            ),
            "domain_alt": (
                "国内用户也可改 base_url 为 https://api.moonshot.cn/v1 (域名不同,Key 通用)"
            ),
        },
    ),
    (
        "minimax",
        {
            "label": "MiniMax 官方",
            "description": (
                "国产代码 / agent 场景的当前 SOTA 之一 (M2.7 在 SWE-Bench 上 80%+),"
                "便宜 ($0.30 / $1.20 per M),适合做推荐这种结构化输出任务"
            ),
            "signup_url": (
                "https://platform.minimaxi.com/user-center/basic-information/interface-key "
                "（国内）/ https://platform.minimax.io （国际）"
            ),
            "supports_embedding": "false",
            "base_url": "https://api.minimax.io/v1",
            "default_model": "MiniMax-M2.7",
            "hint": (
                "MiniMax-M2.7 (默认 / 最新 / 4-2026 / 228K ctx) / "
                "MiniMax-M2.5 / MiniMax-M2.1。"
                "旧 abab 系列 (abab6.5*) 已被 M 系列替代"
            ),
            "domain_alt": (
                "国内用户改 base_url 为 https://api.minimaxi.com/v1 (旧 .chat 域名将停)"
            ),
        },
    ),
    (
        "qwen",
        {
            "label": "通义千问 (阿里 DashScope) 官方",
            "description": (
                "阿里出品,中文最强档之一 (qwen3.6 系列),qwen-plus 别名"
                "自动跟最新快照,无需手动升级。免费档调用次数有限,商用记得充值"
            ),
            "signup_url": "https://bailian.console.aliyun.com/?apiKey=1#/api-key",
            "supports_embedding": "true",
            "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "default_model": "qwen-plus",
            "hint": (
                "qwen-flash (最便宜) / qwen-plus (默认 / 平衡) / qwen-max (旗舰)。"
                "都是别名,自动跟最新快照(当前 → qwen3.6-*, 2026-04 系列)"
            ),
            "embedding_alt": "DashScope 也支持 text-embedding-v3 (Phase 3 高级选项里可选)",
        },
    ),
    (
        "zhipu",
        {
            "label": "智谱 ChatGLM 官方",
            "description": (
                "清华 + 智谱出品。GLM-4.7-Flash 完全免费(每天调用次数限制),"
                "做推荐 / 画像够用;GLM-5 是付费旗舰 (745B MoE,Claude Opus 级)"
            ),
            "signup_url": "https://www.bigmodel.cn/usercenter/proj-mgmt/apikeys",
            "supports_embedding": "true",
            "base_url": "https://open.bigmodel.cn/api/paas/v4",
            "default_model": "glm-4.7-flash",
            "hint": (
                "glm-4.7-flash (默认 / 免费 / 200K ctx) / glm-5 (付费旗舰 / 4/2026 / 745B MoE) / "
                "glm-4.6。注意: base_url 是 /api/paas/v4 不是 /v1"
            ),
            "embedding_alt": "智谱也有 embedding-3 (Phase 3 高级选项里可选)",
        },
    ),
    (
        "yi",
        {
            "label": "零一万物 (Yi) 官方",
            "description": (
                "李开复创业团队出品,Yi-Large 在 LMSYS 中文榜常年 top 国产之一。"
                "yi-medium 平衡好用,yi-spark 最便宜适合高频小任务"
            ),
            "signup_url": "https://platform.lingyiwanwu.com/apikeys",
            "supports_embedding": "false",
            "base_url": "https://api.lingyiwanwu.com/v1",
            "default_model": "yi-medium",
            "hint": (
                "yi-spark (最便宜) / yi-medium (默认 / 平衡) / yi-lightning (新 / 快) / "
                "yi-large (旗舰) / yi-large-turbo (平衡) / yi-medium-200k (长上下文)"
            ),
        },
    ),
    (
        "azure",
        {
            "label": "Azure OpenAI",
            "description": (
                "微软的 OpenAI 企业版。和 OpenAI 官方模型一致,但鉴权 / 模型名 / "
                "endpoint 都按 Azure 的 deployment 模式走。多用于企业合规场景"
            ),
            "signup_url": (
                "Azure portal → 创建 OpenAI resource → 创建 deployment → "
                "Keys & Endpoint 取 KEY 和 ENDPOINT"
            ),
            "supports_embedding": "true",
            "base_url": "https://YOUR-RESOURCE.openai.azure.com/openai/deployments/YOUR-DEPLOYMENT",
            "default_model": "",
            "hint": (
                "Azure 模型名 = 你创建 deployment 时指定的 deployment name(不是底层 gpt-5)。"
                "Base URL 把 YOUR-RESOURCE / YOUR-DEPLOYMENT 替换成你自己的"
            ),
            "embedding_alt": (
                "Azure 上 embedding 模型也是单独 deployment,Phase 3 时再起一个 deployment "
                "并填那个的 endpoint"
            ),
        },
    ),
    (
        "self-hosted",
        {
            "label": "自建 vLLM / LMStudio / Ollama 网关",
            "description": (
                "你自己跑的 LLM 服务,常见: vLLM (多卡推理) / LMStudio (Mac M-series) / "
                "Ollama 的 OpenAI 兼容 shim。免费但要自备硬件"
            ),
            "signup_url": "无 (本地服务通常不需要 Key,鉴权可留空)",
            "supports_embedding": "false",  # depends — assume no
            "base_url": "http://localhost:8000/v1",
            "default_model": "",  # force user to type their deployed model
            "hint": (
                "看你网关上部署的是什么。HuggingFace 路径,如 "
                "meta-llama/Llama-3.3-70B-Instruct / Qwen/Qwen2.5-72B-Instruct / "
                "deepseek-ai/DeepSeek-V3"
            ),
            "embedding_alt": (
                "如果你的 vLLM/LMStudio 也部署了 embedding 模型,Phase 3 高级选项里"
                "可以指向同一个 base_url"
            ),
        },
    ),
    (
        "custom",
        {
            "label": "其它 (完全手填)",
            "description": (
                "上面 8 个都不匹配的兜底选项。任何 OpenAI Chat Completions 协议兼容的服务"
                "都能填(Bearer auth + /v1/chat/completions 形态)"
            ),
            "signup_url": "看你的服务方文档",
            "supports_embedding": "false",  # unknown
            "base_url": "",
            "default_model": "",
            "hint": (
                "Base URL 必须以 /v1 (或网关等价路径)结尾。"
                "模型名得是网关上真实部署 / 提供的那个,写错会 404"
            ),
        },
    ),
)


def _ollama_has_model(model: str, host: str = "http://localhost:11434") -> bool:
    """如果 Ollama 已经拉取过该模型则返回 True。"""
    import httpx

    try:
        with httpx.Client(timeout=5.0, trust_env=False) as client:
            response = client.get(f"{host}/api/tags")
            response.raise_for_status()
            tags = response.json().get("models", [])
            for tag in tags:
                name = str(tag.get("name", "")).strip()
                # 匹配 "bge-m3"、"bge-m3:latest" 等。
                if name == model or name.startswith(f"{model}:"):
                    return True
    except Exception:
        return False
    return False


def _ollama_pull_model(model: str, host: str = "http://localhost:11434") -> bool:
    """从 Ollama 流式拉取模型，并将进度打印到控制台。"""
    import httpx

    try:
        with (
            httpx.Client(timeout=600.0, trust_env=False) as client,
            client.stream(
                "POST",
                f"{host}/api/pull",
                json={"model": model, "stream": True},
            ) as stream,
        ):
            stream.raise_for_status()
            for line in stream.iter_lines():
                if not line:
                    continue
                import json as _json

                try:
                    evt = _json.loads(line)
                except _json.JSONDecodeError:
                    continue
                status = evt.get("status", "")
                if status:
                    console.print(f"  [dim]{status}[/dim]")
                if evt.get("error"):
                    console.print(f"  [red]{evt['error']}[/red]")
                    return False
        return True
    except Exception as exc:
        console.print(f"  [red]拉取失败: {exc}[/red]")
        return False


def _ollama_install_if_missing() -> bool:
    """若未安装 Ollama，则提示通过包管理器自动安装。

    当本调用结束后二进制可用时返回 True。用户可拒绝
    （此时返回 False——调用方应回退为要求用户手动安装）。
    镜像 agent_bootstrap.py 的 install_ollama，但带交互式同意提示，
    因为调用包管理器是用户应当批准的副作用。
    """
    import shutil
    import subprocess

    if shutil.which("ollama"):
        return True

    console.print(
        "[yellow]检测不到 ollama 命令。[/yellow] "
        "OpenBiliClaw 可以帮你装上，过程透明：\n"
        "  • macOS: 通过 brew install ollama\n"
        "  • Windows: 通过 winget install Ollama.Ollama\n"
        "  • Linux: 通过官方 install.sh（curl https://ollama.com/install.sh | sh）"
    )
    if not typer.confirm("是否现在帮你装 Ollama？", default=True):
        console.print(
            "[dim]已跳过自动安装。请手动从 https://ollama.com/download 下载，"
            "然后重新跑一遍本命令。[/dim]"
        )
        return False

    if sys.platform == "darwin":
        if not shutil.which("brew"):
            console.print(
                "[red]没找到 brew。请从 https://ollama.com/download 下载 Mac 安装包，"
                "装好后重新运行本命令。[/red]"
            )
            return False
        subprocess.run(["brew", "install", "ollama"], check=False)
    elif os.name == "nt":
        if not shutil.which("winget"):
            console.print(
                "[red]没找到 winget。请从 https://ollama.com/download 下载 Windows 安装包，"
                "装好后重新运行本命令。[/red]"
            )
            return False
        subprocess.run(
            [
                "winget",
                "install",
                "-e",
                "--id",
                "Ollama.Ollama",
                "--accept-source-agreements",
                "--accept-package-agreements",
            ],
            check=False,
        )
    else:
        # Linux：通过 curl | sh 管道安装——systemd 注册需要 sudo。
        subprocess.run(
            "curl -fsSL https://ollama.com/install.sh | sh",
            shell=True,
            check=False,
        )

    if shutil.which("ollama"):
        console.print("[green]Ollama 安装成功。[/green]")
        return True
    console.print(
        "[red]安装似乎没成功。请从 https://ollama.com/download 手动装一下，再重新跑本命令。[/red]"
    )
    return False


def _save_embedding_config(
    *,
    provider: str,
    model: str,
    base_url: str = "",
    api_key: str = "",
) -> None:
    """将 embedding provider/model 选择持久化到 config.toml。

    对于 OpenAI 兼容 provider，向导可能收集自定义 ``base_url`` /
    ``api_key``（例如一个通过 OpenAI 协议运行 bge-m3 的自托管 vLLM
    网关）。它们被写入 ``[llm.embedding]``，因为 embedding 与 chat
    provider 配置相互独立。
    """
    from openbiliclaw.config import load_config_with_diagnostics, save_config

    config, diagnostics = load_config_with_diagnostics()
    config.llm.embedding.provider = provider
    config.llm.embedding.model = model
    if base_url:
        config.llm.embedding.base_url = base_url.strip()
    elif provider == "ollama" and not config.llm.embedding.base_url.strip():
        config.llm.embedding.base_url = "http://localhost:11434/v1"
    if api_key:
        config.llm.embedding.api_key = api_key.strip()
    save_config(config, diagnostics.config_path)


def _save_module_overrides(overrides: dict[str, dict[str, str]]) -> None:
    """将每模块 LLM 覆盖持久化到 config.toml。

    ``overrides`` 把模块名（``soul`` / ``discovery`` /
    ``recommendation`` / ``evaluation``）映射到一个含可选
    ``provider`` 与 ``model`` 键的 dict。空值以空字符串写入，
    加载器会把空字符串视为"使用全局默认"。
    """
    from openbiliclaw.config import load_config_with_diagnostics, save_config

    config, diagnostics = load_config_with_diagnostics()
    for module, payload in overrides.items():
        module_config = getattr(config.llm, module, None)
        if module_config is None:
            continue
        if "provider" in payload:
            module_config.provider = payload["provider"].strip()
        if "model" in payload:
            module_config.model = payload["model"].strip()
    save_config(config, diagnostics.config_path)


_SUPPORTED_PROVIDERS: tuple[str, ...] = (
    "openai",
    "claude",
    "gemini",
    "deepseek",
    "ollama",
    "openrouter",
)


# Phase 1 显示的编号菜单。顺序有含义（v0.3.20+）：
# DeepSeek 排第一作为零摩擦默认推荐（¥0.001/千 token）；
# OpenAI / Gemini / Claude / OpenRouter 给已有这些 key 的用户；
# Ollama 作为纯离线兜底（CPU 推理慢，硬件门槛真实存在）；
# "OpenAI 协议兼容自建网关" 降级为最后的 "(高级)" 条目，
# 防止普通用户误选——大多数以为自己需要它的人其实需要的是
# 第 2 项（OpenAI 官方）。
_LLM_MENU: tuple[tuple[str, str, str], ...] = (
    (
        "deepseek",
        "DeepSeek 官方 [ICON]默认推荐",
        "默认 deepseek-v4-flash (V4)。¥0.001/千 token 几乎免费,国内可直连",
    ),
    (
        "openai-compat",
        "[ICON] 第二推荐 — 中转站 / OpenAI 协议兼容服务",
        "买了中转站 Key 选这个。也覆盖 Kimi / 通义 / 智谱 / Yi / MiniMax 官方 / Azure / vLLM",
    ),
    (
        "openai",
        "OpenAI 官方",
        "默认 gpt-5-nano (最便宜的 GPT-5)。api.openai.com,需要 sk- 开头的 Key",
    ),
    (
        "gemini",
        "Gemini 官方",
        "默认 gemini-2.5-flash (稳定 / 便宜)。Google AI Studio 申请 Key,免费档每天 1500 次够用",
    ),
    (
        "claude",
        "Claude 官方",
        "默认 claude-sonnet-4-6。Anthropic console,按 token 付费,质量高",
    ),
    (
        "openrouter",
        "OpenRouter 聚合",
        "默认 openai/gpt-5-nano。一个 Key 跑多家模型,按调用计费",
    ),
    (
        "ollama",
        "本地 Ollama（完全离线）",
        "默认 qwen2.5:7b (中文好)。不要 Key / 完全免费,但需 16GB+ 内存,CPU 推理首次响应 10-60s",
    ),
)


def _print_provider_table() -> None:
    """渲染 provider 菜单 —— DeepSeek 为默认,协议兼容其次(v0.3.27+)。"""
    console.print("[bold]OpenBiliClaw 需要一个语言模型来理解你的兴趣、写推荐文案。[/bold]")
    console.print("请选一个 LLM 服务：\n")
    table = Table(show_lines=False, show_header=True)
    table.add_column("#", style="cyan", no_wrap=True)
    table.add_column("名称", no_wrap=True)
    table.add_column("说明")
    for index, (_, label, hint) in enumerate(_LLM_MENU, start=1):
        table.add_row(str(index), label, hint)
    console.print(table)
    console.print(
        "[dim]Tip:不确定就选 1 (DeepSeek),¥0.001/千 token 几乎免费,月度通常 ¥0.5-2。"
        "已经买了中转站 / OneAPI Key 选 2 (协议兼容);想完全离线选 7 (Ollama,但 CPU 推理慢)。[/dim]"
    )


def _resolve_menu_choice(raw: str) -> str | None:
    """把 Phase 1 菜单输入映射到规范 choice key。

    接受序号（1..N）或直接键入的规范名（如 "ollama" 或
    "openai-compat"）。未知输入返回 None。
    """
    raw = raw.strip().lower()
    if raw.isdigit():
        index = int(raw)
        if 1 <= index <= len(_LLM_MENU):
            return _LLM_MENU[index - 1][0]
        return None
    aliases = {
        "openai-compat": "openai-compat",
        "compat": "openai-compat",
        "openai兼容": "openai-compat",
    }
    if raw in aliases:
        return aliases[raw]
    if raw in {key for key, *_ in _LLM_MENU}:
        return raw
    return None


def _prompt_openai_compat() -> tuple[str, str, str, str]:
    """openai-compat 子流程 —— 预设菜单 → 简介 → base_url → key → model → embedding 提示。

    所有 compat-protocol 服务都写入 ``[llm.openai]`` 段
    （``openai_provider.OpenAIProvider`` 类是通用的 Bearer-auth +
    ``/v1/chat/completions`` 客户端）。子菜单的作用是消除普通用户自配时
    踩到的四个痛点：

    1. **去哪注册** —— 每个预设都在 API Key 提示上方显示
       ``signup_url``，用户可 ``cmd-click`` 打开。
    2. **这玩意到底是啥** —— 选完预设后 ``description`` 作为一段简介
       展示，框定该服务的强项与适用场景，让用户知道选了什么。
    3. **Base URL 格式** —— 由预设自动填好；用户确认即可。
    4. **没有 embedding 端点** —— Kimi / MiniMax / Yi / 自建都不提供
       embedding，因此我们提前告知 Phase 3 会回退到本地 Ollama bge-m3。
       对 Qwen / GLM / Azure / 中转站（确实有 embedding）则提示
       Phase 3 的高级选项可指向同一个 base_url。
    """
    console.print(
        "\n[bold]配置 OpenAI 协议兼容服务[/bold]\n"
        "[dim]这一项主要给三类用户:[/dim]\n"
        "[dim]  1. **买了中转站 / OneAPI Key**(国内付人民币用海外模型,最常见)→ 选 1[/dim]\n"
        "[dim]  2. **用国产大模型官方 API**(Kimi / 通义 / 智谱 / Yi / MiniMax) → 选 2-6[/dim]\n"
        "[dim]  3. **企业 Azure / 自建 vLLM-LMStudio** → 选 7-8[/dim]\n"
        r"[dim]后端会按 OpenAI 协议(Bearer 鉴权 + /v1/chat/completions)打你给的 Base URL,"
        r"配置统一写到 config.toml 的 \[llm.openai] 段。[/dim]\n"
    )
    table = Table(show_lines=False, show_header=True)
    table.add_column("#", style="cyan", no_wrap=True)
    table.add_column("服务", no_wrap=True)
    table.add_column("Base URL")
    table.add_column("默认模型")
    for index, (_, preset) in enumerate(_OPENAI_COMPAT_PRESETS, start=1):
        bu = preset["base_url"] or "[dim](需自填)[/dim]"
        dm = preset["default_model"] or "[dim](需自填)[/dim]"
        table.add_row(str(index), preset["label"], bu, dm)
    console.print(table)
    console.print(
        "[dim]Tip: 不知道选哪个就看你的 API Key 是哪家发的—— "
        "买的中转站 / OneAPI(常见)选 1;Kimi/MiniMax/通义/智谱/Yi 官方选 2-6;"
        "Azure 选 7;自建本地服务选 8。[/dim]\n"
    )
    raw = typer.prompt(f"选服务类型 (1-{len(_OPENAI_COMPAT_PRESETS)})", default="1").strip()
    try:
        choice_index = max(1, min(len(_OPENAI_COMPAT_PRESETS), int(raw))) - 1
    except ValueError:
        choice_index = 0
    preset_key, preset = _OPENAI_COMPAT_PRESETS[choice_index]

    # 每个预设的简介：这个服务是什么、去哪注册。
    console.print(f"\n[bold]→ 已选: {preset['label']}[/bold]")
    if preset.get("description"):
        console.print(f"[dim]  {preset['description']}[/dim]")
    if preset.get("signup_url"):
        console.print(f"[dim]  申请 Key: [cyan]{preset['signup_url']}[/cyan][/dim]")
    if preset.get("domain_alt"):
        console.print(f"[dim]  [TIP] {preset['domain_alt']}[/dim]")
    console.print()

    base_url_default = preset["base_url"]
    if base_url_default:
        base_url = (
            typer.prompt(
                f"Base URL (回车 = {base_url_default})",
                default=base_url_default,
                show_default=False,
            ).strip()
            or base_url_default
        )
    else:
        base_url = typer.prompt(
            "Base URL (必填,见上面的表格)",
        ).strip()

    api_key = typer.prompt(
        f"{preset['label']} 的 API Key (本地 / 不鉴权服务可留空)",
        hide_input=True,
        default="",
        show_default=False,
    ).strip()

    if preset.get("hint"):
        console.print(f"[dim]  {preset['hint']}[/dim]")
    default_model = preset["default_model"]
    if default_model:
        model = (
            typer.prompt(
                f"模型名 (回车 = {default_model})",
                default=default_model,
                show_default=False,
            ).strip()
            or default_model
        )
    else:
        model = typer.prompt("模型名 (必填,见上面的提示)").strip()

    # Embedding 提醒 —— 大多数 compat-protocol 厂商不提供
    # /v1/embeddings 端点。在用户进入 Phase 3 之前预先告警，
    # 以免自动回退时用户以为向导坏了。
    has_embed = preset.get("supports_embedding", "false") == "true"
    if not has_embed:
        console.print(
            f"\n[yellow]ⓘ {preset['label']} 没有 OpenAI 兼容的 embedding endpoint[/yellow]\n"
            "[dim]  Phase 3 会自动选「本地 Ollama bge-m3」给推荐管线做向量化"
            "(免费 / 离线 / 不影响主 LLM)。回车跳过即可。[/dim]"
        )
    elif preset.get("embedding_alt"):
        console.print(f"\n[dim][TIP] embedding 提示: {preset['embedding_alt']}[/dim]")

    # 最终确认：展示规范三元组以便用户察觉错别字。
    console.print(
        f"\n[bold green][OK] 即将写入 config.toml:[/bold green]\n"
        f"  [llm.openai].base_url = [cyan]{base_url}[/cyan]\n"
        f"  [llm.openai].model    = [cyan]{model}[/cyan]"
    )
    return "openai", base_url, api_key, model


def _prompt_provider_triplet(menu_choice: str) -> tuple[str, str, str, str]:
    """Phase 2 —— 为所选 choice 收集 (provider, base_url, api_key, model)。

    ``menu_choice`` 是来自 ``_LLM_MENU`` 的值（如 ``"ollama"`` 或
    ``"openai-compat"``）。对于 ``openai-compat`` 我们仍写入
    ``[llm.openai]`` 段，但强制用户提供 Base URL——这一字段区分了
    "我要用 OpenAI 公司服务" 与 "我有自建网关、用 OpenAI 协议"。
    """
    if menu_choice == "openai-compat":
        return _prompt_openai_compat()

    provider = menu_choice
    defaults = _PROVIDER_DEFAULTS.get(provider, {})
    default_base_url = defaults.get("base_url", "")
    default_model = defaults.get("model", "")

    if provider == "ollama":
        console.print(
            "\n[bold]配置本地 Ollama[/bold]\n"
            "[dim]我会自动帮你装/启动/拉模型，无需 API Key。第一次拉模型可能要"
            "几分钟（取决于网速）。[/dim]"
        )
        # Phase 1：确保二进制存在（缺失则在用户同意下安装）。
        if not _ollama_install_if_missing():
            return provider, default_base_url, "", default_model

        # Phase 2：确保守护进程已启动。
        if not _ollama_start_serve_background():
            console.print("[red]Ollama 已装好但服务没起来。请手动跑 `ollama serve` 后重试。[/red]")
            return provider, default_base_url, "", default_model

        # Phase 3：询问用哪个模型，缺失则拉取。
        ollama_hint = _PROVIDER_MODEL_HINT.get("ollama")
        if ollama_hint:
            console.print(f"[dim]  {ollama_hint}[/dim]")
        model = (
            typer.prompt(
                "选个 Ollama 模型（按回车 = 默认 llama3）",
                default=default_model,
            ).strip()
            or default_model
        )
        if not _ollama_has_model(model):
            console.print(f"开始拉取 {model}（首次下载耗时几分钟）…")
            if not _ollama_pull_model(model):
                console.print(
                    f"[red]{model} 拉取失败。可以稍后手动跑 `ollama pull {model}` "
                    "再重启 backend。[/red]"
                )
        else:
            console.print(f"[green]模型 {model} 已就绪。[/green]")
        return provider, default_base_url, "", model

    # 云端 provider：询问 key（必填），模型回落到默认。
    console.print(f"\n[bold]配置 {_PROVIDER_HINTS.get(provider, provider)}[/bold]")
    api_key = typer.prompt(
        "API Key",
        prompt_suffix=": ",
        hide_input=True,
        default="",
        show_default=False,
    ).strip()
    # 在询问前展示每个 provider 的模型菜单，让用户主动确认默认值，
    # 而不是对着不透明字符串按回车。对 DeepSeek 尤其重要——
    # deepseek-chat / deepseek-reasoner 将于 2026-07-24 弃用。
    model_hint = _PROVIDER_MODEL_HINT.get(provider)
    if model_hint:
        console.print(f"[dim]  {model_hint}[/dim]")
    model = (
        typer.prompt(
            "模型名（直接回车 = 用默认）",
            default=default_model,
            show_default=bool(default_model),
        ).strip()
        or default_model
    )
    return provider, default_base_url, api_key, model


def _interactive_embedding_setup(default_provider: str, *, auto_if_ready: bool = False) -> None:
    """Phase 3 —— embedding 服务（v0.3.20+ "有默认值的取舍提问"）。

    默认 = 1（本地 Ollama bge-m3）。镜像 docs/agent-install.md 中的
    提问形式：每个选项都附 tradeoff 说明，"不确定就回 1"。两条
    高级分支（自定义 OpenAI 兼容端点 / 固定不同 provider）保留但
    弱化展示，以免普通用户被打乱节奏。

    ``auto_if_ready``（v0.3.95+）：当本地 Ollama 已运行且服务着
    bge-m3 时，跳过菜单直接接线启用。这堵上了"已为 chat 确认 Ollama
    但 embedding 仍处于禁用"导致 dedup 静默降级的缺口。只有 ``init``
    会传这个标志——显式的 ``setup-embedding`` 命令保留完整菜单，
    让用户能刻意切换 provider。
    """
    if auto_if_ready and _ollama_is_running() and _ollama_has_model("bge-m3"):
        _save_embedding_config(provider="ollama", model="bge-m3")
        console.print(
            "\n[bold green]检测到本地 Ollama 已就绪且装有 bge-m3,已自动启用本地 embedding"
            "(跨视频去重 / 相似度判定)。[/bold green]"
            "\n[dim]想换成 Gemini/OpenAI 或关闭,去插件设置页或重跑 "
            "`openbiliclaw setup-embedding`。[/dim]"
        )
        return
    console.print(
        "\n[bold]Embedding(向量化)服务[/bold]\n"
        "[dim]把视频标题/简介压成向量,跨视频做相似度对比 —— 决定"
        '"这条和你之前喜欢的那条是不是同一类"。和聊天 LLM 是分开的。[/dim]\n'
    )
    options = (
        (
            "1",
            "本地 Ollama bge-m3 [ICON]默认推荐",
            "免费 / 离线 / 不消耗主 LLM 配额(自动装 Ollama + 拉 568MB 模型)",
        ),
        (
            "2",
            "云端 Gemini embedding",
            "质量略高 / 跨语言更稳;免费档每天 1500 次,日常够用,需 Gemini Key",
        ),
        (
            "3",
            "暂不启用 embedding",
            "保留独立配置为空;不会跟随主 LLM,也不会自动 fallback",
        ),
        ("4", "(高级)自定义 OpenAI 兼容服务", "vLLM / OneAPI / 自建网关 —— 自填 base_url"),
        ("5", "(高级)指定其他 provider", "手动选 provider + 模型 + 可选 base_url"),
        ("0", "跳过(不修改当前 embedding 配置)", ""),
    )
    table = Table(show_lines=False, show_header=True)
    table.add_column("#", style="cyan", no_wrap=True)
    table.add_column("方案", no_wrap=True)
    table.add_column("说明")
    for label, name, desc in options:
        table.add_row(label, name, desc)
    console.print(table)
    console.print(
        "[dim]Tip:不确定就选 1。日常推荐质量已经够用且不消耗主 LLM 配额。"
        "想再准一点选 2(Gemini),需要去 https://aistudio.google.com/apikey 拿 Key。[/dim]"
    )

    choice = typer.prompt("请选择 embedding 方案", default="1").strip()

    if choice in {"0", "skip", "跳过"}:
        console.print("[dim]已跳过 embedding 配置,不修改当前设置。[/dim]")
        return

    if choice in {"1", "ollama", ""}:
        # 自动安装 + 启动 + 拉取。流程与 Phase 1 的 Ollama 分支
        # 一致——共享这些助手，让用户不必为 chat 与 embedding
        # 学两套安装步骤。
        if not _ollama_install_if_missing():
            console.print("[yellow]Ollama 装机失败,未启用本地 embedding。[/yellow]")
            return
        if not _ollama_start_serve_background():
            console.print("[red]Ollama 已装好但服务没起来。请手动跑 `ollama serve` 后重试。[/red]")
            return

        model = "bge-m3"
        if _ollama_has_model(model):
            console.print(f"[green]已检测到本地模型 {model}[/green]")
        else:
            console.print(f"开始拉取 {model}(首次下载约 568MB,几分钟)…")
            if not _ollama_pull_model(model):
                console.print(f"[red]{model} 拉取失败,未启用本地 embedding[/red]")
                return
        _save_embedding_config(provider="ollama", model=model)
        console.print(f"[bold green]已启用本地 Ollama embedding({model})[/bold green]")
        return

    if choice in {"2", "gemini"}:
        from openbiliclaw.config import load_config

        existing_key = ""
        try:
            existing_cfg = load_config()
            existing_key = (existing_cfg.llm.gemini.api_key or "").strip()
        except Exception:
            pass

        if existing_key:
            console.print("[green]复用 [llm.gemini] 段已配置的 API Key,无需再填。[/green]")
            api_key = existing_key
        else:
            console.print(
                "[dim]去 https://aistudio.google.com/apikey 拿一个 Gemini API Key,"
                "复制粘贴到下面(免费档每天 1500 次,日常用足够)。[/dim]"
            )
            api_key = typer.prompt(
                "Gemini API Key",
                hide_input=True,
                default="",
                show_default=False,
            ).strip()
            if not api_key:
                console.print("[yellow]Key 为空,未启用 Gemini embedding。[/yellow]")
                return

        _save_embedding_config(
            provider="gemini",
            model="gemini-embedding-001",
            api_key=api_key,
        )
        console.print("[bold green]已启用 Gemini embedding(gemini-embedding-001)[/bold green]")
        return

    if choice in {"3", "follow"}:
        _save_embedding_config(provider="", model="")
        console.print(
            "[green]已设置为不启用 embedding。需要语义去重/相似度时,可之后运行 "
            "`openbiliclaw setup-embedding` 单独配置。[/green]"
        )
        return

    if choice == "4":
        base_url = typer.prompt(
            "Embedding Base URL(OpenAI 兼容,例如 http://localhost:8000/v1)"
        ).strip()
        api_key = typer.prompt(
            "Embedding API Key(如服务无鉴权可留空)",
            hide_input=True,
            default="",
            show_default=False,
        ).strip()
        model = typer.prompt("Embedding 模型名称", default="bge-m3").strip()
        _save_embedding_config(
            provider="openai",
            model=model,
            base_url=base_url,
            api_key=api_key,
        )
        console.print(
            "[bold green]已配置自定义 OpenAI 兼容 embedding 服务"
            r"(写入 \[llm.embedding] 段)。[/bold green]"
        )
        return

    if choice == "5":
        target = (
            typer.prompt(
                "选择 provider(claude / gemini / deepseek / openrouter / ollama)",
                default="gemini",
            )
            .strip()
            .lower()
        )
        if target not in _SUPPORTED_PROVIDERS:
            console.print("[red]未知 provider,跳过 embedding 配置。[/red]")
            return
        defaults = _PROVIDER_DEFAULTS.get(target, {})
        base_url = typer.prompt(
            f"{target} Base URL(留空走默认)",
            default=defaults.get("base_url", ""),
            show_default=bool(defaults.get("base_url")),
        ).strip()
        api_key = ""
        if target != "ollama":
            api_key = typer.prompt(
                f"{target} API Key",
                hide_input=True,
                default="",
                show_default=False,
            ).strip()
        model = typer.prompt(
            "Embedding 模型名称",
            default="text-embedding-3-small" if target == "openai" else "",
            show_default=False,
        ).strip()
        if not model:
            console.print("[red]模型名为空,跳过 embedding 配置。[/red]")
            return
        _save_embedding_config(
            provider=target,
            model=model,
            base_url=base_url,
            api_key=api_key,
        )
        console.print(f"[bold green]已配置 {target} 作为 embedding provider。[/bold green]")
        return

    console.print("[red]未识别的选项,跳过 embedding 配置。[/red]")


def _interactive_module_overrides(default_provider: str) -> None:
    """Phase 4 —— 可选的 per-module LLM 覆盖(高级,可跳过)。"""
    if not typer.confirm(
        "（高级，可跳过）是否为单个模块单独指定 provider/model？\n"
        "  典型场景：发现/评估走便宜模型，灵魂画像走高质量模型。",
        default=False,
    ):
        return

    overrides: dict[str, dict[str, str]] = {}
    modules = (
        ("soul", "灵魂画像（高质量模型，稳定性优先）"),
        ("discovery", "内容发现（吞吐量大，建议廉价模型）"),
        ("recommendation", "推荐文案（解释生成，平衡质量和成本）"),
        ("evaluation", "内容评估（高频调用，建议廉价模型）"),
    )
    for module, desc in modules:
        if not typer.confirm(f"为 [{module}] {desc} 配置覆盖？", default=False):
            continue
        provider = (
            typer.prompt(
                f"  {module} provider（留空 = 跟随默认 {default_provider}）",
                default="",
                show_default=False,
            )
            .strip()
            .lower()
        )
        if provider and provider not in _SUPPORTED_PROVIDERS:
            console.print(f"  [red]未知 provider「{provider}」，跳过该模块。[/red]")
            continue
        model = typer.prompt(
            f"  {module} 模型（留空 = 跟随 provider 默认）",
            default="",
            show_default=False,
        ).strip()
        overrides[module] = {"provider": provider, "model": model}

    if overrides:
        _save_module_overrides(overrides)
        console.print(f"[green]已写入 {len(overrides)} 个模块的 LLM 覆盖配置。[/green]")
    else:
        console.print("[dim]未配置任何模块覆盖。[/dim]")


def _interactive_runtime_config_setup() -> None:
    """在 init 之前引导用户补齐缺失的 LLM 配置。

    四阶段流程：
      1) 选 LLM 服务（Ollama 优先菜单；OpenAI-compat 是独立条目，
         不埋在 ``openai`` 里）。
      2) 提供该选项实际需要的字段。
      3) 选择 embedding 服务方式（独立提问，不打包）。
      4) 可选的每模块覆盖（高级，默认跳过）。
    """
    _print_page_title("初始化前配置引导", "选 LLM、配 Embedding、填 B 站 Cookie")
    _print_provider_table()

    while True:
        raw = typer.prompt("\n请输入序号或名称（默认 1=Ollama）", default="1")
        choice = _resolve_menu_choice(raw)
        if choice is None:
            console.print("[bold red]看不懂这个输入，请重新输入序号或名称[/bold red]")
            continue

        provider, base_url, api_key, model = _prompt_provider_triplet(choice)

        _save_runtime_provider_config(
            provider,
            api_key=api_key,
            base_url=base_url,
            model=model,
        )

        error = _load_runtime_config_error(render=False)
        if error is not None:
            console.print("[bold yellow]刚写入的配置仍不完整，请重新选择。[/bold yellow]")
            _print_runtime_config_error(error)
            continue

        console.print(
            "\n[bold]接下来配 Embedding[/bold]"
            "\n[dim]Embedding 是和聊天模型分开的：把视频标题/简介变成向量，"
            "用于跨视频去重和相似度判定。频次很高，所以单独拎出来配。[/dim]"
        )
        _interactive_embedding_setup(provider, auto_if_ready=True)

        console.print(
            "\n[bold]最后是 Per-module 覆盖（高级，默认可跳过）[/bold]"
            "\n[dim]给 soul / discovery / recommendation / evaluation 单独指定模型，"
            "比如发现/评估走便宜模型，画像走高质量。大多数用户不需要。[/dim]"
        )
        _interactive_module_overrides(provider)
        return


def _interactive_auth_setup(auth_manager: Any) -> Any:
    """在 init 之前引导用户完成 B 站认证。

    自 v0.3.12 起有两条路径：
      A. 安装浏览器扩展，让它通过 ``POST /api/bilibili/cookie``
         自动同步 cookie（推荐——零 F12）。
      B. 在这里手动粘贴 cookie（针对不愿装扩展的用户兜底）。
    """
    _print_page_title("初始化前认证引导", "补齐 B 站认证")
    console.print(
        "[bold]为什么需要 B 站 Cookie？[/bold]\n"
        "OpenBiliClaw 需要你的 B 站登录态来：\n"
        "  • 拉你的观看历史（用来训练画像）\n"
        "  • 以你的身份调 B 站 API 拿视频详情\n"
        "[dim]Cookie 只存在你本机 data/bilibili_cookie.json，不会上传任何地方。[/dim]\n\n"
        "[bold]两种方式（任选其一）：[/bold]\n"
        "  [cyan]1.[/cyan] 装浏览器扩展，自动同步（推荐，零配置）\n"
        "     下载: https://github.com/whiteguo233/OpenBiliClaw/releases\n"
        "     装好后扩展会几秒内自动把登录 Cookie 推到本地后端。\n"
        "     选这条会先退出 init；扩展同步完再跑 `openbiliclaw init` 即可。\n\n"
        "  [cyan]2.[/cyan] 现在手动贴 Cookie\n"
        "     1) 用 Chrome/Edge/Firefox 登录 https://www.bilibili.com\n"
        "     2) F12 → Network 标签 → 刷新 → 点任意 bilibili.com 请求\n"
        "     3) Headers 区域找到 cookie: 一行，右键复制整行 value\n"
        "     4) 把那一长串（含 SESSDATA / bili_jct / DedeUserID）粘下面\n"
    )
    choice = typer.prompt("请选 [1=装扩展自动同步 / 2=现在手贴]", default="1").strip()
    if choice in {"1", "extension", "ext", ""}:
        console.print(
            "\n[bold green]好的——退出当前 init，让扩展接手。[/bold green]\n"
            "  1. 启动后端：[cyan]openbiliclaw start[/cyan]（或保持当前 docker compose up）\n"
            "  2. 装扩展：[cyan]https://github.com/whiteguo233/OpenBiliClaw/releases[/cyan]\n"
            "  3. 确认你已登录 B 站；扩展会几秒内同步 Cookie\n"
            "  4. 再跑 [cyan]openbiliclaw init[/cyan] 完成画像生成 + 首轮发现\n"
        )
        raise typer.Exit(code=0)

    while True:
        cookie_value = typer.prompt("请粘贴 B 站 Cookie", prompt_suffix=": ")
        status = asyncio.run(auth_manager.validate_cookie(cookie_value))
        if status.authenticated:
            auth_manager.set_cookie(cookie_value)
            console.print("[bold green]登录成功[/bold green]")
            _print_auth_status(status)
            return status

        console.print("[bold red]认证失败 —— Cookie 看起来无效或过期了[/bold red]")
        _print_auth_status(status)
        if not typer.confirm("是否重试？（重新走一遍上面的步骤）", default=True):
            raise typer.Exit(code=1)


def _prepare_init_runtime() -> Any:
    """在 init 推进之前确保运行时配置与认证已就绪。"""
    error = _load_runtime_config_error(render=False)
    if error is not None:
        if not _is_interactive_terminal():
            _print_runtime_config_error(error)
            raise typer.Exit(code=1)
        _interactive_runtime_config_setup()

    auth_manager = _build_auth_manager()
    status = asyncio.run(auth_manager.get_status())
    if status.authenticated:
        return status
    if not _is_interactive_terminal():
        console.print("[bold red]认证失败[/bold red]")
        console.print("请先执行 `openbiliclaw auth login` 完成 B 站认证。")
        raise typer.Exit(code=1)
    return _interactive_auth_setup(auth_manager)


def _format_strategy_group(strategies: list[str]) -> str:
    return " + ".join(strategies)


async def _run_init_discovery_backfill_async(
    profile: Any,
    *,
    target_pool_count: int = 100,
    label_suffix: str = "",
) -> int:
    """分阶段补货初始 discovery 池，直到达到目标数量。"""
    from openbiliclaw.discovery.pool_snapshot import build_cold_start_pool_snapshot

    database = _get_runtime_database()
    discovery_engine = _build_discovery_engine()
    discovered_count = 0

    for index, strategies in enumerate(_INIT_DISCOVERY_PLAN, start=1):
        current_pool_count = database.count_pool_candidates()
        if current_pool_count >= target_pool_count:
            break
        request_limit = max(20, target_pool_count - current_pool_count)
        pool_snapshot = (
            build_cold_start_pool_snapshot(
                profile,
                pool_target_count=target_pool_count,
                source_targets={"bilibili": target_pool_count},
            )
            if current_pool_count <= 0
            else None
        )
        console.print(
            f"补货阶段 {index}/{len(_INIT_DISCOVERY_PLAN)}: {_format_strategy_group(strategies)}"
            f"{label_suffix}"
        )
        console.print(
            f"当前池子 {current_pool_count}/{target_pool_count}，本轮请求上限 {request_limit}"
        )
        discovered = await _run_with_progress(
            discovery_engine.discover(
                profile,
                strategies=strategies,
                limit=request_limit,
                # Init 对延迟敏感——跳过默认的 search-first
                # phase 切分，让每个策略共享 gather。
                fully_parallel=True,
                pool_snapshot=pool_snapshot,
            ),
            label=f"发现内容({_format_strategy_group(strategies)} 并发){label_suffix}",
            eta_seconds=300,
        )
        discovered_count += len(discovered)
        console.print(
            "阶段完成: "
            f"当前池子 {database.count_pool_candidates()}/{target_pool_count}，"
            f"本轮发现 {len(discovered)} 条"
        )

    return discovered_count


def _build_draft_profile_for_discover(memory: Any) -> Any:
    """构建仅含偏好的 ``OnionProfile``，使 discover 能与
    ``build_initial_profile`` 并行启动（P3）。

    完整画像构建器会跑一次 LLM synthesis 调用，遍历 history +
    preference + awareness + insights 来产出
    ``personality_portrait``、``deep_needs``、``core_traits`` 等
    字段——这些字段会"上色" discover 的评估提示，但对相关性打分
    并非承重字段（信号由 interests + style +
    favorite_up_users 承载）。让 discover 用仅含偏好的草稿、
    同时在后台构建真画像，使原本串行的两个阶段得以重叠。
    """
    from openbiliclaw.soul.profile import OnionProfile

    preference_layer = memory.get_layer("preference").data
    draft = OnionProfile()
    draft.populate_from_flat_preference(preference_layer)
    return draft


def _xhs_bootstrap_dedupe_hours() -> float:
    raw = os.environ.get(
        "OPENBILICLAW_XHS_BOOTSTRAP_DEDUPE_HOURS",
        str(_DEFAULT_XHS_BOOTSTRAP_DEDUPE_HOURS),
    )
    try:
        return max(0.0, float(raw))
    except ValueError:
        return _DEFAULT_XHS_BOOTSTRAP_DEDUPE_HOURS


def _dy_bootstrap_dedupe_hours() -> float:
    raw = os.environ.get(
        "OPENBILICLAW_DY_BOOTSTRAP_DEDUPE_HOURS",
        str(_DEFAULT_DY_BOOTSTRAP_DEDUPE_HOURS),
    )
    try:
        return max(0.0, float(raw))
    except ValueError:
        return _DEFAULT_DY_BOOTSTRAP_DEDUPE_HOURS


def _yt_bootstrap_dedupe_hours() -> float:
    raw = os.environ.get(
        "OPENBILICLAW_YT_BOOTSTRAP_DEDUPE_HOURS",
        str(_DEFAULT_YT_BOOTSTRAP_DEDUPE_HOURS),
    )
    try:
        return max(0.0, float(raw))
    except ValueError:
        return _DEFAULT_YT_BOOTSTRAP_DEDUPE_HOURS


def _zhihu_bootstrap_dedupe_hours() -> float:
    raw = os.environ.get(
        "OPENBILICLAW_ZHIHU_BOOTSTRAP_DEDUPE_HOURS",
        str(_DEFAULT_ZHIHU_BOOTSTRAP_DEDUPE_HOURS),
    )
    try:
        return max(0.0, float(raw))
    except ValueError:
        return _DEFAULT_ZHIHU_BOOTSTRAP_DEDUPE_HOURS


def _enqueue_xhs_bootstrap_task(*, force: bool = False, kick: bool = True) -> str | None:
    """以 fire-and-forget 方式入队 bootstrap_profile 任务。

    入队成功则返回 task_id,否则返回 ``None``(DB 不可用、
    日预算耗尽等)。不等待 —— 扩展会从队列中取走任务,
    与 init 的其余步骤并行执行。

    默认值:``max_scroll_rounds=15`` 与 ``max_items_per_scope=300``。
    两者都可以通过环境变量
    ``OPENBILICLAW_XHS_BOOTSTRAP_SCROLL_ROUNDS`` 和
    ``OPENBILICLAW_XHS_BOOTSTRAP_MAX_ITEMS`` 覆盖。
    """
    from openbiliclaw.sources.xhs_tasks import XhsTaskQueue

    try:
        database = _get_runtime_database()
    except Exception as exc:
        console.print(f"  [yellow]小红书初始化信号未导入: 数据库不可用: {exc}[/yellow]")
        return None
    if not hasattr(database, "conn"):
        return None

    scroll_rounds = int(os.environ.get("OPENBILICLAW_XHS_BOOTSTRAP_SCROLL_ROUNDS", "15"))
    max_items = int(
        os.environ.get(
            "OPENBILICLAW_XHS_BOOTSTRAP_MAX_ITEMS",
            str(_INIT_BOOTSTRAP_MAX_ITEMS_PER_SCOPE),
        )
    )
    task_id: str | None = None

    try:
        queue = XhsTaskQueue(database)
        dedupe_hours = _xhs_bootstrap_dedupe_hours()
        find_recent = getattr(queue, "find_recent_task", None)
        if not force and dedupe_hours > 0 and callable(find_recent):
            recent = find_recent(
                "bootstrap_profile",
                recent_hours=dedupe_hours,
                statuses=("pending", "in_progress", "completed", "failed"),
            )
            if recent is not None:
                task_id = str(recent.get("id", "")).strip()
                if task_id:
                    status = str(recent.get("status", "unknown"))
                    console.print(
                        "  [dim]复用最近的小红书 bootstrap 任务"
                        f"({status})；需要重新拉取可用 `openbiliclaw fetch-xhs --force`。[/dim]"
                    )
                    return task_id
        task_id = queue.enqueue_with_id(
            "bootstrap_profile",
            {
                "scopes": ["saved", "liked", "xhs_history"],
                "max_items_per_scope": max(1, max_items),
                "max_scroll_rounds": max(0, scroll_rounds),
            },
            daily_budget=10,
        )
    except Exception as exc:
        console.print(f"  [yellow]小红书初始化信号未导入: {exc}[/yellow]")
        return None
    if not task_id:
        console.print("  [yellow]小红书初始化信号未导入: 今日任务预算已用完。[/yellow]")
        return None
    # 立即通过 runtime-stream WebSocket 唤醒扩展 dispatcher，
    # 而不是等下一次 chrome.alarms tick（最多 60s）。kick 是
    # best-effort——若守护进程的 API 未运行，现有的 alarm 轮询
    # 仍会在下次触发时拿到任务。
    # ``kick=False`` 让 guided-init 流水线先在 coordinator 注册任务
    # 所有权 *再* 唤醒扩展（避免 register-after-kick 竞态：owned
    # 结果被当作外来结果处理）。
    if kick:
        _kick_task_dispatcher("xhs")
    return task_id


def _kick_task_dispatcher(source: str) -> None:
    """对守护进程的 task-kick 端点发起 fire-and-forget POST。

    守护进程通过 runtime-stream WebSocket 广播
    ``<source>_task_available``，扩展的 service-worker 收到后会
    立即触发对应 dispatcher 的轮询。失败静默：若守护进程未运行，
    现有的 chrome.alarms 60s 轮询兜底仍会拾起任务。
    """
    if source not in {"xhs", "dy", "yt", "zhihu"}:
        return
    import urllib.error
    import urllib.request

    url = f"http://127.0.0.1:8420/api/sources/{source}/kick"
    req = urllib.request.Request(url, method="POST", data=b"")
    # 短超时——kick 是 best-effort。守护进程未运行 /
    # 网络抖动 / 连接被拒都静默降级到 60s alarm 兜底。
    with suppress(urllib.error.URLError, TimeoutError, OSError):
        urllib.request.urlopen(req, timeout=1.0).close()


def _collect_xhs_bootstrap_events(
    task_id: str | None,
    *,
    max_wait_seconds: float | None = None,
) -> tuple[list[dict[str, Any]], dict[str, int], str]:
    """等待并收割之前入队的 bootstrap_profile 任务。

    返回 ``(events, scope_counts, status_label)``，``status_label``
    取以下值之一：
      - ``"ok"``         —— 任务完成且有 notes
      - ``"empty"``      —— 任务完成但扩展返回 0 条 notes
      - ``"timeout"``    —— 等待窗口到期，任务仍 pending / in-progress
      - ``"failed"``     —— 扩展或后端报错
      - ``"skipped"``    —— 无 task_id（DB 不可用 / 预算耗尽）

    等待截止从 NOW 开始计算；在 init 流程中较早入队任务的调用方
    可享受并行执行的领先时间。
    """
    import json
    import time

    from openbiliclaw.sources.xhs_tasks import (
        XhsTaskQueue,
        xhs_bootstrap_notes_to_events,
    )

    if not task_id:
        return [], {}, "skipped"

    if max_wait_seconds is None:
        max_wait_seconds = float(
            os.environ.get(
                "OPENBILICLAW_XHS_BOOTSTRAP_WAIT_SECONDS",
                str(_DEFAULT_XHS_BOOTSTRAP_WAIT_SECONDS),
            )
        )

    try:
        database = _get_runtime_database()
    except Exception:
        return [], {}, "skipped"
    if not hasattr(database, "conn"):
        return [], {}, "skipped"

    queue = XhsTaskQueue(database)
    deadline = time.monotonic() + max(0.0, max_wait_seconds)
    poll_interval = 0.5
    task: dict[str, Any] | None = None
    while True:
        task = queue.get(task_id)
        status = str((task or {}).get("status", "")).strip()
        if status in {"completed", "failed"}:
            break
        if time.monotonic() >= deadline:
            break
        time.sleep(poll_interval)

    if not task:
        return [], {}, "timeout"
    if task.get("status") == "failed":
        return [], {}, "failed"
    if task.get("status") != "completed":
        return [], {}, "timeout"

    try:
        result = json.loads(str(task.get("result_json") or "{}"))
    except json.JSONDecodeError:
        return [], {}, "failed"
    notes = [note for note in result.get("notes", []) if isinstance(note, dict)]
    events = xhs_bootstrap_notes_to_events(notes)
    raw_counts = result.get("scope_counts", {})
    scope_counts = {"saved": 0, "liked": 0, "xhs_history": 0}
    if isinstance(raw_counts, dict):
        for key in scope_counts:
            with suppress(Exception):
                scope_counts[key] = int(raw_counts.get(key, 0) or 0)
    if not any(scope_counts.values()):
        for event in events:
            metadata = event.get("metadata", {})
            if not isinstance(metadata, dict):
                continue
            source = str(metadata.get("import_source", ""))
            for key in scope_counts:
                if source == f"xhs_bootstrap_{key}":
                    scope_counts[key] += 1
    status_label = "ok" if events else "empty"
    return events, scope_counts, status_label


def _import_xhs_bootstrap_events() -> tuple[list[dict[str, Any]], dict[str, int]]:
    """向后兼容的单发包装器，供测试使用。

    真实的 ``init`` 流程使用上面拆分的 enqueue/collect API，
    让 xhs 数据采集与 B 站拉取并行进行，而不是串行等待固定时长。
    该包装器保留旧的测试契约。
    """
    task_id = _enqueue_xhs_bootstrap_task()
    events, counts, _status = _collect_xhs_bootstrap_events(task_id)
    return events, counts


def _enqueue_dy_bootstrap_task(*, kick: bool = True) -> str | None:
    """fire-and-forget 入队 Douyin bootstrap_profile 任务。

    镜像 ``_enqueue_xhs_bootstrap_task``，用于 Douyin 流水线。
    两者不共享代码——``DyTaskQueue`` 表独立、env 变量独立、
    面向用户的消息独立。soul-engine 通过统一的
    ``event_format.build_event`` 契约消费产出事件，因此跨源
    分析在下游保持一致。

    默认值：``max_scroll_rounds=15``、``max_items_per_scope=300``。
    两者均可通过环境变量覆盖。
    ``OPENBILICLAW_DY_BOOTSTRAP_SCROLL_ROUNDS`` 与
    ``OPENBILICLAW_DY_BOOTSTRAP_MAX_ITEMS``。
    """
    from openbiliclaw.sources.dy_tasks import DyTaskQueue

    try:
        database = _get_runtime_database()
    except Exception as exc:
        console.print(f"  [yellow]抖音初始化信号未导入: 数据库不可用: {exc}[/yellow]")
        return None
    if not hasattr(database, "conn"):
        return None

    scroll_rounds = int(os.environ.get("OPENBILICLAW_DY_BOOTSTRAP_SCROLL_ROUNDS", "15"))
    max_items = int(
        os.environ.get(
            "OPENBILICLAW_DY_BOOTSTRAP_MAX_ITEMS",
            str(_INIT_BOOTSTRAP_MAX_ITEMS_PER_SCOPE),
        )
    )
    task_id: str | None = None

    try:
        queue = DyTaskQueue(database)
        dedupe_hours = _dy_bootstrap_dedupe_hours()
        find_recent = getattr(queue, "find_recent_task", None)
        if dedupe_hours > 0 and callable(find_recent):
            recent = find_recent(
                "bootstrap_profile",
                recent_hours=dedupe_hours,
                statuses=("pending", "in_progress", "completed", "failed"),
            )
            if recent is not None:
                task_id = str(recent.get("id", "")).strip()
                if task_id:
                    status = str(recent.get("status", "unknown"))
                    console.print(
                        "  [dim]复用最近的抖音 bootstrap 任务"
                        f"({status})；需要重新拉取可设 "
                        "OPENBILICLAW_DY_BOOTSTRAP_DEDUPE_HOURS=0。[/dim]"
                    )
                    return task_id
        task_id = queue.enqueue_with_id(
            "bootstrap_profile",
            {
                "scopes": ["dy_post", "dy_collect", "dy_like", "dy_follow"],
                "max_items_per_scope": max(1, max_items),
                "max_scroll_rounds": max(0, scroll_rounds),
            },
            daily_budget=10,
        )
    except Exception as exc:
        console.print(f"  [yellow]抖音初始化信号未导入: {exc}[/yellow]")
        return None
    if not task_id:
        console.print("  [yellow]抖音初始化信号未导入: 今日任务预算已用完。[/yellow]")
        return None
    if kick:
        _kick_task_dispatcher("dy")
    return task_id


def _collect_dy_bootstrap_events(
    task_id: str | None,
    *,
    max_wait_seconds: float | None = None,
) -> tuple[list[dict[str, Any]], dict[str, int], str]:
    """等待并收割之前入队的 Douyin bootstrap 任务。

    返回 ``(events, scope_counts, status_label)``，``status_label``
    取以下值之一：
      - ``"ok"``         —— 任务完成且有 videos
      - ``"empty"``      —— 任务完成但扩展返回 0 条 videos
        （典型发生在用户未登录 douyin.com 时——软反爬返回
        HTTP 200 + 空 body，详见 design-doc Risk #7）
      - ``"timeout"``    —— 等待窗口到期，任务仍 pending
      - ``"failed"``     —— 扩展或后端报错
      - ``"skipped"``    —— 无 task_id（DB 不可用 / 预算耗尽）
    """
    import json
    import time

    from openbiliclaw.sources.dy_tasks import (
        DyTaskQueue,
        dy_bootstrap_videos_to_events,
    )

    if not task_id:
        return [], {}, "skipped"

    if max_wait_seconds is None:
        max_wait_seconds = float(
            os.environ.get(
                "OPENBILICLAW_DY_BOOTSTRAP_WAIT_SECONDS",
                str(_DEFAULT_DY_BOOTSTRAP_WAIT_SECONDS),
            )
        )

    try:
        database = _get_runtime_database()
    except Exception:
        return [], {}, "skipped"
    if not hasattr(database, "conn"):
        return [], {}, "skipped"

    queue = DyTaskQueue(database)
    deadline = time.monotonic() + max(0.0, max_wait_seconds)
    poll_interval = 0.5
    task: dict[str, Any] | None = None
    while True:
        task = queue.get(task_id)
        status = str((task or {}).get("status", "")).strip()
        if status in {"completed", "failed"}:
            break
        if time.monotonic() >= deadline:
            break
        time.sleep(poll_interval)

    if not task:
        return [], {}, "timeout"
    if task.get("status") == "failed":
        return [], {}, "failed"
    if task.get("status") != "completed":
        return [], {}, "timeout"

    try:
        result = json.loads(str(task.get("result_json") or "{}"))
    except json.JSONDecodeError:
        return [], {}, "failed"
    videos = [v for v in result.get("videos", []) if isinstance(v, dict)]
    events = dy_bootstrap_videos_to_events(videos)
    raw_counts = result.get("scope_counts", {})
    scope_counts = {"dy_post": 0, "dy_collect": 0, "dy_like": 0, "dy_follow": 0}
    if isinstance(raw_counts, dict):
        for key in scope_counts:
            with suppress(Exception):
                scope_counts[key] = int(raw_counts.get(key, 0) or 0)
    if not any(scope_counts.values()):
        # 回退到逐事件计数：dy_bootstrap_videos_to_events
        # 把每个事件的 metadata.import_source 标记为
        # "dy_bootstrap_<scope_short>"（post / collect / like / follow）。
        for event in events:
            metadata = event.get("metadata", {})
            if not isinstance(metadata, dict):
                continue
            source = str(metadata.get("import_source", ""))
            for key in scope_counts:
                short = key.removeprefix("dy_") if key.startswith("dy_") else key
                if source == f"dy_bootstrap_{short}":
                    scope_counts[key] += 1
    status_label = "ok" if events else "empty"
    return events, scope_counts, status_label


def _enqueue_yt_bootstrap_task(*, kick: bool = True) -> str | None:
    """为浏览器扩展入队 YouTube bootstrap_profile 任务。

    默认值：``max_scroll_rounds=10``、``max_items_per_scope=300``。
    两者均可通过环境变量覆盖：
    ``OPENBILICLAW_YT_BOOTSTRAP_SCROLL_ROUNDS`` 与
    ``OPENBILICLAW_YT_BOOTSTRAP_MAX_ITEMS``。
    """
    from openbiliclaw.sources.yt_tasks import YtTaskQueue

    try:
        database = _get_runtime_database()
    except Exception as exc:
        console.print(f"  [yellow]YouTube 初始化信号未导入: 数据库不可用: {exc}[/yellow]")
        return None
    if not hasattr(database, "conn"):
        return None

    scroll_rounds = int(os.environ.get("OPENBILICLAW_YT_BOOTSTRAP_SCROLL_ROUNDS", "10"))
    max_items = int(
        os.environ.get(
            "OPENBILICLAW_YT_BOOTSTRAP_MAX_ITEMS",
            str(_INIT_BOOTSTRAP_MAX_ITEMS_PER_SCOPE),
        )
    )
    task_id: str | None = None

    try:
        queue = YtTaskQueue(database)
        dedupe_hours = _yt_bootstrap_dedupe_hours()
        find_recent = getattr(queue, "find_recent_task", None)
        if dedupe_hours > 0 and callable(find_recent):
            recent = find_recent(
                "bootstrap_profile",
                recent_hours=dedupe_hours,
                statuses=("pending", "in_progress", "completed", "failed"),
            )
            if recent is not None:
                task_id = str(recent.get("id", "")).strip()
                if task_id:
                    status = str(recent.get("status", "unknown"))
                    console.print(
                        "  [dim]复用最近的 YouTube bootstrap 任务"
                        f"({status})；需要重新拉取可设 "
                        "OPENBILICLAW_YT_BOOTSTRAP_DEDUPE_HOURS=0。[/dim]"
                    )
                    return task_id
        task_id = queue.enqueue_with_id(
            "bootstrap_profile",
            {
                "scopes": ["yt_history", "yt_subscriptions", "yt_likes"],
                "max_items_per_scope": max(1, max_items),
                "max_scroll_rounds": max(0, scroll_rounds),
            },
            daily_budget=10,
        )
    except Exception as exc:
        console.print(f"  [yellow]YouTube 初始化信号未导入: {exc}[/yellow]")
        return None
    if not task_id:
        console.print("  [yellow]YouTube 初始化信号未导入: 今日任务预算已用完。[/yellow]")
        return None
    if kick:
        _kick_task_dispatcher("yt")
    return task_id


def _collect_yt_bootstrap_events(
    task_id: str | None,
    *,
    max_wait_seconds: float | None = None,
) -> tuple[list[dict[str, Any]], dict[str, int], str]:
    """等待并收割之前入队的 YouTube bootstrap 任务。

    返回 ``(events, scope_counts, status_label)``，``status_label``
    取 ``"ok"``、``"empty"``、``"timeout"``、``"failed"`` 或
    ``"skipped"`` 之一。
    """
    import json
    import time

    from openbiliclaw.sources.yt_tasks import (
        YtTaskQueue,
        yt_bootstrap_items_to_events,
    )

    if not task_id:
        return [], {}, "skipped"

    if max_wait_seconds is None:
        max_wait_seconds = float(
            os.environ.get(
                "OPENBILICLAW_YT_BOOTSTRAP_WAIT_SECONDS",
                str(_DEFAULT_YT_BOOTSTRAP_WAIT_SECONDS),
            )
        )

    try:
        database = _get_runtime_database()
    except Exception:
        return [], {}, "skipped"
    if not hasattr(database, "conn"):
        return [], {}, "skipped"

    queue = YtTaskQueue(database)
    deadline = time.monotonic() + max(0.0, max_wait_seconds)
    poll_interval = 0.5
    task: dict[str, Any] | None = None
    while True:
        task = queue.get(task_id)
        status = str((task or {}).get("status", "")).strip()
        if status in {"completed", "failed"}:
            break
        if time.monotonic() >= deadline:
            break
        time.sleep(poll_interval)

    if not task:
        return [], {}, "timeout"
    if task.get("status") == "failed":
        return [], {}, "failed"
    if task.get("status") != "completed":
        return [], {}, "timeout"

    try:
        result = json.loads(str(task.get("result_json") or "{}"))
    except json.JSONDecodeError:
        return [], {}, "failed"

    items = [v for v in result.get("items", []) if isinstance(v, dict)]
    events = yt_bootstrap_items_to_events(items)
    raw_counts = result.get("scope_counts", {})
    scope_counts: dict[str, int] = {"yt_history": 0, "yt_subscriptions": 0, "yt_likes": 0}
    if isinstance(raw_counts, dict):
        for key in scope_counts:
            with suppress(Exception):
                scope_counts[key] = int(raw_counts.get(key, 0) or 0)
    if not any(scope_counts.values()):
        for event in events:
            metadata = event.get("metadata", {})
            if not isinstance(metadata, dict):
                continue
            source = str(metadata.get("import_source", ""))
            for key in scope_counts:
                short = key.removeprefix("yt_") if key.startswith("yt_") else key
                if source == f"yt_bootstrap_{short}":
                    scope_counts[key] += 1
    status_label = "ok" if events else "empty"
    return events, scope_counts, status_label


def _enqueue_zhihu_bootstrap_task(
    *,
    profile_slug: str = "",
    kick: bool = True,
    profile_update: bool = False,
) -> str | None:
    """为浏览器扩展入队 Zhihu bootstrap_events 任务。

    扩展在已登录的浏览器里执行 same-origin 知乎会话拉取。
    本命令只做 fetch；不触发画像生成。
    """
    from openbiliclaw.sources.zhihu_tasks import ZhihuTaskQueue

    try:
        database = _get_runtime_database()
    except Exception as exc:
        console.print(f"  [yellow]知乎事件未拉取: 数据库不可用: {exc}[/yellow]")
        return None
    if not hasattr(database, "conn"):
        return None

    max_items = int(
        os.environ.get(
            "OPENBILICLAW_ZHIHU_BOOTSTRAP_MAX_ITEMS",
            str(_INIT_BOOTSTRAP_MAX_ITEMS_PER_SCOPE),
        )
    )
    max_collections = int(os.environ.get("OPENBILICLAW_ZHIHU_BOOTSTRAP_MAX_COLLECTIONS", "20"))
    task_id: str | None = None

    try:
        queue = ZhihuTaskQueue(database)
        dedupe_hours = _zhihu_bootstrap_dedupe_hours()
        find_recent = getattr(queue, "find_recent_task", None)
        if dedupe_hours > 0 and callable(find_recent):
            recent = find_recent(
                "bootstrap_events",
                recent_hours=dedupe_hours,
                statuses=("pending", "in_progress", "completed", "failed"),
            )
            if recent is not None:
                task_id = str(recent.get("id", "")).strip()
                if task_id:
                    status = str(recent.get("status", "unknown"))
                    console.print(
                        "  [dim]复用最近的知乎 bootstrap 任务"
                        f"({status})；需要重新拉取可设 "
                        "OPENBILICLAW_ZHIHU_BOOTSTRAP_DEDUPE_HOURS=0。[/dim]"
                    )
                    return task_id

        scopes = ["zhihu_read_history", "zhihu_collection", "zhihu_activity"]
        if not profile_slug.strip():
            console.print(
                "  [dim]未传 --profile-slug，扩展会尝试从知乎登录态识别当前用户；"
                "识别失败时只返回浏览记录和收藏夹。[/dim]"
            )
        task_id = queue.enqueue_with_id(
            "bootstrap_events",
            {
                "scopes": scopes,
                "profile_slug": profile_slug.strip(),
                "max_items_per_scope": max(1, max_items),
                "max_collections": max(1, max_collections),
                "profile_update": bool(profile_update),
            },
            daily_budget=10,
        )
    except Exception as exc:
        console.print(f"  [yellow]知乎事件未拉取: {exc}[/yellow]")
        return None
    if not task_id:
        console.print("  [yellow]知乎事件未拉取: 今日任务预算已用完。[/yellow]")
        return None
    if kick:
        _kick_task_dispatcher("zhihu")
    return task_id


def _collect_zhihu_bootstrap_events(
    task_id: str | None,
    *,
    max_wait_seconds: float | None = None,
) -> tuple[list[dict[str, Any]], dict[str, int], str]:
    """等待并收割之前入队的 Zhihu bootstrap 任务。"""
    import json
    import time

    from openbiliclaw.sources.zhihu_tasks import (
        ZhihuTaskQueue,
        zhihu_bootstrap_items_to_events,
    )

    empty_counts = {
        "zhihu_read_history": 0,
        "zhihu_collection": 0,
        "zhihu_activity_like": 0,
        "zhihu_activity_favorite": 0,
    }
    if not task_id:
        return [], empty_counts, "skipped"

    if max_wait_seconds is None:
        max_wait_seconds = float(
            os.environ.get(
                "OPENBILICLAW_ZHIHU_BOOTSTRAP_WAIT_SECONDS",
                str(_DEFAULT_ZHIHU_BOOTSTRAP_WAIT_SECONDS),
            )
        )

    try:
        database = _get_runtime_database()
    except Exception:
        return [], empty_counts, "skipped"
    if not hasattr(database, "conn"):
        return [], empty_counts, "skipped"

    queue = ZhihuTaskQueue(database)
    deadline = time.monotonic() + max(0.0, max_wait_seconds)
    task: dict[str, Any] | None = None
    while True:
        task = queue.get(task_id)
        status = str((task or {}).get("status", "")).strip()
        if status in {"completed", "failed"}:
            break
        if time.monotonic() >= deadline:
            break
        time.sleep(0.5)

    if not task:
        return [], empty_counts, "timeout"
    if task.get("status") == "failed":
        try:
            result = json.loads(str(task.get("result_json") or "{}"))
        except json.JSONDecodeError:
            result = {}
        debug = result.get("debug", {}) if isinstance(result, dict) else {}
        error = str(result.get("error", "") if isinstance(result, dict) else "")
        if error == "zhihu_login_required" or (
            isinstance(debug, dict) and debug.get("login_required") is True
        ):
            return [], empty_counts, "login_required"
        return [], empty_counts, "failed"
    if task.get("status") != "completed":
        if str(task.get("status", "")).strip() in {"pending", "in_progress"}:
            with suppress(Exception):
                queue.fail(
                    task_id,
                    error="extension_result_timeout",
                    debug={
                        "wait_seconds": max_wait_seconds,
                        "last_status": str(task.get("status", "")),
                    },
                )
        return [], empty_counts, "timeout"

    try:
        result = json.loads(str(task.get("result_json") or "{}"))
    except json.JSONDecodeError:
        return [], empty_counts, "failed"

    items = [v for v in result.get("items", []) if isinstance(v, dict)]
    events = zhihu_bootstrap_items_to_events(items)
    scope_counts = dict(empty_counts)
    raw_counts = result.get("scope_counts", {})
    if isinstance(raw_counts, dict):
        for key in scope_counts:
            with suppress(Exception):
                scope_counts[key] = int(raw_counts.get(key, 0) or 0)
    if not any(scope_counts.values()):
        for event in events:
            event_type = str(event.get("event_type", ""))
            metadata = event.get("metadata", {})
            if not isinstance(metadata, dict):
                continue
            source = str(metadata.get("import_source", ""))
            if source == "zhihu_bootstrap_read_history":
                scope_counts["zhihu_read_history"] += 1
            elif source == "zhihu_bootstrap_collection":
                scope_counts["zhihu_collection"] += 1
            elif event_type == "like":
                scope_counts["zhihu_activity_like"] += 1
            elif event_type == "favorite":
                scope_counts["zhihu_activity_favorite"] += 1
    status_label = "ok" if events else "empty"
    return events, scope_counts, status_label


def _event_memory_key(event: dict[str, Any]) -> tuple[str, str, str, str, str]:
    metadata = event.get("metadata")
    if not isinstance(metadata, dict):
        metadata = {}
    source = str(metadata.get("source_platform") or "").strip()
    event_type = str(event.get("event_type") or event.get("type") or "").strip()
    url = str(event.get("url") or "").strip()
    content_id = str(metadata.get("content_id") or "").strip()
    import_source = str(metadata.get("import_source") or "").strip()
    title = str(event.get("title") or "").strip()
    identity = content_id or url or title
    return source, event_type, identity, import_source, url


def _load_existing_event_keys(memory: Any, *, limit: int) -> set[tuple[str, str, str, str, str]]:
    query_events = getattr(memory, "query_events", None)
    if not callable(query_events):
        return set()
    try:
        rows = query_events(limit=limit)
    except Exception:
        return set()

    import json as _json

    keys: set[tuple[str, str, str, str, str]] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        event = dict(row)
        metadata = event.get("metadata")
        if isinstance(metadata, str):
            try:
                parsed = _json.loads(metadata)
                event["metadata"] = parsed if isinstance(parsed, dict) else {}
            except _json.JSONDecodeError:
                event["metadata"] = {}
        keys.add(_event_memory_key(event))
    return keys


def _write_events_to_memory(events: list[dict[str, Any]], *, source: str = "") -> tuple[int, int]:
    """将采集到的源事件持久化到 memory，并带轻量去重保护。"""
    if not events:
        return 0, 0

    memory = _build_memory_manager()
    existing_keys = _load_existing_event_keys(memory, limit=max(10_000, len(events) * 4))
    batch_keys: set[tuple[str, str, str, str, str]] = set()
    fresh: list[dict[str, Any]] = []
    for event in events:
        key = _event_memory_key(event)
        if key in existing_keys or key in batch_keys:
            continue
        if source:
            metadata = event.get("metadata")
            if isinstance(metadata, dict):
                metadata.setdefault("source_platform", source)
        batch_keys.add(key)
        fresh.append(event)

    async def _propagate() -> None:
        for event in fresh:
            await memory.propagate_event(event)

    asyncio.run(_propagate())
    return len(fresh), len(events) - len(fresh)


def _enqueue_zhihu_search_task(
    keywords: tuple[str, ...],
    *,
    max_items_per_keyword: int = 20,
) -> str | None:
    """为浏览器扩展入队 Zhihu 插件搜索任务。"""
    from openbiliclaw.config import load_config
    from openbiliclaw.sources.zhihu_tasks import ZhihuTaskQueue

    normalized_keywords: list[str] = []
    seen: set[str] = set()
    for keyword in keywords:
        value = str(keyword).strip()
        if not value or value in seen:
            continue
        seen.add(value)
        normalized_keywords.append(value)
    if not normalized_keywords:
        console.print("  [yellow]知乎搜索任务未入队: 关键词为空。[/yellow]")
        return None

    try:
        database = _get_runtime_database()
    except Exception as exc:
        console.print(f"  [yellow]知乎搜索任务未入队: 数据库不可用: {exc}[/yellow]")
        return None
    if not hasattr(database, "conn"):
        return None

    try:
        cfg = load_config()
        budget = int(getattr(getattr(cfg.sources, "zhihu", None), "daily_search_budget", 0))
    except Exception:
        budget = 0

    try:
        queue = ZhihuTaskQueue(database)
        task_id = queue.enqueue_with_id(
            "search",
            {
                "keywords": normalized_keywords,
                "max_items_per_keyword": max(1, int(max_items_per_keyword)),
            },
            daily_budget=budget,
        )
    except Exception as exc:
        console.print(f"  [yellow]知乎搜索任务未入队: {exc}[/yellow]")
        return None
    if not task_id:
        console.print("  [yellow]知乎搜索任务未入队: 今日任务预算已用完。[/yellow]")
        return None
    _kick_task_dispatcher("zhihu")
    return task_id


def _collect_zhihu_search_results(
    task_id: str | None,
    *,
    max_wait_seconds: float,
) -> tuple[list[dict[str, Any]], dict[str, int], str]:
    """等待 plugin 搜索任务并返回原始 Zhihu 候选。"""
    import json
    import time

    from openbiliclaw.sources.zhihu_tasks import ZhihuTaskQueue

    if not task_id:
        return [], {}, "skipped"

    try:
        database = _get_runtime_database()
    except Exception:
        return [], {}, "skipped"
    if not hasattr(database, "conn"):
        return [], {}, "skipped"

    queue = ZhihuTaskQueue(database)
    deadline = time.monotonic() + max(0.0, max_wait_seconds)
    task: dict[str, Any] | None = None
    while True:
        task = queue.get(task_id)
        status = str((task or {}).get("status", "")).strip()
        if status in {"completed", "failed"}:
            break
        if time.monotonic() >= deadline:
            break
        time.sleep(0.5)

    if not task:
        return [], {}, "timeout"
    if task.get("status") == "failed":
        try:
            result = json.loads(str(task.get("result_json") or "{}"))
        except json.JSONDecodeError:
            result = {}
        debug = result.get("debug", {}) if isinstance(result, dict) else {}
        error = str(result.get("error", "") if isinstance(result, dict) else "")
        if error == "zhihu_login_required" or (
            isinstance(debug, dict) and debug.get("login_required") is True
        ):
            return [], {}, "login_required"
        return [], {}, "failed"
    if task.get("status") != "completed":
        if str(task.get("status", "")).strip() in {"pending", "in_progress"}:
            with suppress(Exception):
                queue.fail(
                    task_id,
                    error="extension_result_timeout",
                    debug={
                        "wait_seconds": max_wait_seconds,
                        "last_status": str(task.get("status", "")),
                    },
                )
        return [], {}, "timeout"

    try:
        result = json.loads(str(task.get("result_json") or "{}"))
    except json.JSONDecodeError:
        return [], {}, "failed"

    items = [v for v in result.get("items", []) if isinstance(v, dict)]
    raw_counts = result.get("scope_counts", {})
    count = len(items)
    if isinstance(raw_counts, dict):
        with suppress(Exception):
            count = int(raw_counts.get("zhihu_search", count) or count)
    status_label = "ok" if items else "empty"
    return items, {"zhihu_search": count}, status_label


def _enqueue_zhihu_discovery_task(
    task_type: str,
    payload: dict[str, object],
    *,
    daily_budget_key: str,
) -> str | None:
    """入队非搜索类的 Zhihu 插件 discovery 任务。"""
    from openbiliclaw.config import load_config
    from openbiliclaw.sources.zhihu_tasks import ZhihuTaskQueue

    try:
        database = _get_runtime_database()
    except Exception as exc:
        console.print(f"  [yellow]知乎 {task_type} 任务未入队: 数据库不可用: {exc}[/yellow]")
        return None
    if not hasattr(database, "conn"):
        return None

    try:
        cfg = load_config()
        budget = int(getattr(getattr(cfg.sources, "zhihu", None), daily_budget_key, 0))
    except Exception:
        budget = 0

    try:
        queue = ZhihuTaskQueue(database)
        task_id = queue.enqueue_with_id(task_type, payload, daily_budget=budget)
    except Exception as exc:
        console.print(f"  [yellow]知乎 {task_type} 任务未入队: {exc}[/yellow]")
        return None
    if not task_id:
        console.print(f"  [yellow]知乎 {task_type} 任务未入队: 今日任务预算已用完。[/yellow]")
        return None
    _kick_task_dispatcher("zhihu")
    return task_id


def _collect_zhihu_discovery_results(
    task_id: str | None,
    *,
    max_wait_seconds: float,
) -> tuple[list[dict[str, Any]], dict[str, int], str]:
    """等待 Zhihu 插件 discovery 任务并返回原始候选。"""
    import json
    import time

    from openbiliclaw.sources.zhihu_tasks import ZhihuTaskQueue

    if not task_id:
        return [], {}, "skipped"
    try:
        database = _get_runtime_database()
    except Exception:
        return [], {}, "skipped"
    if not hasattr(database, "conn"):
        return [], {}, "skipped"

    queue = ZhihuTaskQueue(database)
    deadline = time.monotonic() + max(0.0, max_wait_seconds)
    task: dict[str, Any] | None = None
    while True:
        task = queue.get(task_id)
        status = str((task or {}).get("status", "")).strip()
        if status in {"completed", "failed"}:
            break
        if time.monotonic() >= deadline:
            break
        time.sleep(0.5)

    if not task:
        return [], {}, "timeout"
    if task.get("status") == "failed":
        try:
            result = json.loads(str(task.get("result_json") or "{}"))
        except json.JSONDecodeError:
            result = {}
        debug = result.get("debug", {}) if isinstance(result, dict) else {}
        error = str(result.get("error", "") if isinstance(result, dict) else "")
        if error == "zhihu_login_required" or (
            isinstance(debug, dict) and debug.get("login_required") is True
        ):
            return [], {}, "login_required"
        return [], {}, "failed"
    if task.get("status") != "completed":
        if str(task.get("status", "")).strip() in {"pending", "in_progress"}:
            with suppress(Exception):
                queue.fail(
                    task_id,
                    error="extension_result_timeout",
                    debug={
                        "wait_seconds": max_wait_seconds,
                        "last_status": str(task.get("status", "")),
                    },
                )
        return [], {}, "timeout"

    try:
        result = json.loads(str(task.get("result_json") or "{}"))
    except json.JSONDecodeError:
        return [], {}, "failed"
    items = [v for v in result.get("items", []) if isinstance(v, dict)]
    raw_counts = result.get("scope_counts", {})
    scope_counts = (
        {str(k): int(v) for k, v in raw_counts.items()} if isinstance(raw_counts, dict) else {}
    )
    return items, scope_counts, "ok" if items else "empty"


def _enqueue_zhihu_discovery_candidates(items: list[dict[str, Any]]) -> tuple[int, list[Any]]:
    """将 Zhihu 搜索结果行转换并入队到 discovery_candidates。"""
    from openbiliclaw.discovery.candidate_pool import discovered_content_to_candidate_write
    from openbiliclaw.sources.zhihu_tasks import zhihu_discovery_items_to_contents

    contents = zhihu_discovery_items_to_contents(items)
    if not contents:
        return 0, []
    database = _get_runtime_database()
    writes = [
        discovered_content_to_candidate_write(item, source_context=item.source_strategy)
        for item in contents
    ]
    enqueued = int(database.enqueue_discovery_candidates(writes))
    return enqueued, contents


def _enqueue_dy_search_task(
    keywords: tuple[str, ...],
    *,
    max_items_per_keyword: int = 20,
) -> str | None:
    """为浏览器扩展入队 Douyin 插件搜索任务。"""
    from openbiliclaw.sources.dy_tasks import DyTaskQueue

    normalized_keywords = []
    seen: set[str] = set()
    for keyword in keywords:
        value = str(keyword).strip()
        if not value or value in seen:
            continue
        seen.add(value)
        normalized_keywords.append(value)
    if not normalized_keywords:
        console.print("  [yellow]抖音搜索任务未入队: 关键词为空。[/yellow]")
        return None

    try:
        database = _get_runtime_database()
    except Exception as exc:
        console.print(f"  [yellow]抖音搜索任务未入队: 数据库不可用: {exc}[/yellow]")
        return None
    if not hasattr(database, "conn"):
        return None

    try:
        queue = DyTaskQueue(database)
        task_id = queue.enqueue_with_id(
            "search",
            {
                "keywords": normalized_keywords,
                "max_items_per_keyword": max(1, int(max_items_per_keyword)),
            },
            daily_budget=20,
        )
    except Exception as exc:
        console.print(f"  [yellow]抖音搜索任务未入队: {exc}[/yellow]")
        return None
    if not task_id:
        console.print("  [yellow]抖音搜索任务未入队: 今日任务预算已用完。[/yellow]")
        return None
    _kick_task_dispatcher("dy")
    return task_id


def _collect_dy_search_results(
    task_id: str | None,
    *,
    max_wait_seconds: float,
) -> tuple[list[dict[str, Any]], dict[str, int], str]:
    """等待插件搜索任务并返回原始 Douyin 视频候选。"""
    import json
    import time

    from openbiliclaw.sources.dy_tasks import DyTaskQueue

    if not task_id:
        return [], {}, "skipped"

    try:
        database = _get_runtime_database()
    except Exception:
        return [], {}, "skipped"
    if not hasattr(database, "conn"):
        return [], {}, "skipped"

    queue = DyTaskQueue(database)
    deadline = time.monotonic() + max(0.0, max_wait_seconds)
    task: dict[str, Any] | None = None
    while True:
        task = queue.get(task_id)
        status = str((task or {}).get("status", "")).strip()
        if status in {"completed", "failed"}:
            break
        if time.monotonic() >= deadline:
            break
        time.sleep(0.5)

    if not task:
        return [], {}, "timeout"
    if task.get("status") == "failed":
        return [], {}, "failed"
    if task.get("status") != "completed":
        return [], {}, "timeout"

    try:
        result = json.loads(str(task.get("result_json") or "{}"))
    except json.JSONDecodeError:
        return [], {}, "failed"

    videos = [v for v in result.get("videos", []) if isinstance(v, dict)]
    raw_counts = result.get("scope_counts", {})
    count = len(videos)
    if isinstance(raw_counts, dict):
        with suppress(Exception):
            count = int(raw_counts.get("dy_search", count) or count)
    status_label = "ok" if videos else "empty"
    return videos, {"dy_search": count}, status_label


def _dy_events_to_history_items(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """将 Douyin bootstrap 事件转换为 profile-builder history 行。

    镜像 ``_xhs_events_to_history_items`` —— 保留自然语言
    ``context`` 并打 ``source_platform=douyin`` 标签，
    以保证跨源分析一致。
    """
    rows: list[dict[str, Any]] = []
    for event in events:
        metadata = event.get("metadata", {})
        if not isinstance(metadata, dict):
            metadata = {}
        rows.append(
            {
                "title": str(event.get("title", "")).strip(),
                "url": str(event.get("url", "")).strip(),
                "author": str(metadata.get("author", "")).strip(),
                "event_type": str(event.get("event_type", "")).strip(),
                "context": str(event.get("context", "")).strip(),
                "metadata": metadata,
                "source_platform": "douyin",
            }
        )
    return [row for row in rows if row.get("title") or row.get("url")]


def _xhs_events_to_history_items(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """将 XHS bootstrap 事件转换为 profile-builder history 行。

    保留源事件中的自然语言 ``context`` 字段，以便下游选择
    context-aware 摘要的消费者使用。当前 profile_builder 的
    ``_summarize_history`` 不读 ``context``，但保持其完整流转
    让数据在跨源时一致，且不阻碍未来 analyzer 增强。
    """
    rows: list[dict[str, Any]] = []
    for event in events:
        metadata = event.get("metadata", {})
        if not isinstance(metadata, dict):
            metadata = {}
        rows.append(
            {
                "title": str(event.get("title", "")).strip(),
                "url": str(event.get("url", "")).strip(),
                "author": str(metadata.get("author", "")).strip(),
                "event_type": str(event.get("event_type", "")).strip(),
                # v0.3.22+：保留自然语言 context，让 history 列表
                # 与底层事件保持同一份 single-source-of-truth 描述。
                "context": str(event.get("context", "")).strip(),
                "metadata": metadata,
                "source_platform": "xiaohongshu",
            }
        )
    return [row for row in rows if row.get("title") or row.get("url")]


def _yt_events_to_history_items(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """将 YouTube bootstrap 事件转换为 profile-builder history 行。

    镜像 ``_xhs_events_to_history_items`` —— 保留自然语言
    ``context`` 并打 ``source_platform=youtube`` 标签以维持跨源分析一致。
    """
    rows: list[dict[str, Any]] = []
    for event in events:
        metadata = event.get("metadata", {})
        if not isinstance(metadata, dict):
            metadata = {}
        rows.append(
            {
                "title": str(event.get("title", "")).strip(),
                "url": str(event.get("url", "")).strip(),
                "author": str(metadata.get("author", "")).strip(),
                "event_type": str(event.get("event_type", "")).strip(),
                "context": str(event.get("context", "")).strip(),
                "metadata": metadata,
                "source_platform": "youtube",
            }
        )
    return [row for row in rows if row.get("title") or row.get("url")]


def _x_events_to_history_items(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """将 X (Twitter) init 事件转换为 profile-builder history 行。

    镜像 ``_xhs_events_to_history_items`` —— 保留自然语言
    ``context`` 并打 ``source_platform=twitter`` 标签。当 X 是
    选中（且为数不多）的 init 源之一时，让 profile builder 仍能取到数据。
    """
    rows: list[dict[str, Any]] = []
    for event in events:
        metadata = event.get("metadata", {})
        if not isinstance(metadata, dict):
            metadata = {}
        rows.append(
            {
                "title": str(event.get("title", "")).strip(),
                "url": str(event.get("url", "")).strip(),
                "author": str(metadata.get("author", "")).strip(),
                "event_type": str(event.get("event_type", "")).strip(),
                "context": str(event.get("context", "")).strip(),
                "metadata": metadata,
                "source_platform": "twitter",
            }
        )
    return [row for row in rows if row.get("title") or row.get("url")]


def _zhihu_events_to_history_items(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """将 Zhihu bootstrap 事件转换为 profile-builder history 行。"""
    rows: list[dict[str, Any]] = []
    for event in events:
        metadata = event.get("metadata", {})
        if not isinstance(metadata, dict):
            metadata = {}
        rows.append(
            {
                "title": str(event.get("title", "")).strip(),
                "url": str(event.get("url", "")).strip(),
                "author": str(metadata.get("author", "")).strip(),
                "event_type": str(event.get("event_type", "")).strip(),
                "context": str(event.get("context", "")).strip(),
                "metadata": metadata,
                "source_platform": "zhihu",
            }
        )
    return [row for row in rows if row.get("title") or row.get("url")]


@app.command("setup-embedding")
def setup_embedding() -> None:
    """配置本地 Ollama 作为 embedding 兜底服务（可选）.

    init 时已经问过；如果当时没启用、之后想加上，跑这条命令再走一次引导。
    """
    _print_page_title("配置本地 embedding", "Ollama + bge-m3")
    from openbiliclaw.config import load_config_with_diagnostics

    config, _ = load_config_with_diagnostics()
    _interactive_embedding_setup(config.llm.default_provider)


@app.command()
def cost(
    days: int = typer.Option(7, "--days", min=1, max=90, help="统计窗口(天)"),
    by: str = typer.Option(
        "all",
        "--by",
        help="单维度展开: all (默认 / 三表全显) / day / provider / caller",
    ),
) -> None:
    """显示本机 LLM 调用花费(按天 + 按 provider/model + 按 caller 模块)。

    数据来源:每次成功的 LLM 调用都会写一条到 ``llm_usage`` 表(v0.3.26+)。
    费用按 ``llm.pricing`` 里的官方单价估算,允许 ±20% 误差。本地 Ollama
    调用单价 0,只统计调用次数。

    ``--by caller`` 显示按模块(discovery / recommendation / soul / api 等)
    拆分的占比,这是排查"钱花在哪一层"最有用的视图。
    """
    _print_page_title("LLM 调用花费", f"最近 {days} 天")
    _ensure_runtime_database_healthy()
    db = _get_runtime_database()

    daily = db.query_llm_usage_by_day(days=days)
    by_provider = db.query_llm_usage_by_provider(days=days)
    by_caller = db.query_llm_usage_by_caller(days=days)
    total = db.query_llm_usage_total(days=days)

    if total["calls"] == 0:
        _print_status_panel(
            "info",
            "暂无数据",
            "这台机器最近没记录到 LLM 调用。\n"
            "如果你刚升级到 v0.3.26+,旧数据不会回填——继续运行一段时间后再来查。",
        )
        return

    show_all = by == "all"

    if show_all or by == "day":
        daily_table = Table(show_header=True, header_style="bold cyan", title="按天 (cost by day)")
        daily_table.add_column("日期", no_wrap=True)
        daily_table.add_column("调用数", justify="right")
        daily_table.add_column("input tokens", justify="right")
        daily_table.add_column("output tokens", justify="right")
        daily_table.add_column("¥ 估算", justify="right", style="bold yellow")
        for row in daily:
            daily_table.add_row(
                str(row["day"]),
                f"{row['calls']:,}",
                f"{row['prompt_tokens']:,}",
                f"{row['completion_tokens']:,}",
                f"¥{row['cost_cny']:.4f}",
            )
        console.print(daily_table)
        console.print()

    total_cost = total["cost_cny"] or 1e-9

    if show_all or by == "provider":
        provider_table = Table(
            show_header=True,
            header_style="bold magenta",
            title="按 Provider/Model (cost by provider)",
        )
        provider_table.add_column("Provider", no_wrap=True)
        provider_table.add_column("Model")
        provider_table.add_column("调用数", justify="right")
        provider_table.add_column("input", justify="right")
        provider_table.add_column("output", justify="right")
        provider_table.add_column("¥ 占比", justify="right", style="bold yellow")
        for row in by_provider:
            share = row["cost_cny"] / total_cost * 100
            provider_table.add_row(
                row["provider"] or "?",
                row["model"] or "(default)",
                f"{row['calls']:,}",
                f"{row['prompt_tokens']:,}",
                f"{row['completion_tokens']:,}",
                f"¥{row['cost_cny']:.4f} ({share:.0f}%)",
            )
        console.print(provider_table)
        console.print()

    if show_all or by == "caller":
        caller_table = Table(
            show_header=True,
            header_style="bold green",
            title="按模块 (cost by caller — 钱花在哪一层 / cache 命中率)",
        )
        caller_table.add_column("Caller (模块.动作)", no_wrap=True)
        caller_table.add_column("调用数", justify="right")
        caller_table.add_column("input", justify="right")
        caller_table.add_column("output", justify="right")
        # v0.3.28+: cache hit rate per caller. Low hit rate (red) on a
        # high-cost caller is the smoking gun for prompt-prefix
        # instability — that's where to focus prompt-builder audits.
        caller_table.add_column("cache 命中", justify="right")
        caller_table.add_column("¥ 占比", justify="right", style="bold yellow")
        for row in by_caller:
            share = row["cost_cny"] / total_cost * 100
            prompt_tok = int(row["prompt_tokens"])
            cached_tok = int(row.get("cached_input_tokens", 0) or 0)
            if prompt_tok > 0 and cached_tok > 0:
                hit_pct = cached_tok / prompt_tok * 100
                if hit_pct < 30:
                    cache_cell = f"[red]{hit_pct:.0f}%[/red]"
                elif hit_pct < 60:
                    cache_cell = f"[yellow]{hit_pct:.0f}%[/yellow]"
                else:
                    cache_cell = f"[green]{hit_pct:.0f}%[/green]"
                cache_cell += f" ({cached_tok:,}/{prompt_tok:,})"
            else:
                cache_cell = "[dim]—[/dim]"
            caller_table.add_row(
                row["caller"] or "[dim](untagged)[/dim]",
                f"{row['calls']:,}",
                f"{row['prompt_tokens']:,}",
                f"{row['completion_tokens']:,}",
                cache_cell,
                f"¥{row['cost_cny']:.4f} ({share:.0f}%)",
            )
        console.print(caller_table)
        console.print()

    avg_per_day = total["cost_cny"] / max(1, len(daily))
    total_prompt = int(total["prompt_tokens"])
    total_cached = int(total.get("cached_input_tokens", 0) or 0)
    cache_summary = ""
    if total_prompt > 0 and total_cached > 0:
        overall_hit = total_cached / total_prompt * 100
        cache_summary = (
            f"\ncache 命中: [bold green]{overall_hit:.1f}%[/bold green] "
            f"({total_cached:,}/{total_prompt:,} input tokens served from cache)"
        )
    elif total_prompt > 0:
        cache_summary = "\ncache 命中: [dim]0%(还没命中或 provider 不上报 cache 字段)[/dim]"
    _print_status_panel(
        "info",
        f"近 {days} 天合计",
        f"总调用 [bold]{total['calls']:,}[/bold] 次, "
        f"总 token [bold]{total['total_tokens']:,}[/bold] "
        f"(input {total['prompt_tokens']:,} + output {total['completion_tokens']:,}), "
        f"估算消耗 [bold yellow]¥{total['cost_cny']:.4f}[/bold yellow]"
        f"{cache_summary}\n"
        f"按记录到的天数平均 ≈ ¥{avg_per_day:.4f}/天 ≈ "
        f"¥{avg_per_day * 30:.2f}/月\n"
        "[dim]（费率为公开渠道估算,与 provider 实际账单可能差 ±20%。"
        "tail daemon 日志可以看每次调用的实时 [llm-cost] INFO 行,"
        "cache 命中率 < 30% 的 caller 在 by-caller 表里会标红。）[/dim]",
    )


@app.command("logs-prune")
def logs_prune(
    truncate_mb: int = typer.Option(
        200,
        "--truncate-mb",
        min=0,
        help="单个 unmanaged 日志文件超过此 MB 数则截断为 0 字节(0 = 关闭)",
    ),
    max_age_days: int = typer.Option(
        30,
        "--max-age-days",
        min=0,
        help="超过此天数的 unmanaged 日志文件直接删除(0 = 关闭)",
    ),
    aggregate_budget_mb: int = typer.Option(
        500,
        "--aggregate-budget-mb",
        min=0,
        help="logs/ 目录(含 unmanaged + managed)总磁盘预算 MB,超出时按 mtime 从旧到新删 unmanaged",
    ),
    apply: bool = typer.Option(
        False,
        "--apply",
        help="实际执行删除/截断;默认是 dry-run 模式只列出会改什么",
    ),
) -> None:
    """手动 prune logs/ 目录的日志文件(默认 dry-run)。

    daemon 启动时已经会按 config 自动跑这套清理(v0.3.30+),这个命令是
    手动触发用的 —— 比如 daemon 没在运行 / 想查看会删什么 / 临时换一组
    更激进或更保守的阈值。
    """
    import time as _time

    from openbiliclaw.config import load_config
    from openbiliclaw.logging_setup import _is_managed_log

    config = load_config()
    log_dir = config.logging.directory_path
    managed = config.logging.filename

    _print_page_title("LLM 日志清理 (logs prune)", str(log_dir))
    if not log_dir.exists():
        _print_status_panel("warning", "日志目录不存在", f"{log_dir} 还没创建。")
        return

    truncate_bytes = truncate_mb * 1024 * 1024
    age_cutoff = _time.time() - max_age_days * 86400 if max_age_days > 0 else 0.0
    budget_bytes = aggregate_budget_mb * 1024 * 1024

    actions: list[tuple[str, str, int]] = []  # (action, path, size)
    total = 0
    for path in sorted(log_dir.iterdir()):
        if not path.is_file():
            continue
        try:
            st = path.stat()
        except OSError:
            continue
        total += st.st_size
        is_managed = _is_managed_log(path, managed)
        tag = "managed" if is_managed else "unmanaged"
        if is_managed:
            actions.append(("keep", f"{path.name}  [{tag}]", st.st_size))
            continue
        if truncate_mb > 0 and st.st_size >= truncate_bytes:
            actions.append(
                (
                    "truncate",
                    f"{path.name}  [{tag}, > {truncate_mb} MB]",
                    st.st_size,
                )
            )
            continue
        if max_age_days > 0 and st.st_mtime < age_cutoff:
            age_days = (_time.time() - st.st_mtime) / 86400
            actions.append(
                (
                    "delete (age)",
                    f"{path.name}  [{tag}, {age_days:.0f} days old]",
                    st.st_size,
                )
            )
            continue
        actions.append(("keep", f"{path.name}  [{tag}]", st.st_size))

    # 总预算扫描：模拟驱逐最旧的未托管 'keep' 行
    if aggregate_budget_mb > 0 and total > budget_bytes:
        # 把尚未被裁掉的未托管行按 mtime 重新排序
        unmanaged_keep: list[tuple[Path, float, int, int]] = []
        for i, (action, label, size) in enumerate(actions):
            if action != "keep" or "[managed]" in label:
                continue
            name = label.split("  ")[0]
            try:
                st = (log_dir / name).stat()
            except OSError:
                continue
            unmanaged_keep.append((log_dir / name, st.st_mtime, size, i))
        unmanaged_keep.sort(key=lambda x: x[1])
        running = total
        for path, _mt, size, idx in unmanaged_keep:
            if running <= budget_bytes:
                break
            actions[idx] = (
                "delete (budget)",
                f"{path.name}  [unmanaged, oldest, evict to fit {aggregate_budget_mb} MB]",
                size,
            )
            running -= size

    table = Table(
        show_header=True,
        header_style="bold cyan",
        title=f"Plan ({'APPLY' if apply else 'DRY-RUN'})",
    )
    table.add_column("Action", no_wrap=True)
    table.add_column("File", overflow="fold")
    table.add_column("Size", justify="right")
    for action, label, size in actions:
        size_h = f"{size / (1024 * 1024):.1f} MB"
        style = "green" if action == "keep" else "yellow" if action == "truncate" else "red"
        table.add_row(f"[{style}]{action}[/{style}]", label, size_h)
    console.print(table)

    will_change = [a for a in actions if a[0] != "keep"]
    freed = sum(s for action, _, s in actions if action.startswith("delete")) + sum(
        s - 1
        for action, _, s in actions
        if action == "truncate"  # leaves ~1 byte stub
    )
    console.print(
        f"\n会释放约 [bold]{freed / (1024 * 1024):.1f} MB[/bold] 磁盘"
        f" / 影响 [bold]{len(will_change)}[/bold] 个文件"
    )

    if not apply:
        console.print("\n[yellow]这是 dry-run。加上 --apply 才会真的改文件。[/yellow]")
        return

    # 应用
    import time as _time2

    actually_freed = 0
    for action, label, size in actions:
        name = label.split("  ")[0]
        path = log_dir / name
        if action == "truncate":
            try:
                with path.open("w", encoding="utf-8") as f:
                    f.write(
                        f"# truncated by `openbiliclaw logs-prune` "
                        f"{_time2.strftime('%Y-%m-%d %H:%M:%S')} — was "
                        f"{size / (1024 * 1024):.0f} MB\n"
                    )
                actually_freed += size
            except OSError as exc:
                console.print(f"[red][X] truncate {path}: {exc}[/red]")
        elif action.startswith("delete"):
            try:
                path.unlink()
                actually_freed += size
            except OSError as exc:
                console.print(f"[red][X] unlink {path}: {exc}[/red]")
    freed_mb = actually_freed / (1024 * 1024)
    console.print(f"\n[bold green][OK] Applied — actually freed {freed_mb:.1f} MB[/bold green]")


@app.command()
def start(
    host: str = typer.Option("", "--host", help="API 监听地址（默认读 config.toml [api].host）"),
    port: int = typer.Option(
        0, "--port", min=0, max=65535, help="API 监听端口（默认读 config.toml [api].port）"
    ),
) -> None:
    """启动 OpenBiliClaw Agent."""
    from openbiliclaw.config import load_config

    cfg = load_config()
    effective_host = host if host else cfg.api.host
    effective_port = port if port else cfg.api.port
    _print_page_title("启动 OpenBiliClaw", "本地 API 服务")
    _ensure_runtime_database_healthy()
    _print_status_panel(
        "info",
        "API 服务",
        f"正在启动本地后端，当前监听 {effective_host}:{effective_port}。",
    )
    _warn_if_pause_on_disconnect_requires_presence()
    if cfg.api.auth.enabled:
        _print_status_panel(
            "info",
            "[LOCK] 访问控制",
            "局域网/远程访问已启用密码登录（本机访问免登录）。",
        )
        if cfg.api.auth.trust_loopback and not cfg.api.auth.trusted_proxies:
            _print_status_panel(
                "warning",
                "反向代理提醒",
                "如部署在同机反向代理后，请配置 [api.auth].trusted_proxies"
                "（并确保代理覆盖而非透传客户端转发头），或让代理自行鉴权，"
                "否则远程请求可能被误判为本机而绕过密码。",
            )
    _maybe_create_runtime_database_backup()
    _preflight_loopback_ollama(cfg)
    _self_heal_autostart_registration(cfg)
    _run_api_server(host=effective_host, port=effective_port)


def _bump_auth_epoch(cfg: Any) -> bool:
    """在运行时 DB 中提升 revocation epoch（立即 logout-all）。"""
    from openbiliclaw.storage.database import Database

    db = Database(cfg.data_path / "openbiliclaw.db")
    try:
        db.initialize()
        db.bump_auth_epoch()
        return True
    except Exception:
        return False
    finally:
        with suppress(Exception):
            db.close()


def _rebase_auth_fingerprint(cfg: Any) -> None:
    """在 cfg 当前签名 secret 之下重新存储密码指纹。

    在 ``--rotate-secret`` 之后调用，让下一次启动 reconcile 时
    看到的就是它自己（用新 secret）会算出来的指纹，从而不会在
    我们已经 bump 之上再做一次冗余 epoch bump。Best-effort：
    若 DB 不可写，我们就保留旧指纹，代价仅是重启时多一次
    无害的 reconcile bump。见 ``set_password_fingerprint``。
    """
    from openbiliclaw.auth_core import password_fingerprint
    from openbiliclaw.config import get_auth_plain_password
    from openbiliclaw.storage.database import Database

    auth = cfg.api.auth
    if not (auth.password_hash.strip() and auth.session_secret.strip()):
        return
    fingerprint = password_fingerprint(
        auth.session_secret,
        plain=get_auth_plain_password(),
        password_hash=auth.password_hash,
    )
    db = Database(cfg.data_path / "openbiliclaw.db")
    try:
        db.initialize()
        db.set_password_fingerprint(fingerprint)
    except Exception:
        # Best-effort：旧指纹只带来一次无害的 reconcile bump。
        pass
    finally:
        with suppress(Exception):
            db.close()


def _autostart_reason_message(reason: str) -> str:
    if reason == "unsupported_docker_runtime":
        return "当前在 Docker / 容器环境中，不支持注册桌面登录自启动。"
    if reason == "unsupported_platform":
        return "当前平台暂不支持开机自启动。"
    if reason == "env_managed":
        return "检测到环境变量配置，登录会话可能拿不到这些值；请先写入 config.toml。"
    if reason == "shadowed":
        return "config.local.toml 正在覆盖 [autostart].enabled，config.toml 修改不会生效。"
    if reason == "registration_failed":
        return "系统自启动注册失败，config 已回滚。"
    if reason == "unregister_failed":
        return "系统自启动注销失败，config 未修改。"
    return "无法完成开机自启动操作。"


def _autostart_status_rows(cfg: Any) -> list[tuple[str, str]]:
    from openbiliclaw.runtime import autostart

    state = autostart.status()
    enabled = bool(getattr(getattr(cfg, "autostart", None), "enabled", False))
    manage_ollama = bool(getattr(getattr(cfg, "autostart", None), "manage_ollama", True))
    return [
        ("配置", "开启" if enabled else "关闭"),
        ("系统注册", "已注册" if state.registered else "未注册"),
        ("支持状态", "支持" if state.supported else "不支持"),
        ("平台", state.platform),
        ("机制", state.mechanism),
        ("原因", state.reason),
        ("Ollama 预检", "开启" if manage_ollama else "关闭"),
    ]


def _print_autostart_status(cfg: Any) -> None:
    _print_page_title("开机自启动", "登录系统时自动拉起 OpenBiliClaw 后端")
    _print_key_value_table("自启动状态", _autostart_status_rows(cfg))


def _format_autostart_config_status(cfg: Any) -> str:
    from openbiliclaw.runtime import autostart

    try:
        state = autostart.status()
    except Exception:
        return "开启" if bool(getattr(cfg.autostart, "enabled", False)) else "关闭"
    enabled = "开启" if bool(getattr(cfg.autostart, "enabled", False)) else "关闭"
    registered = "已注册" if state.registered else "未注册"
    return f"{enabled}（{registered}，{state.mechanism}）"


def _autostart_manager_or_exit() -> Any:
    from openbiliclaw.runtime import autostart

    manager = autostart.get_manager()
    if manager is not None:
        return manager
    reason = autostart.status().reason
    _print_status_panel("error", "当前环境不支持开机自启动", _autostart_reason_message(reason))
    raise typer.Exit(code=1)


def _save_autostart_authoritative(cfg: Any) -> None:
    from openbiliclaw.config import save_config

    save_config(cfg, autostart_authoritative=True)


def _restore_autostart_enabled(cfg: Any, enabled: bool) -> None:
    cfg.autostart.enabled = enabled
    with suppress(Exception):
        _save_autostart_authoritative(cfg)


def _register_autostart_best_effort(manager: Any, cfg: Any, should_register: bool) -> None:
    if should_register:
        with suppress(Exception):
            manager.register(cfg)


@autostart_app.command("status")
def autostart_status() -> None:
    """显示开机自启动状态。"""
    from openbiliclaw.config import load_config

    _print_autostart_status(load_config())


@autostart_app.command("enable")
def autostart_enable() -> None:
    """开启登录系统后自动拉起后端。"""
    from openbiliclaw.config import load_config
    from openbiliclaw.runtime.autostart.guards import (
        active_env_managed_inputs,
        autostart_shadowed,
    )

    cfg = load_config()
    manager = _autostart_manager_or_exit()
    managed = active_env_managed_inputs(cfg)
    if managed:
        _print_status_panel(
            "error",
            "检测到环境变量配置，无法开启自启动",
            f"{_autostart_reason_message('env_managed')}\n命中：{', '.join(managed)}",
        )
        raise typer.Exit(code=1)

    previous_enabled = bool(cfg.autostart.enabled)
    cfg.autostart.enabled = True
    try:
        _save_autostart_authoritative(cfg)
    except Exception as exc:
        cfg.autostart.enabled = previous_enabled
        _print_status_panel("error", "配置保存失败", str(exc))
        raise typer.Exit(code=1) from exc

    if autostart_shadowed(True):
        _restore_autostart_enabled(cfg, previous_enabled)
        _print_status_panel("error", "配置被覆盖", _autostart_reason_message("shadowed"))
        raise typer.Exit(code=1)

    try:
        manager.register(cfg)
    except Exception as exc:
        _restore_autostart_enabled(cfg, previous_enabled)
        _print_status_panel(
            "error",
            "自启动注册失败",
            f"{_autostart_reason_message('registration_failed')}\n{exc}",
        )
        raise typer.Exit(code=1) from exc

    _print_status_panel(
        "success",
        "已开启开机自启动",
        "下次登录系统时会拉起 OpenBiliClaw 后端；当前进程不会被启停。",
    )
    _print_autostart_status(cfg)


@autostart_app.command("disable")
def autostart_disable() -> None:
    """关闭登录系统后自动拉起后端。"""
    from openbiliclaw.config import load_config
    from openbiliclaw.runtime.autostart.guards import autostart_shadowed

    cfg = load_config()
    manager = _autostart_manager_or_exit()
    previous_enabled = bool(cfg.autostart.enabled)
    was_registered = bool(manager.is_registered())

    try:
        manager.unregister()
    except Exception as exc:
        _print_status_panel(
            "error",
            "自启动注销失败",
            f"{_autostart_reason_message('unregister_failed')}\n{exc}",
        )
        raise typer.Exit(code=1) from exc

    cfg.autostart.enabled = False
    try:
        _save_autostart_authoritative(cfg)
    except Exception as exc:
        cfg.autostart.enabled = previous_enabled
        _register_autostart_best_effort(manager, cfg, was_registered)
        _restore_autostart_enabled(cfg, previous_enabled)
        _print_status_panel("error", "配置保存失败", str(exc))
        raise typer.Exit(code=1) from exc

    if autostart_shadowed(False):
        cfg.autostart.enabled = previous_enabled
        _register_autostart_best_effort(manager, cfg, was_registered)
        _restore_autostart_enabled(cfg, previous_enabled)
        _print_status_panel("error", "配置被覆盖", _autostart_reason_message("shadowed"))
        raise typer.Exit(code=1)

    _print_status_panel(
        "success",
        "已关闭开机自启动",
        "系统登录项已移除；当前后端进程不会被停止。",
    )
    _print_autostart_status(cfg)


@app.command("set-password")
def set_password(
    disable: bool = typer.Option(False, "--disable", help="关闭密码门禁"),
    logout_all: bool = typer.Option(
        False, "--logout-all", help="使所有设备的登录态立即失效（不改密码/密钥）"
    ),
    rotate_secret: bool = typer.Option(
        False, "--rotate-secret", help="轮换会话签名密钥（最强撤销，需重启后端生效）"
    ),
) -> None:
    """设置 / 修改局域网访问密码（或关闭门禁 / 登出所有设备）。"""
    import secrets as _secrets

    from openbiliclaw.auth_core import hash_password
    from openbiliclaw.config import load_config, save_config

    cfg = load_config()

    if logout_all:
        # 仅在 DB 中吊销 —— 始终生效,与 env/config 来源无关。
        ok = _bump_auth_epoch(cfg)
        _print_status_panel(
            "success" if ok else "error",
            "已登出所有设备" if ok else "操作失败",
            "所有设备需重新登录。"
            if ok
            else "无法访问运行库、未能撤销，请确认 data 目录可写后重试。",
        )
        if not ok:
            raise typer.Exit(code=1)
        return

    # 下面的写配置路径都会调用 save_config(cfg),它会写入整个
    # [api.auth] 块。cfg 来自 load_config(),其中环境变量优先级
    # 高于 config.toml —— 因此任何 auth 环境变量覆盖都会
    # (a) 在重启时被重新应用(文件编辑被静默丢失),并且
    # (b) 被原样写入 config.toml,一旦环境变量后续被移除,
    # 就会留下一个过期值(这可能悄然改变 trust boundary /
    # session lifetime)。在完整的 override 表面上都要明确拒绝
    # —— 不仅仅是 password —— 并告诉用户去管理
    # 改为通过 env 管理(review r3#2)。`--logout-all` 已在上面 return,因此
    # 即使在 env 管理期间也仍可用于紧急吊销。
    from openbiliclaw.config import API_AUTH_ENV_VARS

    _auth_env = [name for name in API_AUTH_ENV_VARS if (os.environ.get(name) or "").strip()]
    if _auth_env:
        _print_status_panel(
            "error",
            "检测到环境变量覆盖，config 修改不会生效",
            f"已设置 {', '.join(_auth_env)}；load_config 中环境变量优先于 config.toml，"
            "改写文件重启后仍会用旧的环境变量值。请改这些环境变量并重启后端；"
            "如只想立即失效现有登录态，用 `openbiliclaw set-password --logout-all`。",
        )
        raise typer.Exit(code=1)

    # config.local.toml 会合并覆盖 config.toml（local 优先）。若它固定了
    # set-password 写入的任何凭据字段，我们对 config.toml 的修改会在
    # 重启时被静默回滚——大声拒绝而非报虚假成功（r9）。
    from openbiliclaw.config import config_local_auth_keys

    _local_keys = sorted(
        config_local_auth_keys() & {"password", "password_hash", "enabled", "session_secret"}
    )
    if _local_keys:
        _print_status_panel(
            "error",
            "config.local.toml 覆盖了 [api.auth] 字段，config.toml 修改不会生效",
            f"config.local.toml 中设置了 {', '.join(_local_keys)}；它会盖过 config.toml，"
            "改写后者重启后仍会被覆盖。请改 config.local.toml 并重启后端；"
            "如只想立即失效现有登录态，用 `openbiliclaw set-password --logout-all`。",
        )
        raise typer.Exit(code=1)

    if disable:
        cfg.api.auth.enabled = False
        save_config(cfg)
        _print_status_panel("success", "已关闭密码门禁", "重启后端 (openbiliclaw start) 后生效。")
        return

    if rotate_secret:
        cfg.api.auth.session_secret = _secrets.token_urlsafe(32)
        save_config(cfg)
        revoked = _bump_auth_epoch(cfg)
        if not revoked:
            _print_status_panel(
                "error",
                "密钥已轮换，但未能立即撤销",
                "新密钥已写入 config，但运行库不可写、现有登录态未即时失效。"
                "请重启后端使其生效，或修复 data 目录后重试。",
            )
            raise typer.Exit(code=1)
        # 在新 secret 下重新落库指纹，让下次重启的 reconcile 不会
        # 在我们已经做过的 bump 之上再补一次冗余 epoch bump。
        _rebase_auth_fingerprint(cfg)
        _print_status_panel(
            "success",
            "已轮换会话密钥",
            "所有设备需重新登录；重启后端使新密钥完全生效。",
        )
        return

    if not _is_interactive_terminal():
        _print_status_panel(
            "error",
            "无法设置密码",
            "请在交互式终端运行，或用 OPENBILICLAW_API_AUTH_PASSWORD 环境变量配置。",
        )
        raise typer.Exit(code=1)

    password = str(
        typer.prompt("设置访问密码", hide_input=True, confirmation_prompt=True) or ""
    ).strip()
    if not password:
        _print_status_panel("error", "密码为空", "未做更改。")
        raise typer.Exit(code=1)

    cfg.api.auth.password_hash = hash_password(password)
    cfg.api.auth.enabled = True
    if not cfg.api.auth.session_secret.strip():
        cfg.api.auth.session_secret = _secrets.token_urlsafe(32)
    save_config(cfg)
    # 立即吊销所有现有会话（由任何运行中的后端从 SQLite 实时读取），
    # 以便密码轮换后不会让旧 cookie 一直有效到下次重启。新密码本身
    # 要等后端重新加载配置才生效，因此才有那条重启提示。
    revoked = _bump_auth_epoch(cfg)
    if not revoked:
        _print_status_panel(
            "error",
            "密码已保存，但未能立即撤销现有登录态",
            "新密码已写入 config，但运行库不可写、现有 cookie 未即时失效（仍可能有效到重启）。"
            "请重启后端使其生效，或修复 data 目录后重跑 `set-password`。",
        )
        raise typer.Exit(code=1)
    _print_status_panel(
        "success",
        "已设置访问密码",
        "已立即失效所有现有登录态。请重启后端 (openbiliclaw start) 使新密码生效"
        "（运行中的进程仍持旧配置，重启前请勿依赖新密码已启用）。",
    )


@app.command("serve-api")
def serve_api(
    host: str = typer.Option("0.0.0.0", "--host", help="API 监听地址"),
    port: int = typer.Option(8420, "--port", min=1, max=65535, help="API 监听端口"),
) -> None:
    """启动容器友好的 API 服务入口."""
    _print_page_title("启动 OpenBiliClaw", "容器 API 服务")
    _print_status_panel(
        "info",
        "API 服务",
        f"正在启动容器友好的后端入口，当前监听 {host}:{port}。",
    )
    _warn_if_pause_on_disconnect_requires_presence()
    _run_api_server(host=host, port=port)


@app.command("db-repair")
def db_repair() -> None:
    """检查并修复本地 SQLite 数据库。"""
    result = _run_db_repair()
    console.print(result.message)
    if getattr(result, "db_backup", None) is not None:
        console.print(f"备份文件: {result.db_backup}")
    if getattr(result, "wal_backup", None) is not None:
        console.print(f"WAL 备份: {result.wal_backup}")
    if getattr(result, "repaired_db", None) is not None:
        console.print(f"恢复副本: {result.repaired_db}")
    if result.status in {"in_use", "failed"}:
        raise typer.Exit(code=1)


def _ask_xhs_inclusion() -> bool:
    """决定本次 init 是否要入队 xhs bootstrap 任务。

    解析顺序(第一个匹配的获胜):
      1. ``OPENBILICLAW_NO_XHS=1`` 环境变量 → False,静默
      2. 非交互式终端(CI / 管道 stdin)→ False,静默。
      3. 交互式终端 → 用默认值 N 询问用户,然后
         (若 Y)引导他们过一遍 prep checklist。

    当调用方应继续执行 xhs bootstrap 时返回 True。
    """
    if os.environ.get("OPENBILICLAW_NO_XHS", "").strip() == "1":
        console.print("[dim]  跳过小红书数据接入(OPENBILICLAW_NO_XHS=1)。[/dim]")
        return False
    if not _is_interactive_terminal():
        return False

    console.print()
    console.print("[bold][BLOOM] 小红书数据接入(可选)[/bold]")
    console.print(
        "把你的小红书[bold cyan]收藏 / 点赞[/bold cyan]混进画像,"
        "系统能读懂你跨平台的口味——\n"
        "你刷小红书喜欢的领域(咖啡 / 摄影 / 穿搭…)也会反映到 B 站推荐里。"
    )
    console.print()
    console.print("启用需要:")
    console.print("  1. 装好 OpenBiliClaw 浏览器扩展")
    console.print(
        "     [link=https://github.com/whiteguo233/OpenBiliClaw/releases]"
        "https://github.com/whiteguo233/OpenBiliClaw/releases[/link]"
    )
    console.print(
        "  2. 浏览器登录 [link=https://www.xiaohongshu.com]https://www.xiaohongshu.com[/link]"
    )
    console.print()
    console.print(
        "[dim]说 N 也没关系,init 只用 B 站数据建画像;以后想加随时再跑一次 init,"
        "或设 OPENBILICLAW_NO_XHS=1 永久跳过。[/dim]"
    )
    console.print()

    if not typer.confirm("加入小红书数据?", default=False):
        console.print("[dim]  已选择跳过,本次 init 不会请求扩展。[/dim]")
        return False

    # 用户答 yes —— 在调用扩展前先走一遍准备清单。
    # bootstrap 任务内置 30-60s 超时，所以即便用户说"好了"但实际没好，
    # collect 步骤会优雅降级（status="empty"/"timeout"），init 仍能
    # 仅靠 B 站数据完成。
    console.print()
    console.print("[bold]准备小红书接入[/bold]")
    console.print("请确认以下三件事都做了:")
    console.print("  [cyan][ ][/cyan] 装好了 OpenBiliClaw 浏览器扩展")
    console.print(
        "  [cyan][ ][/cyan] 浏览器目前是打开的且是当前 [bold]活跃窗口[/bold]"
        "(扩展需要前台 tab 才能触发小红书的瀑布流懒加载)"
    )
    console.print("  [cyan][ ][/cyan] 已经登录了 https://www.xiaohongshu.com")
    console.print()
    console.print(
        "[bold yellow][!][/bold yellow]  接下来扩展会[bold]在你的浏览器里自动打开"
        "一个新 tab[/bold]并切到那个 tab(会抢一次焦点),进到你的小红书 profile 页"
        "向下滚动加载收藏/点赞。整个过程 10-30 秒。"
    )
    console.print(
        "[dim]   — 期间不要关那个 tab、不要切走太久(可能影响滚动加载)。"
        "完成后扩展会自动关闭它,焦点还回来。[/dim]"
    )
    console.print(
        "[dim]   — 想跳过焦点抢占的话:Ctrl-C 退出,改用 "
        "`OPENBILICLAW_XHS_BOOTSTRAP_SCROLL_ROUNDS=0 openbiliclaw init` "
        "拿浅层数据(只读初始 state,无前台 tab,但只能拿到 ~10-20 条)。[/dim]"
    )
    console.print()
    if not typer.confirm("准备好了吗,可以开始吗?", default=True):
        console.print(
            "[dim]  已暂缓小红书接入,本次 init 只用 B 站数据。装好扩展+登录"
            "小红书后随时再跑一次 init 就能补上。[/dim]"
        )
        return False
    return True


def _ask_dy_inclusion() -> bool:
    """决定是否在本次 init 中入队 Douyin bootstrap 任务。

    解析顺序（首个命中即生效）：
      1. ``OPENBILICLAW_NO_DOUYIN=1`` 环境变量 → False，静默
      2. 非交互式终端（CI / piped stdin） → **False**，静默。
         保守默认。因为抖音风控更激进，若用户实际未登录，
         软反爬会返回 HTTP 200 + 空 body（design-doc Risk #7），
         只有 bootstrap 跑完才能识别。对 Douyin 而言显式 opt-in
         比每次 CI 都自动触发更稳妥。
      3. 交互式终端 → 询问用户，默认 N；若答 Y 则走一遍准备清单。
    """
    if os.environ.get("OPENBILICLAW_NO_DOUYIN", "").strip() == "1":
        console.print("[dim]  跳过抖音数据接入(OPENBILICLAW_NO_DOUYIN=1)。[/dim]")
        return False
    if not _is_interactive_terminal():
        return False

    console.print()
    console.print("[bold][MUSIC] 抖音数据接入(可选)[/bold]")
    console.print(
        "把你的抖音[bold cyan]发布 / 收藏 / 点赞 / 关注[/bold cyan]混进画像,"
        "系统能读懂你跨平台的口味——\n"
        "你刷抖音常停留的领域(美食 / 历史 / 知识区…)也会反映到 B 站推荐里。"
    )
    console.print()
    console.print("启用需要:")
    console.print("  1. 装好 OpenBiliClaw 浏览器扩展")
    console.print(
        "     [link=https://github.com/whiteguo233/OpenBiliClaw/releases]"
        "https://github.com/whiteguo233/OpenBiliClaw/releases[/link]"
    )
    console.print("  2. 浏览器登录 [link=https://www.douyin.com]https://www.douyin.com[/link]")
    console.print()
    console.print(
        "[dim]说 N 也没关系,init 会用 B 站(+小红书,如启用)数据建画像;"
        "以后想加随时再跑一次 init,或设 OPENBILICLAW_NO_DOUYIN=1 永久跳过。[/dim]"
    )
    console.print()

    if not typer.confirm("加入抖音数据?", default=False):
        console.print("[dim]  已选择跳过,本次 init 不会请求抖音数据。[/dim]")
        return False

    console.print()
    console.print("[bold]准备抖音接入[/bold]")
    console.print("请确认以下三件事都做了:")
    console.print("  [cyan][ ][/cyan] 装好了 OpenBiliClaw 浏览器扩展")
    console.print(
        "  [cyan][ ][/cyan] 浏览器目前是打开的且是当前 [bold]活跃窗口[/bold]"
        "(扩展需要前台 tab 才能让抖音的虚拟列表分页加载)"
    )
    console.print("  [cyan][ ][/cyan] 已经登录了 https://www.douyin.com")
    console.print()
    console.print(
        "[bold yellow][!][/bold yellow]  接下来扩展会[bold]在你的浏览器里自动打开"
        "一个新 tab[/bold]并切到那个 tab(会抢一次焦点),依次访问 4 个 profile sub-tab"
        "(发布 / 收藏 / 点赞 / 关注)向下滚动加载。整个过程 30-90 秒。"
    )
    console.print(
        "[dim]   — 期间不要关那个 tab、不要切走太久(可能影响虚拟列表分页)。"
        "完成后扩展会自动关闭它,焦点还回来。[/dim]"
    )
    console.print(
        "[dim]   — 想跳过焦点抢占的话:Ctrl-C 退出,改用 "
        "`OPENBILICLAW_DY_BOOTSTRAP_SCROLL_ROUNDS=0 openbiliclaw init` "
        "拿浅层数据。[/dim]"
    )
    console.print()
    if not typer.confirm("准备好了吗,可以开始吗?", default=True):
        console.print(
            "[dim]  已暂缓抖音接入,本次 init 不会拉抖音数据。装好扩展+登录"
            "抖音后随时再跑一次 init 就能补上。[/dim]"
        )
        return False
    return True


def _ask_yt_inclusion() -> bool:
    """决定是否在本次 init 中入队 YouTube bootstrap 任务。

    解析顺序（首个命中即生效）：
      1. ``OPENBILICLAW_NO_YOUTUBE=1`` 环境变量 → False，静默
      2. 非交互式终端（CI / piped stdin） → **False**，静默。
         保守默认——YouTube 需要浏览器登录与焦点。
      3. 交互式终端 → 询问用户，默认 N；若答 Y 则走一遍准备清单。
    """
    if os.environ.get("OPENBILICLAW_NO_YOUTUBE", "").strip() == "1":
        console.print("[dim]  跳过 YouTube 数据接入(OPENBILICLAW_NO_YOUTUBE=1)。[/dim]")
        return False
    if not _is_interactive_terminal():
        return False

    console.print()
    console.print("[bold]▶ YouTube 数据接入(可选)[/bold]")
    console.print(
        "把你的 YouTube[bold cyan]观看历史 / 订阅 / 点赞[/bold cyan]混进画像,"
        "系统能读懂你跨平台的兴趣——\n"
        "你在 YouTube 常看的领域(科技 / 历史 / 音乐…)也会反映到 B 站推荐里。"
    )
    console.print()
    console.print("启用需要:")
    console.print("  1. 装好 OpenBiliClaw 浏览器扩展")
    console.print(
        "     [link=https://github.com/whiteguo233/OpenBiliClaw/releases]"
        "https://github.com/whiteguo233/OpenBiliClaw/releases[/link]"
    )
    console.print("  2. 浏览器登录 [link=https://www.youtube.com]https://www.youtube.com[/link]")
    console.print()
    console.print(
        "[dim]说 N 也没关系,init 会用 B 站(+其他已启用平台)数据建画像;"
        "以后想加随时再跑一次 init,或设 OPENBILICLAW_NO_YOUTUBE=1 永久跳过。[/dim]"
    )
    console.print()

    if not typer.confirm("加入 YouTube 数据?", default=False):
        console.print("[dim]  已选择跳过,本次 init 不会请求 YouTube 数据。[/dim]")
        return False

    console.print()
    console.print("[bold]准备 YouTube 接入[/bold]")
    console.print("请确认以下三件事都做了:")
    console.print("  [cyan][ ][/cyan] 装好了 OpenBiliClaw 浏览器扩展")
    console.print(
        "  [cyan][ ][/cyan] 浏览器目前是打开的且是当前 [bold]活跃窗口[/bold]"
        "(扩展需要前台 tab 才能滚动加载 YouTube 历史/订阅/点赞列表)"
    )
    console.print("  [cyan][ ][/cyan] 已经登录了 https://www.youtube.com")
    console.print()
    console.print(
        "[bold yellow][!][/bold yellow]  接下来扩展会[bold]在你的浏览器里自动打开"
        "一个新 tab[/bold]并切到那个 tab(会抢一次焦点),依次访问 3 个页面"
        "(观看历史 / 订阅频道 / 点赞列表)向下滚动加载。整个过程 30-90 秒。"
    )
    console.print(
        "[dim]   — 期间不要关那个 tab、不要切走太久(可能影响滚动加载)。"
        "完成后扩展会自动关闭它,焦点还回来。[/dim]"
    )
    console.print(
        "[dim]   — 想跳过焦点抢占的话:Ctrl-C 退出,改用 "
        "`OPENBILICLAW_YT_BOOTSTRAP_SCROLL_ROUNDS=0 openbiliclaw init` "
        "拿浅层数据。[/dim]"
    )
    console.print()
    if not typer.confirm("准备好了吗,可以开始吗?", default=True):
        console.print(
            "[dim]  已暂缓 YouTube 接入,本次 init 不会拉 YouTube 数据。装好扩展+登录"
            "YouTube 后随时再跑一次 init 就能补上。[/dim]"
        )
        return False
    return True


def _ask_x_inclusion() -> bool:
    """决定是否在本次 init 中启用 X (Twitter) discovery 源。

    与 xhs/douyin/youtube 不同，X 没有扩展 bootstrap 任务——discovery
    通过服务端 cookie replay 进行。所以这里只是翻转
    ``[sources.twitter].enabled``；真正的拉取会在 x.com cookie 同步后
    由后端 producer 执行。解析顺序（首个命中即生效）：
      1. ``OPENBILICLAW_NO_X=1`` 环境变量 → False，静默。
      2. 非交互式终端（CI / piped stdin） → **False**，静默。
      3. 交互式终端 → 询问用户，默认 N（opt-in）。
    """
    if os.environ.get("OPENBILICLAW_NO_X", "").strip() == "1":
        console.print("[dim]  跳过 X 数据接入(OPENBILICLAW_NO_X=1)。[/dim]")
        return False
    if not _is_interactive_terminal():
        return False

    console.print()
    console.print("[bold]𝕏 X (Twitter) 数据接入(可选)[/bold]")
    console.print(
        "把 X 内容混进发现池,系统会按你的画像在 X 上"
        "[bold cyan]搜索 / 拉 For-You / 追订阅作者[/bold cyan],"
        "推荐里会多出 X 的文字卡片。"
    )
    console.print()
    console.print("启用需要:")
    console.print("  1. 装好 OpenBiliClaw 浏览器扩展")
    console.print(
        "     [link=https://github.com/whiteguo233/OpenBiliClaw/releases]"
        "https://github.com/whiteguo233/OpenBiliClaw/releases[/link]"
    )
    console.print(
        "  2. 浏览器登录 [link=https://x.com]https://x.com[/link](扩展会自动把 cookie 同步给后端)"
    )
    console.print()
    console.print(
        "[dim]说 N 也没关系,init 会用 B 站(+其他已启用平台)数据建画像;"
        "以后想加随时再跑一次 init,或在设置页开启 X 来源,或设 OPENBILICLAW_NO_X=1 永久跳过。[/dim]"
    )
    console.print()

    if not typer.confirm("加入 X 数据?", default=False):
        console.print("[dim]  已选择跳过,本次 init 不会启用 X 来源。[/dim]")
        return False
    return True


def _ask_zhihu_inclusion() -> bool:
    """决定是否在本次 init 中入队 Zhihu bootstrap 任务。"""
    if os.environ.get("OPENBILICLAW_NO_ZHIHU", "").strip() == "1":
        console.print("[dim]  跳过知乎数据接入(OPENBILICLAW_NO_ZHIHU=1)。[/dim]")
        return False
    if not _is_interactive_terminal():
        return False

    console.print()
    console.print("[bold]知乎数据接入(可选)[/bold]")
    console.print(
        "把你的知乎[bold cyan]浏览 / 收藏 / 点赞[/bold cyan]混进画像，"
        "知识类回答、文章和关注领域会参与首次偏好分析。"
    )
    console.print()
    console.print("启用需要:")
    console.print("  1. 装好 OpenBiliClaw 浏览器扩展")
    console.print("  2. 浏览器登录 [link=https://www.zhihu.com]https://www.zhihu.com[/link]")
    console.print()
    console.print(
        "[dim]知乎通过浏览器插件使用当前登录态抓取；说 N 也没关系，"
        "以后可在设置页开启知乎来源，或重新运行 init。[/dim]"
    )
    console.print()

    if not typer.confirm("加入知乎数据?", default=False):
        console.print("[dim]  已选择跳过，本次 init 不会请求知乎数据。[/dim]")
        return False
    return True


def _ask_network_binding() -> bool:
    """询问后端是否应监听所有网卡（0.0.0.0）。

    用户确认全网卡监听返回 True；仅本机返回 False。
    非交互式终端默认 True（新默认保留移动端 Web 可访问）。
    """
    if not _is_interactive_terminal():
        return True

    console.print()
    console.print("[bold][MOBILE] 移动端访问[/bold]")
    console.print(
        "OpenBiliClaw 自带移动端 Web（[bold cyan]/m/[/bold cyan]），同一局域网的手机扫码即可打开。"
    )
    console.print()
    console.print(
        "为此，后端需要监听 [bold]0.0.0.0[/bold]（所有网卡），"
        "这样手机才能连上来。\n"
        "如果你只在本机使用、不需要手机端，选 N 会改为仅监听 127.0.0.1。"
    )
    console.print()
    console.print("[dim]后续可在 config.toml 的 [api].host 随时切换。[/dim]")
    console.print()
    return typer.confirm("允许局域网设备访问（推荐）?", default=True)


def _persist_api_host_choice(*, allow_lan: bool) -> None:
    """将用户的网卡绑定选择持久化到 config.toml。"""
    try:
        from openbiliclaw.config import load_config, save_config

        cfg = load_config()
        target_host = "0.0.0.0" if allow_lan else "127.0.0.1"
        if cfg.api.host != target_host:
            cfg.api.host = target_host
            save_config(cfg)
    except Exception:
        return


def _maybe_setup_password_in_init(*, allow_lan: bool) -> None:
    """在 init 期间询问是否设置局域网访问密码（仅在启用局域网时）。"""
    if not allow_lan or not _is_interactive_terminal():
        return
    console.print()
    console.print("[bold][LOCK] 访问密码（可选）[/bold]")
    console.print(
        "为局域网/远程设备访问设置登录密码？[bold]本机访问始终免登录[/bold]，"
        "只有手机和其他电脑需要输入密码。"
    )
    console.print("[dim]后续可用 `openbiliclaw set-password` 设置或修改。[/dim]")
    console.print()
    if not typer.confirm("为局域网访问设置登录密码?", default=False):
        return
    password = str(
        typer.prompt("设置访问密码", hide_input=True, confirmation_prompt=True) or ""
    ).strip()
    if not password:
        console.print("[dim]密码为空，已跳过。[/dim]")
        return
    try:
        import secrets as _secrets

        from openbiliclaw.auth_core import hash_password
        from openbiliclaw.config import load_config, save_config

        cfg = load_config()
        cfg.api.auth.password_hash = hash_password(password)
        cfg.api.auth.enabled = True
        if not cfg.api.auth.session_secret.strip():
            cfg.api.auth.session_secret = _secrets.token_urlsafe(32)
        save_config(cfg)
        console.print("[green]已设置访问密码，局域网访问将需要登录。[/green]")
    except Exception:
        console.print("[yellow]密码设置失败，可稍后用 `openbiliclaw set-password` 重试。[/yellow]")


def _persist_init_source_enabled_flags(
    *,
    include_bili: bool = True,
    include_xhs: bool,
    include_dy: bool,
    include_yt: bool,
    include_x: bool = False,
    include_zhihu: bool = False,
) -> None:
    """持久化 init 的数据源选择，以便后台 discovery 遵循它们。"""

    try:
        from openbiliclaw.config import load_config, save_config

        cfg = load_config()
        changed = False
        bilibili_cfg = getattr(cfg.sources, "bilibili", None)
        if (
            bilibili_cfg is not None
            and bool(getattr(bilibili_cfg, "enabled", True)) != include_bili
        ):
            bilibili_cfg.enabled = include_bili
            changed = True
        if bool(getattr(cfg.sources.xiaohongshu, "enabled", False)) != include_xhs:
            cfg.sources.xiaohongshu.enabled = include_xhs
            changed = True
        if bool(getattr(cfg.sources.douyin, "enabled", False)) != include_dy:
            cfg.sources.douyin.enabled = include_dy
            changed = True
        if bool(getattr(cfg.sources.youtube, "enabled", False)) != include_yt:
            cfg.sources.youtube.enabled = include_yt
            changed = True
        twitter_cfg = getattr(cfg.sources, "twitter", None)
        if twitter_cfg is not None and bool(getattr(twitter_cfg, "enabled", False)) != include_x:
            twitter_cfg.enabled = include_x
            changed = True
        zhihu_cfg = getattr(cfg.sources, "zhihu", None)
        if zhihu_cfg is not None and bool(getattr(zhihu_cfg, "enabled", False)) != include_zhihu:
            zhihu_cfg.enabled = include_zhihu
            changed = True
        if changed:
            save_config(cfg)
    except Exception:
        # 持久化 init 选择是 best-effort；init 应继续推进。
        return


def _select_init_source_shares(
    event_counts: Mapping[str, int],
    *,
    enabled_sources: Mapping[str, bool],
    configured_shares: Mapping[str, int],
) -> dict[str, int]:
    """返回交互式 init 期间选定的数据源份额。"""

    from openbiliclaw.runtime.source_policy import (
        SOURCE_ORDER,
        suggest_pool_source_shares,
    )

    configured = _merge_source_shares(configured_shares, {})
    suggestion = suggest_pool_source_shares(
        event_counts,
        enabled_sources=enabled_sources,
        configured_shares=configured,
    )
    if not _is_interactive_terminal():
        return configured

    enabled_order = [source for source in SOURCE_ORDER if enabled_sources.get(source, False)]
    console.print()
    console.print("[bold]平台发现比例[/bold]")
    console.print(
        "[dim]根据本次初始化采集到的各平台事件量，推荐后台发现池比例："
        f"{_format_source_shares(suggestion)}。[/dim]"
    )
    if typer.confirm("使用这个比例?", default=True):
        return _merge_source_shares(configured, suggestion)

    raw = typer.prompt(
        "手动输入比例",
        default=",".join(f"{source}={configured.get(source, 1)}" for source in enabled_order),
    ).strip()
    parsed = _parse_source_share_input(raw, enabled_order=enabled_order)
    if not parsed:
        console.print("[yellow]比例输入无效，保留原配置。[/yellow]")
        return configured
    return _merge_source_shares(configured, parsed)


def _maybe_update_init_source_shares(event_counts: Mapping[str, int]) -> None:
    """在 init 事件采集后，请用户接受 / 调整数据源份额。"""

    try:
        from openbiliclaw.config import load_config, save_config
        from openbiliclaw.runtime.source_policy import source_enabled_map

        cfg = load_config()
        enabled_sources = source_enabled_map(cfg)
        selected = _select_init_source_shares(
            event_counts,
            enabled_sources=enabled_sources,
            configured_shares=cfg.scheduler.pool_source_shares,
        )
        if selected != cfg.scheduler.pool_source_shares:
            cfg.scheduler.pool_source_shares = selected
            save_config(cfg)
    except Exception:
        return


def _merge_source_shares(
    configured_shares: Mapping[str, int],
    updates: Mapping[str, int],
) -> dict[str, int]:
    from openbiliclaw.runtime.source_policy import DEFAULT_POOL_SOURCE_SHARES, SOURCE_ORDER

    merged = dict(DEFAULT_POOL_SOURCE_SHARES)
    for source in SOURCE_ORDER:
        if source in configured_shares:
            try:
                share = int(configured_shares[source])
            except (TypeError, ValueError):
                continue
            if share > 0:
                merged[source] = share
    for source, raw_share in updates.items():
        if source not in SOURCE_ORDER:
            continue
        try:
            share = int(raw_share)
        except (TypeError, ValueError):
            continue
        if share > 0:
            merged[source] = share
    return {source: merged[source] for source in SOURCE_ORDER if source in merged}


def _parse_source_share_input(raw: str, *, enabled_order: list[str]) -> dict[str, int]:
    if not raw.strip():
        return {}

    parsed: dict[str, int] = {}
    if "=" in raw:
        for part in re.split(r"[,，\s]+", raw.strip()):
            if not part or "=" not in part:
                continue
            key, value = part.split("=", 1)
            source = key.strip().lower()
            if source not in enabled_order:
                continue
            try:
                share = int(value)
            except ValueError:
                continue
            if share > 0:
                parsed[source] = share
        return parsed

    values = [item for item in re.split(r"[:：,，\s]+", raw.strip()) if item]
    for source, value in zip(enabled_order, values, strict=False):
        try:
            share = int(value)
        except ValueError:
            continue
        if share > 0:
            parsed[source] = share
    return parsed


def _format_source_shares(shares: Mapping[str, int]) -> str:
    labels = {
        "bilibili": "B站",
        "xiaohongshu": "小红书",
        "douyin": "抖音",
        "youtube": "YouTube",
    }
    return ", ".join(f"{labels.get(source, source)}={share}" for source, share in shares.items())


def _normalize_init_bilibili_limit(value: int | None, *, default: int) -> int:
    """归一化面向用户的 init 信号上限。

    0 的含义由调用方决定：history 视 0 为"拉全部"，
    favorite / follow 沿用既有的"跳过该信号"语义。
    """
    if value is None:
        return default
    return max(0, int(value))


def _ask_init_bilibili_limits(
    *,
    history_limit: int | None,
    favorite_limit: int | None,
    follow_limit: int | None,
) -> tuple[int, int, int]:
    """请交互式用户确认 Bilibili init 信号上限。"""
    history = _normalize_init_bilibili_limit(
        history_limit,
        default=_INIT_BILIBILI_HISTORY_LIMIT,
    )
    favorite = _normalize_init_bilibili_limit(
        favorite_limit,
        default=_INIT_BILIBILI_FAVORITE_LIMIT,
    )
    follow = _normalize_init_bilibili_limit(
        follow_limit,
        default=_INIT_BILIBILI_FOLLOW_LIMIT,
    )
    if not _is_interactive_terminal():
        return history, favorite, follow
    if history_limit is not None and favorite_limit is not None and follow_limit is not None:
        return history, favorite, follow

    console.print(
        "\n[bold]B 站初始化信号上限[/bold]\n"
        "[dim]回车使用默认值；历史输入 0 表示拉全部，收藏 / 关注输入 0 表示跳过。[/dim]"
    )
    if history_limit is None:
        raw = typer.prompt(
            "B 站历史最多导入多少条",
            default=str(_INIT_BILIBILI_HISTORY_LIMIT),
        )
        try:
            history = max(0, int(str(raw).strip()))
        except ValueError:
            history = _INIT_BILIBILI_HISTORY_LIMIT
    if favorite_limit is None:
        raw = typer.prompt(
            "B 站收藏最多导入多少条",
            default=str(_INIT_BILIBILI_FAVORITE_LIMIT),
        )
        try:
            favorite = max(0, int(str(raw).strip()))
        except ValueError:
            favorite = _INIT_BILIBILI_FAVORITE_LIMIT
    if follow_limit is None:
        raw = typer.prompt(
            "B 站关注 UP 最多导入多少人",
            default=str(_INIT_BILIBILI_FOLLOW_LIMIT),
        )
        try:
            follow = max(0, int(str(raw).strip()))
        except ValueError:
            follow = _INIT_BILIBILI_FOLLOW_LIMIT
    return history, favorite, follow


@dataclass
class InitResult:
    """:func:`run_guided_init` 的结果，由 CLI 汇总以及
    （gui-init）API init 端点消费。"""

    history: list[dict[str, Any]]
    favorites_data: list[dict[str, Any]]
    following_data: list[dict[str, Any]]
    events: list[dict[str, Any]]
    bilibili_event_count: int
    xhs_events: list[dict[str, Any]]
    xhs_scope_counts: dict[str, Any]
    xhs_status: str
    dy_events: list[dict[str, Any]]
    dy_scope_counts: dict[str, Any]
    dy_status: str
    yt_events: list[dict[str, Any]]
    yt_scope_counts: dict[str, Any]
    yt_status: str
    zhihu_events: list[dict[str, Any]]
    zhihu_scope_counts: dict[str, Any]
    zhihu_status: str
    profile_data: Any
    discovered_count: int
    discovery_error: bool
    discover_exc: BaseException | None


class GuidedInitError(Exception):
    """:func:`run_guided_init` 内部抛出的硬失败。

    ``reason`` 是稳定的机器码（``empty_history`` /
    ``profile_failed``），API 把它映射到 ``InitCoordinator.fail``，
    CLI 把它映射到状态面板 + 非零退出码。
    """

    def __init__(self, reason: str, message: str) -> None:
        self.reason = reason
        self.message = message
        super().__init__(message)


async def _fetch_bilibili_init_data(
    client: Any,
    *,
    history_limit: int = _INIT_BILIBILI_HISTORY_LIMIT,
    favorite_limit: int,
    follow_limit: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """在单个事件循环内拉取 B 站 history / favorites / following。

    从旧的 ``init`` 闭包中抽出，使 CLI 与 API guided-init 路径
    共享同一段 B 站拉取（gui-init spec §1）。Favorites / following
    上限由调用方解析；history 默认 ``_INIT_BILIBILI_HISTORY_LIMIT``，
    调用方可传入覆盖值。
    """
    hist = await client.get_user_history(max_items=history_limit)

    favs: list[dict[str, Any]] = []
    try:
        fav_folders = (
            await client.get_all_favorites(
                max_folders=200,
                max_items_per_folder=max(1, favorite_limit),
                max_total_items=favorite_limit,
            )
            if favorite_limit > 0
            else []
        )
        for folder in fav_folders:
            folder_title = folder.folder.title if hasattr(folder, "folder") else "未知"
            for item in folder.items if hasattr(folder, "items") else []:
                if len(favs) >= favorite_limit:
                    break
                upper = item.get("upper", {}) if isinstance(item, dict) else {}
                if not isinstance(upper, dict):
                    upper = {}
                favs.append(
                    {
                        "title": item.get("title", "") if isinstance(item, dict) else str(item),
                        "upper": str(upper.get("name", "")).strip(),
                        "folder": folder_title,
                    }
                )
            if len(favs) >= favorite_limit:
                break
    except Exception as exc:
        console.print(f"  [yellow]收藏夹拉取失败: {exc}[/yellow]")

    follows: list[dict[str, Any]] = []
    try:
        page = 1
        page_size = 50
        while len(follows) < follow_limit:
            page_users = await client.get_following(page=page, page_size=page_size)
            if not page_users:
                break
            for user in page_users:
                if len(follows) >= follow_limit:
                    break
                follows.append(
                    {
                        "name": getattr(user, "uname", str(user)),
                        "sign": getattr(user, "sign", ""),
                    }
                )
            if len(page_users) < page_size:
                break
            page += 1
    except Exception as exc:
        console.print(f"  [yellow]关注列表拉取失败: {exc}[/yellow]")

    return hist, favs, follows


async def _fetch_x_init_data(
    *,
    likes_limit: int,
    bookmarks_limit: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """拉取用户自己的 X 点赞 + 收藏，用于 init 偏好回填。

    X 走服务端 cookie replay（无扩展 bootstrap 任务），所以——
    跟 B 站一样——直接在这里拉取。通过 discovery producer 用的
    同一路径解析已同步的 ``x.com`` cookie；若不存在（用户启用了 X
    但未登录 / 扩展尚未同步），干净跳过。所有拉取都是 best-effort：
    缺失 / 过期 cookie 或限流绝不硬失败 ``init``。
    返回 ``(likes, bookmarks)``，均为 ``tweet_to_dict`` dict。
    """
    from openbiliclaw.config import load_config

    cfg = load_config()
    x_cfg = getattr(getattr(cfg, "sources", None), "twitter", None)
    cookie_env = str(getattr(x_cfg, "cookie_env", "OPENBILICLAW_X_COOKIE"))

    from openbiliclaw.sources.x_auth import resolve_x_cookie

    cookie = resolve_x_cookie(data_dir=cfg.data_path, cookie_env=cookie_env)
    if not cookie:
        console.print(
            "  [dim]X 未同步 cookie,跳过点赞/收藏历史回填"
            "(登录 x.com 后扩展会自动同步,下次 init 生效)。[/dim]"
        )
        return [], []

    from openbiliclaw.sources.x_client import XClient

    x_client = XClient(cookie=cookie)
    likes: list[dict[str, Any]] = []
    bookmarks: list[dict[str, Any]] = []
    if likes_limit > 0:
        try:
            likes = await x_client.likes(limit=likes_limit)
        except Exception as exc:
            console.print(f"  [yellow]X 点赞拉取失败: {exc}[/yellow]")
    if bookmarks_limit > 0:
        try:
            bookmarks = await x_client.bookmarks(limit=bookmarks_limit)
        except Exception as exc:
            console.print(f"  [yellow]X 收藏拉取失败: {exc}[/yellow]")
    return likes, bookmarks


async def run_guided_init(
    *,
    client: Any,
    memory: Any,
    soul_engine: Any,
    favorite_limit: int,
    follow_limit: int,
    history_limit: int = _INIT_BILIBILI_HISTORY_LIMIT,
    include_bili: bool = True,
    include_xhs: bool,
    include_dy: bool,
    include_yt: bool,
    include_x: bool = False,
    include_zhihu: bool = False,
    target_pool_count: int,
    discover_backfill: Callable[..., Coroutine[Any, Any, int]],
    coordinator: Any = None,
    run_id: str | None = None,
) -> InitResult:
    """共享的异步 init 流程(gui-init spec §1)。

    在同一个事件循环中运行四个 init 阶段,这样 CLI
    (``asyncio.run(run_guided_init(...))``)和 API
    (在 server loop 上的 ``await run_guided_init(...)``)都不会嵌套事件循环:

      1. 拉取 B 站 + 收集跨平台 bootstrap 信号 → 传播
      2. 分析偏好
      3/4. 构建 soul profile ‖ backfill discovery pool(并行)

    Bilibili 与其他来源一样是可选的(``include_bili``);至少
    要有一个选中的来源产生信号,否则 stage 1 会抛出
    ``GuidedInitError("empty_signals")``。当 ``include_bili`` 为
    False 时,``client`` 可以为 ``None``。

    ``discover_backfill`` 是唯一真正与路径相关的步骤:CLI
    注入 :func:`_run_init_discovery_backfill_async`(一次性 engine);
    API 注入 ``controller.run_init_backfill``(持有 refresh
    lock)。当提供 ``coordinator``/``run_id`` 时,会汇报阶段
    转换和入队的 bootstrap task id,用于 live GUI 进度;
    run 的生命周期(mark_running / complete / fail)仍由调用方负责。
    """

    async def _stage_started(n: int) -> None:
        if coordinator is not None and run_id is not None:
            await coordinator.stage_started(run_id, n)

    async def _stage_done(n: int, *, status: str = "ok", reason: str | None = None) -> None:
        if coordinator is not None and run_id is not None:
            await coordinator.stage_done(run_id, n, status=status, reason=reason)

    def _register_task(task_id: str | None) -> None:
        if coordinator is not None and run_id is not None and task_id:
            coordinator.register_enqueued_task(run_id, task_id)

    async def _enqueue_register_kick(
        enqueue_fn: Callable[..., str | None], source: str
    ) -> str | None:
        """在事件循环之外入队 bootstrap 任务,然后唤醒扩展。

        在 API 路径(已设置 coordinator)上,dispatcher kick 会延迟到
        task id 注册为 init-owned 之后才执行,避免快速的扩展在
        ownership 记录之前就提交结果(那会让 task-result 处理器
        把 init 自己的数据当成外部数据而跳过 memory 传播)。
        CLI 路径保留 helper 内置的 kick,且没有 ownership 需要注册。
        """
        if coordinator is not None:
            task_id = await asyncio.to_thread(lambda: enqueue_fn(kick=False))
            _register_task(task_id)
            if task_id:
                await asyncio.to_thread(_kick_task_dispatcher, source)
            return task_id
        return await asyncio.to_thread(enqueue_fn)

    # 先入队 XHS bootstrap 任务,让浏览器扩展可以与下面缓慢的
    # B 站 历史/收藏/关注 拉取(~10–30s)并行执行。
    # XHS 在 B 站侧只走 HTTP,因此没有浏览器标签页焦点冲突;
    # Douyin/YouTube 之后再入队,串行执行,避免两个 active-tab
    # 焦点抢占相互竞争。
    xhs_task_id = (
        (await _enqueue_register_kick(_enqueue_xhs_bootstrap_task, "xhs")) if include_xhs else None
    )
    if xhs_task_id:
        console.print("  [dim]已请求扩展拉小红书收藏 / 点赞（后台并行,不阻塞 B 站拉取）。[/dim]")

    # ── Stage 1: fetch + cross-platform bootstrap collect → propagate ──
    await _stage_started(1)
    _print_section_title("1/4 拉取数据")
    history: list[dict[str, Any]] = []
    favorites_data: list[dict[str, Any]] = []
    following_data: list[dict[str, Any]] = []
    if include_bili:
        history, favorites_data, following_data = await _fetch_bilibili_init_data(
            client,
            history_limit=history_limit,
            favorite_limit=favorite_limit,
            follow_limit=follow_limit,
        )
        if not history:
            raise GuidedInitError("empty_history", "当前无法从 B 站历史中生成初始画像。")
        console.print(
            f"  浏览历史 [green]{len(history)}[/green] 条"
            f" / 收藏 [green]{len(favorites_data)}[/green] 个"
            f" / 关注 [green]{len(following_data)}[/green] 人"
        )
    else:
        console.print("  [dim]未选择 B 站来源,跳过 B 站历史 / 收藏 / 关注拉取。[/dim]")

    # Bootstrap 收集器通过带阻塞 sleep 的 DB 任务队列轮询 ——
    # 在 worker 线程中运行(Database 已配置 check_same_thread=False),
    # 避免 API 事件循环在 collect 窗口期内被冻结。
    # CLI 输出 / 顺序保持不变(此处本就是顺序执行的)。
    xhs_events, xhs_scope_counts, xhs_status = await asyncio.to_thread(
        _collect_xhs_bootstrap_events, xhs_task_id
    )
    if xhs_status == "ok":
        console.print(
            "  小红书 "
            f"收藏 [green]{xhs_scope_counts.get('saved', 0)}[/green] 个"
            f" / 点赞 [green]{xhs_scope_counts.get('liked', 0)}[/green] 个"
            f" / 浏览记录 [green]{xhs_scope_counts.get('xhs_history', 0)}[/green] 个"
        )
    elif xhs_status == "empty":
        console.print(
            "  [yellow]小红书任务跑通但 0 条 notes —— "
            "可能未登录小红书 / 个人主页没有公开收藏 / 页面 state 漂移。[/yellow]"
        )
    elif xhs_status == "timeout":
        console.print(
            "  [dim]小红书初始化信号未导入：扩展未连接或任务仍在后台跑。"
            "可设 OPENBILICLAW_XHS_BOOTSTRAP_WAIT_SECONDS=180 延长等待。[/dim]"
        )
    elif xhs_status == "failed":
        console.print("  [yellow]小红书任务失败 —— 检查扩展日志,或重试 init。[/yellow]")

    # 现在(XHS 完成)入队 Douyin。串行执行,避免两个浏览器
    # 焦点抢占型 dispatcher 争抢同一个 active tab。
    dy_task_id = (
        (await _enqueue_register_kick(_enqueue_dy_bootstrap_task, "dy")) if include_dy else None
    )
    if dy_task_id:
        console.print(
            "  [dim]已请求扩展拉抖音发布 / 收藏 / 点赞 / 关注"
            "(开始抢一次浏览器焦点,~60-90 秒)。[/dim]"
        )
    dy_events, dy_scope_counts, dy_status = await asyncio.to_thread(
        _collect_dy_bootstrap_events, dy_task_id
    )
    if dy_status == "ok":
        console.print(
            "  抖音 "
            f"发布 [green]{dy_scope_counts.get('dy_post', 0)}[/green] 条"
            f" / 收藏 [green]{dy_scope_counts.get('dy_collect', 0)}[/green] 个"
            f" / 点赞 [green]{dy_scope_counts.get('dy_like', 0)}[/green] 个"
            f" / 关注 [green]{dy_scope_counts.get('dy_follow', 0)}[/green] 人"
        )
    elif dy_status == "empty":
        console.print(
            "  [yellow]抖音任务跑通但 0 条 videos —— "
            "未登录抖音(常见,抖音对未登录返回 200+空 body),或个人主页隐私设置阻拦。[/yellow]"
        )
    elif dy_status == "timeout":
        console.print(
            "  [dim]抖音初始化信号未导入:扩展未连接或任务仍在后台跑。"
            "可设 OPENBILICLAW_DY_BOOTSTRAP_WAIT_SECONDS=180 延长等待。[/dim]"
        )
    elif dy_status == "failed":
        console.print("  [yellow]抖音任务失败 —— 检查扩展日志,或重试 init。[/yellow]")

    # YouTube 在 Douyin 完成之后再入队 —— 串行化的理由与
    # XHS→Douyin 相同:每个 dispatcher 都会打开前台标签页并
    # 抢占焦点;同时运行两个会引发 tab-focus 竞争。
    yt_task_id = (
        (await _enqueue_register_kick(_enqueue_yt_bootstrap_task, "yt")) if include_yt else None
    )
    if yt_task_id:
        console.print(
            "  [dim]已请求扩展拉 YouTube 观看历史 / 订阅 / 点赞"
            "(开始抢一次浏览器焦点,~30-90 秒)。[/dim]"
        )
    yt_events, yt_scope_counts, yt_status = await asyncio.to_thread(
        _collect_yt_bootstrap_events, yt_task_id
    )
    if yt_status == "ok":
        console.print(
            "  YouTube "
            f"观看历史 [green]{yt_scope_counts.get('yt_history', 0)}[/green] 条"
            f" / 订阅 [green]{yt_scope_counts.get('yt_subscriptions', 0)}[/green] 个"
            f" / 点赞 [green]{yt_scope_counts.get('yt_likes', 0)}[/green] 个"
        )
    elif yt_status == "empty":
        console.print(
            "  [yellow]YouTube 任务跑通但 0 条记录 —— 未登录 YouTube 或页面内容为空。[/yellow]"
        )
    elif yt_status == "timeout":
        console.print(
            "  [dim]YouTube 初始化信号未导入:扩展未连接或任务仍在后台跑。"
            "可设 OPENBILICLAW_YT_BOOTSTRAP_WAIT_SECONDS=300 延长等待。[/dim]"
        )
    elif yt_status == "failed":
        console.print("  [yellow]YouTube 任务失败 —— 检查扩展日志,或重试 init。[/yellow]")

    # Zhihu 同样由插件支持,使用浏览器中已登录的 zhihu.com
    # 会话。与其他驱动标签页的来源保持串行执行。
    zhihu_task_id = (
        (await _enqueue_register_kick(_enqueue_zhihu_bootstrap_task, "zhihu"))
        if include_zhihu
        else None
    )
    if zhihu_task_id:
        console.print(
            "  [dim]已请求扩展拉知乎浏览 / 收藏 / 点赞(使用当前浏览器登录态,~30-90 秒)。[/dim]"
        )
    zhihu_events, zhihu_scope_counts, zhihu_status = await asyncio.to_thread(
        _collect_zhihu_bootstrap_events, zhihu_task_id
    )
    if zhihu_status == "ok":
        zhihu_activity_favorites = int(zhihu_scope_counts.get("zhihu_activity_favorite", 0))
        zhihu_favorites = (
            int(zhihu_scope_counts.get("zhihu_collection", 0)) + zhihu_activity_favorites
        )
        console.print(
            "  知乎 "
            f"浏览 [green]{zhihu_scope_counts.get('zhihu_read_history', 0)}[/green] 条"
            f" / 收藏 [green]{zhihu_favorites}[/green] 条"
            f" / 点赞 [green]{zhihu_scope_counts.get('zhihu_activity_like', 0)}[/green] 条"
        )
    elif zhihu_status == "empty":
        console.print(
            "  [yellow]知乎任务跑通但 0 条记录 —— 可能未登录知乎，或页面数据为空。[/yellow]"
        )
    elif zhihu_status == "login_required":
        console.print("  [yellow]知乎需要登录 —— 请先在当前浏览器登录知乎后重试 init。[/yellow]")
    elif zhihu_status == "timeout":
        console.print(
            "  [dim]知乎初始化信号未导入:扩展未连接或任务仍在后台跑。"
            "可设 OPENBILICLAW_ZHIHU_BOOTSTRAP_WAIT_SECONDS=180 延长等待。[/dim]"
        )
    elif zhihu_status == "failed":
        console.print("  [yellow]知乎任务失败 —— 检查扩展日志,或重试 init。[/yellow]")

    # X (Twitter): server-side cookie replay (no extension bootstrap task), so —
    # like B站 — fetch the user's own likes + bookmarks directly here. Skips
    # cleanly when X is disabled or the cookie isn't synced yet.
    x_likes_data: list[dict[str, Any]] = []
    x_bookmarks_data: list[dict[str, Any]] = []
    if include_x:
        x_likes_data, x_bookmarks_data = await _fetch_x_init_data(
            likes_limit=_INIT_X_LIKES_LIMIT,
            bookmarks_limit=_INIT_X_BOOKMARKS_LIMIT,
        )
        if x_likes_data or x_bookmarks_data:
            console.print(
                f"  X 点赞 [green]{len(x_likes_data)}[/green] 条"
                f" / 收藏 [green]{len(x_bookmarks_data)}[/green] 条"
            )

    # 通过统一的 event_format 构建器把所有数据源构建为 events,
    # 让 B 站 / 小红书 / 未来新增来源的 events 共享同一种结构。
    from openbiliclaw.sources.event_format import SOURCE_BILIBILI, build_event

    events = [_history_item_to_event(item) for item in history]
    for fav in favorites_data:
        folder = str(fav.get("folder", "")).strip()
        upper = str(fav.get("upper", "")).strip()
        events.append(
            build_event(
                event_type="favorite",
                source_platform=SOURCE_BILIBILI,
                title=str(fav.get("title", "")),
                author=upper,
                metadata={
                    "folder": folder,
                    "upper": upper,
                },
            )
        )
    for user in following_data:
        sign = str(user.get("sign", "")).strip()
        name = str(user.get("name", ""))
        events.append(
            build_event(
                event_type="follow",
                source_platform=SOURCE_BILIBILI,
                title=name,
                author=name,
                context=(
                    f"在 B 站关注了《{name}》,签名:{sign}" if sign else f"在 B 站关注了《{name}》"
                ),
                metadata={
                    "up_name": name,
                    "sign": sign,
                },
            )
        )
    bilibili_event_count = len(events)
    # X 的 likes/bookmarks 在此处直接拉取(没有扩展任务 handler 来
    # 传播它们),因此 —— 像 B 站一样 —— 必须在本次运行中持久化。
    # 在下面 events_to_persist 快照之前追加;跨平台(xhs/dy/yt)
    # 的 extend 发生在快照之后,因为它们由各自的 task-result handler
    # 持久化。
    x_likes_events = [
        ev for tw in x_likes_data if (ev := _x_tweet_to_event(tw, event_type="like")) is not None
    ]
    x_bookmark_events = [
        ev
        for tw in x_bookmarks_data
        if (ev := _x_tweet_to_event(tw, event_type="favorite")) is not None
    ]
    events.extend(x_likes_events)
    events.extend(x_bookmark_events)
    x_event_count = len(x_likes_events) + len(x_bookmark_events)
    # 在此把 B 站 + X events 持久化到 memory。跨平台(xhs/dy/yt)events
    # 由 task-result handler 传播 —— 在 init 期间,handler 只传播
    # init-OWNED 的结果,并复用其 bootstrap-key 去重(因此在 task-reuse
    # 窗口内强制 re-init 不会重复插入)。它们仍然会通过下面收集到的
    # ``events`` 列表喂给 *本次* 运行的 analyze/profile;memory 持久化
    # 在 CLI 和 API 两条路径上都由 handler 拥有(gui-init review §5e)。
    events_to_persist = list(events)
    events_to_persist.extend(zhihu_events)
    events.extend(xhs_events)
    events.extend(dy_events)
    events.extend(yt_events)
    events.extend(zhihu_events)
    # 由于 bilibili 现在是可选的,下限条件变为"至少一个选中的来源
    # 产生了信号" —— 全空的 run 无法构建有意义的 profile。
    if not events:
        raise GuidedInitError(
            "empty_signals",
            "所选数据来源没有拉到任何行为信号，无法生成初始画像。"
            "请确认对应平台已在浏览器登录（或扩展已连接）后重试 init。",
        )
    # Source-share 调优执行未加锁的 load_config/save_config。对
    # CLI(单进程、无 live runtime)来说没问题,但在 API 路径上
    # 会在 _CONFIG_SAVE_LOCK / rebuild_from_config 之外修改
    # config.toml,与 live backend 竞争 —— 因此只有 CLI
    # (coordinator 为 None)执行此操作(gui-init review §5e)。
    # API 在首次运行时保留默认 shares。
    if coordinator is None:
        _maybe_update_init_source_shares(
            {
                "bilibili": bilibili_event_count,
                "xiaohongshu": len(xhs_events),
                "douyin": len(dy_events),
                "youtube": len(yt_events),
                "twitter": x_event_count,
                "zhihu": len(zhihu_events),
            }
        )
    for event in events_to_persist:
        await memory.propagate_event(event)
    await _stage_done(1)

    # ── Stage 2: analyze preferences ──
    await _stage_started(2)
    _print_section_title("2/4 分析偏好")
    console.print(f"  总信号量: [green]{len(events)}[/green] 条事件")
    # 把 event list 分块,让 bootstrap 做有限批次的处理,
    # 而不是对数百条 events 做一次 max-thinking 调用。
    await _run_with_progress(
        soul_engine.analyze_events(
            events,
            event_chunk_size=DEFAULT_PREFERENCE_EVENT_CHUNK_SIZE,
        ),
        label="分析偏好（分片批处理）",
        eta_seconds=180,
    )
    await _stage_done(2)

    # ── Stage 3 + 4: build profile ‖ discovery backfill (parallel) ──
    await _stage_started(3)
    await _stage_started(4)
    _print_section_title("3/4 生成画像 + 4/4 发现内容(并发)")
    combined_history: list[dict[str, Any]] = list(history)
    if favorites_data:
        combined_history.append(
            {
                "title": "[收藏夹汇总]",
                "_favorites": favorites_data,
                "_favorites_summary": f"共 {len(favorites_data)} 个收藏，"
                + "涵盖: "
                + ", ".join(
                    set(f.get("folder", "") for f in favorites_data[:100] if f.get("folder"))
                ),
            }
        )
    if following_data:
        combined_history.append(
            {
                "title": "[关注列表汇总]",
                "_following": following_data,
                "_following_summary": f"共关注 {len(following_data)} 人，"
                + "包括: "
                + ", ".join(f["name"] for f in following_data[:100]),
            }
        )
    if xhs_events:
        combined_history.extend(_xhs_events_to_history_items(xhs_events))
    if dy_events:
        combined_history.extend(_dy_events_to_history_items(dy_events))
    if yt_events:
        combined_history.extend(_yt_events_to_history_items(yt_events))
    if zhihu_events:
        combined_history.extend(_zhihu_events_to_history_items(zhihu_events))
    # X 的 likes/bookmarks 之前只喂给 analyze 阶段;同时喂给
    # profile builder 既能保持跨来源流程统一,也能保证当 X 是
    # 唯一选中来源时 profile 输入非空。
    if x_likes_events or x_bookmark_events:
        combined_history.extend(_x_events_to_history_items(x_likes_events + x_bookmark_events))

    # Discover 在仅含偏好的 draft profile 上启动,这样 trending /
    # search / related_chain / explore 可以在 LLM 合成丰富的
    # personality_portrait / deep_needs 字段时同时给候选打分。
    draft_profile = _build_draft_profile_for_discover(memory)

    profile_task = asyncio.create_task(
        _run_with_progress(
            soul_engine.build_initial_profile(combined_history),
            label="生成画像(单次 LLM 综合分析)",
            eta_seconds=70,
        )
    )
    discover_task = asyncio.create_task(
        discover_backfill(
            draft_profile,
            target_pool_count=target_pool_count,
            label_suffix=" — 用 P2 草稿画像并发预热",
        )
    )
    profile_data: Any = None
    discovered_count = 0
    discover_exc: BaseException | None = None
    try:
        # Profile 是关键路径。CancelledError 故意不被捕获 ——
        # 让它向上传播(并由 finally 拆除兄弟任务),使 wrapper
        # 记录为 `cancelled`,绝不会是 `completed`。
        try:
            profile_data = await profile_task
        except Exception as exc:
            raise GuidedInitError(
                "profile_failed",
                "画像生成阶段出错。可稍后手动重试 `openbiliclaw init`。",
            ) from exc
        await _stage_done(3)

        # Discover 是 best-effort:正常失败后会留下一个部分结果池,
        # 用户仍可基于此开始使用。Cancellation 向上传播(不捕获)。
        try:
            discovered_count = await discover_task
        except Exception as exc:
            discovered_count = 0
            discover_exc = exc
        await _stage_done(
            4,
            status="warning" if discover_exc is not None else "ok",
            reason="discovery_partial" if discover_exc is not None else None,
        )
    finally:
        # 保证在任何退出路径上,两个并行任务都不会超出本作用域存活 ——
        # 包括在阶段之间(例如 _stage_done(3) 的事件发布)的 await 处
        # 抛出的 CancelledError。否则孤立的 run_init_backfill 会一直
        # 占着 _refresh_lock。先 cancel 再 drain 两个任务。
        for _parallel_task in (profile_task, discover_task):
            if not _parallel_task.done():
                _parallel_task.cancel()
        for _parallel_task in (profile_task, discover_task):
            with suppress(BaseException):
                await _parallel_task

    return InitResult(
        history=history,
        favorites_data=favorites_data,
        following_data=following_data,
        events=events,
        bilibili_event_count=bilibili_event_count,
        xhs_events=xhs_events,
        xhs_scope_counts=xhs_scope_counts,
        xhs_status=xhs_status,
        dy_events=dy_events,
        dy_scope_counts=dy_scope_counts,
        dy_status=dy_status,
        yt_events=yt_events,
        yt_scope_counts=yt_scope_counts,
        yt_status=yt_status,
        zhihu_events=zhihu_events,
        zhihu_scope_counts=zhihu_scope_counts,
        zhihu_status=zhihu_status,
        profile_data=profile_data,
        discovered_count=discovered_count,
        discovery_error=discover_exc is not None,
        discover_exc=discover_exc,
    )


@app.command()
def init(
    no_bilibili: bool = typer.Option(
        False,
        "--no-bilibili",
        help="跳过 B 站数据接入(默认包含；init 至少需要保留一个数据来源)。",
    ),
    no_xhs: bool = typer.Option(
        False,
        "--no-xhs",
        help="跳过小红书数据接入(默认会问)。",
    ),
    skip_xhs_prompt: bool = typer.Option(
        False,
        "--yes-xhs",
        help="跳过小红书的 y/n 提问,直接启用(适合脚本化场景)。",
    ),
    no_douyin: bool = typer.Option(
        False,
        "--no-douyin",
        help="跳过抖音数据接入(默认非交互模式下就是跳过)。",
    ),
    skip_dy_prompt: bool = typer.Option(
        False,
        "--yes-douyin",
        help="跳过抖音的 y/n 提问,直接启用(适合脚本化场景)。",
    ),
    no_youtube: bool = typer.Option(
        False,
        "--no-youtube",
        help="跳过 YouTube 数据接入(默认非交互模式下就是跳过)。",
    ),
    skip_yt_prompt: bool = typer.Option(
        False,
        "--yes-youtube",
        help="跳过 YouTube 的 y/n 提问,直接启用(适合脚本化场景)。",
    ),
    no_x: bool = typer.Option(
        False,
        "--no-x",
        help="跳过 X (Twitter) 数据接入(默认非交互模式下就是跳过)。",
    ),
    skip_x_prompt: bool = typer.Option(
        False,
        "--yes-x",
        help="跳过 X 的 y/n 提问,直接启用 X 来源(适合脚本化场景)。",
    ),
    no_zhihu: bool = typer.Option(
        False,
        "--no-zhihu",
        help="跳过知乎数据接入(默认非交互模式下就是跳过)。",
    ),
    skip_zhihu_prompt: bool = typer.Option(
        False,
        "--yes-zhihu",
        help="跳过知乎的 y/n 提问,直接启用知乎来源(适合脚本化场景)。",
    ),
    bilibili_history_limit: int | None = typer.Option(
        None,
        "--bilibili-history-limit",
        min=0,
        help="B 站历史初始化信号上限；默认 500，0 表示拉全部历史。",
    ),
    bilibili_favorite_limit: int | None = typer.Option(
        None,
        "--bilibili-favorite-limit",
        min=0,
        help="B 站收藏初始化信号上限；默认 500，0 表示跳过收藏。",
    ),
    bilibili_follow_limit: int | None = typer.Option(
        None,
        "--bilibili-follow-limit",
        min=0,
        help="B 站关注 UP 初始化信号上限；默认 100，0 表示跳过关注。",
    ),
) -> None:
    """首次运行：拉取历史、生成画像并补足首轮发现池."""
    _prepare_init_runtime()

    # 在启动时快照当前最大的 llm_usage row id,这样 init 后的
    # cost summary 就能限定为"仅本次 init"而不是用户的终生
    # 账单。包裹在 try/except 中 —— billing 是 best-effort,
    # 不能阻塞 init 启动。
    init_start_usage_id: int | None = None
    try:
        init_start_usage_id = _get_runtime_database().max_llm_usage_id()
    except Exception:
        init_start_usage_id = None

    # B 站 与其他来源一样是可选的(v0.3.118+):--no-bilibili 或
    # OPENBILICLAW_NO_BILIBILI=1 会跳过它,只要至少还剩 ≥1 个来源。
    include_bili = not (
        no_bilibili or os.environ.get("OPENBILICLAW_NO_BILIBILI", "").strip() == "1"
    )

    client = _build_bilibili_client() if include_bili else None
    memory = _build_memory_manager()
    soul_engine = _build_soul_engine()

    _print_page_title("初始化 OpenBiliClaw", "首次运行引导")
    stage1_label = (
        "拉 B 站历史 / 收藏 / 关注（≈ 20–60s，看你的列表大小）"
        if include_bili
        else "拉取所选平台数据（B 站已跳过）"
    )
    console.print(
        "[bold yellow][TIME]  这一步首次运行预计需要 2–5 分钟，"
        "请保持网络畅通别中断。[/bold yellow]\n"
        "  四个阶段会依次跑：\n"
        f"    1/4  {stage1_label}\n"
        "    2/4  分析偏好（LLM 调用，≈ 30–90s）\n"
        "    3/4  生成灵魂画像（LLM 调用，≈ 30–60s）\n"
        "    4/4  发现首轮内容池（多策略并发 + LLM 评估，≈ 1–3 分钟）\n"
        "[dim]全程会打印进度，不要以为卡住了——LLM 单次响应可能就要 10–30s。[/dim]\n"
    )
    if not include_bili:
        console.print(
            "[dim]  跳过 B 站数据接入"
            f"({'命令行 --no-bilibili' if no_bilibili else 'OPENBILICLAW_NO_BILIBILI=1'})。[/dim]"
        )

    # v0.3.89+: ask user whether the backend should be reachable from
    # the local network (0.0.0.0) so mobile /m/ works out of the box.
    allow_lan = _ask_network_binding()
    _persist_api_host_choice(allow_lan=allow_lan)
    _maybe_setup_password_in_init(allow_lan=allow_lan)

    if include_bili:
        (
            resolved_bilibili_history_limit,
            resolved_bilibili_favorite_limit,
            resolved_bilibili_follow_limit,
        ) = _ask_init_bilibili_limits(
            history_limit=bilibili_history_limit,
            favorite_limit=bilibili_favorite_limit,
            follow_limit=bilibili_follow_limit,
        )
    else:
        resolved_bilibili_history_limit = 0
        resolved_bilibili_favorite_limit = 0
        resolved_bilibili_follow_limit = 0

    # v0.3.27+:询问用户是否接入 xhs 数据,选择接入时展示一份
    # prep checklist。默认保持关闭,除非用户显式启用 XHS:
    #   --no-xhs          强制跳过
    #   --yes-xhs         跳过 y/n + checklist(脚本化 opt-in)
    #   OPENBILICLAW_NO_XHS=1   环境变量跳过
    # 默认(交互式、无 flag):带默认值 N 进行 prompt。
    if no_xhs:
        include_xhs = False
        console.print("[dim]  跳过小红书数据接入(命令行 --no-xhs)。[/dim]")
    elif skip_xhs_prompt:
        include_xhs = True
    else:
        include_xhs = _ask_xhs_inclusion()

    # Douyin opt-in 用相同的解析顺序。默认在非交互模式下
    # 关闭(见 _ask_dy_inclusion docstring)。
    if no_douyin:
        include_dy = False
        console.print("[dim]  跳过抖音数据接入(命令行 --no-douyin)。[/dim]")
    elif skip_dy_prompt:
        include_dy = True
    else:
        include_dy = _ask_dy_inclusion()

    if no_youtube:
        include_yt = False
        console.print("[dim]  跳过 YouTube 数据接入(命令行 --no-youtube)。[/dim]")
    elif os.environ.get("OPENBILICLAW_NO_YOUTUBE", "").strip() == "1":
        include_yt = False
        console.print("[dim]  跳过 YouTube 数据接入(OPENBILICLAW_NO_YOUTUBE=1)。[/dim]")
    elif skip_yt_prompt:
        include_yt = True
    else:
        include_yt = _ask_yt_inclusion()

    # X (Twitter) is server-side cookie replay — no init bootstrap task, so this
    # only flips [sources.twitter].enabled; the producer fetches later once the
    # x.com cookie is synced. Same resolution order as the other opt-ins.
    if no_x:
        include_x = False
        console.print("[dim]  跳过 X 数据接入(命令行 --no-x)。[/dim]")
    elif os.environ.get("OPENBILICLAW_NO_X", "").strip() == "1":
        include_x = False
        console.print("[dim]  跳过 X 数据接入(OPENBILICLAW_NO_X=1)。[/dim]")
    elif skip_x_prompt:
        include_x = True
    else:
        include_x = _ask_x_inclusion()

    if no_zhihu:
        include_zhihu = False
        console.print("[dim]  跳过知乎数据接入(命令行 --no-zhihu)。[/dim]")
    elif os.environ.get("OPENBILICLAW_NO_ZHIHU", "").strip() == "1":
        include_zhihu = False
        console.print("[dim]  跳过知乎数据接入(OPENBILICLAW_NO_ZHIHU=1)。[/dim]")
    elif skip_zhihu_prompt:
        include_zhihu = True
    else:
        include_zhihu = _ask_zhihu_inclusion()

    if not any((include_bili, include_xhs, include_dy, include_yt, include_x, include_zhihu)):
        _print_status_panel(
            "error",
            "没有可用的数据来源",
            "已跳过 B 站且未启用任何其他平台——init 至少需要一个数据来源。"
            "去掉 --no-bilibili，或配合 --yes-xhs / --yes-douyin / "
            "--yes-youtube / --yes-x / --yes-zhihu "
            "启用其他来源。",
        )
        raise typer.Exit(code=1)

    _persist_init_source_enabled_flags(
        include_bili=include_bili,
        include_xhs=include_xhs,
        include_dy=include_dy,
        include_yt=include_yt,
        include_x=include_x,
        include_zhihu=include_zhihu,
    )

    # gui-init (B2): the four init stages now run inside the shared async
    # pipeline run_guided_init so the API can reuse them without nesting
    # event loops. The CLI injects the one-shot discovery backfill and
    # renders the summary below from the returned InitResult.
    try:
        result = asyncio.run(
            run_guided_init(
                client=client,
                memory=memory,
                soul_engine=soul_engine,
                history_limit=resolved_bilibili_history_limit,
                favorite_limit=resolved_bilibili_favorite_limit,
                follow_limit=resolved_bilibili_follow_limit,
                include_bili=include_bili,
                include_xhs=include_xhs,
                include_dy=include_dy,
                include_yt=include_yt,
                include_x=include_x,
                include_zhihu=include_zhihu,
                target_pool_count=_INIT_POOL_TARGET_COUNT,
                discover_backfill=_run_init_discovery_backfill_async,
            )
        )
    except GuidedInitError as exc:
        if exc.reason == "empty_history":
            _print_status_panel("warning", "历史为空", exc.message)
        elif exc.reason == "empty_signals":
            _print_status_panel("warning", "没有拉到信号", exc.message)
        else:
            _print_status_panel("error", "失败", exc.message)
        raise typer.Exit(code=1) from exc

    history = result.history
    favorites_data = result.favorites_data
    following_data = result.following_data
    events = result.events
    xhs_events = result.xhs_events
    xhs_scope_counts = result.xhs_scope_counts
    xhs_status = result.xhs_status
    dy_events = result.dy_events
    dy_scope_counts = result.dy_scope_counts
    yt_events = result.yt_events
    yt_scope_counts = result.yt_scope_counts
    yt_status = result.yt_status
    discovered_count = result.discovered_count
    discovery_error = result.discovery_error

    if result.discover_exc is not None:
        _print_status_panel(
            "warning",
            "部分完成",
            "画像已生成，但 discover 阶段失败，可稍后手动执行 `openbiliclaw discover`。",
        )

    _print_status_panel(
        "success" if not discovery_error else "warning",
        "初始化完成" if not discovery_error else "初始化部分完成",
        "初始化摘要",
    )

    # v0.3.58+:按平台显式拆分,让用户(以及驱动安装的
    # AI agent)能清楚看到是什么信号喂给了 soul profile。
    # 之前 summary 只写"小红书事件 N",在 bootstrap_profile
    # 处于 async-pending 时会跌到 0 —— 现在展示 scope-level
    # 计数(saved / liked / xhs_history)以及 bilibili 的
    # history / favorites / following 拆分,再加一个总数。
    # xhs_scope_counts 不论任务成功还是返回空都会被设置,
    # 因此也能暴露"0 / 0 / 0"的情况,提示用户未登录 XHS。
    # 用 pipeline 的快照,而不是对 ``events`` 做减法 ——
    # event 列表里也带有 X 的 likes/bookmarks,旧的减法
    # 会把它们默默并入 B 站 行(在 B 站 本身变可选后,这点
    # 就特别刺眼)。
    bilibili_events = result.bilibili_event_count
    xhs_saved = int(xhs_scope_counts.get("saved", 0))
    xhs_liked = int(xhs_scope_counts.get("liked", 0))
    xhs_history = int(xhs_scope_counts.get("xhs_history", 0))
    dy_post = int(dy_scope_counts.get("dy_post", 0))
    dy_collect = int(dy_scope_counts.get("dy_collect", 0))
    dy_like = int(dy_scope_counts.get("dy_like", 0))
    dy_follow = int(dy_scope_counts.get("dy_follow", 0))
    yt_history_count = int(yt_scope_counts.get("yt_history", 0))
    yt_subs_count = int(yt_scope_counts.get("yt_subscriptions", 0))
    yt_likes_count = int(yt_scope_counts.get("yt_likes", 0))
    summary_rows: list[tuple[str, str]] = [
        ("[TV] B 站观看历史", f"{len(history)} 条"),
        ("[TV] B 站收藏夹", f"{len(favorites_data)} 条"),
        ("[TV] B 站关注 UP", f"{len(following_data)} 人"),
        ("[WEB] B 站 入库事件", f"{bilibili_events} 条"),
        ("[BOOK] 小红书 收藏(saved)", f"{xhs_saved} 条"),
        ("[BOOK] 小红书 点赞(liked)", f"{xhs_liked} 条"),
        ("[BOOK] 小红书 浏览记录", f"{xhs_history} 条"),
        ("[WEB] 小红书 入库事件", f"{len(xhs_events)} 条"),
        ("[MUSIC] 抖音 发布", f"{dy_post} 条"),
        ("[MUSIC] 抖音 收藏", f"{dy_collect} 个"),
        ("[MUSIC] 抖音 点赞", f"{dy_like} 个"),
        ("[MUSIC] 抖音 关注", f"{dy_follow} 人"),
        ("[WEB] 抖音 入库事件", f"{len(dy_events)} 条"),
        ("▶ YouTube 观看历史", f"{yt_history_count} 条"),
        ("▶ YouTube 订阅频道", f"{yt_subs_count} 个"),
        ("▶ YouTube 点赞", f"{yt_likes_count} 个"),
        ("[WEB] YouTube 入库事件", f"{len(yt_events)} 条"),
        ("[STAT] 画像建模总事件", f"{len(events)} 条"),
        ("[OK] 灵魂画像", "已生成"),
        ("[SEARCH] 首轮发现内容", f"{discovered_count} 条"),
    ]
    _print_key_value_table("初始化摘要", summary_rows)

    # 如果 XHS 任务没拿到任何数据,展示可能的原因,
    # 让用户知道是否需要装好扩展后重跑。
    if (xhs_saved + xhs_liked + xhs_history) == 0 and xhs_status != "skipped":
        console.print(
            "[dim]ℹ️  小红书 0 条信号入库。最常见原因:扩展未装 / 浏览器没登录 "
            "https://www.xiaohongshu.com / 任务仍在后台跑。装好扩展后重新跑 "
            "[cyan]openbiliclaw init --yes-xhs[/cyan] 可补齐。[/dim]"
        )
    if (yt_history_count + yt_subs_count + yt_likes_count) == 0 and yt_status != "skipped":
        console.print(
            "[dim]ℹ️  YouTube 0 条信号入库。最常见原因:扩展未装 / 浏览器没登录 "
            "https://www.youtube.com / 任务仍在后台跑。装好扩展后重新跑 "
            "[cyan]openbiliclaw init --yes-youtube[/cyan] 可补齐。[/dim]"
        )

    source_parts = []
    if bilibili_events > 0:
        source_parts.append(f"[green]{bilibili_events}[/green] 条 B 站信号")
    if len(xhs_events) > 0:
        source_parts.append(f"[green]{len(xhs_events)}[/green] 条小红书信号")
    if len(dy_events) > 0:
        source_parts.append(f"[green]{len(dy_events)}[/green] 条抖音信号")
    if len(yt_events) > 0:
        source_parts.append(f"[green]{len(yt_events)}[/green] 条 YouTube 信号")
    if len(source_parts) > 1:
        console.print(
            "[dim]ℹ️  本次画像综合了 "
            + " + ".join(source_parts)
            + "。后续 daemon 会持续从这些来源增量补充。[/dim]"
        )

    # Phase E (v0.3.28+):仅打印 *本次* init 的 cost 拆分,
    # 范围由任何 LLM 调用之前快照的 row-id 限定。
    # 让用户立刻看到"init 这次花了 ¥X,其中 X% 在 discovery
    # 评估",而不必手动跑 `openbiliclaw cost`。
    if init_start_usage_id is not None:
        _print_init_cost_summary(init_start_usage_id)

    # 通知正在运行的 API server,让扩展立即刷新。
    _notify_running_server_init_completed()


def _print_init_cost_summary(since_id: int) -> None:
    """按 caller 打印 *仅本次 init* 的 LLM cost 拆分。"""
    try:
        db = _get_runtime_database()
        snapshot = db.query_llm_usage_since_id(since_id=since_id)
    except Exception:
        return  # never block init success on a billing query
    total = snapshot.get("total", {})
    if not total or total.get("calls", 0) == 0:
        return
    by_caller = snapshot.get("by_caller", [])
    total_cost = float(total.get("cost_cny", 0.0)) or 1e-9

    total_prompt = int(total.get("prompt_tokens", 0))
    total_cached = int(total.get("cached_input_tokens", 0) or 0)
    cache_blurb = ""
    if total_prompt > 0 and total_cached > 0:
        overall_hit = total_cached / total_prompt * 100
        cache_blurb = f" / cache 命中 {overall_hit:.0f}%"

    summary_table = Table(
        show_header=True,
        header_style="bold green",
        title=(
            f"本次 init LLM 花费 — 总 {total['calls']:,} 次调用 "
            f"≈ ¥{total['cost_cny']:.4f}{cache_blurb}"
        ),
    )
    summary_table.add_column("Caller (模块.动作)", no_wrap=True)
    summary_table.add_column("调用数", justify="right")
    summary_table.add_column("token in→out", justify="right")
    summary_table.add_column("cache", justify="right")
    summary_table.add_column("¥ 占比", justify="right", style="bold yellow")
    for row in by_caller:
        share = float(row["cost_cny"]) / total_cost * 100
        prompt_tok = int(row["prompt_tokens"])
        cached_tok = int(row.get("cached_input_tokens", 0) or 0)
        if prompt_tok > 0 and cached_tok > 0:
            hit_pct = cached_tok / prompt_tok * 100
            cache_cell = (
                f"[green]{hit_pct:.0f}%[/green]"
                if hit_pct >= 60
                else (
                    f"[yellow]{hit_pct:.0f}%[/yellow]"
                    if hit_pct >= 30
                    else f"[red]{hit_pct:.0f}%[/red]"
                )
            )
        else:
            cache_cell = "[dim]—[/dim]"
        summary_table.add_row(
            row["caller"] or "[dim](untagged)[/dim]",
            f"{row['calls']:,}",
            f"{row['prompt_tokens']:,}→{row['completion_tokens']:,}",
            cache_cell,
            f"¥{row['cost_cny']:.4f} ({share:.0f}%)",
        )
    console.print(summary_table)
    console.print(
        "[dim][TIP] 想看历史累积花费跑 `openbiliclaw cost` (默认 7 天) / "
        "`openbiliclaw cost --by caller --days 30` 看 30 天按模块拆分。"
        "cache 列里红色 (<30%) 的 caller 说明 prompt 前缀不稳,可以 audit 一下。[/dim]"
    )


def _notify_running_server_init_completed(
    *,
    base_url: str = "http://127.0.0.1:8420",
) -> None:
    """POST 到正在运行的 API server,通知 init 已完成。

    尽力而为:server 未运行时静默忽略。
    """
    import urllib.request

    url = f"{base_url}/api/init-completed"
    try:
        req = urllib.request.Request(url, method="POST", data=b"")
        with urllib.request.urlopen(req, timeout=3):
            console.print("[dim]已通知后端服务，插件将自动刷新。[/dim]")
    except Exception:
        # Server 未运行 —— 没什么可通知的,这没问题。
        pass


@app.command("rebuild-profile")
def rebuild_profile(
    limit: int = typer.Option(
        5000,
        "--limit",
        help="从数据库加载的最大事件数（默认 5000）。",
    ),
    source: str = typer.Option(
        "",
        "--source",
        help="只用指定来源：bilibili / xiaohongshu / douyin / youtube，留空=全部。",
    ),
    no_analyze: bool = typer.Option(
        False,
        "--no-analyze",
        help="跳过 analyze_events，直接重跑 build_initial_profile。",
    ),
) -> None:
    """从数据库重新生成灵魂画像（调试用）。

    从已存储的行为事件重跑完整的偏好分析 + 画像生成流程，
    无需重新从任何平台拉取数据。适合：

    \\b
      - 调整了 LLM prompt 后验证效果
      - 新接入平台后补充旧数据重跑
      - init 中途中断后只补跑画像阶段
    """
    import json as _json

    _prepare_init_runtime()
    memory = _build_memory_manager()
    soul_engine = _build_soul_engine()

    _print_page_title("重新生成灵魂画像", "rebuild-profile")

    init_start_usage_id: int | None = None
    with suppress(Exception):
        init_start_usage_id = _get_runtime_database().max_llm_usage_id()

    # ── 1. 从 DB 加载事件 ────────────────────────────────────────────
    console.print(f"  [dim]从数据库加载最多 {limit} 条事件...[/dim]")
    raw_rows = memory.query_events(limit=limit)

    # metadata 在 DB 中以 JSON 文本存储；context 是纯文本（v0.3.23+）。
    events: list[dict[str, Any]] = []
    for row in raw_rows:
        ev = dict(row)
        meta_raw = ev.get("metadata")
        if isinstance(meta_raw, str) and meta_raw:
            try:
                parsed = _json.loads(meta_raw)
                ev["metadata"] = parsed if isinstance(parsed, dict) else {}
            except _json.JSONDecodeError:
                ev["metadata"] = {}
        events.append(ev)

    # 来源过滤
    source = source.strip().lower()
    if source:
        events = [
            e
            for e in events
            if str((e.get("metadata") or {}).get("source_platform", "")).lower() == source
        ]

    if not events:
        console.print(
            "[yellow]  没有找到事件。"
            + (f"来源 '{source}' 不存在，或" if source else "")
            + "请先运行 [cyan]openbiliclaw init[/cyan] 拉取数据。[/yellow]"
        )
        raise typer.Exit(code=1)

    # 按来源平台打印分布
    from collections import Counter

    platform_counts: Counter[str] = Counter()
    for ev in events:
        platform_counts[str((ev.get("metadata") or {}).get("source_platform", "unknown"))] += 1
    console.print(f"  已加载 [green]{len(events)}[/green] 条事件：")
    for platform, count in sorted(platform_counts.items(), key=lambda x: -x[1]):
        console.print(f"    {platform}: [green]{count}[/green] 条")

    # ── 2. 偏好分析 ──────────────────────────────────────────────────
    if not no_analyze:
        _print_section_title("1/2 分析偏好")
        console.print(f"  总信号量: [green]{len(events)}[/green] 条")
        asyncio.run(
            _run_with_progress(
                soul_engine.analyze_events(
                    events,
                    event_chunk_size=DEFAULT_PREFERENCE_EVENT_CHUNK_SIZE,
                ),
                label="分析偏好（分片并发）",
                eta_seconds=180,
            )
        )
    else:
        console.print("  [dim]跳过 analyze_events（--no-analyze）。[/dim]")

    # ── 3. 画像生成 ──────────────────────────────────────────────────
    section_label = "2/2 生成画像" if not no_analyze else "1/1 生成画像"
    _print_section_title(section_label)
    asyncio.run(
        _run_with_progress(
            soul_engine.build_initial_profile(events),
            label="生成灵魂画像（单次 LLM 综合分析）",
            eta_seconds=70,
        )
    )

    _print_status_panel("success", "完成", "灵魂画像已重新生成")

    if init_start_usage_id is not None:
        _print_init_cost_summary(init_start_usage_id)

    _notify_running_server_init_completed()


def _run_single_source_bootstrap(
    *,
    source_label: str,
    enqueue: Callable[[], str | None],
    collect: Callable[[str | None], tuple[list[dict[str, Any]], dict[str, int], str]],
    wait_seconds: float,
    summary_renderer: Callable[[dict[str, int], str, int], None],
) -> None:
    """``fetch-douyin`` / ``fetch-xhs`` 独立命令的共享核心。

    纯拉取流程 —— enqueue → kick → 等待完成 →
    渲染 scope_counts。不会触碰 B 站 auth,也不会把
    events 传播到 memory。daemon 的
    ``/api/sources/{xhs,dy}/task-result`` handler 在收到
    partials 时已经把 incoming events 传播到 memory,
    因此 CLI 侧再 propagate 会重复写入。Init 仍会在其上
    跑 soul pipeline(preference / awareness / soul)——
    本命令是它下方孤立的"只验证扩展能否拉数据"那一层,
    适合一次只测试一个平台。
    """
    _print_page_title(f"{source_label} 数据拉取", "扩展任务 → 后端入库")
    console.print(
        f"[dim]入队 {source_label} bootstrap 任务,等扩展执行(最多 {wait_seconds:.0f}s)...[/dim]"
    )

    task_id = enqueue()
    if not task_id:
        console.print(
            f"[bold red]无法入队 {source_label} 任务[/bold red]"
            " — 看上面的提示(数据库 / 预算 / 任务表问题)。"
        )
        raise typer.Exit(code=1)

    events, scope_counts, status_label = collect(task_id)
    summary_renderer(scope_counts, status_label, len(events))


@app.command("profile-consolidate")
def profile_consolidate(
    apply: bool = typer.Option(
        False,
        "--apply",
        help="真正写入合并结果。默认 dry-run：只打印建议，不改任何数据。",
    ),
    revert: str = typer.Option(
        "",
        "--revert",
        help="按 run_id 回滚一次已应用的整理（备份在 data/memory/consolidation_runs/）。",
    ),
    migrate_categories: bool = typer.Option(
        False,
        "--migrate-categories",
        help="一次性把存量一级分类迁移到固定词表（默认 dry-run，配 --apply 写入）。",
    ),
    full: bool = typer.Option(
        False,
        "--full",
        help="把 likes 整理边界从默认 top-512 开到全量标签库（嫌疑簇 32/批送审）。",
    ),
) -> None:
    """用 LLM 整理合并画像里重复的喜欢 / 讨厌主题。

    兴趣标签和避雷主题会不断积累措辞变体（「智能体开发」vs
    「智能体开发与实现」），把进入 prompt 的兴趣名额挤占掉。
    本命令按「规则合并 → embedding 聚类 → LLM 裁决 → 校验执行」
    的流水线做同义合并（likes 看权重 top-512 + 全量避雷主题，
    LLM 裁决每批 32 簇分批执行）。

    \b
      - 默认 dry-run，先看建议再决定
      - --apply 写入,自动备份到 data/memory/consolidation_runs/
      - --migrate-categories 一次性分类词表迁移（同样 dry-run/--apply/--revert）
      - --full 一次性全量清理 likes 长尾标签（与 --migrate-categories 互斥）
      - 审计记录追加到 data/memory/soul_changelog.md
    """
    import asyncio as _asyncio

    from openbiliclaw.config import load_config
    from openbiliclaw.llm.registry import build_embedding_service
    from openbiliclaw.llm.service import LLMService, module_overrides_from_config
    from openbiliclaw.soul.consolidator import ProfileConsolidator

    _print_page_title("画像整理", "profile-consolidate")

    cfg = load_config()
    memory = _build_memory_manager()
    llm_service = None
    registry = None
    try:
        registry = _build_registry()
        llm_service = LLMService(
            registry=registry,
            memory=memory,
            usage_recorder=_build_usage_recorder(),
            module_overrides=module_overrides_from_config(cfg),
            concurrency=cfg.llm.concurrency,
        )
    except Exception as exc:
        console.print(f"[yellow]  LLM 不可用（{exc}）— 只做规则合并与聚类预览。[/yellow]")
    embedding_service = None
    if registry is not None:
        try:
            embedding_service = build_embedding_service(cfg, registry)
        except Exception:
            embedding_service = None
    if embedding_service is None:
        console.print("[dim]  embedding 服务不可用，退回子串聚类。[/dim]")

    if full and migrate_categories:
        console.print("[bold red]  --full 与 --migrate-categories 不能同时使用。[/bold red]")
        console.print("[dim]  推荐顺序：先 --migrate-categories --apply，再 --full --apply。[/dim]")
        raise typer.Exit(code=1)

    if full:
        raw_interests = memory.get_layer("preference").data.get("interests", [])
        interest_count = len([item for item in raw_interests if isinstance(item, dict)])
        likes_boundary = max(interest_count, 128)
        console.print(f"  [cyan]--full：likes 边界开到全量（{likes_boundary} 条）。[/cyan]")
        consolidator = ProfileConsolidator(
            memory=memory,
            llm_service=llm_service,
            embedding_service=embedding_service,
            likes_boundary=likes_boundary,
            like_target_upper=cfg.scheduler.profile_consolidation_like_target_upper,
            like_target_soft=cfg.scheduler.profile_consolidation_like_target_soft,
            archive_enabled=cfg.scheduler.profile_consolidation_archive_enabled,
        )
    else:
        consolidator = ProfileConsolidator(
            memory=memory,
            llm_service=llm_service,
            embedding_service=embedding_service,
            like_target_upper=cfg.scheduler.profile_consolidation_like_target_upper,
            like_target_soft=cfg.scheduler.profile_consolidation_like_target_soft,
            archive_enabled=cfg.scheduler.profile_consolidation_archive_enabled,
        )

    if revert.strip():
        ok = consolidator.revert(revert.strip())
        if ok:
            console.print(f"  [green]已回滚 run {revert.strip()}，画像与覆盖层均已恢复。[/green]")
            console.print("  [dim]被回滚的合并已记入 no-merge 记忆，下轮整理不会重做。[/dim]")
        else:
            console.print(f"[bold red]  回滚失败：找不到 run 记录 {revert.strip()}。[/bold red]")
            raise typer.Exit(code=1)
        return

    if migrate_categories:
        from openbiliclaw.soul.category_migration import CategoryMigrator

        migrator = CategoryMigrator(memory=memory, llm_service=llm_service)
        migration_report = _asyncio.run(migrator.run(dry_run=not apply))
        for err in migration_report.errors:
            console.print(f"[yellow]  [!] {err}[/yellow]")
        console.print(
            f"  现存分类: {len(migration_report.histogram)} 个，"
            f"标签 {sum(migration_report.histogram.values())} 条"
        )
        for old, new in sorted(
            migration_report.mapping.items(),
            key=lambda item: -migration_report.histogram.get(item[0], 0),
        ):
            console.print(f"  {old}({migration_report.histogram.get(old, 0)}) → [bold]{new}[/bold]")
        if migration_report.mapping:
            suffix = "  [yellow][!] 超过 10%[/yellow]" if migration_report.other_ratio > 0.10 else ""
            console.print(f"\n  「其他」占比: {migration_report.other_ratio:.1%}{suffix}")
        if not apply and migration_report.mapping:
            console.print("\n  [dim]满意的话用 --apply 真正写入。[/dim]")
        if migration_report.applied:
            console.print(
                "\n  [dim]已备份，"
                f"run_id={migration_report.run_id}（--revert {migration_report.run_id} 可回滚）"
                "[/dim]"
            )
        # 只有「LLM 服务不可用」是降级只读预览（打印 histogram 即成功，code=0）；
        # LLM 调用异常 / 映射校验失败必须非零退出，脚本化调用才能区分失败与预览。
        degraded = migration_report.errors == ["llm: service unavailable"]
        if migration_report.errors and not migration_report.mapping and not degraded:
            raise typer.Exit(code=1)
        return

    mode_label = "[bold]apply[/bold]" if apply else "dry-run（加 --apply 才会写入）"
    console.print(f"  模式: {mode_label}")
    report = _asyncio.run(consolidator.run(dry_run=not apply))

    if report.errors:
        for err in report.errors:
            console.print(f"[yellow]  [!] {err}[/yellow]")
    if report.likes_before > report.likes_target_upper:
        console.print(
            f"  [cyan]likes 动态聚类阈值:[/cyan] cosine ≥ {report.like_similarity_threshold:.2f}"
        )
    console.print(f"  嫌疑簇送审: {report.clusters_sent} 个")
    for rule_merge in report.rule_merges:
        console.print(f"  [cyan][规则][/cyan] {rule_merge}")
    for merge in report.merges:
        raw_members = merge.get("members", [])
        member_items = raw_members if isinstance(raw_members, list) else []
        members = " / ".join(str(m) for m in member_items)
        scope = "兴趣" if merge.get("scope") == "likes" else "避雷"
        console.print(
            f"  [green][{scope}][/green] {members} → [bold]{merge.get('canonical')}[/bold]"
        )
    for rejected in report.rejected_clusters:
        console.print(f"  [dim][放弃簇] {rejected}[/dim]")
    console.print(
        f"\n  兴趣: {report.likes_before} → {report.likes_after}"
        f"    避雷: {report.dislikes_before} → {report.dislikes_after}"
    )
    if report.archived_interests:
        console.print(
            f"  [cyan]归档低权重兴趣:[/cyan] {len(report.archived_interests)} 个"
            f"（目标 ≤ {report.likes_target_upper}，整理水位 {report.likes_target_soft}）"
        )
    if report.inventory_reason:
        console.print(f"  [yellow]库存说明:[/yellow] {report.inventory_reason}")
    if not apply and (report.merges or report.rule_merges):
        console.print("\n  [dim]满意的话用 --apply 真正写入。[/dim]")
    if apply and (report.merges or report.rule_merges or report.archived_interests):
        console.print(f"\n  [dim]已备份，run_id={report.run_id}[/dim]")


@app.command("fetch-douyin")
def fetch_douyin(
    wait_seconds: float = typer.Option(
        _DEFAULT_DY_BOOTSTRAP_WAIT_SECONDS,
        "--wait-seconds",
        "-w",
        help="等扩展回结果的最大秒数(默认 180s,4 个 scope 串行 + 滚动 + 兜底)。",
    ),
) -> None:
    """单独触发抖音 bootstrap 拉取(纯执行,不跑 init 的画像 / 发现层).

    流程:CLI 入队 → /api/sources/dy/kick(WS push 立即唤醒扩展)→ 扩展 dispatcher
    跑完 4 个 scope → POST 回 /api/sources/dy/task-result → daemon propagate
    事件到 memory(daemon 端自己干,CLI 不再 propagate 一次)。

    适合什么时候用:
      - 单独测试抖音的扩展能不能拉数据(不污染 init 的画像 / 发现池逻辑)
      - 已经 init 过画像后,补一次抖音拉取
      - 调扩展或诊断风控时反复跑

    前提:
      1. ``openbiliclaw start`` daemon 在跑(kick 才有人接)
      2. 浏览器扩展已装、service-worker 在线
      3. 浏览器登录了 https://www.douyin.com
    """

    def _render(scope_counts: dict[str, int], status_label: str, event_count: int) -> None:
        if status_label == "ok":
            console.print(
                "  抖音 "
                f"发布 [green]{scope_counts.get('dy_post', 0)}[/green] 条"
                f" / 收藏 [green]{scope_counts.get('dy_collect', 0)}[/green] 个"
                f" / 点赞 [green]{scope_counts.get('dy_like', 0)}[/green] 个"
                f" / 关注 [green]{scope_counts.get('dy_follow', 0)}[/green] 人"
            )
            console.print(f"  共 [green]{event_count}[/green] 条事件已由 daemon 写入 memory。")
        elif status_label == "empty":
            console.print(
                "  [yellow]抖音任务跑通但 0 条 videos —— 未登录抖音(常见,"
                "抖音对未登录返回 200+空 body),或风控触发。[/yellow]"
            )
        elif status_label == "timeout":
            console.print(
                "  [dim]抖音任务超时:扩展未连接 / 任务还在跑。"
                "可加 --wait-seconds 240 重试,或确认 daemon + 扩展都在跑。[/dim]"
            )
        elif status_label == "failed":
            console.print("  [yellow]抖音任务失败 —— 检查扩展日志。[/yellow]")

    _run_single_source_bootstrap(
        source_label="抖音",
        enqueue=_enqueue_dy_bootstrap_task,
        collect=lambda tid: _collect_dy_bootstrap_events(tid, max_wait_seconds=wait_seconds),
        wait_seconds=wait_seconds,
        summary_renderer=_render,
    )


@app.command("search-douyin")
def search_douyin(
    keywords: list[str] = _DOUYIN_SEARCH_KEYWORDS_OPTION,
    wait_seconds: float = typer.Option(
        180.0,
        "--wait-seconds",
        "-w",
        help="等扩展回搜索结果的最大秒数(默认 180s)。",
    ),
    max_items_per_keyword: int = typer.Option(
        20,
        "--max-items-per-keyword",
        min=1,
        help="每个关键词最多抓取多少条视频候选。",
    ),
) -> None:
    """通过浏览器插件执行抖音搜索 discovery smoke."""
    from openbiliclaw.discovery.douyin import split_csv_values

    selected_keywords = split_csv_values(keywords)
    _print_page_title("抖音搜索发现", "浏览器插件任务 → dy_tasks 结果")
    console.print(f"[dim]入队抖音搜索任务,等扩展执行(最多 {wait_seconds:.0f}s)...[/dim]")
    task_id = _enqueue_dy_search_task(
        selected_keywords,
        max_items_per_keyword=max_items_per_keyword,
    )
    if not task_id:
        raise typer.Exit(code=1)

    videos, counts, status_label = _collect_dy_search_results(
        task_id,
        max_wait_seconds=wait_seconds,
    )
    if status_label == "ok":
        console.print(f"  抖音搜索 [green]{counts.get('dy_search', len(videos))}[/green] 条候选")
        for index, video in enumerate(videos[:5], start=1):
            title = str(video.get("title", "") or "（无标题）")
            author = str(video.get("author", "") or "")
            url = str(video.get("url", "") or "")
            suffix = f" [dim]{author}[/dim]" if author else ""
            console.print(f"  {index}. {title}{suffix}")
            if url:
                console.print(f"     [dim]{url}[/dim]")
        return
    if status_label == "empty":
        console.print(
            "  [yellow]抖音搜索任务跑通但 0 条候选 —— 搜索页可能仍被风控软空，"
            "或页面 DOM / 接口字段漂移。[/yellow]"
        )
        return
    if status_label == "timeout":
        console.print(
            "  [dim]抖音搜索任务超时:扩展未连接 / 任务还在跑。可加 --wait-seconds 240 重试。[/dim]"
        )
        return
    if status_label == "failed":
        console.print("  [yellow]抖音搜索任务失败 —— 检查扩展日志。[/yellow]")


@app.command("fetch-xhs")
def fetch_xhs(
    wait_seconds: float = typer.Option(
        _DEFAULT_XHS_BOOTSTRAP_WAIT_SECONDS,
        "--wait-seconds",
        "-w",
        help="等扩展回结果的最大秒数(默认 180s)。",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="忽略近期小红书 bootstrap 任务，强制重新拉取收藏 / 点赞。",
    ),
) -> None:
    """单独测试小红书 bootstrap(独立于 ``init``).

    用于在不重新跑完整 init 的情况下逐项验证小红书端到端链路。
    需要 daemon + 扩展 + 浏览器登录 https://www.xiaohongshu.com。
    """

    def _render(scope_counts: dict[str, int], status_label: str, event_count: int) -> None:
        if status_label == "ok":
            console.print(
                "  小红书 "
                f"收藏 [green]{scope_counts.get('saved', 0)}[/green] 个"
                f" / 点赞 [green]{scope_counts.get('liked', 0)}[/green] 个"
                f" / 浏览记录 [green]{scope_counts.get('xhs_history', 0)}[/green] 个"
            )
            console.print(f"  共生成 [green]{event_count}[/green] 条事件。")
        elif status_label == "empty":
            console.print(
                "  [yellow]小红书任务跑通但 0 条 notes —— 可能未登录 /"
                "个人主页没有公开收藏 / 页面 state 漂移。[/yellow]"
            )
        elif status_label == "timeout":
            console.print(
                "  [dim]小红书任务超时:扩展未连接 / 任务还在跑。"
                "可加 --wait-seconds 240 重试。[/dim]"
            )
        elif status_label == "failed":
            console.print("  [yellow]小红书任务失败 —— 检查扩展日志。[/yellow]")

    _run_single_source_bootstrap(
        source_label="小红书",
        enqueue=(lambda: _enqueue_xhs_bootstrap_task(force=True))
        if force
        else _enqueue_xhs_bootstrap_task,
        collect=lambda tid: _collect_xhs_bootstrap_events(tid, max_wait_seconds=wait_seconds),
        wait_seconds=wait_seconds,
        summary_renderer=_render,
    )


@app.command("fetch-youtube")
def fetch_youtube(
    wait_seconds: float = typer.Option(
        _DEFAULT_YT_BOOTSTRAP_WAIT_SECONDS,
        "--wait-seconds",
        "-w",
        help="等扩展回结果的最大秒数(默认 240s，YouTube 滚动比较慢)。",
    ),
) -> None:
    """单独测试 YouTube bootstrap（独立于 ``init``）。

    用于在不重新跑完整 init 的情况下验证 YouTube 端到端链路。
    需要 daemon + 扩展 + 浏览器登录 https://www.youtube.com。

    \b
    采集范围：
      yt_history      — /feed/history        观看历史 (弱信号)
      yt_subscriptions — /feed/channels       订阅频道 (强信号)
      yt_likes        — /playlist?list=LL    点赞视频 (强信号)
    """

    def _render(scope_counts: dict[str, int], status_label: str, event_count: int) -> None:
        if status_label == "ok":
            console.print(
                "  YouTube "
                f"观看历史 [green]{scope_counts.get('yt_history', 0)}[/green] 条"
                f" / 订阅 [green]{scope_counts.get('yt_subscriptions', 0)}[/green] 个"
                f" / 点赞 [green]{scope_counts.get('yt_likes', 0)}[/green] 个"
            )
            console.print(f"  共生成 [green]{event_count}[/green] 条事件。")
        elif status_label == "empty":
            console.print(
                "  [yellow]YouTube 任务跑通但 0 条数据 —— "
                "可能未登录 YouTube / 页面还未渲染完 / 选择器失效。[/yellow]"
            )
        elif status_label == "timeout":
            console.print(
                "  [dim]YouTube 任务超时：扩展未连接 / 任务还在跑。"
                "可加 --wait-seconds 360 重试。[/dim]"
            )
        elif status_label == "failed":
            console.print("  [yellow]YouTube 任务失败 —— 检查扩展日志。[/yellow]")

    _run_single_source_bootstrap(
        source_label="YouTube",
        enqueue=_enqueue_yt_bootstrap_task,
        collect=lambda tid: _collect_yt_bootstrap_events(tid, max_wait_seconds=wait_seconds),
        wait_seconds=wait_seconds,
        summary_renderer=_render,
    )


@app.command("fetch-zhihu")
def fetch_zhihu(
    profile_slug: str = typer.Option(
        "",
        "--profile-slug",
        help=(
            "知乎个人主页 slug，例如 https://www.zhihu.com/people/<slug>。"
            "不提供时扩展会尝试从当前知乎登录态自动识别。"
        ),
    ),
    wait_seconds: float = typer.Option(
        _DEFAULT_ZHIHU_BOOTSTRAP_WAIT_SECONDS,
        "--wait-seconds",
        "-w",
        help="等扩展回结果的最大秒数(默认 180s)。",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="忽略近期知乎 bootstrap 任务，强制重新拉取事件。",
    ),
    write_memory: bool = typer.Option(
        False,
        "--write-memory",
        help="将本次抓到的知乎事件写入 memory；默认只做抓取 smoke。",
    ),
    rebuild_profile: bool = typer.Option(
        False,
        "--rebuild-profile",
        help="写入 memory 后用本次知乎事件重建画像（会触发真实 LLM 调用）。",
    ),
) -> None:
    """单独测试知乎事件拉取(默认独立于 ``init``，不生成画像)。

    需要 daemon + 扩展 + 浏览器登录 https://www.zhihu.com。扩展会在知乎
    页面内用当前登录态拉取最近浏览、收藏夹内容和个人动态中的点赞 / 收藏。
    传 ``--profile-slug`` 可手动指定用户主页；不传时扩展会尝试自动识别。
    默认只读取任务结果并打印统计；传 ``--write-memory`` 才写入 memory，
    传 ``--rebuild-profile`` 会继续触发画像生成。
    """
    write_memory = write_memory or rebuild_profile

    def _render(scope_counts: dict[str, int], status_label: str, event_count: int) -> None:
        if status_label == "ok":
            activity_favorites = scope_counts.get("zhihu_activity_favorite", 0)
            total_favorites = scope_counts.get("zhihu_collection", 0) + activity_favorites
            console.print(
                "  知乎 "
                f"浏览 [green]{scope_counts.get('zhihu_read_history', 0)}[/green] 条"
                f" / 收藏 [green]{total_favorites}[/green] 条"
                f" / 点赞 [green]{scope_counts.get('zhihu_activity_like', 0)}[/green] 条"
            )
            if rebuild_profile:
                suffix = "将写入 memory 并重建画像。"
            elif write_memory:
                suffix = "将写入 memory。"
            else:
                suffix = "未触发画像生成。"
            console.print(f"  共抓取并转换 [green]{event_count}[/green] 条事件；{suffix}")
        elif status_label == "empty":
            console.print(
                "  [yellow]知乎任务跑通但 0 条数据 —— "
                "可能未登录知乎 / 浏览历史关闭 / 收藏夹为空 / 接口字段漂移。[/yellow]"
            )
        elif status_label == "timeout":
            console.print(
                "  [dim]知乎任务超时:扩展未连接 / 任务还在跑。可加 --wait-seconds 240 重试。[/dim]"
            )
        elif status_label == "failed":
            console.print("  [yellow]知乎任务失败 —— 检查扩展日志。[/yellow]")
        elif status_label == "login_required":
            console.print(
                "  [yellow]知乎任务已到达浏览器，但当前知乎页面未登录。"
                "请先在当前浏览器登录知乎，再用 --force 重试。[/yellow]"
            )

    def _enqueue() -> str | None:
        # A write/rebuild run must not silently reuse a previous smoke task that
        # was already collected without persistence.
        dedupe_disabled = force or write_memory
        previous = os.environ.get("OPENBILICLAW_ZHIHU_BOOTSTRAP_DEDUPE_HOURS")
        if dedupe_disabled:
            os.environ["OPENBILICLAW_ZHIHU_BOOTSTRAP_DEDUPE_HOURS"] = "0"
        try:
            return _enqueue_zhihu_bootstrap_task(
                profile_slug=profile_slug,
                profile_update=False,
            )
        finally:
            if dedupe_disabled:
                if previous is None:
                    os.environ.pop("OPENBILICLAW_ZHIHU_BOOTSTRAP_DEDUPE_HOURS", None)
                else:
                    os.environ["OPENBILICLAW_ZHIHU_BOOTSTRAP_DEDUPE_HOURS"] = previous

    _print_page_title("知乎 数据拉取", "扩展任务 → 后端入库")
    console.print(f"[dim]入队 知乎 bootstrap 任务,等扩展执行(最多 {wait_seconds:.0f}s)...[/dim]")

    task_id = _enqueue()
    if not task_id:
        console.print(
            "[bold red]无法入队 知乎 任务[/bold red] — 看上面的提示(数据库 / 预算 / 任务表问题)。"
        )
        raise typer.Exit(code=1)

    events, scope_counts, status_label = _collect_zhihu_bootstrap_events(
        task_id,
        max_wait_seconds=wait_seconds,
    )
    _render(scope_counts, status_label, len(events))
    if status_label != "ok":
        return

    if write_memory:
        written, skipped = _write_events_to_memory(events, source="zhihu")
        console.print(
            f"  [green]已写入 memory: {written} 条知乎事件"
            f"[/green]{f'，跳过重复 {skipped} 条。' if skipped else '。'}"
        )

    if rebuild_profile:
        _prepare_init_runtime()
        soul_engine = _build_soul_engine()
        _print_section_title("1/2 分析知乎偏好")
        asyncio.run(
            _run_with_progress(
                soul_engine.analyze_events(events, event_chunk_size=200),
                label="分析知乎偏好",
                eta_seconds=180,
            )
        )
        _print_section_title("2/2 生成画像")
        asyncio.run(
            _run_with_progress(
                soul_engine.build_initial_profile(_zhihu_events_to_history_items(events)),
                label="生成灵魂画像",
                eta_seconds=70,
            )
        )
        _print_status_panel("success", "完成", "知乎事件已写入并完成画像重建")


@app.command("discover-zhihu")
def discover_zhihu(
    keywords: list[str] = _ZHIHU_DISCOVER_KEYWORDS_ARGUMENT,
    limit: int = typer.Option(
        20,
        "--limit",
        "-n",
        min=1,
        help="每个关键词最多抓取的搜索结果数。",
    ),
    wait_seconds: float = typer.Option(
        180.0,
        "--wait-seconds",
        "-w",
        help="等扩展回结果的最大秒数。",
    ),
    no_enqueue: bool = typer.Option(
        False,
        "--no-enqueue",
        help="只预览插件搜索结果，不写入 discovery_candidates。",
    ),
) -> None:
    """通过浏览器插件触发一次知乎搜索 discovery。"""
    from openbiliclaw.discovery.douyin import split_csv_values

    selected_keywords = split_csv_values(keywords)
    _print_page_title("知乎内容发现", "插件搜索 → discovery_candidates")
    console.print(f"[dim]入队知乎 search 任务,等扩展执行(最多 {wait_seconds:.0f}s)...[/dim]")
    task_id = _enqueue_zhihu_search_task(
        tuple(selected_keywords),
        max_items_per_keyword=limit,
    )
    if not task_id:
        raise typer.Exit(code=1)

    items, scope_counts, status_label = _collect_zhihu_search_results(
        task_id,
        max_wait_seconds=wait_seconds,
    )
    if status_label == "login_required":
        console.print(
            "  [yellow]知乎任务已到达浏览器，但当前知乎页面未登录。"
            "请先在当前浏览器登录知乎后重试。[/yellow]"
        )
        raise typer.Exit(code=1)
    if status_label == "timeout":
        console.print(
            "  [yellow]知乎搜索任务超时:扩展未连接 / 任务还在跑。"
            "可加 --wait-seconds 240 重试。[/yellow]"
        )
        raise typer.Exit(code=1)
    if status_label == "failed":
        console.print("  [yellow]知乎搜索任务失败 —— 检查扩展日志。[/yellow]")
        raise typer.Exit(code=1)
    if status_label == "empty" or not items:
        _print_status_panel(
            "info",
            "没有发现到知乎内容",
            "可能是搜索接口返回空、知乎未登录，或关键词没有结果。",
        )
        return

    enqueued = 0
    contents: list[Any] = []
    if no_enqueue:
        from openbiliclaw.sources.zhihu_tasks import zhihu_discovery_items_to_contents

        contents = zhihu_discovery_items_to_contents(items)
    else:
        enqueued, contents = _enqueue_zhihu_discovery_candidates(items)

    _print_key_value_table(
        "发现摘要",
        [
            ("搜索结果", str(scope_counts.get("zhihu_search", len(items)))),
            ("转换候选", str(len(contents))),
            ("入池候选", "跳过（--no-enqueue）" if no_enqueue else str(enqueued)),
            ("来源", "zhihu"),
            ("策略", "zhihu-search"),
        ],
    )
    for index, item in enumerate(contents[:5], start=1):
        _print_discovered_content_preview(item, index)


def _run_zhihu_discovery_smoke(
    *,
    title: str,
    task_type: str,
    strategy: str,
    scope_key: str,
    payload: dict[str, object],
    daily_budget_key: str,
    wait_seconds: float,
    no_enqueue: bool,
) -> None:
    _print_page_title(title, f"插件 {strategy} → discovery_candidates")
    console.print(f"[dim]入队知乎 {task_type} 任务,等扩展执行(最多 {wait_seconds:.0f}s)...[/dim]")
    task_id = _enqueue_zhihu_discovery_task(
        task_type,
        payload,
        daily_budget_key=daily_budget_key,
    )
    if not task_id:
        raise typer.Exit(code=1)

    items, scope_counts, status_label = _collect_zhihu_discovery_results(
        task_id,
        max_wait_seconds=wait_seconds,
    )
    if status_label == "login_required":
        console.print(
            "  [yellow]知乎任务已到达浏览器，但当前知乎页面未登录。"
            "请先在当前浏览器登录知乎后重试。[/yellow]"
        )
        raise typer.Exit(code=1)
    if status_label == "timeout":
        console.print(
            "  [yellow]知乎 discovery 任务超时:扩展未连接 / 任务还在跑。"
            "可加 --wait-seconds 240 重试。[/yellow]"
        )
        raise typer.Exit(code=1)
    if status_label == "failed":
        console.print("  [yellow]知乎 discovery 任务失败 —— 检查扩展日志。[/yellow]")
        raise typer.Exit(code=1)
    if status_label == "empty" or not items:
        _print_status_panel("info", "没有发现到知乎内容", f"{strategy} 返回为空。")
        return

    enqueued = 0
    contents: list[Any] = []
    if no_enqueue:
        from openbiliclaw.sources.zhihu_tasks import zhihu_discovery_items_to_contents

        contents = zhihu_discovery_items_to_contents(items)
    else:
        enqueued, contents = _enqueue_zhihu_discovery_candidates(items)

    _print_key_value_table(
        "发现摘要",
        [
            ("抓取结果", str(scope_counts.get(scope_key, len(items)))),
            ("转换候选", str(len(contents))),
            ("入池候选", "跳过（--no-enqueue）" if no_enqueue else str(enqueued)),
            ("来源", "zhihu"),
            ("策略", strategy),
        ],
    )
    for index, item in enumerate(contents[:5], start=1):
        _print_discovered_content_preview(item, index)


@app.command("discover-zhihu-hot")
def discover_zhihu_hot(
    limit: int = typer.Option(20, "--limit", "-n", min=1, help="最多抓取的热榜条数。"),
    wait_seconds: float = typer.Option(
        180.0, "--wait-seconds", "-w", help="等扩展回结果的最大秒数。"
    ),
    no_enqueue: bool = typer.Option(
        False, "--no-enqueue", help="只预览插件结果，不写入 discovery_candidates。"
    ),
) -> None:
    """通过浏览器插件触发一次知乎热榜 discovery。"""
    _run_zhihu_discovery_smoke(
        title="知乎热榜发现",
        task_type="hot",
        strategy="zhihu-hot",
        scope_key="zhihu_hot",
        payload={"max_items": max(1, int(limit))},
        daily_budget_key="daily_hot_budget",
        wait_seconds=wait_seconds,
        no_enqueue=no_enqueue,
    )


@app.command("discover-zhihu-feed")
def discover_zhihu_feed(
    limit: int = typer.Option(20, "--limit", "-n", min=1, help="最多抓取的首页推荐条数。"),
    wait_seconds: float = typer.Option(
        180.0, "--wait-seconds", "-w", help="等扩展回结果的最大秒数。"
    ),
    no_enqueue: bool = typer.Option(
        False, "--no-enqueue", help="只预览插件结果，不写入 discovery_candidates。"
    ),
) -> None:
    """通过浏览器插件触发一次知乎首页推荐 discovery。"""
    _run_zhihu_discovery_smoke(
        title="知乎首页发现",
        task_type="feed",
        strategy="zhihu-feed",
        scope_key="zhihu_feed",
        payload={"max_items": max(1, int(limit))},
        daily_budget_key="daily_feed_budget",
        wait_seconds=wait_seconds,
        no_enqueue=no_enqueue,
    )


@app.command("discover-zhihu-creator")
def discover_zhihu_creator(
    creator_urls: list[str] = _ZHIHU_CREATOR_URLS_ARGUMENT,
    limit: int = typer.Option(20, "--limit", "-n", min=1, help="每个作者最多抓取的内容数。"),
    wait_seconds: float = typer.Option(
        180.0, "--wait-seconds", "-w", help="等扩展回结果的最大秒数。"
    ),
    no_enqueue: bool = typer.Option(
        False, "--no-enqueue", help="只预览插件结果，不写入 discovery_candidates。"
    ),
) -> None:
    """通过浏览器插件触发一次知乎作者 discovery。"""
    from openbiliclaw.discovery.douyin import split_csv_values

    selected = split_csv_values(creator_urls)
    _run_zhihu_discovery_smoke(
        title="知乎作者发现",
        task_type="creator",
        strategy="zhihu-creator",
        scope_key="zhihu_creator",
        payload={"creator_urls": selected, "max_items_per_creator": max(1, int(limit))},
        daily_budget_key="daily_creator_budget",
        wait_seconds=wait_seconds,
        no_enqueue=no_enqueue,
    )


@app.command("discover-zhihu-related")
def discover_zhihu_related(
    related_urls: list[str] = _ZHIHU_RELATED_URLS_ARGUMENT,
    limit: int = typer.Option(20, "--limit", "-n", min=1, help="每个种子最多扩展的相关内容数。"),
    wait_seconds: float = typer.Option(
        180.0, "--wait-seconds", "-w", help="等扩展回结果的最大秒数。"
    ),
    no_enqueue: bool = typer.Option(
        False, "--no-enqueue", help="只预览插件结果，不写入 discovery_candidates。"
    ),
) -> None:
    """通过浏览器插件触发一次知乎相关内容 discovery。"""
    from openbiliclaw.discovery.douyin import split_csv_values

    selected = split_csv_values(related_urls)
    _run_zhihu_discovery_smoke(
        title="知乎相关发现",
        task_type="related",
        strategy="zhihu-related",
        scope_key="zhihu_related",
        payload={"related_urls": selected, "max_items_per_seed": max(1, int(limit))},
        daily_budget_key="daily_related_budget",
        wait_seconds=wait_seconds,
        no_enqueue=no_enqueue,
    )


@app.command("fetch-x")
def fetch_x(
    limit: int = typer.Option(
        50,
        "--limit",
        "-n",
        help="每类(点赞 / 收藏)最多拉取条数(默认 50,init 回填用 200)。",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="只拉取并打印,不写入 memory / 不更新画像。",
    ),
) -> None:
    """单独触发 X(Twitter)点赞 / 收藏拉取(独立于 ``init``)。

    与 fetch-xhs / fetch-douyin / fetch-youtube 对应,但 X 是服务端 cookie
    重放(无扩展 bootstrap 任务):本命令直接用已同步的 x.com cookie 拉取你
    自己的点赞 + 收藏,转成统一事件写入 memory —— 用于在不重跑完整 ``init``
    的情况下验证 X 历史偏好回填链路。不需要 daemon。

    \b
    采集范围:
      like      — 你的点赞 timeline   (强信号 → event_type="like")
      favorite  — 你的收藏 / 书签      (强信号 → event_type="favorite")

    前提:
      1. 浏览器扩展已把 x.com cookie 同步到后端(登录 x.com 即自动同步),
         或设置环境变量 ``OPENBILICLAW_X_COOKIE``。cookie 缺失时静默跳过。
    """
    _require_runtime_config()
    _print_page_title("拉取 X 点赞 / 收藏", "服务端 cookie 重放,独立于 init")

    likes_data, bookmarks_data = asyncio.run(
        _fetch_x_init_data(likes_limit=limit, bookmarks_limit=limit)
    )
    like_events = [
        ev for tw in likes_data if (ev := _x_tweet_to_event(tw, event_type="like")) is not None
    ]
    bookmark_events = [
        ev
        for tw in bookmarks_data
        if (ev := _x_tweet_to_event(tw, event_type="favorite")) is not None
    ]
    events = like_events + bookmark_events

    console.print(
        f"  X 点赞 [green]{len(like_events)}[/green] 条"
        f" / 收藏 [green]{len(bookmark_events)}[/green] 条"
        f" → 共 [green]{len(events)}[/green] 条事件。"
    )
    for ev in events[:5]:
        console.print(f"    [dim]- {ev.get('event_type')}: {(ev.get('title') or '')[:50]}[/dim]")

    if not events:
        console.print(
            "  [yellow]没有可写入的事件 —— 未登录 X / cookie 未同步 / 账号无点赞收藏。[/yellow]"
        )
        raise typer.Exit(code=0)

    if dry_run:
        console.print("  [dim]--dry-run:未写入 memory。[/dim]")
        return

    memory = _build_memory_manager()

    async def _persist() -> None:
        for ev in events:
            await memory.propagate_event(ev)

    asyncio.run(_persist())
    console.print(
        f"  [green]已写入 memory:{len(events)} 条事件。[/green]"
        " 跑 `openbiliclaw rebuild-profile` 让画像吃进新信号。"
    )


@app.command("import-youtube")
def import_youtube(
    path: str = typer.Argument(
        ...,
        help="Google Takeout 导出路径：.zip 文件或解压后的目录。",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="只解析打印统计，不写入数据库 / 不更新画像。",
    ),
) -> None:
    """从 Google Takeout 导入 YouTube 观看历史、订阅和点赞数据。

    使用步骤：

    \b
    1. 访问 https://takeout.google.com
    2. 仅选择 "YouTube and YouTube Music"
    3. 格式选 JSON（默认 HTML 也支持，但 JSON 更精确）
    4. 下载后将 .zip 路径传给本命令，或先解压再传目录。
    """
    from openbiliclaw.youtube.takeout import parse_takeout

    _print_page_title("导入 YouTube Takeout", "冷启动画像补充")

    takeout_path = Path(path)
    if not takeout_path.exists():
        console.print(f"[red]路径不存在: {takeout_path}[/red]")
        raise typer.Exit(code=1)

    console.print(f"  解析 [cyan]{takeout_path}[/cyan] …")
    result = parse_takeout(takeout_path)

    for warning in result.warnings:
        console.print(f"  [yellow][!] {warning}[/yellow]")

    stats = result.stats
    console.print(
        f"\n  解析完成：\n"
        f"    观看历史  [green]{stats.watch_history}[/green] 条\n"
        f"    订阅频道  [green]{stats.subscriptions}[/green] 个\n"
        f"    点赞视频  [green]{stats.liked_videos}[/green] 个\n"
        f"    合计      [green]{stats.total}[/green] 条事件"
    )

    if stats.total == 0:
        console.print("[yellow]未找到任何 YouTube 信号，请检查 Takeout 目录结构。[/yellow]")
        raise typer.Exit(code=0)

    if dry_run:
        console.print("\n[dim]--dry-run 模式，不写入数据库，结束。[/dim]")
        raise typer.Exit(code=0)

    _require_runtime_config()
    memory = _build_memory_manager()
    soul_engine = _build_soul_engine()

    _print_section_title("1/2 写入记忆层")
    console.print(f"  将 {stats.total} 条事件传播到记忆层 …")

    async def _propagate() -> None:
        for event in result.events:
            await memory.propagate_event(event)

    asyncio.run(_propagate())
    console.print("  [green][OK] 记忆层写入完成[/green]")

    _print_section_title("2/2 更新偏好画像")
    console.print(
        f"  分析 {stats.total} 条 YouTube 信号（分片 {DEFAULT_PREFERENCE_EVENT_CHUNK_SIZE} 条）…"
    )
    asyncio.run(
        _run_with_progress(
            soul_engine.analyze_events(
                result.events,
                event_chunk_size=DEFAULT_PREFERENCE_EVENT_CHUNK_SIZE,
            ),
            label="分析偏好（YouTube 信号）",
            eta_seconds=90,
        )
    )
    console.print("  [green][OK] 偏好画像已更新[/green]")

    console.print(
        "\n[bold green][OK] YouTube Takeout 导入完成。[/bold green]\n"
        "  运行 [cyan]openbiliclaw profile[/cyan] 查看更新后的用户画像。"
    )


@app.command()
def recommend() -> None:
    """查看推荐内容."""
    from openbiliclaw.soul.engine import SoulProfileNotInitializedError

    _require_runtime_config()
    soul_engine = _build_soul_engine()
    recommendation_engine = _build_recommendation_engine()

    try:
        profile_data = asyncio.run(soul_engine.get_profile())
    except SoulProfileNotInitializedError as exc:
        console.print("[bold yellow]尚未初始化用户画像[/bold yellow]")
        console.print("请先执行 `openbiliclaw init` 拉取历史并生成初始画像。")
        raise typer.Exit(code=1) from exc

    recommendations = asyncio.run(
        recommendation_engine.generate_recommendations(
            discovered=None,
            profile=profile_data,
            limit=5,
        )
    )

    _print_page_title("本轮推荐", "朋友式推荐列表")
    if not recommendations:
        _print_status_panel(
            "info",
            "暂无可推荐内容",
            "请先执行 `openbiliclaw discover`。",
        )
        return

    presented_ids: list[int] = []
    for index, item in enumerate(recommendations, start=1):
        _print_recommendation_card(item, index)
        presented_ids.append(item.recommendation_id)

    recommendation_engine.mark_presented(presented_ids)


@app.command()
def feedback(
    recommendation_id: int,
    signal: str,
    note: str = typer.Option("", "--note", help="补充反馈备注"),
) -> None:
    """对一条推荐记录提交反馈."""
    _require_runtime_config()
    normalized_signal = signal.strip().lower()
    if normalized_signal not in {"like", "dislike", "comment", "dismiss"}:
        _print_status_panel("error", "反馈类型无效", "仅支持: like, dislike, comment, dismiss")
        raise typer.Exit(code=1)
    if normalized_signal == "comment" and not note.strip():
        _print_status_panel("error", "comment 需要备注", "请通过 `--note` 补充一句你的想法。")
        raise typer.Exit(code=1)

    recommendation_engine = _build_recommendation_engine()
    memory = _build_memory_manager()
    recommendation = recommendation_engine.get_recommendation(recommendation_id)
    if recommendation is None:
        _print_status_panel("error", "推荐不存在", f"recommendation_id={recommendation_id}")
        raise typer.Exit(code=1)
    soul_engine = _build_soul_engine()

    asyncio.run(
        recommendation_engine.record_feedback(
            recommendation_id,
            feedback_type=normalized_signal,
            note=note.strip(),
        )
    )
    asyncio.run(
        memory.propagate_event(
            {
                "event_type": "feedback",
                "title": str(recommendation.get("title", "")),
                "metadata": {
                    "recommendation_id": recommendation_id,
                    "bvid": recommendation.get("bvid", ""),
                    "feedback_type": normalized_signal,
                    "feedback_note": note.strip(),
                },
            }
        )
    )
    record_immediate_feedback_cognition = getattr(
        soul_engine,
        "record_immediate_feedback_cognition",
        None,
    )
    if callable(record_immediate_feedback_cognition):
        with suppress(Exception):
            record_immediate_feedback_cognition(
                feedback_type=normalized_signal,
                title=str(recommendation.get("title", "")),
                note=note.strip(),
            )
    with suppress(Exception):
        asyncio.run(soul_engine.process_feedback_batch_if_needed())

    _print_status_panel("success", "反馈已记录", f"推荐ID {recommendation_id} 已更新。")
    rows = [
        ("推荐ID", str(recommendation_id)),
        ("反馈", normalized_signal),
    ]
    if note:
        rows.append(("备注", note.strip()))
    _print_key_value_table("反馈详情", rows)


@app.command()
def profile() -> None:
    """查看用户画像."""
    from openbiliclaw.soul.engine import SoulProfileNotInitializedError

    engine = _build_soul_engine()
    try:
        profile_data = asyncio.run(engine.get_profile())
    except SoulProfileNotInitializedError as exc:
        console.print("[bold yellow]尚未初始化用户画像[/bold yellow]")
        console.print("请先执行 `openbiliclaw init` 拉取历史并生成初始画像。")
        raise typer.Exit(code=1) from exc

    _print_page_title("用户画像概览", "当前稳定画像")

    # -- 人格描述 ------------------------------------------------------------
    # 按中文句子终止符切分,让 Rich 在句子边界处换行,
    # 而不是在 CJK cell 中间断开。每个句子单独起一行。
    portrait_raw = profile_data.personality_portrait or "（暂无）"
    sentences = [s.strip() for s in re.split(r"(?<=[。！？])", portrait_raw) if s.strip()]
    portrait_body = "\n".join(sentences) if sentences else portrait_raw
    console.print(
        Panel(
            portrait_body,
            title="[bold cyan]人格描述[/bold cyan]",
            border_style="cyan",
            padding=(1, 2),
        )
    )

    # -- 核心层 Core ---------------------------------------------------------
    core = profile_data.core
    _print_section_title("核心层 Core")
    core_traits = "、".join(core.core_traits) if core.core_traits else "（暂无）"
    deep_needs = "、".join(core.deep_needs) if core.deep_needs else "（暂无）"
    console.print(f"  [bold]人格特质[/bold]：{core_traits}")
    console.print(f"  [bold]深层需求[/bold]：{deep_needs}")
    mbti = core.mbti
    if mbti.type:
        dim_parts = [
            f"{key}={dim.pole}({dim.strength:.2f})" for key, dim in mbti.dimensions.items()
        ]
        dims_text = "  ".join(dim_parts) if dim_parts else ""
        console.print(
            f"  [bold]MBTI[/bold]：{mbti.type}  置信度 {mbti.confidence:.0%}"
            + (f"  [dim]{dims_text}[/dim]" if dims_text else "")
        )

    # -- 价值层 Values -------------------------------------------------------
    values_layer = profile_data.values_layer
    _print_section_title("价值层 Values")
    values_text = "、".join(values_layer.values) if values_layer.values else "（暂无）"
    drivers_text = (
        "、".join(values_layer.motivational_drivers)
        if values_layer.motivational_drivers
        else "（暂无）"
    )
    console.print(f"  [bold]价值观[/bold]：{values_text}")
    console.print(f"  [bold]动机驱动[/bold]：{drivers_text}")

    # -- 角色层 Role ---------------------------------------------------------
    role = profile_data.role
    _print_section_title("角色层 Role")
    console.print(f"  [bold]生活阶段[/bold]：{role.life_stage or '（暂无）'}")
    console.print(f"  [bold]当前阶段[/bold]：{role.current_phase or '（暂无）'}")

    # -- 兴趣层 Interest -----------------------------------------------------
    interest = profile_data.interest
    _print_section_title("兴趣层 Interest")
    if interest.likes:
        sorted_likes = sorted(interest.likes, key=lambda d: d.weight, reverse=True)
        for dom in sorted_likes[:10]:
            spec_names = [s.name for s in dom.specifics[:5]]
            spec_text = "、".join(spec_names)
            suffix = f"  [dim]{spec_text}[/dim]" if spec_text else ""
            console.print(f"  ▸ [bold]{dom.domain}[/bold] [dim]({dom.weight:.2f})[/dim]{suffix}")
    else:
        console.print("  （暂无兴趣领域）")
    if interest.dislikes:
        dislike_text = "、".join(d.domain for d in interest.dislikes[:8])
        console.print(f"  [dim]讨厌领域：{dislike_text}[/dim]")
    if interest.favorite_up_users:
        up_total = len(interest.favorite_up_users)
        preview = "、".join(interest.favorite_up_users[:6])
        suffix = f"（共{up_total}位）" if up_total > 6 else ""
        console.print(f"  [bold]常看UP主[/bold]：{preview}{suffix}")

    # -- 表层 Surface --------------------------------------------------------
    surface = profile_data.surface
    _print_section_title("表层 Surface")
    if surface.cognitive_style:
        for idx, item in enumerate(surface.cognitive_style, start=1):
            console.print(f"  {idx}. {item}")
    else:
        console.print("  认知风格：（暂无）")
    console.print(
        f"  [bold]深度偏好[/bold]：{surface.style.depth_preference:.2f}"
        f"   [bold]探索开放度[/bold]：{surface.exploration_openness:.2f}"
    )


_BILIBILI_STRATEGY_NAMES = ("search", "trending", "explore", "related_chain")


def _normalize_strategy_names(raw: list[str] | None) -> list[str]:
    """拆分逗号分隔的值并校验 strategy 名称。"""
    if not raw:
        return []
    names: list[str] = []
    for token in raw:
        for part in token.split(","):
            name = part.strip()
            if name:
                names.append(name)
    unknown = [n for n in names if n not in _BILIBILI_STRATEGY_NAMES]
    if unknown:
        allowed = ", ".join(_BILIBILI_STRATEGY_NAMES)
        raise typer.BadParameter(f"未知的 Bilibili 策略：{', '.join(unknown)}。可选：{allowed}")
    # 保留首次出现的顺序,丢弃重复项。
    seen: set[str] = set()
    deduped: list[str] = []
    for name in names:
        if name not in seen:
            seen.add(name)
            deduped.append(name)
    return deduped


def _run_xhs_discovery(*, force: bool) -> None:
    """触发一次 Soul 驱动的 xhs 关键词生产循环。"""
    from openbiliclaw.config import load_config
    from openbiliclaw.llm.service import LLMService, module_overrides_from_config
    from openbiliclaw.runtime.xhs_producer import XhsTaskProducer
    from openbiliclaw.soul.engine import SoulProfileNotInitializedError
    from openbiliclaw.sources.xhs_tasks import XhsTaskQueue

    _require_runtime_config()
    soul_engine = _build_soul_engine()
    try:
        asyncio.run(soul_engine.get_profile())
    except SoulProfileNotInitializedError as exc:
        _print_status_panel(
            "warning",
            "尚未初始化用户画像",
            "请先执行 `openbiliclaw init` 拉取历史并生成初始画像。",
        )
        raise typer.Exit(code=1) from exc

    config = load_config()
    memory = _build_memory_manager()
    database = _get_runtime_database()
    registry = _build_registry()
    llm_service = LLMService(
        registry=registry,
        memory=memory,
        usage_recorder=_build_usage_recorder(),
        module_overrides=module_overrides_from_config(config),
        concurrency=config.llm.concurrency,
    )

    xhs_cfg = getattr(config.sources, "xiaohongshu", None)
    producer = XhsTaskProducer(
        task_queue=XhsTaskQueue(database),
        soul_engine=soul_engine,
        llm_service=llm_service,
        enabled=True,
        daily_budget=int(getattr(xhs_cfg, "daily_search_budget", 0)),
        min_interval_hours=0 if force else 4,
    )
    result = asyncio.run(producer.produce_if_due())

    reason = str(result.get("reason", ""))
    enqueued = int(cast("int", result.get("enqueued", 0)))
    attempted = int(cast("int", result.get("attempted", 0)))

    _print_page_title("小红书关键词生产", "已将关键词写入 xhs_tasks，由浏览器扩展在后台抓取")
    if reason == "ok":
        _print_key_value_table(
            "生产摘要",
            [
                ("入队关键词数", str(enqueued)),
                ("尝试关键词数", str(attempted)),
                ("今日预算", str(int(getattr(xhs_cfg, "daily_search_budget", 0)))),
                ("节流开关", "已跳过（--force）" if force else "4 小时节流"),
            ],
        )
        return

    messages = {
        "disabled": (
            "info",
            "xhs producer 已禁用",
            "config.scheduler.enabled = false 时无法触发。",
        ),
        "throttled": (
            "info",
            "距离上次关键词生产不足 4 小时",
            "可使用 `--force` 忽略节流重新触发。",
        ),
        "no_profile": (
            "warning",
            "尚未初始化 Soul 画像",
            "请先执行 `openbiliclaw init` 生成初始画像。",
        ),
        "no_keywords": (
            "info",
            "本次未产出关键词",
            "Soul 画像兴趣列表可能为空，或 LLM 返回了空结果。",
        ),
    }
    kind, title, body = messages.get(reason, ("info", "未知状态", reason or "无详细信息"))
    _print_status_panel(kind, title, body)


def _comma_separated_env_values(name: str) -> tuple[str, ...]:
    from openbiliclaw.discovery.douyin import split_csv_values

    return split_csv_values([os.environ.get(name, "")])


def _normalize_douyin_discovery_sources(sources: tuple[str, ...]) -> tuple[str, ...]:
    allowed = {"search", "hot", "feed"}
    normalized: list[str] = []
    seen: set[str] = set()
    for source in sources:
        for part in str(source).split(","):
            value = part.strip().lower()
            if not value or value in seen:
                continue
            if value not in allowed:
                raise typer.BadParameter(
                    f"未知的抖音 discovery 来源 `{value}`，当前支持：search、hot、feed。"
                )
            seen.add(value)
            normalized.append(value)
    return tuple(normalized) or ("search", "hot", "feed")


def _recent_douyin_creator_sec_uids(*, limit: int = 20) -> tuple[str, ...]:
    try:
        database = _get_runtime_database()
    except Exception:
        return ()
    if not hasattr(database, "conn"):
        return ()
    try:
        from openbiliclaw.sources.dy_tasks import recent_dy_creator_sec_uids

        return recent_dy_creator_sec_uids(database, limit=limit)
    except Exception:
        return ()


def _run_douyin_discovery(
    *,
    limit: int,
    keywords: tuple[str, ...] = (),
    creator_sec_uids: tuple[str, ...] = (),
    sources: tuple[str, ...] = ("search", "hot", "feed"),
    cache: bool = True,
    evaluate: bool = True,
) -> None:
    """运行一次基于 direct-cookie 的 Douyin discovery 循环。"""
    import openbiliclaw.config as config_module
    from openbiliclaw.discovery.douyin import (
        DouyinDiscoveryOptions,
        DouyinDiscoveryResult,
        DouyinDiscoveryService,
    )
    from openbiliclaw.soul.engine import SoulProfileNotInitializedError
    from openbiliclaw.sources.douyin_auth import resolve_douyin_cookie
    from openbiliclaw.sources.douyin_direct import DouyinDirectAuthError, DouyinDirectClient
    from openbiliclaw.sources.douyin_plugin_search import DouyinPluginSearchClient

    _require_runtime_config()
    config = config_module.load_config()
    dy_cfg = getattr(config.sources, "douyin", None)
    if dy_cfg is None or not bool(getattr(dy_cfg, "enabled", False)):
        _print_status_panel(
            "warning",
            "抖音 direct discovery 未启用",
            (
                "请在 config.toml 中设置 [sources.douyin].enabled = true；Cookie 可由"
                " OPENBILICLAW_DOUYIN_COOKIE 覆盖，或由浏览器扩展同步到本机。"
            ),
        )
        raise typer.Exit(code=1)

    mode = str(getattr(dy_cfg, "mode", "direct")).strip().lower()
    if mode != "direct":
        _print_status_panel(
            "warning",
            "抖音 discovery 模式暂不支持",
            f"当前 mode={mode!r}；本版本仅支持 direct。",
        )
        raise typer.Exit(code=1)

    cookie_env = str(getattr(dy_cfg, "cookie_env", "OPENBILICLAW_DOUYIN_COOKIE"))
    cookie = resolve_douyin_cookie(data_dir=config.data_path, cookie_env=cookie_env)
    if not cookie:
        _print_status_panel(
            "warning",
            "缺少抖音 Cookie",
            (
                f"请设置环境变量 {cookie_env}，或保持浏览器扩展在线，"
                "让它同步 douyin.com Cookie 到本机。"
            ),
        )
        raise typer.Exit(code=1)

    soul_engine = _build_soul_engine()
    try:
        profile_data = asyncio.run(soul_engine.get_profile())
    except SoulProfileNotInitializedError as exc:
        _print_status_panel(
            "warning",
            "尚未初始化用户画像",
            "请先执行 `openbiliclaw init` 拉取历史并生成初始画像。",
        )
        raise typer.Exit(code=1) from exc

    normalized_sources = _normalize_douyin_discovery_sources(sources)
    resolved_creator_sec_uids = creator_sec_uids or _comma_separated_env_values(
        "OPENBILICLAW_DOUYIN_CREATOR_SEC_UIDS"
    )
    if not resolved_creator_sec_uids and "creator" in normalized_sources:
        resolved_creator_sec_uids = _recent_douyin_creator_sec_uids(
            limit=max(1, min(limit * 2, 20))
        )

    async def _discover() -> DouyinDiscoveryResult:
        async with DouyinDirectClient(cookie=cookie) as direct_client:
            client: Any = direct_client
            if any(source in normalized_sources for source in ("search", "hot", "feed")):
                try:
                    database = _get_runtime_database()
                except Exception:
                    database = None
                if database is not None and hasattr(database, "conn"):
                    search_wait_seconds = float(
                        os.environ.get("OPENBILICLAW_DY_DISCOVERY_SEARCH_WAIT_SECONDS", "180")
                    )
                    client = DouyinPluginSearchClient(
                        database=database,
                        direct_client=direct_client,
                        wait_seconds=search_wait_seconds,
                        daily_search_budget=int(getattr(dy_cfg, "daily_search_budget", 0)),
                        daily_hot_budget=int(getattr(dy_cfg, "daily_hot_budget", 0)),
                        daily_feed_budget=int(getattr(dy_cfg, "daily_feed_budget", 0)),
                    )
            discovery_engine = _build_discovery_engine() if cache else None
            service = DouyinDiscoveryService(
                client=client,
                discovery_engine=discovery_engine,
            )
            return await service.discover(
                profile_data,
                DouyinDiscoveryOptions(
                    limit=limit,
                    sources=normalized_sources,
                    keywords=keywords,
                    creator_sec_uids=resolved_creator_sec_uids,
                    cache=cache,
                    evaluate=evaluate,
                    per_source_limit=max(1, min(limit, 30)),
                ),
            )

    try:
        result = asyncio.run(_discover())
    except DouyinDirectAuthError as exc:
        _print_status_panel("warning", "抖音 Cookie 无效", str(exc))
        raise typer.Exit(code=1) from exc

    discovered = result.items
    source_counts = ", ".join(
        f"{source}:{count}" for source, count in sorted(result.source_counts.items())
    )
    _print_page_title("抖音内容发现", f"plugin/direct {' / '.join(normalized_sources)}")
    if not discovered:
        _print_status_panel(
            "info",
            "没有发现到新抖音内容",
            "可能是 Cookie 失效、签名被拒绝，或本轮关键词没有结果。",
        )
        return

    strategies = sorted({str(getattr(item, "source_strategy", "") or "") for item in discovered})
    _print_key_value_table(
        "发现摘要",
        [
            ("发现条数", str(len(discovered))),
            ("缓存状态", "已写入 content_cache" if result.cached else "未写入 content_cache"),
            ("来源", "douyin"),
            ("来源分布", source_counts or "（无）"),
            ("策略", ", ".join(s for s in strategies if s) or "douyin_direct"),
        ],
    )
    for index, item in enumerate(discovered[:5], start=1):
        _print_discovered_content_preview(item, index)


def _build_discovery_candidate_pipeline(
    *,
    config: Any,
    database: Any,
    discovery_engine: Any,
) -> Any:
    """构建共享的 raw-candidate evaluator,用于手动 producer 运行。"""
    from openbiliclaw.discovery.candidate_pipeline import DiscoveryCandidatePipeline

    discovery_cfg = getattr(config, "discovery", None)
    admission_min_score = float(getattr(discovery_cfg, "admission_min_score", 0.60) or 0.60)
    set_admission_min_score = getattr(database, "set_admission_min_score", None)
    if callable(set_admission_min_score):
        with suppress(Exception):
            set_admission_min_score(admission_min_score)
    return DiscoveryCandidatePipeline(
        database=database,
        discovery_engine=discovery_engine,
        pool_target_count=int(getattr(config.scheduler, "pool_target_count", 300)),
        admission_min_score=admission_min_score,
    )


def _run_zhihu_discovery(*, limit: int) -> None:
    """通过 runtime producer 运行一次正式的 Zhihu discovery 循环。"""
    from openbiliclaw.config import load_config
    from openbiliclaw.runtime.keyword_fetch import KeywordFetchCoordinator
    from openbiliclaw.runtime.zhihu_producer import build_zhihu_discovery_producer
    from openbiliclaw.soul.engine import SoulProfileNotInitializedError

    _require_runtime_config()
    config = load_config()
    zh_cfg = getattr(getattr(config, "sources", None), "zhihu", None)
    if zh_cfg is None or not bool(getattr(zh_cfg, "enabled", False)):
        _print_status_panel(
            "warning",
            "知乎 discovery 未启用",
            "请在配置页或 config.toml 中启用 [sources.zhihu].enabled。",
        )
        raise typer.Exit(code=1)

    database = _get_runtime_database()
    if not hasattr(database, "conn"):
        _print_status_panel("warning", "知乎任务表不可用", "当前数据库不支持 zhihu_tasks。")
        raise typer.Exit(code=1)

    soul_engine = _build_soul_engine()
    try:
        asyncio.run(soul_engine.get_profile())
    except SoulProfileNotInitializedError as exc:
        _print_status_panel(
            "warning",
            "尚未初始化用户画像",
            "请先执行 `openbiliclaw init` 拉取历史并生成初始画像。",
        )
        raise typer.Exit(code=1) from exc

    discovery_engine = _build_discovery_engine()
    candidate_pipeline = _build_discovery_candidate_pipeline(
        config=config,
        database=database,
        discovery_engine=discovery_engine,
    )
    keyword_fetch = KeywordFetchCoordinator(
        database=database,
        discovery_config=config.discovery,
    )
    producer = build_zhihu_discovery_producer(
        config=config,
        database=database,
        soul_engine=soul_engine,
        candidate_pipeline=candidate_pipeline,
        keyword_fetch=keyword_fetch,
    )
    if producer is None:
        _print_status_panel(
            "warning",
            "知乎 discovery producer 未启动",
            "请确认知乎来源和 scheduler 均已启用。",
        )
        raise typer.Exit(code=1)

    result = asyncio.run(producer.produce_if_due(limit=limit))
    reason = str(result.get("reason", ""))
    discovered_raw = result.get("discovered", 0)
    enqueued_raw = result.get("enqueued", 0)
    discovered = int(cast("int | float | str | bool", discovered_raw) if discovered_raw else 0)
    enqueued = int(cast("int | float | str | bool", enqueued_raw) if enqueued_raw else 0)
    source_counts_raw = result.get("source_counts", {})
    source_counts = source_counts_raw if isinstance(source_counts_raw, dict) else {}
    source_counts_text = ", ".join(
        f"{source}:{count}" for source, count in sorted(source_counts.items())
    )
    source_modes = ", ".join(str(mode) for mode in getattr(zh_cfg, "source_modes", ()) or ())

    _print_page_title("知乎内容发现", f"正式 discover · {source_modes or 'search'}")
    if reason == "ok":
        _print_key_value_table(
            "发现摘要",
            [
                ("发现条数", str(discovered)),
                ("入池候选", str(enqueued)),
                ("来源", "zhihu"),
                ("来源分布", source_counts_text or "（无）"),
                ("分支", source_modes or "search"),
            ],
        )
        for index, item in enumerate(candidate_pipeline.last_admitted_items[:5], start=1):
            _print_discovered_content_preview(item, index)
        return

    messages = {
        "disabled": ("info", "知乎 discovery 已禁用", "请启用知乎来源后重试。"),
        "throttled": (
            "info",
            "距离上次知乎 discovery 不足最小调度间隔",
            "可在配置页调整知乎最小调度间隔分钟数。",
        ),
        "pool_full": ("info", "候选池已满", "当前无需继续补充知乎候选。"),
        "no_profile": ("warning", "尚未初始化 Soul 画像", "请先执行 `openbiliclaw init`。"),
        "no_keywords": ("info", "没有可用搜索词", "画像兴趣或统一关键词池为空。"),
        "no_creator_seeds": (
            "info",
            "没有作者分支 seed",
            "先跑 search/hot/feed 或手动 `discover-zhihu-creator` 积累作者 URL。",
        ),
        "no_related_seeds": (
            "info",
            "没有相关分支 seed",
            "先跑 search/hot/feed 或手动 `discover-zhihu-related` 积累内容 URL。",
        ),
        "budget_exhausted": (
            "info",
            "知乎 discovery 今日预算已用完",
            "可在配置页调整对应分支预算。",
        ),
        "empty": ("info", "知乎 discovery 返回为空", "插件任务完成但没有可转换的候选。"),
    }
    kind, title, body = messages.get(
        reason,
        ("info", "知乎 discovery 未产出内容", reason or "无详细信息"),
    )
    _print_status_panel(kind, title, body)


@app.command("discover-douyin")
def discover_douyin(
    keywords: list[str] | None = _DOUYIN_DISCOVERY_KEYWORDS_OPTION,
    creator_sec_uids: list[str] | None = _DOUYIN_DISCOVERY_CREATOR_SEC_UIDS_OPTION,
    sources: list[str] | None = _DOUYIN_DISCOVERY_SOURCES_OPTION,
    limit: int = typer.Option(30, "--limit", "-n", min=1, help="发现结果条数上限。"),
    no_cache: bool = typer.Option(
        False,
        "--no-cache",
        help="只跑策略并预览结果，不写入 content_cache。",
    ),
    no_evaluate: bool = typer.Option(
        False,
        "--no-evaluate",
        help="跳过 LLM 相关性评估，便于调试源接口原始召回。",
    ),
) -> None:
    """单独调试抖音 direct-cookie 内容 discovery."""
    from openbiliclaw.discovery.douyin import split_csv_values

    selected_sources = _normalize_douyin_discovery_sources(
        split_csv_values(sources) or ("search", "hot", "feed")
    )
    _run_douyin_discovery(
        limit=limit,
        keywords=split_csv_values(keywords),
        creator_sec_uids=split_csv_values(creator_sec_uids),
        sources=selected_sources,
        cache=not no_cache,
        evaluate=not no_evaluate,
    )


@app.command()
def discover(
    source: str = typer.Option(
        "bilibili",
        "--source",
        "-s",
        help="触发发现的内容源：bilibili、xiaohongshu、douyin 或 zhihu。",
        case_sensitive=False,
    ),
    strategies: list[str] | None = _DISCOVER_STRATEGIES_OPTION,
    limit: int = typer.Option(30, "--limit", "-n", min=1, help="发现结果条数上限。"),
    force: bool = typer.Option(
        False,
        "--force",
        help="xiaohongshu：忽略 4 小时节流强制生产一次关键词。",
    ),
) -> None:
    """手动触发内容发现（按来源选择渠道）."""
    from openbiliclaw.soul.engine import SoulProfileNotInitializedError

    source_normalized = source.strip().lower()
    if source_normalized == "xiaohongshu":
        if strategies:
            _print_status_panel(
                "info",
                "--strategy 仅对 Bilibili 生效",
                "xiaohongshu 渠道走关键词生产流程，已忽略策略过滤。",
            )
        _run_xhs_discovery(force=force)
        return

    if source_normalized == "douyin":
        if strategies:
            _print_status_panel(
                "info",
                "--strategy 仅对 Bilibili 生效",
                "douyin 渠道走 direct-cookie discovery，已忽略策略过滤。",
            )
        _run_douyin_discovery(limit=limit)
        return

    if source_normalized == "zhihu":
        if strategies:
            _print_status_panel(
                "info",
                "--strategy 仅对 Bilibili 生效",
                "zhihu 渠道走配置页 source_modes 选择的插件 discovery 分支，已忽略策略过滤。",
            )
        _run_zhihu_discovery(limit=limit)
        return

    if source_normalized != "bilibili":
        raise typer.BadParameter(
            f"未知的内容源 `{source}`，当前支持：bilibili、xiaohongshu、douyin、zhihu。"
        )

    active_strategies = _normalize_strategy_names(strategies)

    _require_runtime_config()
    soul_engine = _build_soul_engine()
    try:
        profile_data = asyncio.run(soul_engine.get_profile())
    except SoulProfileNotInitializedError as exc:
        _print_status_panel(
            "warning",
            "尚未初始化用户画像",
            "请先执行 `openbiliclaw init` 拉取历史并生成初始画像。",
        )
        raise typer.Exit(code=1) from exc

    discovery_engine = _build_discovery_engine()
    discovered = asyncio.run(
        discovery_engine.discover(
            profile_data,
            strategies=active_strategies or None,
            limit=limit,
        )
    )

    subtitle = "发现结果预览"
    if active_strategies:
        subtitle += f"（策略：{', '.join(active_strategies)}）"
    _print_page_title("本次内容发现", subtitle)
    if not discovered:
        _print_status_panel("info", "没有发现到新内容", "当前没有发现到新的可缓存内容。")
        return

    _print_key_value_table(
        "发现摘要",
        [
            ("发现条数", str(len(discovered))),
            ("缓存状态", "已写入 content_cache"),
            ("来源", "bilibili"),
            ("策略", ", ".join(active_strategies) if active_strategies else "全部"),
        ],
    )
    for index, item in enumerate(discovered[:5], start=1):
        _print_discovered_content_preview(item, index)


@app.command()
def chat() -> None:
    """与 Agent 对话（苏格拉底式深度交流）."""
    from openbiliclaw.soul.engine import SoulProfileNotInitializedError

    _require_runtime_config()
    soul_engine = _build_soul_engine()
    try:
        asyncio.run(soul_engine.get_profile())
    except SoulProfileNotInitializedError as exc:
        _print_status_panel(
            "warning",
            "尚未初始化用户画像",
            "请先执行 `openbiliclaw init` 拉取历史并生成初始画像。",
        )
        raise typer.Exit(code=1) from exc

    dialogue = _build_dialogue(soul_engine)
    _print_page_title("苏格拉底式对话", "输入 exit / quit / 空行结束")

    try:
        while True:
            try:
                user_message = typer.prompt("你", prompt_suffix="： ").strip()
            except (click.Abort, EOFError, KeyboardInterrupt):
                console.print("阿花：对话结束。")
                return

            if user_message.lower() in {"", "exit", "quit"}:
                console.print("阿花：对话结束。")
                return

            reply = asyncio.run(dialogue.respond(user_message))
            console.print(f"阿花：{reply}")
    except KeyboardInterrupt:
        console.print("阿花：对话结束。")


@app.command()
def delight() -> None:
    """手动触发一次惊喜推荐检查."""
    from openbiliclaw.recommendation.delight import DEFAULT_DELIGHT_THRESHOLD
    from openbiliclaw.soul.engine import SoulProfileNotInitializedError

    _require_runtime_config()
    soul_engine = _build_soul_engine()
    try:
        profile = asyncio.run(soul_engine.get_profile())
    except SoulProfileNotInitializedError as exc:
        _print_status_panel(
            "warning",
            "尚未初始化用户画像",
            "请先执行 `openbiliclaw init` 拉取历史并生成初始画像。",
        )
        raise typer.Exit(code=1) from exc

    database = _get_runtime_database()
    recommendation_engine = _build_recommendation_engine()

    # 先给未打分的条目打分
    asyncio.run(
        recommendation_engine.precompute_delight_scores(
            profile=profile,
            limit=30,
        )
    )

    candidate = database.get_delight_candidate(min_delight_score=DEFAULT_DELIGHT_THRESHOLD)

    _print_page_title("惊喜推荐", "从池中寻找你可能意外喜欢的内容")
    if candidate is None:
        _print_status_panel(
            "info",
            "暂时没有惊喜候选",
            "池中还没有文案已就绪的高分惊喜内容，多刷一阵会有的。",
        )
        return

    bvid = str(candidate.get("bvid", ""))
    title = str(candidate.get("title", ""))
    score = float(candidate.get("delight_score", 0.0))
    hook = str(candidate.get("delight_hook", ""))
    reason = str(candidate.get("delight_reason", ""))
    platform = str(candidate.get("source_platform", "") or "bilibili")
    url = str(candidate.get("content_url", ""))

    hook_label = f"【{hook}】" if hook else ""
    _print_key_value_table(
        f"{hook_label}阿B 觉得这条你会意外喜欢",
        [
            ("标题", title),
            ("惊喜分", f"{score:.2f}"),
            ("理由", reason or "—"),
            ("来源", platform),
            ("链接", url or f"https://www.bilibili.com/video/{bvid}"),
        ],
    )

    # 标记为已通知,避免再次推送
    database.mark_delight_notified(bvid)
    console.print(f"  [dim]已标记 {bvid} 为已通知，不会重复推送。[/dim]")


@app.command()
def probe() -> None:
    """手动触发一次兴趣探针，确认或拒绝猜测方向."""
    from openbiliclaw.soul.engine import SoulProfileNotInitializedError

    _require_runtime_config()
    soul_engine = _build_soul_engine()
    try:
        asyncio.run(soul_engine.get_profile())
    except SoulProfileNotInitializedError as exc:
        _print_status_panel(
            "warning",
            "尚未初始化用户画像",
            "请先执行 `openbiliclaw init` 拉取历史并生成初始画像。",
        )
        raise typer.Exit(code=1) from exc

    speculator = getattr(soul_engine, "_speculator", None)
    if speculator is None:
        _print_status_panel("info", "猜测引擎未就绪", "Speculator 未初始化。")
        raise typer.Exit(code=1)

    specs = speculator.get_active_speculations()
    _print_page_title("兴趣探针", "确认或拒绝阿B 正在试探的方向")

    if not specs:
        _print_status_panel("info", "暂时没有活跃的猜测", "过一阵阿B 会生成新的猜测方向。")
        return

    for i, spec in enumerate(specs, 1):
        specifics = [
            str(getattr(s, "name", "")).strip()
            for s in getattr(spec, "specifics", [])
            if str(getattr(s, "name", "")).strip()
        ][:3]
        hint = f"（{', '.join(specifics)}）" if specifics else ""
        progress = f"{spec.confirmation_count}/{spec.confirmation_threshold}"

        console.print(f"\n  [bold]{i}. {spec.domain}[/bold] {hint}")
        console.print(f"     理由：{spec.reason or '—'}")
        console.print(f"     确认进度：{progress}  置信度：{spec.confidence:.0%}")

    console.print()
    try:
        choice = typer.prompt(
            "输入序号确认（是），序号+n 拒绝（如 1n），或 q 退出",
            prompt_suffix="： ",
        ).strip()
    except (click.Abort, EOFError, KeyboardInterrupt):
        return

    if choice.lower() in {"q", "quit", "exit", ""}:
        return

    reject = choice.endswith("n") or choice.endswith("N")
    index_str = choice.rstrip("nN").strip()
    try:
        index = int(index_str) - 1
    except ValueError:
        console.print("[red]无效输入[/red]")
        raise typer.Exit(code=1) from None

    if index < 0 or index >= len(specs):
        console.print("[red]序号超出范围[/red]")
        raise typer.Exit(code=1)

    target = specs[index]
    domain = target.domain

    if reject:
        ok = speculator.user_reject_speculation(domain)
        if ok:
            console.print(f"  好，「{domain}」先不看了，30 天内不再猜测这个方向。")
        else:
            console.print(f"  [yellow]未找到活跃的「{domain}」猜测。[/yellow]")
    else:
        ok = speculator.user_confirm_speculation(domain)
        if ok:
            # 触发 promotion
            memory = getattr(soul_engine, "_memory", None)
            load_runtime_state = getattr(memory, "load_discovery_runtime_state", None)

            def _load_feedback_history() -> object:
                if not callable(load_runtime_state):
                    return []
                runtime_state = load_runtime_state()
                if not isinstance(runtime_state, dict):
                    return []
                return runtime_state.get("probe_feedback_history", [])

            profile = asyncio.run(soul_engine.get_profile())
            asyncio.run(
                speculator.force_tick(
                    profile,
                    feedback_history=_load_feedback_history(),
                    feedback_history_loader=_load_feedback_history,
                )
            )
            console.print(f"  好，「{domain}」记住了，已转入正式兴趣。")
        else:
            console.print(f"  [yellow]未找到活跃的「{domain}」猜测。[/yellow]")


@app.command()
def config_show() -> None:
    """显示当前配置."""
    from openbiliclaw.config import load_config_with_diagnostics
    from openbiliclaw.llm import RegistryBuildError, summarize_registry

    cfg, diagnostics = load_config_with_diagnostics()
    _print_page_title("当前配置概览", "运行时配置")
    rows = [
        ("语言", cfg.language),
        ("LLM", cfg.llm.default_provider),
        ("LLM 并发", str(cfg.llm.concurrency)),
        ("B站认证", cfg.bilibili.auth_method),
        ("定时任务", "开启" if cfg.scheduler.enabled else "关闭"),
        ("停止后台 LLM 请求", "否" if cfg.scheduler.enabled else "是"),
        (
            "浏览器断开后暂停",
            _format_pause_on_disconnect_status(
                enabled=cfg.scheduler.pause_on_extension_disconnect,
                grace_seconds=cfg.scheduler.extension_disconnect_grace_seconds,
            ),
        ),
        ("开机自启动", _format_autostart_config_status(cfg)),
        ("数据目录", str(cfg.data_path)),
    ]
    if diagnostics.config_path:
        rows.append(("配置文件", str(diagnostics.config_path)))
    _print_key_value_table("配置项", rows)

    try:
        registry = _build_registry()
        summary = summarize_registry(cfg, registry)
        _print_key_value_table(
            "Provider 概览",
            [
                ("已注册 Provider", ", ".join(summary.registered_providers)),
                ("最终默认 Provider", summary.effective_default),
            ],
        )
    except RegistryBuildError as exc:
        _print_key_value_table(
            "Provider 概览",
            [
                ("已注册 Provider", "无"),
                ("Provider 状态", str(exc)),
            ],
        )

    hints = diagnostics.messages + [
        f"{issue.field}: {issue.message}" for issue in diagnostics.issues
    ]
    _print_config_guidance(hints)


@auth_app.command("login")
def auth_login(
    cookie: str | None = typer.Option(None, "--cookie", help="直接传入完整 Cookie"),
) -> None:
    """交互式设置并验证 B 站 Cookie."""
    manager = _build_auth_manager()
    cookie_value = cookie or typer.prompt("请输入 B 站 Cookie", prompt_suffix=": ")
    status = asyncio.run(manager.validate_cookie(cookie_value))
    if not status.authenticated:
        console.print("[bold red]认证失败[/bold red]")
        _print_auth_status(status)
        raise typer.Exit(code=1)

    manager.set_cookie(cookie_value)
    console.print("[bold green]登录成功[/bold green]")
    _print_auth_status(status)


@auth_app.command("status")
def auth_status() -> None:
    """查看当前 B 站 Cookie 认证状态."""
    manager = _build_auth_manager()
    status = asyncio.run(manager.get_status())
    _print_auth_status(status)


@login_app.command("codex")
def login_codex(
    import_credentials: bool = _CODEX_LOGIN_IMPORT_OPTION,
    source: Path | None = _CODEX_LOGIN_SOURCE_OPTION,
    status: bool = _CODEX_LOGIN_STATUS_OPTION,
    logout: bool = _CODEX_LOGIN_LOGOUT_OPTION,
) -> None:
    """导入或管理 Codex CLI 的 ChatGPT OAuth 凭据."""
    from datetime import datetime

    from openbiliclaw.llm.codex_auth import (
        CodexAuthError,
        CodexCredentials,
        delete_codex_credentials,
        import_codex_credentials,
        load_codex_credentials,
        run_codex_cli_login,
    )

    def _print_codex_credentials(credentials: CodexCredentials) -> None:
        expires = datetime.fromtimestamp(credentials.expires_at).strftime("%Y-%m-%d %H:%M:%S")
        state = "临期/需刷新" if credentials.is_expired() else "有效"
        _print_key_value_table(
            "Codex OAuth",
            [
                ("状态", f"已登录（{state}）"),
                ("账号", credentials.account_id or "（未知）"),
                ("过期时间", expires),
            ],
        )

    if status:
        credentials = load_codex_credentials()
        if credentials is None:
            _print_status_panel(
                "warning",
                "Codex OAuth",
                "未登录。请运行 `openbiliclaw login codex` "
                "或 `openbiliclaw login codex --import`。",
            )
            return
        _print_codex_credentials(credentials)
        return

    if logout:
        deleted = delete_codex_credentials()
        body = "已登出 Codex OAuth。" if deleted else "本地没有 Codex OAuth 凭据。"
        _print_status_panel("success" if deleted else "info", "Codex OAuth", body)
        return

    try:
        if import_credentials or source is not None:
            credentials = import_codex_credentials(source=source)
        else:
            try:
                credentials = import_codex_credentials()
            except CodexAuthError:
                console.print("[dim]未找到可导入的 Codex 凭据，启动 `codex login`...[/dim]")
                run_codex_cli_login()
                credentials = import_codex_credentials()
    except CodexAuthError as exc:
        _print_status_panel("error", "Codex OAuth 登录失败", str(exc))
        raise typer.Exit(code=1) from exc

    _print_status_panel("success", "Codex OAuth", "登录凭据已导入。")
    _print_codex_credentials(credentials)


@app.command("health-check")
def health_check() -> None:
    """检查当前已注册 LLM provider 的可用性."""
    from openbiliclaw.llm import RegistryBuildError

    try:
        registry = _build_registry()
    except RegistryBuildError as exc:
        _print_status_panel("error", "Provider 健康检查失败", str(exc))
        raise typer.Exit(code=1) from exc

    results = asyncio.run(registry.health_check_all())
    _print_page_title("Provider 健康检查", "已注册 LLM Provider 状态")
    for name, result in results.items():
        status = "可用" if result.available else "不可用"
        default_label = " (default)" if result.is_default else ""
        console.print(f"  {name}{default_label}: {status}")
        if result.error:
            console.print(f"    原因: {result.error}")


@browser_app.command("status")
def browser_status() -> None:
    """检查 agent-browser 是否可用."""
    browser = _build_browser()
    _print_browser_status(browser)
    if browser.is_available:
        return
    console.print(f"  安装提示: {browser.get_install_hint()}")
    raise typer.Exit(code=1)


@browser_app.command("open")
def browser_open(url: str) -> None:
    """通过 agent-browser 打开一个页面."""
    from openbiliclaw.bilibili.browser import BrowserCommandError

    browser = _build_browser()
    if not browser.is_available:
        _print_status_panel("error", "agent-browser 未安装", browser.get_install_hint())
        raise typer.Exit(code=1)

    try:
        asyncio.run(browser.navigate(url))
    except BrowserCommandError as exc:
        _print_status_panel("error", "浏览器操作失败", str(exc))
        raise typer.Exit(code=1) from exc

    _print_page_title("浏览器已打开")
    _print_key_value_table("目标地址", [("URL", url)])


@browser_app.command("content")
def browser_content(url: str) -> None:
    """抓取当前页面可见文本."""
    from openbiliclaw.bilibili.browser import BrowserCommandError

    browser = _build_browser()
    if not browser.is_available:
        _print_status_panel("error", "agent-browser 未安装", browser.get_install_hint())
        raise typer.Exit(code=1)

    try:
        content = asyncio.run(browser.get_page_content(url))
    except BrowserCommandError as exc:
        _print_status_panel("error", "浏览器操作失败", str(exc))
        raise typer.Exit(code=1) from exc

    _print_page_title("页面内容")
    console.print(Panel(content, border_style="cyan"))


if __name__ == "__main__":
    app()
