import logging

import fractale.core.plan.schema as schema
import fractale.utils as utils
from fractale.core.plan.step import Step

logger = logging.getLogger(__name__)


class Plan:
    """
    A plan describes a state machine or orchestration.

    It was intended for the native design, but we can also use it for other
    orchestrators (TBA).
    """

    def __init__(self, plan_path_or_dict):
        if isinstance(plan_path_or_dict, dict):
            self.raw_data = plan_path_or_dict
            self.plan_path = "memory"
        else:
            self.plan_path = plan_path_or_dict
            self.raw_data = utils.read_yaml(self.plan_path)

        self.validate_schema()

        # YAML List -> state graph
        self.states = self.do_compile(self.raw_data.get("steps", []))

    def validate_schema(self):
        return schema.validate_plan(self.raw_data)

    def do_compile(self, raw_steps):
        """
        Converts the list into a State Machine Config.
        """
        compiled = {}
        step_names = [s["name"] for s in raw_steps]

        # Add Terminal States
        compiled["success"] = Step({"name": "success", "type": "final"})
        compiled["failed"] = Step({"name": "failed", "type": "final"})

        for i, step_data in enumerate(raw_steps):
            name = step_data["name"]

            # If no transitions defined, assume linear flow (e.g., MuMMI)
            if "transitions" not in step_data:
                next_node = step_names[i + 1] if (i + 1 < len(step_names)) else "success"
                step_data["transitions"] = {"success": next_node, "failure": "failed"}

            # Mark initial state (0)
            if i == 0:
                step_data["initial"] = True

            compiled[name] = Step(step_data)

        return compiled

    @property
    def initial_state(self):
        """
        Find the state marked initial, or the first one defined
        """
        for s in self.states.values():
            if getattr(s, "initial", False):
                return s.name
        return list(self.states.keys())[0] if self.states else None

    @property
    def global_inputs(self):
        return self.raw_data.get("inputs", {})
