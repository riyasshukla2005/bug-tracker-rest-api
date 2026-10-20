# Bug Tracking REST API

A backend application built with Python, Flask, and SQLite to manage software bugs through REST API endpoints.

## Features

- Create, retrieve, update, and delete bug reports.
- Create developer records and assign bugs.
- Add and retrieve comments.
- Filter bugs by status and priority.
- Enforce valid status transitions.
- Automatically record status, priority, and assignment changes.
- Validate input and return JSON error responses.
- Store records persistently in SQLite.

## Technologies

Python, Flask, SQLite, SQL, Postman

## Setup and Run

Open a terminal in the project folder.

### Windows

```bat
py -m venv venv
venv\Scripts\python.exe -m pip install -r requirements.txt
venv\Scripts\python.exe app.py
```

The application creates `bugs.db` and its tables automatically.

Base URL: `http://127.0.0.1:5000`

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | / | Check whether the API is running |
| POST | /developers | Create a developer |
| GET | /developers | List developers |
| POST | /bugs | Create a bug |
| GET | /bugs | List or filter bugs |
| GET | /bugs/{id} | Retrieve a bug |
| PATCH | /bugs/{id} | Update a bug or assign a developer |
| DELETE | /bugs/{id} | Delete a bug |
| POST | /bugs/{id}/comments | Add a comment |
| GET | /bugs/{id}/comments | Retrieve comments |
| GET | /bugs/{id}/history | Retrieve change history |

Replace `{id}` with an existing bug ID.

## Example: Create a Bug

Send POST `/bugs` with Content-Type `application/json`:

```json
{
  "title": "Login button not responding",
  "description": "Clicking Login does not open the dashboard.",
  "priority": "High"
}
```

Expected response: `201 Created` with the saved bug.

## Filtering

Example:

```text
GET /bugs?priority=High&status=Open
```

## Status Rules

The standard workflow is:

Open → In Progress → Resolved → Closed

A resolved bug can also return to In Progress.
Invalid transitions return `409 Conflict`.

## Change History

Changes to status, priority, and developer assignment record:

- Changed field.
- Previous value.
- New value.
- Timestamp.

The bug update and its history are saved in the same transaction.

## Testing

Use Postman to test successful requests and error scenarios.

| Scenario | Expected Status |
|----------|-----------------|
| Create a bug or developer | 201 |
| Retrieve or update a bug | 200 |
| Delete a bug | 204 |
| Submit invalid input | 400 |
| Request a missing record | 404 |
| Attempt an invalid status transition | 409 |
| Send an unsupported content type | 415 |

To check persistence, restart the application and retrieve previously saved records.

## Limitations

- Authentication and role-based permissions are not implemented.
- Developer assignment does not verify the identity of the caller.
- Deleting a bug also deletes its comments and history.
- The application runs locally using Flask's development server.