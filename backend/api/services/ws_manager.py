"""
WebSocket 连接管理服务层，负责管理连接的生命周期和活跃连接状态。

支持同一会话多设备并发连接，实现多端消息实时同步。
内部维护两张映射表：
  - _session_connections: session_id -> 该会话所有 WebSocket 连接列表
  - _user_sessions: user_id -> 该用户关联的 session_id 集合
"""

import json
from typing import Dict, List, Optional, Set

from fastapi import WebSocket
from loguru import logger


class WebSocketManager:
    """
    管理 WebSocket 连接，支持会话级多设备并发。

    同一 session_id 可有多个设备同时连接，消息可广播到会话内所有设备，
    也可按 user_id 跨会话广播，满足多端互通场景。
    """

    def __init__(self) -> None:
        # session_id -> 该会话所有活跃 WebSocket 连接
        self._session_connections: Dict[str, List[WebSocket]] = {}
        # user_id -> 该用户关联的 session_id 集合（用于跨会话广播）
        self._user_sessions: Dict[str, Set[str]] = {}

    async def connect(
        self,
        session_id: str,
        websocket: WebSocket,
        user_id: Optional[str] = None,
    ) -> None:
        """
        接受 WebSocket 连接并注册到会话连接列表。

        同一 session_id 的多次连接会追加到列表，实现多设备并发。
        若传入 user_id，则建立 user -> session 映射，支持用户级广播。
        """
        await websocket.accept()
        conns = self._session_connections.setdefault(session_id, [])
        conns.append(websocket)
        if user_id:
            self._user_sessions.setdefault(user_id, set()).add(session_id)
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
            # 清空整个会话（旧行为）
            self._session_connections.pop(session_id, None)
            return
        try:
            conns.remove(websocket)
        except ValueError:
            # 连接不在列表中，忽略
            pass
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

    async def broadcast_to_session(
        self,
        session_id: str,
        message: Dict,
        exclude: Optional[WebSocket] = None,
    ) -> None:
        """
        向会话内所有活跃连接广播消息。

        exclude 指定的连接不会被发送（用于排除消息发送者，避免回显）。
        发送失败的连接会被收集并清理，避免僵尸连接影响后续广播。
        """
        conns = list(self._session_connections.get(session_id, []))
        if not conns:
            return
        payload = json.dumps(message, ensure_ascii=False)
        dead: List[WebSocket] = []
        for ws in conns:
            if ws is exclude:
                continue
            try:
                await ws.send_text(payload)
            except Exception as exc:
                logger.bind(
                    event="ws_broadcast_failed",
                    module="ws_manager",
                    session_id=session_id,
                    error_type=type(exc).__name__,
                ).debug(f"广播消息失败，连接可能已断开: {exc}")
                dead.append(ws)
        # 清理失效连接
        if dead:
            current = self._session_connections.get(session_id)
            if current:
                for ws in dead:
                    try:
                        current.remove(ws)
                    except ValueError:
                        pass
                if not current:
                    self._session_connections.pop(session_id, None)

    async def broadcast_to_user(self, user_id: str, message: Dict) -> None:
        """
        向指定用户的所有会话的所有连接广播消息。

        用于跨会话通知场景（如系统通知、状态变更）。
        """
        sessions = list(self._user_sessions.get(user_id, set()))
        for session_id in sessions:
            await self.broadcast_to_session(session_id, message)


ws_manager = WebSocketManager()
