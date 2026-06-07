"""
启动任务分级定义。

启动任务分为三个层级：
- BLOCKING:  必须在服务 ready 前完成，阻塞启动
- WARMUP:    服务 ready 后可异步后台执行
- LAZY:      首次实际使用该功能时才触发
"""
from enum import Enum
from dataclasses import dataclass, field
from typing import Callable, Awaitable


class StartupTier(Enum):
    BLOCKING = "blocking"   # 阻塞式核心任务
    WARMUP = "warmup"       # 启动后后台预热
    LAZY = "lazy"           # 首次访问按需初始化


@dataclass
class StartupTask:
    """单个启动任务定义。"""
    name: str
    tier: StartupTier
    # 异步执行函数
    coro: Callable[[], Awaitable[None]]
    # 依赖的任务名列表（依赖必须先完成）
    depends_on: list[str] = field(default_factory=list)
    # 是否仅在非 SKIP_INIT_DB 环境下执行
    requires_db: bool = True
    # 开发快启模式下是否跳过
    skip_in_dev_fast: bool = False


def get_startup_tasks(
    *,
    init_db_fn,
    billing_create_all_fn,
    pricing_init_fn,
    rbac_init_fn,
    owner_user_init_fn,
    marketplace_seed_fn,
    plugin_discover_fn,
    plugin_load_all_fn,
    scheduled_task_start_fn,
    weixin_auto_reply_start_fn,
) -> list[StartupTask]:
    """构建启动任务列表，依赖通过参数注入以保持可测试。"""

    return [
        StartupTask(
            name="db_init",
            tier=StartupTier.BLOCKING,
            coro=init_db_fn,
            requires_db=True,
            skip_in_dev_fast=False,
        ),
        StartupTask(
            name="billing_tables",
            tier=StartupTier.BLOCKING,
            coro=billing_create_all_fn,
            depends_on=["db_init"],
            requires_db=True,
            skip_in_dev_fast=False,
        ),
        StartupTask(
            name="pricing_init",
            tier=StartupTier.BLOCKING,
            coro=pricing_init_fn,
            depends_on=["billing_tables"],
            requires_db=True,
            skip_in_dev_fast=False,
        ),
        StartupTask(
            name="rbac_init",
            tier=StartupTier.BLOCKING,
            coro=rbac_init_fn,
            depends_on=["db_init"],
            requires_db=True,
            skip_in_dev_fast=False,
        ),
        StartupTask(
            name="owner_user_init",
            tier=StartupTier.BLOCKING,
            coro=owner_user_init_fn,
            depends_on=["db_init", "rbac_init"],
            requires_db=True,
            skip_in_dev_fast=False,
        ),
        StartupTask(
            name="marketplace_seed",
            tier=StartupTier.WARMUP,  # P0: 从阻塞改为预热
            coro=marketplace_seed_fn,
            depends_on=["db_init"],
            requires_db=True,
            skip_in_dev_fast=True,
        ),
        StartupTask(
            name="plugin_discover",
            tier=StartupTier.BLOCKING,
            coro=plugin_discover_fn,
            depends_on=["db_init"],
            requires_db=True,
            skip_in_dev_fast=False,
        ),
        StartupTask(
            name="plugin_load_enabled",
            tier=StartupTier.WARMUP,  # P0: 从阻塞改为预热
            coro=plugin_load_all_fn,
            depends_on=["plugin_discover"],
            requires_db=True,
            skip_in_dev_fast=True,
        ),
        StartupTask(
            name="scheduled_task_start",
            tier=StartupTier.BLOCKING,
            coro=scheduled_task_start_fn,
            depends_on=[],
            requires_db=False,
            skip_in_dev_fast=False,
        ),
        StartupTask(
            name="weixin_auto_reply",
            tier=StartupTier.WARMUP,  # P0: 从阻塞改为预热
            coro=weixin_auto_reply_start_fn,
            depends_on=["db_init"],
            requires_db=True,
            skip_in_dev_fast=True,
        ),
    ]
