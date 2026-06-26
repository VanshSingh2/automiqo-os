from pydantic import BaseModel, Field
from typing import Any, Optional
from uuid import UUID
from datetime import datetime
from enum import Enum


class TaskPriority(str, Enum):
    HIGH = "high"
    NORMAL = "normal"
    LOW = "low"


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class TaskRequest(BaseModel):
    business_id: UUID
    created_by: str
    workflow: str
    priority: TaskPriority = TaskPriority.NORMAL
    parameters: dict[str, Any] = Field(default_factory=dict)


class TaskResult(BaseModel):
    task_id: UUID
    success: bool
    data: dict[str, Any] = Field(default_factory=dict)
    message: str = ""
    error: Optional[str] = None


class AgentResponse(BaseModel):
    status: str
    metrics: dict[str, Any] = Field(default_factory=dict)
    recommendations: list[str] = Field(default_factory=list)
    tasks_to_dispatch: list[TaskRequest] = Field(default_factory=list)
    summary: str = ""


class BusinessConfig(BaseModel):
    business_id: Optional[UUID] = None
    id: Optional[UUID] = None
    name: str
    industry: str
    phone: Optional[str] = None
    email: Optional[str] = None
    address: Optional[str] = None
    timezone: str = "America/New_York"

    @property
    def get_id(self) -> Optional[UUID]:
        return self.business_id or self.id


class CustomerProfile(BaseModel):
    id: UUID
    business_id: UUID
    name: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    tags: list[str] = Field(default_factory=list)
    lifetime_value: float = 0
    last_visit: Optional[datetime] = None
    visit_count: int = 0
    opt_out_sms: bool = False
    opt_out_email: bool = False


class ChatMessage(BaseModel):
    role: str
    content: str
    timestamp: Optional[datetime] = None


class ChatRequest(BaseModel):
    business_id: UUID
    message: str
    history: list[ChatMessage] = Field(default_factory=list)


class OnboardRequest(BaseModel):
    name: str
    industry: str
    phone: Optional[str] = None
    email: Optional[str] = None
    address: Optional[str] = None
    timezone: str = "America/New_York"
