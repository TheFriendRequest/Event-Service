from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from routers import events
# from database import Base, engine

# Create all tables (if not exist)
# Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="Event Service",
    description="Handles user-to-user event management",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(events.router)

@app.get("/")
def root():
    return {"status": "Event Service running"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
