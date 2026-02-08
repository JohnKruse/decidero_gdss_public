#!/usr/bin/env python3
"""
Migration script to add activity_id column to the ideas table.

Usage:
    python scripts/add_activity_id_to_ideas.py

This script:
1. Adds the activity_id column if it doesn't exist
2. Creates an index on activity_id for query performance
"""

import sqlite3
import sys
from pathlib import Path


def migrate(db_path: str = "decidero.db") -> None:
    """Add activity_id column and index to the ideas table."""
    db_file = Path(db_path)
    if not db_file.exists():
        print(f"Database file not found: {db_path}")
        sys.exit(1)

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    try:
        # Check if column already exists
        cursor.execute("PRAGMA table_info(ideas)")
        columns = {row[1] for row in cursor.fetchall()}

        if "activity_id" in columns:
            print("Column 'activity_id' already exists in 'ideas' table. Skipping.")
        else:
            print("Adding 'activity_id' column to 'ideas' table...")
            cursor.execute(
                "ALTER TABLE ideas ADD COLUMN activity_id VARCHAR(32)"
            )
            print("Column added successfully.")

        # Check if index exists
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name='ix_ideas_activity_id'"
        )
        if cursor.fetchone():
            print("Index 'ix_ideas_activity_id' already exists. Skipping.")
        else:
            print("Creating index on 'activity_id'...")
            cursor.execute(
                "CREATE INDEX ix_ideas_activity_id ON ideas (activity_id)"
            )
            print("Index created successfully.")

        conn.commit()
        print("Migration completed successfully.")

    except sqlite3.Error as e:
        conn.rollback()
        print(f"Migration failed: {e}")
        sys.exit(1)
    finally:
        conn.close()


if __name__ == "__main__":
    migrate()
