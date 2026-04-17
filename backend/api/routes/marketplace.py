"""
插件市场路由模块，提供插件浏览、搜索、详情查看与安装接口。
"""

from fastapi import APIRouter, HTTPException, Query, Depends
from sqlalchemy.orm import Session
from typing import Optional

from api.dependencies import get_current_user
from api.schemas import MarketplacePluginResponse, MarketplaceSearchResponse
from db.models import get_db, Plugin
from plugins.marketplace.registry import marketplace_registry
from plugins import plugin_instance
from loguru import logger
import uuid


router = APIRouter(prefix="/api/marketplace", tags=["Marketplace"])


@router.get(
    "/plugins",
    response_model=MarketplaceSearchResponse,
    summary="浏览插件列表",
    description="分页获取市场中的插件列表，支持按分类筛选。",
)
async def list_plugins(
    category: Optional[str] = Query(None, description="插件分类"),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(12, ge=1, le=50, description="每页数量"),
    current_user=Depends(get_current_user),
):
    """分页获取市场插件列表"""
    result = marketplace_registry.list_plugins(
        category=category,
        page=page,
        page_size=page_size,
    )
    return result


@router.get(
    "/plugins/search",
    response_model=MarketplaceSearchResponse,
    summary="搜索插件",
    description="根据关键词搜索插件名称、描述和标签。",
)
async def search_plugins(
    q: str = Query("", description="搜索关键词"),
    current_user=Depends(get_current_user),
):
    """根据关键词搜索市场插件"""
    plugins = marketplace_registry.search_plugins(q)
    return {
        "plugins": plugins,
        "total": len(plugins),
        "page": 1,
        "page_size": len(plugins),
    }


@router.get(
    "/plugins/{plugin_id}",
    response_model=MarketplacePluginResponse,
    summary="获取插件详情",
    description="根据插件ID获取详细信息。",
)
async def get_plugin_detail(
    plugin_id: str,
    current_user=Depends(get_current_user),
):
    """获取单个插件的详细信息"""
    plugin = marketplace_registry.get_plugin(plugin_id)
    if not plugin:
        raise HTTPException(status_code=404, detail="插件不存在")
    return plugin


@router.post(
    "/plugins/{plugin_id}/install",
    summary="从市场安装插件",
    description="将市场中的插件安装到当前系统。",
)
async def install_plugin(
    plugin_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """从市场安装指定插件到系统"""
    # 检查插件是否存在于市场
    plugin_meta = marketplace_registry.get_plugin(plugin_id)
    if not plugin_meta:
        raise HTTPException(status_code=404, detail="市场中不存在该插件")

    # 使用插件 id 作为名称（与文件系统目录名及插件类名一致），而非展示用的 name
    plugin_name = plugin_meta["id"]

    # 检查是否已安装（按插件 id 匹配）
    existing = db.query(Plugin).filter(Plugin.name == plugin_name).first()
    if existing:
        raise HTTPException(status_code=400, detail="该插件已安装")

    # 创建插件记录
    new_plugin = Plugin(
        id=str(uuid.uuid4()),
        name=plugin_name,
        version=plugin_meta.get("version", "1.0.0"),
        enabled=True,
        config={},
        author=plugin_meta.get("author", "unknown"),
        category=plugin_meta.get("category", "general"),
        source="marketplace",
    )
    db.add(new_plugin)
    db.commit()
    db.refresh(new_plugin)

    # 尝试通过全局插件管理器发现并加载插件到运行时
    pm = plugin_instance.get()
    if plugin_name not in pm.plugin_metadata:
        pm.discover_plugins()
    if plugin_name in pm.plugin_metadata:
        try:
            pm.load_plugin(plugin_name)
            logger.bind(
                event="marketplace_plugin_loaded",
                module="marketplace",
                plugin_name=plugin_name,
            ).info(f"市场插件 '{plugin_name}' 安装后已成功加载")
        except Exception as exc:
            logger.bind(
                event="marketplace_plugin_load_failed",
                module="marketplace",
                plugin_name=plugin_name,
            ).warning(f"市场插件 '{plugin_name}' 安装成功但加载失败: {exc}")
    else:
        logger.bind(
            event="marketplace_plugin_not_found",
            module="marketplace",
            plugin_name=plugin_name,
        ).warning(f"市场插件 '{plugin_name}' 已注册到数据库但未在文件系统中发现")

    logger.bind(
        event="marketplace_install",
        module="marketplace",
        plugin_id=plugin_id,
        plugin_name=plugin_name,
    ).info(f"从市场安装插件: {plugin_name}")

    return {
        "status": "success",
        "message": f"插件 {plugin_name} 安装成功",
        "plugin_id": new_plugin.id,
    }


@router.get(
    "/categories",
    summary="获取分类列表",
    description="获取市场中所有插件分类。",
)
async def get_categories(
    current_user=Depends(get_current_user),
):
    """获取所有插件分类"""
    categories = marketplace_registry.get_categories()
    return {"categories": categories}
