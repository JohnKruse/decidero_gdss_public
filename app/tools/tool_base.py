from abc import ABC, abstractmethod
from typing import Dict, Any


class Tool(ABC):
    """
    Abstract base class for all collaborative tools.

    This class defines the common interface and basic functionality that all tools must implement.
    Each specific tool (e.g., Brainstorming, Voting) will inherit from this class and provide
    its own implementation of the execute method.
    """

    def __init__(self, name: str, order: int, settings: Dict[str, Any]):
        """
        Initialize a new Tool instance.

        Args:
            name (str): The name of the tool (e.g., "Brainstorming")
            order (int): The position of the tool in the process sequence
            settings (dict): Configuration settings specific to the tool
        """
        self.name = name
        self.order = order
        self.settings = settings

    @abstractmethod
    def execute(self, session_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute the tool's main functionality.

        This method must be implemented by all concrete tool classes.

        Args:
            session_data (Dict[str, Any]): The current session data containing all necessary
                                         information for the tool to operate

        Returns:
            Dict[str, Any]: Updated session data after tool execution
        """
        pass

    def configure(self, settings: Dict[str, Any]) -> None:
        """
        Update the tool's settings.

        Args:
            settings (Dict[str, Any]): New settings to update or add to the tool's configuration
        """
        self.settings.update(settings)
