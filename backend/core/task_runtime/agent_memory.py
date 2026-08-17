"""
代理记忆三级范围模块。

支持 USER / PROJECT / LOCAL 三级记忆范围，分别对应：
- USER: 用户级长期记忆，跨项目共享，存储于长期记忆表
- PROJECT: 项目级记忆，存储于 .openawa/agent_memories/{agent_type}/project.json
- LOCAL: 会话级内存，仅当前代理会话可见，不持久化

设计要点：
1. 存储键使用 agent_type（+scope）而非随机 agent_id：同一类型的代理实例
   跨会话共享记忆池，保证跨会话记忆复用；PROJECT 目录不存在时自动创建
2. LOCAL 范围使用模块级 dict 缓存，不持久化
3. USER 范围复用现有 memory 模块的 MemoryManager 公开异步接口
   （get_long_term_memories / add_long_term_memory），按 agent_type 维度过滤
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

# PROJECT 范围记忆文件名（按 scope 区分，后续扩展其他范围时追加）
_PROJECT_MEMORY_FILE_NAME: str = "project.json"

# LOCAL 范围记忆缓存：agent_id -> {key -> AgentMemoryEntry}
_LOCAL_MEMORY_CACHE: Dict[str, Dict[str, "AgentMemoryEntry"]] = {}


@dataclass
class AgentMemoryEntry:
    """代理记忆条目，描述一条带范围标签的记忆。

    属性:
        agent_id: 所属代理 ID
        agent_type: 所属代理类型；作为 PROJECT/USER 范围的存储键与过滤维度
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
    agent_type: Optional[str] = None


# ──────────────────────────────────────────────
#  路径辅助函数
# ──────────────────────────────────────────────

def _get_project_memory_dir(base_dir: Optional[Path] = None) -> Path:
    """获取 PROJECT 范围记忆存储根目录，不存在则创建。

    参数:
        base_dir: 自定义根目录；为 None 时使用模块级默认目录

    返回:
        记忆存储根目录 Path 对象
    """
    root = Path(base_dir) if base_dir else _PROJECT_MEMORY_BASE_DIR
    root.mkdir(parents=True, exist_ok=True)
    return root


def _get_project_memory_path(agent_type: str, base_dir: Optional[Path] = None) -> Path:
    """获取指定代理类型的 PROJECT 范围记忆文件路径。

    PROJECT 记忆按 agent_type 维度存储（{base_dir}/{agent_type}/project.json），
    同一类型的不同实例（不同 agent_id）共享同一记忆池，保证跨会话记忆复用。

    参数:
        agent_type: 代理类型
        base_dir: 自定义根目录；为 None 时使用模块级默认目录

    返回:
        记忆文件 Path 对象
    """
    return _get_project_memory_dir(base_dir) / agent_type / _PROJECT_MEMORY_FILE_NAME


# ──────────────────────────────────────────────
#  三级范围加载实现
# ──────────────────────────────────────────────

async def _load_user_scope_memories(agent_type: str) -> List[AgentMemoryEntry]:
    """从长期记忆表加载 USER 范围记忆。

    使用 MemoryManager 的公开异步接口 get_long_term_memories，按 agent_type
    维度过滤：仅返回 memory_metadata 中 source_type == "agent" 且
    agent_type 与目标类型一致的记忆，保证同类型代理跨会话共享、不同类型隔离。
    加载失败时异常自然传播（记忆是子代理上下文的必需输入）。

    参数:
        agent_type: 代理类型（用于过滤与日志关联）

    返回:
        记忆条目列表
    """
    # 延迟导入避免循环依赖：memory.manager -> core.conversation_sessions -> core.task_runtime
    from db.models import SessionLocal
    from memory.manager import MemoryManager

    manager = MemoryManager(SessionLocal)
    # 调用公开异步接口获取高重要性长期记忆
    memories = await manager.get_long_term_memories(
        min_importance=0.5,
        limit=20,
    )
    entries: List[AgentMemoryEntry] = []
    for mem in memories:
        mem_metadata = dict(getattr(mem, "memory_metadata", None) or {})
        # 按 agent_type 维度过滤：仅保留本类型代理写入的 USER 记忆
        if mem_metadata.get("source_type") != "agent":
            continue
        if mem_metadata.get("agent_type") != agent_type:
            continue
        entries.append(
            AgentMemoryEntry(
                agent_id=str(getattr(mem, "user_id", "") or agent_type),
                agent_type=agent_type,
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
    agent_type: str, base_dir: Optional[Path] = None
) -> List[AgentMemoryEntry]:
    """从 .openawa/agent_memories/{agent_type}/project.json 加载 PROJECT 范围记忆。

    文件不存在时返回空列表；若代理类型目录下存在旧格式孤儿文件（按 agent_id
    命名、不具备 agent_type 语义），记录日志并跳过，避免旧数据干扰。
    payload 中 agent_type 与请求不一致时视为孤儿文件，跳过并记录日志。

    参数:
        agent_type: 代理类型
        base_dir: 自定义根目录；为 None 时使用模块级默认目录

    返回:
        记忆条目列表
    """
    memory_path = _get_project_memory_path(agent_type, base_dir)
    if not memory_path.exists():
        # 清理逻辑：扫描代理类型目录下的孤儿文件（非 project.json），跳过并记录日志
        agent_type_dir = memory_path.parent
        if agent_type_dir.exists() and agent_type_dir.is_dir():
            orphan_files = [
                f.name
                for f in agent_type_dir.iterdir()
                if f.is_file() and f.name != memory_path.name
            ]
            if orphan_files:
                logger.bind(module="agent_memory", agent_type=agent_type).warning(
                    f"跳过不含 agent_type 语义的孤儿记忆文件: {orphan_files}"
                )
        return []
    try:
        raw = memory_path.read_text(encoding="utf-8")
        data = json.loads(raw)
        if not isinstance(data, dict):
            return []
        # 孤儿文件语义校验：payload 中 agent_type 与请求类型不一致时跳过
        file_agent_type = str(data.get("agent_type") or "").strip()
        if file_agent_type and file_agent_type != agent_type:
            logger.bind(module="agent_memory", agent_type=agent_type).warning(
                f"跳过 agent_type 不匹配的记忆文件: {file_agent_type} != {agent_type}"
            )
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
                    agent_id=str(item.get("agent_id", agent_type)),
                    agent_type=str(item.get("agent_type", agent_type)),
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
        logger.bind(module="agent_memory", agent_type=agent_type).warning(
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


async def load_agent_memory_prompt(agent_type: str, scope: AgentMemoryScope) -> str:
    """根据 scope 动态加载记忆并返回格式化的 prompt 字符串。

    根据 scope 从不同存储加载记忆，存储键为 agent_type（+scope）：
    - USER: 从 memory/ 长期记忆表加载（按 agent_type 维度过滤）
    - PROJECT: 从 .openawa/agent_memories/{agent_type}/project.json 加载
    - LOCAL: 从会话级内存加载

    参数:
        agent_type: 代理类型
        scope: 记忆范围（USER / PROJECT / LOCAL）

    返回:
        格式化的记忆 prompt 字符串；无记忆时返回空字符串
    """
    if scope == AgentMemoryScope.USER:
        entries = await _load_user_scope_memories(agent_type)
    elif scope == AgentMemoryScope.PROJECT:
        entries = _load_project_scope_memories(agent_type)
    elif scope == AgentMemoryScope.LOCAL:
        entries = _load_local_scope_memories(agent_type)
    else:
        logger.bind(module="agent_memory", agent_type=agent_type).warning(
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

async def _save_user_scope_memory(entry: AgentMemoryEntry) -> None:
    """将 USER 范围记忆保存到长期记忆表。

    使用 MemoryManager 的公开异步接口 add_long_term_memory，以
    source_type="agent" + agent_type 维度写入，便于跨会话按类型检索过滤。

    参数:
        entry: 记忆条目

    异常:
        保存失败时向上抛出原始异常，由调用方决定降级策略
    """
    # 延迟导入避免循环依赖：memory.manager -> core.conversation_sessions -> core.task_runtime
    from db.models import SessionLocal
    from memory.manager import MemoryManager

    manager = MemoryManager(SessionLocal)
    await manager.add_long_term_memory(
        content=entry.value,
        importance=0.5,
        embedding=None,
        memory_metadata={
            "agent_id": entry.agent_id,
            "agent_type": entry.agent_type,
            "key": entry.key,
            "source_type": "agent",
            **(entry.metadata or {}),
        },
        source_type="agent",
    )


def _save_project_scope_memory(
    entry: AgentMemoryEntry, base_dir: Optional[Path] = None
) -> None:
    """将 PROJECT 范围记忆保存到 .openawa/agent_memories/{agent_type}/project.json。

    存储键取 entry.agent_type；未设置时回退到 agent_id，保持向后兼容。
    采用读-改-写模式追加条目，保留已有记忆。

    参数:
        entry: 记忆条目
        base_dir: 自定义根目录；为 None 时使用模块级默认目录

    异常:
        文件写入失败时向上抛出 OSError
    """
    storage_key = entry.agent_type or entry.agent_id
    memory_path = _get_project_memory_path(storage_key, base_dir)
    # 确保 agent_type 子目录存在（_get_project_memory_dir 仅创建根目录）
    memory_path.parent.mkdir(parents=True, exist_ok=True)
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
            logger.bind(module="agent_memory", agent_type=storage_key).warning(
                f"读取 PROJECT 记忆文件失败，将覆盖: {exc}"
            )
    # 追加新条目
    existing.append(
        {
            "agent_id": entry.agent_id,
            "agent_type": entry.agent_type or storage_key,
            "scope": entry.scope.value,
            "key": entry.key,
            "value": entry.value,
            "timestamp": entry.timestamp,
            "metadata": entry.metadata,
        }
    )
    # 写入文件
    payload = {
        "agent_type": entry.agent_type or storage_key,
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


async def save_agent_memory(entry: AgentMemoryEntry) -> None:
    """根据 scope 将记忆条目保存到对应存储。

    参数:
        entry: 记忆条目

    异常:
        USER 范围保存失败时向上抛出原始异常；
        PROJECT 范围文件写入失败时向上抛出 OSError；
        LOCAL 范围不会失败（内存操作）。
    """
    if entry.scope == AgentMemoryScope.USER:
        await _save_user_scope_memory(entry)
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
    快照携带 agent_type，作为 PROJECT/USER 范围记忆的存储键。

    属性:
        agent_id: 所属代理 ID
        agent_type: 所属代理类型；为 None 时回退到条目的 agent_id 作为存储键
    """

    def __init__(self, agent_id: str, agent_type: Optional[str] = None) -> None:
        """初始化快照。

        参数:
            agent_id: 所属代理 ID
            agent_type: 所属代理类型；为 None 时表示未指定
        """
        self.agent_id: str = agent_id
        self.agent_type: Optional[str] = agent_type
        self._entries: Dict[str, AgentMemoryEntry] = {}
        self._last_sync: Optional[str] = None

    def add_entry(self, entry: AgentMemoryEntry) -> None:
        """添加记忆条目到快照。

        以 key 作为去重键，相同 key 会覆盖旧条目。
        agent_id 不匹配时记录警告但仍写入，便于跨代理记忆合并场景。
        条目未携带 agent_type 时回填快照的 agent_type。

        参数:
            entry: 记忆条目
        """
        if entry.agent_id != self.agent_id:
            logger.bind(
                module="agent_memory", agent_id=self.agent_id
            ).warning(
                f"条目 agent_id 不匹配: {entry.agent_id}"
            )
        if entry.agent_type is None:
            entry.agent_type = self.agent_type
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
                await save_agent_memory(entry)
            except Exception as exc:
                logger.bind(
                    module="agent_memory", agent_id=self.agent_id
                ).error(f"同步记忆条目失败: {exc}")
        self._last_sync = datetime.now(timezone.utc).isoformat()


def check_agent_memory_snapshot(
    agent_id: str, agent_type: Optional[str] = None
) -> AgentMemorySnapshot:
    """检查并返回指定代理的记忆快照。

    创建一个新的空快照实例，调用方可通过 add_entry 填充条目。

    参数:
        agent_id: 代理 ID
        agent_type: 代理类型；为 None 时表示未指定

    返回:
        AgentMemorySnapshot 实例
    """
    return AgentMemorySnapshot(agent_id, agent_type=agent_type)
