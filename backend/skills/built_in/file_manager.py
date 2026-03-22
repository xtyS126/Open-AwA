import os
from pathlib import Path
from typing import Dict, Any, List, Optional
from loguru import logger


class FileManagerSkill:
    name: str = "file_manager"
    version: str = "1.0.0"
    description: str = "文件管理技能"

    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or {}
        self.allowed_directories: List[str] = self.config.get('allowed_directories', [])
        self._initialized = False

    async def initialize(self) -> bool:
        logger.info(f"Initializing {self.name} skill v{self.version}")
        self._setup_allowed_directories()
        logger.info(f"FileManager initialized with allowed directories: {self.allowed_directories}")
        self._initialized = True
        return True

    def _setup_allowed_directories(self):
        if not self.allowed_directories:
            self.allowed_directories = [os.getcwd()]
        self.allowed_directories = [
            str(Path(d).resolve()) for d in self.allowed_directories
        ]

    def _validate_path(self, file_path: str) -> bool:
        resolved_path = str(Path(file_path).resolve())
        for allowed_dir in self.allowed_directories:
            if resolved_path.startswith(allowed_dir):
                return True
        logger.warning(f"Access denied to path: {file_path}")
        return False

    async def execute(self, **kwargs) -> Dict[str, Any]:
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
        file_path = kwargs.get('path')
        if not file_path:
            return {"success": False, "error": "path parameter is required"}

        if not self._validate_path(file_path):
            return {"success": False, "error": "Access denied"}

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
        except Exception as e:
            logger.error(f"Error reading file {file_path}: {e}")
            return {"success": False, "error": str(e)}

    async def _write_file(self, kwargs: Dict[str, Any]) -> Dict[str, Any]:
        file_path = kwargs.get('path')
        content = kwargs.get('content', '')

        if not file_path:
            return {"success": False, "error": "path parameter is required"}

        if not self._validate_path(file_path):
            return {"success": False, "error": "Access denied"}

        try:
            directory = Path(file_path).parent
            directory.mkdir(parents=True, exist_ok=True)

            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(content)

            logger.info(f"Successfully wrote file: {file_path}")
            return {
                "success": True,
                "path": file_path,
                "bytes_written": len(content.encode('utf-8'))
            }
        except Exception as e:
            logger.error(f"Error writing file {file_path}: {e}")
            return {"success": False, "error": str(e)}

    async def _list_files(self, kwargs: Dict[str, Any]) -> Dict[str, Any]:
        directory = kwargs.get('path', '')
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
        file_path = kwargs.get('path')

        if not file_path:
            return {"success": False, "error": "path parameter is required"}

        if not self._validate_path(file_path):
            return {"success": False, "error": "Access denied"}

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
        file_path = kwargs.get('path')

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
        directory = kwargs.get('path')

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
        self._initialized = False
        logger.info(f"{self.name} skill cleaned up")
