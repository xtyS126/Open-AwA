import requests
import json
from typing import List, Dict, Optional


class TwitterAPI:
    """TwitterApi.io API 客户端封装

    提供获取用户推文、搜索用户、获取用户信息等功能。
    API 文档: https://twitterapi.io/docs
    """

    BASE_URL = "https://api.twitterapi.io/twitter"

    def __init__(self, api_key: str):
        """初始化 Twitter API 客户端

        参数:
            api_key: TwitterApi.io 的 API 密钥
        """
        self.api_key = api_key
        self.headers = {"X-API-Key": api_key}

    def get_user_last_tweets(
        self,
        user_name: str = None,
        user_id: str = None,
        include_replies: bool = False,
        limit: int = 20
    ) -> Dict:
        """获取指定用户的最新推文

        参数:
            user_name: Twitter 用户名，例如 "elonmusk"
            user_id: Twitter 用户 ID（推荐使用，更稳定）
            include_replies: 是否包含回复推文，默认 False
            limit: 最多返回的推文数量

        返回:
            包含 success/tweets/has_next_page/error 的字典
        """
        url = f"{self.BASE_URL}/user/last_tweets"

        params = {
            "includeReplies": str(include_replies).lower()
        }

        if user_id:
            params["userId"] = user_id
        elif user_name:
            params["userName"] = user_name

        try:
            response = requests.get(url, headers=self.headers, params=params)
            response.raise_for_status()
            data = response.json()

            if data.get("status") == "success":
                tweets = data.get("data", {}).get("tweets", [])[:limit]
                return {
                    "success": True,
                    "tweets": tweets,
                    "has_next_page": data.get("data", {}).get("has_next_page", False)
                }
            else:
                return {
                    "success": False,
                    "error": data.get("msg", "Unknown error"),
                    "tweets": []
                }
        except requests.exceptions.RequestException as e:
            return {
                "success": False,
                "error": str(e),
                "tweets": []
            }
        except json.JSONDecodeError:
            return {
                "success": False,
                "error": "Failed to parse response",
                "tweets": []
            }

    def search_users(self, query: str) -> Dict:
        """通过关键词搜索 Twitter 用户

        参数:
            query: 搜索关键词，例如 "AI" 或 "Elon"

        返回:
            包含 success/users/has_next_page/error 的字典
        """
        url = f"{self.BASE_URL}/user/search"
        params = {"query": query}

        try:
            response = requests.get(url, headers=self.headers, params=params)
            response.raise_for_status()
            data = response.json()

            if data.get("status") == "success":
                return {
                    "success": True,
                    "users": data.get("data", {}).get("users", []),
                    "has_next_page": data.get("data", {}).get("has_next_page", False)
                }
            else:
                return {
                    "success": False,
                    "error": data.get("msg", "Unknown error"),
                    "users": []
                }
        except requests.exceptions.RequestException as e:
            return {
                "success": False,
                "error": str(e),
                "users": []
            }
        except json.JSONDecodeError:
            return {
                "success": False,
                "error": "Failed to parse response",
                "users": []
            }

    def get_user_info(self, user_name: str) -> Dict:
        """获取指定用户的详细信息

        参数:
            user_name: Twitter 用户名

        返回:
            包含 success/user/error 的字典
        """
        url = f"{self.BASE_URL}/user/search"
        params = {"query": user_name}

        try:
            response = requests.get(url, headers=self.headers, params=params)
            response.raise_for_status()
            data = response.json()

            if data.get("status") == "success":
                users = data.get("data", {}).get("users", [])
                if users:
                    return {"success": True, "user": users[0]}
                return {"success": False, "error": "User not found"}
            else:
                return {"success": False, "error": data.get("msg", "Unknown error")}
        except requests.exceptions.RequestException as e:
            return {"success": False, "error": str(e)}
        except json.JSONDecodeError:
            return {"success": False, "error": "Failed to parse response"}
