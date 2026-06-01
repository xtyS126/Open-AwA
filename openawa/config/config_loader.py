"""
openawa 配置加载器模块 —— 重新导出 backend.config 的实现。
"""
try:
    from backend.config.config_loader import *
except ImportError:
    from config.config_loader import *
