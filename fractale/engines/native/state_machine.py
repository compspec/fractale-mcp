import json
import logging

from rich import print

import fractale.utils as utils

logger = logging.getLogger(__name__)


class WorkflowStateMachine:
    """
    Dynamic State Machine execution engine.
    """

    def __init__(self, states, context, callbacks, ui=None):
        self.states = states
        self.context = context
        self.ui = ui

        # This is manager.run_agent and manager.run_tool
        self.current_state_name = None
        self.callbacks = callbacks
        self.set_initial_state()

    def set_initial_state(self):
        """
        Set the initial state based on finding "initial"
        """
        for s in self.states.values():
            if s.get("initial"):
                self.current_state_name = s.name
                break

        if not self.current_state_name:
            # Fallback to first key that isn't a terminal
            keys = [k for k, v in self.states.items() if v.type != "final"]
            self.current_state_name = keys[0] if keys else "failed"

    def run_cycle(self):
        """
        Executes ONE state and determines the next state.

        Returns: (step_metadata, is_finished)
        """
        current_step = self.states[self.current_state_name]

        # Are we terminal? That sounds dark...
        if current_step.type == "final":
            print("Current step is final, returning finished")
            return None, True

        # Execute via callback function
        print(f"Step type: {current_step.type}")
        runner = self.callbacks.get(current_step.type)
        if not runner:
            raise ValueError(f"No runner for type '{current_step.type}'")

        # Merge into temp context for execution
        step_inputs = utils.resolve_templates(current_step.spec.get("inputs", {}), self.context)
        exec_context = self.context.copy()
        exec_context.update(step_inputs)
        result, error, meta = runner(current_step, exec_context)

        # Ensure any rendering (jinja2) is carried forward to inputs
        self.update_context(current_step.name, result, error)

        # Save previous result and last error in context
        if error:
            print(error)

        # Determine Transition
        outcome = "success" if (result and not error) else "failure"
        next_state = current_step.transitions.get(outcome)

        # If explicit transition missing, default to failed
        if not next_state and outcome == "success":
            next_state = "success"
        elif not next_state and outcome == "failure":
            next_state = "failed"
        print(f"next state is {next_state}")

        logger.info(f"🔀 Transition: {current_step.name} ({outcome}) -> {next_state}")
        prev_state_name = self.current_state_name
        self.current_state_name = next_state

        return {
            "agent": prev_state_name,
            "result": result,
            "error": error,
            "metadata": meta,
            "transition": f"{outcome} -> {next_state}",
        }, False

    def update_context(self, step_name, result, error):
        """
        Parses results and updates the context.
        E.g., render {{ result.field }} access in Jinja2.
        """
        if error:
            self.context["_last_error"] = error

        if result is not None:
            self.context["_previous_result"] = result

            parsed_data = result
            if isinstance(result, str):
                try:
                    parsed_data = json.loads(result)
                except Exception:
                    parsed_data = result

            # 3. Update 'result' (The transient variable for the next step)
            self.context["result"] = parsed_data
            self.context[f"{step_name}_result"] = parsed_data

    def ask_next_step(self, step_meta):
        """
        Ask the user what to do next.
        """
        if step_meta and "failure" in step_meta.get("transition", ""):
            if self.current_state_name == "failed":
                if self.ui:
                    action = self.ui.ask_user(
                        f"Workflow Failed at '{step_meta['agent']}'.\nError: {step_meta['error']}\nRetry?",
                        options=["retry", "quit"],
                    )
                    if action == "retry":
                        self.current_state_name = step_meta["agent"]
                        logger.warning(
                            f"🔄 User requested retry. Rewinding to {step_meta['agent']}"
                        )
                    return action
