# -*- coding: utf-8 -*-
"""
Twitter博主推文监控工具

功能概述:
    - 定期抓取指定Twitter用户的最新推文
    - 支持两种存储模式:
        1. latest.json: 存储每次运行时的最新推文（会被覆盖）
        2. daily/YYYY-MM-DD.json: 按日期累积存储推文（每日一个文件）
    - 支持持续监控和单次执行两种模式

使用示例:
    # 持续监控（默认，每30分钟检查一次）
    python monitor.py
    
    # 单次执行后退出
    python monitor.py --once
    
    # 仅显示统计数据
    python monitor.py --stats
    
    # 查看特定日期的历史数据
    python monitor.py --stats --date 2024-01-07
    
    # 使用自定义配置文件
    python monitor.py --config custom.py
"""

import json
import time
import argparse
import importlib.util
from datetime import datetime, date
from pathlib import Path
from typing import List

from core.api import TwitterAPI
from core.storage import TweetStorage


def load_config(config_path: str) -> dict:
    """
    加载配置文件
    
    支持两种格式:
        1. .py格式: Python模块，直接读取config字典
        2. .json格式: JSON配置文件
    
    参数:
        config_path: 配置文件路径
        
    返回:
        配置字典，包含API密钥、监控用户列表、监控频率等信息
    """
    config_path = Path(config_path)
    
    if config_path.suffix == '.py':
        spec = importlib.util.spec_from_file_location("config", config_path)
        config_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(config_module)
        return config_module.config
    else:
        with open(config_path, 'r', encoding='utf-8') as f:
            return json.load(f)


def fetch_user_tweets(
    api: TwitterAPI, 
    user_name: str, 
    limit: int,
    include_replies: bool
) -> List[dict]:
    """
    获取指定用户的最新推文
    
    参数:
        api: TwitterAPI实例
        user_name: Twitter用户名（不带@符号）
        limit: 最多返回的推文数量
        include_replies: 是否包含回复推文
        
    返回:
        推文列表，如果出错则返回空列表
    """
    result = api.get_user_last_tweets(
        user_name=user_name,
        include_replies=include_replies,
        limit=limit
    )
    
    if result["success"]:
        return result["tweets"]
    else:
        print(f"  [错误] 获取 @{user_name} 推文失败: {result['error']}")
        return []


def check_and_update_users(api: TwitterAPI, storage: TweetStorage, config: dict) -> dict:
    """
    检查所有监控用户的推文并更新存储
    
    参数:
        api: TwitterAPI实例
        storage: TweetStorage实例
        config: 配置字典
        
    返回:
        统计信息字典，包含检查用户数、新增推文数等
    """
    stats = {
        "users_checked": 0,
        "new_tweets": 0,
        "errors": []
    }
    
    users = config.get("monitored_users", [])
    limit = config.get("tweets_per_user", 20)
    include_replies = config.get("include_replies", False)
    
    print(f"\n开始检查 {len(users)} 位博主...")
    
    all_tweets = []
    
    for user_name in users:
        print(f"  正在检查 @{user_name}...")
        stats["users_checked"] += 1
        
        tweets = fetch_user_tweets(api, user_name, limit, include_replies)
        all_tweets.extend(tweets)
        
        if tweets:
            print(f"    发现 {len(tweets)} 条推文")
        
        time.sleep(0.5)
    
    if all_tweets:
        added = storage.save_all(all_tweets)
        stats["new_tweets"] = added
    
    return stats


def print_stats_for_storage_type(
    storage: TweetStorage, 
    storage_type: str, 
    label: str, 
    target_date: date = None
):
    """
    打印指定存储类型的统计信息
    
    参数:
        storage: TweetStorage实例
        storage_type: 存储类型 ("latest" 或 "daily")
        label: 显示标签
        target_date: 目标日期（仅用于daily类型）
    """
    stats = storage.get_stats(storage_type, target_date)
    print(f"\n{'='*50}")
    print(f"【{label}】数据统计")
    print(f"{'='*50}")
    if stats.get('date'):
        print(f"日期: {stats['date']}")
    print(f"总推文数: {stats['total_tweets']}")
    print(f"监控用户数: {stats['users_tracked']}")
    if stats['tweets_per_user']:
        print(f"\n各用户推文数量:")
        for user, count in sorted(stats['tweets_per_user'].items(), key=lambda x: x[1], reverse=True):
            print(f"  @{user}: {count}")
    print(f"{'='*50}")


def print_current_stats(storage: TweetStorage):
    """
    打印当前所有存储类型的统计信息
    
    参数:
        storage: TweetStorage实例
    """
    config = storage.config or {}
    mode = config.get("storage_mode", "both")
    
    if mode in ["latest", "both"]:
        print_stats_for_storage_type(storage, "latest", "本次最新")
    
    if mode in ["daily", "both"]:
        print_stats_for_storage_type(storage, "daily", "今日累积")
    
    print("\n历史日期:")
    daily_dates = storage.get_daily_dates()
    if daily_dates:
        for d in daily_dates[:7]:
            print(f"  {d.isoformat()}")
        if len(daily_dates) > 7:
            print(f"  ... 共 {len(daily_dates)} 天")
    else:
        print("  无历史数据")


def run_once(config_path: str):
    """
    单次执行模式：抓取一次推文后退出
    
    参数:
        config_path: 配置文件路径
    """
    print(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 开始执行抓取...")
    
    config = load_config(config_path)
    
    if config.get("api_key") == "your_api_key_here":
        print("\n[错误] 请先在 config/config.json 中设置您的API密钥！")
        return
    
    api = TwitterAPI(config["api_key"])
    storage = TweetStorage(config)
    
    stats = check_and_update_users(api, storage, config)
    
    print(f"\n本次执行完成:")
    print(f"  检查用户: {stats['users_checked']}")
    print(f"  新增推文: {stats['new_tweets']}")
    
    print_current_stats(storage)


def run_continuous(config_path: str):
    """
    持续监控模式：按照配置的时间间隔循环执行
    
    参数:
        config_path: 配置文件路径
    """
    config = load_config(config_path)
    
    if config.get("api_key") == "your_api_key_here":
        print("\n[错误] 请先在 config/config.json 中设置您的API密钥！")
        return
    
    interval = config.get("check_interval_minutes", 30) * 60
    
    print(f"\n启动持续监控模式...")
    print(f"监控频率: 每 {config.get('check_interval_minutes', 30)} 分钟一次")
    print(f"监控用户: {len(config.get('monitored_users', []))} 位")
    print("-"*50)
    
    api = TwitterAPI(config["api_key"])
    storage = TweetStorage(config)
    
    try:
        while True:
            current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            print(f"\n[{current_time}] 开始检查...")
            
            stats = check_and_update_users(api, storage, config)
            
            print(f"\n[{current_time}] 本次检查完成，新增 {stats['new_tweets']} 条推文")
            print_current_stats(storage)
            
            print(f"\n等待 {config.get('check_interval_minutes', 30)} 分钟...")
            time.sleep(interval)
            
    except KeyboardInterrupt:
        print("\n\n检测到用户中断，程序退出。")


def main():
    """
    程序入口点
    
    支持以下命令行参数:
        --once: 单次执行模式
        --config: 指定配置文件路径
        --stats: 仅显示统计数据
        --date: 指定查看的日期（格式: YYYY-MM-DD）
    """
    parser = argparse.ArgumentParser(
        description="Twitter博主推文监控工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python monitor.py --once               # 单次执行
  python monitor.py                       # 持续监控（默认）
  python monitor.py --config custom.json  # 使用自定义配置文件
  python monitor.py --stats               # 显示统计数据
  python monitor.py --stats --date 2024-01-07  # 查看特定日期的统计
        """
    )
    
    parser.add_argument(
        "--once", 
        action="store_true",
        help="仅执行一次后退出，不持续监控"
    )
    
    parser.add_argument(
        "--config",
        type=str,
        default="config/config.py",
        help="配置文件路径（默认: config/config.py）"
    )
    
    parser.add_argument(
        "--stats",
        action="store_true",
        help="仅显示当前统计数据，不抓取新内容"
    )
    
    parser.add_argument(
        "--date",
        type=str,
        help="指定日期，格式: YYYY-MM-DD（用于查看历史数据）"
    )
    
    args = parser.parse_args()
    
    config_path = Path(__file__).parent / args.config
    
    if not config_path.exists():
        print(f"\n[错误] 配置文件不存在: {config_path}")
        print("请确保已正确设置 config/config.json")
        return
    
    config = load_config(str(config_path))
    
    if args.stats:
        storage = TweetStorage(config)
        
        if args.date:
            try:
                target_date = date.fromisoformat(args.date)
                print_stats_for_storage_type(storage, "daily", f"{args.date} 历史", target_date)
            except ValueError:
                print(f"\n[错误] 日期格式无效，请使用 YYYY-MM-DD 格式")
        else:
            print_current_stats(storage)
    
    elif args.once:
        run_once(str(config_path))
    
    else:
        run_continuous(str(config_path))


if __name__ == "__main__":
    main()
