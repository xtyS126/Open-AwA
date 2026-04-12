"""
Agent工具管理路由 - 提供文件操作、终端执行、网页搜索等工具的统一API入口。
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from loguru import logger

from skills.built_in.file_manager import FileManagerSkill
from skills.built_in.terminal_executor import TerminalExecutorSkill
from skills.built_in.web_search import WebSearchSkill


router = APIRouter(prefix="/api/tools", tags=["agent-tools"])

# 全局工具实例
_file_manager: Optional[FileManagerSkill] = None
_terminal_executor: Optional[TerminalExecutorSkill] = None
_web_search: Optional[WebSearchSkill] = None


async def _get_file_manager() -> FileManagerSkill:
    """获取或初始化文件管理工具。"""
    global _file_manager
    if _file_manager is None or not _file_manager.is_initialized():
        _file_manager = FileManagerSkill()
        await _file_manager.initialize()
    return _file_manager


async def _get_terminal_executor() -> TerminalExecutorSkill:
    """获取或初始化终端执行工具。"""
    global _terminal_executor
    if _terminal_executor is None or not _terminal_executor.is_initialized():
        _terminal_executor = TerminalExecutorSkill()
        await _terminal_executor.initialize()
    return _terminal_executor


async def _get_web_search() -> WebSearchSkill:
    """获取或初始化网页搜索工具。"""
    global _web_search
    if _web_search is None or not _web_search.is_initialized():
        _web_search = WebSearchSkill()
        await _web_search.initialize()
    return _web_search


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
    fm = await _get_file_manager()
    te = await _get_terminal_executor()
    ws = await _get_web_search()

    tools = {
        "file_manager": {
            "name": "file_manager",
            "display_name": "文件管理器",
            "description": "文件检索、查看、创建、编辑和删除",
            "version": fm.version,
            "status": "active",
            "tools": fm.get_tools()
        },
        "terminal_executor": {
            "name": "terminal_executor",
            "display_name": "终端执行器",
            "description": "在终端运行命令并获取状态和结果",
            "version": te.version,
            "status": "active",
            "tools": te.get_tools()
        },
        "web_search": {
            "name": "web_search",
            "display_name": "网页搜索",
            "description": "搜索和用户任务相关的网页",
            "version": ws.version,
            "status": "active",
            "tools": ws.get_tools()
        }
    }
    return {"tools": tools, "count": len(tools)}


# --- 文件操作 ---

@router.post("/file/read", response_model=ToolResponse)
async def file_read(req: FileReadRequest):
    """读取文件内容。"""
    fm = await _get_file_manager()
    result = await fm.execute(action='read_file', path=req.path)
    return ToolResponse(
        success=result.get('success', False),
        data=result if result.get('success') else None,
        error=result.get('error')
    )


@router.post("/file/write", response_model=ToolResponse)
async def file_write(req: FileWriteRequest):
    """写入文件内容。"""
    fm = await _get_file_manager()
    result = await fm.execute(action='write_file', path=req.path, content=req.content)
    return ToolResponse(
        success=result.get('success', False),
        data=result if result.get('success') else None,
        error=result.get('error')
    )


@router.post("/file/list", response_model=ToolResponse)
async def file_list(req: FileListRequest):
    """列出目录文件。"""
    fm = await _get_file_manager()
    result = await fm.execute(action='list_files', path=req.path, pattern=req.pattern)
    return ToolResponse(
        success=result.get('success', False),
        data=result if result.get('success') else None,
        error=result.get('error')
    )


@router.post("/file/delete", response_model=ToolResponse)
async def file_delete(req: FileDeleteRequest):
    """删除文件或目录。"""
    fm = await _get_file_manager()
    result = await fm.execute(action='delete_file', path=req.path)
    return ToolResponse(
        success=result.get('success', False),
        data=result if result.get('success') else None,
        error=result.get('error')
    )


@router.post("/file/exists", response_model=ToolResponse)
async def file_exists(req: FileReadRequest):
    """检查文件是否存在。"""
    fm = await _get_file_manager()
    result = await fm.execute(action='file_exists', path=req.path)
    return ToolResponse(
        success=result.get('success', False),
        data=result if result.get('success') else None,
        error=result.get('error')
    )


# --- 终端命令 ---

@router.post("/terminal/run", response_model=ToolResponse)
async def terminal_run(req: CommandRequest):
    """执行终端命令。"""
    te = await _get_terminal_executor()
    result = await te.execute(
        action='run_command',
        command=req.command,
        working_dir=req.working_dir,
        timeout=req.timeout
    )
    return ToolResponse(
        success=result.get('success', False),
        data=result if result.get('success') else None,
        error=result.get('error')
    )


@router.get("/terminal/status", response_model=ToolResponse)
async def terminal_status():
    """获取系统状态。"""
    te = await _get_terminal_executor()
    result = await te.execute(action='get_status')
    return ToolResponse(
        success=result.get('success', False),
        data=result if result.get('success') else None,
        error=result.get('error')
    )


# --- 网页搜索 ---

@router.post("/search/web", response_model=ToolResponse)
async def web_search(req: SearchRequest):
    """搜索网页。"""
    ws = await _get_web_search()
    result = await ws.execute(
        action='search',
        query=req.query,
        max_results=req.max_results
    )
    return ToolResponse(
        success=result.get('success', False),
        data=result if result.get('success') else None,
        error=result.get('error')
    )


@router.post("/search/fetch", response_model=ToolResponse)
async def fetch_url(req: FetchUrlRequest):
    """获取URL内容。"""
    ws = await _get_web_search()
    result = await ws.execute(
        action='fetch_url',
        url=req.url,
        max_length=req.max_length
    )
    return ToolResponse(
        success=result.get('success', False),
        data=result if result.get('success') else None,
        error=result.get('error')
    )
