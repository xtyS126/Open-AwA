"""
MCP 相关 API 路由模块，提供 MCP Server 管理、工具发现与调用的 HTTP 接口。
所有接口均需认证，通过 MCPManager 单例统一管理 Server 连接。
"""

from typing import List

from fastapi import APIRouter, Depends, HTTPException
from loguru import logger

from api.dependencies import get_current_user
from api.schemas import MCPServerCreate, MCPServerResponse, MCPToolCallCreate, MCPToolCallResponse
from db.models import User
from mcp.client import MCPClientError
from mcp.manager import MCPManager
from mcp.types import MCPServerConfig, TransportType

router = APIRouter(prefix="/api/mcp", tags=["MCP"])


def _get_manager() -> MCPManager:
    """获取 MCP 管理器单例"""
    return MCPManager()


@router.get("/servers", response_model=List[MCPServerResponse])
async def get_servers(current_user: User = Depends(get_current_user)):
    """获取已配置的 MCP Server 列表"""
    manager = _get_manager()
    servers = manager.get_all_servers()
    return [
        MCPServerResponse(
            id=s["server_id"],
            name=s["name"],
            transport_type=s["transport_type"],
            status="connected" if s["connected"] else "disconnected",
            tools_count=s["tools_count"],
        )
        for s in servers
    ]


@router.post("/servers", response_model=MCPServerResponse)
async def add_server(
    data: MCPServerCreate,
    current_user: User = Depends(get_current_user),
):
    """添加 MCP Server 配置"""
    manager = _get_manager()
    config = MCPServerConfig(
        name=data.name,
        command=data.command,
        args=data.args or [],
        env=data.env or {},
        transport_type=TransportType(data.transport_type),
        url=data.url,
    )
    server_id = manager.add_server(config)
    logger.bind(module="mcp.route", event="server_added", user=current_user.username).info(
        f"用户 {current_user.username} 添加了 MCP Server: {data.name}"
    )
    status_info = manager.get_server_status(server_id)
    return MCPServerResponse(
        id=server_id,
        name=status_info["name"],
        transport_type=status_info["transport_type"],
        status="disconnected",
        tools_count=0,
    )


@router.delete("/servers/{server_id}")
async def delete_server(
    server_id: str,
    current_user: User = Depends(get_current_user),
):
    """删除 MCP Server 配置"""
    manager = _get_manager()
    try:
        # 先断开连接（如果已连接）
        client = manager._clients.get(server_id)
        if client and client.is_connected:
            await manager.disconnect_server(server_id)
        manager.remove_server(server_id)
        logger.bind(module="mcp.route", event="server_deleted", user=current_user.username).info(
            f"用户 {current_user.username} 删除了 MCP Server: {server_id}"
        )
        return {"status": "ok", "message": f"已删除 MCP Server: {server_id}"}
    except MCPClientError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/servers/{server_id}/connect")
async def connect_server(
    server_id: str,
    current_user: User = Depends(get_current_user),
):
    """连接指定的 MCP Server"""
    manager = _get_manager()
    try:
        await manager.connect_server(server_id)
        status_info = manager.get_server_status(server_id)
        return {"status": "ok", "message": f"已连接 MCP Server: {server_id}", "server": status_info}
    except MCPClientError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/servers/{server_id}/disconnect")
async def disconnect_server(
    server_id: str,
    current_user: User = Depends(get_current_user),
):
    """断开指定的 MCP Server 连接"""
    manager = _get_manager()
    try:
        await manager.disconnect_server(server_id)
        return {"status": "ok", "message": f"已断开 MCP Server: {server_id}"}
    except MCPClientError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/servers/{server_id}/tools")
async def get_server_tools(
    server_id: str,
    current_user: User = Depends(get_current_user),
):
    """获取指定 MCP Server 的工具列表"""
    manager = _get_manager()
    try:
        tools = await manager.get_server_tools(server_id)
        return {
            "server_id": server_id,
            "tools": [tool.model_dump() for tool in tools],
        }
    except MCPClientError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/tools/call", response_model=MCPToolCallResponse)
async def call_tool(
    data: MCPToolCallCreate,
    current_user: User = Depends(get_current_user),
):
    """调用 MCP 工具"""
    manager = _get_manager()
    try:
        result = await manager.call_tool(data.server_id, data.tool_name, data.arguments)
        logger.bind(module="mcp.route", event="tool_called", user=current_user.username).info(
            f"用户 {current_user.username} 调用工具: {data.tool_name} (Server: {data.server_id})"
        )
        return MCPToolCallResponse(result=result.result, is_error=result.is_error)
    except MCPClientError as e:
        raise HTTPException(status_code=400, detail=str(e))
