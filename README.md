# Event Service

Microservice responsible for event management, including creation, updates, interests, and event-related operations.

## 📋 Overview

The Event Service handles all event-related functionality including:
- Event creation and management
- Event search and filtering
- Interest-based event discovery
- Event interest management
- Async event processing with task tracking

## 🏗️ Architecture

```
API Gateway → Composite Service → Event Service → Event Database (VM MySQL)
```

- **Port**: 8002
- **Database**: MySQL (on VM or local)
- **Authentication**: Trusts `x-firebase-uid` header from API Gateway
- **Pub/Sub**: Publishes `event-created` messages

## 🚀 Setup

### Prerequisites

- Python 3.9+
- MySQL 8.0+
- Firebase service account key
- Google Cloud Pub/Sub (for production)

### Installation

1. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

2. **Set up database**
   ```bash
   mysql -u root -p event_db < ../DB-Service/initEvent.sql
   ```

3. **Configure environment variables**
   Create a `.env` file:
   ```env
   DB_HOST=127.0.0.1
   DB_USER=root
   DB_PASS=your_password
   DB_NAME=event_db
   GCP_PROJECT_ID=your-project-id
   PUBSUB_EVENT_CREATED_TOPIC=event-created
   FIREBASE_SERVICE_ACCOUNT_PATH=./serviceAccountKey.json
   ```

4. **Add Firebase service account key**
   - Download from Firebase Console
   - Place as `serviceAccountKey.json` in service directory

5. **Run the service**
   ```bash
   uvicorn main:app --host 0.0.0.0 --port 8002
   ```

## 🔧 Environment Variables

| Variable | Description | Default | Required |
|----------|-------------|---------|---------|
| `DB_HOST` | Database host address | `127.0.0.1` | Yes |
| `DB_USER` | Database username | `root` | Yes |
| `DB_PASS` | Database password | - | Yes |
| `DB_NAME` | Database name | `event_db` | Yes |
| `GCP_PROJECT_ID` | GCP project ID for Pub/Sub | - | Yes (for Pub/Sub) |
| `PUBSUB_EVENT_CREATED_TOPIC` | Pub/Sub topic name | `event-created` | No |
| `FIREBASE_SERVICE_ACCOUNT_PATH` | Path to Firebase service account JSON | `./serviceAccountKey.json` | No |

## 📡 API Endpoints

### Event Management

#### `GET /events`
Get all events with pagination and filtering

**Query Parameters:**
- `skip`: Number of events to skip (default: 0)
- `limit`: Number of events to return (default: 10, max: 100)
- `interest_id`: Filter by interest ID
- `created_by`: Filter by creator user ID
- `search`: Search in title and description
- `start_time_from`: Filter events starting after this time (ISO 8601)
- `start_time_to`: Filter events starting before this time (ISO 8601)

**Headers:**
- `x-firebase-uid`: Firebase user ID (injected by API Gateway)

**Response:**
```json
{
  "items": [
    {
      "event_id": 1,
      "title": "Tech Meetup",
      "description": "Monthly tech meetup",
      "location": "San Francisco",
      "start_time": "2024-01-15T18:00:00",
      "end_time": "2024-01-15T20:00:00",
      "created_by": 1,
      "interests": [
        {"interest_id": 1, "interest_name": "Technology"}
      ],
      "_links": {
        "self": {"href": "/events/1"},
        "collection": {"href": "/events"}
      }
    }
  ],
  "total": 50,
  "skip": 0,
  "limit": 10
}
```

**ETag Support**: Returns `ETag` header for caching

#### `GET /events/{event_id}`
Get event by ID

**Response:**
```json
{
  "event_id": 1,
  "title": "Tech Meetup",
  "description": "Monthly tech meetup",
  "location": "San Francisco",
  "start_time": "2024-01-15T18:00:00",
  "end_time": "2024-01-15T20:00:00",
  "created_by": 1,
  "interests": [...],
  "_links": {...}
}
```

#### `POST /events`
Create a new event

**Request Body:**
```json
{
  "title": "Tech Meetup",
  "description": "Monthly tech meetup",
  "location": "San Francisco",
  "start_time": "2024-01-15T18:00:00",
  "end_time": "2024-01-15T20:00:00",
  "interest_ids": [1, 2, 3]
}
```

**Response:**
- `201 Created` with event data
- `202 Accepted` if async processing (with task_id)

**Pub/Sub**: Publishes `event-created` message to Pub/Sub topic

#### `PUT /events/{event_id}`
Update an event (full update)

**Request Body:**
```json
{
  "title": "Updated Tech Meetup",
  "description": "Updated description",
  "location": "New Location",
  "start_time": "2024-01-15T19:00:00",
  "end_time": "2024-01-15T21:00:00"
}
```

**ETag Support**: Requires `If-Match` header for optimistic locking

#### `PATCH /events/{event_id}`
Partially update an event

**Request Body:**
```json
{
  "title": "Updated Title",
  "location": "New Location"
}
```

**ETag Support**: Requires `If-Match` header

#### `DELETE /events/{event_id}`
Delete an event

**ETag Support**: Requires `If-Match` header

### Event Interests

#### `GET /events/{event_id}/interests`
Get interests for an event

#### `POST /events/{event_id}/interests`
Add interests to an event

**Request Body:**
```json
{
  "interest_ids": [1, 2, 3]
}
```

#### `DELETE /events/{event_id}/interests/{interest_id}`
Remove interest from an event

### Task Management (Async Processing)

#### `GET /events/tasks/{task_id}`
Get task status for async event creation

**Response:**
```json
{
  "task_id": "uuid-here",
  "status": "completed",
  "result": {
    "event_id": 1,
    "title": "Tech Meetup"
  },
  "created_at": "2024-01-01T00:00:00",
  "completed_at": "2024-01-01T00:00:05"
}
```

## 🔐 Authentication

This service **does not** perform Firebase authentication directly. It trusts the `x-firebase-uid` header injected by the API Gateway middleware.

## 🗄️ Database Schema

### Events Table
- `event_id` (INT, PRIMARY KEY, AUTO_INCREMENT)
- `title` (VARCHAR)
- `description` (TEXT)
- `location` (VARCHAR)
- `start_time` (DATETIME)
- `end_time` (DATETIME)
- `created_by` (INT, FOREIGN KEY to Users)
- `created_at` (TIMESTAMP)
- `updated_at` (TIMESTAMP)

### EventInterests Table (Many-to-Many)
- `event_id` (INT, FOREIGN KEY)
- `interest_id` (INT, FOREIGN KEY)

### Tasks Table (Async Processing)
- `task_id` (VARCHAR, PRIMARY KEY)
- `status` (ENUM: pending, processing, completed, failed)
- `result` (JSON)
- `created_at` (TIMESTAMP)
- `completed_at` (TIMESTAMP)

## 📨 Pub/Sub Integration

When an event is created, the service publishes a message to the `event-created` Pub/Sub topic:

```json
{
  "event_id": 1,
  "title": "Tech Meetup",
  "created_by": 1,
  "created_at": "2024-01-01T00:00:00"
}
```

The Composite Service subscribes to this topic and sends email notifications.

## 🐳 Docker Deployment

### Build Image
```bash
docker build -t event-service .
```

### Run Container
```bash
docker run -p 8002:8002 \
  -e DB_HOST=your_db_host \
  -e DB_USER=your_db_user \
  -e DB_PASS=your_db_password \
  -e DB_NAME=event_db \
  -e GCP_PROJECT_ID=your-project-id \
  event-service
```

## ☁️ GCP Cloud Run Deployment

The service is deployed to Cloud Run with:
- VPC Connector for database access (connects to VM MySQL)
- Private IP connection to Event Database VM
- Pub/Sub publisher permissions
- Environment variables configured via deployment script

See [../GCP_DEPLOYMENT_GUIDE.md](../GCP_DEPLOYMENT_GUIDE.md) for details.

## 🧪 Testing

### Health Check
```bash
curl http://localhost:8002/
```

### Get Events
```bash
curl -H "x-firebase-uid: your-firebase-uid" \
     http://localhost:8002/events
```

### Create Event
```bash
curl -X POST \
     -H "x-firebase-uid: your-firebase-uid" \
     -H "Content-Type: application/json" \
     -d '{
       "title": "Test Event",
       "description": "Test Description",
       "location": "Test Location",
       "start_time": "2024-12-31T18:00:00",
       "end_time": "2024-12-31T20:00:00",
       "interest_ids": [1]
     }' \
     http://localhost:8002/events
```

## 📚 API Documentation

Interactive API documentation available at:
- Swagger UI: `http://localhost:8002/docs`
- ReDoc: `http://localhost:8002/redoc`
- OpenAPI JSON: `http://localhost:8002/openapi.json`

## 🔍 Error Handling

The service returns standard HTTP status codes:

- `200 OK`: Successful request
- `201 Created`: Event created
- `202 Accepted`: Event creation accepted (async processing)
- `400 Bad Request`: Invalid request data
- `401 Unauthorized`: Missing or invalid `x-firebase-uid` header
- `404 Not Found`: Event not found
- `409 Conflict`: ETag mismatch (optimistic locking)
- `412 Precondition Failed`: ETag required but not provided
- `500 Internal Server Error`: Server error

## 🎯 Features

- **HATEOAS**: All responses include `_links` for navigation
- **ETag Support**: Optimistic locking for updates
- **Pagination**: Skip/limit for large result sets
- **Filtering**: By interest, creator, time range, search
- **Async Processing**: Background task processing for event creation
- **Pub/Sub Integration**: Event-driven notifications

## 📝 Notes

- The service uses MySQL connector with dictionary cursor for JSON-like responses
- ETag is generated from event data for optimistic locking
- Async event creation stores tasks in database for status tracking
- All datetime fields use ISO 8601 format

## 🤝 Contributing

When adding new endpoints:
1. Add route to `routers/events.py`
2. Use `get_firebase_uid_from_header()` helper for authentication
3. Add proper error handling and ETag support
4. Update this README with endpoint documentation
