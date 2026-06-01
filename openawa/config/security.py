"""
openawa 安全配置模块 —— 重新导出 backend.config 的实现。
"""
try:
    from backend.config.security import *
except ImportError:
    from config.security import *
