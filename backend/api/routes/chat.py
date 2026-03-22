from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect, Query
from sqlalchemy.orm import Session
from typing import Dict, List
from loguru import logger
from db.models import get_db
from api.dependencies import get_current_user
from api.schemas import ChatMessage, ChatResponse, ConfirmationRequest
from core.agent import AIAgent
from core.feedback import FeedbackLayer
from config.security import decode_access_token
from db.models import User
import json


router = APIRouter(prefix="/chat", tags=["Chat"])


agent = AIAgent()
active_connections: Dict[str, WebSocket] = {}


@router.post("", response_model=ChatResponse)
async def chat(
    message: ChatMessage,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    context = {
        "user_id": current_user.id,
        "session_id": message.session_id,
        "username": current_user.username
    }
    
    result = await agent.process(message.message, context)
    
    return ChatResponse(
        status=result.get("status"),
        response=result.get("response", ""),
        session_id=message.session_id
    )


@router.post("/confirm")
async def confirm_operation(
    confirmation: ConfirmationRequest,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    if not confirmation.step:
        raise HTTPException(status_code=400, detail="No step provided for confirmation")
    
    context = {
        "user_id": current_user.id,
        "session_id": "default",
        "username": current_user.username
    }
    
    result = await agent.handle_confirmation(
        confirmed=confirmation.confirmed,
        step=confirmation.step,
        context=context
    )
    
    return result


@router.websocket("/ws/{session_id}")
async def websocket_endpoint(
    websocket: WebSocket,
    session_id: str,
    token: str = Query(None)
):
    if token is None:
        await websocket.close(code=4001, reason="Missing authentication token")
        return
    
    payload = decode_access_token(token)
    if payload is None:
        await websocket.close(code=4002, reason="Invalid or expired token")
        return
    
    username = payload.get("sub")
    if username is None:
        await websocket.close(code=4003, reason="Invalid token payload")
        return
    
    db_gen = get_db()
    db = next(db_gen)
    
    try:
        user = db.query(User).filter(User.username == username).first()
        if user is None:
            await websocket.close(code=4004, reason="User not found")
            return
    except Exception as e:
        logger.error(f"Database query failed: {type(e).__name__}")
        await websocket.close(code=4004, reason="Database error")
        return
    finally:
        try:
            db_gen.close()
        except Exception as e:
            logger.error(f"Failed to close database connection in WebSocket auth: {type(e).__name__}")
            try:
                if hasattr(db_gen, 'remove'):
                    db_gen.remove()
            except Exception:
                logger.warning("Unable to clean up database connection resources")
        logger.debug(f"Database connection cleanup completed for session {session_id}")
    
    await websocket.accept()
    
    user_id = user.id
    active_connections[session_id] = websocket
    
    try:
        while True:
            data = await websocket.receive_text()
            message_data = json.loads(data)
            
            if message_data.get("type") == "message":
                context = {
                    "session_id": session_id,
                    "user_id": user_id,
                    "username": username
                }
                
                result = await agent.process(message_data.get("content", ""), context)
                
                await websocket.send_json({
                    "type": "response",
                    "status": result.get("status"),
                    "content": result.get("response", ""),
                    "results": result.get("results", [])
                })
                
            elif message_data.get("type") == "confirm":
                confirmed = message_data.get("confirmed", False)
                step = message_data.get("step")
                
                context = {
                    "session_id": session_id,
                    "user_id": user_id,
                    "username": username
                }
                result = await agent.handle_confirmation(confirmed, step, context)
                
                await websocket.send_json({
                    "type": "confirmation_result",
                    "result": result
                })
                
    except WebSocketDisconnect:
        if session_id in active_connections:
            del active_connections[session_id]
    except Exception as e:
        if session_id in active_connections:
            del active_connections[session_id]
        await websocket.close(code=4005, reason="Internal server error")
    finally:
        try:
            db_gen.close()
        except:
            pass


@router.get("/history/{session_id}")
async def get_chat_history(
    session_id: str,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    from db.models import ShortTermMemory
    
    messages = db.query(ShortTermMemory).filter(
        ShortTermMemory.session_id == session_id
    ).order_by(ShortTermMemory.timestamp).all()
    
    return [
        {
            "id": msg.id,
            "role": msg.role,
            "content": msg.content,
            "timestamp": msg.timestamp
        }
        for msg in messages
    ]
