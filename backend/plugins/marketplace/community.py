"""
插件市场社区功能模块。

提供评分聚合、评论管理功能。
"""
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from loguru import logger
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import PluginRating, PluginReview


# 评分范围常量
MIN_RATING_SCORE = 1
MAX_RATING_SCORE = 5
DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100


class CommunityError(Exception):
    """社区功能基础异常。"""


class InvalidRatingError(CommunityError):
    """评分值不合法。"""


class ReviewNotFoundError(CommunityError):
    """评论不存在。"""


class DuplicateReviewError(CommunityError):
    """重复评论（同一用户对同一插件多次评论需要更新而非新建）。"""


def validate_rating_score(score: int) -> None:
    """校验评分值是否在合法范围内。"""
    if not isinstance(score, int) or score < MIN_RATING_SCORE or score > MAX_RATING_SCORE:
        raise InvalidRatingError(
            f"评分必须在 {MIN_RATING_SCORE}-{MAX_RATING_SCORE} 之间，当前值: {score}"
        )


async def upsert_rating(
    db: AsyncSession,
    plugin_id: str,
    user_id: str,
    score: int,
) -> PluginRating:
    """
    创建或更新用户对插件的评分。

    每个用户对每个插件仅保留一条评分记录。
    """
    validate_rating_score(score)

    # 查找现有评分
    stmt = select(PluginRating).where(
        PluginRating.plugin_id == plugin_id,
        PluginRating.user_id == user_id,
    )
    result = await db.execute(stmt)
    existing = result.scalars().first()

    if existing:
        existing.score = score
        existing.updated_at = datetime.now(timezone.utc)
        await db.flush()
        logger.info(
            f"更新插件评分: plugin={plugin_id}, user={user_id}, score={score}"
        )
        return existing

    rating = PluginRating(
        plugin_id=plugin_id,
        user_id=user_id,
        score=score,
    )
    db.add(rating)
    await db.flush()
    logger.info(
        f"创建插件评分: plugin={plugin_id}, user={user_id}, score={score}"
    )
    return rating


async def get_rating_summary(
    db: AsyncSession,
    plugin_id: str,
) -> Dict[str, object]:
    """
    获取插件的评分汇总信息。

    Returns:
        包含 average_score、total_count、distribution 的字典
    """
    # 平均分与总数
    avg_stmt = select(
        func.avg(PluginRating.score).label("average"),
        func.count(PluginRating.id).label("total"),
    ).where(PluginRating.plugin_id == plugin_id)
    avg_result = await db.execute(avg_stmt)
    avg_row = avg_result.one()

    # 分布统计
    dist_stmt = (
        select(PluginRating.score, func.count(PluginRating.id))
        .where(PluginRating.plugin_id == plugin_id)
        .group_by(PluginRating.score)
    )
    dist_result = await db.execute(dist_stmt)
    distribution: Dict[int, int] = {i: 0 for i in range(MIN_RATING_SCORE, MAX_RATING_SCORE + 1)}
    for score, count in dist_result.all():
        distribution[score] = count

    return {
        "average_score": round(float(avg_row.average), 2) if avg_row.average else 0.0,
        "total_count": int(avg_row.total),
        "distribution": distribution,
    }


async def get_user_rating(
    db: AsyncSession,
    plugin_id: str,
    user_id: str,
) -> Optional[int]:
    """获取用户对指定插件的评分。"""
    stmt = select(PluginRating.score).where(
        PluginRating.plugin_id == plugin_id,
        PluginRating.user_id == user_id,
    )
    result = await db.execute(stmt)
    row = result.first()
    return row[0] if row else None


async def create_review(
    db: AsyncSession,
    plugin_id: str,
    user_id: str,
    username: str,
    content: str,
    rating: Optional[int] = None,
) -> PluginReview:
    """
    创建插件评论。

    Args:
        rating: 可选评分（1-5），若提供则同时更新评分表
    """
    if not content or not content.strip():
        raise CommunityError("评论内容不能为空")
    if len(content) > 2000:
        raise CommunityError("评论内容不能超过 2000 字符")

    if rating is not None:
        validate_rating_score(rating)
        # 同步更新评分
        await upsert_rating(db, plugin_id, user_id, rating)

    review = PluginReview(
        plugin_id=plugin_id,
        user_id=user_id,
        username=username or "",
        content=content.strip(),
        rating=rating,
    )
    db.add(review)
    await db.flush()
    logger.info(
        f"创建插件评论: plugin={plugin_id}, user={user_id}, review_id={review.id}"
    )
    return review


async def update_review(
    db: AsyncSession,
    review_id: int,
    user_id: str,
    content: Optional[str] = None,
    rating: Optional[int] = None,
) -> PluginReview:
    """更新评论内容或评分（仅作者可操作）。"""
    stmt = select(PluginReview).where(PluginReview.id == review_id)
    result = await db.execute(stmt)
    review = result.scalars().first()
    if not review:
        raise ReviewNotFoundError(f"评论不存在: {review_id}")
    if review.user_id != user_id:
        raise CommunityError("无权修改他人评论")

    if content is not None:
        if not content.strip():
            raise CommunityError("评论内容不能为空")
        if len(content) > 2000:
            raise CommunityError("评论内容不能超过 2000 字符")
        review.content = content.strip()

    if rating is not None:
        validate_rating_score(rating)
        review.rating = rating
        # 同步更新评分表
        await upsert_rating(db, review.plugin_id, user_id, rating)

    review.updated_at = datetime.now(timezone.utc)
    await db.flush()
    return review


async def delete_review(
    db: AsyncSession,
    review_id: int,
    user_id: str,
    is_admin: bool = False,
) -> None:
    """删除评论（作者或管理员可操作）。"""
    stmt = select(PluginReview).where(PluginReview.id == review_id)
    result = await db.execute(stmt)
    review = result.scalars().first()
    if not review:
        raise ReviewNotFoundError(f"评论不存在: {review_id}")
    if not is_admin and review.user_id != user_id:
        raise CommunityError("无权删除他人评论")

    await db.delete(review)
    await db.flush()
    logger.info(f"删除插件评论: review_id={review_id}, user={user_id}")


async def list_reviews(
    db: AsyncSession,
    plugin_id: str,
    page: int = 1,
    page_size: int = DEFAULT_PAGE_SIZE,
) -> Tuple[List[PluginReview], int]:
    """
    分页获取插件评论列表。

    Returns:
        (评论列表, 总数)
    """
    page = max(1, page)
    page_size = max(1, min(page_size, MAX_PAGE_SIZE))

    # 总数
    count_stmt = select(func.count(PluginReview.id)).where(
        PluginReview.plugin_id == plugin_id,
        PluginReview.is_hidden == False,  # noqa: E712
    )
    count_result = await db.execute(count_stmt)
    total = int(count_result.scalar() or 0)

    # 分页查询
    stmt = (
        select(PluginReview)
        .where(
            PluginReview.plugin_id == plugin_id,
            PluginReview.is_hidden == False,  # noqa: E712
        )
        .order_by(PluginReview.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    result = await db.execute(stmt)
    reviews = list(result.scalars().all())
    return reviews, total
