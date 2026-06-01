"""
openawa 经验设置模块 —— 重新导出 backend.config 的实现。
"""
try:
    from backend.config.experience_settings import *
except ImportError:
    from config.experience_settings import *
