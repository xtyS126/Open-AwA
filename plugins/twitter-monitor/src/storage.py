import json
import os
from datetime import datetime, date
from typing import List, Dict, Set


class TweetStorage:
    """推文数据存储管理类

    提供 latest 和 daily 两种存储模式：
    - latest.json: 每次运行的最新推文（覆盖模式）
    - daily/YYYY-MM-DD.json: 按日期累积存储（带 ID 去重）
    """

    def __init__(self, data_dir: str):
        """初始化推文存储

        参数:
            data_dir: 数据目录的绝对路径（插件 data/ 目录）
        """
        self.data_dir = data_dir

        self.latest_path = os.path.join(data_dir, "latest.json")
        self.daily_dir = os.path.join(data_dir, "daily")
        os.makedirs(self.daily_dir, exist_ok=True)

        self.latest_tweets = self._load_tweets_from_file(self.latest_path)
        self.today_tweets: Dict[str, dict] = {}

    def _load_tweets_from_file(self, file_path: str) -> Dict[str, dict]:
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
        if target_date is None:
            target_date = date.today()
        file_name = f"{target_date.isoformat()}.json"
        return os.path.join(self.daily_dir, file_name)

    def _load_daily_tweets(self, target_date: date = None) -> Dict[str, dict]:
        daily_file = self._get_daily_file_path(target_date)
        return self._load_tweets_from_file(daily_file)

    def get_existing_ids(self, storage_type: str = "latest") -> Set[str]:
        if storage_type == "latest":
            return set(self.latest_tweets.keys())
        else:
            return set(self.today_tweets.keys())

    def save_latest(self, new_tweets: List[Dict]):
        self.latest_tweets = {tweet["id"]: tweet for tweet in new_tweets}
        self._save_tweets_to_file(self.latest_tweets, self.latest_path, "latest")

    def add_daily(self, new_tweets: List[Dict], target_date: date = None) -> int:
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

    def _save_tweets_to_file(self, tweets_dict: Dict[str, Dict], file_path: str, storage_type: str):
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
        if storage_type == "latest":
            tweets_dict = self.latest_tweets
        else:
            tweets_dict = self.today_tweets

        tweets_list = list(tweets_dict.values())
        tweets_list.sort(key=lambda x: x.get("createdAt", ""), reverse=True)
        return tweets_list

    def get_tweets_by_user(self, user_name: str, storage_type: str = "latest") -> List[Dict]:
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
        tweets_dict = self._load_daily_tweets(target_date)
        tweets_list = list(tweets_dict.values())
        tweets_list.sort(key=lambda x: x.get("createdAt", ""), reverse=True)
        return tweets_list

    def get_stats(self, storage_type: str = "latest", target_date: date = None) -> Dict:
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
        self.save_latest(new_tweets)
        added = self.add_daily(new_tweets)
        return added

    def clear_latest(self):
        self.latest_tweets = {}
        if os.path.exists(self.latest_path):
            os.remove(self.latest_path)
