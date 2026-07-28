"""bilibili-toolkit-builtin 下载流水线编排模块。

阶段 14 实现：提供单个视频与订阅级两层的下载编排能力，统一以
:class:`WorkflowResult` 纯数据结构向上层返回结果，不在本层写库。

模块导出：

- :class:`WorkflowResult`：单次下载任务结果（分页级），含位图与产出文件列表
- :class:`WorkflowError`：下载流水线异常（携带 reason 标识）
- :func:`download_video`：下载单个视频的所有分 P（视频层编排）
- :func:`download_subscription`：下载整个订阅源的所有视频（订阅级编排）

设计要点：

1. **5 路并发子任务**：分页层用 ``asyncio.gather`` 并发执行封面 / 视频 /
   NFO / 弹幕 / 字幕 5 个子任务，对应 :class:`SubTask` 位图的 5 个槽位
2. **风控熔断**：任一子任务抛 :class:`RiskControlError` 立即终止其他子任务，
   已完成子任务的位图保留，未完成的子任务保持 ``Skipped`` 状态；
   订阅级同样在任一视频触发风控时终止整个订阅处理
3. **失败不阻塞**：除风控异常外，子任务失败仅标记自身为 ``Failed``，
   不影响其他子任务继续执行
4. **不写库**：本模块仅返回 :class:`WorkflowResult` 纯数据，持久化由上层
   路由（阶段 15）处理
"""

from __future__ import annotations

from .orchestrator import download_subscription
from .pipeline import WorkflowError, WorkflowResult, download_page, download_video

__all__ = [
    # 数据类
    "WorkflowResult",
    # 异常类
    "WorkflowError",
    # 视频层编排
    "download_video",
    "download_page",
    # 订阅级编排
    "download_subscription",
]
