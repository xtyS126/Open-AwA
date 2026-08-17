"""
统一阈值配置：集中管理所有硬编码阈值，支持环境变量覆盖。
所有阈值以 OPENAWAS_ 前缀的环境变量可覆盖默认值。
"""
import os


def _env_int(name: str, default: int) -> int:
    """从环境变量读取整数阈值"""
    val = os.environ.get(name)
    return int(val) if val is not None else default


def _env_float(name: str, default: float) -> float:
    """从环境变量读取浮点数阈值"""
    val = os.environ.get(name)
    return float(val) if val is not None else default


# ===== Agent 核心 =====
# 能力缓存 TTL（秒）
CAPABILITIES_CACHE_TTL = _env_float("OPENAWAS_CAPABILITIES_CACHE_TTL", 30.0)

# ===== 压缩相关 =====
# 触发压缩的消息数量阈值
COMPACTION_MESSAGE_THRESHOLD = _env_int("OPENAWAS_COMPACTION_MESSAGE_THRESHOLD", 40)
# 历史消息截断字符数
MAX_HISTORY_MESSAGE_CHARS = _env_int("OPENAWAS_MAX_HISTORY_MESSAGE_CHARS", 5_000)
# 摘要输出 token 上限
SUMMARY_OUTPUT_TOKENS = _env_int("OPENAWAS_SUMMARY_OUTPUT_TOKENS", 4_096)
# 保留 token 下限
RESERVED_TOKENS_MIN = _env_int("OPENAWAS_RESERVED_TOKENS_MIN", 8_000)
# 缓冲 token
BUFFER_TOKENS = _env_int("OPENAWAS_BUFFER_TOKENS", 20_000)
# 压缩工具输出截断字符数（CompactionManager 内部使用）
COMPACTION_TOOL_OUTPUT_MAX_CHARS = _env_int("OPENAWAS_COMPACTION_TOOL_OUTPUT_MAX_CHARS", 2_000)
# 断路器：连续失败上限
MAX_CONSECUTIVE_FAILURES = _env_int("OPENAWAS_MAX_CONSECUTIVE_FAILURES", 3)
# MicroCompact 保留最近消息数
MICRO_COMPACT_KEEP_RECENT = _env_int("OPENAWAS_MICRO_COMPACT_KEEP_RECENT", 5)

# ===== 工具执行 =====
# 工具输出截断字符数（ToolRegistry 全局上限）
MAX_TOOL_OUTPUT_CHARS = _env_int("OPENAWAS_MAX_TOOL_OUTPUT_CHARS", 10_000)
# 工具结果截断字符数（执行层通用）
MAX_TOOL_RESULT_CHARS = _env_int("OPENAWAS_MAX_TOOL_RESULT_CHARS", 8_000)
# 工具事件结果截断字符数（流式事件中）
MAX_TOOL_EVENT_RESULT_CHARS = _env_int("OPENAWAS_MAX_TOOL_EVENT_RESULT_CHARS", 2_000)

# ===== 流式处理 =====
# 流式重试上限
STREAM_MAX_RETRIES = _env_int("OPENAWAS_STREAM_MAX_RETRIES", 2)
# 流式 chunk 超时（秒），LLM 服务 hang 住但不断开时触发
STREAM_CHUNK_TIMEOUT_SECONDS = _env_float("OPENAWAS_STREAM_CHUNK_TIMEOUT_SECONDS", 120.0)
# 输出 token 恢复重试次数
OUTPUT_TOKEN_RECOVERY_MAX_RETRIES = _env_int("OPENAWAS_OUTPUT_TOKEN_RECOVERY_MAX_RETRIES", 3)
# 输出 token 恢复阈值
OUTPUT_TOKEN_RECOVERY_THRESHOLD = _env_int("OPENAWAS_OUTPUT_TOKEN_RECOVERY_THRESHOLD", 64_000)

# ===== 钩子系统 =====
# 钩子执行超时（秒）
HOOK_TIMEOUT_SECONDS = _env_float("OPENAWAS_HOOK_TIMEOUT_SECONDS", 30.0)
# 钩子耗时告警阈值（毫秒）
HOOK_TIMING_DISPLAY_THRESHOLD_MS = _env_int("OPENAWAS_HOOK_TIMING_DISPLAY_THRESHOLD_MS", 500)