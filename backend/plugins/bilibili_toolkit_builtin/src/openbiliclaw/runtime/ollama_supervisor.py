"""监督本地 Ollama 守护进程的共享助手。"""

from __future__ import annotations

import ipaddress
import os
from contextlib import suppress
from typing import TYPE_CHECKING
from urllib.parse import urlparse, urlunparse

import httpx
from rich.console import Console

from openbiliclaw.llm.registry import _ollama_is_chat_capable

if TYPE_CHECKING:
    import subprocess

    from openbiliclaw.config import Config

_DEFAULT_OLLAMA_ENDPOINT = "http://localhost:11434"
_DEFAULT_OLLAMA_KEEP_ALIVE = "24h"

console = Console()

# 由 *本进程* 启动的 ``ollama serve`` 守护进程句柄（若 Ollama 已经在
# 运行而我们只是收养它，或我们从未启动过，则为 None）。让
# ``stop_managed_ollama`` 在退出时仅关闭我们自身拉起的进程，对外部
# 管理的 Ollama（官方应用 / 用户守护进程）保持不动。
_managed_proc: subprocess.Popen[bytes] | None = None


def _embedding_wants_ollama(config: Config) -> bool:
    embedding = config.llm.embedding
    return (
        str(embedding.provider).strip().lower() == "ollama"
        or str(embedding.fallback_provider).strip().lower() == "ollama"
    )


def ollama_required(config: Config) -> bool:
    """返回 chat 或 embedding 路由是否会调用 Ollama。"""
    return _ollama_is_chat_capable(config) or _embedding_wants_ollama(config)


def _strip_openai_v1_suffix(url: str) -> str:
    text = url.strip().rstrip("/")
    if not text:
        return _DEFAULT_OLLAMA_ENDPOINT
    parsed = urlparse(text)
    path = parsed.path.rstrip("/")
    if path == "/v1":
        path = ""
    elif path.endswith("/v1"):
        path = path[: -len("/v1")]
    return urlunparse((parsed.scheme, parsed.netloc, path.rstrip("/"), "", "", "")).rstrip("/")

def effective_ollama_endpoint(config: Config) -> str:
    """返回用于 Ollama 健康探测的守护进程根端点。

    Chat 和 embedding provider 在配置里使用 OpenAI 兼容的 ``/v1``
    URL，而 Ollama 的健康 API 位于守护进程根 ``/api/version``。
    """
    if _ollama_is_chat_capable(config):
        base_url = config.llm.ollama.base_url.strip() or f"{_DEFAULT_OLLAMA_ENDPOINT}/v1"
    elif _embedding_wants_ollama(config):
        base_url = (
            config.llm.embedding.base_url.strip()
            or config.llm.ollama.base_url.strip()
            or f"{_DEFAULT_OLLAMA_ENDPOINT}/v1"
        )
    else:
        base_url = config.llm.ollama.base_url.strip() or f"{_DEFAULT_OLLAMA_ENDPOINT}/v1"
    return _strip_openai_v1_suffix(base_url)


def is_loopback(url: str) -> bool:
    """返回某 URL 是否指向本机。"""
    parsed = urlparse(url)
    host = (parsed.hostname or "").strip().lower()
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _ollama_is_running(host: str = _DEFAULT_OLLAMA_ENDPOINT) -> bool:
    """探测 Ollama 的 HTTP API；仅在返回健康的 200 时返回 True。"""
    try:
        # trust_env=False —— 对 localhost Ollama 的探测绝不能被
        # HTTP_PROXY 环境变量劫持（例如 127.0.0.1:7897 的 VPN 客户端）。
        with httpx.Client(timeout=2.0, trust_env=False) as client:
            response = client.get(f"{host.rstrip('/')}/api/version")
            return response.status_code == 200
    except Exception:
        return False


def _ollama_start_serve_background() -> bool:
    """后台启动 ``ollama serve``，最多等 15 秒确认健康。"""
    import shutil
    import subprocess
    import time

    if _ollama_is_running():
        return True

    ollama = shutil.which("ollama")
    if ollama is None:
        return False

    try:
        env = os.environ.copy()
        env.setdefault("OLLAMA_KEEP_ALIVE", _DEFAULT_OLLAMA_KEEP_ALIVE)
        if os.name == "nt":
            # CREATE_NO_WINDOW（不是 DETACHED_PROCESS）：给 `ollama serve`
            # 一个隐藏控制台，让它的子进程 `ollama runner` 继承，使两者
            # 都不弹窗。DETACHED_PROCESS 会让 runner 没有可继承的控制台，
            # 只能自己分配一个 *可见的* conhost —— 用户在打包托盘应用上
            # 看到的窗口闪烁就是这么来的。
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000) | getattr(
                subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200
            )
            proc = subprocess.Popen(
                [ollama, "serve"],
                creationflags=creationflags,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
                env=env,
            )
        else:
            proc = subprocess.Popen(
                [ollama, "serve"],
                start_new_session=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
                env=env,
            )
    except Exception as exc:
        console.print(f"[red]启动 ollama serve 失败: {exc}[/red]")
        return False

    # 记住 *我们* 启动的守护进程，便于退出时干净停止（连同其模型
    # runner / llama-server 子进程），而不是成为孤儿。
    global _managed_proc
    _managed_proc = proc

    for _ in range(30):
        if _ollama_is_running():
            return True
        time.sleep(0.5)
    return False


def stop_managed_ollama() -> bool:
    """停止由本进程启动的 ``ollama serve`` 守护进程（如有）。

    仅触碰我们在 :func:`_ollama_start_serve_background` 中拉起的守护
    进程；启动时已经在跑的 Ollama（官方应用 / 用户管理的守护进程）
    不动。Kill 整个进程树，使模型 runner（``llama-server`` /
    ``ollama runner``）随父进程一起退出，而不是作为泄露资源的孤儿
    残留。当确实停止了被托管的守护进程时返回 True。
    """
    global _managed_proc
    proc = _managed_proc
    _managed_proc = None
    if proc is None or proc.poll() is not None:
        return False

    import signal
    import subprocess

    try:
        if os.name == "nt":
            # terminate() 只能到达 `ollama serve`；模型 runner 是子进程，
            # 所以用 taskkill /T 把整棵树带走。
            subprocess.run(  # noqa: S603
                ["taskkill", "/PID", str(proc.pid), "/T", "/F"],  # noqa: S607
                capture_output=True,
                check=False,
            )
        else:
            # 启动时用了 start_new_session=True → 它有自己的进程组；
            # 给整组发信号让 runner 子进程也一起停。
            with suppress(ProcessLookupError, PermissionError):
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        with suppress(Exception):
            proc.wait(timeout=5)
        return True
    except Exception as exc:  # noqa: BLE001 — 尽力而为的关闭，退出时绝不抛
        console.print(f"[yellow]停止托管 ollama 失败: {exc}[/yellow]")
        return False
