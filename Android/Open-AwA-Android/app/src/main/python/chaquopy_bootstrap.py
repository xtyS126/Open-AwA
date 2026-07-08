"""
Chaquopy 启动入口

在 Android 原生层（EmbeddedBackend.kt）通过 Chaquopy 调用此模块，
启动内嵌的 FastAPI 后端，监听 127.0.0.1:8000。

阶段 2 实现：
- 模块化后端（backend_mobile.main.create_app）
- 启动时初始化数据库与默认管理员
- 数据目录通过环境变量 OPENAWA_DATA_DIR 注入（由 Kotlin 侧设置）

调用方式（Kotlin）：
    val py = Python.getInstance()
    val port = py.getModule("chaquopy_bootstrap").callAttr("start_backend").toInt()

注意：Chaquopy 在 Android 上运行 Python，部分依赖不兼容：
- 不兼容：torch, pywinpty, qdrant-client 嵌入式模式, tree-sitter
- 兼容：fastapi, uvicorn, sqlalchemy, pydantic, httpx, loguru, passlib (pbkdf2_sha256)
"""

import logging
import os
import socket
import sys
import threading
import time
from typing import Optional

_logger = logging.getLogger("chaquopy_bootstrap")

# 后端运行状态
_backend_thread: Optional[threading.Thread] = None
_backend_started: bool = False
_backend_error: Optional[str] = None
_backend_port: int = 0


def _find_available_port(start: int = 8000, end: int = 8099) -> int:
    """在 start-end 范围内查找可用端口"""
    for port in range(start, end + 1):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(("127.0.0.1", port))
                return port
        except OSError:
            continue
    raise RuntimeError(f"未找到可用端口（{start}-{end}）")


def _run_backend(port: int) -> None:
    """在子线程中运行 uvicorn（阻塞调用）"""
    global _backend_started, _backend_error, _backend_port
    try:
        import uvicorn

        # 配置日志：loguru 与标准 logging 桥接
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        )

        # 导入模块化后端
        from backend_mobile.main import create_app

        app = create_app()
        config = uvicorn.Config(
            app=app,
            host="127.0.0.1",
            port=port,
            log_level="info",
            access_log=False,
        )
        server = uvicorn.Server(config)
        _backend_started = True
        _backend_port = port
        _logger.info(f"内嵌后端已启动，监听 127.0.0.1:{port}")
        server.run()
    except Exception as e:
        _backend_error = str(e)
        _logger.error(f"内嵌后端启动失败: {e}", exc_info=True)


def start_backend(port: int = 0) -> int:
    """
    启动内嵌后端

    参数：
        port: 监听端口，0 表示自动查找（8000-8099）

    返回：实际监听端口

    调用后立即返回，后端在子线程中运行。
    重复调用会直接返回已运行实例的端口。
    """
    global _backend_thread

    if _backend_thread and _backend_thread.is_alive():
        _logger.warning("后端已在运行，跳过启动")
        return _backend_port

    actual_port = port if port > 0 else _find_available_port()

    _backend_thread = threading.Thread(
        target=_run_backend,
        args=(actual_port,),
        name="openawa-backend",
        daemon=True,
    )
    _backend_thread.start()

    # 等待后端就绪（最多 10 秒，首次启动需要安装依赖）
    for _ in range(100):
        if _backend_started:
            return actual_port
        if _backend_error:
            raise RuntimeError(f"后端启动失败: {_backend_error}")
        time.sleep(0.1)

    raise RuntimeError("后端启动超时（10 秒内未就绪）")


def stop_backend() -> None:
    """停止内嵌后端（阶段 2 待实现：通过 uvicorn.Server.should_exit）"""
    _logger.info("停止内嵌后端（待实现）")


def get_api_key() -> str:
    """
    获取当前 API Key（供 Kotlin 侧 EmbeddedBackend 读取）

    Kotlin 侧通过 EmbeddedBackend.start() 调用此函数，
    前端启动时自动持久化，跳过登录页。

    API Key 在首次启动时由 config.MobileSettings 生成并持久化到 secret.key 文件。
    """
    from backend_mobile.config import get_settings

    return get_settings().api_key


def get_backend_status() -> dict:
    """获取后端运行状态"""
    return {
        "started": _backend_started,
        "port": _backend_port,
        "error": _backend_error,
        "thread_alive": _backend_thread.is_alive() if _backend_thread else False,
    }


def set_data_dir(path: str) -> None:
    """
    设置数据目录（由 Kotlin 侧调用）

    必须在 start_backend 之前调用。
    Kotlin 侧从 Context.getFilesDir() 获取路径并传入。
    """
    os.environ["OPENAWA_DATA_DIR"] = path
    _logger.info(f"数据目录设置为: {path}")


if __name__ == "__main__":
    # 直接运行此脚本时启动后端（用于桌面调试）
    logging.basicConfig(level=logging.INFO)
    port = start_backend()
    print(f"后端已启动，端口 {port}")
    # 保持主线程不退出
    while True:
        time.sleep(1)
