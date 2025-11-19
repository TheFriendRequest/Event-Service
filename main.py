from fastapi import FastAPI
from routers.events import router as events
# from database import Base, engine

# Create all tables (if not exist)
# Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="Event Service",
    description="Handles user-to-user event management",
    version="1.0.0"
)

app.include_router(events)

@app.get("/")
def root():
    return {"status": "Event Service running"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
