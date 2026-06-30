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


class ServiceItem(BaseModel):
    name: str
    price: Optional[float] = None
    duration_minutes: Optional[int] = None
    description: Optional[str] = None


class StaffMember(BaseModel):
    name: str
    role: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    services: list[str] = Field(default_factory=list)


class FAQItem(BaseModel):
    question: str
    answer: str


class OnboardRequest(BaseModel):
    # Core identity
    name: str
    industry: str
    phone: Optional[str] = None
    email: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    timezone: str = "America/New_York"
    website: Optional[str] = None

    # Business brain — how agents should operate for THIS business
    services: list[ServiceItem] = Field(default_factory=list)
    staff: list[StaffMember] = Field(default_factory=list)
    business_hours: dict[str, str] = Field(default_factory=dict)   # {"mon": "9-5", ...}
    booking_url: Optional[str] = None                              # Cal.com link
    brand_voice: str = "friendly, professional, concise"
    target_customer: Optional[str] = None
    monthly_revenue_goal: Optional[float] = None
    avg_ticket_value: Optional[float] = None
    policies: list[str] = Field(default_factory=list)              # cancellation, refund, etc.
    faqs: list[FAQItem] = Field(default_factory=list)
    competitors: list[str] = Field(default_factory=list)
    unique_selling_points: list[str] = Field(default_factory=list)


class OnboardUpdateRequest(BaseModel):
    """Partial update of an existing business profile."""
    business_id: UUID
    updates: dict[str, Any] = Field(default_factory=dict)
