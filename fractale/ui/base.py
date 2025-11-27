from typing import Any, Optional, Protocol


class UserInterface(Protocol):
    """
    The strict contract that ManagerAgent relies on.
    Any implementation (Web, TUI, CLI) must provide these methods.
    """

    def on_step_start(self, name: str, description: str, inputs: dict):
        """
        Onset of a new step.
        """
        pass

    def on_log(self, message: str, level: str = "info"):
        """
        Let there be logs.
        """
        pass

    def log(self, message: str, level: str = "info"):
        self.on_log(message, level)

    def on_step_finish(self, name: str, result: str, error: Optional[str], metadata: dict):
        """
        A step completes (success or failure).
        """
        pass

    def on_workflow_complete(self, status: str):
        """
        The whole plan finishes.
        """
        pass

    # --- INPUT (Blocking) ---
    def ask_user(self, question: str, options: list[str] = None) -> str:
        """
        The Manager pauses until the user answers (blocking)
        """
        pass
