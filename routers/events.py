from fastapi import APIRouter, HTTPException, Depends, status, Query, Header, Response
from typing import Optional, Dict, Any, List, cast
from datetime import datetime
import os
import sys
import mysql.connector
import hashlib
import json
import threading
import time
import uuid
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from auth import verify_firebase_token, get_firebase_uid
from model import EventCreate, EventUpdate, EventResponse

router = APIRouter(prefix="/events", tags=["Events"])

# ----------------------
# In-memory task store for async processing
# ----------------------
task_store: Dict[str, Dict[str, Any]] = {}
task_lock = threading.Lock()

# ----------------------
# DB Connection
# ----------------------
def get_connection():
    return mysql.connector.connect(
        host=os.getenv("DB_HOST", "127.0.0.1"),
        user=os.getenv("DB_USER", "root"),
        password=os.getenv("DB_PASS", "admin"),
        database=os.getenv("DB_NAME", "event_db")
    )


# ----------------------
# Helper: Get user_id from Firebase UID
# ----------------------
def get_user_id_from_firebase_uid(firebase_uid: str) -> Optional[int]:
    """Get user_id from Users table using Firebase UID"""
    # Connect to user_db to get user_id
    cnx = mysql.connector.connect(
        host=os.getenv("DB_HOST", "127.0.0.1"),
        user=os.getenv("DB_USER", "root"),
        password=os.getenv("DB_PASS", "admin"),
        database=os.getenv("USER_DB_NAME", "user_db")
    )
    cur = cnx.cursor(dictionary=True)
    cur.execute("SELECT user_id FROM Users WHERE firebase_uid = %s", (firebase_uid,))
    row = cast(Optional[Dict[str, Any]], cur.fetchone())
    cur.close()
    cnx.close()
    return cast(int, row['user_id']) if row and 'user_id' in row else None


# ----------------------
# Helper: Generate eTag
# ----------------------
def generate_etag(data: dict) -> str:
    """Generate eTag from data"""
    data_str = json.dumps(data, sort_keys=True, default=str)
    return hashlib.md5(data_str.encode()).hexdigest()


# ----------------------
# Helper: Add HATEOAS links
# ----------------------
def add_links(event_id: int, base_url: str = "") -> dict:
    """Add HATEOAS links to event"""
    return {
        "self": f"{base_url}/events/{event_id}",
        "collection": f"{base_url}/events",
        "interests": f"{base_url}/events/{event_id}/interests",
        "creator": f"{base_url}/users/{event_id}"  # Relative path example
    }


# ----------------------
# Helper: Get event interests
# ----------------------
def get_event_interests(event_id: int) -> list:
    """Get interests associated with an event"""
    cnx = get_connection()
    cur = cnx.cursor(dictionary=True)
    cur.execute("""
        SELECT i.interest_id, i.interest_name
        FROM Interests i
        INNER JOIN EventInterests ei ON i.interest_id = ei.interest_id
        WHERE ei.event_id = %s
    """, (event_id,))
    interests = cur.fetchall()
    cur.close()
    cnx.close()
    return interests


# ----------------------
# Async task processing function
# ----------------------
def process_event_async(task_id: str, event_data: dict, user_id: int):
    """Background task to process event creation"""
    try:
        # Simulate async processing (e.g., sending notifications, generating recommendations)
        time.sleep(2)  # Simulate processing time
        
        cnx = get_connection()
        cur = cnx.cursor(dictionary=True)
        
        # Create the event
        sql = """
            INSERT INTO Events (title, description, location, start_time, end_time, capacity, created_by)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """
        values = (
            event_data['title'],
            event_data.get('description'),
            event_data.get('location'),
            event_data['start_time'],
            event_data['end_time'],
            event_data.get('capacity'),
            user_id
        )
        
        cur.execute(sql, values)
        cnx.commit()
        event_id = cur.lastrowid
        
        # Fetch the created event
        cur.execute("""
            SELECT event_id, title, description, location, start_time, end_time, 
                   capacity, created_by, created_at
            FROM Events
            WHERE event_id = %s
        """, (event_id,))
        created_event = cur.fetchone()
        cur.close()
        cnx.close()
        
        # Update task status
        with task_lock:
            task_store[task_id] = {
                "status": "completed",
                "event_id": event_id,
                "event": created_event,
                "completed_at": datetime.now().isoformat()
            }
    except Exception as e:
        with task_lock:
            task_store[task_id] = {
                "status": "failed",
                "error": str(e),
                "failed_at": datetime.now().isoformat()
            }


# ----------------------
# CRUD Endpoints
# ----------------------
@router.get("/", response_model=Dict[str, Any])
def get_events(
    response: Response,
    firebase_uid: str = Depends(get_firebase_uid),
    skip: int = Query(0, ge=0, description="Number of events to skip"),
    limit: int = Query(10, ge=1, le=100, description="Number of events to return"),
    location: Optional[str] = Query(None, description="Filter by location"),
    created_by: Optional[int] = Query(None, description="Filter by creator user ID"),
    start_date: Optional[str] = Query(None, description="Filter events starting from this date (YYYY-MM-DD)"),
    end_date: Optional[str] = Query(None, description="Filter events ending before this date (YYYY-MM-DD)")
):
    """
    Get all events with pagination and query parameters.
    Supports filtering by location, created_by, and date range.
    Returns HATEOAS links and pagination metadata.
    """
    cnx = get_connection()
    cur = cnx.cursor(dictionary=True)
    
    # Build query with filters
    where_clauses = []
    params = []
    
    if location:
        where_clauses.append("location LIKE %s")
        params.append(f"%{location}%")
    
    if created_by:
        where_clauses.append("created_by = %s")
        params.append(created_by)
    
    if start_date:
        where_clauses.append("DATE(start_time) >= %s")
        params.append(start_date)
    
    if end_date:
        where_clauses.append("DATE(end_time) <= %s")
        params.append(end_date)
    
    where_sql = " AND ".join(where_clauses) if where_clauses else "1=1"
    
    # Get total count
    count_query = f"SELECT COUNT(*) as total FROM Events WHERE {where_sql}"
    cur.execute(count_query, tuple(params))
    count_result = cast(Optional[Dict[str, Any]], cur.fetchone())
    total = int(count_result['total']) if count_result and 'total' in count_result else 0
    
    # Get paginated events
    query = f"""
        SELECT event_id, title, description, location, start_time, end_time, 
               capacity, created_by, created_at
        FROM Events
        WHERE {where_sql}
        ORDER BY created_at DESC
        LIMIT %s OFFSET %s
    """
    params.extend([limit, skip])
    cur.execute(query, tuple(params))
    events = cast(List[Dict[str, Any]], cur.fetchall())
    
    cur.close()
    cnx.close()
    
    # Add interests and links to each event
    for event in events:
        event_id = int(event['event_id']) if event.get('event_id') else None
        if event_id:
            event['interests'] = get_event_interests(event_id)
            event['links'] = add_links(event_id)
        # Convert datetime to string
        start_time = event.get('start_time')
        if start_time and isinstance(start_time, datetime):
            event['start_time'] = start_time.isoformat()
        end_time = event.get('end_time')
        if end_time and isinstance(end_time, datetime):
            event['end_time'] = end_time.isoformat()
        created_at = event.get('created_at')
        if created_at and isinstance(created_at, datetime):
            event['created_at'] = created_at.isoformat()
    
    # Generate eTag for the collection
    etag = generate_etag({"events": events, "total": total, "skip": skip, "limit": limit})
    response.headers["ETag"] = f'"{etag}"'
    
    # Return with pagination metadata and HATEOAS links
    total_int = int(total) if total else 0
    skip_int = int(skip) if skip else 0
    limit_int = int(limit) if limit else 10
    return {
        "items": events,
        "total": total_int,
        "skip": skip_int,
        "limit": limit_int,
        "has_more": (skip_int + limit_int) < total_int,
        "links": {
            "self": f"/events?skip={skip_int}&limit={limit_int}",
            "first": f"/events?skip=0&limit={limit_int}",
            "last": f"/events?skip={max(0, (total_int - 1) // limit_int * limit_int)}&limit={limit_int}",
            "next": f"/events?skip={skip_int + limit_int}&limit={limit_int}" if (skip_int + limit_int) < total_int else None,
            "prev": f"/events?skip={max(0, skip_int - limit_int)}&limit={limit_int}" if skip_int > 0 else None
        }
    }


@router.get("/{event_id}", response_model=EventResponse)
def get_event(
    event_id: int,
    response: Response,
    firebase_uid: str = Depends(get_firebase_uid),
    if_none_match: Optional[str] = Header(None, alias="If-None-Match")
):
    """
    Get a specific event by ID with eTag support.
    Returns 304 Not Modified if eTag matches.
    """
    cnx = get_connection()
    cur = cnx.cursor(dictionary=True)
    cur.execute("""
        SELECT event_id, title, description, location, start_time, end_time, 
               capacity, created_by, created_at
        FROM Events
        WHERE event_id = %s
    """, (event_id,))
    event = cast(Optional[Dict[str, Any]], cur.fetchone())
    cur.close()
    cnx.close()
    
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    
    # Add interests
    event['interests'] = get_event_interests(event_id)
    
    # Convert datetime to string
    if event.get('start_time') and isinstance(event['start_time'], datetime):
        event['start_time'] = event['start_time'].isoformat()
    if event.get('end_time') and isinstance(event['end_time'], datetime):
        event['end_time'] = event['end_time'].isoformat()
    if event.get('created_at') and isinstance(event['created_at'], datetime):
        event['created_at'] = event['created_at'].isoformat()
    
    # Generate eTag
    etag = generate_etag(event)
    response.headers["ETag"] = f'"{etag}"'
    
    # Check if client has matching eTag
    if if_none_match and if_none_match.strip('"') == etag:
        return Response(status_code=304)
    
    # Add HATEOAS links
    event['links'] = add_links(event_id)
    
    return event


@router.post("/", response_model=EventResponse, status_code=status.HTTP_201_CREATED)
def create_event(
    event: EventCreate,
    response: Response,
    firebase_uid: str = Depends(get_firebase_uid)
):
    """
    Create a new event (requires Firebase authentication).
    The created_by field is automatically set from the authenticated user.
    Returns 201 Created with Location header.
    """
    # Get user_id from Firebase UID
    user_id = get_user_id_from_firebase_uid(firebase_uid)
    if not user_id:
        raise HTTPException(
            status_code=404,
            detail="User not found in database. Please sync your account first."
        )
    
    # Validate that end_time is after start_time
    if event.end_time <= event.start_time:
        raise HTTPException(
            status_code=400,
            detail="end_time must be after start_time"
        )
    
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
        user_id
    )
    
    cur.execute(sql, values)
    cnx.commit()
    event_id = cur.lastrowid
    
    # Fetch the created event
    cur.execute("""
        SELECT event_id, title, description, location, start_time, end_time, 
               capacity, created_by, created_at
        FROM Events
        WHERE event_id = %s
    """, (event_id,))
    created_event = cast(Optional[Dict[str, Any]], cur.fetchone())
    cur.close()
    cnx.close()
    
    if not created_event:
        raise HTTPException(status_code=500, detail="Failed to retrieve created event")
    
    # Add interests and links
    if event_id:
        created_event['interests'] = get_event_interests(event_id)
        created_event['links'] = add_links(event_id)
    
    # Convert datetime objects to strings for JSON serialization
    start_time = created_event.get('start_time')
    if start_time and isinstance(start_time, datetime):
        created_event['start_time'] = start_time.isoformat()
    end_time = created_event.get('end_time')
    if end_time and isinstance(end_time, datetime):
        created_event['end_time'] = end_time.isoformat()
    created_at = created_event.get('created_at')
    if created_at and isinstance(created_at, datetime):
        created_event['created_at'] = created_at.isoformat()
    
    # Set Location header
    response.headers["Location"] = f"/events/{event_id}"
    
    return created_event


@router.post("/async", status_code=status.HTTP_202_ACCEPTED)
def create_event_async(
    event: EventCreate,
    response: Response,
    firebase_uid: str = Depends(get_firebase_uid)
):
    """
    Create a new event asynchronously (requires Firebase authentication).
    Returns 202 Accepted with a task ID for polling status.
    """
    # Get user_id from Firebase UID
    user_id = get_user_id_from_firebase_uid(firebase_uid)
    if not user_id:
        raise HTTPException(
            status_code=404,
            detail="User not found in database. Please sync your account first."
        )
    
    # Validate that end_time is after start_time
    if event.end_time <= event.start_time:
        raise HTTPException(
            status_code=400,
            detail="end_time must be after start_time"
        )
    
    # Generate task ID
    task_id = str(uuid.uuid4())
    
    # Store task as pending
    with task_lock:
        task_store[task_id] = {
            "status": "pending",
            "created_at": datetime.now().isoformat()
        }
    
    # Start async processing in background thread
    event_data = event.dict()
    thread = threading.Thread(
        target=process_event_async,
        args=(task_id, event_data, user_id)
    )
    thread.daemon = True
    thread.start()
    
    # Return 202 Accepted with task location
    response.headers["Location"] = f"/events/tasks/{task_id}"
    return {
        "task_id": task_id,
        "status": "pending",
        "message": "Event creation in progress",
        "links": {
            "status": f"/events/tasks/{task_id}",
            "self": f"/events/tasks/{task_id}"
        }
    }


@router.get("/tasks/{task_id}")
def get_task_status(task_id: str, firebase_uid: str = Depends(get_firebase_uid)):
    """
    Poll the status of an async event creation task.
    Returns task status and event data when completed.
    """
    with task_lock:
        task = task_store.get(task_id)
    
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    
    response_data = {
        "task_id": task_id,
        "status": task["status"],
        "created_at": task.get("created_at")
    }
    
    if task["status"] == "completed":
        event = task.get("event")
        if event and isinstance(event, dict):
            # Convert datetime to string
            start_time = event.get('start_time')
            if start_time and isinstance(start_time, datetime):
                event['start_time'] = start_time.isoformat()
            end_time = event.get('end_time')
            if end_time and isinstance(end_time, datetime):
                event['end_time'] = end_time.isoformat()
            created_at = event.get('created_at')
            if created_at and isinstance(created_at, datetime):
                event['created_at'] = created_at.isoformat()
            
            event_id = int(event.get('event_id', 0)) if event.get('event_id') else None
            if event_id:
                event['interests'] = get_event_interests(event_id)
                event['links'] = add_links(event_id)
            response_data["event"] = event
            response_data["completed_at"] = task.get("completed_at")
            event_id_val = event.get('event_id') if isinstance(event, dict) else None
            if event_id_val:
                response_data["links"] = {
                    "event": f"/events/{event_id_val}",
                    "self": f"/events/tasks/{task_id}"
                }
    elif task["status"] == "failed":
        response_data["error"] = task.get("error")
        response_data["failed_at"] = task.get("failed_at")
    
    return response_data


@router.put("/{event_id}", response_model=EventResponse)
def update_event(
    event_id: int,
    update: EventUpdate,
    response: Response,
    firebase_uid: str = Depends(get_firebase_uid),
    if_match: Optional[str] = Header(None, alias="If-Match")
):
    """
    Update an event (requires Firebase authentication).
    Supports eTag validation with If-Match header.
    Users can only update events they created.
    """
    # Get user_id from Firebase UID
    user_id = get_user_id_from_firebase_uid(firebase_uid)
    if not user_id:
        raise HTTPException(
            status_code=404,
            detail="User not found in database. Please sync your account first."
        )
    
    cnx = get_connection()
    cur = cnx.cursor(dictionary=True)
    
    # Check if event exists and user is the creator
    cur.execute("""
        SELECT event_id, title, description, location, start_time, end_time, 
               capacity, created_by, created_at
        FROM Events WHERE event_id = %s
    """, (event_id,))
    existing_event = cast(Optional[Dict[str, Any]], cur.fetchone())
    
    if not existing_event:
        cur.close()
        cnx.close()
        raise HTTPException(status_code=404, detail="Event not found")
    
    if existing_event.get('created_by') != user_id:
        cur.close()
        cnx.close()
        raise HTTPException(
            status_code=403,
            detail="You can only update events you created"
        )
    
    # Check eTag if provided
    if if_match:
        existing_event['interests'] = get_event_interests(event_id)
        existing_etag = generate_etag(existing_event)
        if if_match.strip('"') != existing_etag:
            cur.close()
            cnx.close()
            raise HTTPException(status_code=412, detail="Precondition Failed: eTag mismatch")
    
    # Build dynamic SQL for update
    fields = []
    values = []
    
    update_dict = update.dict(exclude_unset=True)
    
    # Validate end_time > start_time if both are being updated
    if 'start_time' in update_dict and 'end_time' in update_dict:
        if update_dict['end_time'] <= update_dict['start_time']:
            cur.close()
            cnx.close()
            raise HTTPException(
                status_code=400,
                detail="end_time must be after start_time"
            )
    
    # If only start_time is updated, check against existing end_time
    if 'start_time' in update_dict and 'end_time' not in update_dict:
        cur.execute("SELECT end_time FROM Events WHERE event_id = %s", (event_id,))
        existing = cast(Optional[Dict[str, Any]], cur.fetchone())
        if existing and existing.get('end_time'):
            existing_end = existing['end_time']
            if isinstance(existing_end, str):
                existing_end = datetime.fromisoformat(existing_end.replace('Z', '+00:00'))
            elif not isinstance(existing_end, datetime):
                existing_end = datetime.fromisoformat(str(existing_end).replace('Z', '+00:00'))
            
            new_start = update_dict['start_time']
            if isinstance(new_start, str):
                new_start = datetime.fromisoformat(new_start.replace('Z', '+00:00'))
            elif not isinstance(new_start, datetime):
                new_start = datetime.fromisoformat(str(new_start).replace('Z', '+00:00'))
            
            if existing_end <= new_start:
                cur.close()
                cnx.close()
                raise HTTPException(
                    status_code=400,
                    detail="start_time must be before existing end_time"
                )
    
    # If only end_time is updated, check against existing start_time
    if 'end_time' in update_dict and 'start_time' not in update_dict:
        cur.execute("SELECT start_time FROM Events WHERE event_id = %s", (event_id,))
        existing = cast(Optional[Dict[str, Any]], cur.fetchone())
        if existing and existing.get('start_time'):
            existing_start = existing['start_time']
            if isinstance(existing_start, str):
                existing_start = datetime.fromisoformat(existing_start.replace('Z', '+00:00'))
            elif not isinstance(existing_start, datetime):
                existing_start = datetime.fromisoformat(str(existing_start).replace('Z', '+00:00'))
            
            new_end = update_dict['end_time']
            if isinstance(new_end, str):
                new_end = datetime.fromisoformat(new_end.replace('Z', '+00:00'))
            elif not isinstance(new_end, datetime):
                new_end = datetime.fromisoformat(str(new_end).replace('Z', '+00:00'))
            
            if new_end <= existing_start:
                cur.close()
                cnx.close()
                raise HTTPException(
                    status_code=400,
                    detail="end_time must be after existing start_time"
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
    cur.execute("""
        SELECT event_id, title, description, location, start_time, end_time, 
               capacity, created_by, created_at
        FROM Events
        WHERE event_id = %s
    """, (event_id,))
    updated_event = cast(Optional[Dict[str, Any]], cur.fetchone())
    cur.close()
    cnx.close()
    
    if not updated_event:
        raise HTTPException(status_code=500, detail="Failed to retrieve updated event")
    
    # Add interests and links
    updated_event['interests'] = get_event_interests(event_id)
    updated_event['links'] = add_links(event_id)
    
    # Convert datetime objects to strings for JSON serialization
    start_time = updated_event.get('start_time')
    if start_time and isinstance(start_time, datetime):
        updated_event['start_time'] = start_time.isoformat()
    end_time = updated_event.get('end_time')
    if end_time and isinstance(end_time, datetime):
        updated_event['end_time'] = end_time.isoformat()
    created_at = updated_event.get('created_at')
    if created_at and isinstance(created_at, datetime):
        updated_event['created_at'] = created_at.isoformat()
    
    # Generate new eTag
    etag = generate_etag(updated_event)
    response.headers["ETag"] = f'"{etag}"'
    
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
            detail="User not found in database. Please sync your account first."
        )
    
    cnx = get_connection()
    cur = cnx.cursor(dictionary=True)
    
    # Check if event exists and user is the creator
    cur.execute("""
        SELECT created_by FROM Events WHERE event_id = %s
    """, (event_id,))
    event = cast(Optional[Dict[str, Any]], cur.fetchone())
    
    if not event:
        cur.close()
        cnx.close()
        raise HTTPException(status_code=404, detail="Event not found")
    
    if event.get('created_by') != user_id:
        cur.close()
        cnx.close()
        raise HTTPException(
            status_code=403,
            detail="You can only delete events you created"
        )
    
    cur.execute("DELETE FROM Events WHERE event_id = %s", (event_id,))
    cnx.commit()
    cur.close()
    cnx.close()
    
    return {"status": "deleted", "event_id": event_id}
