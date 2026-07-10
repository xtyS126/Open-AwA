"""
问题反馈路由模块。

提供 POST /api/feedback/issue 端点，接收用户提交的问题反馈，
经 Pydantic 校验后通过 issue_writer 写入 data/issue_reports/ 目录的 JSON 文件。

设计约束（用户明确要求，禁止违反）：
1. 仅提供写入端点，不提供任何 GET 查询端点
2. 不依赖数据库，不写审计日志，不接 RateLimitStore
3. 用户标识仅以 sha256 哈希形式存储，不记录原始 user_id
4. 不在此文件中 import 任何读取/列举/删除文件的 API
"""

import hashlib
import os
from datetime import datetime, timezone
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException
from loguru import logger

from api.dependencies import get_current_user
from issue_writer import write_issue
from issue_writer.schemas import IssueFeedbackPayload


router = APIRouter(prefix="/api/feedback", tags=["feedback"])


@router.post("/issue", summary="提交问题反馈")
async def submit_issue(
    body: IssueFeedbackPayload,
    current_user=Depends(get_current_user),
) -> Dict[str, Any]:
    """
    接收用户提交的问题反馈，写入 data/issue_reports/ 目录。

    仅执行写入操作，不返回文件内容，不提供读取端点。
    用户标识以 sha256 哈希形式存储，不记录原始 user_id。
    """
    salt = os.environ.get("ISSUE_FEEDBACK_SALT", "open-awa-issue-salt-v1")
    user_id_hash = "sha256:" + hashlib.sha256(
        f"{current_user.id}:{salt}".encode()
    ).hexdigest()

    payload = {
        "issue_type": body.issue_type,
        "title": body.title,
        "content": body.content,
        "page_url": body.page_url,
        "submitted_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "user_id_hash": user_id_hash,
    }

    try:
        file_id = write_issue(payload)
    except OSError as exc:
        logger.bind(
            event="issue_feedback_write_failed",
            module="feedback",
            action="submit_issue",
            status="failure",
            user_id_hash=user_id_hash,
        ).error("问题反馈写入失败", exc_info=exc)
        raise HTTPException(status_code=500, detail="写入失败")

    return {"ok": True, "file_id": file_id}
