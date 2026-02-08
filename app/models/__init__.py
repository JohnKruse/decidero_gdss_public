# Import models to make them accessible via app.models
# and ensure they are registered with SQLAlchemy's Base metadata
from .user import User
from .meeting import (
    Meeting,
    MeetingFacilitator,
    participants_table,
    ToolConfig,
    Agenda,
    AgendaActivity,
)
from .idea import Idea
from .voting import VotingVote
from .activity_bundle import ActivityBundle

# You can optionally define __all__ to control what `from app.models import *` imports
__all__ = [
    "User",
    "Meeting",
    "MeetingFacilitator",
    "participants_table",
    "ToolConfig",
    "Idea",
    "Agenda",
    "AgendaActivity",
    "VotingVote",
    "ActivityBundle",
]
