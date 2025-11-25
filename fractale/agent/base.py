import copy
import os
import time
from typing import Any, Dict

from fractale.logger import logger


class Agent:
    """
    Base Agent infrastructure.
    """

    def __init__(
        self,
        name: str = "agent",
        results_dir: str = None,
        save_incremental: bool = False,
        max_attempts: int = None,
    ):
        self.name = name
        self.attempts = 0
        self.max_attempts = max_attempts

        self.results_dir = results_dir or os.getcwd()
        self.save_incremental = save_incremental
        self.init_metadata()

        # Called by subclass for its specific setup
        self.init()

    def init(self):
        """
        Init operations, intended to override in subclass.
        """
        pass

    def init_metadata(self):
        self.metadata = {
            "name": self.name,
            "times": {},
            "assets": {},
            "failures": [],
            # TODO: likely we want to replace this with the metadata registry.
            "counts": {"retries": 0, "return_to_manager": 0, "return_to_human": 0},
            "llm_usage": [],
        }

    def run(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Main execution wrapper
        """
        # Ensure max_attempts is set
        context["max_attempts"] = self.max_attempts or context.get("max_attempts")

        # 3. RUN STEP
        logger.info(f"▶️  Running {self.name}...")
        start_time = time.time()

        try:
            # Call abstract method
            context = self.run_step(context)

        finally:
            duration = time.time() - start_time
            self.metadata["times"]["execution"] = duration

        return context

    def run_step(self, context):
        """
        Abstract: Implemented by MCPAgent
        """
        raise NotImplementedError(f"Agent {self.name} missing run_step")

    def reset_context(self, context):
        """
        Clears output variables to prepare for a retry.
        """
        # Convert to dict if it's a Context object
        is_obj = hasattr(context, "data")
        data = context.data if is_obj else context

        # Clear state variables
        for key in self.state_variables:
            if key in data:
                del data[key]

        # Archive current metadata into failures list
        if "failures" not in self.metadata:
            self.metadata["failures"] = []

        # Snapshot current metadata
        self.metadata["failures"].append(copy.deepcopy(self.metadata))

        # Reset current counters (keep retries count consistent)
        current_retries = self.metadata["counts"]["retries"]
        self.init_metadata()
        self.metadata["counts"]["retries"] = current_retries
        return context

    def reached_max_attempts(self):
        """
        Return true if we have reached maximum number of attempts.
        """
        if not self.max_attempts:
            return False
        return self.attempts >= self.max_attempts
