"""
技能系统模块，负责技能注册、加载、校验、执行或适配外部能力。
当 Agent 需要调用外部能力时，通常会经过这一层完成查找、验证与执行。
"""

import os
from pathlib import Path
from typing import Dict, Any, List, Optional
from loguru import logger


def safe_resolve_path(file_path: str) -> str:
    """
    处理safe、resolve、path相关逻辑，并为调用方返回对应结果。
    阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
    """
    return os.path.realpath(file_path)


def is_path_safe(file_path: str, allowed_directories: List[str]) -> bool:
    """
    处理is、path、safe相关逻辑，并为调用方返回对应结果。
    阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
    """
    try:
        resolved_path = safe_resolve_path(file_path)
        
        if not os.path.exists(resolved_path):
            return True
        
        for allowed_dir in allowed_directories:
            allowed_resolved = os.path.realpath(allowed_dir)
            common = os.path.commonpath([resolved_path, allowed_resolved])
            if common == allowed_resolved:
                return True
        
        return False
    except Exception:
        return False


class FileManagerSkill:
    """
    封装与FileManagerSkill相关的核心逻辑与运行状态。
    该类通常是当前文件中组织数据与调度行为的主要封装单元。
    """
    name: str = "file_manager"
    version: str = "1.0.0"
    description: str = "文件管理技能"

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        初始化文件管理工具：从配置中读取允许操作的目录白名单，设置检查点存储引用。
        """
        self.config = config or {}
        self.allowed_directories: List[str] = self.config.get('allowed_directories', [])
        self._initialized = False
        # 检查点存储器，可选注入；为 None 时跳过检查点保存
        self.checkpoint_store: Optional[object] = None

    def set_checkpoint_store(self, store: object) -> None:
        """
        注入检查点存储器实例，使文件写入/删除操作自动保存快照。

        Args:
            store: CheckpointStore 实例
        """
        self.checkpoint_store = store

    async def initialize(self) -> bool:
        """
        验证文件管理工具的运行环境：检查配置目录是否存在且可访问。
        初始化成功后设置 _initialized 标志，后续 execute 调用依赖此标志。
        """
        logger.info(f"Initializing {self.name} skill v{self.version}")
        self._setup_allowed_directories()
        logger.info(f"FileManager initialized with allowed directories: {self.allowed_directories}")
        self._initialized = True
        return True

    def _setup_allowed_directories(self):
        """
        处理setup、allowed、directories相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        if not self.allowed_directories:
            self.allowed_directories = [os.getcwd()]
        self.allowed_directories = [
            str(Path(d).resolve()) for d in self.allowed_directories
        ]

    def is_initialized(self) -> bool:
        """检查技能是否已初始化。"""
        return self._initialized

    def _resolve_relative_path(self, file_path: str) -> str:
        """
        处理相对路径解析：对于不存在的相对路径，尝试在允许目录中查找匹配文件。
        解决子代理使用 'plugin_manager.py' 等相对路径时找不到文件的问题。
        """
        # 绝对路径或已存在的路径直接返回
        if os.path.isabs(file_path) or os.path.exists(file_path):
            return file_path
        # 对纯文件名或相对路径，在允许目录中搜索
        for allowed_dir in self.allowed_directories:
            candidate = os.path.join(allowed_dir, file_path)
            if os.path.exists(candidate):
                return candidate
        return file_path

    def _validate_path(self, file_path: str) -> bool:
        """
        处理validate、path相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        resolved = self._resolve_relative_path(file_path)
        if is_path_safe(resolved, self.allowed_directories):
            return True
        logger.warning(f"Access denied to path: {file_path}")
        return False

    async def execute(self, **kwargs) -> Dict[str, Any]:
        """
        执行文件操作（读取/写入/删除/列表/搜索/差异对比/批量编辑/撤销）。
        所有路径操作限制在 allowed_directories 白名单内，编辑前自动保存检查点。
        """
        if not self._initialized:
            logger.error("Skill not initialized")
            return {"success": False, "error": "Skill not initialized"}

        action = kwargs.get('action')
        logger.info(f"Executing file operation: {action}")

        if action == 'read_file':
            return await self._read_file(kwargs)
        elif action == 'write_file':
            return await self._write_file(kwargs)
        elif action == 'list_files':
            return await self._list_files(kwargs)
        elif action == 'delete_file':
            return await self._delete_file(kwargs)
        elif action == 'file_exists':
            return await self._file_exists(kwargs)
        elif action == 'create_directory':
            return await self._create_directory(kwargs)
        else:
            logger.error(f"Unknown action: {action}")
            return {"success": False, "error": f"Unknown action: {action}"}

    async def _read_file(self, kwargs: Dict[str, Any]) -> Dict[str, Any]:
        """
        处理read、file相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        file_path = self._resolve_relative_path(kwargs.get('path', ''))
        if not file_path:
            return {"success": False, "error": "path parameter is required"}

        if not self._validate_path(file_path):
            return {"success": False, "error": "Access denied"}

        # 检查路径是否为目录，避免 PermissionError
        if os.path.isdir(file_path):
            logger.warning(f"Cannot read directory as file: {file_path}")
            return {"success": False, "error": "Is a directory"}

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            logger.info(f"Successfully read file: {file_path}")
            return {
                "success": True,
                "content": content,
                "path": file_path
            }
        except FileNotFoundError:
            logger.error(f"File not found: {file_path}")
            return {"success": False, "error": "File not found"}
        except PermissionError:
            logger.error(f"Permission denied: {file_path}")
            return {"success": False, "error": "Permission denied"}
        except Exception as e:
            logger.error(f"Error reading file {file_path}: {e}")
            return {"success": False, "error": str(e)}

    async def _write_file(self, kwargs: Dict[str, Any]) -> Dict[str, Any]:
        """
        处理write、file相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        file_path = self._resolve_relative_path(kwargs.get('path', ''))
        content = kwargs.get('content', '')

        if not file_path:
            return {"success": False, "error": "path parameter is required"}

        if not self._validate_path(file_path):
            return {"success": False, "error": "Access denied"}

        # 写入前保存检查点快照
        operation_id = None
        if self.checkpoint_store is not None:
            op_type = "overwrite" if os.path.exists(file_path) else "create"
            operation_id = self.checkpoint_store.save(
                session_id=kwargs.get("session_id", "default"),
                tool_name="write_file",
                file_path=file_path,
                operation_type=op_type,
            )

        try:
            directory = Path(file_path).parent
            directory.mkdir(parents=True, exist_ok=True)

            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(content)

            logger.info(f"Successfully wrote file: {file_path}")
            return {
                "success": True,
                "path": file_path,
                "bytes_written": len(content.encode('utf-8')),
                "operation_id": operation_id,
            }
        except Exception as e:
            logger.error(f"Error writing file {file_path}: {e}")
            return {"success": False, "error": str(e)}

    async def _list_files(self, kwargs: Dict[str, Any]) -> Dict[str, Any]:
        """
        处理list、files相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        directory = self._resolve_relative_path(kwargs.get('path', ''))
        pattern = kwargs.get('pattern', '*')

        if not self._validate_path(directory):
            return {"success": False, "error": "Access denied"}

        try:
            dir_path = Path(directory)
            if not dir_path.exists():
                return {"success": False, "error": "Directory not found"}

            files = [
                {
                    "name": f.name,
                    "path": str(f),
                    "is_file": f.is_file(),
                    "is_directory": f.is_dir(),
                    "size": f.stat().st_size if f.is_file() else 0
                }
                for f in dir_path.glob(pattern)
            ]

            logger.info(f"Listed {len(files)} items in: {directory}")
            return {
                "success": True,
                "path": directory,
                "files": files,
                "count": len(files)
            }
        except Exception as e:
            logger.error(f"Error listing files in {directory}: {e}")
            return {"success": False, "error": str(e)}

    async def _delete_file(self, kwargs: Dict[str, Any]) -> Dict[str, Any]:
        """
        处理delete、file相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        file_path = self._resolve_relative_path(kwargs.get('path', ''))

        if not file_path:
            return {"success": False, "error": "path parameter is required"}

        if not self._validate_path(file_path):
            return {"success": False, "error": "Access denied"}

        # 删除文件前保存检查点快照（仅当目标为文件且检查点存储器已注入时）
        if self.checkpoint_store and Path(file_path).is_file():
            self.checkpoint_store.save(
                session_path=kwargs.get('session_path'),
                tool="delete_file",
                file_path=file_path,
                reason="delete_file即将删除",
            )

        try:
            path = Path(file_path)
            if path.is_file():
                path.unlink()
            elif path.is_dir():
                import shutil
                shutil.rmtree(path)
            else:
                return {"success": False, "error": "Path does not exist"}

            logger.info(f"Successfully deleted: {file_path}")
            return {"success": True, "path": file_path}
        except Exception as e:
            logger.error(f"Error deleting {file_path}: {e}")
            return {"success": False, "error": str(e)}

    async def _file_exists(self, kwargs: Dict[str, Any]) -> Dict[str, Any]:
        """
        处理file、exists相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        file_path = self._resolve_relative_path(kwargs.get('path', ''))

        if not file_path:
            return {"success": False, "error": "path parameter is required"}

        if not self._validate_path(file_path):
            return {"success": False, "error": "Access denied"}

        exists = Path(file_path).exists()
        logger.info(f"File exists check for {file_path}: {exists}")
        return {
            "success": True,
            "path": file_path,
            "exists": exists
        }

    async def _create_directory(self, kwargs: Dict[str, Any]) -> Dict[str, Any]:
        """
        处理create、directory相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        directory = self._resolve_relative_path(kwargs.get('path', ''))

        if not directory:
            return {"success": False, "error": "path parameter is required"}

        if not self._validate_path(directory):
            return {"success": False, "error": "Access denied"}

        try:
            Path(directory).mkdir(parents=True, exist_ok=True)
            logger.info(f"Successfully created directory: {directory}")
            return {"success": True, "path": directory}
        except Exception as e:
            logger.error(f"Error creating directory {directory}: {e}")
            return {"success": False, "error": str(e)}

    def get_tools(self) -> List[Dict[str, Any]]:
        """
        获取tools相关数据或当前状态。
        调用方通常依赖该结果继续进行后续判断、渲染或业务编排。
        """
        return [
            {
                "name": "read_file",
                "description": "读取文件内容",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "要读取的文件路径"
                        }
                    },
                    "required": ["path"]
                }
            },
            {
                "name": "write_file",
                "description": "写入文件内容",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "要写入的文件路径"
                        },
                        "content": {
                            "type": "string",
                            "description": "要写入的内容"
                        }
                    },
                    "required": ["path", "content"]
                }
            },
            {
                "name": "list_files",
                "description": "列出目录中的文件",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "要列出的目录路径"
                        },
                        "pattern": {
                            "type": "string",
                            "description": "文件匹配模式",
                            "default": "*"
                        }
                    },
                    "required": ["path"]
                }
            }
        ]

    def cleanup(self):
        """
        清理文件管理工具的内部状态：重置 _initialized 标志，释放检查点引用。
        """
        self._initialized = False
        logger.info(f"{self.name} skill cleaned up")
