from pydantic import BaseModel
from datetime import datetime
from typing import Optional

# --------------------------
# Event Schemas
# --------------------------
class EventBase(BaseModel):
    title: str
    description: Optional[str] = None
    location: Optional[str] = None
    start_time: datetime
    end_time: datetime
    capacity: Optional[int] = None

class EventCreate(EventBase):
    created_by: int  # user_id passed from Composite Service

class EventUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    location: Optional[str] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    capacity: Optional[int] = None

class EventResponse(EventBase):
    event_id: int
    created_by: int
    created_at: datetime
    interests: Optional[list] = []
    links: Optional[dict] = {}

    class Config:
        orm_mode = True
