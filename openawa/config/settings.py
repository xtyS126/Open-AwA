"""
openawa 配置模块 —— 重新导出 backend.config 的实现。
pip 安装模式下 backend/ 目录不在 sys.path，通过本模块提供向后兼容。
"""
try:
    from backend.config.settings import *
except ImportError:
    from config.settings import *
