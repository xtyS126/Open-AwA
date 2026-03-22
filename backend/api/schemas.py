from pydantic import BaseModel
from typing import Optional, List, Any, Dict
from datetime import datetime


class UserBase(BaseModel):
    username: str


class UserCreate(UserBase):
    password: str


class UserResponse(UserBase):
    id: str
    role: str
    created_at: datetime
    
    class Config:
        from_attributes = True


class Token(BaseModel):
    access_token: str
    token_type: str


class TokenData(BaseModel):
    username: Optional[str] = None


class ChatMessage(BaseModel):
    message: str
    session_id: Optional[str] = "default"


class ChatResponse(BaseModel):
    status: str
    response: str
    session_id: Optional[str] = None


class SkillBase(BaseModel):
    name: str
    version: Optional[str] = None
    description: Optional[str] = None


class SkillCreate(SkillBase):
    config: str


class SkillResponse(SkillBase):
    id: str
    enabled: bool
    installed_at: datetime
    
    class Config:
        from_attributes = True


class PluginBase(BaseModel):
    name: str
    version: Optional[str] = None


class PluginCreate(PluginBase):
    config: Optional[str] = None


class PluginResponse(PluginBase):
    id: str
    enabled: bool
    installed_at: datetime
    
    class Config:
        from_attributes = True


class MemoryBase(BaseModel):
    content: str


class ShortTermMemoryCreate(MemoryBase):
    session_id: str
    role: str


class LongTermMemoryCreate(MemoryBase):
    importance: Optional[float] = 0.5


class ShortTermMemoryResponse(MemoryBase):
    id: int
    session_id: str
    role: str
    timestamp: datetime
    
    class Config:
        from_attributes = True


class LongTermMemoryResponse(MemoryBase):
    id: int
    importance: float
    created_at: datetime
    access_count: int
    last_access: datetime
    
    class Config:
        from_attributes = True


class PromptConfigBase(BaseModel):
    name: str
    content: str
    variables: Optional[str] = None


class PromptConfigCreate(PromptConfigBase):
    pass


class PromptConfigUpdate(BaseModel):
    name: Optional[str] = None
    content: Optional[str] = None
    variables: Optional[str] = None
    is_active: Optional[bool] = None


class PromptConfigResponse(PromptConfigBase):
    id: str
    is_active: bool
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True


class BehaviorStats(BaseModel):
    total_interactions: int
    total_tools_used: int
    total_errors: int
    top_tools: List[Any]
    top_intents: List[Any]
    average_response_time: float


class ConfirmationRequest(BaseModel):
    confirmed: bool
    step: Optional[Dict[str, Any]] = None
