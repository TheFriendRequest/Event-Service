from fastapi import FastAPI
from routers import events
from database import Base, engine

# Create all tables (if not exist)
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="Event Service",
    description="Handles user-to-user event management",
    version="1.0.0"
)

app.include_router(events.router)

@app.get("/")
def root():
    return {"status": "Event Service running"}
