"""
WebSocket 连接管理服务层，负责管理连接的生命周期和活跃连接状态。

支持同一会话多设备并发连接，实现多端消息实时同步。
内部维护两张映射表：
  - _session_connections: session_id -> 该会话所有 WebSocket 连接列表
  - _user_sessions: user_id -> 该用户关联的 session_id 集合

PERF-06: 添加心跳机制与僵尸连接清理，广播改为并发发送。
"""

import asyncio
import json
import time
from typing import Dict, List, Optional, Set

from fastapi import WebSocket
from loguru import logger


# 心跳间隔（秒）：每隔此时间向所有连接发送一次 ping
HEARTBEAT_INTERVAL_SECONDS = 30
# 心跳超时（秒）：超过此时间未成功通信的连接视为僵尸并清理
HEARTBEAT_TIMEOUT_SECONDS = 90


class WebSocketManager:
    """
    管理 WebSocket 连接，支持会话级多设备并发。

    同一 session_id 可有多个设备同时连接，消息可广播到会话内所有设备，
    也可按 user_id 跨会话广播，满足多端互通场景。

    PERF-06: 内置心跳机制，定期 ping 所有连接并清理僵尸连接；
    广播使用 asyncio.gather 并发发送，避免串行 await 导致延迟累积。
    """

    def __init__(self) -> None:
        # session_id -> 该会话所有活跃 WebSocket 连接
        self._session_connections: Dict[str, List[WebSocket]] = {}
        # user_id -> 该用户关联的 session_id 集合（用于跨会话广播）
        self._user_sessions: Dict[str, Set[str]] = {}
        # 每个连接最后一次成功通信的单调时间戳，用于僵尸检测
        # key 为 id(websocket)，value 为 time.monotonic() 结果
        self._last_activity: Dict[int, float] = {}
        # 全局心跳后台任务
        self._heartbeat_task: Optional[asyncio.Task] = None

    async def connect(
        self,
        session_id: str,
        websocket: WebSocket,
        user_id: Optional[str] = None,
        subprotocol: Optional[str] = None,
    ) -> None:
        """
        接受 WebSocket 连接并注册到会话连接列表。

        同一 session_id 的多次连接会追加到列表，实现多设备并发。
        若传入 user_id，则建立 user -> session 映射，支持用户级广播。
        连接成功后自动启动全局心跳任务（幂等，已运行则跳过）。

        Args:
            subprotocol: 可选的子协议标识，用于回显 Sec-WebSocket-Protocol 头。
                         当客户端通过子协议传递 token 时，必须回显以完成握手。
        """
        await websocket.accept(subprotocol=subprotocol) if subprotocol else await websocket.accept()
        conns = self._session_connections.setdefault(session_id, [])
        conns.append(websocket)
        self._last_activity[id(websocket)] = time.monotonic()
        if user_id:
            self._user_sessions.setdefault(user_id, set()).add(session_id)
        # 启动全局心跳任务（幂等，已运行则跳过）
        self.start_heartbeat()
        logger.bind(
            event="ws_connected",
            module="ws_manager",
            session_id=session_id,
            user_id=user_id,
            connection_count=len(conns),
        ).debug("websocket connected")

    def disconnect(
        self,
        session_id: str,
        websocket: Optional[WebSocket] = None,
    ) -> None:
        """
        从会话连接列表移除连接。

        传入 websocket 时仅移除该连接（多设备场景下不影响其他设备）；
        不传 websocket 时清空整个会话的所有连接（向后兼容旧行为）。
        """
        conns = self._session_connections.get(session_id)
        if not conns:
            return
        if websocket is None:
            # 清空整个会话（旧行为），同时清理 last_activity
            for ws in conns:
                self._last_activity.pop(id(ws), None)
            self._session_connections.pop(session_id, None)
            return
        try:
            conns.remove(websocket)
        except ValueError:
            # 连接不在列表中，忽略
            pass
        self._last_activity.pop(id(websocket), None)
        if not conns:
            self._session_connections.pop(session_id, None)

    def get_connection(self, session_id: str) -> Optional[WebSocket]:
        """
        获取会话的第一个活跃连接（向后兼容）。
        """
        conns = self._session_connections.get(session_id, [])
        return conns[0] if conns else None

    def get_connections(self, session_id: str) -> List[WebSocket]:
        """获取会话的所有活跃连接列表（副本）。"""
        return list(self._session_connections.get(session_id, []))

    def get_session_count(self, session_id: str) -> int:
        """获取会话的活跃连接数。"""
        return len(self._session_connections.get(session_id, []))

    def start_heartbeat(self) -> None:
        """
        启动全局心跳后台任务（幂等）。

        若心跳任务已在运行则跳过；若已结束或不存在则创建新任务。
        在无事件循环的上下文中调用时静默跳过（如同步初始化场景）。
        """
        if self._heartbeat_task is not None and not self._heartbeat_task.done():
            return
        try:
            self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
        except RuntimeError:
            # 无运行中的事件循环，静默跳过
            logger.bind(event="ws_heartbeat_no_loop", module="ws_manager").debug(
                "无法启动心跳任务：无运行中的事件循环"
            )

    def stop_heartbeat(self) -> None:
        """
        停止全局心跳后台任务。

        取消正在运行的心跳任务并置空引用。重复调用安全。
        """
        if self._heartbeat_task is not None and not self._heartbeat_task.done():
            self._heartbeat_task.cancel()
        self._heartbeat_task = None

    async def _heartbeat_loop(self) -> None:
        """
        心跳循环：定期向所有连接发送 ping 并清理僵尸连接。

        每 HEARTBEAT_INTERVAL_SECONDS 秒执行一轮：
        1. 向所有活跃连接并发发送 ping 消息
        2. 清理超过 HEARTBEAT_TIMEOUT_SECONDS 未通信的僵尸连接

        心跳任务被取消时静默退出，不记录错误。
        """
        try:
            while True:
                await asyncio.sleep(HEARTBEAT_INTERVAL_SECONDS)
                await self._send_heartbeats()
                self._cleanup_zombies()
        except asyncio.CancelledError:
            # 正常取消，静默退出
            pass
        except Exception as exc:
            logger.bind(
                event="ws_heartbeat_error",
                module="ws_manager",
                error_type=type(exc).__name__,
            ).warning(f"心跳循环异常退出: {exc}")

    async def _send_heartbeats(self) -> None:
        """
        向所有活跃连接并发发送心跳 ping 消息。

        发送失败的连接会被立即清理。使用 asyncio.gather 并发发送，
        避免单个慢连接阻塞其他连接的心跳。
        """
        # 收集所有 (session_id, websocket) 对的快照
        all_conns: List[tuple] = []
        for session_id, conns in self._session_connections.items():
            for ws in conns:
                all_conns.append((session_id, ws))

        if not all_conns:
            return

        ping_payload = json.dumps({"type": "ping"}, ensure_ascii=False)

        async def _send_ping(sid: str, ws: WebSocket) -> Optional[tuple]:
            """向单个连接发送 ping，失败时返回 (sid, ws) 以便清理。"""
            try:
                await ws.send_text(ping_payload)
                self._last_activity[id(ws)] = time.monotonic()
                return None
            except Exception:
                # 连接已断开或发送失败，标记为待清理
                return (sid, ws)

        results = await asyncio.gather(
            *[_send_ping(sid, ws) for sid, ws in all_conns],
            return_exceptions=True,
        )

        # 清理发送失败的连接
        for result in results:
            if isinstance(result, tuple) and result[0] is not None:
                sid, ws = result
                self._remove_connection(sid, ws)
                logger.bind(
                    event="ws_heartbeat_dead",
                    module="ws_manager",
                    session_id=sid,
                ).debug("心跳检测到失效连接，已清理")

    def _cleanup_zombies(self) -> None:
        """
        清理超时未通信的僵尸连接。

        遍历所有连接，若 last_activity 距今超过 HEARTBEAT_TIMEOUT_SECONDS，
        则视为僵尸并移除。此机制确保即使客户端静默断开（未触发异常），
        连接也不会无限期残留。
        """
        now = time.monotonic()
        stale: List[tuple] = []
        for session_id, conns in list(self._session_connections.items()):
            for ws in conns:
                last = self._last_activity.get(id(ws), now)
                if now - last > HEARTBEAT_TIMEOUT_SECONDS:
                    stale.append((session_id, ws))

        for session_id, ws in stale:
            self._remove_connection(session_id, ws)
            logger.bind(
                event="ws_zombie_cleaned",
                module="ws_manager",
                session_id=session_id,
            ).debug("清理僵尸 WebSocket 连接")

    def _remove_connection(self, session_id: str, ws: WebSocket) -> None:
        """
        从会话连接列表移除单个连接并清理 last_activity 记录。

        供心跳检测和广播失败清理复用，确保连接移除逻辑一致。
        """
        conns = self._session_connections.get(session_id)
        if not conns:
            return
        try:
            conns.remove(ws)
        except ValueError:
            pass
        self._last_activity.pop(id(ws), None)
        if not conns:
            self._session_connections.pop(session_id, None)

    async def broadcast_to_session(
        self,
        session_id: str,
        message: Dict,
        exclude: Optional[WebSocket] = None,
    ) -> None:
        """
        向会话内所有活跃连接并发广播消息。

        PERF-06: 使用 asyncio.gather 并发发送，避免串行 await 导致
        延迟随连接数线性增长。发送失败的连接会被收集并清理。

        exclude 指定的连接不会被发送（用于排除消息发送者，避免回显）。
        """
        conns = list(self._session_connections.get(session_id, []))
        if not conns:
            return
        payload = json.dumps(message, ensure_ascii=False)

        targets = [ws for ws in conns if ws is not exclude]
        if not targets:
            return

        async def _send_one(ws: WebSocket) -> Optional[WebSocket]:
            """向单个连接发送消息，失败时返回该 ws 以便清理。"""
            try:
                await ws.send_text(payload)
                self._last_activity[id(ws)] = time.monotonic()
                return None
            except Exception as exc:
                logger.bind(
                    event="ws_broadcast_failed",
                    module="ws_manager",
                    session_id=session_id,
                    error_type=type(exc).__name__,
                ).debug(f"广播消息失败，连接可能已断开: {exc}")
                return ws

        # 并发发送到所有目标连接，return_exceptions=True 防止单个异常中断整体
        results = await asyncio.gather(
            *[_send_one(ws) for ws in targets],
            return_exceptions=True,
        )

        # 清理发送失败的连接
        dead = [r for r in results if r is not None and isinstance(r, WebSocket)]
        if dead:
            current = self._session_connections.get(session_id)
            if current:
                for ws in dead:
                    try:
                        current.remove(ws)
                    except ValueError:
                        pass
                    self._last_activity.pop(id(ws), None)
                if not current:
                    self._session_connections.pop(session_id, None)

    async def broadcast_to_user(self, user_id: str, message: Dict) -> None:
        """
        向指定用户的所有会话的所有连接广播消息。

        用于跨会话通知场景（如系统通知、状态变更）。
        各会话的广播通过 gather 并发执行，提升多会话场景吞吐。
        """
        sessions = list(self._user_sessions.get(user_id, set()))
        if not sessions:
            return
        await asyncio.gather(
            *(self.broadcast_to_session(sid, message) for sid in sessions),
            return_exceptions=True,
        )


ws_manager = WebSocketManager()
