import sqlite3
import os

DB_PATH = "decidero.db"

def add_verification_columns():
    if not os.path.exists(DB_PATH):
        print(f"Database {DB_PATH} not found. Skipping migration.")
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    columns = [
        ("is_verified", "BOOLEAN DEFAULT 0"),
        ("verification_token", "VARCHAR"),
    ]

    for col_name, col_def in columns:
        try:
            cursor.execute(f"ALTER TABLE users ADD COLUMN {col_name} {col_def}")
            print(f"Successfully added '{col_name}' column to 'users' table.")
        except sqlite3.OperationalError as e:
            if "duplicate column" in str(e):
                print(f"'{col_name}' column already exists.")
            else:
                print(f"Error adding column '{col_name}': {e}")
    
    conn.commit()
    conn.close()

if __name__ == "__main__":
    add_verification_columns()
