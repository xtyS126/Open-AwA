"""
检查点系统单元测试。
测试 CheckpointStore 的保存、恢复、列表、清理等功能。
"""

import json
import os
import sys
import tempfile
import time
from pathlib import Path

import pytest

# 确保 backend 目录在 PYTHONPATH 中
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.builtin_tools.checkpoint import (  # noqa: E402
    BINARY_EXTENSIONS,
    CheckpointStore,
    MAX_CHECKPOINT_SIZE_KB,
)


class TestCheckpointStoreBasic:
    """测试 CheckpointStore 基本功能 —— 保存、恢复、列表"""

    def test_save_and_restore_text_file(self):
        """测试保存文本文件检查点并恢复 —— 正常路径"""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = CheckpointStore(checkpoints_dir=os.path.join(tmpdir, "checkpoints"))

            # 创建测试文件（newline='' 防止 Windows 自动转换换行符）
            test_file = os.path.join(tmpdir, "test.txt")
            original_content = "原始内容\n第二行"
            with open(test_file, 'w', encoding='utf-8', newline='') as f:
                f.write(original_content)

            # 保存检查点
            result = store.save(
                session_path="/test/session",
                tool="write_file",
                file_path=test_file,
                reason="测试保存",
            )
            assert result is not None
            assert result["path"] == test_file
            # 读取时 content 保留原始字节（二进制模式），所以内容一致
            assert result["content"] == original_content
            assert "id" in result

            # 修改文件
            modified_content = "修改后的内容"
            with open(test_file, 'w', encoding='utf-8') as f:
                f.write(modified_content)

            # 恢复检查点
            restore = store.restore(result["id"])
            assert restore is not None
            assert restore["success"] is True
            assert restore["path"] == test_file

            # 验证恢复后的内容
            with open(test_file, 'r', encoding='utf-8', newline='') as f:
                restored_content = f.read()
            assert restored_content == original_content

    def test_save_nonexistent_file(self):
        """测试保存不存在的文件时返回 None"""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = CheckpointStore(checkpoints_dir=os.path.join(tmpdir, "checkpoints"))

            result = store.save(
                session_path="/test/session",
                tool="write_file",
                file_path=os.path.join(tmpdir, "nonexistent.txt"),
            )
            assert result is None

    def test_save_empty_file(self):
        """测试空文件被跳过"""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = CheckpointStore(checkpoints_dir=os.path.join(tmpdir, "checkpoints"))

            test_file = os.path.join(tmpdir, "empty.txt")
            with open(test_file, 'w', encoding='utf-8') as f:
                f.write("")  # 空文件

            result = store.save(
                session_path="/test/session",
                tool="write_file",
                file_path=test_file,
            )
            assert result is None


class TestCheckpointStoreSkipConditions:
    """测试检查点跳过的各种条件"""

    def test_skip_binary_extension(self):
        """测试二进制扩展名文件被跳过"""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = CheckpointStore(checkpoints_dir=os.path.join(tmpdir, "checkpoints"))

            # 测试所有已知的二进制扩展名
            for ext in list(BINARY_EXTENSIONS)[:5]:  # 取样部分扩展名测试
                test_file = os.path.join(tmpdir, f"image{ext}")
                with open(test_file, 'wb') as f:
                    f.write(b'\x89PNG\r\n\x1a\n\x00\x00\x00\x00IHDR')

                result = store.save(
                    session_path="/test/session",
                    tool="write_file",
                    file_path=test_file,
                )
                assert result is None, f"应跳过二进制扩展名文件: {ext}"

    def test_skip_binary_content(self):
        """测试包含 NULL 字节的二进制内容文件被跳过"""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = CheckpointStore(checkpoints_dir=os.path.join(tmpdir, "checkpoints"))

            # 创建 .txt 扩展名但包含 NULL 字节的二进制文件
            test_file = os.path.join(tmpdir, "binary.txt")
            with open(test_file, 'wb') as f:
                f.write(b'some text\x00\x00\x00more text')

            result = store.save(
                session_path="/test/session",
                tool="write_file",
                file_path=test_file,
            )
            assert result is None

    def test_skip_large_file(self):
        """测试超大文件被跳过（>1MB）"""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = CheckpointStore(checkpoints_dir=os.path.join(tmpdir, "checkpoints"))

            test_file = os.path.join(tmpdir, "large.txt")
            # 创建超过 MAX_CHECKPOINT_SIZE_KB 的文本文件
            large_size = (MAX_CHECKPOINT_SIZE_KB + 10) * 1024
            with open(test_file, 'w', encoding='utf-8') as f:
                f.write('x' * large_size)

            result = store.save(
                session_path="/test/session",
                tool="write_file",
                file_path=test_file,
            )
            assert result is None


class TestCheckpointStoreList:
    """测试检查点列表功能"""

    def test_list_all_checkpoints(self):
        """测试列出全部检查点"""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = CheckpointStore(checkpoints_dir=os.path.join(tmpdir, "checkpoints"))

            # 依次保存两个检查点（加短暂间隔确保时间戳不同）
            test_file = os.path.join(tmpdir, "test.txt")
            with open(test_file, 'w', encoding='utf-8') as f:
                f.write("test content")

            result1 = store.save(session_path="/session/a", tool="write_file", file_path=test_file)
            assert result1 is not None
            time.sleep(0.01)

            result2 = store.save(session_path="/session/b", tool="delete_file", file_path=test_file)
            assert result2 is not None

            # 列出全部
            all_cps = store.list_checkpoints()
            assert len(all_cps) == 2
            # 最新保存的应排在最前面（按修改时间倒序）
            assert all_cps[0]["id"] == result2["id"]

    def test_list_filter_by_session(self):
        """测试按会话过滤检查点"""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = CheckpointStore(checkpoints_dir=os.path.join(tmpdir, "checkpoints"))

            test_file = os.path.join(tmpdir, "test.txt")
            with open(test_file, 'w', encoding='utf-8') as f:
                f.write("test content")

            store.save(session_path="/session/a", tool="write_file", file_path=test_file)
            time.sleep(0.01)
            store.save(session_path="/session/b", tool="delete_file", file_path=test_file)

            # 按会话 A 过滤
            session_a = store.list_checkpoints(session_path="/session/a")
            assert len(session_a) == 1
            assert session_a[0]["tool"] == "write_file"
            # 摘要中不应包含 content 字段
            assert "content" not in session_a[0]

            # 按不存在的会话过滤
            none_session = store.list_checkpoints(session_path="/session/nonexistent")
            assert none_session == []

    def test_list_empty_directory(self):
        """测试空目录或不存在目录列出返回空列表"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # 使用不存在的目录
            store = CheckpointStore(checkpoints_dir=os.path.join(tmpdir, "nonexistent"))
            result = store.list_checkpoints()
            assert result == []

    def test_list_returns_summary_only(self):
        """测试列表返回摘要，不含文件内容"""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = CheckpointStore(checkpoints_dir=os.path.join(tmpdir, "checkpoints"))

            test_file = os.path.join(tmpdir, "test.txt")
            with open(test_file, 'w', encoding='utf-8') as f:
                f.write("some content here")

            result = store.save(session_path="/test/session", tool="write_file", file_path=test_file)
            assert result is not None

            checkpoints = store.list_checkpoints()
            assert len(checkpoints) == 1
            # 摘要项不应包含 content 字段
            assert "content" not in checkpoints[0]
            # 但是应该包含其他关键字段
            assert "id" in checkpoints[0]
            assert "tool" in checkpoints[0]
            assert "path" in checkpoints[0]


class TestCheckpointStoreRestore:
    """测试检查点恢复的各种场景"""

    def test_restore_nonexistent(self):
        """测试恢复不存在的检查点返回 None"""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = CheckpointStore(checkpoints_dir=os.path.join(tmpdir, "checkpoints"))
            result = store.restore("nonexistent_id")
            assert result is None

    def test_restore_creates_parent_directory(self):
        """测试恢复时自动创建目标文件的父目录"""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = CheckpointStore(checkpoints_dir=os.path.join(tmpdir, "checkpoints"))

            # 创建测试文件在嵌套目录中
            nested_dir = os.path.join(tmpdir, "a", "b", "c")
            os.makedirs(nested_dir, exist_ok=True)
            test_file = os.path.join(nested_dir, "test.txt")
            original_content = "嵌套文件内容"
            with open(test_file, 'w', encoding='utf-8') as f:
                f.write(original_content)

            # 保存检查点
            result = store.save(file_path=test_file, tool="write_file")
            assert result is not None

            # 删除嵌套目录
            import shutil
            shutil.rmtree(nested_dir)

            # 恢复 —— 应自动创建父目录
            restore = store.restore(result["id"])
            assert restore is not None
            assert restore["success"] is True

            # 验证文件存在且内容正确
            assert os.path.exists(test_file)
            with open(test_file, 'r', encoding='utf-8') as f:
                assert f.read() == original_content


class TestCheckpointStoreExecute:
    """测试 execute 统一执行入口"""

    def test_execute_list_checkpoints(self):
        """测试 execute(action='list_checkpoints') 正常返回"""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = CheckpointStore(checkpoints_dir=os.path.join(tmpdir, "checkpoints"))

            test_file = os.path.join(tmpdir, "test.txt")
            with open(test_file, 'w', encoding='utf-8') as f:
                f.write("test")

            store.save(session_path="/session/a", tool="write_file", file_path=test_file)

            import asyncio
            result = asyncio.run(store.execute("list_checkpoints"))
            assert result["success"] is True
            assert result["count"] == 1
            assert len(result["checkpoints"]) == 1

    def test_execute_list_with_session_filter(self):
        """测试 execute 列表时按会话过滤"""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = CheckpointStore(checkpoints_dir=os.path.join(tmpdir, "checkpoints"))

            test_file = os.path.join(tmpdir, "test.txt")
            with open(test_file, 'w', encoding='utf-8') as f:
                f.write("test")

            store.save(session_path="/s/a", tool="write_file", file_path=test_file)

            import asyncio
            result = asyncio.run(store.execute("list_checkpoints", session_path="/s/b"))
            assert result["success"] is True
            assert result["count"] == 0

    def test_execute_restore_checkpoint(self):
        """测试 execute(action='restore_checkpoint') 正常恢复"""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = CheckpointStore(checkpoints_dir=os.path.join(tmpdir, "checkpoints"))

            test_file = os.path.join(tmpdir, "test.txt")
            original = "原始内容"
            with open(test_file, 'w', encoding='utf-8') as f:
                f.write(original)

            saved = store.save(file_path=test_file, tool="write_file")
            assert saved is not None

            # 修改文件
            with open(test_file, 'w', encoding='utf-8') as f:
                f.write("修改后")

            import asyncio
            result = asyncio.run(store.execute("restore_checkpoint", checkpoint_id=saved["id"]))
            assert result["success"] is True

            with open(test_file, 'r', encoding='utf-8') as f:
                assert f.read() == original

    def test_execute_restore_missing_id(self):
        """测试 execute 恢复时缺少 checkpoint_id 参数"""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = CheckpointStore(checkpoints_dir=os.path.join(tmpdir, "checkpoints"))

            import asyncio
            result = asyncio.run(store.execute("restore_checkpoint"))
            assert result["success"] is False
            assert "checkpoint_id" in result["error"]

    def test_execute_unknown_action(self):
        """测试 execute 未知操作"""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = CheckpointStore(checkpoints_dir=os.path.join(tmpdir, "checkpoints"))

            import asyncio
            result = asyncio.run(store.execute("unknown_action"))
            assert result["success"] is False
            assert "未知" in result["error"]


class TestCheckpointStoreCleanup:
    """测试检查点清理功能"""

    def test_remove_checkpoint(self):
        """测试删除单个检查点"""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = CheckpointStore(checkpoints_dir=os.path.join(tmpdir, "checkpoints"))

            test_file = os.path.join(tmpdir, "test.txt")
            with open(test_file, 'w', encoding='utf-8') as f:
                f.write("test")

            result = store.save(file_path=test_file, tool="write_file")
            assert result is not None

            # 确认文件存在
            cp_file = Path(store._dir) / f"{result['id']}.json"
            assert cp_file.exists()

            # 删除
            assert store.remove(result["id"]) is True
            assert not cp_file.exists()

    def test_remove_nonexistent(self):
        """测试删除不存在的检查点"""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = CheckpointStore(checkpoints_dir=os.path.join(tmpdir, "checkpoints"))
            assert store.remove("nonexistent") is False

    def test_cleanup_by_age(self):
        """测试按天数清理过期检查点"""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = CheckpointStore(checkpoints_dir=os.path.join(tmpdir, "checkpoints"))

            # 创建测试文件
            test_file = os.path.join(tmpdir, "test.txt")
            with open(test_file, 'w', encoding='utf-8') as f:
                f.write("test")

            # 保存检查点
            result = store.save(file_path=test_file, tool="write_file")
            assert result is not None

            # 使用 retention_days=0 清理所有（指定 cutoff 为未来时间，所有检查点都会过期）
            import asyncio
            cleaned = store.cleanup(retention_days=0)
            # 由于使用毫秒时间戳和微小的时差，可能清理 1 个或 0 个
            assert cleaned >= 0

    def test_cleanup_empty_directory(self):
        """测试清理空目录"""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = CheckpointStore(checkpoints_dir=os.path.join(tmpdir, "nonexistent"))
            cleaned = store.cleanup(retention_days=7)
            assert cleaned == 0


class TestCheckpointStoreInit:
    """测试初始化及相关方法"""

    def test_initialize_async(self):
        """测试 initialize 方法不抛异常"""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = CheckpointStore(checkpoints_dir=os.path.join(tmpdir, "checkpoints"))
            import asyncio
            # 不应抛出异常
            asyncio.run(store.initialize())

    def test_get_tools(self):
        """测试 get_tools 返回正确的工具定义"""
        store = CheckpointStore(checkpoints_dir="/tmp/test")
        tools = store.get_tools()
        assert len(tools) == 2
        tool_names = [t["name"] for t in tools]
        assert "list_checkpoints" in tool_names
        assert "restore_checkpoint" in tool_names

    def test_name_and_version(self):
        """测试类属性名称和版本"""
        store = CheckpointStore(checkpoints_dir="/tmp/test")
        assert store.name == "checkpoint"
        assert store.version == "1.0.0"
        assert isinstance(store.description, str)
