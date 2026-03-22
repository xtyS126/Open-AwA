from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session
from typing import Dict, List
from db.models import get_db
from api.dependencies import get_current_user
from api.schemas import ChatMessage, ChatResponse, ConfirmationRequest
from core.agent import AIAgent
from core.feedback import FeedbackLayer
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
async def websocket_endpoint(websocket: WebSocket, session_id: str):
    await websocket.accept()
    active_connections[session_id] = websocket
    
    try:
        while True:
            data = await websocket.receive_text()
            message_data = json.loads(data)
            
            if message_data.get("type") == "message":
                context = {
                    "session_id": session_id,
                    "user_id": "anonymous"
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
                
                context = {"session_id": session_id, "user_id": "anonymous"}
                result = await agent.handle_confirmation(confirmed, step, context)
                
                await websocket.send_json({
                    "type": "confirmation_result",
                    "result": result
                })
                
    except WebSocketDisconnect:
        if session_id in active_connections:
            del active_connections[session_id]


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
