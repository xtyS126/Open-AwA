"""
代理记忆三级范围模块。

支持 USER / PROJECT / LOCAL 三级记忆范围，分别对应：
- USER: 用户级长期记忆，跨项目共享，存储于长期记忆表
- PROJECT: 项目级记忆，存储于 .openawa/agent_memories/{agent_id}.json
- LOCAL: 会话级内存，仅当前代理会话可见，不持久化

设计要点：
1. 使用 pathlib.Path 处理路径，PROJECT 目录不存在时自动创建
2. LOCAL 范围使用模块级 dict 缓存，不持久化
3. USER 范围复用现有 memory 模块的 MemoryManager 接口
4. 异常使用具体类型，禁止静默吞异常
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from loguru import logger

from .definitions import AgentMemoryScope


# PROJECT 范围记忆存储根目录（可被测试覆盖）
_PROJECT_MEMORY_BASE_DIR: Path = Path.home() / ".openawa" / "agent_memories"

# LOCAL 范围记忆缓存：agent_id -> {key -> AgentMemoryEntry}
_LOCAL_MEMORY_CACHE: Dict[str, Dict[str, "AgentMemoryEntry"]] = {}


@dataclass
class AgentMemoryEntry:
    """代理记忆条目，描述一条带范围标签的记忆。

    属性:
        agent_id: 所属代理 ID
        scope: 记忆范围（USER / PROJECT / LOCAL）
        key: 记忆键名，用于去重与检索
        value: 记忆内容
        timestamp: ISO 8601 格式的时间戳
        metadata: 可选的附加元数据
    """

    agent_id: str
    scope: AgentMemoryScope
    key: str
    value: str
    timestamp: str  # ISO 8601
    metadata: Optional[dict] = None


# ──────────────────────────────────────────────
#  路径辅助函数
# ──────────────────────────────────────────────

def _get_project_memory_dir(base_dir: Optional[Path] = None) -> Path:
    """获取 PROJECT 范围记忆存储目录，不存在则创建。

    参数:
        base_dir: 自定义根目录；为 None 时使用模块级默认目录

    返回:
        记忆存储目录 Path 对象
    """
    root = Path(base_dir) if base_dir else _PROJECT_MEMORY_BASE_DIR
    root.mkdir(parents=True, exist_ok=True)
    return root


def _get_project_memory_path(agent_id: str, base_dir: Optional[Path] = None) -> Path:
    """获取指定代理的 PROJECT 范围记忆文件路径。

    参数:
        agent_id: 代理 ID
        base_dir: 自定义根目录；为 None 时使用模块级默认目录

    返回:
        记忆文件 Path 对象
    """
    return _get_project_memory_dir(base_dir) / f"{agent_id}.json"


# ──────────────────────────────────────────────
#  三级范围加载实现
# ──────────────────────────────────────────────

def _load_user_scope_memories(agent_id: str) -> List[AgentMemoryEntry]:
    """从长期记忆表加载 USER 范围记忆。

    复用 MemoryManager 的内部同步方法，避免 async/sync 转换开销。
    加载失败时异常自然传播（记忆是子代理上下文的必需输入）。

    参数:
        agent_id: 代理 ID（用于日志关联）

    返回:
        记忆条目列表
    """
    # 延迟导入避免循环依赖：memory.manager -> core.conversation_sessions -> core.task_runtime
    from db.models import SessionLocal
    from memory.manager import MemoryManager

    manager = MemoryManager(SessionLocal)
    # 调用内部同步方法获取高重要性长期记忆
    memories = manager._get_and_evaluate_long_term_memories_sync(
        min_importance=0.5,
        limit=20,
    )
    entries: List[AgentMemoryEntry] = []
    for mem in memories:
        entries.append(
            AgentMemoryEntry(
                agent_id=agent_id,
                scope=AgentMemoryScope.USER,
                key=str(mem.id),
                value=mem.content or "",
                timestamp=(
                    mem.created_at.isoformat()
                    if mem.created_at
                    else datetime.now(timezone.utc).isoformat()
                ),
                metadata={
                    "importance": float(mem.importance or 0.0),
                    "confidence": float(mem.confidence or 0.0),
                    "memory_layer": getattr(mem, "memory_layer", "semantic"),
                },
            )
        )
    return entries


def _load_project_scope_memories(
    agent_id: str, base_dir: Optional[Path] = None
) -> List[AgentMemoryEntry]:
    """从 .openawa/agent_memories/{agent_id}.json 加载 PROJECT 范围记忆。

    文件不存在或解析失败时返回空列表。

    参数:
        agent_id: 代理 ID
        base_dir: 自定义根目录；为 None 时使用模块级默认目录

    返回:
        记忆条目列表
    """
    memory_path = _get_project_memory_path(agent_id, base_dir)
    if not memory_path.exists():
        return []
    try:
        raw = memory_path.read_text(encoding="utf-8")
        data = json.loads(raw)
        if not isinstance(data, dict):
            return []
        entries_data = data.get("entries", [])
        if not isinstance(entries_data, list):
            return []
        entries: List[AgentMemoryEntry] = []
        for item in entries_data:
            if not isinstance(item, dict):
                continue
            scope_str = str(item.get("scope", "project")).lower()
            try:
                scope = AgentMemoryScope(scope_str)
            except ValueError:
                scope = AgentMemoryScope.PROJECT
            entries.append(
                AgentMemoryEntry(
                    agent_id=str(item.get("agent_id", agent_id)),
                    scope=scope,
                    key=str(item.get("key", "")),
                    value=str(item.get("value", "")),
                    timestamp=str(item.get("timestamp", "")),
                    metadata=(
                        item.get("metadata")
                        if isinstance(item.get("metadata"), dict)
                        else None
                    ),
                )
            )
        return entries
    except (OSError, json.JSONDecodeError) as exc:
        # 项目记忆文件损坏或不可读必须传播，禁止静默返回空列表
        logger.bind(module="agent_memory", agent_id=agent_id).warning(
            f"加载 PROJECT 范围记忆失败: {exc}"
        )
        raise


def _load_local_scope_memories(agent_id: str) -> List[AgentMemoryEntry]:
    """从模块级缓存加载 LOCAL 范围记忆。

    参数:
        agent_id: 代理 ID

    返回:
        记忆条目列表
    """
    cache = _LOCAL_MEMORY_CACHE.get(agent_id, {})
    return list(cache.values())


def load_agent_memory_prompt(agent_id: str, scope: AgentMemoryScope) -> str:
    """根据 scope 动态加载记忆并返回格式化的 prompt 字符串。

    根据 scope 从不同存储加载记忆：
    - USER: 从 memory/ 长期记忆表加载
    - PROJECT: 从 .openawa/agent_memories/{agent_id}.json 加载
    - LOCAL: 从会话级内存加载

    参数:
        agent_id: 代理 ID
        scope: 记忆范围（USER / PROJECT / LOCAL）

    返回:
        格式化的记忆 prompt 字符串；无记忆时返回空字符串
    """
    if scope == AgentMemoryScope.USER:
        entries = _load_user_scope_memories(agent_id)
    elif scope == AgentMemoryScope.PROJECT:
        entries = _load_project_scope_memories(agent_id)
    elif scope == AgentMemoryScope.LOCAL:
        entries = _load_local_scope_memories(agent_id)
    else:
        logger.bind(module="agent_memory", agent_id=agent_id).warning(
            f"未知记忆范围: {scope}"
        )
        return ""

    if not entries:
        return ""

    # 格式化为 prompt 字符串
    lines: List[str] = [f"## 代理记忆（范围: {scope.value}）"]
    for entry in entries:
        lines.append(f"- [{entry.key}] {entry.value}")
    return "\n".join(lines)


# ──────────────────────────────────────────────
#  三级范围保存实现
# ──────────────────────────────────────────────

def _save_user_scope_memory(entry: AgentMemoryEntry) -> None:
    """将 USER 范围记忆保存到长期记忆表。

    复用 MemoryManager 的内部同步方法，避免 async/sync 转换问题。
    记忆条目以 source_type="agent" 写入，便于后续检索区分。

    参数:
        entry: 记忆条目

    异常:
        保存失败时向上抛出原始异常，由调用方决定降级策略
    """
    # 延迟导入避免循环依赖：memory.manager -> core.conversation_sessions -> core.task_runtime
    from db.models import SessionLocal
    from memory.manager import MemoryManager

    manager = MemoryManager(SessionLocal)
    manager._add_long_term_memory_sync(
        content=entry.value,
        importance=0.5,
        embedding=None,
        memory_metadata={
            "agent_id": entry.agent_id,
            "key": entry.key,
            "source_type": "agent",
            **(entry.metadata or {}),
        },
        source_type="agent",
    )


def _save_project_scope_memory(
    entry: AgentMemoryEntry, base_dir: Optional[Path] = None
) -> None:
    """将 PROJECT 范围记忆保存到 .openawa/agent_memories/{agent_id}.json。

    采用读-改-写模式追加条目，保留已有记忆。

    参数:
        entry: 记忆条目
        base_dir: 自定义根目录；为 None 时使用模块级默认目录

    异常:
        文件写入失败时向上抛出 OSError
    """
    memory_path = _get_project_memory_path(entry.agent_id, base_dir)
    # 读取现有数据
    existing: List[Dict[str, Any]] = []
    if memory_path.exists():
        try:
            raw = memory_path.read_text(encoding="utf-8")
            data = json.loads(raw)
            if isinstance(data, dict):
                existing_entries = data.get("entries", [])
                if isinstance(existing_entries, list):
                    existing = [
                        e for e in existing_entries if isinstance(e, dict)
                    ]
        except (OSError, json.JSONDecodeError) as exc:
            logger.bind(module="agent_memory", agent_id=entry.agent_id).warning(
                f"读取 PROJECT 记忆文件失败，将覆盖: {exc}"
            )
    # 追加新条目
    existing.append(
        {
            "agent_id": entry.agent_id,
            "scope": entry.scope.value,
            "key": entry.key,
            "value": entry.value,
            "timestamp": entry.timestamp,
            "metadata": entry.metadata,
        }
    )
    # 写入文件
    payload = {
        "agent_id": entry.agent_id,
        "entries": existing,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    memory_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _save_local_scope_memory(entry: AgentMemoryEntry) -> None:
    """将 LOCAL 范围记忆保存到模块级缓存。

    参数:
        entry: 记忆条目
    """
    cache = _LOCAL_MEMORY_CACHE.setdefault(entry.agent_id, {})
    cache[entry.key] = entry


def save_agent_memory(entry: AgentMemoryEntry) -> None:
    """根据 scope 将记忆条目保存到对应存储。

    参数:
        entry: 记忆条目

    异常:
        USER 范围保存失败时向上抛出原始异常；
        PROJECT 范围文件写入失败时向上抛出 OSError；
        LOCAL 范围不会失败（内存操作）。
    """
    if entry.scope == AgentMemoryScope.USER:
        _save_user_scope_memory(entry)
    elif entry.scope == AgentMemoryScope.PROJECT:
        _save_project_scope_memory(entry)
    elif entry.scope == AgentMemoryScope.LOCAL:
        _save_local_scope_memory(entry)
    else:
        logger.bind(module="agent_memory", agent_id=entry.agent_id).warning(
            f"未知记忆范围，无法保存: {entry.scope}"
        )


# ──────────────────────────────────────────────
#  AgentMemorySnapshot 快照管理
# ──────────────────────────────────────────────

class AgentMemorySnapshot:
    """代理记忆快照，管理单个代理的内存中记忆条目。

    快照本身不持久化，需调用 sync() 方法将条目同步到对应存储。
    用于在代理执行期间累积记忆，执行结束后统一持久化。

    属性:
        agent_id: 所属代理 ID
    """

    def __init__(self, agent_id: str) -> None:
        """初始化快照。

        参数:
            agent_id: 所属代理 ID
        """
        self.agent_id: str = agent_id
        self._entries: Dict[str, AgentMemoryEntry] = {}
        self._last_sync: Optional[str] = None

    def add_entry(self, entry: AgentMemoryEntry) -> None:
        """添加记忆条目到快照。

        以 key 作为去重键，相同 key 会覆盖旧条目。
        agent_id 不匹配时记录警告但仍写入，便于跨代理记忆合并场景。

        参数:
            entry: 记忆条目
        """
        if entry.agent_id != self.agent_id:
            logger.bind(
                module="agent_memory", agent_id=self.agent_id
            ).warning(
                f"条目 agent_id 不匹配: {entry.agent_id}"
            )
        self._entries[entry.key] = entry

    def get_entries(
        self, scope: Optional[AgentMemoryScope] = None
    ) -> List[AgentMemoryEntry]:
        """获取快照中的记忆条目，可按范围过滤。

        参数:
            scope: 记忆范围过滤；为 None 时返回全部条目

        返回:
            记忆条目列表
        """
        if scope is None:
            return list(self._entries.values())
        return [e for e in self._entries.values() if e.scope == scope]

    def to_prompt(self) -> str:
        """将快照中的记忆转换为 prompt 字符串。

        返回:
            格式化的 prompt 字符串；无条目时返回空字符串
        """
        if not self._entries:
            return ""
        lines: List[str] = ["## 代理记忆快照"]
        for entry in self._entries.values():
            lines.append(
                f"- [{entry.scope.value}] {entry.key}: {entry.value}"
            )
        return "\n".join(lines)

    async def sync(self) -> None:
        """异步将快照中的记忆同步到持久化存储。

        遍历所有条目调用 save_agent_memory，单条失败记录错误但不中断后续同步。
        同步完成后更新 _last_sync 时间戳。
        """
        for entry in self._entries.values():
            try:
                save_agent_memory(entry)
            except Exception as exc:
                logger.bind(
                    module="agent_memory", agent_id=self.agent_id
                ).error(f"同步记忆条目失败: {exc}")
        self._last_sync = datetime.now(timezone.utc).isoformat()


def check_agent_memory_snapshot(agent_id: str) -> AgentMemorySnapshot:
    """检查并返回指定代理的记忆快照。

    创建一个新的空快照实例，调用方可通过 add_entry 填充条目。

    参数:
        agent_id: 代理 ID

    返回:
        AgentMemorySnapshot 实例
    """
    return AgentMemorySnapshot(agent_id)
