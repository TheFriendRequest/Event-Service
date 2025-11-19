from sqlalchemy import Column, Integer, String, DateTime, Boolean
from sqlalchemy.ext.declarative import declarative_base
from pydantic import BaseModel
from datetime import datetime
from typing import Optional

Base = declarative_base()

# -------------------------
# SQLAlchemy Model
# -------------------------
class Event(Base):
    __tablename__ = "events"

    event_id = Column(Integer, primary_key=True, index=True)
    title = Column(String, nullable=False)
    description = Column(String, nullable=True)
    location = Column(String, nullable=True)
    event_time = Column(DateTime, nullable=True)
    created_by = Column(Integer, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    deleted = Column(Boolean, default=False)

# -------------------------
# Pydantic Schemas
# -------------------------
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
    deleted: bool

    class Config:
        orm_mode = True
