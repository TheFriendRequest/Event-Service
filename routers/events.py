from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from datetime import datetime
from typing import Optional, List

router = APIRouter(prefix="/events", tags=["Events"])

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

# -------------------------
# In-memory storage for demo
# -------------------------
events: List[EventResponse] = []

# -------------------------
# CRUD Endpoints
# -------------------------
@router.get("/", response_model=List[EventResponse])
def get_events():
    return events

@router.post("/", response_model=EventResponse)
def create_event(event: EventCreate):
    event_id = len(events) + 1
    created_at = datetime.now()
    new_event = EventResponse(
        event_id=event_id,
        title=event.title,
        description=event.description,
        location=event.location,
        event_time=event.event_time,
        created_by=event.created_by,
        created_at=created_at
    )
    events.append(new_event)
    return new_event

@router.put("/{event_id}", response_model=EventResponse)
def update_event(event_id: int, update: EventUpdate):
    for e in events:
        if e.event_id == event_id:
            updated_data = update.dict(exclude_unset=True)
            for key, value in updated_data.items():
                setattr(e, key, value)
            return e
    raise HTTPException(status_code=404, detail="Event not found")

@router.delete("/{event_id}")
def delete_event(event_id: int):
    global events
    for e in events:
        if e.event_id == event_id:
            events = [ev for ev in events if ev.event_id != event_id]
            return {"msg": f"Event {event_id} deleted successfully"}
    raise HTTPException(status_code=404, detail="Event not found")
