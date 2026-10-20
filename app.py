from pathlib import Path
import sqlite3

from flask import Flask, g, jsonify, request
from werkzeug.exceptions import HTTPException

app = Flask(__name__)

DATABASE = Path(__file__).resolve().parent / "bugs.db"

PRIORITIES = {"Low", "Medium", "High", "Critical"}

TRANSITIONS = {
    "Open": {"In Progress"},
    "In Progress": {"Resolved"},
    "Resolved": {"Closed", "In Progress"},
    "Closed": set(),
}


# ---------- Database ----------

def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DATABASE)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(error=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def initialize_database():
    db = get_db()

    db.executescript("""
        CREATE TABLE IF NOT EXISTS developers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE
        );

        CREATE TABLE IF NOT EXISTS bugs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            priority TEXT NOT NULL DEFAULT 'Medium'
                CHECK(priority IN ('Low', 'Medium', 'High', 'Critical')),
            status TEXT NOT NULL DEFAULT 'Open'
                CHECK(status IN (
                    'Open', 'In Progress', 'Resolved', 'Closed'
                )),
            developer_id INTEGER,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (developer_id) REFERENCES developers(id)
        );

        CREATE TABLE IF NOT EXISTS comments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            bug_id INTEGER NOT NULL,
            content TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (bug_id) REFERENCES bugs(id)
                ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS bug_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            bug_id INTEGER NOT NULL,
            field TEXT NOT NULL,
            old_value TEXT,
            new_value TEXT,
            changed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (bug_id) REFERENCES bugs(id)
                ON DELETE CASCADE
        );
    """)

    db.commit()


# ---------- Validation and errors ----------

class APIError(Exception):
    def __init__(self, message, status=400):
        self.message = message
        self.status = status


@app.errorhandler(APIError)
def handle_api_error(error):
    return jsonify({"error": error.message}), error.status


@app.errorhandler(HTTPException)
def handle_http_error(error):
    return jsonify({"error": error.description}), error.code


@app.errorhandler(sqlite3.Error)
def handle_database_error(error):
    app.logger.exception("Database operation failed")
    return jsonify({"error": "Database operation failed."}), 500


def read_json(allowed_fields):
    data = request.get_json()

    if not isinstance(data, dict):
        raise APIError("Request body must be a JSON object.")

    unknown = set(data) - set(allowed_fields)
    if unknown:
        raise APIError(
            "Unknown fields: " + ", ".join(sorted(unknown))
        )

    return data


def required_text(value, field, max_length):
    if not isinstance(value, str) or not value.strip():
        raise APIError(f"{field} must be a non-empty string.")

    value = value.strip()

    if len(value) > max_length:
        raise APIError(
            f"{field} must contain at most {max_length} characters."
        )

    return value


def validate_priority(value):
    if not isinstance(value, str) or value not in PRIORITIES:
        raise APIError(
            "Priority must be Low, Medium, High, or Critical."
        )


def validate_developer(developer_id):
    if developer_id is None:
        return

    if type(developer_id) is not int or developer_id <= 0:
        raise APIError("developer_id must be a positive integer or null.")

    developer = get_db().execute(
        "SELECT id FROM developers WHERE id = ?",
        (developer_id,),
    ).fetchone()

    if developer is None:
        raise APIError("Developer not found.", 404)


def find_bug(bug_id):
    bug = get_db().execute(
        "SELECT * FROM bugs WHERE id = ?",
        (bug_id,),
    ).fetchone()

    if bug is None:
        raise APIError("Bug not found.", 404)

    return dict(bug)


# ---------- Home ----------

@app.get("/")
def home():
    return jsonify({
        "message": "Bug Tracking REST API is running",
        "endpoints": ["/bugs", "/developers"],
    })


# ---------- Developers ----------

@app.post("/developers")
def create_developer():
    data = read_json({"name", "email"})

    name = required_text(data.get("name"), "name", 100)
    email = required_text(data.get("email"), "email", 254).lower()

    # Basic format check for this learning project.
    if email.count("@") != 1 or any(c.isspace() for c in email):
        raise APIError("Enter a valid email address.")

    local, domain = email.split("@")
    if not local or "." not in domain or domain.startswith("."):
        raise APIError("Enter a valid email address.")

    db = get_db()

    try:
        with db:
            cursor = db.execute(
                "INSERT INTO developers (name, email) VALUES (?, ?)",
                (name, email),
            )
    except sqlite3.IntegrityError:
        raise APIError("A developer with this email already exists.", 409)

    developer = db.execute(
        "SELECT * FROM developers WHERE id = ?",
        (cursor.lastrowid,),
    ).fetchone()

    return jsonify(dict(developer)), 201


@app.get("/developers")
def list_developers():
    rows = get_db().execute(
        "SELECT * FROM developers ORDER BY id"
    ).fetchall()

    return jsonify([dict(row) for row in rows])


# ---------- Bugs ----------

@app.post("/bugs")
def create_bug():
    data = read_json({
        "title", "description", "priority", "developer_id"
    })

    title = required_text(data.get("title"), "title", 200)
    description = data.get("description", "")

    if not isinstance(description, str) or len(description) > 10000:
        raise APIError("description must be a string of at most 10000 characters.")

    priority = data.get("priority", "Medium")
    validate_priority(priority)

    developer_id = data.get("developer_id")
    validate_developer(developer_id)

    db = get_db()

    with db:
        cursor = db.execute("""
            INSERT INTO bugs (
                title, description, priority, developer_id
            ) VALUES (?, ?, ?, ?)
        """, (title, description, priority, developer_id))

    return jsonify(find_bug(cursor.lastrowid)), 201


@app.get("/bugs")
def list_bugs():
    unknown = set(request.args) - {"status", "priority"}
    if unknown:
        raise APIError("Supported filters are status and priority.")

    query = "SELECT * FROM bugs WHERE 1 = 1"
    values = []

    status = request.args.get("status")
    priority = request.args.get("priority")

    if status is not None:
        if status not in TRANSITIONS:
            raise APIError("Invalid status filter.")

        query += " AND status = ?"
        values.append(status)

    if priority is not None:
        validate_priority(priority)
        query += " AND priority = ?"
        values.append(priority)

    query += " ORDER BY id DESC"

    rows = get_db().execute(query, values).fetchall()
    return jsonify([dict(row) for row in rows])


@app.get("/bugs/<int:bug_id>")
def get_bug(bug_id):
    return jsonify(find_bug(bug_id))


@app.patch("/bugs/<int:bug_id>")
def update_bug(bug_id):
    data = read_json({
        "title", "description", "priority", "status", "developer_id"
    })

    if not data:
        raise APIError("Provide at least one field to update.")

    db = get_db()

    # Keep reading, validating, updating, and history together.
    with db:
        db.execute("BEGIN IMMEDIATE")
        old_bug = find_bug(bug_id)

        if "title" in data:
            data["title"] = required_text(data["title"], "title", 200)

        if "description" in data:
            if (
                not isinstance(data["description"], str)
                or len(data["description"]) > 10000
            ):
                raise APIError("Invalid description.")

        if "priority" in data:
            validate_priority(data["priority"])

        if "developer_id" in data:
            validate_developer(data["developer_id"])

        if "status" in data:
            status = data["status"]

            if not isinstance(status, str) or status not in TRANSITIONS:
                raise APIError("Invalid status.")

            if (
                status != old_bug["status"]
                and status not in TRANSITIONS[old_bug["status"]]
            ):
                raise APIError(
                    f"Cannot change status from "
                    f"{old_bug['status']} to {status}.",
                    409,
                )

        changes = {
            field: value
            for field, value in data.items()
            if value != old_bug[field]
        }

        if changes:
            # Field names are safe because read_json allowlists them.
            assignments = ", ".join(
                f"{field} = ?" for field in changes
            )

            db.execute(
                f"UPDATE bugs SET {assignments}, "
                "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                [*changes.values(), bug_id],
            )

            for field, new_value in changes.items():
                if field in {"status", "priority", "developer_id"}:
                    db.execute("""
                        INSERT INTO bug_history (
                            bug_id, field, old_value, new_value
                        ) VALUES (?, ?, ?, ?)
                    """, (
                        bug_id,
                        field,
                        None if old_bug[field] is None
                        else str(old_bug[field]),
                        None if new_value is None
                        else str(new_value),
                    ))

    return jsonify(find_bug(bug_id))


@app.delete("/bugs/<int:bug_id>")
def delete_bug(bug_id):
    db = get_db()

    with db:
        cursor = db.execute(
            "DELETE FROM bugs WHERE id = ?", (bug_id,)
        )

        if cursor.rowcount == 0:
            raise APIError("Bug not found.", 404)

    return "", 204


# ---------- Comments ----------

@app.post("/bugs/<int:bug_id>/comments")
def add_comment(bug_id):
    find_bug(bug_id)

    data = read_json({"content"})
    content = required_text(data.get("content"), "content", 5000)

    db = get_db()

    with db:
        cursor = db.execute(
            "INSERT INTO comments (bug_id, content) VALUES (?, ?)",
            (bug_id, content),
        )

    comment = db.execute(
        "SELECT * FROM comments WHERE id = ?",
        (cursor.lastrowid,),
    ).fetchone()

    return jsonify(dict(comment)), 201


@app.get("/bugs/<int:bug_id>/comments")
def list_comments(bug_id):
    find_bug(bug_id)

    rows = get_db().execute(
        "SELECT * FROM comments WHERE bug_id = ? ORDER BY id",
        (bug_id,),
    ).fetchall()

    return jsonify([dict(row) for row in rows])


# ---------- History ----------

@app.get("/bugs/<int:bug_id>/history")
def get_history(bug_id):
    find_bug(bug_id)

    rows = get_db().execute(
        "SELECT * FROM bug_history WHERE bug_id = ? ORDER BY id",
        (bug_id,),
    ).fetchall()

    return jsonify([dict(row) for row in rows])


with app.app_context():
    initialize_database()


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000)