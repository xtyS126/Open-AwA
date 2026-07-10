"""问题反馈 payload schema。"""

from typing import Literal

from pydantic import BaseModel, Field


class IssueFeedbackPayload(BaseModel):
    """前端提交的问题反馈载荷。"""

    issue_type: Literal["bug", "suggestion", "question", "other"] = Field(
        ..., description="问题类型"
    )
    title: str = Field(..., min_length=1, max_length=200, description="问题标题")
    content: str = Field(..., min_length=1, max_length=10000, description="问题内容")
    page_url: str = Field(default="", max_length=500, description="反馈时所在页面 URL")
