import sys
import os
# Add project root to path
sys.path.append(os.getcwd())

from app.database import SessionLocal
from app.data.user_manager import UserManager
from app.utils.security import get_password_hash
from app.models.user import UserRole

def create_admin():
    db = SessionLocal()
    manager = UserManager()
    manager.set_db(db)
    
    login = "admin"
    password = "password123"
    email = "admin@decidero.local"
    
    if manager.get_user_by_login(login):
        print("Admin user already exists.")
        return

    print(f"Creating admin user: {login} / {password}")
    try:
        hashed = get_password_hash(password)
        manager.add_user(
            first_name="Admin",
            last_name="User",
            email=email,
            hashed_password=hashed,
            role=UserRole.ADMIN.value,
            login=login,
            organization="Decidero Admin"
        )
        print("Admin user created successfully.")
    except Exception as e:
        print(f"Failed to create admin: {e}")

if __name__ == "__main__":
    create_admin()
