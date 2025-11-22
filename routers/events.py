from fastapi import APIRouter, HTTPException, Depends, status
from typing import Optional, Dict, Any, cast
from datetime import datetime
import os
import sys
import mysql.connector

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from auth import verify_firebase_token, get_firebase_uid
from model import EventCreate, EventUpdate, EventResponse

# Debug: Print DB environment variables
print("----DEBUG ENV----")
print(os.getenv("DB_HOST"), os.getenv("DB_PORT"))
print("------------------")


router = APIRouter(prefix="/events", tags=["Events"])


# ----------------------
# DB Connection
# ----------------------
def get_connection():
    host = os.getenv("DB_HOST", "127.0.0.1")
    port = int(os.getenv("DB_PORT", "3307"))
    user = os.getenv("DB_USER", "event_user")
    password = os.getenv("DB_PASSWORD", "")
    database = os.getenv("DB_NAME", "")

    print("----DEBUG MYSQL CONNECTION PARAMS----")
    print("HOST =", host)
    print("PORT =", port)
    print("USER =", user)
    print("DB =", database)
    print("------------------------------------")

    return mysql.connector.connect(
        host=host, port=port, user=user, password=password, database=database
    )


# ----------------------
# Helper: Get user_id from Firebase UID
# ----------------------
def get_user_id_from_firebase_uid(firebase_uid: str) -> Optional[int]:
    """Get user_id from Users table using Firebase UID"""
    cnx = get_connection()
    cur = cnx.cursor(dictionary=True)
    cur.execute("SELECT user_id FROM Users WHERE firebase_uid = %s", (firebase_uid,))
    row = cast(Optional[Dict[str, Any]], cur.fetchone())
    cur.close()
    cnx.close()
    return cast(int, row["user_id"]) if row and "user_id" in row else None


# ----------------------
# CRUD Endpoints
# ----------------------
@router.get("/", response_model=list[EventResponse])
def get_events(firebase_uid: str = Depends(get_firebase_uid)):
    """
    Get all events (requires Firebase authentication).
    """
    cnx = get_connection()
    cur = cnx.cursor(dictionary=True)
    cur.execute(
        """
        SELECT event_id, title, description, location, start_time, end_time, 
               capacity, created_by, created_at
        FROM Events
        ORDER BY created_at DESC
    """
    )
    events = cast(list[Dict[str, Any]], cur.fetchall())
    cur.close()
    cnx.close()

    # Convert datetime objects to strings for JSON serialization
    for event in events:
        if event.get("start_time") and isinstance(event["start_time"], datetime):
            event["start_time"] = event["start_time"].isoformat()
        if event.get("end_time") and isinstance(event["end_time"], datetime):
            event["end_time"] = event["end_time"].isoformat()
        if event.get("created_at") and isinstance(event["created_at"], datetime):
            event["created_at"] = event["created_at"].isoformat()

    return events


@router.get("/{event_id}", response_model=EventResponse)
def get_event(event_id: int, firebase_uid: str = Depends(get_firebase_uid)):
    """
    Get a specific event by ID (requires Firebase authentication).
    """
    cnx = get_connection()
    cur = cnx.cursor(dictionary=True)
    cur.execute(
        """
        SELECT event_id, title, description, location, start_time, end_time, 
               capacity, created_by, created_at
        FROM Events
        WHERE event_id = %s
    """,
        (event_id,),
    )
    event = cast(Optional[Dict[str, Any]], cur.fetchone())
    cur.close()
    cnx.close()

    if not event:
        raise HTTPException(status_code=404, detail="Event not found")

    # Convert datetime objects to strings for JSON serialization
    if event.get("start_time") and isinstance(event["start_time"], datetime):
        event["start_time"] = event["start_time"].isoformat()
    if event.get("end_time") and isinstance(event["end_time"], datetime):
        event["end_time"] = event["end_time"].isoformat()
    if event.get("created_at") and isinstance(event["created_at"], datetime):
        event["created_at"] = event["created_at"].isoformat()

    return event


@router.post("/", response_model=EventResponse, status_code=status.HTTP_201_CREATED)
def create_event(event: EventCreate, firebase_uid: str = Depends(get_firebase_uid)):
    """
    Create a new event (requires Firebase authentication).
    The created_by field is automatically set from the authenticated user.
    """
    # Get user_id from Firebase UID
    user_id = get_user_id_from_firebase_uid(firebase_uid)
    if not user_id:
        raise HTTPException(
            status_code=404,
            detail="User not found in database. Please sync your account first.",
        )

    # Validate that end_time is after start_time
    if event.end_time <= event.start_time:
        raise HTTPException(status_code=400, detail="end_time must be after start_time")

    cnx = get_connection()
    cur = cnx.cursor(dictionary=True)

    sql = """
        INSERT INTO Events (title, description, location, start_time, end_time, capacity, created_by)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
    """
    values = (
        event.title,
        event.description,
        event.location,
        event.start_time,
        event.end_time,
        event.capacity,
        user_id,
    )

    cur.execute(sql, values)
    cnx.commit()
    event_id = cur.lastrowid

    # Fetch the created event
    cur.execute(
        """
        SELECT event_id, title, description, location, start_time, end_time, 
               capacity, created_by, created_at
        FROM Events
        WHERE event_id = %s
    """,
        (event_id,),
    )
    created_event = cast(Optional[Dict[str, Any]], cur.fetchone())
    cur.close()
    cnx.close()

    if not created_event:
        raise HTTPException(status_code=500, detail="Failed to retrieve created event")

    # Convert datetime objects to strings for JSON serialization
    if created_event.get("start_time") and isinstance(
        created_event["start_time"], datetime
    ):
        created_event["start_time"] = created_event["start_time"].isoformat()
    if created_event.get("end_time") and isinstance(
        created_event["end_time"], datetime
    ):
        created_event["end_time"] = created_event["end_time"].isoformat()
    if created_event.get("created_at") and isinstance(
        created_event["created_at"], datetime
    ):
        created_event["created_at"] = created_event["created_at"].isoformat()

    return created_event


@router.put("/{event_id}", response_model=EventResponse)
def update_event(
    event_id: int, update: EventUpdate, firebase_uid: str = Depends(get_firebase_uid)
):
    """
    Update an event (requires Firebase authentication).
    Users can only update events they created.
    """
    # Get user_id from Firebase UID
    user_id = get_user_id_from_firebase_uid(firebase_uid)
    if not user_id:
        raise HTTPException(
            status_code=404,
            detail="User not found in database. Please sync your account first.",
        )

    cnx = get_connection()
    cur = cnx.cursor(dictionary=True)

    # Check if event exists and user is the creator
    cur.execute(
        """
        SELECT created_by FROM Events WHERE event_id = %s
    """,
        (event_id,),
    )
    event = cast(Optional[Dict[str, Any]], cur.fetchone())

    if not event:
        cur.close()
        cnx.close()
        raise HTTPException(status_code=404, detail="Event not found")

    if event.get("created_by") != user_id:
        cur.close()
        cnx.close()
        raise HTTPException(
            status_code=403, detail="You can only update events you created"
        )

    # Build dynamic SQL for update
    fields = []
    values = []

    update_dict = update.dict(exclude_unset=True)

    # Validate end_time > start_time if both are being updated
    if "start_time" in update_dict and "end_time" in update_dict:
        if update_dict["end_time"] <= update_dict["start_time"]:
            cur.close()
            cnx.close()
            raise HTTPException(
                status_code=400, detail="end_time must be after start_time"
            )

    # If only start_time is updated, check against existing end_time
    if "start_time" in update_dict and "end_time" not in update_dict:
        cur.execute("SELECT end_time FROM Events WHERE event_id = %s", (event_id,))
        existing = cast(Optional[Dict[str, Any]], cur.fetchone())
        if existing and existing.get("end_time"):
            # Convert both to datetime objects for comparison
            existing_end = existing["end_time"]
            if isinstance(existing_end, str):
                existing_end = datetime.fromisoformat(
                    existing_end.replace("Z", "+00:00")
                )
            elif not isinstance(existing_end, datetime):
                # Convert to string first, then parse
                existing_end = datetime.fromisoformat(
                    str(existing_end).replace("Z", "+00:00")
                )

            new_start = update_dict["start_time"]
            if isinstance(new_start, str):
                new_start = datetime.fromisoformat(new_start.replace("Z", "+00:00"))
            elif not isinstance(new_start, datetime):
                new_start = datetime.fromisoformat(
                    str(new_start).replace("Z", "+00:00")
                )

            if existing_end <= new_start:
                cur.close()
                cnx.close()
                raise HTTPException(
                    status_code=400,
                    detail="start_time must be before existing end_time",
                )

    # If only end_time is updated, check against existing start_time
    if "end_time" in update_dict and "start_time" not in update_dict:
        cur.execute("SELECT start_time FROM Events WHERE event_id = %s", (event_id,))
        existing = cast(Optional[Dict[str, Any]], cur.fetchone())
        if existing and existing.get("start_time"):
            # Convert both to datetime objects for comparison
            existing_start = existing["start_time"]
            if isinstance(existing_start, str):
                existing_start = datetime.fromisoformat(
                    existing_start.replace("Z", "+00:00")
                )
            elif not isinstance(existing_start, datetime):
                # Convert to string first, then parse
                existing_start = datetime.fromisoformat(
                    str(existing_start).replace("Z", "+00:00")
                )

            new_end = update_dict["end_time"]
            if isinstance(new_end, str):
                new_end = datetime.fromisoformat(new_end.replace("Z", "+00:00"))
            elif not isinstance(new_end, datetime):
                new_end = datetime.fromisoformat(str(new_end).replace("Z", "+00:00"))

            if new_end <= existing_start:
                cur.close()
                cnx.close()
                raise HTTPException(
                    status_code=400, detail="end_time must be after existing start_time"
                )

    for key, value in update_dict.items():
        fields.append(f"{key} = %s")
        values.append(value)

    if not fields:
        cur.close()
        cnx.close()
        raise HTTPException(status_code=400, detail="No fields to update")

    sql = f"UPDATE Events SET {', '.join(fields)} WHERE event_id = %s"
    values.append(event_id)

    cur.execute(sql, tuple(values))
    cnx.commit()

    # Fetch the updated event
    cur.execute(
        """
        SELECT event_id, title, description, location, start_time, end_time, 
               capacity, created_by, created_at
        FROM Events
        WHERE event_id = %s
    """,
        (event_id,),
    )
    updated_event = cast(Optional[Dict[str, Any]], cur.fetchone())
    cur.close()
    cnx.close()

    if not updated_event:
        raise HTTPException(status_code=500, detail="Failed to retrieve updated event")

    # Convert datetime objects to strings for JSON serialization
    if updated_event.get("start_time") and isinstance(
        updated_event["start_time"], datetime
    ):
        updated_event["start_time"] = updated_event["start_time"].isoformat()
    if updated_event.get("end_time") and isinstance(
        updated_event["end_time"], datetime
    ):
        updated_event["end_time"] = updated_event["end_time"].isoformat()
    if updated_event.get("created_at") and isinstance(
        updated_event["created_at"], datetime
    ):
        updated_event["created_at"] = updated_event["created_at"].isoformat()

    return updated_event


@router.delete("/{event_id}")
def delete_event(event_id: int, firebase_uid: str = Depends(get_firebase_uid)):
    """
    Delete an event (requires Firebase authentication).
    Users can only delete events they created.
    """
    # Get user_id from Firebase UID
    user_id = get_user_id_from_firebase_uid(firebase_uid)
    if not user_id:
        raise HTTPException(
            status_code=404,
            detail="User not found in database. Please sync your account first.",
        )

    cnx = get_connection()
    cur = cnx.cursor(dictionary=True)

    # Check if event exists and user is the creator
    cur.execute(
        """
        SELECT created_by FROM Events WHERE event_id = %s
    """,
        (event_id,),
    )
    event = cast(Optional[Dict[str, Any]], cur.fetchone())

    if not event:
        cur.close()
        cnx.close()
        raise HTTPException(status_code=404, detail="Event not found")

    if event.get("created_by") != user_id:
        cur.close()
        cnx.close()
        raise HTTPException(
            status_code=403, detail="You can only delete events you created"
        )

    cur.execute("DELETE FROM Events WHERE event_id = %s", (event_id,))
    cnx.commit()
    cur.close()
    cnx.close()

    return {"status": "deleted", "event_id": event_id}
