"""B 站弹幕下载与 ASS 渲染模块。

提供：
- :class:`DanmakuElem`：protobuf 弹幕元素消息类
- :func:`parse_danmaku_segs`：解析 ``/x/v2/dm/wbi/web/seg.so`` protobuf 响应
- :func:`fetch_danmaku`：按 360 秒分段并发拉取弹幕
- :class:`DanmakuOption`：ASS 渲染选项（字体 / 字号 / 透明度等）
- :func:`render_ass`：将弹幕列表渲染为 ASS 字幕字符串（含 lane 碰撞算法）

模块依赖：
- ``protobuf>=4.0``：运行时构造 DanmakuElem Message 类
- ``pydantic>=2.0``：DanmakuOption 数据校验
- ``httpx``：通过 :class:`BilibiliClient` 发起 HTTP 请求
"""

from __future__ import annotations

from .ass import ASS_PLAY_RES_X, ASS_PLAY_RES_Y, DanmakuOption, render_ass
from .fetcher import (
    DANMAKU_SEG_ENDPOINT,
    SEGMENT_DURATION_SECONDS,
    fetch_danmaku,
)
from .proto import DanmakuElem, parse_danmaku_segs

__all__ = [
    # proto
    "DanmakuElem",
    "parse_danmaku_segs",
    # fetcher
    "DANMAKU_SEG_ENDPOINT",
    "SEGMENT_DURATION_SECONDS",
    "fetch_danmaku",
    # ass
    "ASS_PLAY_RES_X",
    "ASS_PLAY_RES_Y",
    "DanmakuOption",
    "render_ass",
]
