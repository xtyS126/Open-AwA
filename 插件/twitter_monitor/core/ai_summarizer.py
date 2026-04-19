# -*- coding: utf-8 -*-
"""
AI推文总结器模块

功能概述:
    - 调用OpenAI兼容API进行推文总结
    - 格式化推文数据
    - 处理API调用错误
    - 支持流式输出

依赖:
    - openai库 (pip install openai)
    - 或其他兼容openai库格式的API

使用示例:
    from core.ai_summarizer import AISummarizer
    
    summarizer = AISummarizer(config)
    result = summarizer.summarize_tweets(tweets_data)
    print(result)
"""

import json
import time
from datetime import datetime
from typing import Dict, List, Optional
from pathlib import Path


class AISummarizer:
    """
    AI推文总结器类
    
    负责:
    1. 格式化推文数据
    2. 调用OpenAI兼容API
    3. 处理API响应
    4. 保存结果
    
    使用方法:
        summarizer = AISummarizer(ai_config)
        summary = summarizer.summarize_tweets(tweets)
    """
    
    def __init__(self, config: dict):
        """
        初始化总结器
        
        参数:
            config: AI配置字典，包含:
                - api_base_url: API地址
                - api_key: API密钥
                - model: 模型名称
                - temperature: 温度参数
                - max_tokens: 最大token数
                - system_prompt: 系统提示词
        """
        self.config = config
        self.api_base_url = config["api_base_url"]
        self.api_key = config["api_key"]
        self.model = config["model"]
        self.temperature = config.get("temperature", 0.7)
        self.max_tokens = config.get("max_tokens", 2000)
        self.system_prompt = config["system_prompt"]
        
        self._init_client()
    
    def _init_client(self):
        """
        初始化OpenAI客户端
        
        支持:
        - OpenAI官方API
        - 任意OpenAI兼容的第三方API
        """
        try:
            from openai import OpenAI
            self.client = OpenAI(
                api_key=self.api_key,
                base_url=self.api_base_url
            )
            self.client_initialized = True
        except ImportError:
            self.client = None
            self.client_initialized = False
            print("[警告] 未安装openai库，将使用requests直接调用API")
    
    def format_tweets(self, tweets: List[Dict]) -> str:
        """
        将推文数据格式化为易读的文本
        
        参数:
            tweets: 推文列表
            
        返回:
            格式化后的文本字符串
        """
        if not tweets:
            return "没有找到推文数据。"
        
        formatted_text = f"共有 {len(tweets)} 条推文待总结：\n\n"
        
        for i, tweet in enumerate(tweets, 1):
            author = tweet.get("author", {})
            author_name = author.get("name", "Unknown")
            author_username = author.get("userName", "unknown")
            text = tweet.get("text", "")
            created_at = tweet.get("createdAt", "")
            like_count = tweet.get("likeCount", 0)
            retweet_count = tweet.get("retweetCount", 0)
            
            formatted_text += f"--- 推文 {i} ---\n"
            formatted_text += f"作者: {author_name} (@{author_username})\n"
            formatted_text += f"时间: {created_at}\n"
            formatted_text += f"内容: {text}\n"
            formatted_text += f"点赞: {like_count} | 转发: {retweet_count}\n\n"
        
        return formatted_text
    
    def call_api(self, user_prompt: str, max_retries: int = 3) -> Dict:
        """
        调用AI API进行总结
        
        参数:
            user_prompt: 用户提示词
            max_retries: 最大重试次数
            
        返回:
            API响应字典:
            {
                "success": True/False,
                "content": "总结内容",
                "error": "错误信息"
            }
        """
        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": user_prompt}
        ]
        
        for attempt in range(max_retries):
            try:
                if self.client_initialized and self.client:
                    response = self.client.chat.completions.create(
                        model=self.model,
                        messages=messages,
                        temperature=self.temperature,
                        max_tokens=self.max_tokens
                    )
                    
                    content = response.choices[0].message.content
                    return {
                        "success": True,
                        "content": content,
                        "usage": {
                            "prompt_tokens": response.usage.prompt_tokens,
                            "completion_tokens": response.usage.completion_tokens,
                            "total_tokens": response.usage.total_tokens
                        }
                    }
                else:
                    return self._call_api_direct(messages)
                    
            except Exception as e:
                if attempt < max_retries - 1:
                    wait_time = (attempt + 1) * 2
                    print(f"[重试] API调用失败，{wait_time}秒后重试...")
                    time.sleep(wait_time)
                else:
                    return {
                        "success": False,
                        "error": str(e),
                        "content": None
                    }
        
        return {"success": False, "error": "Unknown error", "content": None}
    
    def _call_api_direct(self, messages: List[Dict]) -> Dict:
        """
        直接使用requests调用API（无需openai库）
        
        参数:
            messages: 消息列表
            
        返回:
            API响应字典
        """
        import requests
        
        url = f"{self.api_base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens
        }
        
        response = requests.post(url, headers=headers, json=payload, timeout=60)
        
        if response.status_code == 200:
            data = response.json()
            content = data["choices"][0]["message"]["content"]
            return {
                "success": True,
                "content": content,
                "usage": data.get("usage", {})
            }
        else:
            return {
                "success": False,
                "error": f"HTTP {response.status_code}: {response.text[:200]}",
                "content": None
            }
    
    def summarize_tweets(
        self, 
        tweets: List[Dict], 
        save_path: Optional[str] = None
    ) -> Dict:
        """
        总结推文
        
        参数:
            tweets: 推文列表
            save_path: 可选，保存结果的文件路径
            
        返回:
            结果字典:
            {
                "success": True/False,
                "content": "总结内容",
                "tweets_count": 推文数量,
                "saved_path": 保存路径（如果保存了）
            }
        """
        if not tweets:
            return {
                "success": False,
                "error": "没有推文数据",
                "content": None
            }
        
        print(f"[信息] 正在格式化 {len(tweets)} 条推文...")
        formatted_text = self.format_tweets(tweets)
        
        print(f"[信息] 正在调用AI进行总结...")
        result = self.call_api(formatted_text)
        
        if result["success"]:
            output = result["content"]
            
            if save_path:
                Path(save_path).parent.mkdir(parents=True, exist_ok=True)
                with open(save_path, 'w', encoding='utf-8') as f:
                    f.write(output)
                print(f"[成功] 总结已保存到: {save_path}")
            
            return {
                "success": True,
                "content": output,
                "tweets_count": len(tweets),
                "saved_path": save_path,
                "usage": result.get("usage")
            }
        else:
            return {
                "success": False,
                "error": result["error"],
                "content": None,
                "tweets_count": len(tweets)
            }
    
    def summarize_by_user(
        self, 
        tweets: List[Dict],
        save_path: Optional[str] = None
    ) -> Dict:
        """
        按用户分组总结推文
        
        参数:
            tweets: 推文列表
            save_path: 可选，保存路径
            
        返回:
            按用户分组的总结结果
        """
        if not tweets:
            return {"success": False, "error": "没有推文数据"}
        
        user_tweets = {}
        for tweet in tweets:
            username = tweet.get("author", {}).get("userName", "unknown")
            if username not in user_tweets:
                user_tweets[username] = []
            user_tweets[username].append(tweet)
        
        print(f"[信息] 发现 {len(user_tweets)} 个用户的推文")
        
        all_summaries = []
        for username, user_tweet_list in user_tweets.items():
            print(f"[信息] 正在总结 @{username} 的 {len(user_tweet_list)} 条推文...")
            
            user_prompt = f"请总结以下 @{username} 发布的推文内容：\n\n"
            user_prompt += self.format_tweets(user_tweet_list)
            
            result = self.call_api(user_prompt)
            
            if result["success"]:
                all_summaries.append(f"=== @{username} 的推文总结 ===\n\n")
                all_summaries.append(result["content"])
                all_summaries.append("\n\n")
        
        output = "".join(all_summaries)
        
        if save_path:
            Path(save_path).parent.mkdir(parents=True, exist_ok=True)
            with open(save_path, 'w', encoding='utf-8') as f:
                f.write(output)
            print(f"[成功] 总结已保存到: {save_path}")
        
        return {
            "success": True,
            "content": output,
            "tweets_count": len(tweets),
            "users_count": len(user_tweets),
            "saved_path": save_path
        }
