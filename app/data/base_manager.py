import os
import json
import stat
import base64
import pandas as pd
from typing import Dict, Optional, List, Any
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC


class BaseManager:
    """Base class for data managers with encryption support."""

    def __init__(self):
        self.base_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data"
        )
        os.makedirs(self.base_dir, exist_ok=True)

        # Set restrictive permissions on data directory
        os.chmod(self.base_dir, stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)  # 700

        # Initialize encryption
        self.salt_file = os.path.join(self.base_dir, ".salt")
        self._init_encryption()

        self._ensure_directories()

    def _ensure_directories(self):
        """Ensure required directories exist with proper permissions."""
        dirs = [
            os.path.join(self.base_dir, "meetings"),
            os.path.join(self.base_dir, "meetings_encrypted"),
            os.path.join(self.base_dir, "meetings_archive"),
        ]

        for directory in dirs:
            os.makedirs(directory, exist_ok=True)
            # Set restrictive permissions (700)
            os.chmod(directory, stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)

    def _init_encryption(self, password: Optional[str] = None):
        """Initialize encryption using environment variable or generate new key."""
        try:
            # Try to get key from environment
            env_key = os.environ.get("DECIDERO_ENCRYPTION_KEY")

            if env_key:
                # Use key from environment
                key = base64.b64decode(env_key)
                print("Using encryption key from environment")
            else:
                # Generate and save salt if it doesn't exist
                if not os.path.exists(self.salt_file):
                    salt = os.urandom(16)
                    with open(self.salt_file, "wb") as f:
                        f.write(salt)
                    # Set restrictive permissions (600)
                    os.chmod(self.salt_file, stat.S_IRUSR | stat.S_IWUSR)
                else:
                    with open(self.salt_file, "rb") as f:
                        salt = f.read()

                # Derive key using provided password or from environment
                if password is None:
                    password = os.environ.get(
                        "DECIDERO_KEY_PASSWORD", "default-password-change-me!"
                    )
                kdf = PBKDF2HMAC(
                    algorithm=hashes.SHA256(),
                    length=32,
                    salt=salt,
                    iterations=480000,
                )
                key = base64.b64encode(kdf.derive(password.encode()))
                print("Generated encryption key from password and salt")

            self.cipher_suite = Fernet(key)
            return key
        except Exception as e:
            print(f"Error initializing encryption: {str(e)}")
            raise

    def _save_json(self, path: str, data: Any) -> bool:
        """Save data to JSON file with proper permissions."""
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w") as f:
                json.dump(data, f, indent=4)
            # Set restrictive permissions (600)
            os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
            return True
        except Exception as e:
            print(f"Error saving JSON to {path}: {str(e)}")
            return False

    def _load_json(self, path: str) -> Optional[Any]:
        """Load data from JSON file."""
        try:
            if not os.path.exists(path):
                return None
            with open(path, "r") as f:
                return json.load(f)
        except Exception as e:
            print(f"Error loading JSON from {path}: {str(e)}")
            return None

    def _save_encrypted(self, file_path: str, data: dict) -> bool:
        """Save data with encryption and proper permissions."""
        try:
            # Ensure directory exists
            os.makedirs(os.path.dirname(file_path), exist_ok=True)

            # Add integrity check
            data["_checksum"] = self._calculate_checksum(str(data))

            # Convert data to JSON and encrypt
            json_data = json.dumps(data).encode()
            encrypted_data = self.cipher_suite.encrypt(json_data)

            # Save encrypted data
            with open(file_path, "wb") as f:
                f.write(encrypted_data)

            # Set restrictive permissions (600)
            os.chmod(file_path, stat.S_IRUSR | stat.S_IWUSR)

            print(f"Successfully saved encrypted data to {file_path}")
            return True
        except Exception as e:
            print(f"Error saving encrypted data to {file_path}: {str(e)}")
            return False

    def _load_encrypted(self, file_path: str) -> dict:
        """Load and decrypt data with integrity check."""
        try:
            if not os.path.exists(file_path):
                print(f"No encrypted file found at {file_path}")
                return {}

            with open(file_path, "rb") as f:
                encrypted_data = f.read()

            if not encrypted_data:
                print(f"Empty encrypted file at {file_path}")
                return {}

            # Decrypt and parse JSON
            decrypted_data = self.cipher_suite.decrypt(encrypted_data)
            data = json.loads(decrypted_data)

            # Verify integrity
            if "_checksum" in data:
                stored_checksum = data.pop("_checksum")
                calculated_checksum = self._calculate_checksum(str(data))
                if stored_checksum != calculated_checksum:
                    print("Warning: Data integrity check failed!")
                    return {}

            return data
        except Exception as e:
            print(f"Error loading encrypted data from {file_path}: {str(e)}")
            return {}

    def _calculate_checksum(self, data: str) -> str:
        """Calculate SHA-256 checksum of data."""
        digest = hashes.Hash(hashes.SHA256())
        digest.update(data.encode())
        return base64.b64encode(digest.finalize()).decode()

    def _dataframe_to_records(self, df: pd.DataFrame) -> List[Dict]:
        """Safely convert DataFrame to list of records."""
        try:
            return df.to_dict("records")
        except Exception as e:
            print(f"Error converting DataFrame to records: {str(e)}")
            return []

    def reencrypt_all_files(self, old_password: str, new_password: str) -> bool:
        """
        Re-encrypt all sensitive files with a new key derived from the new password.
        This should be called when the admin password changes.
        """
        try:
            # Store the current cipher suite
            old_cipher = self.cipher_suite

            # Initialize encryption with old password to ensure we can decrypt
            self._init_encryption(old_password)

            # Get all encrypted files
            encrypted_files = []
            for root, _, files in os.walk(self.base_dir):
                for file in files:
                    if file.endswith(".enc"):
                        encrypted_files.append(os.path.join(root, file))

            # Decrypt all files with old key
            decrypted_data = {}
            for file_path in encrypted_files:
                data = self._load_encrypted(file_path)
                if data:  # Only store if decryption was successful
                    decrypted_data[file_path] = data

            # Initialize encryption with new password
            self._init_encryption(new_password)

            # Re-encrypt all files with new key
            for file_path, data in decrypted_data.items():
                success = self._save_encrypted(file_path, data)
                if not success:
                    # If any file fails to re-encrypt, revert to old key and return False
                    self.cipher_suite = old_cipher
                    return False

            return True

        except Exception as e:
            print(f"Error during re-encryption: {str(e)}")
            # Revert to old cipher suite in case of error
            self.cipher_suite = old_cipher
            return False
