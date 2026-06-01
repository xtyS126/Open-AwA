"""
openawa 日志配置模块 —— 重新导出 backend.config 的实现。
"""
try:
    from backend.config.logging import *
except ImportError:
    from config.logging import *
