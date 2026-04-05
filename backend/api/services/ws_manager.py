"""
WebSocket 连接管理服务层，负责管理连接的生命周期和活跃连接状态。
"""

from typing import Dict
from fastapi import WebSocket

class WebSocketManager:
    """
    管理 WebSocket 连接的类。
    """
    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}

    async def connect(self, session_id: str, websocket: WebSocket):
        """
        接受 WebSocket 连接并保存到活跃连接字典中。
        """
        await websocket.accept()
        self.active_connections[session_id] = websocket

    def disconnect(self, session_id: str):
        """
        从活跃连接字典中移除指定的连接。
        """
        if session_id in self.active_connections:
            del self.active_connections[session_id]

    def get_connection(self, session_id: str) -> WebSocket | None:
        """
        获取指定的 WebSocket 连接。
        """
        return self.active_connections.get(session_id)

ws_manager = WebSocketManager()
