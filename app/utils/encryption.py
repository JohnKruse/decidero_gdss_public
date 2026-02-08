from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
import base64
import os
import json
from typing import Dict, Any, Optional


class EncryptionManager:
    """Manages encryption/decryption of sensitive data using keys derived from admin password."""

    def __init__(self):
        self._encryption_key = None
        self._salt = None
        self._salt_file = "data/.salt"

    def initialize_with_admin_password(self, admin_password: str) -> None:
        """Initialize encryption with admin password. Called during first admin registration."""
        # Generate a random salt if not exists
        if not os.path.exists(self._salt_file):
            self._salt = os.urandom(16)
            # Save salt
            os.makedirs(os.path.dirname(self._salt_file), exist_ok=True)
            with open(self._salt_file, "wb") as f:
                f.write(self._salt)
        else:
            # Load existing salt
            with open(self._salt_file, "rb") as f:
                self._salt = f.read()

        # Generate key from password
        self._encryption_key = self._derive_key(admin_password)

    def _derive_key(self, password: str) -> bytes:
        """Derive encryption key from password using PBKDF2."""
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=self._salt,
            iterations=100000,
        )
        key = base64.urlsafe_b64encode(kdf.derive(password.encode()))
        return key

    def encrypt_data(self, data: Dict[str, Any]) -> str:
        """Encrypt dictionary data to string."""
        if not self._encryption_key:
            raise ValueError("Encryption not initialized with admin password")

        f = Fernet(self._encryption_key)
        json_str = json.dumps(data)
        encrypted_data = f.encrypt(json_str.encode())
        return base64.urlsafe_b64encode(encrypted_data).decode()

    def decrypt_data(self, encrypted_str: str) -> Dict[str, Any]:
        """Decrypt string to dictionary data."""
        if not self._encryption_key:
            raise ValueError("Encryption not initialized with admin password")

        f = Fernet(self._encryption_key)
        encrypted_data = base64.urlsafe_b64decode(encrypted_str.encode())
        decrypted_data = f.decrypt(encrypted_data)
        return json.loads(decrypted_data.decode())

    def encrypt_file(self, input_path: str, output_path: str) -> None:
        """Encrypt a JSON file."""
        if not self._encryption_key:
            raise ValueError("Encryption not initialized with admin password")

        with open(input_path, "r") as f:
            data = json.load(f)

        encrypted_data = self.encrypt_data(data)

        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, "w") as f:
            f.write(encrypted_data)

    def decrypt_file(self, input_path: str, output_path: str) -> None:
        """Decrypt an encrypted JSON file."""
        if not self._encryption_key:
            raise ValueError("Encryption not initialized with admin password")

        with open(input_path, "r") as f:
            encrypted_data = f.read()

        decrypted_data = self.decrypt_data(encrypted_data)

        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, "w") as f:
            json.dump(decrypted_data, f, indent=2)

    def encrypt_meeting_data(self, meeting_id: str, data: Dict[str, Any]) -> None:
        """Encrypt meeting data and save to a separate encrypted file."""
        encrypted_path = f"data/meetings_encrypted/{meeting_id}/meeting_data.enc"
        os.makedirs(os.path.dirname(encrypted_path), exist_ok=True)

        encrypted_data = self.encrypt_data(data)
        with open(encrypted_path, "w") as f:
            f.write(encrypted_data)

    def decrypt_meeting_data(self, meeting_id: str) -> Optional[Dict[str, Any]]:
        """Decrypt meeting data from encrypted file."""
        encrypted_path = f"data/meetings_encrypted/{meeting_id}/meeting_data.enc"

        if not os.path.exists(encrypted_path):
            return None

        with open(encrypted_path, "r") as f:
            encrypted_data = f.read()

        return self.decrypt_data(encrypted_data)


# Global encryption manager instance
encryption_manager = EncryptionManager()
