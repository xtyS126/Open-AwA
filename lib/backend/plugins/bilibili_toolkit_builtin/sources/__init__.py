"""四种 B 站订阅源扫描模块。

阶段 6 实现：提供四种订阅源的扫描函数，统一返回 ``list[ScanResult]``，
不写库；持久化与增量水位线更新由阶段 13+ 的数据库与阶段 14 的 workflow
编排层处理。

模块导出：

- :class:`ScanResult`：扫描结果数据类
- :func:`scan_favorite`：收藏夹源（增量扫描，水位线 ``fav_time``）
- :func:`scan_season` / :func:`scan_series`：合集源（全量扫描）
- :func:`scan_submission`：UP 主投稿源（增量扫描，水位线 ``pubtime``，WBI 签名）
- :func:`scan_watchlater`：稍后再看源（全量扫描，全局唯一订阅 id=1）

风控处理：所有 scan 函数在调用 ``client.request()`` 时由
:func:`bilibili.risk_control.check_response` 自动检测风控信号
（HTTP 412/403 / code=-352 / v_voucher），触发时抛出
:class:`bilibili.risk_control.RiskControlError`，不在本层捕获，
由编排层处理整轮熔断。
"""

from __future__ import annotations

from .collection import scan_season, scan_series
from .favorite import scan_favorite
from .submission import scan_submission
from .types import ScanResult
from .watchlater import scan_watchlater

__all__ = [
    # 数据类
    "ScanResult",
    # 收藏夹源
    "scan_favorite",
    # 合集源
    "scan_season",
    "scan_series",
    # 投稿源
    "scan_submission",
    # 稍后再看源
    "scan_watchlater",
]
