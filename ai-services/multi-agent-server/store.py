import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

DATABASE = Path(__file__).parent / "instance" / "workflows.db"


class WorkflowConflict(ValueError):
    pass


def get_connection():
    DATABASE.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DATABASE)
    connection.row_factory = sqlite3.Row
    connection.executescript("""
        CREATE TABLE IF NOT EXISTS workflows (
            id TEXT PRIMARY KEY, task TEXT NOT NULL, status TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS workflow_events (
            sequence INTEGER PRIMARY KEY AUTOINCREMENT,
            workflow_id TEXT NOT NULL,
            status TEXT NOT NULL,
            details TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
    """)
    return connection


def _event(connection, workflow_id, status, details):
    connection.execute(
        "INSERT INTO workflow_events (workflow_id, status, details, created_at) "
        "VALUES (?, ?, ?, ?)",
        (workflow_id, status, json.dumps(details), datetime.now(timezone.utc).isoformat()),
    )


def save_workflow(workflow_id, task):
    connection = get_connection()
    try:
        with connection:
            connection.execute(
                "INSERT INTO workflows (id, task, status) VALUES (?, ?, ?)",
                (workflow_id, task, "received"),
            )
            _event(connection, workflow_id, "received", {})
    finally:
        connection.close()


def transition(workflow_id, expected, status, details):
    connection = get_connection()
    try:
        with connection:
            row = connection.execute(
                "UPDATE workflows SET status = ? WHERE id = ? AND status = ?",
                (status, workflow_id, expected),
            )
            if row.rowcount != 1:
                raise WorkflowConflict("Workflow state changed; refresh its status")
            _event(connection, workflow_id, status, details)
    finally:
        connection.close()


def get_workflow(workflow_id):
    connection = get_connection()
    try:
        row = connection.execute(
            "SELECT id, task, status FROM workflows WHERE id = ?", (workflow_id,)
        ).fetchone()
        if row is None:
            return None
        events = connection.execute(
            "SELECT status, details, created_at FROM workflow_events "
            "WHERE workflow_id = ? ORDER BY sequence", (workflow_id,)
        ).fetchall()
        history = [
            {"status": event["status"], "details": json.loads(event["details"]),
             "created_at": event["created_at"]}
            for event in events
        ]
        # The latest run contains the current plan, evidence, result and review.
        current = {}
        for event in history:
            if event["status"] == "planning":
                current = {}
            current.update(event["details"])
        return {"workflow_id": row["id"], "task": row["task"],
                "status": row["status"], **current, "history": history}
    finally:
        connection.close()
