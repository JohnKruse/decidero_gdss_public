#!/usr/bin/env python3
"""
Script to fix user roles in the database.
Converts uppercase roles to lowercase to match UserRole enum values.
"""

import sys
import os

# Add the parent directory to the path so we can import app modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from app.database import DATABASE_URL, Base
from app.models.user import User

def fix_user_roles():
    """Fix user roles by converting uppercase to lowercase."""
    engine = create_engine(DATABASE_URL)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    
    db = SessionLocal()
    try:
        # Get all users with uppercase roles
        users = db.query(User).all()
        
        role_mappings = {
            'ADMIN': 'admin',
            'FACILITATOR': 'facilitator', 
            'PARTICIPANT': 'participant'
        }
        
        updated_count = 0
        for user in users:
            if user.role in role_mappings:
                old_role = user.role
                user.role = role_mappings[user.role]
                print(f"Updated user {user.email}: {old_role} -> {user.role}")
                updated_count += 1
        
        if updated_count > 0:
            db.commit()
            print(f"Successfully updated {updated_count} user roles.")
        else:
            print("No users found with uppercase roles to fix.")
            
    except Exception as e:
        db.rollback()
        print(f"Error fixing user roles: {e}")
        raise
    finally:
        db.close()

if __name__ == "__main__":
    fix_user_roles()