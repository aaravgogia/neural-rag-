from pydantic import BaseModel, Field, EmailStr, ConfigDict
from typing import List, Optional, Dict, Any
from datetime import datetime

class UserCreate(BaseModel):
    email: EmailStr
    name: str
    picture: Optional[str] = None
    google_id: str

class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    email: str
    name: str
    picture: Optional[str] = None
    is_premium: bool
    total_queries: int
    total_documents: int
    created_at: datetime

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse

class AuthCodeExchange(BaseModel):
    code: str = Field(..., min_length=20, max_length=256)

class APIKeyCreate(BaseModel):
    name: str = Field("API key", min_length=1, max_length=80)

class APIKeyResponse(BaseModel):
    id: str
    name: str
    prefix: str
    created_at: datetime
    last_used_at: Optional[datetime] = None
    # Returned only by POST, never reconstructed or stored.
    key: Optional[str] = None

class ChatSessionCreate(BaseModel):
    title: Optional[str] = "New Chat"
    namespace: Optional[str] = "default"
    workspace_id: str

class ChatSessionResponse(BaseModel):
    id: str
    title: str
    namespace: str
    workspace_id: Optional[str] = None
    message_count: int
    created_at: datetime
    updated_at: datetime

class ChatRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    session_id: str
    namespace: Optional[str] = "default"
    use_agent: bool = True
    workspace_id: Optional[str] = None

class WorkspaceCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)

class WorkspaceInvite(BaseModel):
    email: EmailStr
    role: str = Field("viewer", pattern="^(editor|viewer)$")

class WorkspaceResponse(BaseModel):
    id: str
    name: str
    owner_id: str
    role: str
    plan: str = "free"
    created_at: datetime

class WorkspaceMemberResponse(BaseModel):
    user_id: str
    email: str
    name: Optional[str] = None
    role: str

class ChatResponse(BaseModel):
    answer: str
    sources: List[Dict[str, Any]] = []
    session_id: str
    question: str
    processing_time: float
    message_id: str

class MessageResponse(BaseModel):
    id: str
    role: str
    content: str
    sources: List[Dict] = []
    processing_time: Optional[float] = None
    created_at: datetime

class FeedbackCreate(BaseModel):
    message_id: str
    session_id: str
    rating: str = Field(..., pattern="^(up|down)$")
    comment: Optional[str] = Field(None, max_length=1000)

class FeedbackResponse(BaseModel):
    id: str
    message_id: str
    session_id: str
    rating: str
    comment: Optional[str] = None
    eval_metric_id: Optional[str] = None
    created_at: datetime

class DocumentResponse(BaseModel):
    id: str
    filename: str
    file_size: int
    file_type: str
    namespace: str
    chunks_count: int
    status: str
    created_at: datetime

    class Config:
        from_attributes = True

class AnalyticsResponse(BaseModel):
    total_queries: int
    total_documents: int
    total_sessions: int
    queries_today: int
    avg_response_time: float
    top_topics: List[Dict] = []
    daily_activity: List[Dict] = []
    document_types: List[Dict] = []
