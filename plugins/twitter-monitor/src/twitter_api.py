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
        self.api_key = api_key
        self.headers = {"X-API-Key": api_key}

    def get_user_last_tweets(
        self,
        user_name: str = None,
        user_id: str = None,
        include_replies: bool = False,
        limit: int = 20
    ) -> Dict:
        url = f"{self.BASE_URL}/user/last_tweets"

        params = {
            "includeReplies": str(include_replies).lower()
        }

        if user_id:
            params["userId"] = user_id
        elif user_name:
            params["userName"] = user_name

        try:
            response = requests.get(url, headers=self.headers, params=params, timeout=30)
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
        url = f"{self.BASE_URL}/user/search"
        params = {"query": query}

        try:
            response = requests.get(url, headers=self.headers, params=params, timeout=30)
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
        url = f"{self.BASE_URL}/user/search"
        params = {"query": user_name}

        try:
            response = requests.get(url, headers=self.headers, params=params, timeout=30)
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
