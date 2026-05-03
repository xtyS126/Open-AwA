import requests
import json
from typing import Any, Dict, List, Optional


class TwitterAPI:
    """TwitterApi.io API 客户端封装

    基于文档集 https://docs.twitterapi.io 封装全部监控场景相关的读取端点。
    基址: https://api.twitterapi.io/twitter
    认证: X-API-Key Header
    """

    BASE_URL = "https://api.twitterapi.io/twitter"
    DEFAULT_TIMEOUT = 30

    def __init__(self, api_key: str):
        """初始化 Twitter API 客户端

        参数:
            api_key: TwitterApi.io 的 API 密钥
        """
        self.api_key = api_key
        self.headers = {"X-API-Key": api_key}

    def _make_request(self, endpoint: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """统一的 HTTP GET 请求辅助方法

        处理请求发送、状态检查、JSON 解析和异常捕获。
        所有 API 方法应通过此方法发送请求以避免重复代码。

        参数:
            endpoint: API 端点路径（相对路径，如 "user/info"）
            params: 查询参数字典

        返回:
            原始 API 响应的 JSON 字典，或包含 error 信息的字典
        """
        url = f"{self.BASE_URL}/{endpoint.lstrip('/')}"
        request_params = params or {}

        try:
            response = requests.get(
                url,
                headers=self.headers,
                params=request_params,
                timeout=self.DEFAULT_TIMEOUT,
            )
            response.raise_for_status()
            return response.json()
        except requests.exceptions.Timeout:
            return {"status": "error", "msg": "Twitter API 请求超时"}
        except requests.exceptions.ConnectionError as e:
            return {"status": "error", "msg": f"Twitter API 连接错误: {e}"}
        except requests.exceptions.RequestException as e:
            return {"status": "error", "msg": f"Twitter API 请求失败: {e}"}
        except json.JSONDecodeError:
            return {"status": "error", "msg": "Twitter API 响应解析失败"}

    # ==================== 用户相关端点 ====================

    def get_user_last_tweets(
        self,
        user_name: Optional[str] = None,
        user_id: Optional[str] = None,
        include_replies: bool = False,
        limit: int = 20,
    ) -> Dict[str, Any]:
        """获取用户最近推文

        使用 GET /twitter/user/last_tweets 端点。
        按 user_name 或 user_id 查询，返回最近发布的推文列表。

        参数:
            user_name: Twitter 用户名（不含 @）
            user_id: Twitter 用户 ID
            include_replies: 是否包含回复推文
            limit: 最多返回多少条推文（客户端截断）

        返回:
            {"success": True, "tweets": [...], "has_next_page": bool}
            或 {"success": False, "error": "..."}
        """
        params: Dict[str, str] = {
            "includeReplies": str(include_replies).lower(),
        }
        if user_id:
            params["userId"] = user_id
        elif user_name:
            params["userName"] = str(user_name).strip().lstrip("@")

        data = self._make_request("user/last_tweets", params)
        if data.get("status") == "success":
            tweets = data.get("data", {}).get("tweets", [])[:limit]
            return {
                "success": True,
                "tweets": tweets,
                "has_next_page": data.get("data", {}).get("has_next_page", False),
            }
        return {"success": False, "error": data.get("msg", "未知错误")}

    def search_users(self, query: str) -> Dict[str, Any]:
        """按关键词搜索 Twitter 用户

        使用 GET /twitter/user/search 端点。

        参数:
            query: 搜索关键词

        返回:
            {"success": True, "users": [...], "has_next_page": bool}
            或 {"success": False, "error": "..."}
        """
        params = {"query": query}
        data = self._make_request("user/search", params)
        if data.get("status") == "success":
            return {
                "success": True,
                "users": data.get("data", {}).get("users", []),
                "has_next_page": data.get("data", {}).get("has_next_page", False),
            }
        return {"success": False, "error": data.get("msg", "未知错误")}

    def get_user_info(self, user_name: str) -> Dict[str, Any]:
        """获取用户详细信息（专用端点）

        使用 GET /twitter/user/info 端点，直接返回完整用户资料。
        相比 search_users 方式更高效且返回字段更完整。

        参数:
            user_name: Twitter 用户名（不含 @）

        返回:
            {"success": True, "user": {...}}
            或 {"success": False, "error": "..."}
        """
        params = {"userName": str(user_name).strip().lstrip("@")}
        data = self._make_request("user/info", params)
        if data.get("status") == "success":
            return {"success": True, "user": data.get("data", {})}
        return {"success": False, "error": data.get("msg", "未知错误")}

    # ==================== 时间线端点 ====================

    def get_user_timeline(
        self,
        user_id: str,
        include_replies: bool = False,
        include_parent_tweet: bool = False,
        cursor: str = "",
    ) -> Dict[str, Any]:
        """获取用户完整时间线（带分页）

        使用 GET /twitter/user/tweet_timeline 端点。
        按 user_id 查询，每页最多返回 20 条推文，结果按时间降序排列。

        参数:
            user_id: Twitter 用户 ID（必填）
            include_replies: 是否包含回复推文
            include_parent_tweet: 推文为回复时是否包含父推文
            cursor: 分页游标，首次请求传空字符串

        返回:
            {"success": True, "tweets": [...], "has_next_page": bool, "next_cursor": str}
            或 {"success": False, "error": "..."}
        """
        params: Dict[str, Any] = {
            "userId": user_id,
            "includeReplies": str(include_replies).lower(),
            "includeParentTweet": str(include_parent_tweet).lower(),
        }
        if cursor:
            params["cursor"] = cursor

        data = self._make_request("user/tweet_timeline", params)
        if data.get("status") == "success":
            return {
                "success": True,
                "tweets": data.get("tweets", []),
                "has_next_page": data.get("has_next_page", False),
                "next_cursor": data.get("next_cursor", ""),
            }
        return {"success": False, "error": data.get("msg", "未知错误")}

    # ==================== 推文端点 ====================

    def search_tweets(
        self,
        query: str,
        query_type: str = "Latest",
        cursor: str = "",
    ) -> Dict[str, Any]:
        """高级推文搜索

        使用 GET /twitter/tweet/advanced_search 端点。
        支持 Twitter 高级搜索语法，每页最多返回 20 条推文。
        注意：Twitter 分页存在问题，建议使用 since_time/until_time 替代分页游标。

        参数:
            query: 搜索查询（支持 from:user、关键词、since_time 等语法）
            query_type: 搜索类型，可选 "Latest" 或 "Top"，默认 "Latest"
            cursor: 分页游标

        返回:
            {"success": True, "tweets": [...], "has_next_page": bool, "next_cursor": str}
            或 {"success": False, "error": "..."}
        """
        params: Dict[str, str] = {
            "query": query,
            "queryType": query_type,
        }
        if cursor:
            params["cursor"] = cursor

        data = self._make_request("tweet/advanced_search", params)
        if data.get("status") == "success":
            return {
                "success": True,
                "tweets": data.get("tweets", []),
                "has_next_page": data.get("has_next_page", False),
                "next_cursor": data.get("next_cursor", ""),
            }
        return {"success": False, "error": data.get("msg", "未知错误")}

    def get_tweet_replies(
        self,
        tweet_id: str,
        since_time: Optional[int] = None,
        until_time: Optional[int] = None,
        cursor: str = "",
    ) -> Dict[str, Any]:
        """获取推文回复

        使用 GET /twitter/tweet/replies 端点。
        按 tweet_id 获取回复，每页最多返回 20 条，按回复时间降序排列。
        注意：仅支持查询原始推文（非回复推文）的回复。

        参数:
            tweet_id: 要查询回复的推文 ID（必填）
            since_time: 起始 Unix 时间戳（秒）
            until_time: 截止 Unix 时间戳（秒）
            cursor: 分页游标

        返回:
            {"success": True, "replies": [...], "has_next_page": bool, "next_cursor": str}
            或 {"success": False, "error": "..."}
        """
        params: Dict[str, Any] = {"tweetId": tweet_id}
        if since_time is not None:
            params["sinceTime"] = since_time
        if until_time is not None:
            params["untilTime"] = until_time
        if cursor:
            params["cursor"] = cursor

        data = self._make_request("tweet/replies", params)
        if data.get("status") == "success":
            return {
                "success": True,
                "replies": data.get("replies", []),
                "has_next_page": data.get("has_next_page", False),
                "next_cursor": data.get("next_cursor", ""),
            }
        return {"success": False, "error": data.get("msg", "未知错误")}

    def get_tweets_by_ids(self, tweet_ids: List[str]) -> Dict[str, Any]:
        """按推文 ID 批量获取推文详情

        使用 GET /twitter/tweets 端点。

        参数:
            tweet_ids: 推文 ID 列表

        返回:
            {"success": True, "tweets": [...]}
            或 {"success": False, "error": "..."}
        """
        params = {"tweet_ids": ",".join(tweet_ids)}
        data = self._make_request("tweets", params)
        if data.get("status") == "success":
            return {
                "success": True,
                "tweets": data.get("tweets", []),
            }
        return {"success": False, "error": data.get("msg", "未知错误")}

    # ==================== 社交关系端点 ====================

    def get_user_followers(
        self,
        user_name: str,
        cursor: str = "",
        page_size: int = 200,
    ) -> Dict[str, Any]:
        """获取用户粉丝列表

        使用 GET /twitter/user/followers 端点。
        按关注时间倒序排列，最新关注的粉丝出现在第一页。
        每页最多返回 200 条。

        参数:
            user_name: Twitter 用户名（不含 @，必填）
            cursor: 分页游标
            page_size: 每页返回数量（20~200，默认 200）

        返回:
            {"success": True, "followers": [...], "has_next_page": bool, "next_cursor": str}
            或 {"success": False, "error": "..."}
        """
        page_size = max(20, min(page_size, 200))
        params: Dict[str, Any] = {
            "userName": str(user_name).strip().lstrip("@"),
            "pageSize": page_size,
        }
        if cursor:
            params["cursor"] = cursor

        data = self._make_request("user/followers", params)
        if data.get("status") == "success":
            followers = data.get("followers", [])
            return {
                "success": True,
                "followers": followers,
                "has_next_page": len(followers) >= page_size,
                "next_cursor": data.get("next_cursor", ""),
            }
        return {"success": False, "error": data.get("msg", "未知错误")}

    def get_user_followings(
        self,
        user_name: str,
        cursor: str = "",
        page_size: int = 200,
    ) -> Dict[str, Any]:
        """获取用户关注的列表

        使用 GET /twitter/user/followings 端点。
        按关注时间倒序排列，最新关注的用户出现在第一页。
        每页最多返回 200 条。

        参数:
            user_name: Twitter 用户名（不含 @，必填）
            cursor: 分页游标
            page_size: 每页返回数量（20~200，默认 200）

        返回:
            {"success": True, "followings": [...], "has_next_page": bool, "next_cursor": str}
            或 {"success": False, "error": "..."}
        """
        page_size = max(20, min(page_size, 200))
        params: Dict[str, Any] = {
            "userName": str(user_name).strip().lstrip("@"),
            "pageSize": page_size,
        }
        if cursor:
            params["cursor"] = cursor

        data = self._make_request("user/followings", params)
        if data.get("status") == "success":
            followings = data.get("followings", [])
            return {
                "success": True,
                "followings": followings,
                "has_next_page": len(followings) >= page_size,
                "next_cursor": data.get("next_cursor", ""),
            }
        return {"success": False, "error": data.get("msg", "未知错误")}
