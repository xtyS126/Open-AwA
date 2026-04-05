"""
安全控制模块，负责权限约束、沙箱限制、审计记录或安全边界保护。
这里的逻辑通常用于避免未授权操作、危险行为或不可控的资源访问。
"""

import asyncio
from typing import Dict, Any, Optional
from loguru import logger
from config.settings import settings


class Sandbox:
    """
    封装与Sandbox相关的核心逻辑与运行状态。
    该类通常是当前文件中组织数据与调度行为的主要封装单元。
    """
    def __init__(self):
        """
        处理init相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        self.timeout = settings.SANDBOX_TIMEOUT
        logger.info("Sandbox initialized")
    
    async def execute_command(
        self,
        command: str,
        working_dir: Optional[str] = None,
        env: Optional[Dict[str, str]] = None
    ) -> Dict[str, Any]:
        """
        处理execute、command相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        logger.info(f"Executing command in sandbox: {command[:100]}...")
        
        try:
            process = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=working_dir,
                env=env
            )
            
            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=self.timeout
                )
                
                return {
                    "status": "success",
                    "returncode": process.returncode,
                    "stdout": stdout.decode() if stdout else "",
                    "stderr": stderr.decode() if stderr else ""
                }
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
                
                logger.warning(f"Command timeout after {self.timeout}s")
                return {
                    "status": "timeout",
                    "message": f"Command execution exceeded {self.timeout}s limit"
                }
                
        except Exception as e:
            logger.error(f"Command execution error: {str(e)}")
            return {
                "status": "error",
                "message": str(e)
            }
    
    async def execute_file_operation(
        self,
        operation: str,
        file_path: str,
        content: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        处理execute、file、operation相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        try:
            if operation == "read":
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                return {
                    "status": "success",
                    "content": content
                }
            elif operation == "write":
                if content is None:
                    return {"status": "error", "message": "content cannot be None"}
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(content)
                return {
                    "status": "success",
                    "message": f"Written to {file_path}"
                }
            elif operation == "delete":
                import os
                if os.path.exists(file_path):
                    os.remove(file_path)
                    return {
                        "status": "success",
                        "message": f"Deleted {file_path}"
                    }
                else:
                    return {
                        "status": "error",
                        "message": f"File not found: {file_path}"
                    }
            else:
                return {
                    "status": "error",
                    "message": f"Unknown operation: {operation}"
                }
        except Exception as e:
            logger.error(f"File operation error: {str(e)}")
            return {
                "status": "error",
                "message": str(e)
            }
    
    async def check_permission(
        self,
        operation: str,
        target: str
    ) -> bool:
        """
        检查permission相关条件、状态或权限是否满足要求。
        检查结果往往会直接决定后续是否允许继续执行某项操作。
        """
        dangerous_operations = {
            "delete": ["system", "config", "password"],
            "execute": ["rm", "del", "format", "shutdown"],
            "write": ["sudo", "/etc", "/root"]
        }
        
        if operation in dangerous_operations:
            for keyword in dangerous_operations[operation]:
                if keyword in target.lower():
                    logger.warning(f"Potentially dangerous operation detected: {operation} on {target}")
                    return False
        
        return True
