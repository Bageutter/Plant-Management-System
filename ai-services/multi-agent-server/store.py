import sqlite3
from pathlib import Path

DATABASE = Path(__file__).parent / "instance" / "workflows.db"


def get_connection():
    DATABASE.parent.mkdir(parents=True, exist_ok=True)

    connection = sqlite3.connect(DATABASE)
    connection.row_factory = sqlite3.Row
    connection.execute("""
        CREATE TABLE IF NOT EXISTS workflows (
            id TEXT PRIMARY KEY,
            task TEXT NOT NULL,
            status TEXT NOT NULL
        )
    """)
    connection.commit()
    return connection


def save_workflow(workflow_id, task):
    connection = get_connection()
    try:
        connection.execute(
            "INSERT INTO workflows (id, task, status) VALUES (?, ?, ?)",
            (workflow_id, task, "received"),
        )
        connection.commit()
    finally:
        connection.close()


def get_workflow(workflow_id):
    connection = get_connection()
    try:
        row = connection.execute(
            "SELECT id, task, status FROM workflows WHERE id = ?",
            (workflow_id,),
        ).fetchone()
        if row is None:
            return None
        return {
            "workflow_id": row["id"],
            "task": row["task"],
            "status": row["status"],
        }
    finally:
        connection.close()
