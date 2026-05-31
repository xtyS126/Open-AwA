# -*- coding: utf-8 -*-
"""
Twitter API 调用封装模块

功能概述:
    - 封装 TwitterApi.io 的所有API调用
    - 提供获取用户推文、搜索用户、获取用户信息等功能
    - 处理API认证和错误响应

API认证:
    - 所有请求需要在HTTP头中添加 x-api-key
    - API密钥从配置文件或初始化时传入

注意事项:
    - API有调用频率限制，请合理设置检查间隔
    - 部分API返回的数据量较大，请根据需要设置limit参数
"""

import requests
import json
from typing import List, Dict, Optional


class TwitterAPI:
    """
    Twitter API 客户端类
    
    用于与 TwitterApi.io 进行交互，提供推文获取、用户搜索等功能。
    
    使用方法:
        api = TwitterAPI("your_api_key_here")
        result = api.get_user_last_tweets("elonmusk")
    """
    
    BASE_URL = "https://api.twitterapi.io/twitter"
    
    def __init__(self, api_key: str):
        """
        初始化Twitter API客户端
        
        参数:
            api_key: TwitterApi.io的API密钥
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
        """
        获取指定用户的最新推文
        
        功能说明:
            根据用户名或用户ID获取该用户最近发布的推文。
            返回的推文按创建时间排序，最新的排在前面。
            每次最多返回limit条推文。
        
        参数:
            user_name: Twitter用户名（屏幕名称），例如 "elonmusk"
            user_id: Twitter用户ID（推荐使用，更稳定）
            include_replies: 是否包含回复推文，默认False
            limit: 最多返回的推文数量，默认20条
        
        返回字典格式:
            {
                "success": True/False,      # 请求是否成功
                "tweets": [...],            # 推文列表
                "has_next_page": True/False, # 是否有更多数据
                "error": "错误信息"         # 仅在失败时存在
            }
        
        推文字典格式:
            {
                "id": "推文ID",
                "text": "推文内容",
                "author": {用户信息},
                "createdAt": "创建时间",
                "likeCount": 点赞数,
                "retweetCount": 转发数,
                "replyCount": 回复数
            }
        
        使用示例:
            result = api.get_user_last_tweets(user_name="elonmusk", limit=10)
            if result["success"]:
                for tweet in result["tweets"]:
                    print(tweet["text"])
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
        """
        通过关键词搜索用户
        
        功能说明:
            根据关键词搜索Twitter用户，返回匹配的用户列表。
            搜索会匹配用户名、显示名称和个人简介。
        
        参数:
            query: 搜索关键词，例如 "AI" 或 "Elon"
        
        返回字典格式:
            {
                "success": True/False,
                "users": [...],              # 用户列表
                "has_next_page": True/False,
                "error": "错误信息"
            }
        
        用户字典格式:
            {
                "id": "用户ID",
                "userName": "用户名",
                "name": "显示名称",
                "description": "个人简介",
                "followers": 粉丝数,
                "following": 关注数,
                "profilePicture": "头像URL"
            }
        
        使用示例:
            result = api.search_users("AI researcher")
            if result["success"]:
                for user in result["users"]:
                    print(f"@{user['userName']}: {user['name']}")
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
        """
        获取指定用户的详细信息
        
        功能说明:
            通过用户名获取用户的详细信息。
            内部使用search_users API，返回第一个匹配结果。
        
        参数:
            user_name: Twitter用户名
        
        返回字典格式:
            {
                "success": True/False,
                "user": {用户信息} 或 None,
                "error": "错误信息"
            }
        
        使用示例:
            result = api.get_user_info("elonmusk")
            if result["success"]:
                user = result["user"]
                print(f"粉丝数: {user['followers']}")
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
