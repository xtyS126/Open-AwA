"""
插件安装服务：负责插件下载、安装、卸载。
"""

import io
import os
import re
import shutil
import tempfile
import zipfile
from pathlib import Path
from typing import Optional

from loguru import logger


class PluginInstallService:
    """
    插件安装服务。

    职责：
    - 从本地 ZIP 文件安装插件
    - 从远程 URL 下载并安装插件
    - 安全解压（防路径穿越）
    - 卸载插件
    """

    def __init__(self, plugins_dir: str = None):
        """
        初始化插件安装服务。

        Args:
            plugins_dir: 插件目录路径，默认为当前文件所在目录。
        """
        self._plugins_dir = plugins_dir or os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..")
        )

    def set_plugins_dir(self, directory: str):
        """设置插件目录。"""
        self._plugins_dir = directory

    def install_from_zip(self, zip_path: str, plugin_name: str = None) -> str:
        """
        从 ZIP 文件安装插件。

        Args:
            zip_path: ZIP 文件路径。
            plugin_name: 插件名称，默认使用 ZIP 文件名。

        Returns:
            解压后的插件目录路径。

        Raises:
            FileNotFoundError: ZIP 文件不存在。
            ValueError: 文件不是 ZIP 格式或包含不安全路径。
        """
        if not os.path.exists(zip_path):
            raise FileNotFoundError(f"ZIP 文件不存在: {zip_path}")

        target_dir = os.path.join(
            self._plugins_dir,
            plugin_name or os.path.splitext(os.path.basename(zip_path))[0],
        )

        if os.path.exists(target_dir):
            shutil.rmtree(target_dir)

        self._safe_extract_zip_file(zip_path, target_dir)
        logger.info(f"插件已从 ZIP 安装: {zip_path} -> {target_dir}")
        return target_dir

    def install_from_bytes(self, zip_content: bytes, plugin_name: str) -> str:
        """
        从字节数据安装插件。

        Args:
            zip_content: ZIP 文件的字节数据。
            plugin_name: 插件名称。

        Returns:
            解压后的插件目录路径。

        Raises:
            ValueError: ZIP 内容无效或包含不安全路径。
        """
        target_dir = os.path.join(self._plugins_dir, plugin_name)

        if os.path.exists(target_dir):
            shutil.rmtree(target_dir)

        self._safe_extract_zip_bytes(zip_content, target_dir)
        logger.info(f"插件已从字节数据安装: {plugin_name} -> {target_dir}")
        return target_dir

    def uninstall(self, plugin_name: str):
        """
        卸载插件（删除插件目录）。

        Args:
            plugin_name: 插件名称。
        """
        plugin_dir = os.path.join(self._plugins_dir, plugin_name)
        if os.path.exists(plugin_dir):
            shutil.rmtree(plugin_dir)
            logger.info(f"插件已卸载: {plugin_name}")
        else:
            logger.warning(f"卸载时插件目录不存在: {plugin_dir}")

    def is_installed(self, plugin_name: str) -> bool:
        """
        检查插件是否已安装。

        Args:
            plugin_name: 插件名称。

        Returns:
            已安装返回 True。
        """
        plugin_dir = os.path.join(self._plugins_dir, plugin_name)
        return os.path.isdir(plugin_dir)

    def _safe_extract_zip_file(self, zip_path: str, target_dir: str):
        """从文件路径安全解压 ZIP。"""
        with zipfile.ZipFile(zip_path, "r") as archive:
            self._safe_extract_zip_archive(archive, target_dir)

    def _safe_extract_zip_bytes(self, zip_content: bytes, target_dir: str):
        """从字节数据安全解压 ZIP。"""
        with zipfile.ZipFile(io.BytesIO(zip_content), "r") as archive:
            self._safe_extract_zip_archive(archive, target_dir)

    def _safe_extract_zip_archive(self, archive: zipfile.ZipFile, target_dir: str):
        """
        安全解压 ZIP 压缩包，防止路径遍历攻击。

        Args:
            archive: ZIP 文件对象。
            target_dir: 目标解压目录。

        Raises:
            ValueError: 若检测到非法路径结构。
        """
        target_dir_abs = os.path.abspath(target_dir)
        os.makedirs(target_dir_abs, exist_ok=True)

        for member_info in archive.infolist():
            normalized_member = member_info.filename.replace("\\", "/")
            if normalized_member.startswith("/") or normalized_member.startswith("//"):
                raise ValueError(f"不安全的 ZIP 成员路径: {member_info.filename}")

            parts = [
                part for part in normalized_member.split("/")
                if part not in ("", ".")
            ]
            if not parts:
                continue
            if any(part == ".." for part in parts):
                raise ValueError(f"不安全的 ZIP 成员路径: {member_info.filename}")

            destination = os.path.abspath(os.path.join(target_dir_abs, *parts))
            if os.path.commonpath([target_dir_abs, destination]) != target_dir_abs:
                raise ValueError(f"不安全的 ZIP 成员路径: {member_info.filename}")

            # 阻止解压符号链接
            unix_mode = (member_info.external_attr >> 16) & 0o170000
            if unix_mode == 0o120000:
                raise ValueError("ZIP 压缩包包含不支持的符号链接条目")

            if member_info.is_dir():
                os.makedirs(destination, exist_ok=True)
                continue

            parent_dir = os.path.dirname(destination)
            if parent_dir:
                os.makedirs(parent_dir, exist_ok=True)

            with archive.open(member_info, "r") as source, open(destination, "wb") as target_file:
                shutil.copyfileobj(source, target_file)

    def _create_extract_dir(self, source_name: str) -> str:
        """
        创建用于解压插件的临时目录。

        Args:
            source_name: 源文件名称。

        Returns:
            临时目录路径。
        """
        base_name = os.path.splitext(os.path.basename(source_name))[0] or "plugin"
        safe_base = re.sub(r"[^a-zA-Z0-9_.-]", "_", base_name)
        extract_dir = tempfile.mkdtemp(prefix=f"{safe_base}_", dir=self._plugins_dir)
        return extract_dir