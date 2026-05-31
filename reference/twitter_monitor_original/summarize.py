# -*- coding: utf-8 -*-
"""
AI推文总结主程序

功能概述:
    - 读取历史推文数据
    - 调用AI进行总结
    - 保存总结结果

使用示例:
    # 总结今天的推文
    python summarize.py
    
    # 总结特定日期的推文
    python summarize.py --date 2024-01-15
    
    # 总结latest数据
    python summarize.py --source latest
    
    # 按用户分组总结
    python summarize.py --by-user
    
    # 预览模式（不调用AI）
    python summarize.py --preview
"""

import json
import argparse
import importlib.util
from datetime import datetime, date
from pathlib import Path
from typing import Dict, List, Optional

from core.storage import TweetStorage


def load_ai_config(config_path: str) -> dict:
    """
    加载AI配置
    
    参数:
        config_path: 配置文件路径（.py或.json）
        
    返回:
        AI配置字典
    """
    config_path = Path(config_path)
    
    if config_path.suffix == '.py':
        spec = importlib.util.spec_from_file_location("ai_config", config_path)
        config_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(config_module)
        return config_module.ai_config
    else:
        with open(config_path, 'r', encoding='utf-8') as f:
            return json.load(f)


def get_tweets_from_storage(
    storage: TweetStorage,
    source_type: str,
    target_date: Optional[date] = None
) -> List[Dict]:
    """
    从存储中获取推文
    
    参数:
        storage: TweetStorage实例
        source_type: 来源类型 ("latest" 或 "daily")
        target_date: 目标日期（仅用于daily）
        
    返回:
        推文列表
    """
    if source_type == "latest":
        print("[信息] 从 latest.json 获取推文...")
        tweets = storage.get_all_tweets("latest")
    else:
        if target_date is None:
            target_date = date.today()
        print(f"[信息] 从 daily/{target_date.isoformat()}.json 获取推文...")
        tweets = storage.get_tweets_by_date(target_date)
    
    return tweets


def generate_output_path(
    config: dict,
    source_type: str,
    target_date: Optional[date] = None
) -> str:
    """
    生成输出文件路径
    
    参数:
        config: AI配置
        source_type: 来源类型
        target_date: 目标日期
        
    返回:
        文件路径字符串
    """
    output_config = config.get("output_config", {})
    output_dir = output_config.get("output_dir", "data/summaries")
    
    if target_date is None:
        target_date = date.today()
    
    filename_format = output_config.get("filename_format", "summary_{date}_{source}.txt")
    filename = filename_format.format(
        date=target_date.isoformat(),
        source=source_type
    )
    
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    
    return str(Path(output_dir) / filename)


def preview_tweets(tweets: List[Dict], max_count: int = 10):
    """
    预览推文数据
    
    参数:
        tweets: 推文列表
        max_count: 最大显示数量
    """
    print("\n" + "="*60)
    print("推文预览")
    print("="*60)
    
    if not tweets:
        print("没有找到推文数据")
        return
    
    print(f"共 {len(tweets)} 条推文\n")
    
    for i, tweet in enumerate(tweets[:max_count], 1):
        author = tweet.get("author", {})
        username = author.get("userName", "unknown")
        text = tweet.get("text", "")[:100]
        created_at = tweet.get("createdAt", "")
        
        print(f"[{i}] @{username}: {text}...")
        print(f"    时间: {created_at}\n")
    
    if len(tweets) > max_count:
        print(f"... 还有 {len(tweets) - max_count} 条推文")


def summarize(config_path: str, args):
    """
    执行总结
    
    参数:
        config_path: AI配置文件路径
        args: 命令行参数
    """
    print("="*60)
    print("AI推文总结工具")
    print("="*60)
    
    config = load_ai_config(config_path)
    
    if config.get("api_key") == "your_api_key_here":
        print("\n[错误] 请先在 config/ai_config.py 中设置API密钥！")
        return
    
    from core.ai_summarizer import AISummarizer
    
    summarizer = AISummarizer(config)
    
    source_type = args.source or config.get("input_config", {}).get("source_type", "daily")
    target_date = None
    
    if args.date:
        try:
            target_date = date.fromisoformat(args.date)
        except ValueError:
            print(f"\n[错误] 日期格式无效: {args.date}")
            return
    
    storage = TweetStorage(config)
    
    tweets = get_tweets_from_storage(storage, source_type, target_date)
    
    if not tweets:
        print("\n[错误] 没有找到推文数据")
        print("请先运行 monitor.py 抓取推文数据")
        return
    
    print(f"[信息] 加载了 {len(tweets)} 条推文")
    
    if args.preview:
        preview_tweets(tweets, max_count=args.max_preview or 10)
        return
    
    output_path = None
    if args.output:
        output_path = args.output
    elif config.get("output_config", {}).get("save_to_file", True):
        output_path = generate_output_path(config, source_type, target_date)
    
    if args.by_user:
        result = summarizer.summarize_by_user(tweets, output_path)
    else:
        result = summarizer.summarize_tweets(tweets, output_path)
    
    if result["success"]:
        print("\n" + "="*60)
        print("总结完成！")
        print("="*60)
        
        if output_path:
            print(f"结果已保存到: {output_path}")
        
        print("\n总结内容预览:")
        print("-"*60)
        content = result["content"]
        print(content[:2000] if len(content) > 2000 else content)
        
        if len(content) > 2000:
            print(f"\n... (共 {len(content)} 字符)")
    else:
        print(f"\n[错误] 总结失败: {result.get('error')}")


def main():
    parser = argparse.ArgumentParser(
        description="AI推文总结工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python summarize.py                              # 总结今天的推文
  python summarize.py --date 2024-01-15           # 总结特定日期
  python summarize.py --source latest              # 使用latest数据
  python summarize.py --by-user                    # 按用户分组总结
  python summarize.py --preview                    # 预览推文数据
  python summarize.py --config custom.py           # 自定义配置
        """
    )
    
    parser.add_argument(
        "--config",
        type=str,
        default="config/ai_config.py",
        help="AI配置文件路径（默认: config/ai_config.py）"
    )
    
    parser.add_argument(
        "--source",
        type=str,
        choices=["latest", "daily"],
        help="数据来源: latest 或 daily"
    )
    
    parser.add_argument(
        "--date",
        type=str,
        help="指定日期，格式: YYYY-MM-DD（用于daily模式）"
    )
    
    parser.add_argument(
        "--output",
        type=str,
        help="指定输出文件路径"
    )
    
    parser.add_argument(
        "--by-user",
        action="store_true",
        help="按用户分组总结"
    )
    
    parser.add_argument(
        "--preview",
        action="store_true",
        help="预览推文数据，不调用AI"
    )
    
    parser.add_argument(
        "--max-preview",
        type=int,
        default=10,
        help="预览时最大显示推文数量（默认: 10）"
    )
    
    args = parser.parse_args()
    
    summarize(args.config, args)


if __name__ == "__main__":
    main()
