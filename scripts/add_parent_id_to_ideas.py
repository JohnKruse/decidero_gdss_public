#!/usr/bin/env python3
"""
Migration script to add parent_id column to the ideas table for subcomments support.

Usage:
    python scripts/add_parent_id_to_ideas.py

This script:
1. Adds the parent_id column if it doesn't exist
2. Creates an index on parent_id for query performance
3. Creates a foreign key constraint (SQLite limitation: via temp table recreation)

Note: SQLite doesn't support adding foreign key constraints to existing tables,
so we just add the column and index. The foreign key is enforced at the ORM level.
"""

import sqlite3
import sys
from pathlib import Path


def migrate(db_path: str = "decidero.db") -> None:
    """Add parent_id column and index to the ideas table."""
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

        if "parent_id" in columns:
            print("Column 'parent_id' already exists in 'ideas' table. Skipping.")
        else:
            print("Adding 'parent_id' column to 'ideas' table...")
            cursor.execute(
                "ALTER TABLE ideas ADD COLUMN parent_id INTEGER REFERENCES ideas(id) ON DELETE CASCADE"
            )
            print("Column added successfully.")

        # Check if index exists
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name='ix_ideas_parent_id'"
        )
        if cursor.fetchone():
            print("Index 'ix_ideas_parent_id' already exists. Skipping.")
        else:
            print("Creating index on 'parent_id'...")
            cursor.execute(
                "CREATE INDEX ix_ideas_parent_id ON ideas (parent_id)"
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
