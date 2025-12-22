from abc import ABC, abstractmethod
from typing import Any, Dict

from fractale.plan import Plan
from fractale.ui.base import UserInterface


class WorkflowEngine(ABC):
    """
    Abstract Base Class for any backend that can execute a Fractale Plan.
    """

    def __init__(self, plan: Plan, client: "FastMCPClient", ui: UserInterface = None):
        self.plan = plan
        self.client = client  # Access to MCP tools
        self.ui = ui

    @abstractmethod
    async def run(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute the plan.
        Returns the final context/results.
        """
        pass
