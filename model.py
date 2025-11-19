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
    event_time: Optional[datetime] = None

class EventCreate(EventBase):
    created_by: int

class EventUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    location: Optional[str] = None
    event_time: Optional[datetime] = None

class EventResponse(EventBase):
    event_id: int
    created_by: int
    created_at: datetime

    class Config:
        orm_mode = True
