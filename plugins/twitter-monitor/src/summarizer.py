import os
from datetime import datetime
from typing import Dict, List, Optional, Callable


DEFAULT_SYSTEM_PROMPT = """你是一名 AI 行业速报编辑，AI行业每天都有爆炸式的信息，而你擅长从中抓取到真正的价值。
你的核心目标是输出「是否有重要动态」+「核心内容摘要」+「价值判断」。

# 判断逻辑（按优先级）
1、新开源模型（关键词：release, Open source, 开源, 发布, SOTA, Qwen, GLM 等开源模型发布或更新）
2、商业大模型更新（关键词：ChatGPT, Claude, Gemini, Grok, Kimi, MiniMax 等闭源模型动态）
3、模型实测结论（关键词：对比, 跑测试, 实测, 差距）
4、AI产品/工具发布与更新（关键词：API, 推出, 试玩, Sora, Codex, 等AI工具动态）
5、github开源项目（关键词：star, 工具, 开源, 分享, 爆火, 含有github.com链接）
6、提示词创新（出现prompt，实用性工具性的提示词模板）
7、机器人/硬件相关（关键词：Boston Dynamics, Figure, Optimus, 树莓派 等）
8、重大软件的更新（关键词：Chrome、Vscode等）

只有推文中直接提及或隐含这些事件行为（发布、上线、开放、更新、宣布、推出）时，才视为"有动态"。

# 输出要求
## 第一部分
用一句话说明整体结论：
- 如果没有检测到符合条件的内容，输出："暂无重大动态。"
- 如果检测到，输出："有 X 条重要动态。"

## 第二部分
逐条总结：
- 每条最多 5 行。
- 信息量小的，用一句话概括，越精简越好不必换行。
- 信息量大的，再用以下格式：

一、事件标题（用一句话抓住主干）
细节1：
细节2：

## 第三部分
AI总结：针对以上内容做总结。

# 语言要求
- 全中文输出，但可保留必要的英文关键词。
- 严禁出现"以下是结果""我认为"等AI自述语。
- 不得输出任何格式说明、推理过程或无关评论。
- 再次精简"""


class AISummarizer:
    """AI 推文总结器

    负责格式化推文数据，通过项目 AI 能力进行总结，并保存结果。
    接受外部传入的 ai_call_func 来调用项目自身的 AI 能力。
    """

    def __init__(
        self,
        summaries_dir: str,
        ai_call_func: Callable,
        system_prompt: str = None
    ):
        """初始化总结器

        参数:
            summaries_dir: 总结文件保存目录的绝对路径
            ai_call_func: 调用项目 AI 的回调函数，签名: func(prompt: str) -> str
            system_prompt: 可选的系统提示词，默认使用 AI 行业速报提示词
        """
        self.summaries_dir = summaries_dir
        os.makedirs(summaries_dir, exist_ok=True)
        self.ai_call_func = ai_call_func
        self.system_prompt = system_prompt or DEFAULT_SYSTEM_PROMPT

    def format_tweets(self, tweets: List[Dict]) -> str:
        """将推文数据格式化为易读文本，使用统一 snake_case 字段"""
        if not tweets:
            return "没有找到推文数据。"

        formatted_text = f"共有 {len(tweets)} 条推文待总结：\n\n"

        for i, tweet in enumerate(tweets, 1):
            author = tweet.get("author", {})
            author_name = author.get("name", "Unknown")
            author_username = author.get("user_name", "unknown")
            text = tweet.get("text", "")
            created_at = tweet.get("created_at", "")
            url = tweet.get("url", "")
            lang = tweet.get("lang", "")
            metrics = tweet.get("metrics", {})
            likes = metrics.get("likes", 0)
            retweets = metrics.get("retweets", 0)
            replies = metrics.get("replies", 0)
            quotes = metrics.get("quotes", 0)
            views = metrics.get("views", 0)

            formatted_text += f"--- 推文 {i} ---\n"
            formatted_text += f"作者: {author_name} (@{author_username})\n"
            formatted_text += f"时间: {created_at}\n"
            if lang:
                formatted_text += f"语言: {lang}\n"
            formatted_text += f"内容: {text}\n"
            if url:
                formatted_text += f"链接: {url}\n"
            formatted_text += f"点赞: {likes} | 转发: {retweets} | 回复: {replies} | 引用: {quotes} | 浏览: {views}\n\n"

        return formatted_text

    def summarize_tweets(
        self,
        tweets: List[Dict],
        save_path: Optional[str] = None
    ) -> Dict:
        """总结推文内容

        参数:
            tweets: 推文列表
            save_path: 可选，保存结果的文件路径

        返回:
            {"success": bool, "content": str, "tweets_count": int, "saved_path": str}
        """
        if not tweets:
            return {"success": False, "error": "没有推文数据", "content": None}

        formatted_text = self.format_tweets(tweets)

        try:
            result = self.ai_call_func(
                prompt=formatted_text,
                system_prompt=self.system_prompt
            )

            saved_path = None
            if save_path:
                os.makedirs(os.path.dirname(save_path), exist_ok=True)
                with open(save_path, 'w', encoding='utf-8') as f:
                    f.write(result)
                saved_path = save_path

            return {
                "success": True,
                "content": result,
                "tweets_count": len(tweets),
                "saved_path": saved_path
            }

        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "content": None,
                "tweets_count": len(tweets)
            }

    def summarize_by_user(
        self,
        tweets: List[Dict],
        save_path: Optional[str] = None
    ) -> Dict:
        """按用户分组总结推文"""
        if not tweets:
            return {"success": False, "error": "没有推文数据"}

        user_tweets = {}
        for tweet in tweets:
            username = tweet.get("author", {}).get("user_name", "unknown")
            if username not in user_tweets:
                user_tweets[username] = []
            user_tweets[username].append(tweet)

        all_summaries = []
        for username, user_tweet_list in user_tweets.items():
            user_prompt = f"请总结以下 @{username} 发布的推文内容：\n\n"
            user_prompt += self.format_tweets(user_tweet_list)

            result = self.ai_call_func(
                prompt=user_prompt,
                system_prompt=self.system_prompt
            )

            all_summaries.append(f"=== @{username} 的推文总结 ===\n\n")
            all_summaries.append(result)
            all_summaries.append("\n\n")

        output = "".join(all_summaries)

        saved_path = None
        if save_path:
            os.makedirs(os.path.dirname(save_path), exist_ok=True)
            with open(save_path, 'w', encoding='utf-8') as f:
                f.write(output)
            saved_path = save_path

        return {
            "success": True,
            "content": output,
            "tweets_count": len(tweets),
            "users_count": len(user_tweets),
            "saved_path": saved_path
        }
