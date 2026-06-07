"""
文件操作自动检查点模块。

在自主模式下，文件写入/删除前自动保存快照，
支持事后回滚恢复。
"""

from __future__ import annotations

import asyncio
import datetime
import json
import shutil
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from loguru import logger

from core.autonomous.config import AutonomousConfig


class FileCheckpoint:
    """单个文件检查点。"""

    def __init__(self, checkpoint_id: str, original_path: Path, backup_path: Path,
                 operation: str, created_at: str):
        self.checkpoint_id = checkpoint_id
        self.original_path = original_path
        self.backup_path = backup_path
        self.operation = operation  # 'write' | 'delete'
        self.created_at = created_at


class CheckpointManager:
    """检查点管理器。

    文件操作前创建快照，支持按 ID 恢复或批量回滚。
    """

    def __init__(self, config: AutonomousConfig):
        self._enabled = config.checkpoint_enabled
        self._workspace_root = Path(config.workspace_root) if config.workspace_root else None
        if self._workspace_root and self._enabled:
            self._checkpoints_dir = self._workspace_root / ".openawa" / "checkpoints"
            self._checkpoints_dir.mkdir(parents=True, exist_ok=True)
            self._index_path = self._checkpoints_dir / "index.json"
            self._checkpoints: Dict[str, FileCheckpoint] = self._load_index()
        else:
            self._checkpoints_dir = None
            self._checkpoints: Dict[str, FileCheckpoint] = {}
        logger.info(
            f"检查点管理器已初始化: enabled={self._enabled}, "
            f"dir={self._checkpoints_dir}"
        )

    def _load_index(self) -> Dict[str, FileCheckpoint]:
        """从磁盘加载检查点索引。"""
        if not self._index_path or not self._index_path.exists():
            return {}
        try:
            data = json.loads(self._index_path.read_text(encoding="utf-8"))
            result = {}
            for item in data:
                result[item["checkpoint_id"]] = FileCheckpoint(
                    checkpoint_id=item["checkpoint_id"],
                    original_path=Path(item["original_path"]),
                    backup_path=Path(item["backup_path"]),
                    operation=item["operation"],
                    created_at=item["created_at"],
                )
            return result
        except (json.JSONDecodeError, KeyError, OSError) as e:
            logger.warning(f"加载检查点索引失败: {e}")
            return {}

    def _save_index(self) -> None:
        """将检查点索引持久化到磁盘。"""
        if not self._index_path:
            return
        data = [
            {
                "checkpoint_id": cp.checkpoint_id,
                "original_path": str(cp.original_path),
                "backup_path": str(cp.backup_path),
                "operation": cp.operation,
                "created_at": cp.created_at,
            }
            for cp in self._checkpoints.values()
        ]
        self._index_path.parent.mkdir(parents=True, exist_ok=True)
        self._index_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    async def create(self, file_path: str, operation: str = "write") -> Optional[str]:
        """创建文件检查点。

        在文件被修改/删除前调用，保存当前快照。

        Args:
            file_path: 要创建检查点的文件路径
            operation: 操作类型（'write' 或 'delete'）

        Returns:
            检查点 ID，若文件不存在或不可读则返回 None
        """
        if not self._enabled or not self._checkpoints_dir:
            return None

        try:
            original = Path(file_path).resolve()
            if not original.exists() or not original.is_file():
                return None

            cp_id = f"ckpt_{uuid.uuid4().hex[:12]}"
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            backup_name = f"{cp_id}_{timestamp}_{original.name}"
            backup_path = self._checkpoints_dir / backup_name

            # 异步复制文件
            await asyncio.to_thread(shutil.copy2, str(original), str(backup_path))

            checkpoint = FileCheckpoint(
                checkpoint_id=cp_id,
                original_path=original,
                backup_path=backup_path,
                operation=operation,
                created_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
            )
            self._checkpoints[cp_id] = checkpoint
            await asyncio.to_thread(self._save_index)

            logger.debug(f"检查点已创建: {cp_id} for {original}")
            return cp_id
        except (OSError, shutil.Error) as e:
            logger.warning(f"创建检查点失败 ({file_path}): {e}")
            return None

    async def restore(self, checkpoint_id: str) -> bool:
        """从检查点恢复文件。"""
        checkpoint = self._checkpoints.get(checkpoint_id)
        if not checkpoint:
            logger.warning(f"检查点不存在: {checkpoint_id}")
            return False

        try:
            if not checkpoint.backup_path.exists():
                logger.warning(f"检查点备份文件不存在: {checkpoint.backup_path}")
                return False

            # 确保目标目录存在
            checkpoint.original_path.parent.mkdir(parents=True, exist_ok=True)
            await asyncio.to_thread(
                shutil.copy2, str(checkpoint.backup_path), str(checkpoint.original_path)
            )
            logger.info(f"文件已从检查点恢复: {checkpoint.original_path}")
            return True
        except (OSError, shutil.Error) as e:
            logger.error(f"从检查点恢复失败 ({checkpoint_id}): {e}")
            return False

    async def list_checkpoints(self, limit: int = 50) -> List[Dict[str, Any]]:
        """列出最近的检查点摘要。"""
        sorted_cps = sorted(
            self._checkpoints.values(),
            key=lambda c: c.created_at,
            reverse=True,
        )
        return [
            {
                "checkpoint_id": cp.checkpoint_id,
                "original_path": str(cp.original_path),
                "operation": cp.operation,
                "created_at": cp.created_at,
            }
            for cp in sorted_cps[:limit]
        ]

    async def cleanup(self, max_checkpoints: int = 1000) -> int:
        """清理超出上限的旧检查点。"""
        if len(self._checkpoints) <= max_checkpoints:
            return 0

        sorted_cps = sorted(
            self._checkpoints.values(),
            key=lambda c: c.created_at,
        )
        to_remove = sorted_cps[:-max_checkpoints]
        removed = 0

        for cp in to_remove:
            try:
                if cp.backup_path.exists():
                    await asyncio.to_thread(cp.backup_path.unlink)
                del self._checkpoints[cp.checkpoint_id]
                removed += 1
            except OSError as e:
                logger.warning(f"清理检查点失败 ({cp.checkpoint_id}): {e}")

        if removed > 0:
            await asyncio.to_thread(self._save_index)
            logger.info(f"已清理 {removed} 个旧检查点")

        return removed


# 全局默认实例
_default_checkpoint_mgr: Optional[CheckpointManager] = None


def get_checkpoint_manager() -> Optional[CheckpointManager]:
    """获取当前 CheckpointManager 实例。"""
    return _default_checkpoint_mgr


def set_checkpoint_manager(mgr: CheckpointManager) -> None:
    """设置全局 CheckpointManager 实例。"""
    global _default_checkpoint_mgr
    _default_checkpoint_mgr = mgr
