from uuid import uuid4
from datetime import datetime, UTC
from typing import Dict, Any, List
import logging

from app.tools.tool_base import Tool
from app.data import ideas_manager, meeting_manager

# Set up logging
logging.basicConfig(level=logging.DEBUG)


class BrainstormingTool(Tool):
    def __init__(self):
        super().__init__(
            name="Brainstorming",
            order=1,
            settings={
                "idea_character_limit": 500,  # Maximum characters per idea
                "max_ideas_per_user": 50,  # Maximum ideas per user per meeting
            },
        )

    def execute(self, session_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute the brainstorming session.

        Args:
            session_data (Dict[str, Any]): Current session data including meeting_id

        Returns:
            Dict[str, Any]: Updated session data with brainstorming results
        """
        meeting_id = session_data.get("meeting_id")
        if not meeting_id:
            raise ValueError("Meeting ID is required")

        # Get all ideas for the meeting
        ideas = ideas_manager.get_ideas(meeting_id)

        # Update session data with ideas
        session_data["ideas"] = ideas
        return session_data

    def submit_idea(
        self, meeting_id: str, user_id: str, idea_text: str
    ) -> Dict[str, Any]:
        """
        Submit a new idea to the brainstorming session.
        Ideas inherit encryption from their parent meeting.
        """
        try:
            # Validate idea text
            if not idea_text.strip():
                raise ValueError("Idea text cannot be empty")

            if len(idea_text) > self.settings["idea_character_limit"]:
                raise ValueError(
                    f"Idea text exceeds character limit of {self.settings['idea_character_limit']}"
                )

            # Verify meeting exists
            meeting = meeting_manager.get_meeting(meeting_id)
            if not meeting:
                raise ValueError("Meeting not found")

            # Check if meeting is active
            if meeting.get("status") != "active":
                raise ValueError("Cannot add ideas to non-active meetings")

            # Create idea with metadata
            idea = {
                "idea_id": str(uuid4()),
                "author_id": user_id,
                "idea_text": idea_text,
                "timestamp": datetime.now(UTC).isoformat(),
                "meeting_id": meeting_id,
            }

            logging.debug(f"Adding idea to meeting {meeting_id}: {idea}")

            # Add idea (encryption handled automatically based on meeting settings)
            success = ideas_manager.add_idea(meeting_id, idea)

            if not success:
                raise Exception("Failed to save idea")

            logging.debug(f"Successfully added idea {idea['idea_id']}")
            return idea

        except ValueError as e:
            logging.error(f"Validation error submitting idea: {str(e)}")
            raise
        except Exception as e:
            logging.error(f"Error submitting idea: {str(e)}")
            raise

    def get_ideas(self, meeting_id: str) -> List[Dict[str, Any]]:
        """
        Get all ideas for a meeting.
        Handles decryption automatically if meeting is encrypted.
        """
        try:
            # Verify meeting exists
            meeting = meeting_manager.get_meeting(meeting_id)
            if not meeting:
                raise ValueError("Meeting not found")

            # Get ideas (decryption handled automatically)
            ideas = ideas_manager.get_ideas(meeting_id)

            logging.debug(f"Retrieved {len(ideas)} ideas for meeting {meeting_id}")
            return ideas

        except Exception as e:
            logging.error(f"Error retrieving ideas: {str(e)}")
            raise

    def update_idea(
        self, meeting_id: str, idea_id: str, user_id: str, updated_text: str
    ) -> bool:
        """
        Update an existing idea.
        Only the original author can update their idea.
        """
        try:
            # Validate updated text
            if not updated_text.strip():
                raise ValueError("Idea text cannot be empty")

            if len(updated_text) > self.settings["idea_character_limit"]:
                raise ValueError(
                    f"Idea text exceeds character limit of {self.settings['idea_character_limit']}"
                )

            # Get existing ideas
            ideas = self.get_ideas(meeting_id)

            # Find the idea to update
            idea = next((i for i in ideas if i["idea_id"] == idea_id), None)
            if not idea:
                raise ValueError("Idea not found")

            # Verify ownership
            if idea["author_id"] != user_id:
                raise ValueError("Can only update your own ideas")

            # Update the idea
            updated_data = {
                "idea_text": updated_text,
                "updated_at": datetime.now(UTC).isoformat(),
            }

            success = ideas_manager.update_idea(meeting_id, idea_id, updated_data)

            if not success:
                raise Exception("Failed to update idea")

            logging.debug(f"Successfully updated idea {idea_id}")
            return True

        except Exception as e:
            logging.error(f"Error updating idea: {str(e)}")
            raise

    def delete_idea(self, meeting_id: str, idea_id: str, user_id: str) -> bool:
        """
        Delete an idea.
        Only the original author or meeting facilitator can delete an idea.
        """
        try:
            # Get meeting to check facilitator
            meeting = meeting_manager.get_meeting(meeting_id)
            if not meeting:
                raise ValueError("Meeting not found")

            # Get existing ideas
            ideas = self.get_ideas(meeting_id)

            # Find the idea to delete
            idea = next((i for i in ideas if i["idea_id"] == idea_id), None)
            if not idea:
                raise ValueError("Idea not found")

            # Verify permission to delete
            is_facilitator = meeting["facilitator"] == user_id
            is_author = idea["author_id"] == user_id

            if not (is_facilitator or is_author):
                raise ValueError("Can only delete your own ideas or as facilitator")

            success = ideas_manager.delete_idea(meeting_id, idea_id)

            if not success:
                raise Exception("Failed to delete idea")

            logging.debug(f"Successfully deleted idea {idea_id}")
            return True

        except Exception as e:
            logging.error(f"Error deleting idea: {str(e)}")
            raise


# Create singleton instance
brainstorming_tool = BrainstormingTool()
