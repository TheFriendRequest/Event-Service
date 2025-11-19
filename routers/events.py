from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from typing import List
from datetime import datetime
from model import Base, Event, EventCreate, EventUpdate, EventResponse

# -------------------------
# Database setup
# -------------------------
SQLALCHEMY_DATABASE_URL = "sqlite:///./events.db"  # change to Postgres/MySQL if needed
engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# create tables
Base.metadata.create_all(bind=engine)

# -------------------------
# FastAPI router
# -------------------------
router = APIRouter(prefix="/events", tags=["Events"])

# Dependency
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# -------------------------
# CRUD Operations
# -------------------------
def get_event(db: Session, event_id: int):
    return db.query(Event).filter(Event.event_id == event_id, Event.deleted == False).first()

def get_events(db: Session):
    return db.query(Event).filter(Event.deleted == False).all()

def create_event(db: Session, event: EventCreate):
    db_event = Event(
        title=event.title,
        description=event.description,
        location=event.location,
        event_time=event.event_time,
        created_by=event.created_by,
        created_at=datetime.utcnow(),
        deleted=False
    )
    db.add(db_event)
    db.commit()
    db.refresh(db_event)
    return db_event

def update_event(db: Session, db_event: Event, event_update: EventUpdate):
    for key, value in event_update.dict(exclude_unset=True).items():
        setattr(db_event, key, value)
    db.commit()
    db.refresh(db_event)
    return db_event

def delete_event(db: Session, db_event: Event):
    db_event.deleted = True
    db.commit()
    return db_event

# -------------------------
# API Endpoints
# -------------------------
@router.get("/", response_model=List[EventResponse])
def read_events(db: Session = Depends(get_db)):
    return get_events(db)

@router.get("/{event_id}", response_model=EventResponse)
def read_event(event_id: int, db: Session = Depends(get_db)):
    db_event = get_event(db, event_id)
    if not db_event:
        raise HTTPException(status_code=404, detail="Event not found")
    return db_event

@router.post("/", response_model=EventResponse)
def create_new_event(event: EventCreate, db: Session = Depends(get_db)):
    return create_event(db, event)

@router.put("/{event_id}", response_model=EventResponse)
@router.patch("/{event_id}", response_model=EventResponse)
def update_existing_event(event_id: int, event_update: EventUpdate, db: Session = Depends(get_db)):
    db_event = get_event(db, event_id)
    if not db_event:
        raise HTTPException(status_code=404, detail="Event not found")
    return update_event(db, db_event, event_update)

@router.delete("/{event_id}")
def delete_existing_event(event_id: int, db: Session = Depends(get_db)):
    db_event = get_event(db, event_id)
    if not db_event:
        raise HTTPException(status_code=404, detail="Event not found")
    delete_event(db, db_event)
    return {"msg": f"Event {event_id} deleted successfully"}
