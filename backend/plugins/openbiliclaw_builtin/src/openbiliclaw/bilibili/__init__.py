"""Bilibili 包 —— API 与浏览器访问层。"""

from .api import (
    BilibiliAPIClient,
    BilibiliAPIError,
    BilibiliAuthExpiredError,
    CommentInfo,
    FavoriteFolder,
    FavoriteFolderWithItems,
    FollowingUser,
    NavInfo,
    VideoInfo,
)
from .auth import AuthManager, AuthStatus

__all__ = [
    "AuthManager",
    "AuthStatus",
    "BilibiliAPIClient",
    "BilibiliAPIError",
    "BilibiliAuthExpiredError",
    "CommentInfo",
    "FavoriteFolder",
    "FavoriteFolderWithItems",
    "FollowingUser",
    "NavInfo",
    "VideoInfo",
]
