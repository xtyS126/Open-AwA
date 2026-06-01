"""
openawa 本地用户模块 —— 重新导出 backend.config 的实现。
"""
try:
    from backend.config.local_users import *
except ImportError:
    from config.local_users import *
