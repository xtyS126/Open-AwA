"""
MCP 相关 API 路由模块，提供 MCP Server 管理、工具发现与调用的 HTTP 接口。
所有接口均需认证，通过 MCPManager 单例统一管理 Server 连接。

安全：所有 Server 资源按 owner_user_id 隔离，防止 IDOR 跨用户访问他人 MCP Server。
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


def _check_ownership(manager: MCPManager, server_id: str, current_user: User) -> None:
    """
    安全：IDOR 防护——校验当前用户对指定 MCP Server 的所有权。

    策略：
    - Server 不存在 -> 404
    - Server owner_user_id 为 None（旧配置/系统级）-> 仅放行给 is_admin 用户（暂不实现 admin，统一拒绝）
    - Server owner_user_id 与当前用户 ID 不一致 -> 403

    :raises HTTPException: 404 不存在；403 越权访问
    """
    owner = manager.get_server_owner(server_id)
    if owner is None:
        # Server 不存在 OR 旧配置无 owner_user_id 字段
        # 安全侧采取拒绝策略：均返回 404（避免泄露存在性）
        raise HTTPException(status_code=404, detail=f"未找到 MCP Server: {server_id}")
    if owner != current_user.id:
        # 越权访问他人 Server，统一返回 404 避免信息泄露
        raise HTTPException(status_code=404, detail=f"未找到 MCP Server: {server_id}")


@router.get("/servers", response_model=List[MCPServerResponse])
async def get_servers(current_user: User = Depends(get_current_user)):
    """获取已配置的 MCP Server 列表（仅返回当前用户拥有的 Server）"""
    manager = _get_manager()
    # 安全：按 owner_user_id 过滤，避免跨用户泄露
    owned_ids = manager.list_servers_for_user(current_user.id)
    servers = []
    for server_id in owned_ids:
        try:
            status_info = manager.get_server_status(server_id)
        except MCPClientError:
            # 已被并发删除则跳过
            continue
        servers.append(MCPServerResponse(
            id=server_id,
            name=status_info["name"],
            transport_type=status_info["transport_type"],
            status="connected" if status_info["connected"] else "disconnected",
            tools_count=status_info["tools_count"],
        ))
    return servers


@router.post("/servers", response_model=MCPServerResponse)
async def add_server(
    data: MCPServerCreate,
    current_user: User = Depends(get_current_user),
):
    """添加 MCP Server 配置（自动绑定到当前用户）"""
    manager = _get_manager()
    config = MCPServerConfig(
        name=data.name,
        command=data.command,
        args=data.args or [],
        env=data.env or {},
        transport_type=TransportType(data.transport_type),
        url=data.url,
    )
    # 安全：传入 owner_user_id 绑定归属
    server_id = manager.add_server(config, owner_user_id=current_user.id)
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
    """删除 MCP Server 配置（需所有权校验）"""
    manager = _get_manager()
    _check_ownership(manager, server_id, current_user)
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
    """连接指定的 MCP Server（需所有权校验）"""
    manager = _get_manager()
    _check_ownership(manager, server_id, current_user)
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
    """断开指定的 MCP Server 连接（需所有权校验）"""
    manager = _get_manager()
    _check_ownership(manager, server_id, current_user)
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
    """获取指定 MCP Server 的工具列表（需所有权校验）"""
    manager = _get_manager()
    _check_ownership(manager, server_id, current_user)
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
    """调用 MCP 工具（需对 server_id 做所有权校验）"""
    manager = _get_manager()
    _check_ownership(manager, data.server_id, current_user)
    try:
        result = await manager.call_tool(data.server_id, data.tool_name, data.arguments)
        logger.bind(module="mcp.route", event="tool_called", user=current_user.username).info(
            f"用户 {current_user.username} 调用工具: {data.tool_name} (Server: {data.server_id})"
        )
        return MCPToolCallResponse(result=result.result, is_error=result.is_error)
    except MCPClientError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/config/snapshots")
async def list_config_snapshots(current_user: User = Depends(get_current_user)):
    """
    列出 MCP 配置的可用版本快照。

    安全说明：快照为全局文件级回滚机制（涉及 servers.json 整体替换），
    暴露快照元数据（仅文件名/大小/时间）不泄露具体 Server 配置；
    但回滚操作会影响所有用户的配置，因此仅放行给管理员（is_admin）。
    普通用户仅能查看快照列表，无法触发回滚。
    """
    manager = _get_manager()
    return {"snapshots": manager.list_snapshots()}


@router.post("/config/snapshots")
async def create_config_snapshot(
    current_user: User = Depends(get_current_user),
):
    """
    手动创建 MCP 配置快照。

    安全：快照为全局操作，会拷贝当前所有用户的 MCP 配置文件。
    仅管理员（role == 'admin'）可执行。
    """
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="仅管理员可创建配置快照")
    manager = _get_manager()
    snapshot_name = manager.create_snapshot(label="manual")
    if not snapshot_name:
        raise HTTPException(status_code=400, detail="当前没有可用的配置文件，无法创建快照")
    logger.bind(module="mcp.route", event="snapshot_created", user=current_user.username).info(
        f"用户 {current_user.username} 创建了 MCP 配置快照: {snapshot_name}"
    )
    return {"status": "ok", "snapshot_name": snapshot_name}


@router.post("/config/rollback/{snapshot_name}")
async def rollback_config(
    snapshot_name: str,
    current_user: User = Depends(get_current_user),
):
    """
    回滚 MCP 配置到指定快照版本。

    安全：回滚为全局高危操作，会替换所有用户的 MCP 配置，
    仅管理员（role == 'admin'）可执行。
    """
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="仅管理员可回滚配置")
    manager = _get_manager()
    try:
        new_configs = manager.rollback_to_snapshot(snapshot_name)
        logger.bind(module="mcp.route", event="config_rollback", user=current_user.username).info(
            f"用户 {current_user.username} 回滚 MCP 配置到: {snapshot_name}"
        )
        return {
            "status": "ok",
            "message": f"已回滚到快照: {snapshot_name}",
            "server_count": len(new_configs),
        }
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"快照不存在: {snapshot_name}")


@router.post("/config/hot-reload")
async def hot_reload_config(current_user: User = Depends(get_current_user)):
    """
    手动触发 MCP 配置热更新检测。

    安全：热更新为全局操作，仅管理员（role == 'admin'）可执行。
    """
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="仅管理员可触发热更新")
    manager = _get_manager()
    changed = manager.check_hot_reload()
    if changed:
        # 安全：仅返回当前用户拥有的 Server 数量，避免泄露其他用户配置规模
        owned_count = len(manager.list_servers_for_user(current_user.id))
        return {
            "status": "ok",
            "reloaded": True,
            "message": "配置已热更新",
            "server_count": owned_count,
        }
    return {
        "status": "ok",
        "reloaded": False,
        "message": "配置未发生变更",
    }


# ==================== MCP 资源管理 ====================

@router.get("/resources")
async def list_all_resources(current_user: User = Depends(get_current_user)):
    """获取当前用户所有已连接 MCP Server 的资源列表（聚合，按 owner 过滤）"""
    manager = _get_manager()
    owned_ids = manager.list_servers_for_user(current_user.id)
    all_resources = []
    for server_id in owned_ids:
        if not manager.is_server_connected(server_id):
            continue
        try:
            resources = await manager.get_server_resources(server_id)
            for r in resources:
                all_resources.append({
                    "server_id": server_id,
                    "uri": r.uri,
                    "name": r.name,
                    "description": r.description,
                    "mime_type": r.mime_type,
                })
        except (MCPClientError, Exception) as e:
            logger.bind(module="mcp.route", event="list_resources_error").warning(
                f"获取 Server {server_id} 资源列表失败: {e}"
            )
    return {"success": True, "resources": all_resources, "count": len(all_resources)}


@router.get("/servers/{server_id}/resources")
async def list_server_resources(
    server_id: str,
    current_user: User = Depends(get_current_user),
):
    """获取指定 MCP Server 的资源列表（需所有权校验）"""
    manager = _get_manager()
    _check_ownership(manager, server_id, current_user)
    try:
        resources = await manager.get_server_resources(server_id)
        return {
            "success": True,
            "server_id": server_id,
            "resources": [
                {
                    "uri": r.uri,
                    "name": r.name,
                    "description": r.description,
                    "mime_type": r.mime_type,
                }
                for r in resources
            ],
            "count": len(resources),
        }
    except Exception as e:
        # 记录实际异常便于排查，但避免向客户端泄露内部错误详情
        logger.error("获取资源列表失败", exc_info=e, extra={"server_id": server_id})
        raise HTTPException(status_code=500, detail="获取资源列表失败，请稍后重试")


@router.post("/servers/{server_id}/resources/read")
async def read_server_resource(
    server_id: str,
    body: dict,
    current_user: User = Depends(get_current_user),
):
    """读取指定 MCP Server 的资源内容（需所有权校验）"""
    uri = body.get("uri")
    if not uri:
        raise HTTPException(status_code=400, detail="缺少 uri 参数")
    manager = _get_manager()
    _check_ownership(manager, server_id, current_user)
    try:
        content = await manager.read_server_resource(server_id, uri)
        return {
            "success": True,
            "server_id": server_id,
            "uri": content.uri,
            "mime_type": content.mime_type,
            "text": content.text,
            "blob": content.blob,
        }
    except Exception as e:
        # 记录实际异常便于排查，但避免向客户端泄露内部错误详情
        logger.error("读取资源失败", exc_info=e, extra={"server_id": server_id, "uri": uri})
        raise HTTPException(status_code=500, detail="读取资源失败，请稍后重试")
