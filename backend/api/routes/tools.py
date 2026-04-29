"""
Agent工具管理路由 - 提供文件操作、终端执行、网页搜索等工具的统一API入口。
"""

from fastapi import APIRouter
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any

from loguru import logger

from tools.registry import built_in_tool_registry


router = APIRouter(prefix="/api/tools", tags=["agent-tools"])


async def _safe_execute_tool(tool_name: str, action: str, params: dict) -> dict:
    """安全执行内置工具，捕获所有异常并返回结构化错误响应。"""
    try:
        return await built_in_tool_registry.execute_tool(
            tool_name, action=action, params=params
        )
    except Exception as exc:
        logger.bind(
            module="tools",
            event="tool_execution_error",
            tool_name=tool_name,
            action=action,
        ).error(f"工具执行异常: {exc}")
        return {"success": False, "error": str(exc)}


# --- 请求/响应模型 ---

class FileReadRequest(BaseModel):
    """文件读取请求。"""
    path: str = Field(..., description="文件路径")


class FileWriteRequest(BaseModel):
    """文件写入请求。"""
    path: str = Field(..., description="文件路径")
    content: str = Field(..., description="文件内容")


class FileListRequest(BaseModel):
    """文件列表请求。"""
    path: str = Field(..., description="目录路径")
    pattern: str = Field(default="*", description="匹配模式")


class FileDeleteRequest(BaseModel):
    """文件删除请求。"""
    path: str = Field(..., description="文件路径")


class CommandRequest(BaseModel):
    """命令执行请求。"""
    command: str = Field(..., description="要执行的命令")
    working_dir: Optional[str] = Field(default=None, description="工作目录")
    timeout: int = Field(default=30, ge=1, le=300, description="超时时间（秒）")


class SearchRequest(BaseModel):
    """搜索请求。"""
    query: str = Field(..., description="搜索关键词")
    max_results: int = Field(default=10, ge=1, le=20, description="最大结果数")


class FetchUrlRequest(BaseModel):
    """URL获取请求。"""
    url: str = Field(..., description="URL地址")
    max_length: int = Field(default=10000, ge=100, le=50000, description="最大内容长度")


class ToolResponse(BaseModel):
    """统一工具响应。"""
    success: bool
    data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


# --- 工具列表 ---

@router.get("/list")
async def list_tools():
    """获取所有可用的Agent工具列表。"""
    tools = await built_in_tool_registry.list_tools()
    return {"tools": tools, "count": len(tools)}


# --- 文件操作 ---

@router.post("/file/read", response_model=ToolResponse)
async def file_read(req: FileReadRequest):
    """读取文件内容。"""
    result = await _safe_execute_tool(
        'file_manager',
        action='read_file',
        params={'path': req.path}
    )
    return ToolResponse(
        success=result.get('success', False),
        data=result if result.get('success') else None,
        error=result.get('error')
    )


@router.post("/file/write", response_model=ToolResponse)
async def file_write(req: FileWriteRequest):
    """写入文件内容。"""
    result = await _safe_execute_tool(
        'file_manager',
        action='write_file',
        params={'path': req.path, 'content': req.content}
    )
    return ToolResponse(
        success=result.get('success', False),
        data=result if result.get('success') else None,
        error=result.get('error')
    )


@router.post("/file/list", response_model=ToolResponse)
async def file_list(req: FileListRequest):
    """列出目录文件。"""
    result = await _safe_execute_tool(
        'file_manager',
        action='list_files',
        params={'path': req.path, 'pattern': req.pattern}
    )
    return ToolResponse(
        success=result.get('success', False),
        data=result if result.get('success') else None,
        error=result.get('error')
    )


@router.post("/file/delete", response_model=ToolResponse)
async def file_delete(req: FileDeleteRequest):
    """删除文件或目录。"""
    result = await _safe_execute_tool(
        'file_manager',
        action='delete_file',
        params={'path': req.path}
    )
    return ToolResponse(
        success=result.get('success', False),
        data=result if result.get('success') else None,
        error=result.get('error')
    )


@router.post("/file/exists", response_model=ToolResponse)
async def file_exists(req: FileReadRequest):
    """检查文件是否存在。"""
    result = await _safe_execute_tool(
        'file_manager',
        action='file_exists',
        params={'path': req.path}
    )
    return ToolResponse(
        success=result.get('success', False),
        data=result if result.get('success') else None,
        error=result.get('error')
    )


# --- 终端命令 ---

@router.post("/terminal/run", response_model=ToolResponse)
async def terminal_run(req: CommandRequest):
    """执行终端命令。"""
    result = await _safe_execute_tool(
        'terminal_executor',
        action='run_command',
        params={
            'command': req.command,
            'working_dir': req.working_dir,
            'timeout': req.timeout,
        }
    )
    return ToolResponse(
        success=result.get('success', False),
        data=result if result.get('success') else None,
        error=result.get('error')
    )


@router.get("/terminal/status", response_model=ToolResponse)
async def terminal_status():
    """获取系统状态。"""
    result = await _safe_execute_tool(
        'terminal_executor',
        action='get_status',
        params={}
    )
    return ToolResponse(
        success=result.get('success', False),
        data=result if result.get('success') else None,
        error=result.get('error')
    )


# --- 网页搜索 ---

@router.post("/search/web", response_model=ToolResponse)
async def web_search(req: SearchRequest):
    """搜索网页。"""
    result = await _safe_execute_tool(
        'web_search',
        action='search',
        params={
            'query': req.query,
            'max_results': req.max_results,
        }
    )
    return ToolResponse(
        success=result.get('success', False),
        data=result if result.get('success') else None,
        error=result.get('error')
    )


@router.post("/search/fetch", response_model=ToolResponse)
async def fetch_url(req: FetchUrlRequest):
    """获取URL内容。"""
    result = await _safe_execute_tool(
        'web_search',
        action='fetch_url',
        params={
            'url': req.url,
            'max_length': req.max_length,
        }
    )
    return ToolResponse(
        success=result.get('success', False),
        data=result if result.get('success') else None,
        error=result.get('error')
    )
