"""
速率限制模块。
提供全局 limiter 实例，由 main.py 在应用启动时注入 app.state.limiter。
"""
from slowapi import Limiter
from slowapi.util import get_remote_address

# 全局限流器实例，使用客户端 IP 作为限流 key
limiter = Limiter(key_func=get_remote_address)
