from __future__ import annotations

import json
import threading
import time
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests
from loguru import logger

from backend.plugins.base_plugin import BasePlugin
from backend.billing.pricing_manager import PricingManager

from .twitter_api import TwitterAPI
from .storage import TweetStorage
from .summarizer import AISummarizer, DEFAULT_SYSTEM_PROMPT


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
    "第一部分只输出整体结论: 未检测到符合条件的内容时写\u201c暂无重大动态。\u201d；检测到时写\u201c有 X 条重要动态。\u201d。",
    "第二部分逐条总结: 每条最多 5 行；信息量小的一句话概括，信息量大时使用\u201c标题 + \u00b7 细节\u201d结构。",
    "第三部分输出\u201cAI总结：...\u201d并给出价值判断，聚焦对行业或使用场景的意义。",
]
SUMMARY_LANGUAGE_RULES = [
    "全中文输出，但可保留必要的英文关键词。",
    "禁止出现\u201c以下是结果\u201d\u201c我认为\u201d等 AI 自述语。",
    "不要输出格式说明、推理过程、无关评论或再次请求调用工具。",
    "优先精简表达，只保留真正重要的信息。",
]
SUMMARY_EXAMPLE = (
    "有3条重要动态：\n"
    "一、Sora APP 安卓版正式上线，已在加、美、日等地区开放下载。\n\n"
    "二、Google 推出 File Search Tool\n"
    "\u00b7 产品形态：完全托管的 RAG 系统，内置于 Gemini API\n"
    "\u00b7 核心价值：将 RAG 简化为一行 API 调用，自动完成索引、向量嵌入与语义检索\n"
    "\u00b7 计费模式：仅首次建立索引收费，后续查询免费\n\n"
    "三、苹果新版 Siri 将由 Gemini 提供后台支持，预计 2026 年 3 月发布。\n\n"
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
    version: str = "2.0.0"
    description: str = "抓取、缓存并整理指定 Twitter 账号内容，支持搜索用户、指定数量获取推文、每日自动获取并 AI 总结"

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self.plugin_root = Path(__file__).resolve().parents[1]
        self.data_dir = self.plugin_root / "data"
        self.daily_dir = self.data_dir / "daily"
        self.summaries_dir = self.data_dir / "summaries"

        self.twitter_api_key = ""
        self.twitter_api_base_url = DEFAULT_TWITTER_API_BASE_URL
        self.monitored_users: List[str] = []
        self.include_replies = False
        self.tweets_per_user = 8
        self.storage_mode = "both"
        self.auto_fetch_interval_hours = 24
        self.ai_model_config_id: Optional[int] = None

        self.enable_custom_summary = False
        self.custom_summary_role = ""
        self.custom_priority_rules = ""
        self.custom_output_rules = ""
        self.custom_language_rules = ""
        self.custom_summary_example = ""
        self._custom_summary_prompt_template = ""

        self._twitter_api: Optional[TwitterAPI] = None
        self._storage: Optional[TweetStorage] = None
        self._summarizer: Optional[AISummarizer] = None

        self._scheduler_thread: Optional[threading.Thread] = None
        self._scheduler_stop = threading.Event()
        self._scheduler_lock = threading.Lock()

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
        self.auto_fetch_interval_hours = _coerce_int(
            self.config.get("auto_fetch_interval_hours"), 24, minimum=1, maximum=168
        )
        self.ai_model_config_id = self.config.get("ai_model_config_id")

        self._load_summary_customization()

        if self.twitter_api_key:
            self._twitter_api = TwitterAPI(self.twitter_api_key)
        else:
            self._twitter_api = None

        self._storage = TweetStorage(str(self.data_dir))

        self._summarizer = AISummarizer(
            summaries_dir=str(self.summaries_dir),
            ai_call_func=self._call_external_ai_for_summary,
            system_prompt=SUMMARY_PROMPT_TEMPLATE
        )

    def _load_summary_customization(self) -> None:
        summary_config = self.config.get("summary_customization")
        if not isinstance(summary_config, dict):
            self.enable_custom_summary = False
            self.custom_summary_role = ""
            self.custom_priority_rules = ""
            self.custom_output_rules = ""
            self.custom_language_rules = ""
            self.custom_summary_example = ""
            self._custom_summary_prompt_template = ""
            return

        self.enable_custom_summary = _coerce_bool(summary_config.get("enable_custom_summary"), False)
        self.custom_summary_role = str(summary_config.get("custom_summary_role") or "").strip()
        self.custom_priority_rules = str(summary_config.get("custom_priority_rules") or "").strip()
        self.custom_output_rules = str(summary_config.get("custom_output_rules") or "").strip()
        self.custom_language_rules = str(summary_config.get("custom_language_rules") or "").strip()
        self.custom_summary_example = str(summary_config.get("custom_summary_example") or "").strip()

        if self.enable_custom_summary and self._has_custom_content():
            self._custom_summary_prompt_template = self._build_custom_summary_prompt_template()
        else:
            self._custom_summary_prompt_template = ""

    def _has_custom_content(self) -> bool:
        return bool(
            self.custom_summary_role or
            self.custom_priority_rules or
            self.custom_output_rules or
            self.custom_language_rules or
            self.custom_summary_example
        )

    def _build_custom_summary_prompt_template(self) -> str:
        sections = []
        if self.custom_summary_role:
            sections.append(f"角色设定: {self.custom_summary_role}")
        if self.custom_priority_rules:
            sections.append("判断逻辑（按优先级）:")
            rules = [rule.strip() for rule in self.custom_priority_rules.split("\n") if rule.strip()]
            for index, rule in enumerate(rules, start=1):
                sections.append(f"{index}. {rule}")
        if self.custom_output_rules:
            sections.append("输出要求:")
            rules = [rule.strip() for rule in self.custom_output_rules.split("\n") if rule.strip()]
            for index, rule in enumerate(rules, start=1):
                sections.append(f"{index}. {rule}")
        if self.custom_language_rules:
            sections.append("语言要求:")
            rules = [rule.strip() for rule in self.custom_language_rules.split("\n") if rule.strip()]
            for index, rule in enumerate(rules, start=1):
                sections.append(f"{index}. {rule}")
        if self.custom_summary_example:
            sections.append(f"示例输出:\n{self.custom_summary_example}")
        return "\n".join(sections)

    def _get_effective_summary_config(self) -> Dict[str, Any]:
        if self.enable_custom_summary and self._has_custom_content():
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
        if not custom_rules:
            return list(default_rules)
        rules = [rule.strip() for rule in custom_rules.split("\n") if rule.strip()]
        return rules if rules else list(default_rules)

    def initialize(self) -> bool:
        self._refresh_config()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.daily_dir.mkdir(parents=True, exist_ok=True)
        self.summaries_dir.mkdir(parents=True, exist_ok=True)
        self._start_auto_fetch_scheduler()
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
            "fetch_user_tweets": self.fetch_user_tweets,
            "read_twitter_cache": self.read_twitter_cache,
            "get_twitter_daily_tweets": self.get_twitter_daily_tweets,
            "get_twitter_stats": self.get_twitter_stats,
            "search_twitter_users": self.search_twitter_users,
            "search_tweets": self.search_tweets,
            "get_twitter_user_info": self.get_twitter_user_info,
            "get_tweet_replies": self.get_tweet_replies,
            "get_user_followers": self.get_user_followers,
            "get_user_following": self.get_user_following,
            "summarize_twitter_tweets": self.summarize_twitter_tweets,
            "trigger_auto_fetch": self.trigger_auto_fetch,
            "start_auto_fetch_scheduler": self.start_auto_fetch_scheduler,
            "stop_auto_fetch_scheduler": self.stop_auto_fetch_scheduler,
            "get_scheduler_status": self.get_scheduler_status,
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
        self._stop_auto_fetch_scheduler()
        super().cleanup()

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
            self._write_json_payload(self.plugin_root / "data" / "latest.json", "latest", deduplicated)

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
        """将 API 原始推文数据简化为统一字段结构（snake_case）

        参数:
            tweet: Twitter API 返回的原始推文字典

        返回:
            简化后的推文字典，包含 author、metrics、entities 等完整字段
        """
        author = tweet.get("author") or {}

        # 简化 entities（hashtags / urls / user_mentions）
        entities = tweet.get("entities") or {}
        if isinstance(entities, dict):
            hashtags = [h.get("text", "") for h in entities.get("hashtags", []) if isinstance(h, dict)]
            urls = [
                {"display_url": u.get("display_url", ""), "expanded_url": u.get("expanded_url", "")}
                for u in entities.get("urls", []) if isinstance(u, dict)
            ]
            user_mentions = [
                {"screen_name": m.get("screen_name", ""), "name": m.get("name", "")}
                for m in entities.get("user_mentions", []) if isinstance(m, dict)
            ]
        else:
            hashtags = []
            urls = []
            user_mentions = []

        # 简化引用推文（quoted_tweet）
        quoted = tweet.get("quoted_tweet") or {}
        quoted_simplified = None
        if isinstance(quoted, dict) and quoted.get("id"):
            q_author = quoted.get("author") or {}
            quoted_simplified = {
                "id": str(quoted.get("id", "")),
                "text": str(quoted.get("text", ""))[:200],
                "author": {"user_name": str(q_author.get("userName") or "").strip()},
            }

        # 简化转推（retweeted_tweet）
        retweeted = tweet.get("retweeted_tweet") or {}
        retweeted_simplified = None
        if isinstance(retweeted, dict) and retweeted.get("id"):
            r_author = retweeted.get("author") or {}
            retweeted_simplified = {
                "id": str(retweeted.get("id", "")),
                "text": str(retweeted.get("text", ""))[:200],
                "author": {"user_name": str(r_author.get("userName") or "").strip()},
            }

        return {
            "id": str(tweet.get("id") or ""),
            "text": str(tweet.get("text") or "").strip(),
            "created_at": str(tweet.get("createdAt") or tweet.get("created_at") or ""),
            "url": str(tweet.get("url") or tweet.get("twitterUrl") or ""),
            "lang": str(tweet.get("lang") or ""),
            "is_reply": bool(tweet.get("isReply")),
            "in_reply_to_id": str(tweet.get("inReplyToId") or ""),
            "in_reply_to_user_id": str(tweet.get("inReplyToUserId") or ""),
            "in_reply_to_username": str(tweet.get("inReplyToUsername") or ""),
            "conversation_id": str(tweet.get("conversationId") or ""),
            "author": {
                "user_name": str(author.get("userName") or author.get("user_name") or "").strip(),
                "name": str(author.get("name") or "").strip(),
            },
            "metrics": {
                "likes": int(tweet.get("likeCount") or tweet.get("like_count") or 0),
                "retweets": int(tweet.get("retweetCount") or tweet.get("retweet_count") or 0),
                "replies": int(tweet.get("replyCount") or tweet.get("reply_count") or 0),
                "quotes": int(tweet.get("quoteCount") or tweet.get("quote_count") or 0),
                "views": int(tweet.get("viewCount") or tweet.get("view_count") or 0),
                "bookmarks": int(tweet.get("bookmarkCount") or tweet.get("bookmark_count") or 0),
            },
            "entities": {
                "hashtags": hashtags,
                "urls": urls,
                "user_mentions": user_mentions,
            },
            "quoted_tweet": quoted_simplified,
            "retweeted_tweet": retweeted_simplified,
        }

    def _check_api_ready(self) -> Optional[Dict[str, Any]]:
        """检查 API 客户端是否可用，不可用时返回错误信息"""
        if self._twitter_api is None:
            return {"status": "error", "message": "未配置 twitter_api_key，请在插件设置中添加 Twitter API 密钥"}
        return None

    def fetch_user_tweets(
        self,
        user_name: str = None,
        limit: int = 10
    ) -> Dict[str, Any]:
        normalized_user = str(user_name or "").strip().lstrip("@")
        normalized_limit = _coerce_int(limit, 10, minimum=1, maximum=100)
        if not normalized_user:
            return {"status": "error", "message": "user_name 不能为空，请用户提供要搜索的 Twitter 用户名"}

        api_error = self._check_api_ready()
        if api_error:
            return api_error

        api_result = self._twitter_api.get_user_last_tweets(
            user_name=normalized_user,
            include_replies=self.include_replies,
            limit=normalized_limit,
        )
        if not api_result.get("success"):
            return {"status": "error", "message": api_result.get("error", "Twitter API 请求失败")}

        raw_tweets = api_result.get("tweets", [])
        simplified = [self._simplify_tweet(item) for item in raw_tweets[:normalized_limit]]

        deduplicated = self._deduplicate_tweets(simplified)
        added_count = self._save_fetched_tweets(deduplicated)

        return {
            "status": "success",
            "user_name": normalized_user,
            "limit": normalized_limit,
            "fetched_count": len(deduplicated),
            "new_daily_count": added_count,
            "tweets": deduplicated,
        }

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

        api_error = self._check_api_ready()
        if api_error:
            return api_error

        per_user_limit = _coerce_int(limit, self.tweets_per_user, minimum=1, maximum=50)
        include_reply_flag = self.include_replies if include_replies is None else _coerce_bool(include_replies)

        collected_tweets: List[Dict[str, Any]] = []
        results: List[Dict[str, Any]] = []
        errors: List[Dict[str, Any]] = []

        for user_name in selected_users:
            api_result = self._twitter_api.get_user_last_tweets(
                user_name=user_name,
                include_replies=include_reply_flag,
                limit=per_user_limit,
            )
            if not api_result.get("success"):
                error_item = {
                    "user_name": user_name,
                    "message": api_result.get("error", "抓取失败"),
                }
                errors.append(error_item)
                results.append({"user_name": user_name, "status": "error", "count": 0, "message": error_item["message"]})
                continue

            raw_tweets = api_result.get("tweets", [])
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
        payload = self._read_json_payload(self.data_dir / "latest.json")
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
            latest_path = self.plugin_root / "data" / "latest.json"
            payload = self._read_json_payload(latest_path)
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

        api_error = self._check_api_ready()
        if api_error:
            return api_error

        api_result = self._twitter_api.search_users(normalized_query)
        if not api_result.get("success"):
            return {"status": "error", "message": api_result.get("error", "搜索用户失败")}

        users = api_result.get("users", [])
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

        api_error = self._check_api_ready()
        if api_error:
            return api_error

        api_result = self._twitter_api.get_user_info(normalized_user)
        if not api_result.get("success"):
            return {"status": "not_found", "message": f"未找到用户: {normalized_user}"}

        user = api_result.get("user", {})
        return {
            "status": "success",
            "user": {
                "id": str(user.get("id") or ""),
                "user_name": str(user.get("userName") or "").strip(),
                "name": str(user.get("name") or "").strip(),
                "description": str(user.get("description") or "").strip(),
                "followers": int(user.get("followers") or 0),
                "following": int(user.get("following") or 0),
                "profile_picture": str(user.get("profilePicture") or ""),
                "cover_picture": str(user.get("coverPicture") or ""),
                "is_blue_verified": bool(user.get("isBlueVerified")),
                "verified_type": str(user.get("verifiedType") or ""),
                "location": str(user.get("location") or ""),
                "statuses_count": int(user.get("statusesCount") or 0),
                "favourites_count": int(user.get("favouritesCount") or 0),
                "created_at": str(user.get("createdAt") or ""),
            },
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

    def _call_external_ai_for_summary(self, prompt: str, system_prompt: str = None) -> str:
        effective_system = system_prompt or DEFAULT_SYSTEM_PROMPT

        if self.ai_model_config_id is None:
            return "未配置 AI 模型（ai_model_config_id 为空），请在插件设置中选择一个平台已配置的 AI 模型。"

        db = None
        try:
            if self.context is None:
                return "插件上下文不可用，无法解析模型配置。请联系管理员。"
            db = self.context.get_db_session()
            if db is None:
                return "无法获取数据库会话，无法解析模型配置。"
            pricing_mgr = PricingManager(db)
            config = pricing_mgr.get_configuration(self.ai_model_config_id)
            if config is None:
                return f"未找到 ID 为 {self.ai_model_config_id} 的模型配置，请检查插件设置中的 AI 模型选择。"
            if not config.api_key or not config.api_endpoint:
                return f"模型配置 '{config.display_name or config.model}' 缺少 API 密钥或端点，请检查平台计费配置。"

            selected_models = PricingManager.parse_selected_models(getattr(config, "selected_models", None))
            effective_model = config.model
            placeholder_keywords = {"custom-model", "custom_model", "custom", "default-model", "default"}
            if effective_model.lower() in placeholder_keywords or not effective_model:
                effective_model = selected_models[0] if selected_models else effective_model

            endpoint_suffixes = PricingManager.get_provider_endpoint_suffixes(config.provider)
            chat_suffix = endpoint_suffixes.get("chat", "/chat/completions")
            url = f"{config.api_endpoint.rstrip('/')}{chat_suffix}"

            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {config.api_key}"
            }
            payload = {
                "model": effective_model,
                "messages": [
                    {"role": "system", "content": effective_system},
                    {"role": "user", "content": prompt}
                ],
                "temperature": 0.3,
                "max_tokens": 4096
            }

            response = requests.post(url, headers=headers, json=payload, timeout=120)
            response.raise_for_status()
            data = response.json()
            content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            return content
        except Exception as e:
            logger.error(f"[{self.name}] AI 总结调用失败: {e}")
            return f"AI 总结调用失败: {e}"
        finally:
            if db is not None:
                db.close()

    def trigger_auto_fetch(self) -> Dict[str, Any]:
        if not self.monitored_users:
            return {"status": "error", "message": "未配置 monitored_users，请在插件设置中添加要监控的用户"}
        if not self.twitter_api_key:
            return {"status": "error", "message": "未配置 twitter_api_key，请在插件设置中添加 Twitter API 密钥"}

        result = self.fetch_twitter_tweets(
            user_names=self.monitored_users,
            limit=self.tweets_per_user,
            storage_mode="both"
        )

        if result.get("status") != "success":
            return result

        tweets = result.get("tweets", [])
        summary_result = None

        if tweets:
            if self._summarizer:
                today_date = date.today()
                summary_filename = f"summary_{today_date.isoformat()}_daily.txt"
                summary_path = str(self.summaries_dir / summary_filename)

                summary_result = self._summarizer.summarize_by_user(
                    tweets=tweets,
                    save_path=summary_path
                )

        return {
            "status": "success",
            "message": f"自动获取完成，已抓取 {len(self.monitored_users)} 个用户的推文",
            "fetched_count": result.get("fetched_count", 0),
            "new_daily_count": result.get("new_daily_count", 0),
            "monitored_users": self.monitored_users,
            "tweets_per_user": self.tweets_per_user,
            "summary": summary_result.get("content") if summary_result and summary_result.get("success") else "未生成总结（如需自动总结请在插件设置中选择 AI 模型）"
        }

    def start_auto_fetch_scheduler(self) -> Dict[str, Any]:
        if self._scheduler_thread and self._scheduler_thread.is_alive():
            return {"status": "info", "message": "自动获取调度器已在运行中"}

        if not self.monitored_users:
            return {"status": "error", "message": "未配置 monitored_users，无法启动调度器"}
        if not self.twitter_api_key:
            return {"status": "error", "message": "未配置 twitter_api_key，无法启动调度器"}

        self._start_auto_fetch_scheduler()
        return {
            "status": "success",
            "message": f"自动获取调度器已启动，间隔 {self.auto_fetch_interval_hours} 小时",
            "auto_fetch_interval_hours": self.auto_fetch_interval_hours,
            "monitored_users": self.monitored_users,
            "tweets_per_user": self.tweets_per_user
        }

    def stop_auto_fetch_scheduler(self) -> Dict[str, Any]:
        self._stop_auto_fetch_scheduler()
        return {"status": "success", "message": "自动获取调度器已停止"}

    def get_scheduler_status(self) -> Dict[str, Any]:
        is_running = self._scheduler_thread is not None and self._scheduler_thread.is_alive()
        return {
            "status": "success",
            "scheduler_running": is_running,
            "monitored_users": self.monitored_users,
            "tweets_per_user": self.tweets_per_user,
            "auto_fetch_interval_hours": self.auto_fetch_interval_hours,
            "has_twitter_api_key": bool(self.twitter_api_key),
            "has_ai_model_config": self.ai_model_config_id is not None
        }

    def _start_auto_fetch_scheduler(self) -> None:
        with self._scheduler_lock:
            if self._scheduler_thread and self._scheduler_thread.is_alive():
                return
            self._scheduler_stop.clear()
            self._scheduler_thread = threading.Thread(
                target=self._auto_fetch_loop,
                daemon=True,
                name=f"{self.name}-auto-fetch-scheduler"
            )
            self._scheduler_thread.start()
            logger.info(f"[{self.name}] 自动获取调度器已启动")

    def _stop_auto_fetch_scheduler(self) -> None:
        with self._scheduler_lock:
            if self._scheduler_thread and self._scheduler_thread.is_alive():
                self._scheduler_stop.set()
                self._scheduler_thread.join(timeout=10)
                self._scheduler_thread = None
                logger.info(f"[{self.name}] 自动获取调度器已停止")

    def _auto_fetch_loop(self) -> None:
        interval_seconds = self.auto_fetch_interval_hours * 3600
        logger.info(
            f"[{self.name}] 自动获取循环已启动，间隔 {self.auto_fetch_interval_hours} 小时"
        )

        while not self._scheduler_stop.is_set():
            self._refresh_config()
            current_users = self.monitored_users
            current_count = self.tweets_per_user
            current_interval = self.auto_fetch_interval_hours

            if not current_users or not self.twitter_api_key:
                logger.warning(f"[{self.name}] 自动获取跳过：未配置 monitored_users 或 api_key")
            else:
                try:
                    logger.info(
                        f"[{self.name}] 开始自动获取 {len(current_users)} 个用户的推文"
                    )
                    for user in current_users:
                        if self._scheduler_stop.is_set():
                            break
                        time.sleep(1.5)
                        user_result = self._twitter_api.get_user_last_tweets(
                            user_name=user,
                            include_replies=self.include_replies,
                            limit=current_count,
                        )
                        if user_result.get("success"):
                            raw_tweets = user_result.get("tweets", [])
                            simplified = [self._simplify_tweet(t) for t in raw_tweets[:current_count]]
                            if simplified:
                                added = self._save_fetched_tweets(simplified)
                                logger.info(
                                    f"[{self.name}] 自动获取 @{user}: "
                                    f"获取 {len(simplified)} 条，新增 {added} 条"
                                )

                    all_daily_tweets = []
                    today = date.today()
                    for user in current_users:
                        user_tweets_path = self.daily_dir / f"{today.isoformat()}.json"
                        payload = self._read_json_payload(user_tweets_path)
                        tweets = payload.get("tweets", []) if isinstance(payload.get("tweets"), list) else []
                        for t in tweets:
                            if t.get("author", {}).get("user_name", "").lower() == user.lower():
                                all_daily_tweets.append(t)

                    if all_daily_tweets and self.ai_model_config_id is not None:
                        summary_filename = f"summary_{today.isoformat()}_daily.txt"
                        summary_path = str(self.summaries_dir / summary_filename)

                        summary_result = self._summarizer.summarize_by_user(
                            tweets=all_daily_tweets,
                            save_path=summary_path
                        )

                        if summary_result.get("success"):
                            logger.info(
                                f"[{self.name}] 自动总结完成: "
                                f"{summary_result.get('tweets_count', 0)} 条推文"
                            )
                        else:
                            logger.warning(
                                f"[{self.name}] 自动总结失败: {summary_result.get('error', '未知错误')}"
                            )
                    elif all_daily_tweets:
                        logger.info(
                            f"[{self.name}] 推文已保存，未配置 AI API 密钥，跳过自动总结"
                        )

                except Exception as e:
                    logger.error(f"[{self.name}] 自动获取过程出错: {e}")

            if self._scheduler_stop.wait(interval_seconds):
                break

    # ==================== 新增工具：推文高级搜索 ====================

    def search_tweets(
        self,
        query: str,
        query_type: str = "Latest",
        limit: Optional[int] = 20,
    ) -> Dict[str, Any]:
        """高级推文搜索并缓存结果

        使用 Twitter 高级搜索语法搜索推文，支持 from:user、关键词、
        since_time/until_time 等语法。结果会写入 latest 和 daily 缓存。

        参数:
            query: 搜索查询（必填），支持 Twitter 高级搜索语法
            query_type: 搜索类型，"Latest" 或 "Top"，默认 "Latest"
            limit: 最多返回多少条推文

        返回:
            包含搜索结果的字典
        """
        normalized_query = str(query or "").strip()
        if not normalized_query:
            return {"status": "error", "message": "query 不能为空"}

        api_error = self._check_api_ready()
        if api_error:
            return api_error

        normalized_limit = _coerce_int(limit, 20, minimum=1, maximum=100)
        normalized_query_type = "Latest"
        if str(query_type).strip().lower() == "top":
            normalized_query_type = "Top"

        api_result = self._twitter_api.search_tweets(
            query=normalized_query,
            query_type=normalized_query_type,
        )
        if not api_result.get("success"):
            return {"status": "error", "message": api_result.get("error", "推文搜索失败")}

        raw_tweets = api_result.get("tweets", [])
        simplified = [self._simplify_tweet(item) for item in raw_tweets[:normalized_limit]]
        deduplicated = self._deduplicate_tweets(simplified)
        added_count = self._save_fetched_tweets(deduplicated)

        return {
            "status": "success",
            "query": normalized_query,
            "query_type": normalized_query_type,
            "fetched_count": len(deduplicated),
            "new_daily_count": added_count,
            "has_next_page": api_result.get("has_next_page", False),
            "next_cursor": api_result.get("next_cursor", ""),
            "tweets": deduplicated,
        }

    # ==================== 新增工具：推文回复 ====================

    def get_tweet_replies(
        self,
        tweet_id: str,
        limit: Optional[int] = 20,
    ) -> Dict[str, Any]:
        """获取指定推文的回复列表

        使用 GET /twitter/tweet/replies 端点获取推文回复。
        注意：仅支持查询原始推文（非回复推文）的回复。

        参数:
            tweet_id: 要查询回复的推文 ID（必填）
            limit: 最多返回多少条回复

        返回:
            包含回复列表的字典
        """
        normalized_tweet_id = str(tweet_id or "").strip()
        if not normalized_tweet_id:
            return {"status": "error", "message": "tweet_id 不能为空"}

        api_error = self._check_api_ready()
        if api_error:
            return api_error

        normalized_limit = _coerce_int(limit, 20, minimum=1, maximum=100)

        api_result = self._twitter_api.get_tweet_replies(tweet_id=normalized_tweet_id)
        if not api_result.get("success"):
            return {"status": "error", "message": api_result.get("error", "获取推文回复失败")}

        raw_replies = api_result.get("replies", [])
        simplified = [self._simplify_tweet(item) for item in raw_replies[:normalized_limit]]

        return {
            "status": "success",
            "tweet_id": normalized_tweet_id,
            "count": len(simplified),
            "has_next_page": api_result.get("has_next_page", False),
            "next_cursor": api_result.get("next_cursor", ""),
            "replies": simplified,
        }

    # ==================== 新增工具：粉丝与关注列表 ====================

    def get_user_followers(
        self,
        user_name: str,
        limit: Optional[int] = 100,
    ) -> Dict[str, Any]:
        """获取用户粉丝列表

        使用 GET /twitter/user/followers 端点，按关注时间倒序排列。
        每页最多返回 200 条。

        参数:
            user_name: Twitter 用户名（不含 @，必填）
            limit: 最多返回多少粉丝

        返回:
            包含粉丝列表的字典
        """
        normalized_user = str(user_name or "").strip().lstrip("@")
        if not normalized_user:
            return {"status": "error", "message": "user_name 不能为空"}

        api_error = self._check_api_ready()
        if api_error:
            return api_error

        normalized_limit = _coerce_int(limit, 100, minimum=1, maximum=500)

        api_result = self._twitter_api.get_user_followers(
            user_name=normalized_user,
            page_size=min(normalized_limit, 200),
        )
        if not api_result.get("success"):
            return {"status": "error", "message": api_result.get("error", "获取粉丝列表失败")}

        # 简化用户数据
        simplified_users = []
        for follower in api_result.get("followers", [])[:normalized_limit]:
            simplified_users.append({
                "user_name": str(follower.get("userName") or "").strip(),
                "name": str(follower.get("name") or "").strip(),
                "description": str(follower.get("description") or "").strip(),
                "followers": int(follower.get("followers") or 0),
                "following": int(follower.get("following") or 0),
                "profile_picture": str(follower.get("profilePicture") or ""),
                "is_blue_verified": bool(follower.get("isBlueVerified")),
            })

        return {
            "status": "success",
            "user_name": normalized_user,
            "count": len(simplified_users),
            "has_next_page": api_result.get("has_next_page", False),
            "followers": simplified_users,
        }

    def get_user_following(
        self,
        user_name: str,
        limit: Optional[int] = 100,
    ) -> Dict[str, Any]:
        """获取用户关注列表

        使用 GET /twitter/user/followings 端点，按关注时间倒序排列。
        每页最多返回 200 条。

        参数:
            user_name: Twitter 用户名（不含 @，必填）
            limit: 最多返回多少关注用户

        返回:
            包含关注列表的字典
        """
        normalized_user = str(user_name or "").strip().lstrip("@")
        if not normalized_user:
            return {"status": "error", "message": "user_name 不能为空"}

        api_error = self._check_api_ready()
        if api_error:
            return api_error

        normalized_limit = _coerce_int(limit, 100, minimum=1, maximum=500)

        api_result = self._twitter_api.get_user_followings(
            user_name=normalized_user,
            page_size=min(normalized_limit, 200),
        )
        if not api_result.get("success"):
            return {"status": "error", "message": api_result.get("error", "获取关注列表失败")}

        # 简化用户数据
        simplified_users = []
        for following in api_result.get("followings", [])[:normalized_limit]:
            simplified_users.append({
                "user_name": str(following.get("userName") or "").strip(),
                "name": str(following.get("name") or "").strip(),
                "description": str(following.get("description") or "").strip(),
                "followers": int(following.get("followers") or 0),
                "following": int(following.get("following") or 0),
                "profile_picture": str(following.get("profilePicture") or ""),
                "is_blue_verified": bool(following.get("isBlueVerified")),
            })

        return {
            "status": "success",
            "user_name": normalized_user,
            "count": len(simplified_users),
            "has_next_page": api_result.get("has_next_page", False),
            "followings": simplified_users,
        }

    def get_tools(self) -> List[Dict[str, Any]]:
        return [
            {
                "name": "fetch_user_tweets",
                "method": "fetch_user_tweets",
                "description": "获取指定 Twitter 用户的指定数量推文（用户必须提供推文数量），同时写入缓存",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "user_name": {
                            "type": "string",
                            "description": "要获取推文的 Twitter 用户名（必填）"
                        },
                        "limit": {
                            "type": "integer",
                            "description": "要获取的推文数量，用户必须填写具体数字（必填）"
                        }
                    },
                    "required": ["user_name", "limit"]
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
                "name": "fetch_twitter_tweets",
                "method": "fetch_twitter_tweets",
                "description": "批量抓取一个或多个 Twitter 账号的最新推文，并同步写入 latest 与 daily 缓存",
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
                "name": "get_twitter_user_info",
                "method": "get_twitter_user_info",
                "description": "获取指定 Twitter 用户的详细账号信息（包含认证状态、简介、粉丝数等）",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "user_name": {"type": "string", "description": "目标用户名"}
                    },
                    "required": ["user_name"]
                }
            },
            {
                "name": "search_tweets",
                "method": "search_tweets",
                "description": "使用 Twitter 高级搜索语法搜索推文，支持 from:user、关键词、时间范围等过滤条件，结果会自动缓存",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "搜索查询（必填），支持 Twitter 高级搜索语法，如 'AI from:elonmusk'"
                        },
                        "query_type": {
                            "type": "string",
                            "enum": ["Latest", "Top"],
                            "description": "搜索类型：Latest 按时间排序，Top 按热度排序，默认 Latest"
                        },
                        "limit": {
                            "type": "integer",
                            "description": "最多返回多少条推文，默认 20"
                        }
                    },
                    "required": ["query"]
                }
            },
            {
                "name": "get_tweet_replies",
                "method": "get_tweet_replies",
                "description": "获取指定推文的回复列表，仅支持查询原始推文（非回复推文）的回复",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "tweet_id": {
                            "type": "string",
                            "description": "要查询回复的推文 ID（必填）"
                        },
                        "limit": {
                            "type": "integer",
                            "description": "最多返回多少条回复，默认 20"
                        }
                    },
                    "required": ["tweet_id"]
                }
            },
            {
                "name": "get_user_followers",
                "method": "get_user_followers",
                "description": "获取指定 Twitter 用户的粉丝列表，按关注时间倒序排列",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "user_name": {
                            "type": "string",
                            "description": "Twitter 用户名（必填，不含 @）"
                        },
                        "limit": {
                            "type": "integer",
                            "description": "最多返回多少粉丝，默认 100"
                        }
                    },
                    "required": ["user_name"]
                }
            },
            {
                "name": "get_user_following",
                "method": "get_user_following",
                "description": "获取指定 Twitter 用户关注的用户列表，按关注时间倒序排列",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "user_name": {
                            "type": "string",
                            "description": "Twitter 用户名（必填，不含 @）"
                        },
                        "limit": {
                            "type": "integer",
                            "description": "最多返回多少关注用户，默认 100"
                        }
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
            },
            {
                "name": "trigger_auto_fetch",
                "method": "trigger_auto_fetch",
                "description": "手动触发一次自动获取：获取插件配置中 monitored_users 的最新推文并自动总结",
                "parameters": {
                    "type": "object",
                    "properties": {}
                }
            },
            {
                "name": "start_auto_fetch_scheduler",
                "method": "start_auto_fetch_scheduler",
                "description": "启动后台自动获取调度器，按配置的间隔定时获取推文",
                "parameters": {
                    "type": "object",
                    "properties": {}
                }
            },
            {
                "name": "stop_auto_fetch_scheduler",
                "method": "stop_auto_fetch_scheduler",
                "description": "停止后台自动获取调度器",
                "parameters": {
                    "type": "object",
                    "properties": {}
                }
            },
            {
                "name": "get_scheduler_status",
                "method": "get_scheduler_status",
                "description": "查看自动获取调度器的运行状态和配置",
                "parameters": {
                    "type": "object",
                    "properties": {}
                }
            }
        ]
