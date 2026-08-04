"""
向量模型配置 ORM 模型（Spec memory-model-config-chain）。

以 key-value 形式持久化嵌入/重排模型配置，支持前端设置页读写：
- embedding_provider / embedding_model / embedding_api_key / embedding_api_endpoint
- rerank_provider / rerank_model / rerank_api_key / rerank_api_endpoint
- model_download_source

配置在 MemoryManager / VectorStoreManager 初始化时叠加到 settings 之上
（DB 配置优先于 env 默认值），重启后仍保留。
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from db.models.base import Base


class VectorModelConfig(Base):
    """向量模型配置键值对。"""

    __tablename__ = "vector_model_config"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
