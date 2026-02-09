import json
import os
from typing import Dict, List, Any, Optional
from datetime import datetime
from pathlib import Path
import threading
import logging
from ..schemas.meeting import MeetingStatus

logger = logging.getLogger(__name__)


class JsonDataStore:
    """
    A thread-safe JSON-based data store that handles reading and writing data to JSON files.
    Implements basic CRUD operations with file locking to prevent concurrent access issues.
    """

    def __init__(self, file_path: str):
        self.file_path = Path(file_path)
        self.lock = threading.Lock()
        self._ensure_file_exists()

    def _ensure_file_exists(self) -> None:
        """Create the JSON file and its directory if they don't exist."""
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.file_path.exists():
            with open(self.file_path, "w") as f:
                json.dump([], f)

    def _read_data(self) -> List[Dict[str, Any]]:
        """Read data from the JSON file with error handling."""
        try:
            with open(self.file_path, "r") as f:
                return json.load(f)
        except json.JSONDecodeError:
            logger.error(f"Error decoding JSON from {self.file_path}")
            return []
        except Exception as e:
            logger.error(f"Error reading from {self.file_path}: {str(e)}")
            return []

    def _write_data(self, data: List[Dict[str, Any]]) -> bool:
        """Write data to the JSON file with error handling."""
        try:
            with open(self.file_path, "w") as f:
                json.dump(data, f, indent=2, default=str)
            return True
        except Exception as e:
            logger.error(f"Error writing to {self.file_path}: {str(e)}")
            return False

    def create(self, item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Create a new item in the store."""
        with self.lock:
            data = self._read_data()
            # Generate new ID
            item_id = len(data) + 1
            item["id"] = item_id
            data.append(item)
            if self._write_data(data):
                return item
            return None

    def read_all(self) -> List[Dict[str, Any]]:
        """Read all items from the store."""
        with self.lock:
            return self._read_data()

    def read_one(self, item_id: int) -> Optional[Dict[str, Any]]:
        """Read a single item by ID."""
        with self.lock:
            data = self._read_data()
            for item in data:
                if item.get("id") == item_id:
                    return item
            return None

    def update(self, item_id: int, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Update an existing item."""
        with self.lock:
            data = self._read_data()
            for item in data:
                if item.get("id") == item_id:
                    item.update(updates)
                    if self._write_data(data):
                        return item
            return None

    def delete(self, item_id: int) -> bool:
        """Delete an item by ID."""
        with self.lock:
            data = self._read_data()
            initial_length = len(data)
            data = [item for item in data if item.get("id") != item_id]
            if len(data) < initial_length:
                return self._write_data(data)
            return False


class MeetingDataAccess:
    """
    Data access layer for meetings, implementing specific meeting-related queries
    and data operations using the JsonDataStore.
    """

    def __init__(self, data_dir: str = "data"):
        base_dir = Path(data_dir)
        self.store = JsonDataStore(str(base_dir / "meetings.json"))

    def create_meeting(self, meeting_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Create a new meeting."""
        meeting_data["created_at"] = datetime.utcnow()
        meeting_data["updated_at"] = datetime.utcnow()
        return self.store.create(meeting_data)

    def get_active_meetings(self) -> List[Dict[str, Any]]:
        """Get all active meetings."""
        active_statuses = [MeetingStatus.ACTIVE, MeetingStatus.PAUSED]
        return [
            meeting
            for meeting in self.store.read_all()
            if meeting.get("status") in active_statuses
        ]

    def get_recent_meetings(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get recent completed meetings."""
        completed_meetings = [
            meeting
            for meeting in self.store.read_all()
            if meeting.get("status") == MeetingStatus.COMPLETED
        ]
        return sorted(
            completed_meetings,
            key=lambda x: x.get("end_time") or datetime.min,
            reverse=True,
        )[:limit]

    def get_meeting(self, meeting_id: str) -> Optional[Dict[str, Any]]:
        """Get a specific meeting by ID."""
        return self.store.read_one(meeting_id)

    def update_meeting(
        self, meeting_id: str, updates: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """Update a meeting."""
        updates["updated_at"] = datetime.utcnow()
        return self.store.update(meeting_id, updates)

    def delete_meeting(self, meeting_id: str) -> bool:
        """Delete a meeting."""
        return self.store.delete(meeting_id)

    def get_user_meetings(self, user_id: str) -> List[Dict[str, Any]]:
        """Get all meetings for a specific user (as participant or facilitator)."""
        return [
            meeting
            for meeting in self.store.read_all()
            if user_id in meeting.get("participants", [])
            or meeting.get("owner_id") == user_id
            or user_id in meeting.get("facilitator_user_ids", [])
        ]
