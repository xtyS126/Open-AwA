"""
魔法命令 API 路由 — 提供魔法命令的查询和执行接口。
支持列出所有可用命令、执行指定命令、手动触发上下文压缩。
"""
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from api.dependencies import get_current_user
from core.magic_commands import get_magic_command_registry
from db.models import get_db

router = APIRouter(prefix="/magic-commands", tags=["Magic Commands"])


@router.get("", summary="列出所有可用的魔法命令")
async def list_commands(current_user=Depends(get_current_user)):
    """返回所有已注册的魔法命令列表，包含名称、描述和属性。"""
    registry = get_magic_command_registry()
    return {"commands": registry.list_commands(), "total": len(registry.list_commands())}


@router.post("/execute", summary="执行指定的魔法命令")
async def execute_command(
    body: Dict[str, Any],
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """
    执行指定的魔法命令。
    请求体需包含 command_name，可选 context 字典（如 session_id、workspace_id 等）。
    """
    command_name = body.get("command_name", "").strip()
    if not command_name:
        raise HTTPException(status_code=400, detail="缺少 command_name 参数")

    registry = get_magic_command_registry()
    command = registry.get_command(command_name)
    if command is None:
        raise HTTPException(status_code=404, detail=f"未找到命令: /{command_name}")

    ctx = body.get("context", {})
    ctx.setdefault("user_id", getattr(current_user, "id", ""))
    ctx.setdefault("db", db)

    try:
        result = await command.handler(ctx)
        return {"success": True, "command": command_name, "result": result}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"命令执行失败: {str(exc)}")


@router.post("/compact", summary="手动触发上下文压缩")
async def trigger_compact(
    body: Dict[str, Any],
    current_user=Depends(get_current_user),
):
    """
    手动触发当前会话的上下文压缩。
    将对话历史压缩为摘要，保留最近几轮完整对话。
    """
    from core.context.compressor import ContextCompressor
    from core.context.token_budget import TokenBudget
    from memory.manager import MemoryManager

    session_id = body.get("session_id", "default")
    workspace_id = body.get("workspace_id", "default")
    model_name = body.get("model_name", "default")

    # 验证会话归属：确保用户只能压缩自己的会话
    if session_id and session_id != "default":
        from db.models import ConversationRecord, SessionLocal
        with SessionLocal() as verify_db:
            owner = verify_db.query(ConversationRecord.user_id).filter(
                ConversationRecord.session_id == session_id
            ).first()
            if owner and str(owner[0]) != str(current_user.id):
                raise HTTPException(status_code=403, detail="无权访问此会话")

    try:
        memory_manager = MemoryManager()
        messages = await memory_manager.get_short_term_memories(
            session_id=session_id, limit=100
        )
        history = [
            {"role": m.role, "content": m.content}
            for m in reversed(messages)
            if m.role in ("user", "assistant")
        ]

        compressor = ContextCompressor()
        budget = TokenBudget(model_name=model_name)
        current_tokens = budget.count_messages(history)

        if compressor.should_compress(current_tokens, budget.max_tokens):
            result = compressor.compress(history)
            return {
                "success": True,
                "compressed": True,
                "removed_count": result["removed_count"],
                "summary": result["summary"][:500] if result["summary"] else "",
                "stats": {
                    "original_tokens": current_tokens,
                    "max_tokens": budget.max_tokens,
                    "usage_ratio": round(current_tokens / budget.max_tokens, 3) if budget.max_tokens > 0 else 0,
                },
            }
        else:
            return {
                "success": True,
                "compressed": False,
                "message": "当前上下文未达到压缩阈值，无需压缩",
                "stats": {
                    "current_tokens": current_tokens,
                    "max_tokens": budget.max_tokens,
                    "usage_ratio": round(current_tokens / budget.max_tokens, 3) if budget.max_tokens > 0 else 0,
                },
            }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"上下文压缩失败: {str(exc)}")
