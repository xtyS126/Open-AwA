# -*- coding: utf-8 -*-
"""
推文数据存储模块

功能概述:
    - 提供推文数据的持久化存储
    - 支持两种存储模式:
        1. latest.json: 存储每次运行时的最新推文（会被覆盖）
        2. daily/YYYY-MM-DD.json: 按日期累积存储推文（每日一个文件）
    - 自动去重，避免重复存储相同推文
    - 支持按用户、按日期查询推文

存储结构:
    data/
    ├── latest.json           # 本次运行最新推文（每小时覆盖）
    └── daily/
        ├── 2024-01-07.json   # 1月7日的所有推文（每日增量）
        ├── 2024-01-08.json   # 1月8日的所有推文（每日增量）
        └── ...

使用示例:
    storage = TweetStorage(config)
    storage.save_latest(tweets)           # 保存最新推文
    storage.add_daily(tweets)             # 增量添加到当日文件
    all_tweets = storage.get_all_tweets()  # 获取所有推文
    stats = storage.get_stats()           # 获取统计信息
"""

import json
import os
from datetime import datetime, date
from typing import List, Dict, Set
from pathlib import Path


class TweetStorage:
    """
    推文存储管理类
    
    负责管理推文数据的读取、写入、去重和查询。
    
    核心功能:
        1. latest.json管理 - 存储/读取每次运行的最新推文
        2. daily文件管理 - 按日期累积存储推文
        3. 自动去重 - 基于推文ID避免重复存储
        4. 统计查询 - 提供推文数量、用户分布等统计
    
    使用方法:
        config = {"storage_mode": "both"}
        storage = TweetStorage(config)
        storage.save_all(new_tweets)  # 保存到所有存储
    """
    
    def __init__(self, config: dict = None):
        """
        初始化推文存储
        
        参数:
            config: 配置字典，包含以下选项:
                - storage_mode: 存储模式 ("latest", "daily", "both")
                - storage_paths: 存储路径配置
                    {
                        "latest": "data/latest.json",
                        "daily": "data/daily"
                    }
        """
        self.config = config or {}
        self.storage_mode = self.config.get("storage_mode", "both")
        
        base_dir = Path(__file__).parent.parent
        data_dir = base_dir / "data"
        data_dir.mkdir(exist_ok=True)
        
        self.latest_path = str(data_dir / "latest.json")
        
        daily_dir = data_dir / "daily"
        daily_dir.mkdir(exist_ok=True)
        self.daily_dir = str(daily_dir)
        
        self.latest_tweets = self._load_tweets_from_file(self.latest_path)
        self.today_tweets = {}
    
    def _load_tweets_from_file(self, file_path: str) -> Dict[str, dict]:
        """
        从JSON文件加载推文数据
        
        参数:
            file_path: JSON文件路径
            
        返回:
            字典格式 {推文ID: 推文数据}
        """
        if os.path.exists(file_path):
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    tweets = data.get("tweets", [])
                    return {tweet["id"]: tweet for tweet in tweets}
            except (json.JSONDecodeError, IOError):
                return {}
        return {}
    
    def _get_daily_file_path(self, target_date: date = None) -> str:
        """
        获取指定日期的daily文件路径
        
        参数:
            target_date: 目标日期，默认今天
            
        返回:
            文件路径字符串，格式: data/daily/YYYY-MM-DD.json
        """
        if target_date is None:
            target_date = date.today()
        file_name = f"{target_date.isoformat()}.json"
        return os.path.join(self.daily_dir, file_name)
    
    def _load_daily_tweets(self, target_date: date = None) -> Dict[str, dict]:
        """
        加载指定日期的daily推文数据
        
        参数:
            target_date: 目标日期，默认今天
            
        返回:
            字典格式 {推文ID: 推文数据}
        """
        daily_file = self._get_daily_file_path(target_date)
        return self._load_tweets_from_file(daily_file)
    
    def get_existing_ids(self, storage_type: str = "latest") -> Set[str]:
        """
        获取已存储的推文ID集合
        
        参数:
            storage_type: 存储类型 ("latest" 或 "daily")
            
        返回:
            推文ID的集合，用于去重判断
        """
        if storage_type == "latest":
            return set(self.latest_tweets.keys())
        else:
            return set(self.today_tweets.keys())
    
    def save_latest(self, new_tweets: List[Dict]):
        """
        保存最新推文（覆盖模式）
        
        功能说明:
            将推文保存到latest.json文件。
            每次调用会完全覆盖之前的latest.json。
            用于记录"本次运行最新获取的推文"。
        
        参数:
            new_tweets: 要保存的推文列表
        """
        self.latest_tweets = {tweet["id"]: tweet for tweet in new_tweets}
        self._save_tweets_to_file(self.latest_tweets, self.latest_path, "latest")
    
    def add_daily(self, new_tweets: List[Dict], target_date: date = None) -> int:
        """
        增量添加推文到daily文件
        
        功能说明:
            将推文增量添加到指定日期的daily文件。
            如果推文已存在（ID相同），则跳过；
            如果是新推文，则添加到文件中。
            每天的daily文件会累积当天的所有推文。
        
        参数:
            new_tweets: 要添加的推文列表
            target_date: 目标日期，默认今天
            
        返回:
            新增的推文数量
        """
        if target_date is None:
            target_date = date.today()
        
        self.today_tweets = self._load_daily_tweets(target_date)
        added_count = 0
        current_ids = set(self.today_tweets.keys())
        
        for tweet in new_tweets:
            if tweet["id"] not in current_ids:
                self.today_tweets[tweet["id"]] = tweet
                added_count += 1
        
        if added_count > 0:
            daily_file = self._get_daily_file_path(target_date)
            self._save_tweets_to_file(self.today_tweets, daily_file, "daily")
        
        return added_count
    
    def _save_tweets_to_file(
        self, 
        tweets_dict: Dict[str, Dict], 
        file_path: str, 
        storage_type: str
    ):
        """
        将推文字典保存到JSON文件
        
        参数:
            tweets_dict: 推文ID到推文数据的映射字典
            file_path: 保存的文件路径
            storage_type: 存储类型标签 ("latest" 或 "daily")
        """
        tweets_list = list(tweets_dict.values())
        tweets_list.sort(key=lambda x: x.get("createdAt", ""), reverse=True)
        
        data = {
            "storage_type": storage_type,
            "last_updated": datetime.now().isoformat(),
            "total_count": len(tweets_list),
            "tweets": tweets_list
        }
        
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    
    def get_all_tweets(self, storage_type: str = "latest") -> List[Dict]:
        """
        获取所有推文
        
        参数:
            storage_type: 存储类型 ("latest" 或 "daily")
            
        返回:
            推文列表，按创建时间倒序排列
        """
        if storage_type == "latest":
            tweets_dict = self.latest_tweets
        else:
            tweets_dict = self.today_tweets
        
        tweets_list = list(tweets_dict.values())
        tweets_list.sort(key=lambda x: x.get("createdAt", ""), reverse=True)
        return tweets_list
    
    def get_tweets_by_user(
        self, 
        user_name: str, 
        storage_type: str = "latest"
    ) -> List[Dict]:
        """
        获取指定用户的推文
        
        参数:
            user_name: Twitter用户名（不包含@符号）
            storage_type: 存储类型 ("latest" 或 "daily")
            
        返回:
            该用户的推文列表，按创建时间倒序排列
        """
        user_name_lower = user_name.lower()
        
        if storage_type == "latest":
            tweets_dict = self.latest_tweets
        else:
            tweets_dict = self.today_tweets
        
        tweets = [
            tweet for tweet in tweets_dict.values()
            if tweet.get("author", {}).get("userName", "").lower() == user_name_lower
        ]
        tweets.sort(key=lambda x: x.get("createdAt", ""), reverse=True)
        return tweets
    
    def get_daily_dates(self) -> List[date]:
        """
        获取所有有数据的日期列表
        
        返回:
            按日期倒序排列的日期列表
        """
        dates = []
        if os.path.exists(self.daily_dir):
            for file_name in os.listdir(self.daily_dir):
                if file_name.endswith(".json"):
                    try:
                        date_str = file_name.replace(".json", "")
                        dates.append(date.fromisoformat(date_str))
                    except ValueError:
                        continue
        dates.sort(reverse=True)
        return dates
    
    def get_tweets_by_date(self, target_date: date) -> List[Dict]:
        """
        获取指定日期的所有推文
        
        参数:
            target_date: 目标日期
            
        返回:
            该日期的推文列表，按创建时间倒序排列
        """
        tweets_dict = self._load_daily_tweets(target_date)
        tweets_list = list(tweets_dict.values())
        tweets_list.sort(key=lambda x: x.get("createdAt", ""), reverse=True)
        return tweets_list
    
    def get_stats(
        self, 
        storage_type: str = "latest", 
        target_date: date = None
    ) -> Dict:
        """
        获取存储统计信息
        
        参数:
            storage_type: 存储类型 ("latest" 或 "daily")
            target_date: 目标日期（仅用于daily类型）
            
        返回:
            统计信息字典:
            {
                "storage_type": 存储类型,
                "date": 日期字符串,
                "total_tweets": 总推文数,
                "users_tracked": 监控用户数,
                "tweets_per_user": {用户名: 推文数, ...},
                "last_updated": 最后更新时间戳
            }
        """
        if storage_type == "latest":
            tweets = list(self.latest_tweets.values())
            storage_path = self.latest_path
        else:
            if target_date is None:
                target_date = date.today()
            tweets_dict = self._load_daily_tweets(target_date)
            tweets = list(tweets_dict.values())
            storage_path = self._get_daily_file_path(target_date)
        
        user_counts = {}
        
        for tweet in tweets:
            username = tweet.get("author", {}).get("userName", "Unknown")
            user_counts[username] = user_counts.get(username, 0) + 1
        
        last_updated = None
        if os.path.exists(storage_path):
            try:
                last_updated = os.path.getmtime(storage_path)
            except OSError:
                pass
        
        return {
            "storage_type": storage_type,
            "date": str(target_date) if target_date else None,
            "total_tweets": len(tweets),
            "users_tracked": len(user_counts),
            "tweets_per_user": user_counts,
            "last_updated": last_updated
        }
    
    def save_all(self, new_tweets: List[Dict]) -> int:
        """
        保存到所有启用的存储
        
        功能说明:
            根据配置同时保存到latest和daily两种存储。
            便于一次调用完成所有存储操作。
        
        参数:
            new_tweets: 要保存的推文列表
            
        返回:
            daily存储新增的推文数量
        """
        self.save_latest(new_tweets)
        added = self.add_daily(new_tweets)
        return added
    
    def clear_latest(self):
        """
        清空latest存储
        
        功能说明:
            删除latest.json文件并清空内存中的数据。
        """
        self.latest_tweets = {}
        if os.path.exists(self.latest_path):
            os.remove(self.latest_path)
