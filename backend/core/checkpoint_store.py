"""
操作检查点存储模块，为文件写入等副作用操作提供撤销能力。
检查点以内存缓存方式保存操作前的文件备份，支持带 TTL 的自动过期。
"""

import time
import uuid
from pathlib import Path
from typing import Any, Dict, Optional
from loguru import logger

# 默认检查点有效期（秒）
DEFAULT_CHECKPOINT_TTL = 300  # 5 分钟

# 操作 ID 到检查点元数据的映射
_checkpoints: Dict[str, Dict[str, Any]] = {}


class CheckpointStore:
    """操作检查点存储器，在副作用操作前保存恢复所需的快照。"""

    def __init__(self, ttl_seconds: int = DEFAULT_CHECKPOINT_TTL):
        self._ttl = ttl_seconds

    def save(
        self,
        session_id: str,
        tool_name: str,
        file_path: str,
        operation_type: str,
    ) -> str:
        """
        保存操作的检查点。

        对于已存在的文件，保存文件原内容作为备份。
        对于新创建的文件，标记为"可删除"。

        Args:
            session_id: 会话 ID
            tool_name: 工具名称（如 write_file、delete_file、terminal_executor）
            file_path: 操作的文件路径
            operation_type: "overwrite"=覆写已有文件，"create"=创建新文件，"delete"=删除文件

        Returns:
            操作 ID（用于后续撤销）
        """
        operation_id = uuid.uuid4().hex[:12]
        checkpoint = {
            "operation_id": operation_id,
            "session_id": session_id,
            "tool_name": tool_name,
            "file_path": file_path,
            "operation_type": operation_type,
            "created_at": time.time(),
            "backup_content": None,
            "can_undo": False,
        }

        if operation_type == "overwrite":
            try:
                backup_content = Path(file_path).read_text(encoding="utf-8")
                checkpoint["backup_content"] = backup_content
                checkpoint["can_undo"] = True
                logger.info(f"Checkpoint saved for overwrite: {file_path}, op_id={operation_id}")
            except Exception as exc:
                logger.warning(f"Failed to save checkpoint backup for {file_path}: {exc}")

        elif operation_type in ("create", "delete"):
            checkpoint["can_undo"] = True
            logger.info(f"Checkpoint saved for {operation_type}: {file_path}, op_id={operation_id}")

        _checkpoints[operation_id] = checkpoint
        self._cleanup_expired()
        return operation_id

    def undo(self, operation_id: str) -> Dict[str, Any]:
        """
        撤销指定操作。

        Args:
            operation_id: 操作 ID

        Returns:
            {"ok": True/False, "operation_id": ..., "action": ..., "file_path": ...}
        """
        checkpoint = _checkpoints.pop(operation_id, None)
        if checkpoint is None:
            return {"ok": False, "error": "检查点不存在或已过期", "operation_id": operation_id}

        if not checkpoint.get("can_undo"):
            return {"ok": False, "error": "此操作无法撤销", "operation_id": operation_id}

        file_path = Path(checkpoint["file_path"])
        op_type = checkpoint["operation_type"]

        try:
            if op_type == "overwrite":
                backup = checkpoint.get("backup_content")
                if backup is None:
                    return {"ok": False, "error": "备份内容丢失", "operation_id": operation_id}
                file_path.write_text(backup, encoding="utf-8")
                logger.info(f"Undo overwrite restored: {file_path}")

            elif op_type == "create":
                if file_path.is_file():
                    file_path.unlink()
                    logger.info(f"Undo create deleted: {file_path}")

            elif op_type == "delete":
                # 删除操作无法自动恢复（原内容未知），返回提示
                return {
                    "ok": False,
                    "error": "文件删除操作无法自动撤销，原内容已丢失",
                    "operation_id": operation_id,
                    "action": "manual_restore_required",
                }

            return {
                "ok": True,
                "operation_id": operation_id,
                "file_path": str(file_path),
                "action": f"已撤销 {op_type} 操作",
            }

        except Exception as exc:
            logger.error(f"Undo failed for {operation_id}: {exc}")
            return {"ok": False, "error": str(exc), "operation_id": operation_id}

    def get_remaining_ttl(self, operation_id: str) -> int:
        """获取检查点剩余有效时间（秒），过期返回 0。"""
        checkpoint = _checkpoints.get(operation_id)
        if checkpoint is None:
            return 0
        elapsed = time.time() - checkpoint["created_at"]
        remaining = max(0, self._ttl - int(elapsed))
        return remaining

    def _cleanup_expired(self):
        """清理过期的检查点。"""
        now = time.time()
        expired = [
            op_id
            for op_id, cp in _checkpoints.items()
            if now - cp["created_at"] > self._ttl
        ]
        for op_id in expired:
            _checkpoints.pop(op_id, None)
        if expired:
            logger.debug(f"Cleaned up {len(expired)} expired checkpoints")


# 模块级单例，供工具调用处直接使用
checkpoint_store = CheckpointStore()
