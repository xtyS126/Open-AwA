"""
模型等级（Model Tier）域 ORM 模型。

将系统内各类 LLM 调用归类为四档「等级」，每档绑定一个 provider/model
供对应功能调用：

- fable  旗舰级：主对话回复
- opus   强级：复杂任务执行（规划/代码/多步工具）
- sonnet 均衡级：后台常规任务（记忆整合/日记/摘要）
- haiku  轻量级：抽取层（情感/事件评估，快速低成本）

Subagent 的模型由主 Agent 根据任务自行选择，不在此四档内固定设置。

provider/model 为空表示该档未显式指定，调用方应回退到默认模型配置。
"""

from datetime import datetime, timezone

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from db.models.base import Base


class ModelTierConfig(Base):
    """模型等级配置：每档一行，绑定 provider/model。"""

    __tablename__ = "model_tier_configs"

    # 档位标识：fable / opus / sonnet / haiku
    tier: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    # 绑定的 provider（可为空，表示未显式指定）
    provider: Mapped[str] = mapped_column(String, nullable=True, default="")
    # 绑定的 model（可为空）
    model: Mapped[str] = mapped_column(String, nullable=True, default="")

    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc)
    )