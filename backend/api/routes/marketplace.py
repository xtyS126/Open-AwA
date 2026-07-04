"""
插件市场路由模块，提供插件浏览、搜索、详情查看、安装、版本管理与社区功能。
"""

from fastapi import APIRouter, HTTPException, Query, Depends
from sqlalchemy.orm import Session
from typing import Optional, List, Dict
from pathlib import Path
from datetime import datetime, timezone
import asyncio
import time
import uuid

from api.dependencies import get_current_user
from api.schemas import (
    MarketplacePluginResponse,
    MarketplaceSearchResponse,
    PluginVersionResponse,
    PluginVersionListResponse,
    PluginInstallWithVersionRequest,
    PluginUpgradeRequest,
    PluginUpgradeResponse,
    PluginUpdateCheckResponse,
    PluginRatingCreate,
    PluginRatingSummaryResponse,
    PluginReviewCreate,
    PluginReviewUpdate,
    PluginReviewResponse,
    PluginReviewListResponse,
    PluginDownloadResponse,
)
from db.models import (
    Plugin,
    PluginVersion,
    PluginRating,
    PluginReview,
    PluginDownloadLog,
    get_db,
)
from plugins.marketplace.registry import marketplace_registry
from plugins.marketplace import version_manager, community
from plugins.marketplace.downloader import (
    download_plugin_package,
    extract_plugin_package,
    cleanup_package,
    DownloadError,
)
from plugins.plugin_manager import PluginManager
from loguru import logger


router = APIRouter(prefix="/api/marketplace", tags=["Marketplace"])
plugin_manager = PluginManager()

# 插件包缓存目录
PLUGIN_CACHE_DIR = Path("./data/plugin_cache")
PLUGIN_INSTALL_DIR = Path("./data/plugins")


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
    description="将市场中的插件安装到当前系统，支持指定版本。",
)
async def install_plugin(
    plugin_id: str,
    payload: Optional[PluginInstallWithVersionRequest] = None,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """
    从市场安装指定插件到系统。

    若提供 version 字段则安装指定版本，否则安装市场注册表中的默认版本。
    当插件存在 download_url 时，会执行远端下载与 SHA256 校验。
    """
    # 检查插件是否存在于市场
    plugin_meta = marketplace_registry.get_plugin(plugin_id)
    if not plugin_meta:
        raise HTTPException(status_code=404, detail="市场中不存在该插件")

    # 检查是否已安装
    existing = db.query(Plugin).filter(Plugin.name == plugin_meta["name"]).first()
    if existing:
        raise HTTPException(status_code=400, detail="该插件已安装")

    target_version = plugin_meta.get("version", "1.0.0")
    download_url = plugin_meta.get("download_url", "")
    sha256_checksum = ""

    # 若指定版本，从版本表查询
    if payload and payload.version:
        version_record = db.query(PluginVersion).filter(
            PluginVersion.plugin_id == plugin_id,
            PluginVersion.version == payload.version,
        ).first()
        if not version_record:
            raise HTTPException(status_code=404, detail=f"版本 {payload.version} 不存在")
        target_version = version_record.version
        download_url = version_record.download_url or download_url
        sha256_checksum = version_record.sha256_checksum

    # 记录下载日志
    download_log = PluginDownloadLog(
        plugin_id=plugin_id,
        version=target_version,
        user_id=str(current_user.id),
        status="started",
        source_type="remote" if download_url else "local",
    )
    db.add(download_log)
    db.commit()
    db.refresh(download_log)

    started_at = time.time()
    try:
        # 若有下载地址，执行远端下载
        if download_url:
            try:
                package_path, actual_sha256 = await asyncio.wait_for(
                    download_plugin_package(
                        download_url=download_url,
                        expected_sha256=sha256_checksum or None,
                        cache_dir=PLUGIN_CACHE_DIR,
                    ),
                    timeout=120,
                )
                # 解压到安装目录
                install_dir = PLUGIN_INSTALL_DIR / plugin_meta["name"]
                extract_plugin_package(package_path, install_dir)
                cleanup_package(package_path)
                logger.info(
                    f"插件远端下载并解压成功: plugin={plugin_id}, version={target_version}"
                )
            except DownloadError as exc:
                download_log.status = "failed"
                download_log.error_message = str(exc)
                download_log.duration_ms = int((time.time() - started_at) * 1000)
                db.commit()
                # 记录实际异常便于排查，但避免向客户端泄露内部错误详情
                logger.error("插件下载失败", exc_info=exc, extra={"plugin_id": plugin_id, "target_version": target_version})
                raise HTTPException(status_code=502, detail="插件下载失败，请稍后重试")

        # 创建插件记录
        new_plugin = Plugin(
            id=str(uuid.uuid4()),
            name=plugin_meta["name"],
            version=target_version,
            enabled=False,
            config={},
        )
        db.add(new_plugin)

        # 更新下载日志为成功
        download_log.status = "success"
        download_log.duration_ms = int((time.time() - started_at) * 1000)
        db.commit()
        db.refresh(new_plugin)

        logger.bind(
            event="marketplace_install",
            module="marketplace",
            plugin_id=plugin_id,
            plugin_name=plugin_meta["name"],
            version=target_version,
        ).info(f"从市场安装插件: {plugin_meta['name']}@{target_version}")

        return {
            "status": "success",
            "message": f"插件 {plugin_meta['name']}@{target_version} 安装成功",
            "plugin_id": new_plugin.id,
            "version": target_version,
        }
    except HTTPException:
        raise
    except Exception as exc:
        download_log.status = "failed"
        download_log.error_message = str(exc)
        download_log.duration_ms = int((time.time() - started_at) * 1000)
        db.commit()
        logger.error(f"插件安装异常: {exc}")
        raise HTTPException(status_code=500, detail="插件安装失败，请稍后重试")


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


# ── 版本管理 API ──────────────────────────────────────────


@router.get(
    "/plugins/{plugin_id}/versions",
    response_model=PluginVersionListResponse,
    summary="获取插件版本列表",
    description="获取指定插件的所有已发布版本。",
)
async def list_plugin_versions(
    plugin_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """获取插件的所有版本记录"""
    versions = db.query(PluginVersion).filter(
        PluginVersion.plugin_id == plugin_id,
        PluginVersion.is_published == True,  # noqa: E712
    ).order_by(PluginVersion.published_at.desc()).all()

    return {
        "plugin_id": plugin_id,
        "versions": versions,
        "total": len(versions),
    }


@router.get(
    "/plugins/{plugin_id}/versions/{version}",
    response_model=PluginVersionResponse,
    summary="获取指定版本详情",
)
async def get_plugin_version_detail(
    plugin_id: str,
    version: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """获取插件指定版本的详情"""
    version_record = db.query(PluginVersion).filter(
        PluginVersion.plugin_id == plugin_id,
        PluginVersion.version == version,
    ).first()
    if not version_record:
        raise HTTPException(status_code=404, detail="版本不存在")
    return version_record


@router.get(
    "/plugins/{plugin_id}/update-check",
    response_model=PluginUpdateCheckResponse,
    summary="检查插件更新",
    description="检查已安装插件是否有可用更新。",
)
async def check_plugin_update(
    plugin_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """检查插件是否有可用更新"""
    # 从市场注册表获取插件信息
    plugin_meta = marketplace_registry.get_plugin(plugin_id)
    if not plugin_meta:
        raise HTTPException(status_code=404, detail="市场中不存在该插件")

    # 查询已安装版本
    installed = db.query(Plugin).filter(Plugin.name == plugin_meta["name"]).first()
    current_version = installed.version if installed else plugin_meta.get("version", "1.0.0")

    # 查询最新版本
    latest = db.query(PluginVersion).filter(
        PluginVersion.plugin_id == plugin_id,
        PluginVersion.is_published == True,  # noqa: E712
    ).order_by(PluginVersion.published_at.desc()).first()

    if not latest:
        return {
            "has_update": False,
            "current_version": current_version,
            "latest_version": None,
            "latest_changelog": None,
        }

    has_update = version_manager.compare_versions(latest.version, current_version) > 0
    return {
        "has_update": has_update,
        "current_version": current_version,
        "latest_version": latest.version,
        "latest_changelog": latest.changelog if has_update else None,
    }


@router.post(
    "/plugins/{plugin_id}/upgrade",
    response_model=PluginUpgradeResponse,
    summary="升级插件",
    description="将已安装插件升级到指定版本。",
)
async def upgrade_plugin(
    plugin_id: str,
    payload: PluginUpgradeRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """升级已安装插件到目标版本"""
    plugin_meta = marketplace_registry.get_plugin(plugin_id)
    if not plugin_meta:
        raise HTTPException(status_code=404, detail="市场中不存在该插件")

    # 查询已安装插件
    installed = db.query(Plugin).filter(Plugin.name == plugin_meta["name"]).first()
    if not installed:
        raise HTTPException(status_code=400, detail="插件未安装，无法升级")

    previous_version = installed.version

    # 校验目标版本存在
    target_version_record = db.query(PluginVersion).filter(
        PluginVersion.plugin_id == plugin_id,
        PluginVersion.version == payload.target_version,
    ).first()
    if not target_version_record:
        raise HTTPException(status_code=404, detail=f"目标版本 {payload.target_version} 不存在")

    # 校验版本号确实为升级
    if not version_manager.validate_version_bump(previous_version, payload.target_version):
        raise HTTPException(
            status_code=400,
            detail=f"目标版本 {payload.target_version} 不高于当前版本 {previous_version}",
        )

    # 执行升级（更新版本号）
    installed.version = payload.target_version
    db.commit()

    logger.bind(
        event="marketplace_upgrade",
        module="marketplace",
        plugin_id=plugin_id,
        previous_version=previous_version,
        current_version=payload.target_version,
    ).info(f"插件升级: {plugin_meta['name']} {previous_version} -> {payload.target_version}")

    return {
        "success": True,
        "plugin_id": plugin_id,
        "previous_version": previous_version,
        "current_version": payload.target_version,
        "message": f"插件已从 {previous_version} 升级到 {payload.target_version}",
    }


# ── 社区功能 API ──────────────────────────────────────────


@router.post(
    "/plugins/{plugin_id}/rate",
    response_model=PluginRatingSummaryResponse,
    summary="为插件评分",
    description="创建或更新当前用户对插件的评分（1-5 星）。",
)
async def rate_plugin(
    plugin_id: str,
    payload: PluginRatingCreate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """创建或更新用户评分"""
    plugin_meta = marketplace_registry.get_plugin(plugin_id)
    if not plugin_meta:
        raise HTTPException(status_code=404, detail="市场中不存在该插件")

    user_id = str(current_user.id)

    # 检查是否已有评分
    existing = db.query(PluginRating).filter(
        PluginRating.plugin_id == plugin_id,
        PluginRating.user_id == user_id,
    ).first()

    if existing:
        existing.score = payload.score
        existing.updated_at = datetime.now(timezone.utc)
    else:
        rating = PluginRating(
            plugin_id=plugin_id,
            user_id=user_id,
            score=payload.score,
        )
        db.add(rating)
    db.commit()

    # 返回汇总：使用 SQL 聚合避免全量加载到 Python 端
    from sqlalchemy import func as _func

    total_row = (
        db.query(_func.count(PluginRating.id).label("cnt"))
        .filter(PluginRating.plugin_id == plugin_id)
        .scalar()
    )
    total = int(total_row or 0)
    avg_row = (
        db.query(_func.avg(PluginRating.score).label("avg"))
        .filter(PluginRating.plugin_id == plugin_id)
        .scalar()
    )
    avg = float(avg_row) if avg_row is not None else 0.0

    # 评分分布：单次 GROUP BY 查询
    dist_rows = (
        db.query(
            PluginRating.score.label("score"),
            _func.count(PluginRating.id).label("cnt"),
        )
        .filter(PluginRating.plugin_id == plugin_id)
        .group_by(PluginRating.score)
        .all()
    )
    distribution: Dict[int, int] = {i: 0 for i in range(1, 6)}
    for row in dist_rows:
        if row.score in distribution:
            distribution[row.score] = int(row.cnt)

    return {
        "plugin_id": plugin_id,
        "average_score": round(avg, 2),
        "total_count": total,
        "distribution": distribution,
        "user_score": payload.score,
    }


@router.get(
    "/plugins/{plugin_id}/rating",
    response_model=PluginRatingSummaryResponse,
    summary="获取插件评分汇总",
)
async def get_plugin_rating(
    plugin_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """获取插件评分汇总信息"""
    # 使用 SQL 聚合避免全量加载评分记录
    from sqlalchemy import func as _func

    total_row = (
        db.query(_func.count(PluginRating.id).label("cnt"))
        .filter(PluginRating.plugin_id == plugin_id)
        .scalar()
    )
    total = int(total_row or 0)
    avg_row = (
        db.query(_func.avg(PluginRating.score).label("avg"))
        .filter(PluginRating.plugin_id == plugin_id)
        .scalar()
    )
    avg = float(avg_row) if avg_row is not None else 0.0

    dist_rows = (
        db.query(
            PluginRating.score.label("score"),
            _func.count(PluginRating.id).label("cnt"),
        )
        .filter(PluginRating.plugin_id == plugin_id)
        .group_by(PluginRating.score)
        .all()
    )
    distribution: Dict[int, int] = {i: 0 for i in range(1, 6)}
    for row in dist_rows:
        if row.score in distribution:
            distribution[row.score] = int(row.cnt)

    # 当前用户评分
    user_rating = db.query(PluginRating).filter(
        PluginRating.plugin_id == plugin_id,
        PluginRating.user_id == str(current_user.id),
    ).first()

    return {
        "plugin_id": plugin_id,
        "average_score": round(avg, 2),
        "total_count": total,
        "distribution": distribution,
        "user_score": user_rating.score if user_rating else None,
    }


@router.post(
    "/plugins/{plugin_id}/reviews",
    response_model=PluginReviewResponse,
    summary="发表插件评论",
    description="对插件发表评论，可附带评分。",
)
async def create_plugin_review(
    plugin_id: str,
    payload: PluginReviewCreate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """创建插件评论"""
    plugin_meta = marketplace_registry.get_plugin(plugin_id)
    if not plugin_meta:
        raise HTTPException(status_code=404, detail="市场中不存在该插件")

    user_id = str(current_user.id)
    username = getattr(current_user, "username", "") or ""

    # 若附带评分，同步更新评分表
    if payload.rating is not None:
        existing_rating = db.query(PluginRating).filter(
            PluginRating.plugin_id == plugin_id,
            PluginRating.user_id == user_id,
        ).first()
        if existing_rating:
            existing_rating.score = payload.rating
            existing_rating.updated_at = datetime.now(timezone.utc)
        else:
            db.add(PluginRating(
                plugin_id=plugin_id,
                user_id=user_id,
                score=payload.rating,
            ))

    review = PluginReview(
        plugin_id=plugin_id,
        user_id=user_id,
        username=username,
        content=payload.content.strip(),
        rating=payload.rating,
    )
    db.add(review)
    db.commit()
    db.refresh(review)

    logger.info(
        f"创建插件评论: plugin={plugin_id}, user={user_id}, review_id={review.id}"
    )
    return review


@router.get(
    "/plugins/{plugin_id}/reviews",
    response_model=PluginReviewListResponse,
    summary="获取插件评论列表",
)
async def list_plugin_reviews(
    plugin_id: str,
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页数量"),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """分页获取插件评论列表"""
    query = db.query(PluginReview).filter(
        PluginReview.plugin_id == plugin_id,
        PluginReview.is_hidden == False,  # noqa: E712
    )
    total = query.count()
    reviews = query.order_by(PluginReview.created_at.desc()).offset(
        (page - 1) * page_size
    ).limit(page_size).all()

    return {
        "plugin_id": plugin_id,
        "reviews": reviews,
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.put(
    "/reviews/{review_id}",
    response_model=PluginReviewResponse,
    summary="更新评论",
)
async def update_plugin_review(
    review_id: int,
    payload: PluginReviewUpdate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """更新评论内容或评分（仅作者可操作）"""
    review = db.query(PluginReview).filter(PluginReview.id == review_id).first()
    if not review:
        raise HTTPException(status_code=404, detail="评论不存在")
    if review.user_id != str(current_user.id):
        raise HTTPException(status_code=403, detail="无权修改他人评论")

    if payload.content is not None:
        review.content = payload.content.strip()
    if payload.rating is not None:
        review.rating = payload.rating
        # 同步更新评分表
        existing_rating = db.query(PluginRating).filter(
            PluginRating.plugin_id == review.plugin_id,
            PluginRating.user_id == review.user_id,
        ).first()
        if existing_rating:
            existing_rating.score = payload.rating
            existing_rating.updated_at = datetime.now(timezone.utc)

    review.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(review)
    return review


@router.delete(
    "/reviews/{review_id}",
    summary="删除评论",
)
async def delete_plugin_review(
    review_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """删除评论（作者或管理员可操作）"""
    review = db.query(PluginReview).filter(PluginReview.id == review_id).first()
    if not review:
        raise HTTPException(status_code=404, detail="评论不存在")

    # 简单权限检查：作者或 is_admin 标记
    is_admin = getattr(current_user, "is_admin", False) or getattr(current_user, "is_superuser", False)
    if not is_admin and review.user_id != str(current_user.id):
        raise HTTPException(status_code=403, detail="无权删除他人评论")

    db.delete(review)
    db.commit()
    return {"success": True, "review_id": review_id}
