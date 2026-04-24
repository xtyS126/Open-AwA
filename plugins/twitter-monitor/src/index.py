from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests
from loguru import logger

from backend.plugins.base_plugin import BasePlugin


DEFAULT_TWITTER_API_BASE_URL = "https://api.twitterapi.io/twitter"
SUMMARY_ROLE = (
    "你是一名 AI 行业速报编辑，擅长从高密度推文里识别真正值得关注的 AI 动态，"
    "输出是否有重要动态、核心内容摘要和价值判断。"
)
SUMMARY_PRIORITY_RULES = [
    "新开源模型: release、open source、开源、发布、SOTA、Qwen、GLM 等模型发布或更新。",
    "商业大模型更新: ChatGPT、Claude、Gemini、Grok、Kimi、MiniMax 等闭源模型动态。",
    "模型实测结论: 对比、跑测试、实测、差距等评测结果。",
    "AI 产品或工具发布与更新: API、推出、试玩、Sora、Codex 等工具动态。",
    "GitHub 开源项目: star、爆火、github.com 链接、工具分享等开源项目动态。",
    "提示词创新: prompt、模板、工作流等有实用价值的提示词方法。",
    "机器人或硬件相关: Boston Dynamics、Figure、Optimus、树莓派等。",
    "重大软件更新: Chrome、VSCode 等大型软件更新。",
]
SUMMARY_OUTPUT_RULES = [
    "第一部分只输出整体结论: 未检测到符合条件的内容时写“暂无重大动态。”；检测到时写“有 X 条重要动态。”。",
    "第二部分逐条总结: 每条最多 5 行；信息量小的一句话概括，信息量大时使用“标题 + · 细节”结构。",
    "第三部分输出“AI总结：...”并给出价值判断，聚焦对行业或使用场景的意义。",
]
SUMMARY_LANGUAGE_RULES = [
    "全中文输出，但可保留必要的英文关键词。",
    "禁止出现“以下是结果”“我认为”等 AI 自述语。",
    "不要输出格式说明、推理过程、无关评论或再次请求调用工具。",
    "优先精简表达，只保留真正重要的信息。",
]
SUMMARY_EXAMPLE = (
    "有3条重要动态：\n"
    "一、Sora APP 安卓版正式上线，已在加、美、日等地区开放下载。\n\n"
    "二、Google 推出 File Search Tool\n"
    "· 产品形态：完全托管的 RAG 系统，内置于 Gemini API\n"
    "· 核心价值：将 RAG 简化为一行 API 调用，自动完成索引、向量嵌入与语义检索\n"
    "· 计费模式：仅首次建立索引收费，后续查询免费\n\n"
    "三、苹果新版 Siri 将由 Gemini 提供后台支持，预计 2026 年 3 月上线。\n\n"
    "AI总结：谷歌推出的工具会降低企业级知识库部署门槛，RAG 技术正在平民化。"
)
DEFAULT_SUMMARY_GUIDANCE = (
    "请直接基于返回的 digest、top_tweets 和 tweets 数据，在当前对话中完成最终中文总结。"
    "先判断是否存在重要动态，再输出核心摘要与 AI总结。不要再调用额外总结模型，也不要输出 JSON。"
)
SUPPORTED_STORAGE_MODES = {"latest", "daily", "both"}


def _coerce_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "y", "on"}:
            return True
        if normalized in {"0", "false", "no", "n", "off"}:
            return False
    return default


def _coerce_int(value: Any, default: int, minimum: int = 1, maximum: int = 100) -> int:
    try:
        normalized = int(value)
    except (TypeError, ValueError):
        normalized = default
    return max(minimum, min(normalized, maximum))


def _parse_user_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, list):
        raw_values = value
    else:
        raw_values = str(value).replace("\n", ",").split(",")

    result: List[str] = []
    for item in raw_values:
        normalized = str(item).strip().lstrip("@")
        if normalized and normalized not in result:
            result.append(normalized)
    return result


def _build_summary_prompt_template() -> str:
    sections = [
        f"角色设定: {SUMMARY_ROLE}",
        "判断逻辑（按优先级）:",
    ]
    sections.extend(
        f"{index}. {rule}"
        for index, rule in enumerate(SUMMARY_PRIORITY_RULES, start=1)
    )
    sections.append("输出要求:")
    sections.extend(
        f"{index}. {rule}"
        for index, rule in enumerate(SUMMARY_OUTPUT_RULES, start=1)
    )
    sections.append("语言要求:")
    sections.extend(
        f"{index}. {rule}"
        for index, rule in enumerate(SUMMARY_LANGUAGE_RULES, start=1)
    )
    sections.append(f"示例输出:\n{SUMMARY_EXAMPLE}")
    return "\n".join(sections)


SUMMARY_PROMPT_TEMPLATE = _build_summary_prompt_template()


class TwitterMonitorPlugin(BasePlugin):
    name: str = "twitter-monitor"
    version: str = "1.0.0"
    description: str = "抓取、缓存并整理指定 Twitter 账号内容，供当前模型直接分析总结的监控插件"

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self.plugin_root = Path(__file__).resolve().parents[1]
        self.data_dir = self.plugin_root / "data"
        self.daily_dir = self.data_dir / "daily"
        self.latest_path = self.data_dir / "latest.json"

        self.twitter_api_key = ""
        self.twitter_api_base_url = DEFAULT_TWITTER_API_BASE_URL
        self.monitored_users: List[str] = []
        self.include_replies = False
        self.tweets_per_user = 8
        self.storage_mode = "both"
        
        # 自定义提示词配置
        self.enable_custom_summary = False
        self.custom_summary_role = ""
        self.custom_priority_rules = ""
        self.custom_output_rules = ""
        self.custom_language_rules = ""
        self.custom_summary_example = ""
        self._custom_summary_prompt_template = ""
        
        self._refresh_config()

    def _refresh_config(self) -> None:
        self.twitter_api_key = str(
            self.config.get("twitter_api_key") or self.config.get("api_key") or ""
        ).strip()
        self.twitter_api_base_url = str(
            self.config.get("twitter_api_base_url") or DEFAULT_TWITTER_API_BASE_URL
        ).strip().rstrip("/")
        self.monitored_users = _parse_user_list(self.config.get("monitored_users"))
        self.include_replies = _coerce_bool(self.config.get("include_replies"), False)
        self.tweets_per_user = _coerce_int(self.config.get("tweets_per_user"), 8, minimum=1, maximum=50)
        storage_mode = str(self.config.get("storage_mode") or "both").strip().lower()
        self.storage_mode = storage_mode if storage_mode in SUPPORTED_STORAGE_MODES else "both"
        
        # 加载自定义提示词配置
        self._load_summary_customization()

    def _load_summary_customization(self) -> None:
        """
        从配置中加载自定义提示词配置。
        如果未启用自定义提示词或配置为空，使用默认值。
        """
        summary_config = self.config.get("summary_customization")
        
        # 如果配置不是字典或为空，使用默认值
        if not isinstance(summary_config, dict):
            self.enable_custom_summary = False
            self.custom_summary_role = ""
            self.custom_priority_rules = ""
            self.custom_output_rules = ""
            self.custom_language_rules = ""
            self.custom_summary_example = ""
            self._custom_summary_prompt_template = ""
            return
        
        # 读取启用状态
        self.enable_custom_summary = _coerce_bool(summary_config.get("enable_custom_summary"), False)
        
        # 读取自定义字段
        self.custom_summary_role = str(summary_config.get("custom_summary_role") or "").strip()
        self.custom_priority_rules = str(summary_config.get("custom_priority_rules") or "").strip()
        self.custom_output_rules = str(summary_config.get("custom_output_rules") or "").strip()
        self.custom_language_rules = str(summary_config.get("custom_language_rules") or "").strip()
        self.custom_summary_example = str(summary_config.get("custom_summary_example") or "").strip()
        
        # 如果启用了自定义提示词且配置了内容，生成自定义提示词模板
        if self.enable_custom_summary and self._has_custom_content():
            self._custom_summary_prompt_template = self._build_custom_summary_prompt_template()
        else:
            self._custom_summary_prompt_template = ""

    def _has_custom_content(self) -> bool:
        """
        检查是否配置了任何自定义提示词内容。
        """
        return bool(
            self.custom_summary_role or
            self.custom_priority_rules or
            self.custom_output_rules or
            self.custom_language_rules or
            self.custom_summary_example
        )

    def _build_custom_summary_prompt_template(self) -> str:
        """
        根据自定义配置构建提示词模板。
        """
        sections = []
        
        # 角色设定
        if self.custom_summary_role:
            sections.append(f"角色设定: {self.custom_summary_role}")
        
        # 优先级规则
        if self.custom_priority_rules:
            sections.append("判断逻辑（按优先级）:")
            rules = [rule.strip() for rule in self.custom_priority_rules.split("\n") if rule.strip()]
            for index, rule in enumerate(rules, start=1):
                sections.append(f"{index}. {rule}")
        
        # 输出规则
        if self.custom_output_rules:
            sections.append("输出要求:")
            rules = [rule.strip() for rule in self.custom_output_rules.split("\n") if rule.strip()]
            for index, rule in enumerate(rules, start=1):
                sections.append(f"{index}. {rule}")
        
        # 语言规则
        if self.custom_language_rules:
            sections.append("语言要求:")
            rules = [rule.strip() for rule in self.custom_language_rules.split("\n") if rule.strip()]
            for index, rule in enumerate(rules, start=1):
                sections.append(f"{index}. {rule}")
        
        # 示例
        if self.custom_summary_example:
            sections.append(f"示例输出:\n{self.custom_summary_example}")
        
        return "\n".join(sections)

    def _get_effective_summary_config(self) -> Dict[str, Any]:
        """
        获取生效的提示词配置。
        如果启用了自定义提示词且配置了内容，使用自定义配置；
        否则使用默认配置。
        """
        if self.enable_custom_summary and self._has_custom_content():
            # 使用自定义配置
            return {
                "source": "custom",
                "role": self.custom_summary_role or SUMMARY_ROLE,
                "priority_rules": self._parse_rules(self.custom_priority_rules, SUMMARY_PRIORITY_RULES),
                "output_rules": self._parse_rules(self.custom_output_rules, SUMMARY_OUTPUT_RULES),
                "language_rules": self._parse_rules(self.custom_language_rules, SUMMARY_LANGUAGE_RULES),
                "example": self.custom_summary_example or SUMMARY_EXAMPLE,
                "guidance": DEFAULT_SUMMARY_GUIDANCE,
                "prompt_template": self._custom_summary_prompt_template or SUMMARY_PROMPT_TEMPLATE,
            }
        else:
            # 使用默认配置
            return {
                "source": "default",
                "role": SUMMARY_ROLE,
                "priority_rules": list(SUMMARY_PRIORITY_RULES),
                "output_rules": list(SUMMARY_OUTPUT_RULES),
                "language_rules": list(SUMMARY_LANGUAGE_RULES),
                "example": SUMMARY_EXAMPLE,
                "guidance": DEFAULT_SUMMARY_GUIDANCE,
                "prompt_template": SUMMARY_PROMPT_TEMPLATE,
            }

    def _parse_rules(self, custom_rules: str, default_rules: List[str]) -> List[str]:
        """
        解析规则字符串为列表。
        如果自定义规则为空，返回默认规则。
        """
        if not custom_rules:
            return list(default_rules)
        
        rules = [rule.strip() for rule in custom_rules.split("\n") if rule.strip()]
        return rules if rules else list(default_rules)

    def initialize(self) -> bool:
        self._refresh_config()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.daily_dir.mkdir(parents=True, exist_ok=True)
        self._initialized = True
        logger.info(
            f"[{self.name}] 初始化完成，默认监控 {len(self.monitored_users)} 个账号，"
            f"每个账号抓取 {self.tweets_per_user} 条，缓存模式 {self.storage_mode}"
        )
        return True

    def validate(self) -> bool:
        self._refresh_config()
        if self.storage_mode not in SUPPORTED_STORAGE_MODES:
            logger.error(f"[{self.name}] storage_mode 配置无效: {self.storage_mode}")
            return False
        return True

    def execute(self, *args, **kwargs) -> Dict[str, Any]:
        action = str(kwargs.get("action") or "").strip()
        actions = {
            "fetch_twitter_tweets": self.fetch_twitter_tweets,
            "read_twitter_cache": self.read_twitter_cache,
            "get_twitter_daily_tweets": self.get_twitter_daily_tweets,
            "get_twitter_stats": self.get_twitter_stats,
            "search_twitter_users": self.search_twitter_users,
            "get_twitter_user_info": self.get_twitter_user_info,
            "summarize_twitter_tweets": self.summarize_twitter_tweets,
        }

        if not action:
            return {"status": "error", "message": "缺少 action 参数"}

        handler = actions.get(action)
        if handler is None:
            return {"status": "error", "message": f"不支持的 action: {action}"}

        payload = dict(kwargs)
        payload.pop("action", None)
        return handler(**payload)

    def cleanup(self) -> None:
        logger.info(f"[{self.name}] 清理 Twitter 监控插件")
        super().cleanup()

    def _twitter_headers(self) -> Dict[str, str]:
        return {"X-API-Key": self.twitter_api_key}

    def _read_json_payload(self, file_path: Path) -> Dict[str, Any]:
        if not file_path.exists():
            return {"tweets": [], "total_count": 0}
        try:
            with open(file_path, "r", encoding="utf-8") as file_obj:
                payload = json.load(file_obj)
            if isinstance(payload, dict):
                return payload
        except Exception as e:
            logger.warning(f"[{self.name}] 读取文件失败 {file_path}: {e}")
        return {"tweets": [], "total_count": 0}

    def _write_json_payload(self, file_path: Path, storage_type: str, tweets: List[Dict[str, Any]]) -> None:
        payload = {
            "storage_type": storage_type,
            "last_updated": datetime.now().isoformat(),
            "total_count": len(tweets),
            "tweets": tweets,
        }
        with open(file_path, "w", encoding="utf-8") as file_obj:
            json.dump(payload, file_obj, ensure_ascii=False, indent=2)

    def _deduplicate_tweets(self, tweets: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        deduplicated: Dict[str, Dict[str, Any]] = {}
        for tweet in tweets:
            tweet_id = str(tweet.get("id") or "").strip()
            if not tweet_id:
                continue
            deduplicated[tweet_id] = tweet
        return sorted(
            deduplicated.values(),
            key=lambda item: str(item.get("created_at") or ""),
            reverse=True,
        )

    def _append_daily_tweets(self, tweets: List[Dict[str, Any]], target_date: str) -> int:
        daily_path = self.daily_dir / f"{target_date}.json"
        existing_payload = self._read_json_payload(daily_path)
        existing_tweets = existing_payload.get("tweets", []) if isinstance(existing_payload.get("tweets"), list) else []
        existing_ids = {str(item.get("id") or "") for item in existing_tweets}

        added_count = 0
        merged_tweets = list(existing_tweets)
        for tweet in tweets:
            tweet_id = str(tweet.get("id") or "")
            if not tweet_id or tweet_id in existing_ids:
                continue
            merged_tweets.append(tweet)
            existing_ids.add(tweet_id)
            added_count += 1

        self._write_json_payload(daily_path, "daily", self._deduplicate_tweets(merged_tweets))
        return added_count

    def _save_fetched_tweets(self, tweets: List[Dict[str, Any]], storage_mode: Optional[str] = None) -> int:
        normalized_mode = str(storage_mode or self.storage_mode).strip().lower()
        if normalized_mode not in SUPPORTED_STORAGE_MODES:
            normalized_mode = self.storage_mode

        deduplicated = self._deduplicate_tweets(tweets)
        if normalized_mode in {"latest", "both"}:
            self._write_json_payload(self.latest_path, "latest", deduplicated)

        if normalized_mode in {"daily", "both"}:
            return self._append_daily_tweets(deduplicated, date.today().isoformat())
        return 0

    def _filter_tweets(
        self,
        tweets: List[Dict[str, Any]],
        user_name: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        filtered = tweets
        if user_name:
            normalized_user = str(user_name).strip().lstrip("@").lower()
            filtered = [
                item for item in filtered
                if str(item.get("author", {}).get("user_name") or "").lower() == normalized_user
            ]
        if limit is not None:
            filtered = filtered[:_coerce_int(limit, 20, minimum=1, maximum=200)]
        return filtered

    def _simplify_tweet(self, tweet: Dict[str, Any]) -> Dict[str, Any]:
        author = tweet.get("author") or {}
        return {
            "id": str(tweet.get("id") or ""),
            "text": str(tweet.get("text") or "").strip(),
            "created_at": str(tweet.get("createdAt") or tweet.get("created_at") or ""),
            "url": str(tweet.get("url") or tweet.get("twitterUrl") or ""),
            "author": {
                "user_name": str(author.get("userName") or author.get("user_name") or "").strip(),
                "name": str(author.get("name") or "").strip(),
            },
            "metrics": {
                "likes": int(tweet.get("likeCount") or tweet.get("like_count") or 0),
                "retweets": int(tweet.get("retweetCount") or tweet.get("retweet_count") or 0),
                "replies": int(tweet.get("replyCount") or tweet.get("reply_count") or 0),
            },
        }

    def _request_twitter_api(self, endpoint: str, params: Dict[str, Any]) -> Dict[str, Any]:
        if not self.twitter_api_key:
            return {"status": "error", "message": "未配置 twitter_api_key"}

        url = f"{self.twitter_api_base_url}/{endpoint.lstrip('/')}"
        try:
            response = requests.get(url, headers=self._twitter_headers(), params=params, timeout=30)
            response.raise_for_status()
            payload = response.json()
        except Exception as e:
            logger.error(f"[{self.name}] Twitter API 请求失败: {e}")
            return {"status": "error", "message": f"Twitter API 请求失败: {e}"}

        if payload.get("status") != "success":
            return {
                "status": "error",
                "message": str(payload.get("msg") or payload.get("message") or "Twitter API 返回失败"),
            }
        return {"status": "success", "data": payload.get("data", {})}

    def fetch_twitter_tweets(
        self,
        user_names: Optional[Any] = None,
        limit: Optional[int] = None,
        include_replies: Optional[bool] = None,
        storage_mode: Optional[str] = None,
    ) -> Dict[str, Any]:
        selected_users = _parse_user_list(user_names) or self.monitored_users
        if not selected_users:
            return {"status": "error", "message": "未提供 user_names，且默认监控列表为空"}

        per_user_limit = _coerce_int(limit, self.tweets_per_user, minimum=1, maximum=50)
        include_reply_flag = self.include_replies if include_replies is None else _coerce_bool(include_replies)

        collected_tweets: List[Dict[str, Any]] = []
        results: List[Dict[str, Any]] = []
        errors: List[Dict[str, Any]] = []

        for user_name in selected_users:
            request_result = self._request_twitter_api(
                "user/last_tweets",
                {
                    "userName": user_name,
                    "includeReplies": str(include_reply_flag).lower(),
                },
            )
            if request_result.get("status") != "success":
                error_item = {
                    "user_name": user_name,
                    "message": request_result.get("message", "抓取失败"),
                }
                errors.append(error_item)
                results.append({"user_name": user_name, "status": "error", "count": 0, "message": error_item["message"]})
                continue

            payload = request_result.get("data", {})
            raw_tweets = payload.get("tweets", []) if isinstance(payload, dict) else []
            simplified = [self._simplify_tweet(item) for item in raw_tweets[:per_user_limit]]
            collected_tweets.extend(simplified)
            results.append({"user_name": user_name, "status": "success", "count": len(simplified)})

        if not collected_tweets and errors:
            return {
                "status": "error",
                "message": "所有账号抓取均失败",
                "errors": errors,
                "results": results,
            }

        deduplicated = self._deduplicate_tweets(collected_tweets)
        added_count = self._save_fetched_tweets(deduplicated, storage_mode=storage_mode)
        return {
            "status": "success",
            "users": selected_users,
            "fetched_count": len(deduplicated),
            "new_daily_count": added_count,
            "storage_mode": str(storage_mode or self.storage_mode),
            "results": results,
            "errors": errors,
            "tweets": deduplicated,
        }

    def read_twitter_cache(
        self,
        user_name: Optional[str] = None,
        limit: Optional[int] = 20,
    ) -> Dict[str, Any]:
        payload = self._read_json_payload(self.latest_path)
        tweets = payload.get("tweets", []) if isinstance(payload.get("tweets"), list) else []
        filtered = self._filter_tweets(tweets, user_name=user_name, limit=limit)
        return {
            "status": "success",
            "source_type": "latest",
            "count": len(filtered),
            "last_updated": payload.get("last_updated"),
            "tweets": filtered,
        }

    def get_twitter_daily_tweets(
        self,
        target_date: Optional[str] = None,
        user_name: Optional[str] = None,
        limit: Optional[int] = 50,
    ) -> Dict[str, Any]:
        normalized_date = str(target_date or date.today().isoformat()).strip()
        try:
            date.fromisoformat(normalized_date)
        except ValueError:
            return {"status": "error", "message": f"无效日期格式: {normalized_date}"}

        daily_path = self.daily_dir / f"{normalized_date}.json"
        payload = self._read_json_payload(daily_path)
        tweets = payload.get("tweets", []) if isinstance(payload.get("tweets"), list) else []
        filtered = self._filter_tweets(tweets, user_name=user_name, limit=limit)
        return {
            "status": "success",
            "source_type": "daily",
            "target_date": normalized_date,
            "count": len(filtered),
            "last_updated": payload.get("last_updated"),
            "tweets": filtered,
        }

    def get_twitter_stats(
        self,
        storage_type: str = "latest",
        target_date: Optional[str] = None,
    ) -> Dict[str, Any]:
        normalized_storage = str(storage_type or "latest").strip().lower()
        if normalized_storage not in {"latest", "daily"}:
            return {"status": "error", "message": f"不支持的 storage_type: {normalized_storage}"}

        if normalized_storage == "latest":
            payload = self._read_json_payload(self.latest_path)
            normalized_date = None
        else:
            normalized_date = str(target_date or date.today().isoformat()).strip()
            try:
                date.fromisoformat(normalized_date)
            except ValueError:
                return {"status": "error", "message": f"无效日期格式: {normalized_date}"}
            payload = self._read_json_payload(self.daily_dir / f"{normalized_date}.json")

        tweets = payload.get("tweets", []) if isinstance(payload.get("tweets"), list) else []
        tweets_per_user: Dict[str, int] = {}
        for tweet in tweets:
            user_name = str(tweet.get("author", {}).get("user_name") or "unknown")
            tweets_per_user[user_name] = tweets_per_user.get(user_name, 0) + 1

        available_dates = sorted(
            file_path.stem
            for file_path in self.daily_dir.glob("*.json")
            if file_path.is_file()
        )
        available_dates.reverse()

        return {
            "status": "success",
            "storage_type": normalized_storage,
            "target_date": normalized_date,
            "total_tweets": len(tweets),
            "users_tracked": len(tweets_per_user),
            "tweets_per_user": tweets_per_user,
            "last_updated": payload.get("last_updated"),
            "available_dates": available_dates[:30],
        }

    def search_twitter_users(self, query: str, limit: Optional[int] = 10) -> Dict[str, Any]:
        normalized_query = str(query or "").strip()
        if not normalized_query:
            return {"status": "error", "message": "query 不能为空"}

        request_result = self._request_twitter_api("user/search", {"query": normalized_query})
        if request_result.get("status") != "success":
            return request_result

        payload = request_result.get("data", {})
        users = payload.get("users", []) if isinstance(payload, dict) else []
        normalized_limit = _coerce_int(limit, 10, minimum=1, maximum=50)
        results = []
        for user in users[:normalized_limit]:
            results.append(
                {
                    "id": str(user.get("id") or ""),
                    "user_name": str(user.get("userName") or "").strip(),
                    "name": str(user.get("name") or "").strip(),
                    "description": str(user.get("description") or "").strip(),
                    "followers": int(user.get("followers") or 0),
                    "following": int(user.get("following") or 0),
                }
            )

        return {
            "status": "success",
            "query": normalized_query,
            "count": len(results),
            "users": results,
        }

    def get_twitter_user_info(self, user_name: str) -> Dict[str, Any]:
        normalized_user = str(user_name or "").strip().lstrip("@")
        if not normalized_user:
            return {"status": "error", "message": "user_name 不能为空"}

        result = self.search_twitter_users(query=normalized_user, limit=1)
        if result.get("status") != "success":
            return result
        users = result.get("users", [])
        if not users:
            return {"status": "not_found", "message": f"未找到用户: {normalized_user}"}
        return {
            "status": "success",
            "user": users[0],
        }

    def _load_summary_source(
        self,
        source_type: str,
        target_date: Optional[str],
        user_name: Optional[str],
        limit: Optional[int],
    ) -> Dict[str, Any]:
        normalized_source = str(source_type or "daily").strip().lower()
        if normalized_source == "latest":
            return self.read_twitter_cache(user_name=user_name, limit=limit)
        if normalized_source == "daily":
            return self.get_twitter_daily_tweets(target_date=target_date, user_name=user_name, limit=limit)
        return {"status": "error", "message": f"不支持的 source_type: {normalized_source}"}

    def _build_summary_digest(self, tweets: List[Dict[str, Any]]) -> List[str]:
        lines: List[str] = []
        for index, tweet in enumerate(tweets, start=1):
            author = tweet.get("author", {})
            metrics = tweet.get("metrics", {})
            lines.append(
                f"[{index}] @{author.get('user_name', '')} | {tweet.get('created_at', '')} | "
                f"赞 {metrics.get('likes', 0)} 转 {metrics.get('retweets', 0)} 回 {metrics.get('replies', 0)} | "
                f"{tweet.get('text', '')}"
            )

        return lines

    def _select_top_tweets(self, tweets: List[Dict[str, Any]], top_n: int = 5) -> List[Dict[str, Any]]:
        return sorted(
            tweets,
            key=lambda item: (
                int(item.get("metrics", {}).get("likes", 0))
                + int(item.get("metrics", {}).get("retweets", 0)) * 2
                + int(item.get("metrics", {}).get("replies", 0))
            ),
            reverse=True,
        )[:top_n]

    def summarize_twitter_tweets(
        self,
        source_type: str = "daily",
        target_date: Optional[str] = None,
        user_name: Optional[str] = None,
        limit: Optional[int] = 50,
    ) -> Dict[str, Any]:
        source_result = self._load_summary_source(
            source_type=source_type,
            target_date=target_date,
            user_name=user_name,
            limit=_coerce_int(limit, 50, minimum=1, maximum=100),
        )
        if source_result.get("status") != "success":
            return source_result

        tweets = source_result.get("tweets", [])
        if not tweets:
            return {"status": "error", "message": "没有可总结的推文数据"}

        normalized_source = str(source_type or "daily").strip().lower()
        normalized_date = source_result.get("target_date") or str(target_date or date.today().isoformat()).strip()
        digest = self._build_summary_digest(tweets)
        top_tweets = self._select_top_tweets(tweets)
        
        # 获取生效的提示词配置
        effective_config = self._get_effective_summary_config()

        return {
            "status": "success",
            "source_type": source_result.get("source_type", source_type),
            "target_date": normalized_date,
            "count": len(tweets),
            "summary_mode": "current_model",
            "prompt_source": effective_config["source"],
            "summary_guidance": effective_config["guidance"],
            "summary_role": effective_config["role"],
            "summary_priority_rules": effective_config["priority_rules"],
            "summary_output_rules": effective_config["output_rules"],
            "summary_language_rules": effective_config["language_rules"],
            "summary_example": effective_config["example"],
            "summary_prompt_template": effective_config["prompt_template"],
            "summary_context": (
                f"请基于 {normalized_source} 来源的 {len(tweets)} 条推文完成中文总结。"
                "只在推文直接提及或明显暗示发布、上线、开放、更新、宣布、推出等事件行为时，"
                "才判定为有重要动态；可优先参考 digest 的时间顺序，再结合 top_tweets 判断高价值动态。"
            ),
            "digest": digest,
            "top_tweets": top_tweets,
            "tweets": tweets,
        }

    def get_tools(self) -> List[Dict[str, Any]]:
        return [
            {
                "name": "fetch_twitter_tweets",
                "method": "fetch_twitter_tweets",
                "description": "抓取一个或多个 Twitter 账号的最新推文，并同步写入 latest 与 daily 缓存",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "user_names": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "可选，要抓取的用户名列表；为空时使用插件默认监控列表"
                        },
                        "limit": {
                            "type": "integer",
                            "description": "每个用户最多抓取多少条推文"
                        },
                        "include_replies": {
                            "type": "boolean",
                            "description": "是否包含回复推文"
                        }
                    }
                }
            },
            {
                "name": "read_twitter_cache",
                "method": "read_twitter_cache",
                "description": "读取最近一次抓取缓存，可按用户过滤",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "user_name": {"type": "string", "description": "可选，按用户名过滤"},
                        "limit": {"type": "integer", "description": "最多返回多少条记录"}
                    }
                }
            },
            {
                "name": "get_twitter_daily_tweets",
                "method": "get_twitter_daily_tweets",
                "description": "读取某一天累积缓存的推文，可按用户过滤",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "target_date": {"type": "string", "description": "日期，格式 YYYY-MM-DD"},
                        "user_name": {"type": "string", "description": "可选，按用户名过滤"},
                        "limit": {"type": "integer", "description": "最多返回多少条记录"}
                    }
                }
            },
            {
                "name": "get_twitter_stats",
                "method": "get_twitter_stats",
                "description": "查看 latest 或 daily 缓存统计",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "storage_type": {"type": "string", "enum": ["latest", "daily"]},
                        "target_date": {"type": "string", "description": "当 storage_type=daily 时可指定日期"}
                    }
                }
            },
            {
                "name": "search_twitter_users",
                "method": "search_twitter_users",
                "description": "按关键词搜索 Twitter 用户",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "搜索关键词"},
                        "limit": {"type": "integer", "description": "最多返回多少个用户"}
                    },
                    "required": ["query"]
                }
            },
            {
                "name": "get_twitter_user_info",
                "method": "get_twitter_user_info",
                "description": "获取指定 Twitter 用户的账号信息",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "user_name": {"type": "string", "description": "目标用户名"}
                    },
                    "required": ["user_name"]
                }
            },
            {
                "name": "summarize_twitter_tweets",
                "method": "summarize_twitter_tweets",
                "description": "整理缓存中的推文摘要素材，由当前对话模型直接完成总结，不会调用额外总结模型",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "source_type": {"type": "string", "enum": ["latest", "daily"]},
                        "target_date": {"type": "string", "description": "当 source_type=daily 时可指定日期"},
                        "user_name": {"type": "string", "description": "可选，只总结指定用户"},
                        "limit": {"type": "integer", "description": "最多纳入总结的推文条数"}
                    }
                }
            }
        ]