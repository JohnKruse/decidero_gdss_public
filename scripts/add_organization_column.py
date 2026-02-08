import sqlite3
import os

DB_PATH = "decidero.db"

def add_organization_column():
    if not os.path.exists(DB_PATH):
        print(f"Database {DB_PATH} not found. Skipping migration.")
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    try:
        cursor.execute("ALTER TABLE users ADD COLUMN organization VARCHAR")
        conn.commit()
        print("Successfully added 'organization' column to 'users' table.")
    except sqlite3.OperationalError as e:
        if "duplicate column" in str(e):
            print("'organization' column already exists.")
        else:
            print(f"Error adding column: {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    add_organization_column()
