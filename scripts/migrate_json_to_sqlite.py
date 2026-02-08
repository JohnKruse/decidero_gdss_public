import os
import json
import yaml
import base64
import sys
import getpass
from pathlib import Path
from typing import Dict, List, Any, Optional, Union
import math # For checking NaN
from datetime import datetime, timezone # For parsing dates

# --- Adjust sys.path to import app modules ---
# Assuming the script is run from the project root directory
PROJECT_ROOT = Path(__file__).resolve().parent.parent
from sqlalchemy import func # For SQL functions like lower()
sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy.orm import Session
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base, DATABASE_URL, engine # Import engine and Base from app setup
from app.models import User, Meeting, MeetingFacilitator, Idea, participants_table # Import all models
from app.utils.security import get_password_hash # Import from the correct location
from app.utils.identifiers import generate_meeting_id, generate_facilitator_id

# --- Encryption Utilities (Adapted from BaseManager/EncryptionManager) ---
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

SALT_FILE = PROJECT_ROOT / "data" / ".salt"
DATA_DIR = PROJECT_ROOT / "data"
USERS_PUBLIC_FILE = DATA_DIR / "users_public.json"
USERS_SENSITIVE_FILE = DATA_DIR / "users_sensitive.enc"
MEETINGS_DIR = DATA_DIR / "meetings"
MEETINGS_ENCRYPTED_DIR = DATA_DIR / "meetings_encrypted"
MEETINGS_ARCHIVE_DIR = DATA_DIR / "meetings_archive"

cipher_suite: Optional[Fernet] = None

def _derive_key(password: str, salt: bytes) -> bytes:
    """Derive encryption key from password using PBKDF2."""
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        # Use iterations consistent with BaseManager/EncryptionManager (check which one is primary)
        # Using 480000 from BaseManager as it seemed more general
        iterations=480000,
    )
    key = base64.urlsafe_b64encode(kdf.derive(password.encode()))
    return key

def initialize_encryption(password: Optional[str] = None):
    """Initialize the global cipher_suite using password or env key."""
    global cipher_suite
    try:
        env_key = os.environ.get('DECIDERO_ENCRYPTION_KEY')
        key_bytes: Optional[bytes] = None

        if env_key:
            print("Using encryption key from DECIDERO_ENCRYPTION_KEY environment variable.")
            key_bytes = base64.urlsafe_b64decode(env_key)
        else:
            if not SALT_FILE.exists():
                raise FileNotFoundError(f"Salt file not found at {SALT_FILE}. Cannot derive key without salt.")

            with open(SALT_FILE, "rb") as f:
                salt = f.read()

            if password is None:
                password = os.environ.get('DECIDERO_KEY_PASSWORD')
                if not password:
                    print("Encryption password needed.")
                    password = getpass.getpass("Enter encryption password (used for data files): ")
                else:
                    print("Using encryption password from DECIDERO_KEY_PASSWORD environment variable.")

            if not password:
                 raise ValueError("Encryption password is required but was not provided.")

            print("Deriving encryption key from password and salt...")
            key_bytes = _derive_key(password, salt)

        if key_bytes:
            cipher_suite = Fernet(key_bytes)
            print("Encryption initialized successfully.")
        else:
            raise ValueError("Failed to obtain encryption key.")

    except Exception as e:
        print(f"FATAL: Error initializing encryption: {str(e)}")
        sys.exit(1)

def _load_encrypted(file_path: Path) -> Optional[Dict]:
    """Load and decrypt data (adapted from BaseManager)."""
    global cipher_suite
    if not cipher_suite:
        raise RuntimeError("Encryption not initialized. Call initialize_encryption first.")
    if not file_path.exists():
        print(f"Warning: Encrypted file not found at {file_path}")
        return None
    try:
        with open(file_path, "rb") as f:
            encrypted_data = f.read()
        if not encrypted_data:
            print(f"Warning: Empty encrypted file at {file_path}")
            return {}

        decrypted_data = cipher_suite.decrypt(encrypted_data)
        data = json.loads(decrypted_data)

        # Simple integrity check placeholder (checksum logic removed for simplicity here)
        # if '_checksum' in data:
        #     data.pop('_checksum') # Remove checksum if present

        return data
    except Exception as e:
        print(f"Error loading or decrypting {file_path}: {str(e)}")
        return None

def _load_json(file_path: Path) -> Optional[Any]:
    """Load data from JSON file."""
    if not file_path.exists():
        print(f"Warning: JSON file not found at {file_path}")
        return None
    try:
        with open(file_path, 'r') as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading JSON from {file_path}: {str(e)}")
        return None
    

# --- Data Parsing Helper Functions ---

def parse_datetime_safe(value: Optional[str]) -> Optional[datetime]:
    """Safely parse an ISO format datetime string."""
    if not value:
        return None
    try:
        normalized = value.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalized)
        if parsed.tzinfo is None or parsed.tzinfo.utcoffset(parsed) is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except (ValueError, TypeError):
        print(f"Warning: Could not parse datetime: {value}")
        return None

def parse_boolean_safe(value: Any) -> bool:
    """Safely parse a value intended to be boolean, handling None/NaN."""
    if value is None:
        return False # Default for nullable boolean might be None, but model defaults to False
    if isinstance(value, float) and math.isnan(value):
        return False # Treat NaN as False
    # Handle common string representations, default to False if unsure
    if isinstance(value, str):
        return value.lower() in ['true', '1', 't', 'y', 'yes']
    return bool(value) # Standard bool conversion for other types

    # Helper function definitions moved to top level

# --- Migration Logic ---

def migrate_users(db: Session):
    """Migrate users from JSON/encrypted files to SQLite."""
    print("\n--- Migrating Users (Skipped) ---")
    print("Skipping user migration as requested (lost password/test data).")
    return # Add return statement to skip execution
    # Original logic removed as it's being skipped and caused syntax issues.

def create_default_admin(db: Session):
    """Creates a default admin user if one doesn't exist."""
    print("\n--- Ensuring Default Admin User ---")
    admin_email = "admin@decidero.local"
    admin_pass = "ChangeMeNow!" # Default password from myproject.md

    existing_admin = db.query(User).filter(func.lower(User.email) == admin_email.lower()).first()
    if existing_admin:
        print(f"Admin user {admin_email} already exists.")
        # Optionally update password if needed, e.g., if password_changed is False
        # if not existing_admin.password_changed:
        #     print("Updating password for existing admin...")
        #     existing_admin.hashed_password = get_password_hash(admin_pass)
        #     existing_admin.password_changed = True # Mark as changed
        #     db.add(existing_admin)
        #     db.commit()
        return

    print(f"Creating default admin user: {admin_email}")
    hashed_password = get_password_hash(admin_pass)
    admin_user = User(
        email=admin_email,
        first_name="Admin",
        last_name="User",
        login="admin", # Default login
        hashed_password=hashed_password,
        role="ADMIN",
        password_changed=False # User should change this on first login
    )
    try:
        db.add(admin_user)
        db.commit()
        print("Default admin user created successfully.")
    except Exception as e:
        db.rollback()
        print(f"Error creating default admin user: {e}")




def migrate_meetings_and_ideas(db: Session):
    """Migrate meetings and their ideas from directories to SQLite."""
    print("\n--- Migrating Meetings and Ideas ---")
    meeting_dirs_to_scan = {
        MEETINGS_DIR: {'encrypted': False, 'status': 'active'},
        MEETINGS_ENCRYPTED_DIR: {'encrypted': True, 'status': 'active'},
        MEETINGS_ARCHIVE_DIR: {'encrypted': False, 'status': 'archived'}, # Assuming archive is not encrypted
        # Add logic if archive can also be encrypted
    }

    migrated_meetings = 0
    skipped_meetings = 0
    migrated_ideas = 0
    skipped_ideas = 0
    processed_meeting_ids = set() # Track original meeting IDs if they exist

    # Map emails to new User IDs for FK relationships
    user_id_map = {user.email.strip().lower(): user.user_id for user in db.query(User).all()}

    for base_dir, props in meeting_dirs_to_scan.items():
        if not base_dir.exists():
            print(f"Directory not found: {base_dir}. Skipping.")
            continue

        print(f"Scanning directory: {base_dir} (Encrypted: {props['encrypted']}, Status: {props['status']})")
        for meeting_dirname in os.listdir(base_dir):
            meeting_path = base_dir / meeting_dirname
            if not meeting_path.is_dir():
                continue

            print(f"  Processing meeting directory: {meeting_dirname}")

            # --- Load Meeting Info ---
            meeting_info: Optional[Dict] = None
            meeting_info_file = meeting_path / "meeting_info.json"
            meeting_data_enc_file = meeting_path / "meeting_data.enc" # Used by EncryptionManager

            if props['encrypted']:
                 # Try decrypting using the logic adapted from BaseManager/_load_encrypted
                 # Assuming meeting data was saved using _save_encrypted
                 # Check if meeting_data.enc exists, as used by EncryptionManager
                 if meeting_data_enc_file.exists():
                      meeting_info = _load_encrypted(meeting_data_enc_file)
                 else:
                      print(f"    Warning: Encrypted meeting, but {meeting_data_enc_file} not found. Trying meeting_info.json (might fail decryption).")
                      # Attempt decryption of meeting_info.json if it exists (less likely)
                      if meeting_info_file.exists():
                           meeting_info = _load_encrypted(meeting_info_file) # This might fail if not saved this way
            else:
                meeting_info = _load_json(meeting_info_file)

            if not meeting_info:
                print(f"    Warning: Could not load meeting info for {meeting_dirname}. Skipping meeting.")
                skipped_meetings += 1
                continue

            # --- Process Meeting ---
            original_meeting_id = meeting_info.get('meeting_id') # Assuming old data had this
            if original_meeting_id and original_meeting_id in processed_meeting_ids:
                 print(f"    Meeting with original ID {original_meeting_id} already processed. Skipping.")
                 skipped_meetings += 1
                 continue

            # Check if meeting already migrated (using title and maybe facilitator/timestamp as proxy)
            # This is imperfect, ideally use original_meeting_id if reliable
            existing_meeting = db.query(Meeting).filter(Meeting.title == meeting_info.get('title')).first() # Add more filters if needed
            if existing_meeting:
                 print(f"    Meeting '{meeting_info.get('title')}' seems to already exist in DB. Skipping.")
                 skipped_meetings += 1
                 if original_meeting_id: processed_meeting_ids.add(original_meeting_id)
                 continue

            # Find Facilitator/User who owns the meeting
            facilitator_email = meeting_info.get('facilitator_email')
            facilitator_key = facilitator_email.strip().lower() if facilitator_email else None
            owner_user_id = user_id_map.get(facilitator_key) if facilitator_key else None
            owner_user: Optional[User] = db.get(User, owner_user_id) if owner_user_id else None
            if owner_user is None:
                 print(f"    Warning: Facilitator '{facilitator_email}' not found in users. Skipping meeting '{meeting_info.get('title')}'.")
                 skipped_meetings += 1
                 continue

            try:
                created_at = parse_datetime_safe(meeting_info.get('created_at'))
                start_at = parse_datetime_safe(meeting_info.get('started_at'))
                end_at = parse_datetime_safe(meeting_info.get('end_time'))
                reference_time = created_at or start_at or datetime.now(timezone.utc)
                meeting_identifier = generate_meeting_id(db, reference_time)

                db_meeting = Meeting(
                    meeting_id=meeting_identifier,
                    legacy_meeting_id=original_meeting_id,
                    title=meeting_info.get('title'),
                    description=meeting_info.get('description'),
                    created_at=created_at,
                    started_at=start_at,
                    end_time=end_at,
                    status=props['status'], # Set status based on directory
                    is_public=parse_boolean_safe(meeting_info.get('is_public', False)),
                    owner_id=owner_user.user_id,
                )
                db_meeting.owner = owner_user
                db.add(db_meeting)
                db.flush() # Flush so meeting_id is persisted for relationships

                # Ensure facilitator roster entry exists for the owner
                owner_assignment = MeetingFacilitator(
                    facilitator_id=generate_facilitator_id(
                        db, owner_user.first_name, owner_user.last_name
                    ),
                    meeting_id=db_meeting.meeting_id,
                    user_id=owner_user.user_id,
                    is_owner=True,
                )
                owner_assignment.user = owner_user
                db_meeting.facilitator_links.append(owner_assignment)

                # Optionally backfill co-facilitators if present
                co_facilitator_entries = meeting_info.get('co_facilitators') or meeting_info.get('co_facilitator_emails') or []
                for entry in co_facilitator_entries:
                    if isinstance(entry, dict):
                        email = entry.get('email') or entry.get('login')
                    else:
                        email = str(entry) if entry else None
                    if not email:
                        continue
                    mapped_id = user_id_map.get(email.strip().lower())
                    if not mapped_id or mapped_id == owner_user.user_id:
                        continue
                    co_user = db.get(User, mapped_id)
                    if co_user is None:
                        print(f"      Warning: Co-facilitator '{email}' not found for meeting '{db_meeting.title}'. Skipping.")
                        continue
                    assignment = MeetingFacilitator(
                        facilitator_id=generate_facilitator_id(
                            db, co_user.first_name, co_user.last_name
                        ),
                        meeting_id=db_meeting.meeting_id,
                        user_id=co_user.user_id,
                        is_owner=False,
                    )
                    assignment.user = co_user
                    db_meeting.facilitator_links.append(assignment)
                db.flush()

                # --- Process Participants ---
                participant_emails = meeting_info.get('participants', []) # Assuming list of emails
                participants_to_add = []
                for email in participant_emails:
                    user_id = user_id_map.get(email.strip().lower())
                    if user_id:
                        # Fetch the User object to add to the relationship
                        user = db.get(User, user_id)
                        if user:
                            participants_to_add.append(user)
                    else:
                        print(f"      Warning: Participant '{email}' not found for meeting '{db_meeting.title}'.")
                db_meeting.participants.extend(participants_to_add)

                # --- Process Ideas ---
                ideas_file = meeting_path / "ideas" / "ideas.json"
                ideas_data: Optional[List] = None
                if ideas_file.exists():
                    if props['encrypted']:
                        # Assuming ideas file was also encrypted using _save_encrypted
                        ideas_data = _load_encrypted(ideas_file)
                    else:
                        ideas_data = _load_json(ideas_file)

                if ideas_data:
                    for idea_item in ideas_data:
                        author_email = idea_item.get('author_email') # Assuming email stored
                        author_id = user_id_map.get(author_email.strip().lower()) if author_email else None
                        if not author_id:
                             print(f"      Warning: Author '{author_email}' not found for idea in meeting '{db_meeting.title}'. Skipping idea.")
                             skipped_ideas += 1
                             continue

                        try:
                            db_idea = Idea(
                                content=idea_item.get('content'),
                                timestamp=parse_datetime_safe(idea_item.get('timestamp')),
                                # updated_at - handled by default/onupdate
                                meeting_id=db_meeting.meeting_id,
                                user_id=author_id
                            )
                            db.add(db_idea)
                            migrated_ideas += 1
                        except Exception as idea_err:
                             print(f"      Error processing idea {idea_item.get('idea_id', 'N/A')}: {idea_err}. Skipping.")
                             skipped_ideas += 1
                             db.rollback() # Rollback this specific idea

                migrated_meetings += 1
                if original_meeting_id: processed_meeting_ids.add(original_meeting_id)

            except Exception as meeting_err:
                print(f"    Error processing meeting {meeting_dirname}: {meeting_err}. Skipping.")
                skipped_meetings += 1
                db.rollback() # Rollback this meeting and its ideas

    if migrated_meetings > 0 or skipped_meetings > 0 or migrated_ideas > 0 or skipped_ideas > 0:
        print(f"\nMeeting/Idea Migration Summary:")
        print(f"  Meetings: Migrated={migrated_meetings}, Skipped={skipped_meetings}")
        print(f"  Ideas:    Migrated={migrated_ideas}, Skipped={skipped_ideas}")
        if migrated_meetings > 0 or migrated_ideas > 0:
            print("Committing migrated meetings and ideas...")
            db.commit()
    else:
        print("No new meetings or ideas to migrate.")


def main():
    """Main migration function."""
    print("Starting data migration from JSON/Encrypted files to SQLite...")

    # --- Initialize Encryption ---
    # Consider adding command-line args for password/key if preferred
    initialize_encryption() # Will prompt for password if needed and not in env vars

    # --- Database Setup ---
    print(f"Using database: {DATABASE_URL}")
    # Create tables if they don't exist
    print("Creating database tables (if they don't exist)...")
    Base.metadata.create_all(bind=engine)
    print("Tables created.")

    # --- Create Session ---
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db: Session = SessionLocal()

    try:
        # --- Ensure default admin exists ---
        # create_default_admin(db)

        # --- Run Migrations ---
        migrate_users(db)
        migrate_meetings_and_ideas(db)

        print("\nMigration process completed.")

    except Exception as e:
        print(f"\nAn error occurred during migration: {e}")
        db.rollback() # Rollback any partial changes from the failed step
    finally:
        db.close()
        print("Database session closed.")

if __name__ == "__main__":
    main()
