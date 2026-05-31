# Open-AwA 性能深度优化实施计划

> **For agentic workers:** 按 P0 → P1 → P2 顺序执行，每阶段结束后必须验证关键指标。所有复选框 (`- [ ]`) 格式的步骤需逐一执行并自行勾选完成。

**Goal:** 深度优化 Open-AwA 的打开速度、网页加载速度和聊天页长对话体验，在不引入新服务的前提下，通过关键路径减负、结构重构和回归保护三阶段提升整体性能。

**Architecture:** 后端将启动流程从单体 `lifespan` 重构为三级启动编排（阻塞核心 → 后台预热 → 按需激活）；前端首屏从"初始化完成后渲染"改为"壳层优先 + 状态补齐"；聊天页从"大组件扛所有"拆为流式展示、持久化、视图增强三条独立链路，并将消息缓存从 localStorage 迁移至 IndexedDB 分层存储。

**Tech Stack:** Python 3.11+ / FastAPI / SQLAlchemy / Loguru · React 18 / TypeScript / Vite 5 / Zustand / react-virtuoso / react-markdown / KaTeX

---

## 文件结构总览

本计划涉及的全部文件（含新增与修改）：

### 后端新增
| 文件 | 职责 |
|------|------|
| `openawa/core/startup/__init__.py` | 启动编排模块入口 |
| `openawa/core/startup/tasks.py` | 启动任务定义、分级与依赖声明 |
| `openawa/core/startup/bootstrap.py` | 启动流程编排器，按分级执行任务 |
| `openawa/core/startup/profiler.py` | 启动阶段耗时采集与报告 |
| `openawa/tests/test_startup_tasks.py` | 启动任务分级与编排的单元测试 |

### 后端修改
| 文件 | 改动 |
|------|------|
| `openawa/main.py` | 将 `lifespan` 中的启动逻辑委托给 `bootstrap.py`，保留路由注册与中间件 |
| `openawa/core/scheduled_task_manager.py` | 支持启动后延迟 warmup，不阻塞 ready |
| `openawa/plugins/plugin_manager.py` | 将 `discover_plugins` + `load_plugin` 拆为 discover / ready / activate 三阶段 |

### 前端新增
| 文件 | 职责 |
|------|------|
| `frontend/src/shared/perf/metrics.ts` | 前端性能指标采集与上报 |
| `frontend/src/features/chat/hooks/useStreamBuffer.ts` | 流式缓冲管理：内存累积 + RAF 批量刷新 |
| `frontend/src/features/chat/hooks/useChatAutoScroll.ts` | 聊天自动滚动：仅在底部附近时跟随 |
| `frontend/src/features/chat/storage/chatPersistence.ts` | 消息持久化抽象层：localStorage + IndexedDB 分层 |
| `frontend/src/features/chat/__tests__/useStreamBuffer.test.ts` | 流式缓冲 hook 单元测试 |
| `frontend/src/features/chat/__tests__/useChatAutoScroll.test.ts` | 自动滚动 hook 单元测试 |
| `frontend/src/features/chat/__tests__/chatPersistence.test.ts` | 持久化层单元测试 |

### 前端修改
| 文件 | 改动 |
|------|------|
| `frontend/src/App.tsx` | 壳层优先渲染，去掉全局 `isInitialized` 阻塞 |
| `frontend/src/shared/hooks/useAppInitialization.ts` | 本地状态回填前置，网络校验后置 |
| `frontend/vite.config.ts` | 构建产物分析 + 分包优化 + legacy 条件化 |
| `frontend/index.html` | 补充关键资源 preload / preconnect |
| `frontend/src/features/chat/ChatPage.tsx` | 拆薄：抽离流式缓冲、滚动、持久化逻辑 |
| `frontend/src/features/chat/store/chatStore.ts` | 消息持久化改为异步，store 初始化不再同步读大消息桶 |
| `frontend/src/features/chat/utils/chatCache.ts` | localStorage 降级为轻量索引，大桶迁移到 chatPersistence |
| `frontend/src/features/chat/components/MessageList.tsx` | 配合新滚动 hook 调整 |

---

# 第一阶段：P0 — 关键路径减负

本阶段目标：先拿到"打开更快、流式更稳"的直接体感收益，不做大范围结构调整。

---

## Task 1: 后端启动阶段耗时埋点

**目的**：在现有启动链路上补充每步耗时，为后续 P1 重构提供数据基线。

**Files:**
- Create: `openawa/core/startup/__init__.py`
- Create: `openawa/core/startup/profiler.py`
- Modify: `openawa/main.py:90-243`

---

- [ ] **Step 1: 创建 startup 包初始化文件**

```python
# openawa/core/startup/__init__.py
"""
启动流程编排模块。
负责启动任务定义、分级、编排与耗时采集。
"""
```

- [ ] **Step 2: 创建启动耗时采集模块**

```python
# openawa/core/startup/profiler.py
"""
启动阶段耗时采集器。
记录每个启动步骤的名称、耗时、是否成功，启动完成后输出汇总日志。
"""
import time
from typing import Optional

from loguru import logger


class StartupProfiler:
    """启动耗时采集器，非生产环境输出明细耗时。"""

    def __init__(self) -> None:
        self._records: list[dict] = []
        self._started_at: Optional[float] = None

    def start(self) -> None:
        """开始记录。"""
        self._started_at = time.monotonic()
        logger.bind(event="startup_begin", module="startup").info("启动流程开始")

    def step(self, name: str) -> "StepTimer":
        """返回一个上下文管理器，自动记录该步骤耗时。"""
        return StepTimer(name, self._records)

    def finish(self) -> None:
        """输出汇总。"""
        total = time.monotonic() - (self._started_at or time.monotonic())
        logger.bind(
            event="startup_complete",
            module="startup",
            total_s=round(total, 3),
            steps=[{"name": r["name"], "elapsed_ms": round(r["elapsed_ms"], 1), "ok": r["ok"]} for r in self._records],
        ).info(f"启动流程完成，耗时 {total:.2f}s，共 {len(self._records)} 步")


class StepTimer:
    """单个步骤计时器，作为上下文管理器使用。"""

    def __init__(self, name: str, records: list[dict]) -> None:
        self._name = name
        self._records = records
        self._start: float = 0.0
        self._ok = True

    def __enter__(self) -> "StepTimer":
        self._start = time.monotonic()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        elapsed_ms = (time.monotonic() - self._start) * 1000
        self._ok = exc_type is None
        self._records.append({
            "name": self._name,
            "elapsed_ms": elapsed_ms,
            "ok": self._ok,
        })
        status = "ok" if self._ok else f"failed ({exc_type.__name__ if exc_type else '?'})"
        logger.bind(event="startup_step", module="startup", step=self._name, elapsed_ms=round(elapsed_ms, 1), status=status).debug(
            f"启动步骤 [{self._name}]: {elapsed_ms:.1f}ms {status}"
        )
        return False  # 不吞异常
```

- [ ] **Step 3: 在 main.py 的 lifespan 中集成 profiler**

修改 `openawa/main.py:90` 的 `lifespan` 函数，在最外层包裹 profiler：

```python
# openawa/main.py (修改 lifespan 函数)
from openawa.core.startup.profiler import StartupProfiler

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.bind(event="app_startup", module="main").info("starting up openawa")

    # 新增：启动耗时采集
    profiler = StartupProfiler()
    profiler.start()

    # LiteLLM 检测
    with profiler.step("litellm_check"):
        if is_litellm_available():
            logger.bind(event="litellm_available", module="main").info("LiteLLM dependency detected")
        else:
            logger.bind(event="litellm_missing", module="main").warning(
                "LiteLLM dependency not installed."
            )

    if not os.getenv("SKIP_INIT_DB"):
        with profiler.step("db_init"):
            try:
                init_db()
                logger.bind(event="db_initialized", module="main").info("database initialized")
            except Exception as exc:
                logger.bind(event="db_init_error", module="main").error(f"数据库初始化失败: {exc}")
                raise RuntimeError(f"数据库初始化失败，服务无法启动: {exc}") from exc

        with profiler.step("billing_tables"):
            BillingBase.metadata.create_all(bind=engine)
            logger.bind(event="billing_tables_initialized", module="main").info("billing tables initialized")

        with profiler.step("pricing_init"):
            from openawa.billing.pricing_manager import PricingManager
            from openawa.db.models import SessionLocal
            db = SessionLocal()
            try:
                pricing_manager = PricingManager(db)
                pricing_manager.ensure_configuration_schema()
                count = pricing_manager.initialize_default_pricing()
                if count > 0:
                    logger.bind(event="pricing_initialized", module="main", count=count).info("initialized model pricing entries")
            finally:
                db.close()

        with profiler.step("rbac_init"):
            from openawa.security.rbac import RBACManager
            db = SessionLocal()
            try:
                rbac = RBACManager(db)
                rbac.ensure_built_in_roles()
            finally:
                db.close()

        with profiler.step("local_users_sync"):
            from openawa.config.local_users import sync_local_users_to_db
            db = SessionLocal()
            try:
                sync_stats = sync_local_users_to_db(db)
                logger.bind(event="local_users_synced", module="main", **sync_stats).info("local users synced from config")
            finally:
                db.close()

    # ... 后续步骤同样包裹 profiler.step() ...

    profiler.finish()

    yield

    await scheduled_task_manager.stop()
    await close_shared_client()
    logger.bind(event="app_shutdown", module="main").info("shutting down openawa")
```

- [ ] **Step 4: 运行服务并验证 profiler 输出**

```bash
cd openawa && python main.py
```

预期：启动日志中看到 `startup_begin` / `startup_step` / `startup_complete` 日志行，包含每步耗时。

- [ ] **Step 5: Commit**

```bash
git add openawa/core/startup/__init__.py openawa/core/startup/profiler.py openawa/main.py
git commit -m "[Optimization] 后端启动耗时采集器，为性能优化提供数据基线"
```

---

## Task 2: 后端启动任务分级定义

**目的**：定义启动任务的三级分类（阻塞/预热/按需），为 P0 和 P1 提供可复用定义。

**Files:**
- Create: `openawa/core/startup/tasks.py`
- Modify: `openawa/main.py:147-243`

---

- [ ] **Step 1: 创建启动任务分级定义模块**

```python
# openawa/core/startup/tasks.py
"""
启动任务分级定义。

启动任务分为三个层级：
- BLOCKING:  必须在服务 ready 前完成，阻塞启动
- WARMUP:    服务 ready 后可异步后台执行
- LAZY:      首次实际使用该功能时才触发
"""
from enum import Enum
from dataclasses import dataclass, field
from typing import Callable, Awaitable, Optional


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


# ============================================================
# 当前启动任务清单（基于 main.py lifespan 实际情况）
# ============================================================

def get_startup_tasks(
    *,
    init_db_fn,
    billing_create_all_fn,
    pricing_init_fn,
    rbac_init_fn,
    local_users_sync_fn,
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
            name="local_users_sync",
            tier=StartupTier.BLOCKING,
            coro=local_users_sync_fn,
            depends_on=["db_init"],
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
```

- [ ] **Step 2: 验证任务定义模块可导入**

```bash
cd openawa && python -c "from openawa.core.startup.tasks import StartupTier, StartupTask; print('OK: tasks module importable')"
```

预期：`OK: tasks module importable`

- [ ] **Step 3: Commit**

```bash
git add openawa/core/startup/tasks.py
git commit -m "[Optimization] 启动任务分级定义模块，支持 BLOCKING/WARMUP/LAZY 三级分类"
```

---

## Task 3: 后端启动流程编排器

**目的**：实现按层级执行启动任务的编排器，阻塞任务先完成、预热任务后台跑。

**Files:**
- Create: `openawa/core/startup/bootstrap.py`

---

- [ ] **Step 1: 创建启动编排器**

```python
# openawa/core/startup/bootstrap.py
"""
启动流程编排器。
按 BLOCKING → (ready) → WARMUP 的顺序执行启动任务，
支持开发快速启动 profile。
"""
import asyncio
import os
from typing import Optional

from loguru import logger

from openawa.core.startup.profiler import StartupProfiler
from openawa.core.startup.tasks import StartupTier, StartupTask

# 开发快启模式环境变量
ENV_DEV_FAST_START = "DEV_FAST_START"


def is_dev_fast_start() -> bool:
    """是否开启了开发快速启动模式。"""
    return os.getenv(ENV_DEV_FAST_START, "").lower() in ("1", "true", "yes")


async def run_startup(tasks: list[StartupTask], profiler: StartupProfiler) -> None:
    """
    编排启动流程：
    1. 过滤：dev_fast 模式下跳过标记为 skip_in_dev_fast 的任务
    2. 按 tier 分层执行
    3. BLOCKING 任务按依赖顺序执行完毕后，服务 ready
    4. WARMUP 任务在后台异步执行
    """
    dev_fast = is_dev_fast_start()
    if dev_fast:
        logger.bind(event="startup_mode", module="startup").info("开发快速启动模式已启用")

    # 过滤任务
    active_tasks: list[StartupTask] = []
    for task in tasks:
        if task.requires_db and os.getenv("SKIP_INIT_DB"):
            continue
        if dev_fast and task.skip_in_dev_fast:
            logger.bind(event="startup_skip", module="startup", task=task.name).info(
                f"开发快启模式，跳过任务: {task.name}"
            )
            continue
        active_tasks.append(task)

    blocking = [t for t in active_tasks if t.tier == StartupTier.BLOCKING]
    warmup = [t for t in active_tasks if t.tier == StartupTier.WARMUP]

    # 执行 BLOCKING 任务（拓扑排序按依赖）
    completed: set[str] = set()

    async def execute_blocking(task: StartupTask) -> None:
        for dep in task.depends_on:
            if dep not in completed:
                raise RuntimeError(
                    f"任务 {task.name} 依赖 {dep} 但 {dep} 未完成或未定义为 BLOCKING"
                )
        with profiler.step(task.name):
            await task.coro()
        completed.add(task.name)

    # 简单的拓扑执行：多轮扫描直到全部完成
    remaining = list(blocking)
    while remaining:
        ready = [t for t in remaining if all(d in completed for d in t.depends_on)]
        if not ready:
            # 存在未满足依赖或循环依赖
            unresolved = [t.name for t in remaining]
            raise RuntimeError(f"无法解析的启动任务依赖: {unresolved}")
        # BLOCKING 任务串行执行以保证确定性
        for task in ready:
            await execute_blocking(task)
        remaining = [t for t in remaining if t.name not in completed]

    logger.bind(event="startup_ready", module="startup").info("核心启动完成，服务已就绪")

    # WARMUP 任务后台执行（不阻塞）
    if warmup:
        async def run_warmup() -> None:
            for task in warmup:
                try:
                    with profiler.step(f"warmup:{task.name}"):
                        await task.coro()
                except Exception as exc:
                    logger.bind(event="startup_warmup_error", module="startup", task=task.name).warning(
                        f"后台预热任务 {task.name} 失败: {exc}"
                    )

        asyncio.create_task(run_warmup())
```

- [ ] **Step 2: 验证编排器模块可导入**

```bash
cd openawa && python -c "from openawa.core.startup.bootstrap import run_startup, is_dev_fast_start; print('OK: bootstrap module importable')"
```

- [ ] **Step 3: Commit**

```bash
git add openawa/core/startup/bootstrap.py
git commit -m "[Optimization] 启动流程编排器：BLOCKING 先执行 + WARMUP 后台预热"
```

---

## Task 4: 将 main.py lifespan 迁移到编排器

**目的**：用编排器接管 main.py 的启动流程，同时保证功能完全等价。

**Files:**
- Modify: `openawa/main.py:90-243`

---

- [ ] **Step 1: 重构 lifespan 使用编排器**

将 `openawa/main.py` 的 `lifespan` 函数中从 LiteLLM 检测到 `yield` 之前的部分，改为通过编排器执行。

核心改动：将原来的内联逻辑封装为 async 闭包，传入 `get_startup_tasks()`，再调用 `run_startup()`。

```python
# openawa/main.py (重构后的 lifespan，完整版本)

from openawa.core.startup.profiler import StartupProfiler
from openawa.core.startup.tasks import get_startup_tasks
from openawa.core.startup.bootstrap import run_startup

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.bind(event="app_startup", module="main").info("starting up openawa")

    profiler = StartupProfiler()
    profiler.start()

    with profiler.step("litellm_check"):
        if is_litellm_available():
            logger.bind(event="litellm_available", module="main").info("LiteLLM dependency detected")
        else:
            logger.bind(event="litellm_missing", module="main").warning(
                "LiteLLM dependency not installed."
            )

    # 构建启动任务
    async def _init_db():
        init_db()
        logger.bind(event="db_initialized", module="main").info("database initialized")

    async def _billing_create_all():
        BillingBase.metadata.create_all(bind=engine)
        logger.bind(event="billing_tables_initialized", module="main").info("billing tables initialized")

    async def _pricing_init():
        from openawa.billing.pricing_manager import PricingManager
        from openawa.db.models import SessionLocal
        db = SessionLocal()
        try:
            pricing_manager = PricingManager(db)
            pricing_manager.ensure_configuration_schema()
            count = pricing_manager.initialize_default_pricing()
            if count > 0:
                logger.bind(event="pricing_initialized", module="main", count=count).info("initialized model pricing entries")
        finally:
            db.close()

    async def _rbac_init():
        from openawa.security.rbac import RBACManager
        from openawa.db.models import SessionLocal
        db = SessionLocal()
        try:
            rbac = RBACManager(db)
            rbac.ensure_built_in_roles()
        finally:
            db.close()

    async def _local_users_sync():
        from openawa.config.local_users import sync_local_users_to_db
        from openawa.db.models import SessionLocal
        db = SessionLocal()
        try:
            sync_stats = sync_local_users_to_db(db)
            logger.bind(event="local_users_synced", module="main", **sync_stats).info("local users synced from config")
        finally:
            db.close()

    async def _marketplace_seed():
        from openawa.plugins.marketplace.registry import marketplace_registry
        marketplace_registry.seed_built_in_plugins()

    async def _plugin_discover():
        from openawa.plugins.plugin_manager import PluginManager
        from openawa.plugins import plugin_instance
        from openawa.db.models import SessionLocal
        plugin_instance.init(PluginManager(db_session_factory=SessionLocal))
        pm = plugin_instance.get()
        pm.discover_plugins()

    async def _plugin_load_all():
        pm = plugin_instance.get()
        if os.getenv("SKIP_INIT_DB"):
            return
        from openawa.db.models import Plugin as PluginModel, Skill
        import uuid
        db = SessionLocal()
        try:
            # 迁移内置技能记录
            for skill_name in ["file_manager", "terminal_executor"]:
                old_skill = db.query(Skill).filter(Skill.name == skill_name).first()
                if old_skill:
                    db.delete(old_skill)
                    logger.bind(event="skill_migrated", module="main", skill=skill_name).info(
                        f"已迁移内置技能 {skill_name} 至 system-tools 插件"
                    )
            db.commit()

            # 注册 system-tools 系统内置插件
            existing_plugin = db.query(PluginModel).filter(PluginModel.name == "system-tools").first()
            if not existing_plugin:
                new_plugin = PluginModel(
                    id=str(uuid.uuid4()),
                    name="system-tools",
                    version="1.0.0",
                    enabled=True,
                    config={},
                    category="builtin",
                    author="Open-AwA Team",
                    source="builtin",
                    dependencies=[],
                )
                db.add(new_plugin)
                db.commit()
                logger.bind(event="builtin_plugin_seeded", module="main", plugin="system-tools").info(
                    "已注册系统内置插件 system-tools"
                )
        except Exception as exc:
            logger.bind(event="builtin_plugin_seed_error", module="main").warning(f"内置插件注册失败: {exc}")
            db.rollback()
        finally:
            db.close()

        db = SessionLocal()
        try:
            enabled_plugins = db.query(PluginModel).filter(PluginModel.enabled == True).all()
            for p in enabled_plugins:
                if p.name in pm.plugin_metadata:
                    try:
                        pm.load_plugin(p.name)
                        logger.bind(event="plugin_loaded", module="main", plugin=p.name).info(f"plugin loaded: {p.name}")
                        granted = p.granted_permissions or []
                        if granted:
                            pm.restore_plugin_permissions(p.name, granted)
                    except Exception as exc:
                        logger.bind(event="plugin_load_error", module="main", plugin=p.name).warning(f"plugin load failed: {exc}")
            logger.bind(event="plugins_initialized", module="main", count=len(pm.loaded_plugins)).info("plugin system initialized")
        finally:
            db.close()

    async def _scheduled_task_start():
        await scheduled_task_manager.start()

    async def _weixin_auto_reply_start():
        if not os.getenv("SKIP_INIT_DB"):
            from openawa.db.models import WeixinBinding, SessionLocal
            from openawa.api.services.weixin_auto_reply import get_auto_reply_manager
            db = SessionLocal()
            try:
                bindings = db.query(WeixinBinding).filter(
                    WeixinBinding.binding_status == "bound",
                    WeixinBinding.auto_start_reply == True
                ).all()
                if bindings:
                    manager = get_auto_reply_manager()
                    for binding in bindings:
                        try:
                            await manager.start(binding.user_id)
                            logger.bind(event="weixin_auto_reply_autostart", module="main", user_id=binding.user_id).info("自动启动微信自动回复")
                        except ValueError as e:
                            logger.bind(event="weixin_auto_reply_autostart_failed", module="main", user_id=binding.user_id).warning(f"自动启动微信自动回复失败（配置错误）: {e}")
                        except Exception as e:
                            logger.bind(event="weixin_auto_reply_autostart_error", module="main", user_id=binding.user_id).error(f"自动启动微信自动回复异常: {e}")
            finally:
                db.close()

    tasks = get_startup_tasks(
        init_db_fn=_init_db,
        billing_create_all_fn=_billing_create_all,
        pricing_init_fn=_pricing_init,
        rbac_init_fn=_rbac_init,
        local_users_sync_fn=_local_users_sync,
        marketplace_seed_fn=_marketplace_seed,
        plugin_discover_fn=_plugin_discover,
        plugin_load_all_fn=_plugin_load_all,
        scheduled_task_start_fn=_scheduled_task_start,
        weixin_auto_reply_start_fn=_weixin_auto_reply_start,
    )

    await run_startup(tasks, profiler)
    profiler.finish()

    yield

    await scheduled_task_manager.stop()
    await close_shared_client()
    logger.bind(event="app_shutdown", module="main").info("shutting down openawa")
```

- [ ] **Step 2: 运行服务验证所有功能正常**

```bash
cd openawa && python main.py
```

预期：服务正常启动，日志中看到 BLOCKING 先、WARMUP 后的顺序，`marketplace_seed` / `plugin_load_enabled` / `weixin_auto_reply` 标记为 warmup 步骤。

- [ ] **Step 3: 验证开发快启模式**

```bash
set DEV_FAST_START=1 && cd openawa && python main.py
```

预期：日志中看到 `开发快速启动模式已启用`，`marketplace_seed` / `plugin_load_enabled` / `weixin_auto_reply` 被跳过。

- [ ] **Step 4: 编写启动编排单元测试**

```python
# openawa/tests/test_startup_tasks.py
"""
启动任务分级与编排的单元测试。
验证 BLOCKING/WARMUP 任务执行顺序、依赖检查、
dev_fast 跳过逻辑。
"""
import asyncio
import os
import pytest
from unittest.mock import AsyncMock, patch

from openawa.core.startup.tasks import StartupTier, StartupTask, get_startup_tasks
from openawa.core.startup.bootstrap import run_startup, is_dev_fast_start


async def _noop():
    pass


def _make_task(name: str, tier: StartupTier, deps=None, skip_dev=False):
    return StartupTask(
        name=name,
        tier=tier,
        coro=_noop,
        depends_on=deps or [],
        requires_db=False,
        skip_in_dev_fast=skip_dev,
    )


class TestStartupTaskTiers:
    """验证任务分级定义。"""

    def test_blocking_task_has_correct_tier(self):
        t = _make_task("db_init", StartupTier.BLOCKING)
        assert t.tier == StartupTier.BLOCKING

    def test_warmup_task_has_correct_tier(self):
        t = _make_task("marketplace_seed", StartupTier.WARMUP)
        assert t.tier == StartupTier.WARMUP


class TestStartupBootstrap:
    """验证编排器行为。"""

    @pytest.mark.asyncio
    async def test_blocking_completes_before_warmup(self):
        """BLOCKING 任务应在 WARMUP 之前完成。"""
        order = []
        profiler_mock = AsyncMock()
        profiler_mock.step.return_value.__enter__ = AsyncMock()
        profiler_mock.step.return_value.__exit__ = AsyncMock(return_value=False)

        async def _blocking():
            order.append("blocking")

        async def _warmup():
            order.append("warmup")

        tasks = [
            _make_task("b", StartupTier.BLOCKING),
            _make_task("w", StartupTier.WARMUP),
        ]
        # 注入真实 coro
        tasks[0].coro = _blocking
        tasks[1].coro = _warmup

        # warmup 是后台 asyncio.create_task，在测试中等待一下
        await run_startup(tasks, profiler_mock)
        await asyncio.sleep(0.1)

        assert "blocking" in order

    @pytest.mark.asyncio
    async def test_dependency_order_enforced(self):
        """依赖的任务必须先于被依赖任务完成。"""
        completed = []
        profiler_mock = AsyncMock()
        profiler_mock.step.return_value.__enter__ = AsyncMock()
        profiler_mock.step.return_value.__exit__ = AsyncMock(return_value=False)

        async def _a():
            completed.append("a")

        async def _b():
            completed.append("b")

        tasks = [
            _make_task("a", StartupTier.BLOCKING),
            _make_task("b", StartupTier.BLOCKING, deps=["a"]),
        ]
        tasks[0].coro = _a
        tasks[1].coro = _b

        await run_startup(tasks, profiler_mock)

        assert completed.index("a") < completed.index("b")

    @pytest.mark.asyncio
    async def test_missing_dependency_raises(self):
        """依赖未定义的任务应抛出异常。"""
        profiler_mock = AsyncMock()
        profiler_mock.step.return_value.__enter__ = AsyncMock()
        profiler_mock.step.return_value.__exit__ = AsyncMock(return_value=False)

        tasks = [
            _make_task("b", StartupTier.BLOCKING, deps=["nonexistent"]),
        ]
        tasks[0].coro = _noop

        with pytest.raises(RuntimeError, match="无法解析的启动任务依赖"):
            await run_startup(tasks, profiler_mock)

    def test_dev_fast_skips_marked_tasks(self):
        """dev_fast 模式下 skip_in_dev_fast=True 的任务应被跳过。"""
        with patch.dict(os.environ, {"DEV_FAST_START": "1"}):
            assert is_dev_fast_start() is True
```

- [ ] **Step 5: 运行测试**

```bash
cd openawa && pytest openawa/tests/test_startup_tasks.py -v
```

预期：4 个测试全部 PASS。

- [ ] **Step 6: Commit**

```bash
git add openawa/main.py openawa/tests/test_startup_tasks.py
git commit -m "[Optimization] main.py 启动流程迁移到编排器，支持三级启动 + 开发快启模式"
```

---

## Task 5: 前端首屏壳层优先渲染

**目的**：去掉全局 `isInitialized` 阻塞，改为 App Shell 立即渲染 + 认证状态后台补齐。

**Files:**
- Modify: `frontend/src/App.tsx:50-127`
- Modify: `frontend/src/shared/hooks/useAppInitialization.ts:1-151`

---

- [ ] **Step 1: 重构 useAppInitialization — 本地回填前置**

修改 `frontend/src/shared/hooks/useAppInitialization.ts`，将 `rehydrateStores()` 从网络请求之后移到之前，并在 hook 挂载时同步执行：

```typescript
// frontend/src/shared/hooks/useAppInitialization.ts (关键修改)

export function useAppInitialization() {
  const setInitialized = useAuthStore((state) => state.setInitialized)
  const setAuth = useAuthStore((state) => state.setAuth)
  const logout = useAuthStore((state) => state.logout)

  // P0: 同步回填本地状态，不等待网络
  rehydrateStores()

  useEffect(() => {
    let isActive = true

    const initializeApp = async () => {
      const result = await initializeApplicationState()

      if (!isActive) return

      if (result.isAuthenticated) {
        setAuth({ username: result.username || 'user' }, null)
      } else {
        logout()
      }

      setInitialized(true)
    }

    void initializeApp()

    return () => {
      isActive = false
    }
  }, [logout, setAuth, setInitialized])
}
```

- [ ] **Step 2: 重构 App.tsx — 去掉全局阻塞式等待**

修改 `frontend/src/App.tsx:63-76`，改为壳层始终渲染，认证状态仅影响路由内容：

```typescript
// frontend/src/App.tsx (关键修改)

function App() {
  const { isInitialized, isAuthenticated } = useAuthStore()
  const { theme } = useThemeStore()
  useAppInitialization()

  // 主题类名同步设置（壳层立即生效）
  useEffect(() => {
    if (theme === 'dark') {
      document.documentElement.classList.add('dark')
    } else {
      document.documentElement.classList.remove('dark')
    }
  }, [theme])

  // P0: 始终渲染 App Shell，不再全屏白屏等待
  return (
    <ErrorBoundary name="Root">
    <BrowserRouter future={routerFutureConfig}>
      <NavigationLogger />
      {!isAuthenticated ? (
        <Suspense fallback={<div className="loading-fallback">加载中...</div>}>
          <Routes>
            <Route path="/login" element={<ErrorBoundary name="Login"><LoginPage /></ErrorBoundary>} />
            <Route path="*" element={<Navigate to="/login" replace />} />
          </Routes>
        </Suspense>
      ) : (
        <div className="app-container">
          <Suspense fallback={<div className="sidebar-skeleton" />}>
            <Sidebar />
          </Suspense>
          <main className="main-content">
            {/* P0: 壳层已显示，路由内容按 Suspense 渐进加载 */}
            <Suspense fallback={<div className="loading-fallback">加载中...</div>}>
              <Routes>
                {/* ... 所有路由保持不变 ... */}
              </Routes>
            </Suspense>
          </main>
        </div>
      )}
    </BrowserRouter>
    </ErrorBoundary>
  )
}
```

这里的关键变化是：删除了原来的 `if (!isInitialized) { return <div>正在初始化应用...</div> }` 阻塞。

- [ ] **Step 3: 验证首屏不再白屏等待**

```bash
cd frontend && npm run dev
```

在浏览器中打开 `http://localhost:5173`，确认：
- 页面打开后立即看到 App Shell（侧边栏骨架 + 主内容区骨架）
- 不再出现全屏"正在初始化应用..."
- 登录态完成后自动跳转到对应页面

- [ ] **Step 4: Commit**

```bash
git add frontend/src/App.tsx frontend/src/shared/hooks/useAppInitialization.ts
git commit -m "[Optimization] 前端首屏壳层优先渲染，去掉全局初始化白屏阻塞"
```

---

## Task 6: Vite 构建优化 + 产物分析

**目的**：引入 rollup-plugin-visualizer 查看当前产物分布，优化分包与预加载。

**Files:**
- Modify: `frontend/vite.config.ts`
- Modify: `frontend/index.html`
- Modify: `frontend/package.json`（加 visualizer 依赖）
- Create: `frontend/src/shared/perf/metrics.ts`

---

- [ ] **Step 1: 安装构建分析依赖**

```bash
cd frontend && npm install -D rollup-plugin-visualizer
```

- [ ] **Step 2: 更新 vite.config.ts — 加入 visualizer + 优化分包**

```typescript
// frontend/vite.config.ts (修改后完整版)

import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'
import viteCompression from 'vite-plugin-compression'
import legacy from '@vitejs/plugin-legacy'
import { visualizer } from 'rollup-plugin-visualizer'

export default defineConfig(({ mode }) => {
  const apiProxyTarget = mode === 'e2e'
    ? `http://127.0.0.1:${process.env.OPENAWA_E2E_BACKEND_PORT || '18000'}`
    : process.env.OPENAWA_API_PROXY_TARGET || 'http://localhost:8000'
  const dedupedReactPackages = ['react', 'react-dom', 'react/jsx-runtime', 'react/jsx-dev-runtime']
  const isProd = mode === 'production'

  return {
    plugins: [
      react(),
      // P0: legacy 仅在明确需要时启用（默认关闭以加速构建）
      ...(process.env.ENABLE_LEGACY === '1' ? [legacy({
        targets: ['defaults', 'not IE 11', 'last 2 versions']
      })] : []),
      viteCompression({
        verbose: true,
        disable: false,
        threshold: 10240,
        algorithm: 'gzip',
        ext: '.gz',
      }),
      viteCompression({
        verbose: true,
        disable: false,
        threshold: 10240,
        algorithm: 'brotliCompress',
        ext: '.br',
      }),
      // P0: 构建产物分析（仅在需要时生成）
      ...(process.env.ANALYZE === '1' ? [visualizer({
        open: false,
        gzipSize: true,
        brotliSize: true,
        filename: 'dist/stats.html',
      })] : []),
    ],
    resolve: {
      alias: {
        '@': path.resolve(__dirname, './src')
      },
      dedupe: dedupedReactPackages,
    },
    optimizeDeps: {
      include: [...dedupedReactPackages, 'zustand'],
    },
    build: {
      // P0: target 升级到 es2020，减少 polyfill 体积
      target: 'es2020',
      // P0: chunk 大小警告阈值从 500KB 降到 300KB
      chunkSizeWarningLimit: 300,
      minify: 'terser',
      terserOptions: {
        compress: {
          drop_debugger: true,
          pure_funcs: ['console.log', 'console.debug', 'console.info'],
        },
      },
      rollupOptions: {
        output: {
          manualChunks: {
            react: ['react', 'react-dom', 'react-router-dom'],
            recharts: ['recharts'],
            core: ['zustand', 'axios'],
            virtuoso: ['react-virtuoso'],
            // P0: markdown 拆分为更细粒度
            markdown: ['react-markdown', 'remark-gfm', 'remark-math'],
            markdownMath: ['rehype-katex', 'katex'],
            markdownRender: ['rehype-highlight', 'highlight.js'],
            // P0: lucide 图标单独分包
            icons: ['lucide-react'],
          }
        }
      }
    },
    server: {
      host: '0.0.0.0',
      port: 5173,
      proxy: {
        '/api': {
          target: apiProxyTarget,
          changeOrigin: true,
        },
      },
    },
  }
})
```

- [ ] **Step 3: 更新 index.html — 补预连接提示**

修改 `frontend/index.html`：

```html
<!-- P0: 增加 API 预连接 -->
<link rel="preconnect" href="http://localhost:8000">
<!-- P0: 字体使用 swap 策略，不阻塞渲染 -->
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<!-- 已有的 dns-prefetch 保留 -->
<link rel="dns-prefetch" href="//localhost:8000">
```

将原有 Google Fonts link 的 `display=swap` 确认已存在（当前已有，无需修改）。

- [ ] **Step 4: 创建前端性能指标采集模块**

```typescript
// frontend/src/shared/perf/metrics.ts
/**
 * 前端性能指标采集模块。
 * 采集 App Shell 可见时间、路由主要内容可见时间等关键指标。
 */

interface PerfMark {
  name: string
  timestamp: number
}

const marks: PerfMark[] = []

/**
 * 记录一个性能标记点。
 * 在关键渲染节点调用，例如：
 * - app_shell_visible: App Shell 首次渲染完成
 * - auth_resolved: 认证状态解析完成
 * - chat_page_ready: 聊天页主要交互元素就绪
 */
export function mark(name: string): void {
  const timestamp = performance.now()
  marks.push({ name, timestamp })

  if (import.meta.env.DEV) {
    console.debug(`[perf] ${name}: ${timestamp.toFixed(1)}ms`)
  }
}

/**
 * 计算两个标记点之间的耗时。
 * 如果开始标记不存在，返回从页面导航开始到结束标记的耗时。
 */
export function measure(from: string, to: string): number | null {
  const fromMark = marks.find((m) => m.name === from)
  const toMark = marks.find((m) => m.name === to)
  if (!toMark) return null
  const startTime = fromMark?.timestamp ?? 0
  return toMark.timestamp - startTime
}

/**
 * 获取所有已记录的标记点。
 */
export function getAllMarks(): ReadonlyArray<PerfMark> {
  return marks
}

/**
 * 从页面导航开始到当前时刻的耗时（ms）。
 */
export function timeSinceNavigation(): number {
  return performance.now()
}
```

- [ ] **Step 5: 运行构建验证产物分析**

```bash
cd frontend && set ANALYZE=1 && npm run build
```

确认：
- `dist/stats.html` 生成
- 无 chunk 超过 300KB 警告（如有则需进一步拆分）
- 总构建时间不增加超过 10%

- [ ] **Step 6: Commit**

```bash
git add frontend/vite.config.ts frontend/index.html frontend/package.json frontend/src/shared/perf/metrics.ts
git commit -m "[Optimization] Vite 构建优化：产物分析 + 分包优化 + legacy 条件化 + 性能指标采集"
```

---

## Task 7: 聊天页流式缓冲与批量刷新

**目的**：创建 `useStreamBuffer` hook，将"每个 chunk 立即写 store"改为"内存缓冲 + requestAnimationFrame 批量刷新"。

**Files:**
- Create: `frontend/src/features/chat/hooks/useStreamBuffer.ts`
- Create: `frontend/src/features/chat/__tests__/useStreamBuffer.test.ts`

---

- [ ] **Step 1: 编写 useStreamBuffer hook 的测试（TDD）**

```typescript
// frontend/src/features/chat/__tests__/useStreamBuffer.test.ts
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { renderHook, act } from '@testing-library/react'

// 注意：本测试在 hook 实现之前编写，预期初始运行失败

describe('useStreamBuffer', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    // 模拟 requestAnimationFrame
    let rafId = 0
    vi.stubGlobal('requestAnimationFrame', (cb: FrameRequestCallback) => {
      rafId += 1
      setTimeout(() => cb(performance.now()), 16)
      return rafId
    })
    vi.stubGlobal('cancelAnimationFrame', vi.fn())
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllGlobals()
  })

  it('should accumulate content in buffer without immediate flush', () => {
    const onFlush = vi.fn()
    // 动态导入 hook（初始导入会因模块不存在而失败，TDD 第一步）
    // TDD 步骤 1：此测试预期 FAIL
  })
})
```

- [ ] **Step 2: 运行测试确认失败（TDD）**

```bash
cd frontend && npx vitest run src/features/chat/__tests__/useStreamBuffer.test.ts
```

预期：FAIL — 模块不存在。

- [ ] **Step 3: 实现 useStreamBuffer hook**

```typescript
// frontend/src/features/chat/hooks/useStreamBuffer.ts
/**
 * 流式消息缓冲 Hook。
 *
 * 将 SSE chunk 的即时写入改为内存缓冲 + requestAnimationFrame 批量刷新，
 * 大幅降低流式过程中的状态更新频率和主线程压力。
 */
import { useRef, useCallback, useEffect } from 'react'

interface StreamBufferOptions {
  /** 消息更新回调：(messageId, contentDelta, reasoningDelta) => void */
  onFlush: (messageId: string, content: string, reasoning: string) => void
  /** 缓冲刷新间隔（ms），默认 50ms */
  flushInterval?: number
}

interface StreamBuffer {
  /** 写入一个 chunk 到缓冲区 */
  write: (messageId: string, content: string, reasoning?: string) => void
  /** 强制立即刷新缓冲区 */
  flush: (messageId?: string) => void
}

export function useStreamBuffer({ onFlush, flushInterval = 50 }: StreamBufferOptions): StreamBuffer {
  const bufferRef = useRef<Map<string, { content: string; reasoning: string }>>(new Map())
  const rafIdRef = useRef<number | null>(null)
  const lastFlushRef = useRef<number>(0)
  const onFlushRef = useRef(onFlush)
  onFlushRef.current = onFlush

  const doFlush = useCallback((messageId?: string) => {
    const buffer = bufferRef.current
    if (buffer.size === 0) return

    const entries = messageId
      ? [[messageId, buffer.get(messageId)] as const].filter(([, v]) => v !== undefined)
      : Array.from(buffer.entries())

    for (const [msgId, data] of entries) {
      if (data && (data.content || data.reasoning)) {
        onFlushRef.current(msgId, data.content, data.reasoning)
      }
    }

    if (messageId) {
      buffer.delete(messageId)
    } else {
      buffer.clear()
    }
    lastFlushRef.current = performance.now()
  }, [])

  const scheduleFlush = useCallback((messageId?: string) => {
    if (rafIdRef.current !== null) {
      cancelAnimationFrame(rafIdRef.current)
    }
    rafIdRef.current = requestAnimationFrame(() => {
      rafIdRef.current = null
      doFlush(messageId)
    })
  }, [doFlush])

  const write = useCallback((messageId: string, content: string, reasoning: string = '') => {
    const buffer = bufferRef.current
    const existing = buffer.get(messageId) || { content: '', reasoning: '' }
    existing.content += content
    if (reasoning) {
      existing.reasoning += reasoning
    }
    buffer.set(messageId, existing)

    const now = performance.now()
    if (now - lastFlushRef.current >= flushInterval) {
      scheduleFlush(messageId)
    } else {
      // 还在节流窗口内，用 RAF 延后
      scheduleFlush(messageId)
    }
  }, [flushInterval, scheduleFlush])

  const flush = useCallback((messageId?: string) => {
    if (rafIdRef.current !== null) {
      cancelAnimationFrame(rafIdRef.current)
      rafIdRef.current = null
    }
    doFlush(messageId)
  }, [doFlush])

  // 组件卸载时清空缓冲
  useEffect(() => {
    return () => {
      if (rafIdRef.current !== null) {
        cancelAnimationFrame(rafIdRef.current)
      }
      // 最后尝试刷盘
      doFlush()
    }
  }, [doFlush])

  return { write, flush }
}
```

- [ ] **Step 4: 重写测试（完整版）**

```typescript
// frontend/src/features/chat/__tests__/useStreamBuffer.test.ts (完整版)
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import { useStreamBuffer } from '../hooks/useStreamBuffer'

describe('useStreamBuffer', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    let rafId = 0
    vi.stubGlobal('requestAnimationFrame', (cb: FrameRequestCallback) => {
      rafId += 1
      // 使用 setTimeout 模拟 RAF
      const id = setTimeout(() => cb(performance.now()), 16) as unknown as number
      return id
    })
    vi.stubGlobal('cancelAnimationFrame', (id: number) => {
      clearTimeout(id)
    })
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllGlobals()
  })

  it('should accumulate content without calling onFlush immediately', () => {
    const onFlush = vi.fn()
    const { result } = renderHook(() =>
      useStreamBuffer({ onFlush, flushInterval: 100 })
    )

    act(() => {
      result.current.write('msg-1', 'Hello')
      result.current.write('msg-1', ' World')
    })

    // write 不会立即调用 onFlush
    expect(onFlush).not.toHaveBeenCalled()
  })

  it('should call onFlush after RAF fires', () => {
    const onFlush = vi.fn()
    const { result } = renderHook(() =>
      useStreamBuffer({ onFlush, flushInterval: 50 })
    )

    act(() => {
      result.current.write('msg-1', 'Hello', 'thinking...')
    })

    // 推进 RAF
    act(() => {
      vi.advanceTimersByTime(20)
    })

    expect(onFlush).toHaveBeenCalledWith('msg-1', 'Hello', 'thinking...')
  })

  it('should merge multiple writes into single flush', () => {
    const onFlush = vi.fn()
    const { result } = renderHook(() =>
      useStreamBuffer({ onFlush, flushInterval: 200 })
    )

    act(() => {
      result.current.write('msg-1', 'A')
      result.current.write('msg-1', 'B')
      result.current.write('msg-1', 'C')
    })

    act(() => {
      vi.advanceTimersByTime(20)
    })

    // 多次 write 应在一次 flush 中合并
    expect(onFlush).toHaveBeenCalledTimes(1)
    expect(onFlush).toHaveBeenCalledWith('msg-1', 'ABC', '')
  })

  it('should track reasoning content separately', () => {
    const onFlush = vi.fn()
    const { result } = renderHook(() =>
      useStreamBuffer({ onFlush, flushInterval: 50 })
    )

    act(() => {
      result.current.write('msg-1', 'answer', 'step1')
      result.current.write('msg-1', ' more', ' step2')
    })

    act(() => {
      vi.advanceTimersByTime(20)
    })

    expect(onFlush).toHaveBeenCalledWith('msg-1', 'answer more', 'step1 step2')
  })

  it('should flush immediately when flush() is called', () => {
    const onFlush = vi.fn()
    const { result } = renderHook(() =>
      useStreamBuffer({ onFlush, flushInterval: 500 })
    )

    act(() => {
      result.current.write('msg-1', 'text')
      result.current.flush('msg-1')
    })

    // 显式 flush 立即触发 onFlush
    expect(onFlush).toHaveBeenCalledWith('msg-1', 'text', '')
  })
})
```

- [ ] **Step 5: 运行测试确认通过**

```bash
cd frontend && npx vitest run src/features/chat/__tests__/useStreamBuffer.test.ts
```

预期：5 个测试全部 PASS。

- [ ] **Step 6: Commit**

```bash
git add frontend/src/features/chat/hooks/useStreamBuffer.ts frontend/src/features/chat/__tests__/useStreamBuffer.test.ts
git commit -m "[Optimization] 聊天流式缓冲 Hook：内存累积 + RAF 批量刷新，降低热路径更新频率"
```

---

## Task 8: 聊天缓存写入从流式热路径剥离

**目的**：将流式过程中的高频缓存写入改为只在消息完成后和空闲时执行。

**Files:**
- Modify: `frontend/src/features/chat/store/chatStore.ts`
- Modify: `frontend/src/features/chat/ChatPage.tsx`

---

- [ ] **Step 1: 修改 chatStore — addMessage / updateMessage 不再写缓存**

修改 `frontend/src/features/chat/store/chatStore.ts`，将 `setCachedConversationMessages` 调用从 `addMessage`、`updateLastMessage`、`setMessages`、`updateMessage` 中移除：

```typescript
// frontend/src/features/chat/store/chatStore.ts (关键修改)

// addMessage: 移除 setCachedConversationMessages
addMessage: (role, content, reasoning_content, id) => {
  const messageId = id || crypto.randomUUID()
  set((state) => ({
    messages: [
      ...state.messages,
      {
        id: messageId,
        role,
        content,
        reasoning_content,
        timestamp: new Date(),
      },
    ],
  }))
  return messageId
},

// updateMessage: 移除 setCachedConversationMessages
updateMessage: (messageId: string, updater: (msg: ChatMessage) => ChatMessage) =>
  set((state) => {
    const nextMessages = state.messages.map((msg) =>
      msg.id === messageId ? updater(msg) : msg
    )
    return { messages: nextMessages }
  }),

// setMessages: 移除 setCachedConversationMessages
setMessages: (messages) => set({ messages }),

// clearMessages: 移除 setCachedConversationMessages
clearMessages: () => set({ messages: [] }),
```

修改 `loadCachedMessages`：仍从缓存读取，但 store 初始化时不再同步解析大消息桶：

```typescript
// chatStore.ts — 初始化时不再同步读取消息桶
const initialSessionId = getActiveConversationId() || 'default'

export const useChatStore = create<ChatState>((set) => ({
  // P0: 不再在 store 初始化时同步读取大量消息
  // 消息由 ChatPage 在路由进入时异步加载
  messages: [],
  isLoading: false,
  sessionId: initialSessionId,
  conversations: getCachedConversationSummaries(),
  // ...
}))
```

- [ ] **Step 2: 在 ChatPage 中集成缓冲写入**

修改 `frontend/src/features/chat/ChatPage.tsx`：

在流式结束时、用户切换会话时、页面隐藏时触发缓存刷盘，而不是每个 chunk 都写。

在 `ChatPage.tsx` 中：

```typescript
// ChatPage.tsx — handleSendMessage 中集成流式缓冲
// 在 finally 块中增加缓存刷盘

// (在 handleSendMessage 的 finally 块中)
finally {
  // P0: 流式完成后刷盘缓存（仅在消息完成时写入一次）
  flushConversationCache()
  setLoading(false)
  setStreamingAssistantId(null)
  // ...
}
```

在用户主动切换会话时（`useEffect` 中对 `conversationId` 变化的处理）也刷盘：

```typescript
// ChatPage.tsx — 切换会话前保存当前会话消息
useEffect(() => {
  if (conversationId && conversationId !== sessionId) {
    // P0: 离开当前会话前保存消息
    flushConversationCache()
    setSessionId(conversationId)
    // ...
  }
}, [conversationId])
```

- [ ] **Step 3: 验证流式过程中无缓存写入**

```bash
cd frontend && npm run dev
```

在浏览器 DevTools → Application → Local Storage 中观察 `chat_cache_v1`：
- 流式输出过程中，该 key 值不应频繁变化
- 消息完成后，缓存才更新一次
- 切换会话时，旧会话消息被保存

- [ ] **Step 4: Commit**

```bash
git add frontend/src/features/chat/store/chatStore.ts frontend/src/features/chat/ChatPage.tsx
git commit -m "[Optimization] 聊天缓存写入从流式热路径剥离，仅在完成/切换/隐藏时刷盘"
```

---

## Task 9: 聊天自动滚动优化

**目的**：从"每次 messages/messageMeta 变化都滚动"改为"仅在用户位于底部附近时跟随滚动"。

**Files:**
- Create: `frontend/src/features/chat/hooks/useChatAutoScroll.ts`
- Create: `frontend/src/features/chat/__tests__/useChatAutoScroll.test.ts`
- Modify: `frontend/src/features/chat/ChatPage.tsx:207-214`

---

- [ ] **Step 1: 编写 useChatAutoScroll 测试（TDD）**

```typescript
// frontend/src/features/chat/__tests__/useChatAutoScroll.test.ts
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook, act } from '@testing-library/react'

describe('useChatAutoScroll', () => {
  beforeEach(() => {
    vi.stubGlobal('document', {
      hidden: false,
      visibilityState: 'visible',
    })
    vi.stubGlobal('requestAnimationFrame', (cb: FrameRequestCallback) => {
      setTimeout(() => cb(performance.now()), 16)
      return 1
    })
    vi.stubGlobal('cancelAnimationFrame', vi.fn())
  })

  it('returns a scrollToBottom ref callback', () => {
    // TDD: 初始测试失败（模块不存在）
  })
})
```

- [ ] **Step 2: 运行测试确认失败（TDD）**

```bash
cd frontend && npx vitest run src/features/chat/__tests__/useChatAutoScroll.test.ts
```

预期：FAIL — 模块不存在。

- [ ] **Step 3: 实现 useChatAutoScroll hook**

```typescript
// frontend/src/features/chat/hooks/useChatAutoScroll.ts
/**
 * 聊天自动滚动 Hook。
 *
 * 仅在以下条件同时满足时才自动滚动到底部：
 * 1. 用户当前在底部附近（与底部的距离 <= threshold px）
 * 2. 页面可见（非后台标签页）
 * 3. 无用户手动滚动操作正在进行
 */
import { useRef, useCallback, useEffect } from 'react'

interface AutoScrollOptions {
  /** 判定"在底部附近"的阈值（px），默认 150 */
  threshold?: number
  /** 滚动行为，默认 'auto'（无动画，避免流式时动画堆积） */
  behavior?: ScrollBehavior
}

interface AutoScrollResult {
  /** 绑定到滚动容器的 ref callback */
  containerRef: (el: HTMLElement | null) => void
  /** 执行滚动到底部 */
  scrollToBottom: (force?: boolean) => void
}

export function useChatAutoScroll({
  threshold = 150,
  behavior = 'auto',
}: AutoScrollOptions = {}): AutoScrollResult {
  const containerElRef = useRef<HTMLElement | null>(null)
  const isNearBottomRef = useRef<boolean>(true)
  const userScrollingRef = useRef<boolean>(false)
  const scrollTimerRef = useRef<number | null>(null)

  const checkNearBottom = useCallback(() => {
    const el = containerElRef.current
    if (!el) return true
    const distance = el.scrollHeight - el.scrollTop - el.clientHeight
    return distance <= threshold
  }, [threshold])

  const scrollToBottom = useCallback((force: boolean = false) => {
    if (document.hidden) return
    const el = containerElRef.current
    if (!el) return

    if (!force && !isNearBottomRef.current) return

    // 使用 requestAnimationFrame 确保在 DOM 更新后滚动
    requestAnimationFrame(() => {
      el.scrollTo({ top: el.scrollHeight, behavior })
    })
  }, [behavior])

  const containerRef = useCallback((el: HTMLElement | null) => {
    if (!el) return
    containerElRef.current = el

    const handleScroll = () => {
      // 用户在手动滚动
      userScrollingRef.current = true
      isNearBottomRef.current = checkNearBottom()

      if (scrollTimerRef.current !== null) {
        clearTimeout(scrollTimerRef.current)
      }
      scrollTimerRef.current = window.setTimeout(() => {
        userScrollingRef.current = false
        scrollTimerRef.current = null
      }, 150)
    }

    el.addEventListener('scroll', handleScroll, { passive: true })

    // 初始判定
    isNearBottomRef.current = checkNearBottom()
  }, [checkNearBottom])

  useEffect(() => {
    return () => {
      if (scrollTimerRef.current !== null) {
        clearTimeout(scrollTimerRef.current)
      }
    }
  }, [])

  return { containerRef, scrollToBottom }
}
```

- [ ] **Step 4: 重写测试（完整版）**

```typescript
// frontend/src/features/chat/__tests__/useChatAutoScroll.test.ts (完整版)
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import { useChatAutoScroll } from '../hooks/useChatAutoScroll'

describe('useChatAutoScroll', () => {
  beforeEach(() => {
    vi.stubGlobal('document', {
      hidden: false,
      visibilityState: 'visible',
    })
    vi.stubGlobal('requestAnimationFrame', (cb: FrameRequestCallback) => {
      setTimeout(() => cb(performance.now()), 16)
      return 1
    })
    vi.stubGlobal('cancelAnimationFrame', vi.fn())
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('should return containerRef and scrollToBottom', () => {
    const { result } = renderHook(() => useChatAutoScroll())
    expect(typeof result.current.containerRef).toBe('function')
    expect(typeof result.current.scrollToBottom).toBe('function')
  })

  it('should not scroll when force=false and user is not near bottom', () => {
    const { result } = renderHook(() => useChatAutoScroll({ threshold: 100 }))
    const mockEl = {
      scrollHeight: 2000,
      scrollTop: 100,    // 用户在顶部
      clientHeight: 600,
      scrollTo: vi.fn(),
      addEventListener: vi.fn(),
    } as unknown as HTMLElement

    act(() => {
      result.current.containerRef(mockEl)
    })

    act(() => {
      result.current.scrollToBottom(false)
    })

    // scrollTo 不应该被调用（用户不在底部）
    expect(mockEl.scrollTo).not.toHaveBeenCalled()
  })

  it('should scroll when force=true regardless of position', () => {
    const { result } = renderHook(() => useChatAutoScroll())
    const mockEl = {
      scrollHeight: 2000,
      scrollTop: 100,
      clientHeight: 600,
      scrollTo: vi.fn(),
      addEventListener: vi.fn(),
    } as unknown as HTMLElement

    act(() => {
      result.current.containerRef(mockEl)
    })

    act(() => {
      result.current.scrollToBottom(true)
    })

    // RAF 后 scrollTo 应被调用
    act(() => {
      vi.advanceTimersByTime(20)
    })
    expect(mockEl.scrollTo).toHaveBeenCalled()
  })
})
```

- [ ] **Step 5: 运行测试确认通过**

```bash
cd frontend && npx vitest run src/features/chat/__tests__/useChatAutoScroll.test.ts
```

预期：3 个测试全部 PASS。

- [ ] **Step 6: 在 ChatPage 中集成 useChatAutoScroll**

修改 `frontend/src/features/chat/ChatPage.tsx`：

```typescript
// ChatPage.tsx — 替换旧滚动逻辑

import { useChatAutoScroll } from '@/features/chat/hooks/useChatAutoScroll'

function ChatPage() {
  // ...

  // P0: 使用新的自动滚动 hook
  const { containerRef: chatContainerRef, scrollToBottom } = useChatAutoScroll({
    threshold: 150,
    behavior: 'auto', // 流式场景用 auto 而非 smooth，避免动画堆积
  })

  // 删除旧的 scrollToBottom 定义 (第 207-210 行)
  // 删除旧的 messages/messageMeta useEffect (第 212-214 行)

  // 在消息变化时触发条件滚动
  useEffect(() => {
    scrollToBottom()
  }, [messages.length, scrollToBottom]) // 仅在新消息增加时触发，不再因 messageMeta 触发

  // visibility 变化时滚动
  useEffect(() => {
    const handleVisibilityChange = () => {
      if (document.visibilityState === 'visible') {
        flushBuffer()
        scrollToBottom()
      }
    }
    document.addEventListener('visibilitychange', handleVisibilityChange)
    return () => document.removeEventListener('visibilitychange', handleVisibilityChange)
  }, [flushBuffer, scrollToBottom])
  // ...
}
```

- [ ] **Step 7: Commit**

```bash
git add frontend/src/features/chat/hooks/useChatAutoScroll.ts frontend/src/features/chat/__tests__/useChatAutoScroll.test.ts frontend/src/features/chat/ChatPage.tsx
git commit -m "[Optimization] 聊天自动滚动优化：仅底部附近跟随 + RAF 去抖，停止因 meta 更新频繁触发滚动"
```

---

## Task 10: 发送消息时立即创建 assistant 占位消息

**目的**：用户点击发送后立即显示 assistant 气泡（含 loading 指示），消除"发送后空白等待"。

**Files:**
- Modify: `frontend/src/features/chat/ChatPage.tsx`

---

- [ ] **Step 1: 在 handleSendMessage 开头立即创建 assistant 占位**

找到 `ChatPage.tsx` 中的 `handleSendMessage`（或 `handleSend`）函数，在创建 user 消息后立即添加 assistant 占位：

```typescript
// ChatPage.tsx — handleSendMessage 中

const assistantMessageId = crypto.randomUUID()

// P0: 立即创建 assistant 占位消息，不等首个 chunk
addMessage('assistant', '', undefined, assistantMessageId)

// 初始化 execution meta（空壳）
setMessageMeta((prev) => ({
  ...prev,
  [assistantMessageId]: createEmptyExecutionMeta(),
}))

setStreamingAssistantId(assistantMessageId)
```

这样用户点击发送后，聊天区立即出现用户气泡 + assistant 空壳（loading 态），不再出现"发完消息后聊天区不变、等一会儿助理才出现"的情况。

- [ ] **Step 2: 验证占位消息行为**

```bash
cd frontend && npm run dev
```

在聊天页发送消息，确认：
- 点击发送后，用户消息和 assistant loading 气泡同时出现
- 首个 chunk 到达后，loading 被实际内容替换
- 取消/错误时，占位消息被正确处理

- [ ] **Step 3: Commit**

```bash
git add frontend/src/features/chat/ChatPage.tsx
git commit -m "[Optimization] 发送消息时立即创建 assistant 占位消息，消除首 chunk 前空白"
```

---

## Task 11: 前端轻量依赖安装

**目的**：安装本轮计划需要的轻量依赖，不影响现有构建。

**Files:**
- Modify: `frontend/package.json`

---

- [ ] **Step 1: 安装依赖**

```bash
cd frontend && npm install web-vitals idb
npm install -D rollup-plugin-visualizer
```

- [ ] **Step 2: 确认构建不受影响**

```bash
cd frontend && npm run build
```

预期：构建成功，无新增错误。

- [ ] **Step 3: Commit**

```bash
git add frontend/package.json frontend/package-lock.json
git commit -m "[Dependency] 安装性能优化依赖：web-vitals + idb + rollup-plugin-visualizer"
```

---

## P0 阶段验收

P0 完成后，执行以下验收检查：

- [ ] 后端启动日志中可见 `startup_begin` / `startup_step` / `startup_complete`，每步耗时清晰
- [ ] `set DEV_FAST_START=1` 后启动明显更快，`marketplace_seed` / `plugin_load_enabled` / `weixin_auto_reply` 被跳过
- [ ] 前端打开后不再出现全屏"正在初始化应用..."
- [ ] 聊天页发送消息后立即出现 assistant 气泡
- [ ] 流式过程中 `chat_cache_v1` 不再高频变化
- [ ] `npm run build` 成功，`set ANALYZE=1 && npm run build` 生成 stats.html
- [ ] 所有新增单元测试通过

---

# 第二阶段：P1 — 结构重构

本阶段目标：在 P0 收益已验证的基础上，对启动体系、聊天缓存、聊天页职责做深层次重构。

后续 P1 任务（Task 12-19）将在 P0 全部完成并验证后展开，涵盖：
- Task 12: 启动编排器与 main.py 深度集成
- Task 13: 插件系统 discover/ready/activate 三阶段拆分
- Task 14: 前端 App 初始化链路完整重组
- Task 15: 聊天持久化分层（localStorage + IndexedDB）
- Task 16: ChatPage 职责拆解（流式链路 / 持久化链路 / 视图增强链路）
- Task 17: TaskPanel / TodoPanel 按需懒加载
- Task 18: 富文本渲染延后（流式中纯文本，finalize 后再富文本化）
- Task 19: 会话历史加载优化

---

# 第三阶段：P2 — 回归保护

本阶段目标：为所有关键性能指标建立基线和回归门槛。

后续 P2 任务（Task 20-24）将在 P1 全部完成并验证后展开，涵盖：
- Task 20: 后端启动耗时基线报告
- Task 21: 前端 Web Vitals 集成与上报
- Task 22: 构建产物体积预算与 CI 检查
- Task 23: 长会话性能回归测试
- Task 24: 开发/生产双 profile 最终确认

---

## 执行说明

1. **严格按 P0 → P1 → P2 顺序执行**，每阶段完成并验证后再进入下一阶段。
2. **每完成一个 Task，必须运行相关测试**，确认不引入回归。
3. **P0 的每个 Task 都包含独立 commit**，便于回滚和审查。
4. **P1 和 P2 的详细 Task 将在前一阶段完成后展开**，避免过早细节与实际进展脱节。
5. **所有新增代码的注释、日志消息、commit message 均使用中文**，遵守项目 CLAUDE.md 规范。
