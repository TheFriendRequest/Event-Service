from fastapi import APIRouter, HTTPException, Depends, status, Query, Header, Response, Request
from typing import Optional, Dict, Any, List, cast
from datetime import datetime
import os
import sys
import mysql.connector  # type: ignore
import hashlib
import json
import threading
import time
import uuid
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# Authentication removed - trust x-firebase-uid header from API Gateway
from model import EventCreate, EventUpdate, EventResponse

router = APIRouter(prefix="/events", tags=["Events"])

# ----------------------
# Task lock for thread safety (tasks now stored in database)
# ----------------------
task_lock = threading.Lock()

# ----------------------
# DB Connection
# ----------------------
def get_connection():
    return mysql.connector.connect(
        host=os.getenv("DB_HOST", "127.0.0.1"),
        user=os.getenv("DB_USER", "root"),
        password=os.getenv("DB_PASS", "admin"),
        database=os.getenv("DB_NAME", "event_db"),
    )


# ----------------------
# Helper: Get firebase_uid from header (set by API Gateway)
# ----------------------
def get_firebase_uid_from_header(request: Request) -> str:
    """Get firebase_uid from x-firebase-uid header (injected by API Gateway)"""
    firebase_uid = request.headers.get("x-firebase-uid") or request.headers.get("X-Firebase-Uid")
    if not firebase_uid:
        raise HTTPException(status_code=401, detail="Authentication required - x-firebase-uid header missing")
    return firebase_uid

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
        "self": {"href": f"{base_url}/events/{event_id}"},
        "collection": {"href": f"{base_url}/events"},
        "interests": {"href": f"{base_url}/events/{event_id}/interests"},
        "creator": {"href": f"{base_url}/users/{event_id}"}  # Relative path example
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
    """Background task to process event creation - stores tasks in database"""
    try:
        cnx = get_connection()
        cur = cnx.cursor()
        
        # Update task status to processing
        cur.execute("""
            UPDATE Tasks 
            SET status = 'processing', started_at = NOW() 
            WHERE task_id = %s
        """, (task_id,))
        cnx.commit()
        
        # Simulate async processing (e.g., sending notifications, generating recommendations)
        time.sleep(2)  # Simulate processing time
        
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
        
        # Fetch the created event (need dictionary cursor for this query)
        cur_dict = cnx.cursor(dictionary=True)
        cur_dict.execute("""
            SELECT event_id, title, description, location, start_time, end_time, 
                   capacity, created_by, created_at
            FROM Events
            WHERE event_id = %s
        """, (event_id,))
        created_event = cast(Optional[Dict[str, Any]], cur_dict.fetchone())
        cur_dict.close()
        
        # Convert to dict for JSON serialization
        if created_event:
            start_time = created_event.get('start_time')
            end_time = created_event.get('end_time')
            created_at = created_event.get('created_at')
            
            event_dict = {
                'event_id': created_event.get('event_id'),
                'title': created_event.get('title'),
                'description': created_event.get('description'),
                'location': created_event.get('location'),
                'start_time': start_time.isoformat() if isinstance(start_time, datetime) else (str(start_time) if start_time else ''),
                'end_time': end_time.isoformat() if isinstance(end_time, datetime) else (str(end_time) if end_time else ''),
                'capacity': created_event.get('capacity'),
                'created_by': created_event.get('created_by'),
                'created_at': created_at.isoformat() if isinstance(created_at, datetime) else (str(created_at) if created_at else '')
            }
            
            # Update task as completed with result data
            cur.execute("""
                UPDATE Tasks 
                SET status = 'completed', 
                    completed_at = NOW(),
                    result_data = %s
                WHERE task_id = %s
            """, (json.dumps(event_dict), task_id))
            cnx.commit()
        
        cur.close()
        cnx.close()
    except Exception as e:
        # Update task as failed
        error_msg = str(e)
        try:
            cnx = get_connection()
            cur = cnx.cursor()
            cur.execute("""
                UPDATE Tasks 
                SET status = 'failed', 
                    completed_at = NOW(),
                    error_message = %s
                WHERE task_id = %s
            """, (error_msg, task_id))
            cnx.commit()
            cur.close()
            cnx.close()
        except Exception as db_error:
            print(f"[Event Service] Error updating failed task in DB: {db_error}")


# ----------------------
# CRUD Endpoints
# ----------------------
@router.get("/", response_model=Dict[str, Any])
def get_events(
    response: Response,
    request: Request,
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
    Trusts x-firebase-uid header from API Gateway.
    """
    firebase_uid = get_firebase_uid_from_header(request)
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
    print(f"[Event Service] Generated ETag for events collection: {etag}")
    print(f"[Event Service] ETag header set: {response.headers.get('ETag')}")
    
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
            "self": {"href": f"/events?skip={skip_int}&limit={limit_int}"},
            "first": {"href": f"/events?skip=0&limit={limit_int}"},
            "last": {"href": f"/events?skip={max(0, (total_int - 1) // limit_int * limit_int)}&limit={limit_int}"},
            "next": {"href": f"/events?skip={skip_int + limit_int}&limit={limit_int}"} if (skip_int + limit_int) < total_int else None,
            "prev": {"href": f"/events?skip={max(0, skip_int - limit_int)}&limit={limit_int}"} if skip_int > 0 else None
        }
    }


@router.get("/{event_id}", response_model=EventResponse)
def get_event(
    event_id: int,
    response: Response,
    request: Request,
    if_none_match: Optional[str] = Header(None, alias="If-None-Match")
):
    """Get a specific event by ID with eTag support. Trusts x-firebase-uid header from API Gateway."""
    firebase_uid = get_firebase_uid_from_header(request)
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
    request: Request
):
    """Create event. Trusts x-firebase-uid header from API Gateway."""
    firebase_uid = get_firebase_uid_from_header(request)
    """
    Create a new event.
    The created_by field must be provided in the request body (user_id from Composite Service).
    Firebase token is verified but firebase_uid is not used to look up user_id.
    Returns 201 Created with Location header.
    """
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
        event.created_by
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
    request: Request
):
    """
    Create a new event asynchronously.
    The created_by field must be provided in the request body (user_id from Composite Service).
    Trusts x-firebase-uid header from API Gateway.
    Returns 202 Accepted with a task ID for polling status.
    """
    firebase_uid = get_firebase_uid_from_header(request)
    # Validate that end_time is after start_time
    if event.end_time <= event.start_time:
        raise HTTPException(
            status_code=400,
            detail="end_time must be after start_time"
        )
    
    # Generate task ID
    task_id = str(uuid.uuid4())
    
    # Prepare event data for JSON serialization (convert datetime to string)
    event_dict = event.dict()
    # Convert datetime objects to ISO format strings for JSON serialization
    if 'start_time' in event_dict and isinstance(event_dict['start_time'], datetime):
        event_dict['start_time'] = event_dict['start_time'].isoformat()
    if 'end_time' in event_dict and isinstance(event_dict['end_time'], datetime):
        event_dict['end_time'] = event_dict['end_time'].isoformat()
    
    # Store task in database
    cnx = get_connection()
    cur = cnx.cursor()
    try:
        cur.execute("""
            INSERT INTO Tasks (task_id, task_type, status, request_data, created_by)
            VALUES (%s, %s, %s, %s, %s)
        """, (
            task_id,
            'create_event',
            'pending',
            json.dumps(event_dict, default=str),  # default=str handles any remaining non-serializable types
            event.created_by
        ))
        cnx.commit()
    except Exception as e:
        cnx.rollback()
        cur.close()
        cnx.close()
        raise HTTPException(status_code=500, detail=f"Failed to create task: {str(e)}")
    finally:
        cur.close()
        cnx.close()
    
    # Start async processing in background thread
    event_data = event.dict()
    thread = threading.Thread(
        target=process_event_async,
        args=(task_id, event_data, event.created_by)
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
            "status": {"href": f"/events/tasks/{task_id}"},
            "self": {"href": f"/events/tasks/{task_id}"}
        }
    }


@router.get("/tasks/{task_id}")
def get_task_status(
    task_id: str,
    request: Request
):
    """Get task status. Trusts x-firebase-uid header from API Gateway."""
    firebase_uid = get_firebase_uid_from_header(request)
    """
    Poll the status of an async event creation task.
    Returns task status from database and event data when completed.
    """
    cnx = get_connection()
    cur = cnx.cursor(dictionary=True)
    try:
        cur.execute("""
            SELECT task_id, task_type, status, request_data, result_data, 
                   error_message, created_at, started_at, completed_at, created_by
            FROM Tasks
            WHERE task_id = %s
        """, (task_id,))
        task = cast(Optional[Dict[str, Any]], cur.fetchone())
        
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        
        # Build response
        response_data: Dict[str, Any] = {
            "task_id": str(task.get("task_id", "")),
            "task_type": str(task.get("task_type", "")),
            "status": str(task.get("status", "")),
            "links": {
                "self": {"href": f"/events/tasks/{task_id}"}
            }
        }
        
        # Handle created_at
        created_at = task.get("created_at")
        if created_at:
            if isinstance(created_at, datetime):
                response_data["created_at"] = created_at.isoformat()
            else:
                response_data["created_at"] = str(created_at)
        
        # Handle started_at
        started_at = task.get("started_at")
        if started_at:
            if isinstance(started_at, datetime):
                response_data["started_at"] = started_at.isoformat()
            else:
                response_data["started_at"] = str(started_at)
        
        # Handle completed status
        if task.get("status") == "completed":
            result_data = task.get("result_data")
            if result_data and isinstance(result_data, str):
                try:
                    event = json.loads(result_data)
                    event_id = event.get('event_id') if isinstance(event, dict) else None
                    if event_id:
                        event['interests'] = get_event_interests(event_id)
                        event['links'] = add_links(event_id)
                    response_data["event"] = event
                    if isinstance(event, dict) and "event_id" in event:
                        response_data["links"]["event"] = {"href": f"/events/{event['event_id']}"}
                except json.JSONDecodeError:
                    pass
            completed_at = task.get("completed_at")
            if completed_at:
                if isinstance(completed_at, datetime):
                    response_data["completed_at"] = completed_at.isoformat()
                else:
                    response_data["completed_at"] = str(completed_at)
        elif task.get("status") == "failed":
            error_msg = task.get("error_message")
            if error_msg:
                response_data["error"] = str(error_msg)
            completed_at = task.get("completed_at")
            if completed_at:
                if isinstance(completed_at, datetime):
                    response_data["failed_at"] = completed_at.isoformat()
                else:
                    response_data["failed_at"] = str(completed_at)
        
        return response_data
    finally:
        cur.close()
        cnx.close()


@router.put("/{event_id}", response_model=EventResponse)
def update_event(
    event_id: int,
    update: EventUpdate,
    response: Response,
    request: Request,
    created_by: int = Query(..., description="User ID of the creator (for authorization check)"),
    if_match: Optional[str] = Header(None, alias="If-Match")
):
    """Update an event. Trusts x-firebase-uid header from API Gateway."""
    firebase_uid = get_firebase_uid_from_header(request)
    """
    Update an event.
    Supports eTag validation with If-Match header.
    The created_by query parameter is used to verify the user is the creator.
    Firebase token is verified but firebase_uid is not used to look up user_id.
    """
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
    
    if existing_event.get('created_by') != created_by:
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
def delete_event(
    event_id: int,
    request: Request,
    created_by: int = Query(..., description="User ID of the creator (for authorization check)")
):
    """
    Delete an event. Trusts x-firebase-uid header from API Gateway.
    The created_by query parameter is used to verify the user is the creator.
    """
    firebase_uid = get_firebase_uid_from_header(request)
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
    
    if event.get('created_by') != created_by:
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
