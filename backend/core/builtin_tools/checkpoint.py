"""
检查点系统，在工具修改文件前自动保存快照，支持会话级恢复。
参考 OpenHanako 的 checkpoint-store.js 设计。

核心功能：
- 在文件被修改/删除前自动保存文件快照
- 支持按检查点 ID 恢复到快照时刻的文件内容
- 支持按会话过滤列出检查点列表
- 自动跳过二进制文件、空文件和超大文件
"""

from __future__ import annotations

import json
import os
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from loguru import logger

# 二进制文件扩展名集合 —— 这些文件类型不创建检查点
BINARY_EXTENSIONS: set[str] = {
    '.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp', '.ico', '.svg',
    '.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx',
    '.zip', '.tar', '.gz', '.bz2', '.7z', '.rar',
    '.exe', '.dll', '.so', '.dylib', '.wasm',
    '.mp3', '.mp4', '.wav', '.avi', '.mov', '.mkv', '.flac',
    '.ttf', '.otf', '.woff', '.woff2',
    '.db', '.sqlite', '.sqlite3',
}

# 检查点文件最大大小（KB），超过此大小的文件不创建检查点
MAX_CHECKPOINT_SIZE_KB: int = 1024  # 1MB

# 判空二进制文件的采样字节数
BIN_DETECT_SAMPLE_SIZE: int = 8192


class CheckpointStore:
    """
    检查点存储器，负责文件修改前的快照保存与恢复。

    每个检查点保存为一个 JSON 文件，包含：
    - 时间戳、会话路径、工具名、来源
    - 原始文件路径、文件内容、文件大小

    使用示例：
        store = CheckpointStore(checkpoints_dir="/data/checkpoints")
        # 保存快照
        result = store.save(session_path="/sessions/abc", tool="write_file",
                            file_path="/path/to/file.txt")
        # 恢复文件
        store.restore(result["id"])
        # 列出检查点
        store.list_checkpoints(session_path="/sessions/abc")
    """

    name: str = "checkpoint"
    version: str = "1.0.0"
    description: str = "检查点系统，在工具修改文件前自动保存快照，支持会话级恢复"

    def __init__(self, checkpoints_dir: str):
        """
        初始化检查点存储器。

        Args:
            checkpoints_dir: 检查点文件存储目录的绝对路径
        """
        self._dir = Path(checkpoints_dir)

    async def initialize(self) -> None:
        """异步初始化（当前无需额外操作，保留接口兼容性）。"""
        pass

    def get_tools(self) -> List[Dict[str, Any]]:
        """返回检查点系统提供的工具定义列表。"""
        return [
            {
                "name": "list_checkpoints",
                "description": "列出当前会话或全部检查点（不含文件内容，仅摘要信息）",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "session_path": {
                            "type": "string",
                            "description": "按会话路径过滤检查点（可选）",
                        },
                    },
                },
            },
            {
                "name": "restore_checkpoint",
                "description": "根据检查点 ID 恢复文件到快照时的状态",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "checkpoint_id": {
                            "type": "string",
                            "description": "要恢复的检查点 ID",
                        },
                    },
                    "required": ["checkpoint_id"],
                },
            },
        ]

    async def execute(self, action: str, **params: Any) -> Dict[str, Any]:
        """
        统一执行入口，与 BuiltInToolManager 的调度协议兼容。

        Args:
            action: 操作名，支持 "list_checkpoints" 和 "restore_checkpoint"
            **params: 操作参数

        Returns:
            操作结果字典，包含 success 字段
        """
        if action == "list_checkpoints":
            session_path = params.get("session_path")
            checkpoints = self.list_checkpoints(session_path=session_path)
            return {
                "success": True,
                "checkpoints": checkpoints,
                "count": len(checkpoints),
            }
        elif action == "restore_checkpoint":
            checkpoint_id = params.get("checkpoint_id", "")
            if not checkpoint_id:
                return {"success": False, "error": "缺少必填参数: checkpoint_id"}
            result = self.restore(checkpoint_id)
            if result is None:
                return {
                    "success": False,
                    "error": f"检查点不存在或恢复失败: {checkpoint_id}",
                }
            return {"success": True, **result}
        else:
            return {"success": False, "error": f"未知检查点操作: {action}"}

    def save(
        self,
        *,
        session_path: Optional[str] = None,
        tool: str = "unknown",
        file_path: str = "",
        source: str = "llm",
        reason: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        保存文件修改前的检查点快照。

        自动跳过二进制文件、空文件和超大文件。
        使用原子写入（先写 .tmp 再 rename）避免写入中断导致的损坏。

        Args:
            session_path: 当前会话路径，用于后续按会话过滤
            tool: 触发检查点的工具名（如 write_file、delete_file）
            file_path: 要保存快照的文件绝对路径
            source: 触发来源，默认 "llm"
            reason: 保存检查点的原因描述

        Returns:
            检查点元数据字典（含 id、content 等），
            如果跳过保存则返回 None
        """
        # 1. 检查文件扩展名是否为二进制类型
        ext = Path(file_path).suffix.lower()
        if ext in BINARY_EXTENSIONS:
            logger.debug(f"跳过二进制文件检查点: {file_path}")
            return None

        # 2. 检查文件是否存在及大小
        try:
            stat = os.stat(file_path)
        except OSError:
            return None

        # 跳过空文件
        if stat.st_size == 0:
            logger.debug(f"跳过空文件检查点: {file_path}")
            return None

        # 跳过超大文件
        if stat.st_size > MAX_CHECKPOINT_SIZE_KB * 1024:
            logger.debug(f"跳过超大文件检查点 ({stat.st_size} bytes): {file_path}")
            return None

        # 3. 读取文件内容并检测是否为二进制（采样前 N 字节判空）
        try:
            with open(file_path, 'rb') as f:
                buf = f.read(BIN_DETECT_SAMPLE_SIZE)
        except OSError:
            return None

        # 如果采样字节中包含 NULL 字符，判定为二进制文件
        if b'\x00' in buf:
            logger.debug(f"跳过二进制内容文件检查点: {file_path}")
            return None

        # 解码为 UTF-8 文本
        content = buf.decode('utf-8')

        # 4. 确保检查点目录存在
        self._dir.mkdir(parents=True, exist_ok=True)

        # 5. 生成检查点 ID：毫秒时间戳 + 随机后缀，确保排序和唯一性
        ts = int(datetime.now(timezone.utc).timestamp() * 1000)
        suffix = secrets.token_hex(2)  # 4 字符随机后缀
        checkpoint_id = f"{ts}_{suffix}"

        # 6. 构建检查点数据
        data = {
            "ts": ts,
            "sessionPath": session_path,
            "tool": tool,
            "source": source,
            "reason": reason or f"tool-{tool}",
            "path": file_path,
            "content": content,
            "size": stat.st_size,
        }

        # 7. 原子写入：先写入临时文件，再 rename 为目标文件
        filename = f"{checkpoint_id}.json"
        file_full = self._dir / filename
        tmp = self._dir / f"{filename}.tmp"

        try:
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False)
            os.rename(str(tmp), str(file_full))
            logger.info(f"检查点已保存: {checkpoint_id} 路径: {file_path} 工具: {tool}")
            return {"id": checkpoint_id, **data}
        except OSError as e:
            logger.error(f"检查点保存失败: {checkpoint_id} {e}")
            # 清理可能残留的临时文件
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass
            return None

    def restore(self, checkpoint_id: str) -> Optional[Dict[str, Any]]:
        """
        恢复检查点：将文件恢复为快照保存时的内容。

        如果目标文件所在的父目录不存在，会自动创建。

        Args:
            checkpoint_id: 要恢复的检查点 ID（不含 .json 后缀）

        Returns:
            恢复结果字典，包含 success、path、id 等字段；
            如果检查点不存在则返回 None
        """
        filename = f"{checkpoint_id}.json"
        file_full = self._dir / filename

        # 1. 读取检查点数据
        try:
            with open(file_full, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except FileNotFoundError:
            logger.error(f"检查点文件不存在: {checkpoint_id}")
            return None
        except (OSError, json.JSONDecodeError) as e:
            logger.error(f"检查点读取失败: {checkpoint_id} {e}")
            return None

        # 2. 获取目标文件路径
        target_path = data.get("path")
        if not target_path:
            return {"success": False, "error": "检查点数据缺少文件路径字段"}

        # 3. 恢复文件内容
        try:
            target = Path(target_path)
            # 确保父目录存在
            target.parent.mkdir(parents=True, exist_ok=True)
            # 使用 newline='' 保留原始换行符，避免 Windows 上 \n → \r\n 转换
            with open(target, 'w', encoding='utf-8', newline='') as f:
                f.write(data.get("content", ""))
            logger.info(f"检查点已恢复: {checkpoint_id} → {target_path}")
            return {"success": True, "path": target_path, "id": checkpoint_id}
        except OSError as e:
            logger.error(f"检查点恢复失败: {checkpoint_id} {e}")
            return {"success": False, "error": str(e)}

    def list_checkpoints(
        self,
        session_path: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        列出检查点，可按会话过滤。

        返回摘要列表，不包含 content 字段以减少数据传输量。

        Args:
            session_path: 可选，按会话路径过滤检查点

        Returns:
            检查点摘要列表，按修改时间倒序排列
        """
        if not self._dir.exists():
            return []

        checkpoints: List[Dict[str, Any]] = []

        # 按修改时间倒序遍历所有 JSON 文件
        for file_path in sorted(
            self._dir.glob("*.json"),
            key=lambda f: f.stat().st_mtime,
            reverse=True,
        ):
            # 跳过 .tmp 临时文件（虽然 glob 不会匹配到，但防御性保留）
            if file_path.name.endswith(".tmp"):
                continue

            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
            except (OSError, json.JSONDecodeError):
                # 损坏的检查点文件跳过
                continue

            # 按会话过滤
            if session_path and data.get("sessionPath") != session_path:
                continue

            # 返回摘要信息，不含 content 字段
            checkpoints.append({
                "id": file_path.stem,  # 去掉 .json 后缀的文件名
                "ts": data.get("ts"),
                "tool": data.get("tool"),
                "source": data.get("source"),
                "path": data.get("path"),
                "size": data.get("size"),
                "reason": data.get("reason"),
                "sessionPath": data.get("sessionPath"),
            })

        return checkpoints

    def remove(self, checkpoint_id: str) -> bool:
        """
        删除指定检查点文件。

        Args:
            checkpoint_id: 要删除的检查点 ID

        Returns:
            True 如果删除成功，False 如果文件不存在或删除失败
        """
        file_path = self._dir / f"{checkpoint_id}.json"
        try:
            file_path.unlink()
            logger.debug(f"检查点已删除: {checkpoint_id}")
            return True
        except OSError:
            return False

    def cleanup(self, retention_days: int = 7) -> int:
        """
        清理超过保留天数的旧检查点。

        Args:
            retention_days: 保留天数，默认 7 天

        Returns:
            清理的检查点数量
        """
        if not self._dir.exists():
            return 0

        cutoff_ts = int(
            (datetime.now(timezone.utc).timestamp() - retention_days * 86400)
            * 1000
        )
        cleaned = 0

        for file_path in self._dir.glob("*.json"):
            # 跳过临时文件
            if file_path.name.endswith(".tmp"):
                continue

            # 从文件名中提取时间戳（格式: {ts}_{suffix}.json）
            try:
                ts_part = file_path.stem.split("_")[0]
                ts = int(ts_part)
            except (ValueError, IndexError):
                continue

            if ts < cutoff_ts:
                try:
                    file_path.unlink()
                    cleaned += 1
                except OSError:
                    pass

        if cleaned > 0:
            logger.info(f"检查点清理完成，移除 {cleaned} 个过期检查点（保留 {retention_days} 天）")
        return cleaned
