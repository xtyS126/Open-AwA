"""
MCP 相关 API 路由模块，提供 MCP Server 管理、工具发现与调用的 HTTP 接口。
所有接口均需认证，通过 MCPManager 单例统一管理 Server 连接。
"""

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from loguru import logger

from api.dependencies import get_current_user
from api.schemas import BaseModel, Field, MCPServerCreate, MCPServerResponse, MCPToolCallCreate, MCPToolCallResponse
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
        if manager.is_server_connected(server_id):
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


class ConfigSnapshotResponse(BaseModel):
    """配置快照响应"""
    version: str
    timestamp: str
    configs: List[Dict[str, Any]]
    metadata: Dict[str, Any]


class ConfigImportRequest(BaseModel):
    """配置导入请求"""
    json_content: str = Field(..., description="JSON 格式的配置内容")
    replace: bool = Field(default=False, description="是否替换现有配置，False 时为合并")


class ConfigExportResponse(BaseModel):
    """配置导出响应"""
    version: str
    timestamp: str
    configs: List[Dict[str, Any]]


@router.get("/config-center/status")
async def get_config_center_status(current_user: User = Depends(get_current_user)):
    """获取 MCP 配置中心状态"""
    from config.mcp_config_center import get_config_center

    center = get_config_center()
    return {
        "status": "ok",
        "current_version": center.get_current_version(),
        "configs_count": len(center.get_configs()),
        "snapshots_count": len(center.get_snapshots()),
    }


@router.get("/config-center/snapshots")
async def get_config_snapshots(current_user: User = Depends(get_current_user)):
    """获取所有配置快照列表"""
    from config.mcp_config_center import get_config_center

    center = get_config_center()
    snapshots = center.get_snapshots()
    return {
        "snapshots": [
            ConfigSnapshotResponse(
                version=s.version,
                timestamp=s.timestamp,
                configs=s.configs,
                metadata=s.metadata,
            )
            for s in snapshots
        ]
    }


@router.post("/config-center/snapshots")
async def create_config_snapshot(
    metadata: Optional[Dict[str, Any]] = None,
    current_user: User = Depends(get_current_user),
):
    """创建配置快照"""
    from config.mcp_config_center import get_config_center

    center = get_config_center()
    snapshot = center.create_snapshot(metadata=metadata)
    logger.bind(module="mcp.route", event="snapshot_created", user=current_user.username).info(
        f"用户 {current_user.username} 创建了配置快照: {snapshot.version}"
    )
    return {
        "status": "ok",
        "snapshot": ConfigSnapshotResponse(
            version=snapshot.version,
            timestamp=snapshot.timestamp,
            configs=snapshot.configs,
            metadata=snapshot.metadata,
        ),
    }


@router.get("/config-center/snapshots/{version}")
async def get_config_snapshot(
    version: str,
    current_user: User = Depends(get_current_user),
):
    """获取指定版本的配置快照"""
    from config.mcp_config_center import get_config_center

    center = get_config_center()
    snapshot = center.get_snapshot(version)
    if not snapshot:
        raise HTTPException(status_code=404, detail=f"未找到版本: {version}")
    return {
        "snapshot": ConfigSnapshotResponse(
            version=snapshot.version,
            timestamp=snapshot.timestamp,
            configs=snapshot.configs,
            metadata=snapshot.metadata,
        )
    }


@router.post("/config-center/rollback/{version}")
async def rollback_config(
    version: str,
    current_user: User = Depends(get_current_user),
):
    """回滚配置到指定版本"""
    from config.mcp_config_center import get_config_center

    center = get_config_center()
    success = center.rollback_to(version)
    if not success:
        raise HTTPException(status_code=404, detail=f"回滚失败，未找到版本: {version}")
    logger.bind(module="mcp.route", event="config_rollback", user=current_user.username).info(
        f"用户 {current_user.username} 将配置回滚到版本: {version}"
    )
    return {
        "status": "ok",
        "message": f"配置已回滚到版本: {version}",
        "current_version": center.get_current_version(),
    }


@router.get("/config-center/export")
async def export_configs(current_user: User = Depends(get_current_user)):
    """导出当前配置"""
    from config.mcp_config_center import get_config_center

    center = get_config_center()
    export_data = center.export_configs()
    return ConfigExportResponse.model_validate_json(export_data)


@router.post("/config-center/import")
async def import_configs(
    data: ConfigImportRequest,
    current_user: User = Depends(get_current_user),
):
    """导入配置"""
    from config.mcp_config_center import get_config_center

    center = get_config_center()
    try:
        count = center.import_configs(data.json_content, replace=data.replace)
        logger.bind(module="mcp.route", event="configs_imported", user=current_user.username).info(
            f"用户 {current_user.username} 导入了 {count} 个配置"
        )
        return {
            "status": "ok",
            "message": f"成功导入 {count} 个配置",
            "current_version": center.get_current_version(),
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"导入失败: {str(e)}")
