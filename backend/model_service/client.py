"""
模型服务客户端（主进程侧）—— Spec 模型进程化。

职责：
1. 懒启动模型服务子进程（首次推理调用时 spawn，不阻塞主进程启动）
2. 通过 HTTP 调用嵌入 / 重排推理（RemoteEmbeddingProvider / RemoteReranker）
3. 空闲卸载：超过 MODEL_IDLE_UNLOAD_MINUTES 分钟无调用 → kill 子进程
   （释放模型内存），下次调用时自动重新拉起
4. 子进程异常（崩溃/启动失败）时自动重启或降级

生命周期：
- 首次调用 embed/rerank → ensure_started() → spawn uvicorn 子进程 → 探活
- 每次调用更新 last_used_at → 后台 monitor 定时检查 → 空闲超时 kill
- 主进程退出（atexit）→ kill 子进程，不留孤儿
"""
from __future__ import annotations

import asyncio
import atexit
import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

from loguru import logger

from config.settings import settings

# 默认端口：settings.MODEL_SERVICE_PORT（0=自动分配）
# 自动分配策略：绑定 0 端口获取空闲端口号后释放（竞态窗口极小）
def _pick_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class ModelServiceClient:
    """模型服务子进程生命周期管理器 + 推理客户端。"""

    def __init__(self) -> None:
        self._process: Optional[subprocess.Popen] = None
        self._port: int = 0
        self._base_url = ""
        self._client: Optional[httpx.AsyncClient] = None
        self._start_lock = asyncio.Lock()
        self._last_used_at = 0.0
        self._monitor_task: Optional[asyncio.Task] = None
        self._embedding_model = ""
        self._rerank_model = ""
        self._unload_seconds = float(max(0, settings.MODEL_IDLE_UNLOAD_MINUTES)) * 60
        atexit.register(self._kill_process_sync)

    # ---------------- 配置 ----------------

    def configure(self, embedding_model: str = "", rerank_model: str = "") -> None:
        """设置子进程将加载的模型（配置变化时若进程已启动则重启）。"""
        if embedding_model != self._embedding_model or rerank_model != self._rerank_model:
            self._embedding_model = embedding_model
            self._rerank_model = rerank_model
            if self._process is not None:
                self._kill_process_sync()

    @property
    def enabled(self) -> bool:
        """模型服务开关：由 settings 控制；无本地模型时自动禁用。"""
        return bool(settings.MODEL_SERVICE_ENABLED) and bool(
            self._embedding_model or self._rerank_model
        )

    # ---------------- 进程生命周期 ----------------

    async def ensure_started(self) -> bool:
        """确保子进程运行且健康（懒启动 + 崩溃恢复）。"""
        if not self.enabled:
            return False
        if self._process is not None and self._process.poll() is None:
            # 进程在跑：探活一次，失败则重建
            try:
                await self._http_get("/health")
                return True
            except Exception:
                self._kill_process_sync()
        async with self._start_lock:
            if self._process is not None and self._process.poll() is None:
                try:
                    await self._http_get("/health")
                    return True
                except Exception:
                    self._kill_process_sync()
            return await self._spawn()

    async def _spawn(self) -> bool:
        """启动模型服务子进程并等待就绪（最多 30s）。"""
        self._port = _pick_free_port()
        self._base_url = f"http://127.0.0.1:{self._port}"
        self._client = httpx.AsyncClient(timeout=60.0)

        env = dict(os.environ)
        env["MODEL_SERVICE_PORT"] = str(self._port)
        if self._embedding_model:
            env["MODEL_SERVICE_EMBEDDING_MODEL"] = self._embedding_model
        if self._rerank_model:
            env["MODEL_SERVICE_RERANK_MODEL"] = self._rerank_model
        # 子进程不继承 LAN 访问等主进程专属配置无碍，但必须保证 backend 可导入
        backend_dir = str(Path(__file__).resolve().parents[1])

        try:
            self._process = subprocess.Popen(
                [sys.executable, "-m", "uvicorn", "model_service.server:app",
                 "--host", "127.0.0.1", "--port", str(self._port), "--log-level", "warning"],
                cwd=backend_dir,
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except Exception as exc:
            logger.warning(f"模型服务子进程启动失败: {exc}")
            self._kill_process_sync()
            return False

        # 探活等待
        for _ in range(30):
            if self._process.poll() is not None:
                break
            try:
                await self._http_get("/health")
                self._touch()
                self._ensure_monitor()
                logger.info(
                    f"模型服务子进程就绪: pid={self._process.pid} port={self._port} "
                    f"embedding={self._embedding_model or '-'} rerank={self._rerank_model or '-'}"
                )
                return True
            except Exception:
                await asyncio.sleep(1)
        self._kill_process_sync()
        logger.warning("模型服务子进程启动超时")
        return False

    def _kill_process_sync(self) -> None:
        """同步终止子进程（幂等），释放模型内存。"""
        if self._process is not None:
            try:
                self._process.terminate()
                try:
                    self._process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self._process.kill()
            except Exception:
                pass
            self._process = None
        if self._client is not None:
            try:
                asyncio.get_event_loop().run_until_complete(self._client.aclose())
            except Exception:
                pass
            self._client = None
        self._base_url = ""
        self._port = 0

    # ---------------- 空闲卸载 ----------------

    def _touch(self) -> None:
        """记录最近一次调用时间（空闲计时基准）。"""
        self._last_used_at = time.monotonic()

    def _ensure_monitor(self) -> None:
        """启动空闲监控任务（单例）：超过阈值无调用 → kill 子进程。"""
        if self._monitor_task is None or self._monitor_task.done():
            self._monitor_task = asyncio.create_task(self._idle_monitor_loop())

    async def _idle_monitor_loop(self) -> None:
        """每 60s 检查一次空闲状态；阈值=0 时不自动卸载。"""
        if self._unload_seconds <= 0:
            return
        while True:
            await asyncio.sleep(60)
            if self._process is None or self._process.poll() is not None:
                continue
            idle_seconds = time.monotonic() - self._last_used_at
            if idle_seconds >= self._unload_seconds:
                logger.info(
                    f"模型服务空闲 {idle_seconds:.0f}s 超过阈值 {self._unload_seconds:.0f}s，卸载模型进程"
                )
                self._kill_process_sync()

    async def shutdown(self) -> None:
        """主进程退出时调用：终止监控与子进程。"""
        if self._monitor_task is not None:
            self._monitor_task.cancel()
        self._kill_process_sync()

    # ---------------- 推理调用 ----------------

    async def _http_get(self, path: str) -> Dict[str, Any]:
        if self._client is None:
            raise RuntimeError("模型服务客户端未初始化")
        resp = await self._client.get(f"{self._base_url}{path}")
        resp.raise_for_status()
        return resp.json()

    async def embed(self, texts: List[str], images: List[str]) -> List[List[float]]:
        """文本/图片 → 向量。

        Raises:
            RuntimeError: 模型服务未启用或子进程启动失败（显式传播，禁止返回 None 伪装）。
            Exception: 嵌入调用失败（显式传播，调用方不得静默拿到空向量）。
        """
        if not await self.ensure_started():
            raise RuntimeError(
                "模型服务子进程不可用（未启用或启动失败），无法执行嵌入"
            )
        try:
            resp = await self._client.post(
                f"{self._base_url}/embed", json={"texts": texts, "images": images}
            )
            resp.raise_for_status()
            self._touch()
            return resp.json()["vectors"]
        except Exception as exc:
            logger.error(f"模型服务嵌入调用失败: {exc}")
            self._kill_process_sync()
            raise

    async def rerank(self, query: str, documents: List[str]) -> List[float]:
        """查询 + 文档 → 分数。

        Raises:
            RuntimeError: 模型服务未启用或子进程启动失败（显式传播）。
            Exception: 重排调用失败（显式传播，禁止伪装全 0 分）。
        """
        if not await self.ensure_started():
            raise RuntimeError(
                "模型服务子进程不可用（未启用或启动失败），无法执行重排"
            )
        try:
            resp = await self._client.post(
                f"{self._base_url}/rerank", json={"query": query, "documents": documents}
            )
            resp.raise_for_status()
            self._touch()
            return resp.json()["scores"]
        except Exception as exc:
            logger.error(f"模型服务重排调用失败: {exc}")
            self._kill_process_sync()
            raise


# ---------------- 协议适配（嵌入 / 重排 Provider） ----------------

class RemoteEmbeddingProvider:
    """实现 EmbeddingProvider 协议的远程嵌入提供方（代理到模型服务子进程）。

    子进程不可用时显式传播异常，禁止返回空列表伪装嵌入成功。
    """

    provider_name = "model-service"

    def __init__(self, client: ModelServiceClient):
        self._client = client
        self.model_name = client._embedding_model

    @property
    def dimension(self) -> Optional[int]:
        from memory.model_registry import get_embedding_spec

        spec = get_embedding_spec(self.model_name)
        return spec.dimension if spec else None

    async def embed_texts(self, texts: List[str]) -> List[List[float]]:
        return await self._client.embed(texts, [])

    async def embed_inputs(self, inputs: List[Any]) -> List[List[float]]:
        # 多模态输入：拆分文本与图片 URL 透传给子进程
        texts: List[str] = []
        images: List[str] = []
        for item in inputs:
            if isinstance(item, str):
                texts.append(item)
            elif isinstance(item, dict):
                for block in item.get("content", []):
                    if block.get("type") == "image_url":
                        url = block.get("image_url", {}).get("url", "")
                        if url:
                            images.append(url)
        return await self._client.embed(texts, images)


class RemoteReranker:
    """实现 Reranker 协议的远程重排器（代理到模型服务子进程）。"""

    provider_name = "model-service"

    def __init__(self, client: ModelServiceClient):
        self._client = client

    async def rerank(self, query: str, documents: List[str]) -> List[float]:
        # 重排失败由 client 显式传播，禁止伪装全 0 分
        return await self._client.rerank(query, documents)


# ---------------- 单例 ----------------

_model_service_client: Optional[ModelServiceClient] = None
_client_lock = threading.Lock()


def get_model_service_client() -> ModelServiceClient:
    """获取模型服务客户端单例（线程安全，主进程内全局共享）。"""
    global _model_service_client
    if _model_service_client is None:
        with _client_lock:
            if _model_service_client is None:
                _model_service_client = ModelServiceClient()
    return _model_service_client


async def shutdown_model_service() -> None:
    """主进程退出清理（由 main.py lifespan 调用）。"""
    global _model_service_client
    if _model_service_client is not None:
        await _model_service_client.shutdown()
        _model_service_client = None
