# -*- coding: utf-8 -*-
"""
Twitter博主推文监控工具 - 配置文件

功能说明:
    - 本文件用于配置Twitter监控的各项参数
    - 修改配置后无需重启程序（单次执行时会重新加载）

配置项说明:
    1. api_key: TwitterApi.io的API密钥
    2. monitored_users: 要监控的Twitter用户名列表
    3. check_interval_minutes: 检查间隔（分钟）
    4. include_replies: 是否包含回复推文
    5. tweets_per_user: 每个用户每次获取的推文数量
    6. storage_mode: 存储模式 ("latest", "daily", "both")
    7. storage_paths: 存储路径配置

存储说明:
    - latest.json: 每次运行的最新推文（会被覆盖）
    - daily/YYYY-MM-DD.json: 按日期累积的推文
"""

# =============================================================================
# API配置
# =============================================================================
# TwitterApi.io的API密钥
# 获取方式: 登录 https://twitterapi.io/dashboard
api_key = "new1_2ade6ba173fb4523b34db143c09af331"


# =============================================================================
# 监控用户配置
# =============================================================================
# 要监控的Twitter用户名列表（不包含@符号）
# 可以添加任意数量的用户
monitored_users = [
    "elonmusk",      # Elon Musk
    "AndrewYNg",     # Andrew Ng (AI领域知名学者)
    "ylecun",        # Yann LeCun (Meta首席AI科学家)
    "JeffBezos",     # Jeff Bezos (前亚马逊CEO)
    "sama",          # Sam Altman (OpenAI CEO)
    "Alibaba_Qwen",
    "AndrewNG",
    "arena",
    "MiniMax__AI",
    "KwaiAICoder",
    "Zai_org",
    "lmstudio",
    "deepseek_ai",
    "OpenRouterAI",
    "AnthropicAI",
    "OpenAI",
    "huggingface",
    "Kimi_Moonshot",
    "Ali_TongyiLab",
    "cline",
    "OpenAIDevs",
    "cerebras",
    "Baidu_Inc",
    "ManusAI",
    "vista8",
    "karminski3",
    "op7418",
    "geekbb"
]


# =============================================================================
# 监控频率配置
# =============================================================================
# 检查间隔时间，单位：分钟
# 建议设置值:
#   - 30: 适合一般使用
#   - 60: API调用次数较少时
#   - 15: 需要更实时监控时（注意API限制）
check_interval_minutes = 30


# =============================================================================
# 推文获取配置
# =============================================================================
# 是否包含回复推文
# True: 包含用户回复的其他人的推文
# False: 只包含用户自己发的推文
include_replies = False

# 每个用户每次获取的推文数量
# 建议设置值: 10-50
# 注意: 数量越大，API调用越多
tweets_per_user = 8


# =============================================================================
# 存储模式配置
# =============================================================================
# 存储模式选择:
#   "latest": 只保存每次运行的最新推文
#   "daily": 只保存按日期累积的推文
#   "both": 两种模式都启用（推荐）
storage_mode = "both"

# 存储路径配置（一般不需要修改）
storage_paths = {
    "latest": "data/latest.json",
    "daily": "data/daily"
}


# =============================================================================
# 配置字典（程序内部使用）
# =============================================================================
# 请勿修改此配置字典，直接修改上面的配置项即可
config = {
    "api_key": api_key,
    "monitored_users": monitored_users,
    "check_interval_minutes": check_interval_minutes,
    "include_replies": include_replies,
    "tweets_per_user": tweets_per_user,
    "storage_mode": storage_mode,
    "storage_paths": storage_paths
}
