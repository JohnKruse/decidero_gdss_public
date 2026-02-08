import sys
import os
# Add project root to path
sys.path.append(os.getcwd())

from app.database import SessionLocal
from app.data.user_manager import UserManager
from app.utils.security import get_password_hash, verify_password

def reset_admin():
    db = SessionLocal()
    manager = UserManager()
    manager.set_db(db)
    
    login = "admin"
    new_password = "password123"
    
    user = manager.get_user_by_login(login)
    if not user:
        print(f"User {login} not found!")
        return

    print(f"Found user {login}.")
    print(f"Current Stored hash: {user.hashed_password}")
    
    new_hash = get_password_hash(new_password)
    print(f"Generated new hash for '{new_password}': {new_hash}")
    
    user.hashed_password = new_hash
    db.commit()
    print(f"Password reset to '{new_password}'")
    
    # Verify immediately
    is_valid = verify_password(new_password, new_hash)
    print(f"Verification check (in-process): {is_valid}")

if __name__ == "__main__":
    reset_admin()
