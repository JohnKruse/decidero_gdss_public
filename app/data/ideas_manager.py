from sqlalchemy.orm import Session, joinedload
from typing import Dict, List, Any, Optional
from datetime import datetime

from ..models.idea import Idea
from ..models.meeting import Meeting  # Needed to check meeting exists
from ..models.user import User  # Needed to check user exists

# Note: Removed imports for os, BaseManager, meeting_manager, encryption_manager


class IdeasManager:
    """Manages brainstorming ideas using SQLAlchemy."""

    def add_idea(
        self,
        db: Session,
        meeting_id: str,
        user_id: Optional[str],
        idea_data: Dict[str, Any],
        *,
        activity_id: Optional[str] = None,
        force_anonymous_name: bool = False,
        commit: bool = True,
    ) -> Optional[Idea]:
        """Add a new idea to a meeting's brainstorming session."""
        try:
            meeting = db.query(Meeting).filter(Meeting.meeting_id == meeting_id).first()
            if not meeting:
                print(f"Meeting with ID {meeting_id} not found.")
                return None

            user: Optional[User] = None
            if user_id:
                user = db.query(User).filter(User.user_id == user_id).first()
                if not user:
                    print(f"User with ID {user_id} not found.")
                    return None

            content = (idea_data.get("content") or "").strip()
            if not content:
                print("Idea content cannot be empty.")
                return None

            submitted_name = idea_data.get("submitted_name")
            if submitted_name:
                submitted_name = submitted_name.strip()
            if force_anonymous_name:
                submitted_name = "Anonymous"
            elif not submitted_name and user:
                submitted_name = (
                    " ".join(part for part in [user.first_name, user.last_name] if part)
                    or user.login
                )

            parent_id = idea_data.get("parent_id")
            metadata = idea_data.get("metadata") or {}

            db_idea = Idea(
                content=content,
                meeting_id=meeting.meeting_id,
                activity_id=activity_id,
                user_id=user.user_id if user else None,
                submitted_name=submitted_name,
                parent_id=parent_id,
                idea_metadata=metadata,
            )

            db.add(db_idea)
            if commit:
                db.commit()
            else:
                db.flush()
            db.refresh(db_idea)
            print(
                f"Successfully added idea (ID: {db_idea.id}) to meeting ID: {meeting_id}"
            )
            return db_idea
        except Exception as e:
            db.rollback()
            print(f"Error adding idea to meeting {meeting_id}: {str(e)}")
            return None

    def get_ideas_for_activity(
        self, db: Session, meeting_id: str, activity_id: Optional[str] = None
    ) -> List[Idea]:
        """Get all ideas for a specific activity within a meeting."""
        try:
            query = db.query(Idea).filter(Idea.meeting_id == meeting_id)
            query = query.options(joinedload(Idea.author))
            if activity_id:
                query = query.filter(Idea.activity_id == activity_id)
            else:
                query = query.filter(Idea.activity_id.is_(None))
            return query.order_by(Idea.timestamp).all()
        except Exception as e:
            print(
                f"Error getting ideas for meeting {meeting_id}, activity {activity_id}: {str(e)}"
            )
            return []

    def get_ideas_for_meeting(self, db: Session, meeting_id: str) -> List[Idea]:
        """Get all ideas for a meeting regardless of activity."""
        try:
            return (
                db.query(Idea)
                .filter(Idea.meeting_id == meeting_id)
                .order_by(Idea.timestamp)
                .all()
            )
        except Exception as e:
            print(f"Error getting ideas for meeting {meeting_id}: {str(e)}")
            return []

    def count_ideas_for_user(
        self,
        db: Session,
        meeting_id: str,
        user_id: str,
        activity_id: Optional[str] = None,
    ) -> int:
        """Count how many ideas a user has submitted for an activity."""
        try:
            query = db.query(Idea).filter(
                Idea.meeting_id == meeting_id, Idea.user_id == user_id
            )
            if activity_id:
                query = query.filter(Idea.activity_id == activity_id)
            return query.count()
        except Exception as e:
            print(
                f"Error counting ideas for meeting {meeting_id} and user {user_id}: {str(e)}"
            )
            return 0

    def get_idea(self, db: Session, idea_id: int) -> Optional[Idea]:
        """Get a specific idea by its ID."""
        try:
            return db.query(Idea).filter(Idea.id == idea_id).first()
        except Exception as e:
            print(f"Error getting idea ID {idea_id}: {str(e)}")
            return None

    def update_idea(
        self, db: Session, idea_id: int, updated_data: Dict[str, Any]
    ) -> Optional[Idea]:
        """Update an existing idea's content."""
        try:
            db_idea = self.get_idea(db, idea_id)
            if not db_idea:
                print(f"Idea ID {idea_id} not found for update.")
                return None

            update_occurred = False
            # Only update allowed fields, e.g., content
            if "content" in updated_data and updated_data["content"] is not None:
                db_idea.content = updated_data["content"]
                # updated_at is handled by onupdate
                update_occurred = True
            if "metadata" in updated_data and updated_data["metadata"] is not None:
                db_idea.idea_metadata = updated_data["metadata"]
                update_occurred = True

            if update_occurred:
                db.add(db_idea)
                db.commit()
                db.refresh(db_idea)
                print(f"Successfully updated idea ID: {db_idea.id}")
            else:
                print(f"No relevant updates provided for idea ID: {db_idea.id}")

            return db_idea
        except Exception as e:
            db.rollback()
            print(f"Error updating idea ID {idea_id}: {str(e)}")
            return None

    def delete_idea(self, db: Session, idea_id: int) -> bool:
        """Delete an idea."""
        try:
            db_idea = self.get_idea(db, idea_id)
            if not db_idea:
                print(f"Idea ID {idea_id} not found for deletion.")
                return False

            db.delete(db_idea)
            db.commit()
            print(f"Successfully deleted idea ID: {idea_id}")
            return True
        except Exception as e:
            db.rollback()
            print(f"Error deleting idea ID {idea_id}: {str(e)}")
            return False


# Note: Removed the singleton instance creation
